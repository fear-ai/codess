"""session-ingest CLI command."""

import argparse
import json
import logging
import sys
import tempfile
import time
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from types import MappingProxyType
from typing import Any

from codess import reporting
from codess.codex_source import build_session_index as build_codex_session_index
from codess.config import (
    CC_PROJECTS,
    CODEX_SESSIONS,
    CURSOR_DATA,
    LAST_INGEST_REPORT_FILE,
    SOURCE_CHOICES,
    STORE_DIR,
    VENDOR_KEYS,
    get_state_path,
    get_store_path,
    validate_config,
)
from codess.content_processing import ContentPolicy, ContentProcessor
from codess.cursor_cohort import (
    CursorSelection,
    cohort_needed,
    prepare_cursor_cohort,
    resolve_selection_markers,
)
from codess.cursor_source import (
    get_global_db as get_cursor_global_db,
)
from codess.cursor_source import (
    get_project_composer_headers as get_cursor_project_composer_headers,
)
from codess.cursor_source import (
    get_selection_markers as get_cursor_selection_markers,
)
from codess.cursor_source import (
    get_sqlite_container_marker as get_cursor_container_marker,
)
from codess.cursor_source import (
    get_workspace_dbs as get_cursor_workspace_dbs,
)
from codess.cursor_source import (
    get_workspace_ids as get_cursor_workspace_ids,
)
from codess.evidence import summarize_store_evidence
from codess.fileio import write_json_atomic
from codess.ingest_publication import (
    VENDOR_DISPLAY_NAMES,
    PublicationOutcome,
    correlate_project_artifacts,
    current_snapshot_id,
    current_snapshot_is_sealed,
    promote_rebuilt_stores,
    publish_snapshot,
    record_content_processing,
    resync_project_catalog,
)
from codess.ingest_sources import (
    _ingest_cc,
    _ingest_codex,
    _ingest_cursor,
)
from codess.processing_contract import DECODER_VERSION, VALIDATOR_VERSION
from codess.project import (
    RootsWhenEmpty,
    build_ingest_run_options,
    get_cc_session_dir,
    resolve_cli_roots,
)
from codess.project_catalog import (
    ensure_project_binding,
    get_project_entry,
    read_project_binding,
)
from codess.raw_store import RawStore
from codess.reporting import ProgressEmitter
from codess.reporting import emit_named as progress_emit
from codess.reporting.levels import resolve as resolve_profile
from codess.reporting.privacy import Roots
from codess.reporting.sinks import CollectorSink, HumanSink
from codess.resource_policy import ResourcePolicyError
from codess.resources import (
    peak_rss_bytes,
    summarize_project_resources,
)
from codess.snapshot import current_raw_records
from codess.store import (
    SOURCE_PROFILES,
    connect,
    init_db,
    integrity_report,
    sync_project_catalog,
    table_counts,
)

log = logging.getLogger(__name__)


def _resource_limits_report(settings: dict[str, Any]) -> dict:
    """Return effective limits with one compatibility spelling retained."""
    return {
        "max_transcript_bytes": settings["max_source_bytes"],
        "max_source_bytes": settings["max_source_bytes"],
        "max_cursor_container_bytes": settings["max_cursor_container_bytes"],
        "max_events_per_source": settings["max_events_per_source"],
        "max_events_per_session": settings["max_events_per_session"],
        "max_context_content_chars": settings["max_context_content_chars"],
    }


























def _save_stats(project_path: Path, store_root: Path, source_stats: dict) -> None:
    """Merge ingest store stats into registry (preserves ``scan`` / ``query`` / etc.)."""
    from codess.registry_store import merge_ingest_sources, update_project_entry

    proj_str = str(project_path.resolve())
    update_project_entry(
        store_root, proj_str,
        partial(merge_ingest_sources, source_stats=source_stats),
    )


def _write_runtime_report(project_path: Path, report: dict) -> None:
    path = project_path / STORE_DIR / LAST_INGEST_REPORT_FILE
    write_json_atomic(path, report)


def _load_runtime_report(project_path: Path) -> dict:
    path = project_path / STORE_DIR / LAST_INGEST_REPORT_FILE
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _evidence_summary(paths: list[Path]) -> dict:
    return summarize_store_evidence(paths)

PROJECT_SCOPED_OPTIONS = (
    "project_id",
    "location_id",
    "content_actions",
    "raw_records",
    "raw_store",
    "raw_records_changed",
    "external_sources",
)
"""Keys of `opts` that belong to one Project rather than to the whole run."""


@dataclass
class ProjectScope:
    """The per-Project half of `opts`, as a value rather than seven keys.

    `opts` carries three lifetimes in one dict -- run-wide settings mirrored
    from the resolved options, run-wide collectors that accumulate across
    Projects, and these seven, which are replaced on every loop iteration. A
    reader at a call site could not tell which kind a key was, so
    `opts["raw_store"]` read the same whether it was configuration or this
    iteration's store.

    Naming the per-Project set makes the boundary checkable: `into` is the one
    place these reach `opts`, and a key added here without being added to
    `PROJECT_SCOPED_OPTIONS` fails rather than silently persisting into the
    next Project. The dict itself stays, because the adapters take it as their
    diagnostics sink and changing that is a separate decision.
    """

    project_id: str
    location_id: str
    raw_records: list[dict]
    raw_store: "RawStore | None"
    content_actions: list = field(default_factory=list)
    external_sources: list = field(default_factory=list)
    raw_records_changed: bool = False

    def into(self, opts: dict) -> None:
        """Replace the per-Project keys of `opts` with this Project's.

        Every key is written, never merged: a stale `raw_store` or a
        carried-over `content_actions` would attribute one Project's evidence
        to the next, and a partial reset is the way that happens.
        """
        fresh = {
            "project_id": self.project_id,
            "location_id": self.location_id,
            "content_actions": self.content_actions,
            "raw_records": self.raw_records,
            "raw_store": self.raw_store,
            "raw_records_changed": self.raw_records_changed,
            "external_sources": self.external_sources,
        }
        missing = set(PROJECT_SCOPED_OPTIONS) - set(fresh)
        if missing:
            raise KeyError(
                f"per-Project options not reset: {', '.join(sorted(missing))}"
            )
        opts.update({key: fresh[key] for key in PROJECT_SCOPED_OPTIONS})


@dataclass
class IngestTally:
    """Sessions ingested, events processed, and errors, at one scale.

    The same three quantities are counted per Project and per run, so this is
    one type used twice rather than two parallel sets of variables. Mutable
    and passed by reference: a phase updates the tally it was handed instead
    of returning numbers a caller must remember to add, which is what let the
    counters drift apart when they were plain locals.
    """

    sessions: int = 0
    events: int = 0
    errors: int = 0

    def add(self, *, sessions: int = 0, events: int = 0, errors: int = 0) -> None:
        """Record work completed at this scale."""
        self.sessions += sessions
        self.events += events
        self.errors += errors

    def note_error(self) -> None:
        """Record one failure. Named so call sites read as intent, not arithmetic."""
        self.errors += 1

    def absorb(self, other: "IngestTally") -> None:
        """Fold a finished tally from a narrower scope into this one."""
        self.add(sessions=other.sessions, events=other.events, errors=other.errors)

    @property
    def failed(self) -> bool:
        return self.errors > 0

    @property
    def status(self) -> str:
        """Outcome as reported. Derived so it cannot disagree with the count."""
        return "failed" if self.errors else "accepted"


@dataclass
class ProjectOutcome:
    """What one Project's ingest produced.

    Holds the Project's own tally plus the per-vendor facts a report needs.
    Deliberately has no reference to the run: a Project reports upward once,
    when it finishes, so a Project that fails partway cannot leave run totals
    counting work that was rolled back.
    """

    tally: IngestTally = field(default_factory=IngestTally)
    store_totals: dict[str, dict] = field(default_factory=dict)
    changed_vendors: set[str] = field(default_factory=set)
    catalog_changed_vendors: set[str] = field(default_factory=set)

    def record_vendor(
        self,
        display: str,
        *,
        sessions: int,
        events: int,
        failed_sources: int,
        store_changed: bool,
    ) -> None:
        """Record one vendor's contribution to this Project.

        Replaces the six assignments each vendor block performed against
        enclosing variables. Because this object is handed to a caller rather
        than rebound by it, an extracted function can update it -- which a
        plain integer parameter cannot do.
        """
        self.tally.add(sessions=sessions, events=events, errors=failed_sources)
        if store_changed:
            self.changed_vendors.add(display)

    @property
    def status(self) -> str:
        """Per-Project outcome, which distinguishes partial success."""
        return "completed_with_errors" if self.tally.failed else "accepted"


@dataclass
class IngestOutcome:
    """What a whole ingest run produced.

    `absorb` is the only path from a Project to the run, so run totals change
    exactly once per Project and always after that Project's outcome is known.
    """

    tally: IngestTally = field(default_factory=IngestTally)
    source_stats: dict[str, dict] = field(default_factory=dict)

    def absorb(self, project: ProjectOutcome) -> None:
        """Fold one finished Project into the run."""
        self.tally.absorb(project.tally)

    @property
    def overall_sessions(self) -> int:
        """Sessions now stored, across every vendor. Derived, not accumulated."""
        return sum(stats["sessions"] for stats in self.source_stats.values())

    @property
    def overall_events(self) -> int:
        return sum(stats["events"] for stats in self.source_stats.values())


@dataclass
class RunTotals:
    """What accumulates across Projects, in one place.

    `IngestConfig` holds what a run was configured to do and does not change;
    this holds what the run has produced so far and changes constantly. The
    two together are the read-only and mutable halves of ingest state, which
    the phase functions previously took as separate parameters -- five
    accumulators and twelve inputs, seventeen in all, where a call site could
    silently mis-order them.

    Every field here is mutated in place by whichever phase is running, which
    is why they are passed as one object rather than returned: a Project
    folds into `outcome` in a `finally`, so a Project that fails partway
    still reports exactly once.
    """

    outcome: "IngestOutcome"
    diagnostics: dict[str, int]
    opts: dict


@dataclass(frozen=True)
class IngestConfig:
    """Resolved, unchanging settings for one ingest run.

    Everything here is decided before the first Project is touched and is the
    same for all of them. Per-Project state does not belong here; mixing the
    two is what makes the neighbouring `opts` dict hard to read, since a call
    site cannot tell whether a key is a run input or the current iteration's
    value.

    **What frozen does and does not cover.** `frozen=True` prevents rebinding
    this object's fields -- `config.sources = ...` raises. It does not make
    the values themselves immutable, and Python offers no general way to do
    so. `options` is therefore held as a read-only view over a *copy*, so
    `config["force"] = ...` raises too and a later edit to the caller's dict
    is not observed here. What remains unguarded is nested values:
    `config["resource_policy"]` returns a real dict. Closing that would need a
    deep freeze, which costs more than it is worth for values nothing writes.
    The guarantee is "no accidental rewrite through this object", not an
    immutable object graph.

    **Why `options` stays a mapping.** Its keys are already contract-
    documented on `build_ingest_run_options`; restating them as fields would
    create a second definition to maintain, and every addition would need
    edits in two files. Access is by key, with named properties added only
    where a value has behavior worth naming, as `validate_only` does.
    """

    options: Mapping[str, Any]
    sources: tuple[str, ...]
    store_root: Path
    staging_root: Path | None = None
    staged_store_roots: MutableMapping[Path, Path] = field(default_factory=dict)

    def __getitem__(self, key: str) -> Any:
        return self.options[key]

    @property
    def validate_only(self) -> bool:
        return bool(self.options["validate_only"])

    @classmethod
    def from_options(
        cls,
        options: Mapping[str, Any],
        sources: Sequence[str],
        store_root: Path,
        *,
        staging_root: Path | None = None,
        staged_store_roots: MutableMapping[Path, Path] | None = None,
    ) -> "IngestConfig":
        """Build a run configuration, copying the settings it owns.

        `options` is copied and then wrapped: a view over a dict the caller
        still holds would report that caller's later edits, which is the
        aliasing this type exists to prevent.

        `staged_store_roots` is deliberately *not* copied. A rebuild registers
        a Project's staging location partway through a run and removes it on
        promotion, so this one mapping is live shared state rather than a
        setting. It is typed `MutableMapping` so that exception is visible
        rather than implied.
        """
        return cls(
            options=MappingProxyType(dict(options)),
            sources=tuple(sources),
            store_root=store_root,
            staging_root=staging_root,
            staged_store_roots=(
                staged_store_roots if staged_store_roots is not None else {}
            ),
        )

    def vendor_store(self, project_path: Path, src: str) -> "VendorStore":
        """Name one vendor's store for a Project under this run.

        Returns a handle rather than a path so a caller can locate, create,
        and measure the same store without re-deriving the run's staging
        arrangement or the vendor's display name at each step.
        """
        return VendorStore(config=self, project_path=project_path, source_key=src)

    def store_path(self, project_path: Path, src: str) -> Path:
        """Where one vendor's store lives. Shorthand for `vendor_store(...).path`."""
        return self.vendor_store(project_path, src).path


@dataclass(frozen=True)
class VendorStore:
    """One vendor's CoSchema store for one Project under one run.

    Locating, creating, and measuring a store were three free functions that
    each re-derived the same two facts: where the store lives given the run's
    staging arrangement, and what the vendor is called in a report. Binding
    them to one object removes both duplications and gives the vendor display
    name a single owner.

    Frozen because a store's identity -- which Project, which vendor, which
    run -- does not change once chosen. The database it names is of course
    written to; that is the file, not this handle.
    """

    config: IngestConfig
    project_path: Path
    source_key: str

    @property
    def display_name(self) -> str:
        """The vendor's name as it appears in catalogs and reports."""
        return VENDOR_DISPLAY_NAMES[self.source_key]

    @property
    def path(self) -> Path:
        """Where this store lives, honouring preflight and rebuild staging.

        Preflight redirects every Project into a private staging tree so a
        validate-only run cannot touch real data. A rebuild redirects one
        Project to its staged replacement until promotion. Both redirections
        read the same registered mapping, so a Project's stores and its
        ingest state resolve to one directory.

        Preflight previously derived its own directory by hashing the Project
        path here, while the Project loop derived the state path from the
        loop index -- two answers to one question, which put a Project's
        stores and its state in different staging directories. Nothing failed,
        because preflight discards both and always runs with `force`, so the
        state was never read back.
        """
        project = self.config.staged_store_roots.get(
            self.project_path.resolve(), self.project_path,
        )
        return get_store_path(project, self.display_name)

    def exists(self) -> bool:
        return self.path.exists()

    def create(self, project_entry: dict) -> bool:
        """Initialize the store and sync its Project catalog entry.

        Returns whether the catalog entry changed, so a caller can record
        which vendors need republishing without inspecting the store again.
        """
        init_db(self.path)
        conn = connect(self.path)
        try:
            changed = bool(sync_project_catalog(conn, project_entry))
            conn.commit()
        finally:
            conn.close()
        return changed

    def totals(self) -> dict | None:
        """Count what the store now holds, or None if it does not exist.

        Read after ingest rather than accumulated during it, so the figure is
        what the store actually contains rather than what this run believed it
        wrote. A store that was never created reports nothing rather than a
        misleading zero.
        """
        if not self.exists():
            return None
        conn = connect(self.path)
        try:
            counts = table_counts(conn, ("sessions", "events"))
            return {
                "sessions": counts.get("sessions", 0),
                "events": counts.get("events", 0),
                "last_ingestion": datetime.now(UTC).isoformat(),
            }
        finally:
            conn.close()


def _current_raw_records_cached(
    project: Path, cache: dict[Path, list[dict]],
) -> list[dict]:
    """Read a Project's current raw records once per run."""
    resolved = project.resolve()
    if resolved not in cache:
        cache[resolved] = current_raw_records(resolved)
    return cache[resolved]


def _begin_project(
    opts: dict,
    binding: dict,
    *,
    raw_records: list[dict],
    raw_store: "RawStore | None",
) -> None:
    """Point the decoder options at one Project, clearing the previous one.

    Builds the per-Project state as a `ProjectScope` and writes it in one
    step, so the lifetime is a type a reader can see rather than seven keys
    they must recognize. Every key is replaced when the loop advances: a stale
    `raw_store` or a carried-over `content_actions` list would attribute one
    Project's evidence to the next.
    """
    ProjectScope(
        project_id=binding["project_id"],
        location_id=binding["location_id"],
        raw_records=raw_records,
        raw_store=raw_store,
    ).into(opts)


def _resolve_ingest_request(args: argparse.Namespace,
) -> int | tuple[list[Path], Path, list[str], dict]:
    """Validate configuration and arguments before any source is touched.

    Returns an exit code when the request cannot proceed, or the resolved
    (roots, registry root, sources, run settings) otherwise. Every rejection
    prints its own message, matching the command-layer contract that argument
    faults are reported here rather than raised into domain code.
    """
    config_errors = validate_config()
    for msg in config_errors:
        print(f"codess: {msg}", file=sys.stderr)
    if config_errors:
        return 1

    roots, err = resolve_cli_roots(args, when_empty=RootsWhenEmpty.PROJECT_ROOT)
    if err:
        print(err, file=sys.stderr)
        return 1

    from codess.project import resolve_store_root

    store_root = resolve_store_root(args)

    raw_src = getattr(args, "source", None) or "all"
    if "," in raw_src:
        print(
            "codess: ingest --source must be one token: cc | codex | cursor | all (not a comma list)",
            file=sys.stderr,
        )
        return 1
    source = raw_src.strip().lower()
    if source not in SOURCE_CHOICES:
        print(f"codess: invalid ingest --source: {raw_src!r}", file=sys.stderr)
        return 1
    sources = list(VENDOR_KEYS) if source == "all" else [source]

    try:
        settings = build_ingest_run_options(args)
    except ResourcePolicyError as exc:
        print(f"codess: invalid resource policy: {exc}", file=sys.stderr)
        return 1
    for name, value in (
        ("--max-source-bytes", settings["max_source_bytes"]),
        ("--max-cursor-container-bytes", settings["max_cursor_container_bytes"]),
        ("--max-events-per-source", settings["max_events_per_source"]),
        ("--max-events-per-session", settings["max_events_per_session"]),
        ("--max-context-content-chars", settings["max_context_content_chars"]),
    ):
        if value is not None and value <= 0:
            print(f"codess: {name} must be > 0", file=sys.stderr)
            return 1
    return roots, store_root, sources, settings


def _report_ingest_outcome(
    progress_trace: ProgressEmitter,
    opts: dict,
    diagnostics: dict[str, int],
    outcome: "IngestOutcome",
) -> None:
    """Render the completion summary. No state is read or changed here."""
    progress_trace(
        "ingest.done", sessions=outcome.tally.sessions, events=outcome.tally.events,
        errors=outcome.tally.errors,
        status="failed" if outcome.tally.errors else "accepted",
    )
    if opts.get("cursor_cohort"):
        cohort = opts["cursor_cohort"]
        elapsed = cohort.get("cohort_seconds", cohort.get("marker_seconds", 0))
        print(f"Cursor cohort: {cohort['status']} ({elapsed:.3f}s)")
    print(
        f"Processed: {outcome.tally.sessions} session(s), {outcome.tally.events} event(s) | "
        f"Stored: {outcome.overall_sessions} session(s), {outcome.overall_events} event(s)"
    )
    if any(diagnostics.values()):
        # Every counter that fired, rather than a fixed field list. The line
        # named eleven keys and nothing else, so a reason code added at the
        # decode boundary was counted and never printed -- and a zero for a
        # condition that cannot occur in this run reads the same as a zero for
        # one that can. Sorted so two runs are comparable line to line.
        print(
            "codess: ingest diagnostics: "
            + " ".join(
                f"{name}={count}"
                for name, count in sorted(diagnostics.items())
                if count
            ),
            file=sys.stderr,
        )


def _progress_events(project: str | None = None) -> list[dict]:
    """Retained progress events for a durable report, or none.

    Flushes first. Events batch in the ring until the profile's threshold, so a
    report written mid-run would omit whatever had not yet reached the collector
    -- and a short ingest finishes well inside a 256-event batch, which made the
    retained list empty rather than merely incomplete. Writing a durable report is
    a boundary in the same sense a command exit is.

    A profile with no collector attached is legitimate -- `benchmark` has none by
    design -- so this reports an empty list rather than raising. The report then
    says the run produced no retained events, which is true, instead of failing
    on the accessor.
    """
    reporting.flush()
    sink = reporting.collector()
    return sink.records_for(project) if sink is not None else []


def _print_preflight_report(
    settings: dict,
    roots: list,
    sources: list[str],
    staging_root,
    temporary,
    progress_trace: ProgressEmitter,
    opts: dict,
    *,
    diagnostics: dict[str, int],
    outcome: "IngestOutcome",
) -> None:
    """Render the validate-only report and discard the staging tree.

    Preflight writes nothing outside its temporary directory, so this is the
    only place its results are surfaced.
    """
    store_checks = []
    for path in sorted(staging_root.rglob("*.db")):
        conn = connect(path, read_only=True)
        try:
            counts = table_counts(conn, ("sessions", "events"))
            store_checks.append({
                "store": path.name,
                **integrity_report(conn),
                "sessions": counts.get("sessions", 0),
                "events": counts.get("events", 0),
            })
        finally:
            conn.close()
    progress_trace(
        "ingest.done", sessions=outcome.tally.sessions, events=outcome.tally.events,
        errors=outcome.tally.errors,
    status="failed" if outcome.tally.errors else "accepted",
    )
    report = {
        "report_format": "codess.ingest-preflight/1",
        "progress_format": "codess.progress/1",
        "progress_live": settings["live_progress"],
        "status": "rejected" if outcome.tally.errors else "accepted",
        "errors": outcome.tally.errors,
        "decoder_version": DECODER_VERSION,
        "validator_version": VALIDATOR_VERSION,
        "projects": [str(root.resolve()) for root in roots],
        "sources": outcome.source_stats,
        "sessions": outcome.tally.sessions,
        "events": outcome.tally.events,
        "diagnostics": diagnostics,
        "content_failure_reviews": opts["content_failure_reviews"],
        "resource_observations": opts["resource_observations"],
        "resource_summary": summarize_project_resources(
            opts["resource_observations"],
            normalized_store_paths=sorted(staging_root.rglob("*.db")),
        ),
        "progress_events": _progress_events(),
        "session_kinds": (
            {"Claude": opts["claude_session_kinds"]}
            if "Claude" in outcome.source_stats else {}
        ),
        "store_checks": store_checks,
        "evidence_summary": _evidence_summary(sorted(staging_root.rglob("*.db"))),
        "resource_policy": settings["resource_policy"],
        "limits": _resource_limits_report(settings),
        "mutation_boundary": "temporary stores only; project, registry, raw store, snapshots, and ingest state unchanged",
    }
    print(json.dumps(report, sort_keys=True))
    if temporary:
        temporary.cleanup()

def _publish_project(
    config: "IngestConfig",
    run_totals: "RunTotals",
    project_path: Path,
    project: ProjectOutcome,
    *,
    project_entry: dict,
    min_size: int,
    force: bool,
    seal_upgrade: bool,
    rebuild_had_existing_store: bool,
    progress_trace: ProgressEmitter,
) -> PublicationOutcome:
    """Sequence the publication phases for one Project and report the result.

    The phases themselves are in `codess.ingest_publication`; this orders them
    and translates between the run's state and their parameters. The order is
    a dependency, not a preference: promotion must precede the snapshot, or
    the snapshot would record the stores the rebuild replaced.

    A failed rebuild over an existing store is the one case that withdraws
    work already recorded -- the staged stores are discarded, so the vendors
    this run believed it changed did not in fact change, and their marks are
    cleared before the snapshot decision reads them.
    """
    store_root = config.store_root
    opts = run_totals.opts
    diagnostics = run_totals.diagnostics
    # `_begin_project` places these in `opts` as per-Project state; taking them as
    # parameters too would let a call site disagree with the dict every adapter reads.
    raw_records = opts["raw_records"]
    raw_store = opts["raw_store"]
    project_id = opts["project_id"]
    published = PublicationOutcome()
    project.catalog_changed_vendors |= resync_project_catalog(
        config, project_path, project_entry,
        create_store=lambda source_key, entry: config.vendor_store(
            project_path, source_key,
        ).create(entry),
    )
    published.derived_changed = correlate_project_artifacts(
        config, project_path,
        project.changed_vendors | project.catalog_changed_vendors,
        store_root,
        diagnostics=diagnostics, progress_trace=progress_trace,
    )
    if opts.get("content_policy_data") and record_content_processing(
        config, project_path, project.changed_vendors,
        project_id=project_id,
        policy=opts["content_policy_data"],
        actions=opts.get("content_actions", []),
    ):
        published.derived_changed = True

    if force and not config.validate_only:
        staged_project = config.staged_store_roots.pop(project_path)
        retain_prior = project.tally.failed and rebuild_had_existing_store
        published.promoted_stores = promote_rebuilt_stores(
            project_path, staged_project, config.sources,
            retain_prior=retain_prior,
        )
        if retain_prior:
            project.changed_vendors.clear()
            project.catalog_changed_vendors.clear()
            published.derived_changed = False
        progress_trace(
            "fresh_rebuild.promoted", project=str(project_path),
            stores=published.promoted_stores,
            retained_prior=(project.tally.errors and rebuild_had_existing_store),
        )

    published.snapshot_required = (
        bool(project.changed_vendors)
        or bool(project.catalog_changed_vendors)
        or published.derived_changed
        or opts["raw_records_changed"]
        or seal_upgrade
    )
    if config.validate_only:
        published.snapshot_id = current_snapshot_id(project_path)
        return published
    published.snapshot_id, published.candidate_path = publish_snapshot(
        config, project_path, raw_records,
        raw_store=raw_store,
        store_root=store_root,
        project_id=project_id,
        sources=config.sources,
        minimum_source_size=min_size,
        required=published.snapshot_required,
        progress_trace=progress_trace,
    )
    return published


def _cursor_preflight(
    *,
    config: "IngestConfig",
    run_totals: "RunTotals",
    cursor: "CursorSelection",
    raw_records_cache: dict,
    force: bool,
    progress_trace: ProgressEmitter,
) -> tuple[int | None, tempfile.TemporaryDirectory | None]:
    """Fingerprint and, when configured, capture the Cursor cohort once.

    This ran as a 213-line `if` inside `run`, which with the Project loop
    made two statements 90% of that function. It is one phase with one
    precondition -- Cursor roots exist and this is not a validate-only run --
    so it reads as a function and was only ever inline.

    Returns `(exit_code, cohort_temp)`. An exit code is a failure `run`
    should return immediately; `cohort_temp` is the temporary directory the
    caller must clean up, returned rather than assigned because it outlives
    this call.
    """
    # From the two run-state halves: the registry is fixed for the run, `opts` accumulates.
    store_root = config.store_root
    cursor_roots = cursor.roots
    cursor_workspace_ids = cursor.workspace_ids
    live_cursor_global = cursor.global_db
    cursor_project_headers = cursor.project_headers
    opts = run_totals.opts
    cursor_cohort_temp = None

    if cursor_roots and not config.validate_only:
        live_global = live_cursor_global
        if live_global is not None:
            try:
                marker_started = time.monotonic()
                progress_trace(
                    "cursor.marker.start", source=str(live_global.resolve()),
                    projects=len(cursor_roots),
                )
                selections = {
                    str(root): cursor_workspace_ids[root]
                    for root in cursor_roots
                }
                selection_cache_path = (
                    store_root / "cache" / "cursor-selection-v1.json"
                )
                def observe_containers() -> dict:
                    """The Cursor container state -- main and WAL -- read now.

                    *Why here.* Cursor owns these databases and writes to them
                    while Codess reads: the global store carries a live WAL,
                    30 MB on the development machine. `get_selection_markers`
                    holds one read transaction, so the markers it returns are
                    internally consistent, but SQLite's snapshot ends when
                    that transaction does. Nothing stops Cursor committing a
                    new composer between the transaction closing and the
                    markers being cached, which would persist a fingerprint
                    for a state no longer on disk and let a later run skip a
                    Project whose evidence had in fact changed.

                    Bracketing the read is what detects that: inode, size, and
                    mtime of main and WAL before and after. Equal means no
                    write landed across the read and the markers may be
                    cached; unequal retries once, then records
                    `scanned-unstable` rather than caching a marker it cannot
                    vouch for. The check is a cheap prefilter, not an
                    authentication -- it catches a concurrent writer, not a
                    deliberate forgery, which is 8.4's boundary.

                    Written out four times before, of which one compared a
                    fresh reading against another taken with nothing in
                    between -- a check that could not fail.
                    """
                    return {
                        "global": get_cursor_container_marker(live_global),
                        "workspace_indexes": {
                            str(path.resolve()): get_cursor_container_marker(path)
                            for root in cursor_roots
                            for path in get_cursor_workspace_dbs(root)
                        },
                    }

                # The cache decision belongs to `cursor_cohort`, which owns
                # Cursor caching; the command reports what it resolved.
                resolved = resolve_selection_markers(
                    selection_cache_path,
                    source=live_global,
                    selections=selections,
                    supplemental_headers=cursor_project_headers,
                    observe_containers=observe_containers,
                    read_markers=get_cursor_selection_markers,
                    force=force,
                )
                project_markers = resolved.per_project
                marker_status = resolved.status
                marker = resolved.combined
                marker_elapsed = round(time.monotonic() - marker_started, 6)
                progress_trace(
                    "cursor.marker.done", source=str(live_global.resolve()),
                    projects=len(cursor_roots), status=marker_status,
                    phase_seconds=round(marker_elapsed, 3),
                )
                opts.update({
                    "cursor_cohort_source": live_global,
                    "cursor_cohort_marker": marker,
                    "cursor_project_markers": project_markers,
                })
                if (
                    config["raw_mode"] in {"capture", "seal"}
                ):
                    # Keep timing out of diagnostics: that map contains only
                    # integer counters consumed by existing reports.
                    opts["cursor_cohort"] = {
                        "status": "unchanged",
                        "fingerprint_method": marker.get("fingerprint_method"),
                        "marker_seconds": marker_elapsed,
                        "source_bytes": marker.get("source_size"),
                        "peak_rss_bytes": peak_rss_bytes(),
                    }
                    cohort_store = RawStore(store_root / "raw")
                    state_needs_cohort = force or any(
                        cohort_needed(
                            live_global,
                            [get_state_path(root)],
                            project_markers[str(root)],
                            force=False,
                        )
                        for root in cursor_roots
                    )
                    evidence_projects = {
                        str(root)
                        for root in cursor_roots
                        if not any(
                            record.get("source_locator")
                            == str(live_global.resolve())
                            and record.get("availability") == "captured"
                            and (
                                (object_path := cohort_store.resolve(record))
                                is not None
                            )
                            and object_path.is_file()
                            for record in _current_raw_records_cached(root, raw_records_cache)
                        )
                    }
                    opts["cursor_cohort_evidence_projects"] = evidence_projects
                    evidence_needs_cohort = bool(evidence_projects)
                else:
                    state_needs_cohort = False
                    evidence_needs_cohort = False
                if state_needs_cohort or evidence_needs_cohort:
                    cohort_started = time.monotonic()
                    progress_trace(
                        "cursor.cohort.prepare.start",
                        source=str(live_global.resolve()),
                        state_refresh=state_needs_cohort,
                        evidence_refresh=evidence_needs_cohort,
                    )
                    cursor_cohort_temp = tempfile.TemporaryDirectory(
                        prefix="codess-cursor-cohort-"
                    )
                    cohort_db = Path(cursor_cohort_temp.name) / "state.vscdb"
                    cohort_record, marker, status = prepare_cursor_cohort(
                        live_global,
                        raw_store=cohort_store,
                        cache_path=(
                            store_root / "cache" / "cursor-cohort-v1.json"
                        ),
                        working_path=cohort_db,
                        source_system_id=(
                            SOURCE_PROFILES["Cursor"]["source_system_id"]
                        ),
                        storage_format=SOURCE_PROFILES["Cursor"]["storage_format"],
                        marker=marker,
                        force=force,
                        progress=progress_trace,
                    )
                    opts.update({
                        "cursor_cohort_db": cohort_db,
                        "cursor_cohort_record": cohort_record,
                        "cursor_cohort_marker": marker,
                        "cursor_cohort": {
                            "status": status,
                            "object_id": cohort_record.get("object_id"),
                            "source_revision": cohort_record.get(
                                "source_revision_id"
                            ),
                            "fingerprint_method": marker.get(
                                "fingerprint_method"
                            ),
                            "marker_seconds": marker_elapsed,
                            "cohort_seconds": round(
                                time.monotonic() - cohort_started, 6
                            ),
                            "source_bytes": marker.get("source_size"),
                            "stored_bytes": cohort_record.get("stored_size"),
                            "working_bytes": cohort_record.get(
                                "uncompressed_size"
                            ),
                            "peak_rss_bytes": peak_rss_bytes(),
                        },
                    })
                    progress_trace(
                        "cursor.cohort.prepare.done", status=status,
                        object_id=cohort_record.get("object_id"),
                        phase_seconds=round(time.monotonic() - cohort_started, 3),
                    )
                else:
                    progress_trace(
                        "cursor.cohort.unchanged",
                        source=str(live_global.resolve()),
                        projects=len(cursor_roots),
                    )
            except Exception as exc:
                progress_trace(
                    "cursor.cohort.failed", source=str(live_global.resolve()),
                    error_type=type(exc).__name__,
                )
                if cursor_cohort_temp is not None:
                    cursor_cohort_temp.cleanup()
                    cursor_cohort_temp = None
                progress_trace(
                    "ingest.failed", stage="cursor.cohort",
                    error_type=type(exc).__name__,
                )
                print(f"codess: Cursor cohort capture failed: {exc}", file=sys.stderr)
                # The caller cleans up on a returned code, so the temporary is
                # released here and reported as absent rather than handed back
                # already-cleaned.
                return 1, None

    return None, cursor_cohort_temp


def _ingest_project(
    project_path: Path,
    project_index: int,
    *,
    config: "IngestConfig",
    run_totals: "RunTotals",
    settings: dict,
    project_total: int,
    raw_records_cache: dict,
    force: bool,
    # `int`, never None: `project` resolves it as
    # `int(MIN_SIZE if raw is None else raw)`, so the None was in the
    # annotation rather than in the value -- and it propagated to three call
    # sites that each declared `int`.
    min_size: int,
    progress_trace: ProgressEmitter,
) -> int | None:
    """Ingest one Project. Returns an exit code only when the run must stop.

    This was `run`'s 353-line loop body, half that function. It is extracted
    as the body rather than the loop so `run` keeps iteration and the
    early-exit decision visible at its own level: a returned code here means
    `stop_on_error` fired or the Project raised, and `run` returns it.

    `outcome`, `diagnostics`, `source_stats`, `staged_store_roots`, and
    `opts` are mutated in place -- they accumulate across Projects, which is
    why they are passed rather than returned. `ProjectOutcome` is folded into
    `outcome` here, in the `finally`, so a Project that fails partway still
    contributes exactly once.
    """
    # Unpacked once: `config` owns what the run was configured to do, `totals` what it
    # has produced.
    outcome = run_totals.outcome
    diagnostics = run_totals.diagnostics
    opts = run_totals.opts
    source_stats = outcome.source_stats
    sources = list(config.sources)
    store_root = config.store_root
    staging_root = config.staging_root
    staged_store_roots = config.staged_store_roots
    rebuild_temporary = None
    rebuild_had_existing_store = False
    # Bound before the try so the finally can always absorb: a Project
    # that fails during setup still contributes its (empty) outcome
    # rather than raising a second error while handling the first.
    project = ProjectOutcome()
    try:
        resource_start = len(opts["resource_observations"])
        review_start = len(opts["content_failure_reviews"])
        diagnostic_start = dict(diagnostics)
        project_path = project_path.resolve()
        if force and not settings["validate_only"]:
            rebuild_parent = project_path / STORE_DIR
            rebuild_parent.mkdir(parents=True, exist_ok=True)
            rebuild_temporary = tempfile.TemporaryDirectory(
                prefix=".rebuild-", dir=rebuild_parent
            )
            staged_store_roots[project_path] = (
                Path(rebuild_temporary.name) / "project"
            )
            selected_targets = [
                get_store_path(project_path, vendor)
                for source_key, vendor in (
                    ("cc", "Claude"),
                    ("codex", "Codex"),
                    ("cursor", "Cursor"),
                )
                if source_key in sources
            ]
            rebuild_had_existing_store = any(
                path.exists() for path in selected_targets
            )
            for path in selected_targets:
                if not path.exists():
                    init_db(path)
        project_started = time.monotonic()
        progress_trace(
            "project.start", project=str(project_path),
            project_index=project_index + 1, project_total=project_total,
        )
        if settings["validate_only"]:
            # A within-run label for a Project preflight, used only in the dict
            # built below and never persisted or recomputed. The index makes it
            # unique within the run, which is all it has to be: hashing the path
            # implied a stable identity the value neither has nor needs.
            label = f"{project_index + 1}"
            binding = {"project_id": f"codess:preflight-project:{label}", "location_id": f"preflight:{label}"}
            project_entry = {
                "project_id": binding["project_id"], "logical_name": project_path.name,
                "locations": [{"location_id": binding["location_id"], "machine_id": "preflight", "path": str(project_path), "state": "active", "platform": sys.platform}],
                "workspace_bindings": [], "path_aliases": [str(project_path)],
            }
        else:
            binding = ensure_project_binding(store_root, project_path)
            project_entry = get_project_entry(store_root, binding["project_id"])
        if staging_root:
            # Register the preflight staging directory so store paths and
            # the state path resolve through one mapping rather than each
            # deriving a location of its own.
            staged_store_roots[project_path.resolve()] = (
                staging_root / str(project_index)
            )
        work_root = staged_store_roots.get(
            project_path.resolve(), project_path,
        )
        state_path = get_state_path(work_root)
        project_raw_records: list[dict] = (
            [] if settings["validate_only"]
            else _current_raw_records_cached(project_path, raw_records_cache)
        )
        raw_store = RawStore((staging_root / "raw") if staging_root else store_root / "raw")
        _begin_project(
            opts, binding,
            raw_records=project_raw_records,
            raw_store=None if settings["validate_only"] else raw_store,
        )
        seal_upgrade = (
            settings["raw_mode"] == "seal"
            and not current_snapshot_is_sealed(project_path)
        )

        if "cc" in sources:
            vendor_started = time.monotonic()
            progress_trace(
                "vendor.start", project=str(project_path), vendor="Claude",
            )
            store = config.vendor_store(project_path, "cc")
            if store.create(project_entry):
                project.catalog_changed_vendors.add(store.display_name)
            store_path = store.path
            cc_dir = get_cc_session_dir(project_path)
            if cc_dir is None and sources == ["cc"]:
                print(f"No CC project dir for {project_path}", file=sys.stderr)
                project.tally.note_error()
                if settings["stop_on_error"]:
                    progress_trace(
                        "ingest.failed", stage="project.source_selection",
                        project=str(project_path), error_type="SourceNotFound",
                    )
                    return 1
            if cc_dir is not None:
                n, e, failed, store_changed = _ingest_cc(
                    project_path,
                    store_path,
                    state_path,
                    opts,
                    force,
                    min_size,
                    stop_on_error=settings["stop_on_error"],
                )
                project.record_vendor(
                    "Claude", sessions=n, events=e,
                    failed_sources=failed, store_changed=store_changed,
                )
                if failed:
                    diagnostics["failed_sources"] = (
                        diagnostics.get("failed_sources", 0) + failed
                    )
            else:
                n = e = failed = 0
            totals = store.totals()
            if totals is not None:
                project.store_totals["Claude"] = totals
            progress_trace(
                "vendor.done", project=str(project_path), vendor="Claude",
                processed_sessions=n, processed_events=e,
                failed_sources=failed,
                stored_sessions=project.store_totals.get("Claude", {}).get("sessions", 0),
                stored_events=project.store_totals.get("Claude", {}).get("events", 0),
                phase_seconds=round(time.monotonic() - vendor_started, 3),
            )

        if "codex" in sources:
            vendor_started = time.monotonic()
            progress_trace(
                "vendor.start", project=str(project_path), vendor="Codex",
            )
            store = config.vendor_store(project_path, "codex")
            if store.create(project_entry):
                project.catalog_changed_vendors.add(store.display_name)
            store_path = store.path
            n, e, failed, store_changed = _ingest_codex(
                project_path,
                store_path,
                state_path,
                opts,
                force,
                min_size,
                stop_on_error=settings["stop_on_error"],
            )
            project.record_vendor(
                "Codex", sessions=n, events=e,
                failed_sources=failed, store_changed=store_changed,
            )
            if failed:
                diagnostics["failed_sources"] = (
                    diagnostics.get("failed_sources", 0) + failed
                )
            totals = store.totals()
            if totals is not None:
                project.store_totals["Codex"] = totals
            progress_trace(
                "vendor.done", project=str(project_path), vendor="Codex",
                processed_sessions=n, processed_events=e,
                failed_sources=failed,
                stored_sessions=project.store_totals.get("Codex", {}).get("sessions", 0),
                stored_events=project.store_totals.get("Codex", {}).get("events", 0),
                phase_seconds=round(time.monotonic() - vendor_started, 3),
            )

        if "cursor" in sources:
            vendor_started = time.monotonic()
            progress_trace(
                "vendor.start", project=str(project_path), vendor="Cursor",
            )
            store = config.vendor_store(project_path, "cursor")
            if store.create(project_entry):
                project.catalog_changed_vendors.add(store.display_name)
            store_path = store.path
            n, e, failed, store_changed = _ingest_cursor(
                project_path,
                store_path,
                state_path,
                opts,
                force,
                stop_on_error=settings["stop_on_error"],
            )
            project.record_vendor(
                "Cursor", sessions=n, events=e,
                failed_sources=failed, store_changed=store_changed,
            )
            if failed:
                diagnostics["failed_sources"] = (
                    diagnostics.get("failed_sources", 0) + failed
                )
            totals = store.totals()
            if totals is not None:
                project.store_totals["Cursor"] = totals
            progress_trace(
                "vendor.done", project=str(project_path), vendor="Cursor",
                processed_sessions=n, processed_events=e,
                failed_sources=failed,
                stored_sessions=project.store_totals.get("Cursor", {}).get("sessions", 0),
                stored_events=project.store_totals.get("Cursor", {}).get("events", 0),
                phase_seconds=round(time.monotonic() - vendor_started, 3),
            )

        if project.store_totals:
            if not settings["validate_only"]:
                # Check the identity; refresh the entry.
                #
                # The two are different concerns and only the second is a
                # re-read. `store.create` above synced this Project's catalog
                # entry into each vendor store, and `resync_project_catalog`
                # below reports which entries *changed*; handing it the copy
                # read before ingest makes it re-sync work already done and
                # report a false change, which is a spurious correlation pass
                # on an unchanged run. So the refresh is load-bearing rather
                # than defensive -- it reads the state this run itself wrote.
                #
                # The identity is checked instead of re-read, because a fresh
                # read cannot help there: a concurrent writer can change the
                # binding after this point as easily as before it, so a newer
                # copy proves nothing about the moment it is used. And unlike
                # the entry, a changed `project_id` is not recoverable within
                # this Project -- stores were opened, events written, and a
                # snapshot is about to be published under the old one.
                #
                # It is not a reason to abandon the *run*, though. The other
                # Projects are unaffected, so this one is set aside the way
                # any other per-Project failure is: report it, count it, and
                # continue unless the operator asked to stop. What is
                # withheld is publication -- the decoded stores stay as they
                # are, unpublished, so a later run rebuilds them under
                # whichever identity is then current rather than this run
                # publishing work under an identity that no longer names it.
                current = read_project_binding(project_path)
                if current and current["project_id"] != opts["project_id"]:
                    print(
                        f"codess: Project identity changed during ingest of "
                        f"{project_path}: {opts['project_id']} became "
                        f"{current['project_id']}; not publishing this Project",
                        file=sys.stderr,
                    )
                    progress_trace(
                        "project.identity_changed", project=str(project_path),
                        was=opts["project_id"], now=current["project_id"],
                    )
                    project.tally.note_error()
                    if settings["stop_on_error"]:
                        progress_trace(
                            "ingest.failed", stage="project.identity",
                            project=str(project_path),
                            error_type="ProjectIdentityChanged",
                        )
                        return 1
                    return None
                project_entry = get_project_entry(
                    store_root, opts["project_id"],
                )
            published = _publish_project(
                config,
                run_totals,
                project_path,
                project,
                project_entry=project_entry,
                min_size=min_size,
                force=force,
                seal_upgrade=seal_upgrade,
                rebuild_had_existing_store=rebuild_had_existing_store,
                progress_trace=progress_trace,
            )
            snapshot_id = published.snapshot_id
            candidate_snapshot_path = published.candidate_path
            snapshot_required = published.snapshot_required
            evidence_summary = None
            evidence_summary_reused = False
            if not settings["validate_only"]:
                _save_stats(project_path, store_root, project.store_totals)
                evidence_paths = [config.store_path(project_path, key) for key in VENDOR_KEYS]
                previous_report = _load_runtime_report(project_path)
                previous_summary = previous_report.get("evidence_summary")
                if (
                    not snapshot_required
                    and snapshot_id is not None
                    and previous_report.get("report_format")
                    == "codess.ingest-runtime/1"
                    and previous_report.get("project") == str(project_path)
                    and previous_report.get("snapshot_id") == snapshot_id
                    and isinstance(previous_summary, dict)
                ):
                    evidence_summary = previous_summary
                    evidence_summary_reused = True
                    progress_trace(
                        "evidence_summary.reused",
                        project=str(project_path), snapshot_id=snapshot_id,
                    )
                else:
                    evidence_started = time.monotonic()
                    progress_trace(
                        "evidence_summary.start", project=str(project_path),
                        stores=len([path for path in evidence_paths if path.exists()]),
                    )
                    evidence_summary = _evidence_summary(evidence_paths)
                    progress_trace(
                        "evidence_summary.done", project=str(project_path),
                        phase_seconds=round(
                            time.monotonic() - evidence_started, 3
                        ),
                    )
                raw_object_paths = {
                    resolved_object
                    for record in project_raw_records
                    if (resolved_object := raw_store.resolve(record)) is not None
                    and resolved_object.is_file()
                }
                project_resource_summary = summarize_project_resources(
                    opts["resource_observations"][resource_start:],
                    normalized_store_paths=[
                        path for path in evidence_paths if path.exists()
                    ],
                    raw_object_paths=raw_object_paths,
                )
            progress_trace(
                "project.done", project=str(project_path),
                status=("completed_with_errors" if project.tally.errors else "accepted"),
                processed_sessions=project.tally.sessions,
                processed_events=project.tally.events,
                stored_sessions=sum(value["sessions"] for value in project.store_totals.values()),
                stored_events=sum(value["events"] for value in project.store_totals.values()),
                phase_seconds=round(time.monotonic() - project_started, 3),
            )
            if not settings["validate_only"]:
                _write_runtime_report(project_path, {
                    "report_format": "codess.ingest-runtime/1",
                    "progress_format": "codess.progress/1",
                    "progress_live": settings["live_progress"],
                    "status": (
                        "completed_with_errors" if project.tally.errors else "accepted"
                    ),
                    "project": str(project_path), "sources": project.store_totals,
                    "snapshot_id": snapshot_id,
                    "snapshot_publication": (
                        "candidate"
                        if candidate_snapshot_path is not None
                        else "current_or_unchanged"
                    ),
                    "candidate_snapshot_path": candidate_snapshot_path,
                    "decoder_version": DECODER_VERSION,
                    "validator_version": VALIDATOR_VERSION,
                    "evidence_summary_reused": evidence_summary_reused,
                    "diagnostics": {
                        key: value - diagnostic_start.get(key, 0)
                        for key, value in diagnostics.items()
                        if value != diagnostic_start.get(key, 0)
                    },
                    "content_failure_reviews": opts["content_failure_reviews"][review_start:],
                    "resource_observations": opts["resource_observations"][resource_start:],
                    "resource_summary": project_resource_summary,
                    "cursor_cohort": opts.get("cursor_cohort"),
                    "progress_events": _progress_events(str(project_path)),
                    "evidence_summary": evidence_summary,
                    "resource_policy": settings["resource_policy"],
                    "limits": _resource_limits_report(settings),
                })
            for k, v in project.store_totals.items():
                if k not in source_stats:
                    source_stats[k] = {"sessions": 0, "events": 0}
                source_stats[k]["sessions"] += v["sessions"]
                source_stats[k]["events"] += v["events"]
    except Exception:
        # Bound once: `sys.exc_info()[0]` called twice is two lookups that a
        # reader must assume agree, and the guard on the first does not narrow the
        # second for a type checker or for a person.
        failure_type = sys.exc_info()[0]
        progress_trace(
            "project.failed", project=str(project_path),
            error_type=failure_type.__name__ if failure_type else None,
        )
        log.exception("Ingest failed for project root %s", project_path)
        outcome.tally.note_error()
        if settings["stop_on_error"]:
            progress_trace(
                "ingest.failed", stage="project",
                project=str(project_path),
                error_type=failure_type.__name__ if failure_type else None,
            )
            return 1
    finally:
        # Fold this Project into the run exactly once, whether it
        # completed or failed, so run totals reflect every Project
        # attempted and cannot double-count a retry path.
        outcome.absorb(project)
        staged_store_roots.pop(project_path.resolve(), None)
        if rebuild_temporary is not None:
            rebuild_temporary.cleanup()
    # No code: this Project is finished and the run continues. Stated rather
    # than left to fall off the end, so "continue" and "stop" are both
    # visible decisions.
    return None


def run(args: argparse.Namespace) -> int:
    """Run session-ingest. Returns exit code."""
    resolved = _resolve_ingest_request(args)
    if isinstance(resolved, int):
        return resolved
    roots, store_root, sources, settings = resolved
    diagnostics: dict[str, int] = {}
    # Decoder options, passed to every adapter. Distinct from `settings`
    # above: `settings` is what the run was configured to do, `opts` is what
    # the decoders need while doing it. The two share only `raw_mode`.
    #
    # Three lifetimes are mixed here, which is why this is slated for replacement:
    #
    #   run-wide inputs     -- debug, redact, strict_mapping, validate_only,
    #                          and the max_* bounds, copied from `settings`
    #   run-wide collectors -- diagnostics, resource_observations,
    #                          content_failure_reviews, claude_session_kinds:
    #                          accumulate across every Project
    #   per-Project state   -- PROJECT_SCOPED_OPTIONS, reset by _begin_project
    #                          on each loop iteration
    #
    # Adapters take the whole dict, so splitting it changes their signatures;
    # that is the step-4 interface change, not something to do piecemeal.
    opts = {
        "debug": settings["debug"],
        "redact": settings["redact"],
        "diagnostics": diagnostics,
        "raw_mode": settings["raw_mode"],
        "strict_mapping": settings["strict_mapping"],
        "validate_only": settings["validate_only"],
        "max_source_bytes": settings["max_source_bytes"],
        "max_cursor_container_bytes": settings["max_cursor_container_bytes"],
        "max_events_per_source": settings["max_events_per_source"],
        "max_events_per_session": settings["max_events_per_session"],
        "max_context_content_chars": settings["max_context_content_chars"],
        "resource_observations": [],
        "content_failure_reviews": [],
        "claude_session_kinds": {"main": 0, "subagent": 0},
    }
    # Configure the facility before the first event, and register the roots a
    # `located` field is rendered against.
    #
    # The collector is attached explicitly rather than left to the profile,
    # because the durable ingest report reads it: a run whose profile happened
    # not to include a collector would publish a report with no progress events
    # and no indication that any were produced. The human sink is attached beside
    # it unless `--no-progress` suppressed live output.
    #
    # Ingest defaults to `validation`, not to the global `deployment` default.
    # A long-running command whose progress an operator watches is exactly the
    # case the profile table calls validation: lifecycle events at info level,
    # per-source detail withheld until asked for. `deployment` would show
    # warnings only, which for ingest reads as a hang.
    #
    # `--debug` raises it to `debug`, which is what makes the level gate usable
    # rather than merely present: the per-source events are debug level, so they
    # appear when diagnosing and not otherwise. The previous facility printed
    # them unconditionally, which is why `--debug` had nothing to add.
    profile_name = settings.get("report_profile")
    if profile_name is None:
        profile_name = "debug" if settings.get("debug") else "validation"
    # Named `redaction_roots`, not `roots`: this function's `roots` is the list
    # of Project roots being ingested, and shadowing it made every Project path a
    # string, which failed on `.resolve()` several frames later.
    redaction_roots = {
        "home": Path.home(),
        "registry": store_root,
        "cc-projects": CC_PROJECTS,
        "codex-sessions": CODEX_SESSIONS,
        "cursor-data": CURSOR_DATA,
    }
    # `report_profile`, not `resolved`: that name is already bound to the
    # request tuple in this function, and rebinding it to a `Profile` is the
    # shadowing the naming rule forbids.
    report_profile = resolve_profile(
        profile_name, settings.get("report_privacy"),
    )
    report_roots = Roots(redaction_roots)
    # The collector keeps everything the run produced; the human sink prints at
    # the profile's level. That split is the point of R6: `--no-progress` and a
    # quiet profile change what an operator *sees* without changing what the
    # durable report can later explain.
    attached: list[object] = [
        CollectorSink(privacy=report_profile.privacy, roots=report_roots)
    ]
    if settings["live_progress"]:
        attached.append(HumanSink(
            privacy=report_profile.privacy, roots=report_roots,
            min_level=report_profile.min_level,
        ))
    reporting.configure(
        profile_name,
        privacy=settings.get("report_privacy"),
        redaction_roots=redaction_roots,
        sinks=tuple(attached),
    )
    # One name for the 29 call sites and the parameter they thread onward, so
    # the emitter is substituted without touching a signature.
    progress_trace = progress_emit
    opts["progress"] = progress_emit
    opts["store_root"] = str(store_root)
    progress_trace(
        "ingest.start", projects=len(roots), sources=",".join(sources),
        validate_only=settings["validate_only"], raw_mode=settings["raw_mode"],
    )
    if settings["content_policy"]:
        policy_path = Path(settings["content_policy"]).expanduser()
        try:
            policy_data = json.loads(policy_path.read_text(encoding="utf-8"))
            if not isinstance(policy_data, dict):
                raise ValueError("policy root must be a JSON object")
            opts["content_processor"] = ContentProcessor(
                ContentPolicy.from_mapping(policy_data)
            )
            opts["content_policy_data"] = policy_data
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            print(f"codess: invalid content policy {policy_path}: {exc}", file=sys.stderr)
            return 1
    force = True if settings["validate_only"] else settings["force"]
    min_size = settings["min_size"]

    outcome = IngestOutcome()
    staged_store_roots: dict[Path, Path] = {}

    temporary = tempfile.TemporaryDirectory(prefix="codess-preflight-") if settings["validate_only"] else None
    staging_root = Path(temporary.name) if temporary else None
    config = IngestConfig.from_options(
        settings, sources, store_root,
        staging_root=staging_root, staged_store_roots=staged_store_roots,
    )
    # The two halves of run state: `config` is what was decided and does not
    # change, `totals` is what the run has produced and changes constantly.
    totals = RunTotals(outcome=outcome, diagnostics=diagnostics, opts=opts)
    if settings["validate_only"]:
        opts["raw_mode"] = "observe"
    if "codex" in sources:
        index_started = time.monotonic()
        progress_trace("codex.index.start")
        opts["codex_session_index"] = build_codex_session_index(
            cache_path=(
                None if settings["validate_only"] else
                store_root / "cache" / "codex-session-index-v1.json"
            )
        )
        progress_trace(
            "codex.index.done",
            sessions=len(opts["codex_session_index"]),
            phase_seconds=round(time.monotonic() - index_started, 3),
        )

    cursor_cohort_temp = None
    raw_records_cache: dict[Path, list[dict]] = {}

    def cleanup_cursor_cohort() -> None:
        nonlocal cursor_cohort_temp
        if cursor_cohort_temp is not None:
            cursor_cohort_temp.cleanup()
            cursor_cohort_temp = None

    cursor_workspace_ids = {
        root.resolve(): set(workspace_ids)
        for root in roots
        if "cursor" in sources
        and (workspace_ids := get_cursor_workspace_ids(root))
    }
    live_cursor_global = get_cursor_global_db() if cursor_workspace_ids else None
    # One object rather than four parallel values: they are derived together and every
    # following step uses all of them.
    cursor = CursorSelection(
        workspace_ids=cursor_workspace_ids,
        global_db=live_cursor_global,
        project_headers={
            str(root): get_cursor_project_composer_headers(
                live_cursor_global, root, diagnostics=diagnostics
            )
            for root in cursor_workspace_ids
            if live_cursor_global is not None
        },
    )
    opts["cursor_project_headers"] = cursor.project_headers
    preflight_code, cursor_cohort_temp = _cursor_preflight(
        config=config,
        run_totals=totals,
        cursor=cursor,
        raw_records_cache=raw_records_cache,
        force=force,
        progress_trace=progress_trace,
    )
    if preflight_code is not None:
        cleanup_cursor_cohort()
        return preflight_code


    for project_index, project_path in enumerate(roots):
        project_code = _ingest_project(
            project_path,
            project_index,
            config=config,
            run_totals=totals,
            settings=settings,
            project_total=len(roots),
            raw_records_cache=raw_records_cache,
            force=force,
            min_size=min_size,
            progress_trace=progress_trace,
        )
        if project_code is not None:
            cleanup_cursor_cohort()
            return project_code



    if settings["validate_only"]:
        _print_preflight_report(
            settings, roots, sources, staging_root, temporary, progress_trace, opts,
            diagnostics=diagnostics, outcome=outcome,
        )
        return 1 if outcome.tally.errors else 0
    cleanup_cursor_cohort()
    _report_ingest_outcome(
        progress_trace, opts, diagnostics, outcome,
    )
    # A command boundary: a batch smaller than the flush threshold must still
    # reach the sink before the process ends.
    reporting.flush()
    return 1 if outcome.tally.errors else 0
