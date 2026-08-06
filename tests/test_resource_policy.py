"""Versioned ingest resource-policy loading and precedence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from codess.project import build_ingest_run_options
from codess.resource_policy import (
    BUILTIN_MAXIMUMS,
    RESOURCE_POLICY_FORMAT,
    ResourcePolicyError,
    load_resource_policy,
)


def _args(**values):
    defaults = {
        "stop": False,
        "force": False,
        "min_size": 0,
        "debug": False,
        "redact": False,
        "resource_policy": None,
        "no_resource_limits": False,
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


def test_builtins_are_complete_and_separate_cursor_from_transcripts():
    policy = load_resource_policy()
    assert policy.maximums == BUILTIN_MAXIMUMS
    assert policy.maximums["transcript_bytes"] == 256 * 1024**2
    assert policy.maximums["cursor_container_bytes"] == 10 * 1024**3
    assert policy.origins == {key: "built-in" for key in BUILTIN_MAXIMUMS}


def test_partial_file_overrides_and_null_disables_one_limit(tmp_path):
    path = tmp_path / "resources.json"
    payload = json.dumps({
        "format": RESOURCE_POLICY_FORMAT,
        "maximums": {
            "transcript_bytes": 1234,
            "events_per_session": None,
        },
    }).encode()
    path.write_bytes(payload)

    policy = load_resource_policy(path)

    assert policy.maximums["transcript_bytes"] == 1234
    assert policy.maximums["events_per_session"] is None
    assert policy.maximums["events_per_source"] == 200_000
    assert policy.origins["transcript_bytes"] == "policy-file"
    assert policy.origins["events_per_source"] == "built-in"
    assert policy.file_path == str(path.resolve())
    assert policy.file_sha256 == hashlib.sha256(payload).hexdigest()


@pytest.mark.parametrize(
    "value, message",
    [
        ({"format": "wrong", "maximums": {}}, "format must be"),
        ({"format": RESOURCE_POLICY_FORMAT}, "must contain maximums"),
        (
            {
                "format": RESOURCE_POLICY_FORMAT,
                "maximums": {"unknown_limit": 1},
            },
            "unknown maximum",
        ),
        (
            {
                "format": RESOURCE_POLICY_FORMAT,
                "maximums": {"transcript_bytes": 0},
            },
            "greater than zero",
        ),
        (
            {
                "format": RESOURCE_POLICY_FORMAT,
                "maximums": {"transcript_bytes": True},
            },
            "integer or null",
        ),
    ],
)
def test_invalid_policy_is_rejected(tmp_path, value, message):
    path = tmp_path / "resources.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ResourcePolicyError, match=message):
        load_resource_policy(path)


def test_precedence_is_file_then_environment_then_command_line(
    tmp_path, monkeypatch
):
    path = tmp_path / "resources.json"
    path.write_text(json.dumps({
        "format": RESOURCE_POLICY_FORMAT,
        "maximums": {
            "transcript_bytes": 100,
            "events_per_source": 200,
        },
    }), encoding="utf-8")
    monkeypatch.setenv("CODESS_MAX_TRANSCRIPT_BYTES", "300")
    monkeypatch.setenv("CODESS_MAX_EVENTS_PER_SOURCE", "400")

    options = build_ingest_run_options(_args(
        resource_policy=str(path),
        max_source_bytes=500,
    ))

    assert options["max_source_bytes"] == 500
    assert options["max_events_per_source"] == 400
    assert options["resource_policy"]["origins"]["transcript_bytes"] == "command-line"
    assert options["resource_policy"]["origins"]["events_per_source"] == "environment"
    assert options["resource_policy"]["origins"]["events_per_session"] == "built-in"


def test_no_resource_limits_disables_every_maximum(tmp_path):
    path = tmp_path / "resources.json"
    path.write_text(json.dumps({
        "format": RESOURCE_POLICY_FORMAT,
        "maximums": {"events_per_session": 12},
    }), encoding="utf-8")
    options = build_ingest_run_options(_args(
        resource_policy=str(path),
        no_resource_limits=True,
    ))
    assert options["max_source_bytes"] is None
    assert options["max_cursor_container_bytes"] is None
    assert options["max_events_per_source"] is None
    assert options["max_events_per_session"] is None
    assert options["max_context_content_chars"] is None
    assert set(options["resource_policy"]["origins"].values()) == {
        "--no-resource-limits"
    }


def test_contract_and_implementation_use_the_same_maximum_names():
    contract = json.loads(
        (
            Path(__file__).parents[1]
            / "schema/resource-policy-contract.json"
        ).read_text(encoding="utf-8")
    )
    assert set(contract["properties"]["maximums"]["properties"]) == set(
        BUILTIN_MAXIMUMS
    )


def test_approved_event_and_context_builtins_are_exact_decimal_values():
    assert BUILTIN_MAXIMUMS["events_per_source"] == 200_000
    assert BUILTIN_MAXIMUMS["events_per_session"] == 100_000
    assert BUILTIN_MAXIMUMS["context_content_chars"] == 250_000
