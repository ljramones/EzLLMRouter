"""Release versions come from distribution metadata or the source project."""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import tomllib


def release_version(distribution: str, source: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError:
        for parent in Path(source).resolve().parents:
            project = parent / "pyproject.toml"
            if project.is_file():
                data = tomllib.loads(project.read_text(encoding="utf-8")).get("project", {})
                if data.get("name") == distribution:
                    return str(data["version"])
        return "unknown"
