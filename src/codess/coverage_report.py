"""What one ingest mapped, what it did not, and what it could not name.

A result a reader can challenge has to state what it *missed*, not only what
it found. This derives that from a published store rather than from run-time
counters, for two reasons.

**Counters are a report of the run; a store is a report of the evidence.**
The ingest command prints eleven diagnostic counts to stderr and discards
them. They cannot be queried later, cannot be compared between runs, and
answer questions about one process rather than about the Project. A reader
asking "what did Codess fail to map here" cannot be told to re-run ingest and
watch the terminal.

**A hand-written list drifts.** Those eleven counts were an f-string naming
each counter, while adapters produce twenty-one; ten were produced and never
reported, and one reported name no longer existed. Deriving the report from
what the store holds removes the second list that has to be kept in step.

Reports counts, reason codes, and record types -- never message, prompt,
argument, or result content, so a coverage figure can be published alongside
a result without republishing the Session.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from codess.config import MAPPING_PROFILE_FOR_SOURCE_SYSTEM
from codess.fileio import quote_identifier
from codess.schema_contract import (
    SchemaContractError,
    column_names,
    contract_digest,
    load_mapping,
    table_names,
)

# The granularities that mean something was not mapped. `source` and `record`
# mean a whole input did not become an Event; `field` means an Event exists with
# a value missing. Conflating the two overstates loss, which is why the report
# separates them rather than summing -- and is why the column is named
# `granularity` rather than `level`, which reads as an ordering that could be
# summed.
_LOSS_GRANULARITIES = ("source", "record")


def _counts_by(conn: sqlite3.Connection, column: str, where: str = "") -> dict[str, int]:
    """Count `mapping_diagnostics` rows grouped by one column.

    The column is resolved against the live store before it reaches the SQL,
    so a rename fails here naming the column rather than returning an empty
    report from a query that no longer matches anything.
    """
    if column not in column_names(conn, "mapping_diagnostics"):
        raise SchemaContractError(
            f"mapping_diagnostics has no column {column!r}; "
            "the released DDL and this report disagree"
        )
    clause = f" WHERE {where}" if where else ""
    return {
        str(row[0] if row[0] is not None else "[none]"): int(row[1])
        for row in conn.execute(
            f"SELECT {quote_identifier(column)}, COUNT(*) FROM mapping_diagnostics{clause} "  # noqa: S608
            "GROUP BY 1 ORDER BY 2 DESC"
        )
    }


def mapped_coverage(conn: sqlite3.Connection) -> dict[str, Any]:
    """How much of what was read became a classified Event.

    `admitted` counts Events in the store. `unmapped` counts Events whose
    common classification is absent -- a record that arrived and was stored
    without Codess being able to say what it is, which is the honest
    denominator for "coverage" and is distinct from a record that was never
    admitted at all.
    """
    admitted = int(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])
    unmapped = int(
        conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_kind IS NULL "
            "OR actor_kind IS NULL OR content_role IS NULL OR origin_kind IS NULL"
        ).fetchone()[0]
    )
    return {
        "admitted_events": admitted,
        "unclassified_events": unmapped,
        "classified_events": admitted - unmapped,
        # Reported as a ratio a reader can compare between Projects; the
        # counts are given so the ratio can be recomputed rather than trusted.
        "classified_ratio": (
            round((admitted - unmapped) / admitted, 6) if admitted else None
        ),
    }


def source_record_shapes(conn: sqlite3.Connection) -> dict[str, Any]:
    """Which vendor record types were seen, and how many of each.

    This is the shape inventory a reader consults when a vendor changes its
    format: a type appearing here that no mapping profile names is an
    unknown shape, and a type that stops appearing is evidence of a vendor
    change rather than of a decoder fault.
    """
    return {
        "by_source_record_type": {
            str(row[0] if row[0] is not None else "[none]"): int(row[1])
            for row in conn.execute(
                "SELECT source_record_type, COUNT(*) FROM events "
                "GROUP BY 1 ORDER BY 2 DESC"
            )
        },
        "by_mapping_rule": {
            str(row[0] if row[0] is not None else "[none]"): int(row[1])
            for row in conn.execute(
                "SELECT mapping_rule, COUNT(*) FROM events GROUP BY 1 ORDER BY 2 DESC"
            )
        },
    }


def loss(conn: sqlite3.Connection) -> dict[str, Any]:
    """What was read and not fully carried across, by reason.

    Split by diagnostic granularity rather than summed: a source or record
    diagnostic means something did not become an Event, while a field
    diagnostic means an Event exists with a value missing. Adding them would
    report a Project as lossier than it is.
    """
    if "mapping_diagnostics" not in table_names(conn):
        return {"available": False}
    by_granularity = _counts_by(conn, "granularity")
    return {
        "available": True,
        "by_granularity": by_granularity,
        "unmapped_records": {
            name: by_granularity.get(name, 0) for name in _LOSS_GRANULARITIES
        },
        # Adapters now write record-level diagnostics when they refuse a
        # record, so a zero here is evidence rather than silence -- but
        # only for the refusals that are routed. The flag stays so a reader
        # can tell a measured zero from a store written before that landed.
        "record_loss_recorded": any(
            by_granularity.get(name, 0) for name in _LOSS_GRANULARITIES
        ),
        "by_reason": _counts_by(conn, "reason_code"),
        "record_level_reasons": _counts_by(
            conn, "reason_code",
            where="granularity IN ('source', 'record')",
        ),
    }


def undecoded_evidence(source_system_key: str | None) -> dict[str, Any]:
    """Retained vendor evidence Codess located and deliberately did not decode.

    Loss has two shapes and the report was only carrying one. `loss()` measures
    what a decoder read and could not fully map -- a refused record, an
    incomplete field. This measures a different thing: evidence a vendor
    retained, in a container Codess knows about, that no adapter admits at all.
    A store cannot report it, because the whole point is that nothing was
    written -- so a report derived only from the store states zero by
    construction, which is the unfalsifiable zero record-level diagnostics removed elsewhere.

    Codex is the one vendor with a measured instance. `~/.codex/history.jsonl`
    records human prompts keyed by Session, and a Session can appear there with
    no rollout: measured on one machine, 19 history Sessions, 18 with rollouts,
    one without carrying 2 prompts. Admitting it would mean a Session with
    prompts and no Model Turns, which changes what a Session is and is a mapping
    decision under 6.5. Reporting it is the honest middle path.

    Keyed by `source_system_key` so a store's own report names only its vendor,
    and returns `available: False` for a vendor with nothing of this kind rather
    than omitting the key, so a reader can tell "measured, none" from
    "not measured".
    """
    if source_system_key != "openai.codex":
        return {"available": False, "reason": "no undecoded container measured"}
    from codess.codex_source import unrolled_history_sessions

    measured = unrolled_history_sessions()
    if not measured.get("available"):
        return {"available": False, "reason": "history container absent"}
    return {
        "available": True,
        "container": "history.jsonl",
        "sessions": measured["history_sessions"],
        "with_rollout": measured["with_rollout"],
        # The figure a reader wants: Sessions whose only local evidence is a
        # container no adapter decodes.
        "undecodable_sessions": measured["without_rollout"],
        "undecodable_prompts": sum(measured["unrolled_prompt_counts"].values()),
        "disposition": "reported, not admitted",
    }


def projection_coverage(source_system_key: str | None) -> dict[str, Any]:
    """Which vendor fields the decoder projects, and which it drops.

    A coverage report that states only what was mapped cannot say what a
    *projection* dropped: the decoder selects a field subset before an Event is
    built, so a field never projected leaves no trace in the store and reads as
    absent from the vendor rather than as declined by Codess.

    Cursor is where this bites, because its bubble carries 98 fields and the
    projection admits a fraction. The count is derived from the decoder's own
    declared set rather than restated here, so it cannot drift from what the
    decoder actually reads.

    `BUBBLE_FIELD_TOTAL` is the measured shape of the vendor record -- 98 fields
    sampled over 20,000 bubbles, of which roughly 40 are present on every bubble
    and populated on none. Recorded as a measurement with its sample size, which
    is what lets a later release contradict it.
    """
    if source_system_key != "cursor.composer":
        return {"available": False, "reason": "no projection measured"}
    from codess.adapters.cursor import _MAPPED_BUBBLE_FIELDS, BUBBLE_FIELD_TOTAL

    projected = len(_MAPPED_BUBBLE_FIELDS)
    return {
        "available": True,
        "container": "cursorDiskKV.bubbleId",
        "observed_fields": BUBBLE_FIELD_TOTAL,
        "projected_fields": projected,
        "unprojected_fields": max(BUBBLE_FIELD_TOTAL - projected, 0),
        "projected": sorted(_MAPPED_BUBBLE_FIELDS),
        "disposition": "projected set is declared; the remainder is recorded "
                       "as measured-empty or decided per field",
    }


def unbound_composers(source_system_key: str | None) -> dict[str, Any]:
    """Composers holding decodable bubbles that no index binds to a Project.

    Cursor's centralised `composerHeaders` indexes only composers touched since
    it was introduced, while every `composerData:` row and bubble is retained, so
    a composer predating that migration has no header and states no workspace. Codess reads it, records where it came from,
    and does not attribute it -- which is the correct handling of a Session whose
    binding the vendor no longer records.

    Reported because the condition is otherwise invisible: these Sessions are
    excluded from ingest by design, so a store cannot count them and a clean
    coverage report would overstate what the corpus holds.
    """
    if source_system_key != "cursor.composer":
        return {"available": False, "reason": "not a Cursor store"}
    from codess.cursor_source import get_global_db, unbound_composer_count

    database = get_global_db()
    if database is None:
        return {"available": False, "reason": "global container absent"}
    try:
        measured = unbound_composer_count(database)
    except Exception:
        return {"available": False, "reason": "global container unreadable"}
    return {
        "available": True,
        "container": "cursorDiskKV.composerData",
        **measured,
        "disposition": "visible and unattributed; a binding is operator-stated",
    }


def profile_conformance(
    conn: sqlite3.Connection, source_system_key: str | None,
) -> dict[str, Any]:
    """Whether the rules a store used are the rules its profile declares.

    `source_record_shapes` reports which rules a store used; the released
    profile declares which rules exist. Neither alone answers the question a
    coverage report is asked -- *is this store conformant* -- because a rule
    the adapter invented and a rule the profile declares look identical once
    stored.

    Two directions, and they mean different things:

    - **undeclared**: a `mapping_rule` in the store that the profile does not
      name. The adapter emitted a rule id nothing released describes, so the
      store records a mapping no contract covers.
    - **unused**: a declared rule no Event carries. Usually a shape this
      Project's Sessions did not contain, which is unremarkable; consistently
      unused across every Project is evidence the rule is dead or the decoder
      stopped reaching it.

    Returns `available: False` rather than an empty result when the store's
    source system has no released profile, so a reader can tell "compared,
    nothing found" from "not compared".
    """
    if "store_meta" in table_names(conn):
        row = conn.execute(
            "SELECT value FROM store_meta WHERE key='contract_digest'"
        ).fetchone()
        # A store predating the contract-digest column records no digest at
        # all, so an absent value is a superseded store rather than a matching
        # one -- treating absence as agreement is what let stale stores be
        # compared against profiles they never saw.
        written_under = str(row[0]) if row and row[0] else None
        if written_under != contract_digest():
            # A store written under an older contract is compared against
            # profiles it never saw. Its rule ids were declared then and are
            # not now, so every one reads as undeclared -- which says the store
            # is superseded, not that a decoder invented anything. Measured:
            # nine of thirty stores on the development machine predate the
            # current format, and one of them accounts for every undeclared id.
            return {
                "available": False,
                "reason": "store was written under a superseded contract",
            }
    if source_system_key is None:
        return {
            "available": False,
            "reason": "store holds no Sessions, so it names no source system",
        }
    name = MAPPING_PROFILE_FOR_SOURCE_SYSTEM.get(source_system_key)
    if name is None:
        return {
            "available": False,
            "reason": f"no released profile for {source_system_key}",
        }
    try:
        declared = {
            str(rule["id"]) for rule in load_mapping(name).get("rules", [])
            if rule.get("id")
        }
    except SchemaContractError as exc:
        return {"available": False, "reason": str(exc)}
    stored = {
        str(row[0]) for row in conn.execute(
            "SELECT DISTINCT mapping_rule FROM events WHERE mapping_rule IS NOT NULL"
        )
    }
    return {
        "available": True,
        "profile": name,
        "declared": len(declared),
        "used": len(stored & declared),
        "undeclared": sorted(stored - declared),
        "unused": sorted(declared - stored),
    }


def _store_source_system(conn: sqlite3.Connection) -> str | None:
    """Which vendor this store holds, from its own rows."""
    if "sessions" not in table_names(conn):
        return None
    row = conn.execute(
        "SELECT source_system_key FROM sessions LIMIT 1"
    ).fetchone()
    return str(row[0]) if row and row[0] else None


# The window inside which a repeat is more likely a resubmission than a second
# decision. Measured: of the consecutive identical prompts in the corpus, the
# median gap is 98 minutes and only a handful fall within a minute, so the
# window separates a small class rather than describing the common case.
RESUBMISSION_WINDOW_MS = 60_000

# How much of a prompt's opening identifies its family. A templated prompt --
# a scripted run that embeds varying content into a fixed preamble -- shares an
# opening and diverges later, so a key over the opening groups what exact text
# splits apart. 200 characters is well inside the shortest observed preamble
# (7,889 characters before the divergence marker) and well past the point where
# two unrelated prompts would still agree.
#
# Deliberately not configurable. One corpus, one observed family: a setting
# would offer a choice the evidence cannot inform, which is the trap W84
# records for a vocabulary guessed from a single value.
FAMILY_PREFIX_CHARS = 200


def _prompt_families(seen_texts: dict[str, set[str]]) -> list[dict[str, Any]]:
    """Group prompts by their opening, beside the exact-text grouping.

    **An exact-keyed group count is a floor, not a family size.** A templated
    prompt embeds varying content into a fixed preamble, so one scripted run
    splits into as many groups as it has variants and each is reported
    honestly and separately. Measured on this corpus: 327 prompts of an
    LLM-judge harness share one opening, carry 6 distinct preambles and 24
    distinct generated transcripts, and reduce to 34 exact texts -- the largest
    of which holds 13. Reading that 13 as the family understates the run by a
    factor of 25.

    **`chars_min` and `chars_max` are the falsifiable part**, and the reason
    this is worth emitting rather than leaving to a reader. Identical texts
    cannot have different lengths, so a span inside one prefix group *proves*
    the family is larger than any exact group within it. That is a check rather
    than a heuristic: `chars_min == chars_max` means the grouping found nothing
    the exact keying missed.

    **The exact grouping is kept, not replaced.** Exact identity is the honest
    answer to "is this the same text", and it is what a resubmission check
    needs -- two identical submissions seconds apart is a different observation
    from two similar ones. The two questions are different and both are asked.

    **A shared opening is an observation; similarity is an inference.** This
    deliberately stops at a prefix rather than shingling or edit distance.
    Those would catch more and would begin asserting that two prompts *are* the
    same thing, which is a claim about meaning that belongs to a reader rather
    than to a projection of what the vendor wrote.
    """
    grouped: dict[str, dict[str, Any]] = {}
    for text, sessions in seen_texts.items():
        prefix = text[:FAMILY_PREFIX_CHARS]
        family = grouped.setdefault(prefix, {
            "prefix": prefix[:80],
            "exact_texts": 0,
            "sessions": set(),
            "chars_min": len(text),
            "chars_max": len(text),
        })
        family["exact_texts"] += 1
        family["sessions"] |= sessions
        family["chars_min"] = min(int(family["chars_min"]), len(text))
        family["chars_max"] = max(int(family["chars_max"]), len(text))
    families = [
        {
            "prefix": item["prefix"],
            "exact_texts": item["exact_texts"],
            "sessions": len(item["sessions"]),
            "chars_min": item["chars_min"],
            "chars_max": item["chars_max"],
            # The proof, stated rather than left for a reader to derive: a
            # length span inside one opening means the exact grouping split a
            # family, and the count beside it is a floor.
            "varies_by_length": item["chars_min"] != item["chars_max"],
        }
        for item in grouped.values()
        if item["exact_texts"] > 1 or len(item["sessions"]) > 1
    ]
    families.sort(key=lambda item: -int(item["sessions"]))
    return families


def repeated_prompts(conn: sqlite3.Connection) -> dict[str, Any]:
    """Human prompts submitted verbatim more than once, and how far apart.

    **Repetition is the signal, not brevity.** An earlier version of this
    filtered to prompts of 40 characters or fewer, which is wrong twice over:
    40 characters is the 25th percentile of human prompts here, so it is not
    short; and the most repeated text in the corpus is **8,670 characters
    repeated 13 times** -- a scripted evaluation prompt, which a length filter
    would have hidden entirely. Length is a property of the prompt; repetition
    is the observation.

    Two shapes are reported because they mean different things:

    - `consecutive` is the same text twice in a row within one Session. This is
      where a resubmission would appear.
    - `recurring` is a text appearing in several Sessions. `continue` (49
      times) and `go` (13) are the operator's vocabulary; an 8,670-character
      prompt repeated 13 times is a scripted run, and both are worth seeing.

    **The cause is not classified.** A repeat is either the operator asking
    again or a timed-out request submitted a second time, and the local
    evidence does not distinguish them: each repeat is a distinct vendor record
    with its own identity, so the store is not double-counting one submission,
    and the elapsed gap is usually large. `within_window` counts the subset
    tight enough that a resolution would act on it.
    """
    rows = conn.execute(
        "SELECT session_id, sequence_no, event_at, content FROM events "
        "WHERE event_kind='message.prompt' AND actor_kind='human' "
        "AND content IS NOT NULL AND trim(content) != '' "
        "ORDER BY session_id, sequence_no",
    ).fetchall()
    consecutive: list[dict[str, Any]] = []
    seen_texts: dict[str, set[str]] = {}
    previous: Any = None
    for row in rows:
        text = str(row[3] or "").strip()
        folded = text.casefold()
        seen_texts.setdefault(folded, set()).add(str(row[0]))
        if (
            previous is not None
            and previous[0] == row[0]
            and str(previous[3] or "").strip().casefold() == folded
        ):
            gap = (
                (row[2] - previous[2])
                if row[2] is not None and previous[2] is not None
                else None
            )
            consecutive.append({
                "session_id": row[0],
                "sequence_no": row[1],
                "chars": len(text),
                # Bounded: the text may be thousands of characters, and the
                # report states what repeated rather than reproducing it.
                "text": text[:80],
                "gap_ms": gap,
            })
        previous = row
    within = [
        item for item in consecutive
        if item["gap_ms"] is not None and 0 <= item["gap_ms"] < RESUBMISSION_WINDOW_MS
    ]
    # Typed as the literal it is, so the sort key is an `int` rather than the
    # `object` a heterogeneous dict value infers to.
    recurring: list[dict[str, Any]] = [
        {"chars": len(text), "text": text[:80], "sessions": len(sessions)}
        for text, sessions in seen_texts.items()
        if len(sessions) > 1
    ]
    recurring.sort(key=lambda item: -int(item["sessions"]))
    families = _prompt_families(seen_texts)
    return {
        "prompts": len(rows),
        "consecutive": len(consecutive),
        "within_window": len(within),
        "window_ms": RESUBMISSION_WINDOW_MS,
        "recurring_texts": len(recurring),
        "families": families[:20],
        "examples": consecutive[:50],
        "recurring": recurring[:20],
        "disposition": "reported, not classified: the local evidence does not "
                       "distinguish a resubmission from a second request",
    }


def store_coverage(conn: sqlite3.Connection) -> dict[str, Any]:
    """Coverage, shapes, and loss for one vendor store.

    `undecoded` is measured from the vendor container rather than the store,
    which is why it is resolved here rather than inside `loss`: a store is a
    report of what was mapped, and evidence nothing mapped leaves no row.
    """
    source_system_key = _store_source_system(conn)
    return {
        "coverage": mapped_coverage(conn),
        "shapes": source_record_shapes(conn),
        "conformance": profile_conformance(conn, source_system_key),
        "loss": loss(conn),
        "undecoded": undecoded_evidence(source_system_key),
        # Two shapes of loss a store cannot report on itself: a field the
        # decoder never projected leaves no row, and a composer no index binds
        # is excluded from ingest by design. Both read as absent-from-the-vendor
        # unless the report states them.
        "projection": projection_coverage(source_system_key),
        "unbound": unbound_composers(source_system_key),
        "repeated_prompts": repeated_prompts(conn),
    }
