"""Read-only local pre-action verification for AHK; exit 0 only when safe.

No CAD/EXB writes, no network, no GUI. Called at the instant of a user hotkey.
A short workbench lease prevents indefinitely trusted tasks after a crash.
"""
from __future__ import annotations
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import time

import core
import preflight

LEASE_SECONDS = 35


def verify_for_action(storage: Path, signature: str, *, now: float | None = None) -> bool:
    if not signature or len(signature) != 64 or any(ch not in '0123456789abcdef' for ch in signature):
        return False
    try:
        lease = json.loads((storage/'active_job_lease.json').read_text(encoding='utf-8'))
        stamp = lease['seen_at']
        if not isinstance(stamp,(int,float)) or isinstance(stamp,bool):
            return False
        diff=(time.time() if now is None else now)-stamp
        if lease.get('signature') != signature or not 0 <= diff <= LEASE_SECONDS:
            return False
        # Open the existing SQLite DB read-only. Never create a DB from a hotkey.
        db=(storage/'progress.sqlite3').resolve()
        url=db.as_uri()+'?mode=ro'
        with closing(sqlite3.connect(url,uri=True,timeout=1)) as conn:
            conn.row_factory=sqlite3.Row
            valid=preflight.active_job_valid(conn,storage,signature)
        # Recheck the lease: if workbench revoked while hashing, fail closed.
        latest=json.loads((storage/'active_job_lease.json').read_text(encoding='utf-8'))
        return valid and latest==lease
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error,
            UnicodeError, json.JSONDecodeError):
        return False


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args)!=2 or args[0]!='--check-job':
        return 2
    return 0 if verify_for_action(core.storage_dir(),args[1]) else 1


if __name__=='__main__':
    raise SystemExit(main())
