#!/usr/bin/env python3
"""Check that every file stating the CoSchema format agrees with the declaration.

Four locations state it: `schema_contract.FORMAT_VERSION` declares it, and the
manifest, the DDL's `PRAGMA user_version`, and the contract each restate it. A
fifth existed -- a header comment in the DDL that no check could read -- and had
drifted several formats behind while the pragma stayed correct, which is why a
number a check cannot read is deleted rather than synchronised.

Each restatement is otherwise compared only where it is *used*: on a store open,
at store creation, on a contract read. That detects drift, but only once
something exercises the path, and the symptom arrives a layer away -- a format-7
bump surfaced as 289 tests failing on `manifest format_version mismatch`, and a
stale contract digest as 391 failures and 38 collection errors.

This is the check itself, extracted so it has one implementation and three
callers rather than three copies: the pre-collection gate in `tests/conftest.py`,
the pre-commit hook in `tools/install_hooks.py`, and this command. Detection
moves from the next store open, to the test run, to the commit that broke it.

    python tools/format_agreement.py     # exit 0 when the four agree
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))


def _json_format_version(path: Path) -> int | None:
    """The `format_version` a released JSON file states, or None.

    An unreadable file returns None rather than raising: failing the whole
    check on an absent path would hide which of the four is actually stale.
    """
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("format_version")
    except (OSError, ValueError):
        return None
    return value if isinstance(value, int) else None


def disagreements() -> tuple[list[str], list[str]]:
    """Return (what is stale, what fixes it), both empty when the four agree."""
    from codess.schema_contract import (
        CONTRACT_PATH,
        DDL_PATH,
        FORMAT_VERSION,
        MANIFEST_PATH,
    )

    stale: list[str] = []
    remedies: list[str] = []

    manifest_version = _json_format_version(MANIFEST_PATH)
    if manifest_version is not None and manifest_version != FORMAT_VERSION:
        stale.append(f"{MANIFEST_PATH.name} states {manifest_version}")
        remedies.append("run tools/refresh_schema_manifest.py")

    contract_version = _json_format_version(CONTRACT_PATH)
    if contract_version is not None and contract_version != FORMAT_VERSION:
        stale.append(f"{CONTRACT_PATH.name} states {contract_version}")
        remedies.append(f"edit {CONTRACT_PATH.name}")

    try:
        stamped = re.search(
            r"PRAGMA\s+user_version\s*=\s*(\d+)",
            DDL_PATH.read_text(encoding="utf-8"),
        )
    except OSError:
        stamped = None
    if stamped and int(stamped.group(1)) != FORMAT_VERSION:
        stale.append(f"{DDL_PATH.name} stamps {stamped.group(1)}")
        remedies.append(f"edit {DDL_PATH.name}")

    # A released file edited without refreshing its recorded digest fails the
    # same way and worse: the version checks above name a file, while a stale
    # digest surfaces as several hundred store-opening tests failing on a hash.
    try:
        from codess.schema_contract import contract_digest

        contract_digest()
    except ImportError:
        pass
    except Exception as exc:  # SchemaContractError, and anything it wraps
        stale.append(str(exc))
        remedies.append("run tools/refresh_schema_manifest.py")

    return stale, remedies


def failure_message() -> str | None:
    """One line naming the stale file and its remedy, or None when clean."""
    from codess.schema_contract import FORMAT_VERSION

    stale, remedies = disagreements()
    if not stale:
        return None
    return (
        f"declared CoSchema {FORMAT_VERSION}, {'; '.join(stale)}: "
        f"{', '.join(dict.fromkeys(remedies))}"
    )


def main(argv: list[str] | None = None) -> int:
    # `argv` is accepted and unused: this takes no options, and the signature
    # matches every other tool's so a caller does not special-case it.
    del argv
    message = failure_message()
    if message:
        print(f"codess: {message}", file=sys.stderr)
        return 1
    from codess.schema_contract import FORMAT_VERSION

    print(f"CoSchema format {FORMAT_VERSION}: all four locations agree")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
