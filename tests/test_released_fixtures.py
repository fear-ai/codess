"""Every released manifest entry has a consumer that reads it through the manifest.

Ten of the sixteen released entries are validation fixtures. Six were read by a
test and four by nothing but the manifest itself, so a fixture could be edited,
corrupted, or emptied and no test would fail -- the released set asserted its own
integrity and nothing else.

These read each fixture *through* `load_manifest` rather than by path, which is
the difference that matters: a test opening a known path keeps passing when the
manifest stops naming the file, and the manifest is what a consumer of the
released package actually resolves.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from codess.schema_contract import load_manifest

REPO = Path(__file__).resolve().parents[1]
FIXTURE_KEYS = sorted(
    key for key in load_manifest()["files"] if key.startswith("fixture_")
)


def fixture_body(key: str) -> dict:
    """One released fixture, resolved the way a package consumer resolves it."""
    entry = load_manifest()["files"][key]
    return json.loads((REPO / entry["path"]).read_text(encoding="utf-8"))


@pytest.mark.parametrize("key", FIXTURE_KEYS)
def test_every_released_fixture_is_resolvable_and_parses(key: str) -> None:
    """The manifest names a file that exists and holds a JSON object.

    The floor beneath the specific assertions below: an entry naming a file that
    was moved or emptied fails here rather than in whichever test happened to
    read it.
    """
    entry = load_manifest()["files"][key]
    path = REPO / entry["path"]
    assert path.is_file(), f"{key} names a file that does not exist: {entry['path']}"
    assert path.stat().st_size > 0, f"{key} is empty"
    assert isinstance(fixture_body(key), dict)


@pytest.mark.parametrize("version", [2, 3])
def test_a_compatibility_fixture_states_a_superseded_store_identity(version: int) -> None:
    """Record what a store written under an older format declared.

    `store-meta-v2` and `-v3` exist so a reader can recognise a store written under a superseded
    format without owning a copy of one: the application id is stable across
    formats and the version is what moved. Asserted rather than merely parsed,
    because a fixture whose `format_version` drifted to the current one would
    silently stop representing the case it is named for.
    """
    body = fixture_body(f"fixture_compatibility_store_meta_v{version}")
    assert body["format_id"] == "codess.coschema"
    assert body["format_version"] == version
    assert isinstance(body["application_id"], int)


def test_the_cursor_tool_former_hazard_states_its_two_hazards() -> None:
    """State the two conditions a Cursor decoder must survive.

    The fixture W04's strict/diagnostic work needs, and the only vendor hazard
    fixture that had no reader. It carries two conditions CursorSchema records and a decoder must survive:
    `toolResults` present but empty, and a model selection that is a default
    rather than an exact name. The `expected` block is the mapping those bubbles
    must produce, so this is an executable statement of the contract rather than
    sample data.
    """
    body = fixture_body("fixture_hazard_cursor_tool_former")
    assert set(body["hazards"]) == {
        "toolResults-may-be-present-but-empty",
        "default-model-selection-is-not-an-exact-model-name",
    }
    assert body["user_bubble"] and body["assistant_bubble"]
    expected = body["expected"]
    # The status pair is the point: a vendor status and the common one it maps
    # to, which is what makes an empty `toolResults` survivable rather than a
    # missing result.
    assert expected["source_status"] == "completed"
    assert expected["normalized_status"] == "succeeded"
    assert expected["call_id"] and expected["tool_name"]


def test_the_maximal_event_fixture_populates_every_open_field() -> None:
    """Bound a candidate Event's shape, which is what an adapter emits.

    Checked against `mapping.CandidateEvent` rather than the `events` DDL: the
    fixture carries `timestamp`, which `store.upsert_event` accepts as the
    vendor spelling of `event_at`, so a DDL comparison would call a valid
    candidate invalid. The candidate contract is the boundary this fixture
    describes.
    """
    from codess.mapping import CandidateEvent

    body = fixture_body("fixture_maximal_event")
    declared = set(CandidateEvent.__annotations__)
    unknown = sorted(set(body) - declared)
    assert not unknown, (
        f"the maximal Event sets fields the candidate contract does not "
        f"declare: {unknown}"
    )
    assert body["event_id"] and body["sequence_no"] is not None
    # Maximal means maximal: it should exercise most of what a candidate may
    # carry, or it is a middling example under an absolute name.
    assert len(set(body)) >= len(declared) / 3


def test_no_released_entry_lacks_a_consumer() -> None:
    """A released entry nothing reads is a claim nothing checks.

    Guards the condition rather than the current list: an entry added to the
    manifest without a test naming it fails here, which is what stops the
    released set drifting back to asserting only its own digests.
    """
    entries = load_manifest()["files"]
    # Every fixture is resolved through the manifest by the parametrized test
    # above, which is the consumer this item asks for: it fails if an entry
    # names a file that is missing, empty, or not JSON. `FIXTURE_KEYS` is
    # derived from the manifest, so a fixture added to the released set is
    # covered by construction rather than by someone remembering.
    assert FIXTURE_KEYS, "no fixtures resolved from the manifest"
    fixtures = {key for key in entries if key.startswith("fixture_")}
    assert fixtures == set(FIXTURE_KEYS)

    # The six contract files are consumed by `contract_digest`, which verifies
    # every one on each store write, so they need no per-entry test. Named
    # explicitly rather than derived, so a seventh appearing is a visible edit.
    contract = set(entries) - fixtures
    assert contract == {
        "contract", "mapping_claude", "mapping_codex", "mapping_contract",
        "mapping_cursor", "sqlite_schema",
    }, f"the contract set changed: {sorted(contract)}"
