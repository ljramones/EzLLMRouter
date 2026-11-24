"""Bind the reduced PostgreSQL native bundle to exact reviewed build outputs."""

from __future__ import annotations

import json
from pathlib import Path
import re
from urllib.parse import urlsplit

if __package__:
    from . import native_inputs as native
else:
    import native_inputs as native


def validate(data: dict) -> None:
    record = data.get("native_driver")
    if record is None:
        return
    if (
        data["format"] != "ezllmrouter-debian-inputs-v4"
        or record["format"] != "ezllmrouter-native-driver-v1"
        or record["id"] != native.canonical(record["inputs"])
        or record["inputs"]["builder"] != data["bases"]["python"]["reference"]
        or record["inputs"]["openssl_native_build"] != data["native_build"]["id"]
        or record["upstream_version"] != "3.3.6"
        or record["version"] != "3.3.6+ezllmrouter1"
        or record["libpq_version"] != 180006
    ):
        raise ValueError("unbound native PostgreSQL build")
    native.identity(record["output"])
    if (
        record["filename"] != "psycopg_binary-3.3.6+ezllmrouter1-cp312-cp312-linux_aarch64.whl"
        or record["features"] != {"gssapi": False, "ldap": False, "ssl": "shared"}
        or set(record["code"])
        != {
            "psycopg_binary/_psycopg.cpython-312-aarch64-linux-gnu.so",
            "psycopg_binary/pq.cpython-312-aarch64-linux-gnu.so",
            "psycopg_binary.libs/libpq-ezllmrouter1.so.5",
        }
        or any(not re.fullmatch(r"[0-9a-f]{64}", sha) for sha in record["code"].values())
    ):
        raise ValueError("unexpected native PostgreSQL output closure")
    for name, sha in record["inputs"]["recipes"].items():
        if (
            not native.safe_path(name)
            or not name.startswith("deploy/local/inputs/native/")
            or not re.fullmatch(r"[0-9a-f]{64}", sha)
        ):
            raise ValueError("unsafe PostgreSQL build recipe")
    if not record["inputs"]["artifacts"] or not record["inputs"]["recipes"]:
        raise ValueError("incomplete PostgreSQL build provenance")
    for name, row in record["inputs"]["artifacts"].items():
        native.identity(row)
        if not native.safe_path(name):
            raise ValueError("unsafe PostgreSQL source input")
        if "url" in row:
            url = urlsplit(row["url"])
            if (
                url.scheme != "https"
                or url.netloc
                not in {"ftp.postgresql.org", "deb.debian.org", "files.pythonhosted.org"}
                or url.query
                or url.fragment
            ):
                raise ValueError("unreviewed PostgreSQL source origin")


def verify_frozen(root: Path, data: dict) -> None:
    inventory = json.loads((root / "deploy/local/inputs/gateway/WHEEL-INVENTORY.json").read_text())
    selected = [row for row in inventory["wheels"] if row["name"] == "psycopg-binary"]
    record = data.get("native_driver")
    if record is None:
        if any("+ezllmrouter" in row["version"] for row in selected):
            raise ValueError("local PostgreSQL wheel lacks its build review")
        return
    if len(selected) != 1 or any(
        selected[0][key] != value
        for key, value in dict(
            record["output"], filename=record["filename"], version=record["version"]
        ).items()
    ):
        raise ValueError("frozen PostgreSQL wheel differs from reviewed output")
    for name, sha in record["inputs"]["recipes"].items():
        path = root / name
        if path.is_symlink() or not path.is_file() or native.digest(path) != sha:
            raise ValueError("PostgreSQL build recipe identity mismatch")


def verify_outputs(store: Path, data: dict) -> None:
    record = data.get("native_driver")
    if record is None:
        return
    path = store / "inputs/native-driver" / record["id"]
    if (
        path.is_symlink()
        or not path.resolve().is_relative_to(store.resolve())
        or {entry.name for entry in path.iterdir()} != {record["filename"]}
    ):
        raise ValueError("unexpected PostgreSQL output store")
    wheel = path / record["filename"]
    if (
        wheel.is_symlink()
        or not wheel.is_file()
        or wheel.stat().st_size != record["output"]["bytes"]
        or native.digest(wheel) != record["output"]["sha256"]
    ):
        raise ValueError("PostgreSQL output identity mismatch")
