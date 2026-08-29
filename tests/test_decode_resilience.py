"""A vendor data surprise must not crash the program.

Codess reads records it did not write, from formats that change between
releases. A decoder is strict about *meaning* -- it does not guess an Actor or a
relationship -- and must be tolerant about *shape*: a field holding a string
where an object belongs is an observation about the vendor, and raising from
inside the decode discards every Session in that Source rather than the one
record that was malformed.

These fuzz each adapter with shapes a vendor could plausibly emit, and assert
the run completes and reports. Found by a real ingest: `(value or {}).get(...)`
reads as a null guard and is not one, so `"toolFormerData": "a string"` raised
`AttributeError` and aborted an entire Cursor source.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

HOSTILE_CLAUDE = [
    {"type": "assistant", "message": {"role": "assistant",
                                      "content": [{"type": "text", "text": "ok"}]}},
    # A nested object stated as a string.
    {"type": "assistant", "message": "a string, not an object"},
    {"type": "user", "message": {"content": "str"}, "origin": "not-a-dict"},
    # A vendor identifier stated with the wrong scalar type.
    {"type": "user", "message": {"content": [{"type": "tool_result",
                                              "tool_use_id": 1}]}},
    {"type": "assistant", "message": {"content": [{"type": "tool_use",
                                                   "input": "str", "name": None}]}},
    {"type": "system", "subtype": "compact_boundary", "compactMetadata": "str"},
    {"type": "assistant", "timestamp": {"bad": 1}, "message": {"content": []}},
    {"type": "user", "message": {"content": [{"type": "text", "text": None}]}},
    # A record that is valid JSON and not an object, which JSONL permits.
    [1, 2, 3],
    "a bare string record",
    42,
    None,
]

HOSTILE_CODEX = [
    {"type": "session_meta", "payload": {"id": "s1", "cwd": "/tmp"}},
    {"type": "session_meta", "payload": "a string"},
    {"type": "response_item", "payload": {"type": "message", "content": "str"}},
    {"type": "response_item", "payload": {"type": "reasoning", "summary": "str"}},
    {"type": "event_msg", "payload": [1, 2]},
    {"type": "turn_context", "payload": {"model": {"nested": "wrong"}}},
    {"type": "compacted", "payload": {"replacement_history": "str"}},
    {"type": "response_item", "payload": {"type": "function_call",
                                          "arguments": {"a": 1}}},
    [1, 2, 3],
    "a bare string record",
]

HOSTILE_CURSOR = [
    ("composerData:c1", {"composerId": "c1", "modelConfig": {"modelName": "m"}}),
    ("bubbleId:c1:b1", {"type": 2, "text": "ok",
                        "toolFormerData": {"toolCallId": "t1", "name": "read",
                                           "status": "completed"}}),
    ("bubbleId:c1:b2", {"type": "NOT-AN-INT", "text": {"nested": "wrong"}}),
    # The shape that aborted a real Source.
    ("bubbleId:c1:b3", {"type": 2, "toolFormerData": "a string, not an object"}),
    ("bubbleId:c1:b4", {"type": 2, "thinking": 12345}),
    ("bubbleId:c1:b5", [1, 2, 3]),
    ("bubbleId:c1:b9", {"type": 2, "tokenCount": "nope", "createdAt": {"bad": 1}}),
    ("bubbleId:c1:b10", {"type": 2, "timingInfo": "str", "context": "str",
                         "codeBlocks": "str"}),
    ("bubbleId:c1:b11", {"type": 2, "modelInfo": [1], "conversationSummary": "s"}),
]


def _jsonl(tmp_path, name, records):
    path = tmp_path / name
    body = "\n".join(json.dumps(record) for record in records)
    # A truncated final line, which a killed writer leaves behind.
    path.write_text(body + "\n{truncated\n", encoding="utf-8")
    return path


class TestClaudeDecodeSurvivesHostileRecords:
    def test_it_completes_and_reports(self, tmp_path):
        from codess.adapters.cc import process_file

        path = _jsonl(tmp_path, "cc.jsonl", HOSTILE_CLAUDE)
        opts = {"diagnostics": {}, "record_diagnostics": []}
        events = list(process_file(path, "s1", opts))
        # The well-formed record still decodes: one bad record must not cost
        # the Session it sits in.
        assert events
        assert opts["diagnostics"]["malformed_records"] >= 4

    def test_a_non_object_record_is_counted_rather_than_raised(self, tmp_path):
        """JSONL guarantees valid JSON, not an object."""
        from codess.adapters.cc import iter_cc_records

        path = _jsonl(tmp_path, "cc.jsonl", [[1, 2], "str", {"type": "user"}])
        diagnostics: dict[str, int] = {}
        records = list(iter_cc_records(path, diagnostics, warn=False))
        assert [record["type"] for _line, record, _raw in records] == ["user"]
        assert diagnostics["malformed_records"] == 3


class TestCodexDecodeSurvivesHostileRecords:
    def test_it_completes_and_reports(self, tmp_path):
        from codess.adapters.codex import process_file

        path = _jsonl(tmp_path, "cx.jsonl", HOSTILE_CODEX)
        opts = {"diagnostics": {}, "record_diagnostics": []}
        events = list(process_file(path, "s1", "/tmp", opts))
        assert events
        assert opts["diagnostics"]["malformed_records"] >= 1


class TestCursorDecodeSurvivesHostileRecords:
    def _store(self, tmp_path):
        path = tmp_path / "state.vscdb"
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value BLOB)")
        for key, value in HOSTILE_CURSOR:
            conn.execute(
                "INSERT INTO cursorDiskKV VALUES (?,?)", (key, json.dumps(value)),
            )
        # A null value and a binary body, both measured in the real store.
        conn.execute("INSERT INTO cursorDiskKV VALUES ('bubbleId:c1:b7', NULL)")
        conn.execute(
            "INSERT INTO cursorDiskKV VALUES ('bubbleId:c1:b8', ?)",
            (b"\x00\x01\x02binary",),
        )
        conn.execute(
            "INSERT INTO cursorDiskKV VALUES ('bubbleId:c1:b6', '{truncated')",
        )
        conn.commit()
        conn.close()
        return path

    def test_it_completes_and_reports(self, tmp_path):
        from codess.adapters.cursor import process_db

        path = self._store(tmp_path)
        opts = {"diagnostics": {}, "record_diagnostics": []}
        events = list(process_db(path, "/tmp/p", opts))
        assert events
        assert opts["diagnostics"]["malformed_records"] >= 3

    def test_a_string_where_an_object_belongs_does_not_abort_the_source(
        self, tmp_path,
    ):
        """The exact shape that aborted a real Cursor source.

        `(data.get("toolFormerData") or {}).get(...)` guards absence and not
        type, so a string raised `AttributeError` from inside the decode and
        the whole Source was rolled back.
        """
        from codess.adapters.cursor import process_db

        path = tmp_path / "state.vscdb"
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value BLOB)")
        for key, value in (
            ("bubbleId:c1:b1", {"type": 2, "text": "kept",
                                "toolFormerData": {"toolCallId": "t",
                                                   "name": "read",
                                                   "status": "completed"}}),
            ("bubbleId:c1:b2", {"type": 2, "toolFormerData": "a string"}),
        ):
            conn.execute(
                "INSERT INTO cursorDiskKV VALUES (?,?)", (key, json.dumps(value)),
            )
        conn.commit()
        conn.close()
        opts = {"diagnostics": {}, "record_diagnostics": []}
        events = list(process_db(path, "/tmp/p", opts))
        assert any((event.get("content") or "") == "kept" for _sid, event in events)


class TestFieldStateGuardsRecordType:
    """The narrowest point every vendor field passes through."""

    @pytest.mark.parametrize("record", ["a string", [1, 2], 42, None])
    def test_a_non_mapping_record_reads_as_absent(self, record):
        from codess import field_state

        value, state = field_state.get_state(record, "anything")
        assert value is None
        assert state == field_state.ABSENT
