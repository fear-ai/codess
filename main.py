#!/usr/bin/env python3
"""CodingSess CLI: session-ingest, session-query."""

import argparse
import logging
import sys

from config import MIN_SESSION_FILE_SIZE
from cli.ingest_cmd import run as run_ingest
from cli.query_cmd import run as run_query


def main() -> int:
    parser = argparse.ArgumentParser(prog="coding-sess", description="Session record store")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    sub = parser.add_subparsers(dest="cmd", required=True)

    ingest_p = sub.add_parser("ingest", help="Ingest sessions from CC, Codex, Cursor")
    ingest_p.add_argument("--project", type=str, help="Project root (default: git root)")
    ingest_p.add_argument("--source", choices=["cc", "codex", "cursor", "all"], default="all",
                          help="Source to ingest: cc, codex, cursor, all (default: all)")
    ingest_p.add_argument("--cursor-global", action="store_true",
                          help="Cursor: use globalStorage (v44.9+); skip workspace DBs")
    ingest_p.add_argument("--debug", action="store_true", help="Store source_raw BLOB")
    ingest_p.add_argument("--redact", action="store_true", help="Redact secrets")
    ingest_p.add_argument("--force", action="store_true", help="Ignore incremental state")
    ingest_p.add_argument("--min-size", type=int, default=MIN_SESSION_FILE_SIZE, metavar="BYTES",
                          help=f"Skip files smaller than BYTES (default: {MIN_SESSION_FILE_SIZE})")
    ingest_p.set_defaults(run=run_ingest)

    query_p = sub.add_parser("query", help="Query session store")
    query_p.add_argument("--project", type=str, help="Project root (default: git root)")
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
