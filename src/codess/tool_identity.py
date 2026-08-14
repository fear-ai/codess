"""Bounded relational keys derived from vendor tool-invocation identifiers."""

from __future__ import annotations

from codess.hashing import codess_bytes_hash

SOURCE_CALL_ID_MAX_BYTES = 100
_DIGEST_BITS = 256
_DIGEST_HEX_CHARS = _DIGEST_BITS // 4
_SUFFIX_PREFIX = "~sha256:"


def bounded_source_call_id(
    value: object,
    *,
    max_bytes: int = SOURCE_CALL_ID_MAX_BYTES,
) -> str:
    """Return a deterministic UTF-8 key no larger than ``max_bytes``.

    Short identifiers remain byte-for-byte unchanged. Long identifiers retain
    a readable prefix and the full SHA-256 digest so equal prefixes do not
    create a practical invocation collision. The exact source value remains in
    Event metadata/raw evidence.
    """
    if max_bytes <= len(_SUFFIX_PREFIX) + _DIGEST_HEX_CHARS:
        raise ValueError("source call ID byte limit is too small")
    text = str(value)
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    suffix = (
        _SUFFIX_PREFIX
        + codess_bytes_hash(256, _DIGEST_BITS, encoded)
    ).encode("ascii")
    prefix = encoded[: max_bytes - len(suffix)]
    while prefix:
        try:
            decoded = prefix.decode("utf-8")
            break
        except UnicodeDecodeError:
            prefix = prefix[:-1]
    else:
        decoded = ""
    return decoded + suffix.decode("ascii")

# The three spellings vendors use for an MCP tool name. Claude and Codex write
# `mcp__server__tool`; Cursor writes both `mcp_Server_tool` and `mcp-server-tool`.
# Declared once here because two modules previously encoded the same set: one to
# classify a call as MCP, the other to split out the server.
MCP_PREFIXES = ("mcp__", "mcp_", "mcp-")

# Servers whose tools Cursor spells with single hyphens, where the name marks no
# boundary between server and tool. Declared rather than parsed; an undeclared server
# is recorded unresolved rather than guessed at the first hyphen.
MCP_HYPHEN_SERVERS = ("cursor-app-control",)


def is_mcp_tool(name: object) -> bool:
    """Whether a tool name is an MCP call, by any vendor's spelling."""
    if not isinstance(name, str):
        return False
    return name.lower().startswith(MCP_PREFIXES)


def mcp_namespace(tool_name: object) -> str | None:
    """The server an MCP tool belongs to, where the name marks it unambiguously.

    `mcp__server__tool` and `mcp_Server_tool` delimit the server with their separator,
    so it is read. `mcp-server-tool` does not -- single hyphens run through both halves
    and no field states the server -- so those come from `MCP_HYPHEN_SERVERS`.

    A built-in tool has no namespace: it belongs to the harness, not to a server.
    """
    if not isinstance(tool_name, str):
        return None
    lowered = tool_name.lower()
    for server in MCP_HYPHEN_SERVERS:
        if lowered.startswith(f"mcp-{server}-"):
            return server
    for separator in ("__", "_"):
        if not lowered.startswith("mcp" + separator):
            continue
        parts = tool_name.split(separator)
        # `mcp`, server, tool: fewer means the name states no server, and an empty
        # middle part is the degenerate `mcp__` form.
        if len(parts) >= 3 and parts[1].strip():
            return parts[1].strip()
        return None
    return None

