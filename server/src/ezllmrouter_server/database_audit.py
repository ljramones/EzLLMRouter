"""Read-only integrity audit of an existing service database; never repairs records."""

from __future__ import annotations

from collections.abc import Sequence
from .store import Store, Record
from typing import cast
import argparse
from contextlib import closing
import json
from pathlib import Path

from .repositories import database_audit as queries
from .store import SQLiteStore


def audit(store: Store) -> Record:
    with store.database.read() as db:
        quick = db.execute(queries.QUICK_CHECK).fetchall()
        foreign_keys = len(db.execute(queries.FOREIGN_KEY_CHECK).fetchall())
        ownership = dict(
            cast(list[tuple[str, int]], db.execute(queries.OWNERSHIP_COUNTS).fetchall())
        )
    return {
        "sqlite_quick_check": "ok" if quick == [("ok",)] else "failed",
        "foreign_key_violations": foreign_keys,
        "ownership_violations": ownership,
        "ok": quick == [("ok",)] and foreign_keys == 0 and not any(ownership.values()),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.db.is_absolute() or args.db.is_symlink() or not args.db.is_file():
        parser.error("an existing absolute database path is required")
    with closing(SQLiteStore.open_existing(args.db, read_only=True)) as store:
        result = audit(store)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
