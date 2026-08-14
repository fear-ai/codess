"""Cross-store identity invariants."""

from codess.identity import (
    artifact_uri_id,
    event_entity_id,
    location_id,
    session_entity_id,
    source_observation_id,
    source_record_entity_id,
    source_revision_entity_id,
)


def test_artifact_uri_identity_is_stable_and_namespaced():
    value = artifact_uri_id("file:///tmp/example.txt")
    assert value == artifact_uri_id("file:///tmp/example.txt")
    assert value.startswith("codess:artifact:sha256:")


def test_same_vendor_session_has_same_global_id_across_paths_and_databases():
    first = session_entity_id("cursor.composer", "composer-1")
    second = session_entity_id("cursor.composer", "composer-1")
    assert first == second
    assert first.startswith("codess:session:sha256:")


def test_same_vendor_id_in_different_source_namespaces_does_not_collide():
    assert session_entity_id("cursor.composer", "same") != session_entity_id(
        "anthropic.claude-code", "same"
    )


def test_event_and_observation_ids_have_distinct_scopes():
    session = session_entity_id("openai.codex", "s1")
    event = event_entity_id(session, "e1")
    one = source_observation_id(event, "openai.codex", "/one.jsonl", "sha256:a", "p1")
    two = source_observation_id(event, "openai.codex", "/two.jsonl", "sha256:a", "p1")
    assert one != two
    assert event != one


def test_location_is_machine_and_path_specific_not_project_identity(tmp_path):
    assert location_id("machine-a", tmp_path) != location_id("machine-b", tmp_path)


def test_source_revision_and_record_identities_are_layered():
    revision = source_revision_entity_id("openai.codex", "/one.jsonl", "sha256:a")
    assert revision != source_revision_entity_id(
        "openai.codex", "/one.jsonl", "sha256:b"
    )
    assert source_record_entity_id(revision, "line:1") != source_record_entity_id(
        revision, "line:2"
    )
