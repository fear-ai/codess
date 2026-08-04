from __future__ import annotations

import csv
import json
import sqlite3
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "demo_model_metrics.py"


def _store(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE events (
          interaction_id TEXT, actor_kind TEXT, content_role TEXT,
          event_at REAL, content_len INTEGER, event_kind TEXT,
          model_turn_id TEXT
        );
        CREATE TABLE model_turns (id TEXT PRIMARY KEY, model_config_id INTEGER);
        CREATE TABLE model_configurations (
          id INTEGER PRIMARY KEY, model_name_exact TEXT
        );
        """
    )
    models = (
        (1, "claude-fable-5"),
        (2, "claude-opus-4-8"),
        (3, "claude-sonnet-5"),
    )
    conn.executemany("INSERT INTO model_configurations VALUES (?, ?)", models)
    base = 1_783_234_800_000
    for index, (config_id, model) in enumerate(models, 1):
        turn = f"turn-{index}"
        interaction = f"interaction-{index}"
        prompt = base + index * 10_000
        conn.execute("INSERT INTO model_turns VALUES (?, ?)", (turn, config_id))
        conn.executemany(
            "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                (interaction, "human", "prompt", prompt, 100 * index,
                 "message.prompt", None),
                (interaction, "model", "response", prompt + 2_000 * index,
                 1_000 * index, "message.response", turn),
                (interaction, "model", "tool_request", prompt + 3_000 * index,
                 0, "tool.call", turn),
                (interaction, "model", "response", prompt + 5_000 * index,
                 500 * index, "message.response", turn),
            ),
        )
    conn.commit()
    conn.close()


def test_demo_model_metrics_generates_table_data_charts_and_manifest(tmp_path):
    store = tmp_path / "sessions_cc.db"
    output = tmp_path / "output"
    _store(store)
    result = subprocess.run(
        [
            sys.executable, str(TOOL), "--store", str(store),
            "--start", "2026-07-05", "--end", "2026-08-02",
            "--out-dir", str(output),
        ],
        text=True, capture_output=True, check=True,
    )
    report = json.loads(result.stdout)
    assert report["interactions"] == 3
    assert report["plotted_interactions"] == 2
    for name in (
        "model-latency.csv", "model-latency.md", "model-latency.svg",
        "prompt-response.csv", "prompt-response.svg", "manifest.json",
    ):
        assert (output / name).is_file()
    with (output / "model-latency.csv").open(newline="") as stream:
        latency = list(csv.DictReader(stream))
    assert [row["model"] for row in latency] == [
        "claude-fable-5", "claude-opus-4-8", "claude-sonnet-5",
    ]
    assert [row["interactions"] for row in latency] == ["1", "1", "1"]
    with (output / "prompt-response.csv").open(newline="") as stream:
        prompt_response = list(csv.DictReader(stream))
    assert {row["model"] for row in prompt_response} == {
        "claude-fable-5", "claude-opus-4-8",
    }
    assert "Claude Sonnet 5" not in (
        output / "prompt-response.svg"
    ).read_text(encoding="utf-8")
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["format"] == "codess.demo-model-metrics/1"
    assert manifest["selection"]["selection_kind"] == "store"
