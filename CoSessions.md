# CoSessions — note on scope

**Historical intent:** A place for deep technical detail on *sessions, LLM exchanges, tools, and logs* across products.

**Current split:** Vendor-specific **on-disk structure**, field semantics, scan/ingest behavior, quirks, and recommended access are documented per vendor:

| Vendor | Document |
|--------|----------|
| Claude Code | **CCSchema.md** |
| Codex CLI | **CodexSchema.md** |
| Cursor | **CursorSchema.md** |

**Unified normalized model** (after ingest): **CoSchema.md** + `sql/CoSchema.sql`.

Use **CoSessions.md** only as a **pointer** unless you reintroduce a single narrative doc; avoid duplicating tables that already live in `*Schema.md`.
