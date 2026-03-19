#!/usr/bin/env python3
"""Codess CLI: scan, ingest, query."""

import argparse
import logging
import sys
from pathlib import Path

# Ensure src/ is on path for codess and cli packages
_src = Path(__file__).resolve().parent / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from codess.config import FORCE, MIN_SIZE, REGISTRY
from cli.scan_cmd import run as run_scan
from cli.ingest_cmd import run as run_ingest
from cli.query_cmd import run as run_query


def main() -> int:
    parser = argparse.ArgumentParser(prog="codess", description="Session record store")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    sub = parser.add_subparsers(dest="cmd", required=True)

    scan_p = sub.add_parser("scan", help="Discover projects with session data")
    scan_p.add_argument("--dirs", type=str, metavar="PATH",
                        help="File with dirs (one per line)")
    scan_p.add_argument("--dir", type=str, action="append", dest="dir_list",
                        help="Add dir (repeatable)")
    scan_p.add_argument("--source", type=str, metavar="cc,codex,cursor",
                        help="Filter sources (default: all)")
    scan_p.add_argument("--out", type=str, default="find_codess.csv",
                        help="Output CSV path (default: find_codess.csv; - for stdout)")
    scan_p.add_argument("--norec", action="store_true", help="No recursion; cwd or listed dirs only")
    scan_p.add_argument("--days", type=int, metavar="N",
                        help="[CODESS_DAYS] Include sessions from last N days (default: 90)")
    scan_p.add_argument("--debug", action="store_true", help="Print each directory visited with project path")
    scan_p.add_argument("--registry", type=str, metavar="PATH",
                        help="[CODESS_REGISTRY] Override ~/.codess")
    scan_p.set_defaults(run=run_scan)

    ingest_p = sub.add_parser("ingest", help="Ingest sessions from CC, Codex, Cursor")
    ingest_p.add_argument("--dirs", type=str, metavar="PATH",
                        help="File with dirs (one per line)")
    ingest_p.add_argument("--dir", type=str, action="append", dest="dir_list",
                        help="Add dir (repeatable)")
    ingest_p.add_argument("--source", choices=["cc", "codex", "cursor", "all"], default="all",
                          help="Source to ingest: cc, codex, cursor, all (default: all)")
    ingest_p.add_argument("--debug", action="store_true", help="Store source_raw BLOB [CODESS_DEBUG]")
    ingest_p.add_argument("--redact", action="store_true", help="Redact secrets")
    ingest_p.add_argument("--force", action="store_true", default=FORCE,
                        help="[CODESS_FORCE] Ignore incremental state (default: false)")
    ingest_p.add_argument("--min-size", type=int, default=MIN_SIZE, metavar="BYTES",
                        help="[CODESS_MIN_SIZE] Skip files smaller than BYTES (default: 20480)")
    ingest_p.add_argument("--registry", type=str, metavar="PATH",
                        help="[CODESS_REGISTRY] Override ~/.codess")
    ingest_p.set_defaults(run=run_ingest)

    query_p = sub.add_parser("query", help="Query session store")
    query_p.add_argument("--dirs", type=str, metavar="PATH",
                        help="File with dirs (one per line)")
    query_p.add_argument("--dir", type=str, action="append", dest="dir_list",
                        help="Add dir (repeatable)")
    query_p.add_argument("--tool-counts", action="store_true", help="Print tool invocation counts (legacy, use --tool 0)")
    query_p.add_argument("--tool", type=int, nargs="?", default=None, const=0, metavar="N",
                          help="Tool histogram: N=0 all sessions, N=1 most recent; no arg = 0")
    query_p.add_argument("--sessions", action="store_true", help="List sessions")
    query_p.add_argument("--id", action="store_true", dest="sess_id", help="Number sessions (1=most recent)")
    query_p.add_argument("-sess", type=int, metavar="N", dest="sess", help="Select session by number from --id list")
    query_p.add_argument("--show", nargs="*", choices=["prompt", "pr", "agent", "tool", "perm"],
                          default=None, metavar="MODE", help="Show prompt|pr|agent|tool|perm (default: all)")
    query_p.add_argument("--permissions", action="store_true", help="List permission_denied events")
    query_p.add_argument("--task-review", action="store_true", help="Review Task/Web tool invocations and outcomes")
    query_p.add_argument("--stats", action="store_true", help="DB stats: sessions, events")
    query_p.add_argument("--taxonomy", action="store_true", help="Event types and subtypes")
    query_p.set_defaults(run=run_query)

    args = parser.parse_args()
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)

    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
