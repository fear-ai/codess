"""Cross-store identity invariants."""

import pytest

from codess.identity import (
    IDENTITY_FORMAT_TAG,
    artifact_uri_id,
    content_object_id,
    event_entity_id,
    location_id,
    observation_row_id,
    processing_run_id,
    session_entity_id,
    source_key,
    source_observation_id,
    source_record_entity_id,
    source_revision_entity_id,
    workspace_binding_id,
)


def test_artifact_uri_identity_is_stable_and_namespaced():
    value = artifact_uri_id("file:///tmp/example.txt")
    assert value == artifact_uri_id("file:///tmp/example.txt")
    assert value.startswith("codess:artifact:id1:")


def test_same_vendor_session_has_same_global_id_across_paths_and_databases():
    first = session_entity_id("cursor.composer", "composer-1")
    second = session_entity_id("cursor.composer", "composer-1")
    assert first == second
    assert first.startswith("codess:session:id1:")


def test_identity_names_its_derivation_not_its_algorithm():
    """The qualifier states which scheme derived the value.

    Identities are compared across stores, so a reader holding one must be
    able to tell which derivation produced it; a digest alone cannot say. The
    algorithm is deliberately absent -- `hashing` owns that choice, and naming
    it here would make changing it a wire-format change.
    """
    value = session_entity_id("openai.codex", "s1")
    _, kind, fmt, digest = value.split(":")
    assert (kind, fmt) == ("session", "id1")
    assert "sha256" not in value
    assert len(digest) == 64


def test_same_vendor_id_in_different_source_namespaces_does_not_collide():
    assert session_entity_id("cursor.composer", "same") != session_entity_id(
        "anthropic.claude-code", "same"
    )


def test_event_and_observation_ids_have_distinct_scopes():
    session = session_entity_id("openai.codex", "s1")
    event = event_entity_id(session, "e1")
    one = source_observation_id(event, "openai.codex", "/one.jsonl", "digest-fingerprint:a", "p1")
    two = source_observation_id(event, "openai.codex", "/two.jsonl", "digest-fingerprint:a", "p1")
    assert one != two
    assert event != one


def test_location_is_machine_and_path_specific_not_project_identity(tmp_path):
    assert location_id("machine-a", tmp_path) != location_id("machine-b", tmp_path)


def test_source_revision_and_record_identities_are_layered():
    revision = source_revision_entity_id("openai.codex", "/one.jsonl", "digest-fingerprint:a")
    assert revision != source_revision_entity_id(
        "openai.codex", "/one.jsonl", "digest-fingerprint:b"
    )
    assert source_record_entity_id(revision, "line:1") != source_record_entity_id(
        revision, "line:2"
    )


def test_source_revision_identity_survives_a_different_machine_root():
    """The same Source under two machine roots derives one identity.

    `entity_id` means a value derived from vendor-stated facts, so it must not
    depend on the machine a file was read on. Deriving it from the absolute
    path gave every machine its own identity for the same Source, which made
    cross-store deduplication on `sources.entity_id` fail silently.
    """
    assert source_revision_entity_id(
        "anthropic.claude-code",
        "/Users/one/.claude/projects/proj/session.jsonl",
        "digest-fingerprint:abc",
    ) == source_revision_entity_id(
        "anthropic.claude-code",
        "/home/two/.claude/projects/proj/session.jsonl",
        "digest-fingerprint:abc",
    )


def test_source_revision_identity_separates_files_sharing_content():
    """Byte-identical Sources at different names stay distinct.

    A Claude subagent transcript can be byte-identical to its parent, so the
    fingerprint alone does not identify a Source; the vendor-assigned name
    within its store is what separates them. Deriving from the revision alone
    collapsed the two and violated `sources.source_entity_id`'s UNIQUE
    constraint mid-ingest.
    """
    assert source_revision_entity_id(
        "anthropic.claude-code", "/root/proj/parent-session.jsonl", "digest-fingerprint:same"
    ) != source_revision_entity_id(
        "anthropic.claude-code", "/root/proj/child-session.jsonl", "digest-fingerprint:same"
    )


class TestSourceKey:
    """The portable part of a Source location.

    `source_revision_entity_id` derives from this rather than the absolute
    path, so what it keeps and what it discards is the whole of the format's
    portability claim.
    """

    def test_machine_root_discarded(self):
        assert source_key("/Users/one/.claude/projects/proj/s.jsonl") == "proj/s.jsonl"
        assert source_key("/home/two/.claude/projects/proj/s.jsonl") == "proj/s.jsonl"

    def test_vendor_assigned_name_kept(self):
        """Two segments, because one is not enough to separate siblings.

        A Claude subagent transcript and its parent sit in different
        directories under one Project slug; keeping only the filename would
        merge Sources that the vendor distinguishes by directory.
        """
        assert source_key("/r/proj/subagents/child.jsonl") == "subagents/child.jsonl"
        assert source_key("/r/proj/parent.jsonl") == "proj/parent.jsonl"

    def test_short_and_empty_paths(self):
        assert source_key("only.jsonl") == "only.jsonl"
        assert source_key("") == ""

    def test_relative_and_absolute_agree(self):
        """The same trailing name resolves alike however the path was written."""
        assert source_key("proj/s.jsonl") == source_key("/a/b/c/proj/s.jsonl")


class TestQualifiedIdentityHelpers:
    """The identity constructors that replaced hand-composed prefixes.

    Four sites built `codess:<kind>:<algorithm>:<digest>` by hand, which is
    how the algorithm name reached values nothing recomputes. Each now calls
    this module, so the format is decided once.
    """

    def test_every_identity_carries_the_format_tag(self):
        values = [
            session_entity_id("openai.codex", "s1"),
            event_entity_id("codess:session:id1:x", "e1"),
            artifact_uri_id("file:///x"),
            workspace_binding_id("p1", "cursor.composer", "w1"),
            processing_run_id("p1", "digest", "actions"),
            content_object_id("a" * 64),
            observation_row_id("b" * 64),
            source_revision_entity_id("openai.codex", "/a/b.jsonl", "rev"),
            source_record_entity_id("codess:source-revision:id1:x", "line:1"),
        ]
        for value in values:
            assert value.split(":")[2] == IDENTITY_FORMAT_TAG
            assert "sha256" not in value

    def test_each_kind_has_its_own_namespace(self):
        """A shared digest input must not collide across entity kinds."""
        kinds = {value.split(":")[1] for value in (
            session_entity_id("s", "x"),
            artifact_uri_id("x"),
            workspace_binding_id("p", "s", "x"),
            processing_run_id("p", "d", "a"),
            content_object_id("c" * 64),
            observation_row_id("o" * 64),
        )}
        assert kinds == {
            "session", "artifact", "workspace", "processing", "content",
            "observation",
        }

    def test_workspace_binding_distinguishes_each_component(self):
        base = workspace_binding_id("p1", "cursor.composer", "w1")
        assert base != workspace_binding_id("p2", "cursor.composer", "w1")
        assert base != workspace_binding_id("p1", "anthropic.claude-code", "w1")
        assert base != workspace_binding_id("p1", "cursor.composer", "w2")
        assert base == workspace_binding_id("p1", "cursor.composer", "w1")

    def test_processing_run_reflects_policy_and_actions(self):
        base = processing_run_id("p1", "policy-a", "actions-a")
        assert base != processing_run_id("p1", "policy-b", "actions-a")
        assert base != processing_run_id("p1", "policy-a", "actions-b")
        assert base == processing_run_id("p1", "policy-a", "actions-a")

    def test_processing_run_accepts_no_project(self):
        """A run outside any Project still gets an identity, not a crash."""
        assert processing_run_id(None, "policy", "actions").startswith(
            f"codess:processing:{IDENTITY_FORMAT_TAG}:"
        )

    def test_content_and_observation_apply_the_qualifier_only(self):
        """Both are named for a digest the caller already computed.

        They qualify rather than re-derive, so the digest must survive intact
        -- a caller looking up by content digest depends on it.
        """
        digest = "c" * 64
        assert content_object_id(digest).endswith(digest)
        assert observation_row_id(digest).endswith(digest)


class TestIdentityRejectsEmptyComponents:
    """An identity derived from nothing would collide with every other."""

    @pytest.mark.parametrize("call", [
        lambda: session_entity_id("", "s1"),
        lambda: session_entity_id("openai.codex", ""),
        lambda: event_entity_id("", "e1"),
        lambda: event_entity_id("session", ""),
        lambda: artifact_uri_id(""),
        lambda: source_revision_entity_id("", "/a", "rev"),
        lambda: source_revision_entity_id("openai.codex", "/a", ""),
    ])
    def test_missing_component_raises(self, call):
        with pytest.raises(ValueError):
            call()
