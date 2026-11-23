"""Set SQLite capabilities before schema, application or backup operations."""

import sqlite3


def configure(connection: sqlite3.Connection) -> None:
    # Unsupported settings raise: opening must not continue with weaker defaults.
    connection.setconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE, True)
    connection.setconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_LOAD_EXTENSION, False)
