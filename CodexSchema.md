# CodexSchema — OpenAI Codex CLI session storage

Vendor-specific structure for **Codex CLI** sessions. Normalized ingest: `src/codess/adapters/codex.py`. Scan: `src/codess/scan.py` (`_session_metrics_codex`).

**Version note:** Codex evolves; first-line `session_meta` and `response_item` shapes are assumed as below.

---

## 1. Document metadata

| Field | Value |
|-------|--------|
| **Vendor** | OpenAI Codex CLI |
| **Primary paths** | `~/.codex/sessions/**/*.jsonl` (override: `CODESS_CODEX_SESSIONS`) |
| **Encoding** | UTF-8 JSONL |
| **Time basis** | `timestamp` on lines: numeric (s or ms) or ISO 8601 string |

---

## 2. Storage layout

| Pattern | Role |
|---------|------|
| Flat or shallow tree of `*.jsonl` | **One file = one session** |
| First non-empty line | Must be `{"type":"session_meta",...}` for scan matching |

There is **no** subagent / sidechain concept in this layout (unlike CC).

---

## 3. Recommended access

| Method | Use |
|--------|-----|
| **Codess scan** | `codess scan --dir <work>`; matches `session_meta.payload.cwd` to project |
| **Codess ingest** | `codess ingest --dir <project>`; collects files whose `cwd` resolves to project root |
| **Direct read** | Open file; read first line for `session_meta`, then stream lines |

---

## 4. session_meta (first line)

| Field path | Type | Notes |
|------------|------|--------|
| `type` | string | Must be `session_meta` |
| `payload.id` | string | Session id fallback |
| `payload.cwd` | string | Project directory; resolved and compared to scan path |
| `timestamp` | number or string | Session time for `--days` filter |

---

## 5. Subsequent lines (record types)

Ingest adapter primarily uses:

| `type` | Role |
|--------|------|
| `session_meta` | Skipped after first line |
| `response_item` | When `payload.type == "message"`, maps to user/developer messages |
| `event_msg` | Partially normalized (e.g. dialog-style assistant events) |

**Observed ranges:** Line counts per file vary widely (10–10⁵+); non-empty lines ≈ “event” count for scan.

---

## 6. Scan metrics (Codess)

| Metric | Definition |
|--------|------------|
| **Sessions** | Count of `*.jsonl` files whose first line is `session_meta` and `cwd` matches project |
| **Events** | Count of non-empty lines per matching file (includes all record types on lines) |
| **Size (mb)** | Sum of `file.stat().st_size` for matching files |
| **days_ago** | From max `timestamp` among matching sessions (parsed to ms) |
| **span_weeks** | Spread of timestamps across matching files |

---

## 7. Quirks & limitations

- Timestamp formats mixed (Unix s, Unix ms, ISO); parser normalizes to ms where possible.
- “Events” in scan ≠ only chat messages; includes structural lines.
- History file `~/.codex/history.jsonl` (if present) is **not** the same as session store; CodexSchema applies to `sessions/`.

---

## 8. Cross-reference

| Topic | Document |
|-------|----------|
| Unified DB columns | **CoSchema.md** |
| Claude Code storage | **CCSchema.md** |
| Cursor storage | **CursorSchema.md** |
| Work plan | **CoPlan.md** |
