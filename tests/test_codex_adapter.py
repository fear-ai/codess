"""Tests for Codex adapter."""

import json
import tempfile
from pathlib import Path

import pytest

from ingest.codex_adapter import get_session_meta, iter_codex_records, process_file


class TestIterCodexRecords:
    """iter_codex_records edge cases."""

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.jsonl"
        f.write_text("")
        assert list(iter_codex_records(f)) == []

    def test_skips_malformed_json(self, tmp_path):
        f = tmp_path / "bad.jsonl"
        f.write_text('{"type":"session_meta"}\nnot json\n{"type":"other"}\n')
        recs = list(iter_codex_records(f))
        assert len(recs) == 2


class TestGetSessionMeta:
    def test_from_session_meta(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write('{"type":"session_meta","payload":{"id":"abc","cwd":"/x/y"}}\n')
            path = Path(f.name)
        try:
            sid, cwd = get_session_meta(path)
            assert sid == "abc"
            assert cwd == "/x/y"
        finally:
            path.unlink()

    def test_fallback(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write('{"type":"other"}\n')
            path = Path(f.name)
        try:
            sid, cwd = get_session_meta(path)
            assert sid == path.stem
            assert cwd == "."
        finally:
            path.unlink()


class TestProcessFile:
    def test_user_and_developer(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write('{"type":"session_meta","payload":{"id":"s1","cwd":"/p"}}\n')
            f.write('{"type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"Hi"}]}}\n')
            f.write('{"type":"response_item","payload":{"type":"message","role":"developer","content":[{"type":"input_text","text":"Hello"}]}}\n')
            path = Path(f.name)
        try:
            events = list(process_file(path, "s1", "/p", {}))
            assert len(events) == 2
            assert events[0]["event_type"] == "user_message"
            assert events[0]["content"] == "Hi"
            assert events[1]["event_type"] == "assistant_message"
            assert events[1]["content"] == "Hello"
        finally:
            path.unlink()

    def test_skips_non_message_response_item(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write('{"type":"response_item","payload":{"type":"other","role":"user"}}\n')
            path = Path(f.name)
        try:
            events = list(process_file(path, "s1", "/p", {}))
            assert len(events) == 0
        finally:
            path.unlink()

    def test_event_msg_token_count_skipped(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write('{"type":"event_msg","payload":{"type":"token_count"}}\n')
            path = Path(f.name)
        try:
            events = list(process_file(path, "s1", "/p", {}))
            assert len(events) == 0
        finally:
            path.unlink()

    def test_event_msg_user_message(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write('{"type":"event_msg","payload":{"type":"user_message","info":"note"}}\n')
            path = Path(f.name)
        try:
            events = list(process_file(path, "s1", "/p", {}))
            assert len(events) == 1
            assert events[0]["event_type"] == "assistant_message"
            assert events[0]["subtype"] == "dialog"
        finally:
            path.unlink()

    def test_slash_command(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write('{"type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"/fix"}]}}\n')
            path = Path(f.name)
        try:
            events = list(process_file(path, "s1", "/p", {}))
            assert events[0]["subtype"] == "slash_command"
        finally:
            path.unlink()
