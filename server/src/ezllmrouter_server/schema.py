"""One versioned, transactional schema owner for new service databases."""

from hashlib import sha256
from importlib.resources import files
import sqlite3

APPLICATION_ID = 0x455A4C4C
MIGRATIONS = ("v001_initial.sql",)
VERSION = len(MIGRATIONS)


def migration(number: int) -> tuple[str, str]:
    raw = files("ezllmrouter_server").joinpath("schema", MIGRATIONS[number - 1]).read_bytes()
    return raw.decode(), sha256(raw).hexdigest()


def validate(connection: sqlite3.Connection) -> int:
    application = int(connection.execute("PRAGMA application_id").fetchone()[0])
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if application != APPLICATION_ID or not 1 <= version <= VERSION:
        raise RuntimeError("unsupported database; a fresh EzLLMRouter instance is required")
    recorded = connection.execute(
        "SELECT version,sha256 FROM schema_revisions ORDER BY version"
    ).fetchall()
    if recorded != [(number, migration(number)[1]) for number in range(1, version + 1)]:
        raise RuntimeError("database schema revision does not match the installed service")
    return version


def initialize(connection: sqlite3.Connection) -> None:
    connection.execute("BEGIN IMMEDIATE")
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            if connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 1"
            ).fetchone():
                raise RuntimeError("unversioned database; a fresh EzLLMRouter instance is required")
            application = connection.execute("PRAGMA application_id").fetchone()[0]
            if application not in (0, APPLICATION_ID):
                raise RuntimeError("database belongs to another application")
        else:
            validate(connection)
        for number in range(version + 1, VERSION + 1):
            source, digest = migration(number)
            statement = ""
            for line in source.splitlines(keepends=True):
                statement += line
                if sqlite3.complete_statement(statement):
                    connection.execute(statement)
                    statement = ""
            if statement.strip():
                raise RuntimeError("incomplete schema migration")
            connection.execute("INSERT INTO schema_revisions VALUES (?,?)", (number, digest))
            connection.execute(f"PRAGMA user_version={number}")
        connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
        connection.execute("COMMIT")
    except BaseException:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
