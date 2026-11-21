"""Named SQL/copy/publication checkpoints in disposable child processes only."""

from pathlib import Path
import os
import sqlite3
from unittest.mock import patch

from ezllmrouter_server import schema
from ezllmrouter_server.integration_local import main as local_main
from ezllmrouter_server.store import SQLiteStore


def migration_case(root, selected, point, checkpoint):
    original_migration, connect = schema.migration, sqlite3.connect
    active, completed = 0, 0

    def migration(number):
        nonlocal active
        active = number
        return original_migration(number)

    class Interrupted(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            nonlocal completed
            if sql == "COMMIT" and point == "before_commit":
                checkpoint()
            result = super().execute(sql, *args, **kwargs)
            if active == selected and ("CREATE INDEX" in sql or "CREATE TRIGGER" in sql):
                completed += 1
                if point == f"statement.{completed}":
                    checkpoint()
            if sql == "COMMIT" and point == "after_commit":
                checkpoint()
            return result

    def opened(*args, **kwargs):
        connection = connect(*args, **dict(kwargs, factory=Interrupted))
        connection.execute("PRAGMA cache_size=2")
        connection.execute("PRAGMA cache_spill=ON")
        return connection

    with (
        patch.object(schema, "migration", side_effect=migration),
        patch.object(sqlite3, "connect", side_effect=opened),
    ):
        store = SQLiteStore(root / "store.sqlite")
        store.close()
    raise RuntimeError("migration checkpoint was not reached")


def backup_case(root, point, checkpoint):
    connect, link = sqlite3.connect, os.link

    class Interrupted(sqlite3.Connection):
        def backup(self, target, **kwargs):
            def progress(status, remaining, total):
                if point == "copy" and 0 < remaining < total:
                    checkpoint()

            return super().backup(target, pages=1, progress=progress)

    def published(source, destination):
        result = link(source, destination)
        if point == "published" and Path(destination) == root / "backup.sqlite":
            checkpoint()
        return result

    with (
        patch.object(
            sqlite3,
            "connect",
            side_effect=lambda *a, **kw: connect(*a, **dict(kw, factory=Interrupted)),
        ),
        patch.object(os, "link", side_effect=published),
    ):
        local_main(["--db", str(root / "store.sqlite"), "--backup", str(root / "backup.sqlite")])
    raise RuntimeError("backup checkpoint was not reached")


def wal_case(root, point, checkpoint):
    connection = sqlite3.connect(root / "store.sqlite", isolation_level=None)
    if point == "before_checkpoint":
        checkpoint()
    connection.execute("PRAGMA wal_checkpoint(PASSIVE)")
    if point == "after_checkpoint":
        checkpoint()
    raise RuntimeError("WAL checkpoint was not reached")
