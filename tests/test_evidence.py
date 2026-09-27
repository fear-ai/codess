"""Evidence inventory inputs (codess.evidence)."""

import pytest

import codess.evidence as evidence


class _StopAuditError(Exception):
    pass


def _captured_codex_roots(tmp_path, monkeypatch):
    """Stop the inventory at the first Codex audit and return the roots it was given."""

    def audit(roots):
        raise _StopAuditError(list(roots))

    monkeypatch.setattr(evidence, "audit_parentage", audit)
    with pytest.raises(_StopAuditError) as stopped:
        evidence.build_evidence_inventory(tmp_path / "store", cursor_db=tmp_path / "state.vscdb")
    return stopped.value.args[0]


def test_codex_roots_default_to_the_configured_session_trees(tmp_path, monkeypatch):
    """The audit reads the trees CODESS_CODEX_SESSIONS names, not the home-relative vendor default."""
    active = tmp_path / "sessions"
    archive = tmp_path / "archived"
    monkeypatch.setattr(evidence, "CODEX_SESSIONS", active, raising=False)
    monkeypatch.setattr(evidence, "CODEX_ARCHIVED_SESSIONS", archive, raising=False)
    assert _captured_codex_roots(tmp_path, monkeypatch) == [("active", active), ("archive", archive)]


def test_no_archive_root_when_none_is_configured(tmp_path, monkeypatch):
    active = tmp_path / "sessions"
    monkeypatch.setattr(evidence, "CODEX_SESSIONS", active, raising=False)
    monkeypatch.setattr(evidence, "CODEX_ARCHIVED_SESSIONS", None, raising=False)
    assert _captured_codex_roots(tmp_path, monkeypatch) == [("active", active)]
