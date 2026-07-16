"""Cross-store identity invariants."""

from codess.identity import (
    global_event_id, global_session_id, location_id, source_observation_id,
)


def test_same_vendor_session_has_same_global_id_across_paths_and_databases():
    first = global_session_id("cursor.composer", "composer-1")
    second = global_session_id("cursor.composer", "composer-1")
    assert first == second
    assert first.startswith("codess:session:sha256:")


def test_same_vendor_id_in_different_source_namespaces_does_not_collide():
    assert global_session_id("cursor.composer", "same") != global_session_id(
        "anthropic.claude-code", "same"
    )


def test_event_and_observation_ids_have_distinct_scopes():
    session = global_session_id("openai.codex", "s1")
    event = global_event_id(session, "e1")
    one = source_observation_id(event, "openai.codex", "/one.jsonl", "sha256:a", "p1")
    two = source_observation_id(event, "openai.codex", "/two.jsonl", "sha256:a", "p1")
    assert one != two
    assert event != one


def test_location_is_machine_and_path_specific_not_project_identity(tmp_path):
    assert location_id("machine-a", tmp_path) != location_id("machine-b", tmp_path)
