"""Publish a complete offline SQLite snapshot without exposing a partial destination."""

from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile

from .private_files import AtomicPublicationError
from .schema import validate
from .database_security import configure


def backup_database(source_path: Path, destination: Path) -> None:
    """Caller holds the exclusive instance lease; destination must be new."""
    descriptor, name = tempfile.mkstemp(
        prefix="." + destination.name + ".", suffix=".partial", dir=destination.parent
    )
    temporary = Path(name)
    published = False
    try:
        os.close(descriptor)
        with closing(sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True)) as source:
            configure(source)
            validate(source)
            with closing(sqlite3.connect(temporary)) as target:
                configure(target)
                source.backup(target, pages=64)
        with temporary.open("rb") as complete:
            os.fsync(complete.fileno())
        os.link(temporary, destination)
        published = True
        directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except FileExistsError:
        raise
    except OSError as error:
        raise AtomicPublicationError(error, published=published) from error
    finally:
        temporary.unlink(missing_ok=True)
