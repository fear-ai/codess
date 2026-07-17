"""Derived vendor token observations remain explicit about confidence."""

import json
import sqlite3

from codess.token_usage import collect_token_usage


def _lines(path, values):
    path.write_text("".join(json.dumps(value) + "\n" for value in values))


def _source_store(path, sources):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE sources(source_system_id TEXT, source_uri TEXT)")
    conn.executemany("INSERT INTO sources VALUES (?, ?)", sources)
    conn.commit()
    conn.close()


def test_collects_claude_monthly_and_deduplicates(tmp_path):
    source = tmp_path / "claude.jsonl"
    record = {
        "type": "assistant", "timestamp": "2026-07-01T00:00:00Z",
        "requestId": "r1",
        "message": {
            "id": "m1", "model": "claude-opus-4-1",
            "usage": {
                "input_tokens": 10, "cache_creation_input_tokens": 3,
                "cache_read_input_tokens": 4, "output_tokens": 2,
            },
        },
    }
    _lines(source, [record, record])
    store = tmp_path / "store.db"
    _source_store(store, [("anthropic.claude-code", str(source))])
    report = collect_token_usage([store])
    claude = report["vendors"][0]
    assert claude["confidence"] == "local_observed"
    assert claude["monthly"] == [{
        "month": "2026-07", "model": "claude-opus-4-1",
        "input_tokens": 10, "cached_input_tokens": 4,
        "cache_creation_input_tokens": 3, "output_tokens": 2,
        "reasoning_output_tokens": 0, "total_tokens": 19,
        "usage_records": 1,
    }]


def test_codex_uses_positive_cumulative_deltas(tmp_path):
    source = tmp_path / "codex.jsonl"
    _lines(source, [
        {"type": "turn_context", "payload": {"model": "gpt-5"}},
        {"type": "event_msg", "timestamp": "2026-07-01T00:00:00Z", "payload": {
            "type": "token_count", "info": {"total_token_usage": {
                "input_tokens": 10, "cached_input_tokens": 3,
                "output_tokens": 2, "reasoning_output_tokens": 1,
                "total_tokens": 12,
            }},
        }},
        {"type": "event_msg", "timestamp": "2026-07-01T00:01:00Z", "payload": {
            "type": "token_count", "info": {"total_token_usage": {
                "input_tokens": 25, "cached_input_tokens": 8,
                "output_tokens": 5, "reasoning_output_tokens": 2,
                "total_tokens": 30,
            }},
        }},
    ])
    store = tmp_path / "store.db"
    _source_store(store, [("openai.codex", str(source))])
    codex = collect_token_usage([store])["vendors"][1]
    assert codex["confidence"] == "local_derived_provisional"
    assert codex["monthly"][0]["input_tokens"] == 25
    assert codex["monthly"][0]["total_tokens"] == 30
    assert codex["monthly"][0]["usage_records"] == 2


def test_cursor_is_explicitly_unavailable(tmp_path):
    report = collect_token_usage([])
    cursor = report["vendors"][2]
    assert cursor["availability"] == "unavailable"
    assert cursor["monthly"] == []
