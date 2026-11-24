"""Bind the system and embedded Zstandard replacement to its exact build parents."""

from __future__ import annotations

from pathlib import Path
import re
from urllib.parse import urlsplit

if __package__:
    from . import native_inputs as native
else:
    import native_inputs as native

NODE = "node-v24.22.3-ezllmrouter2-linux-arm64"
PACKAGE = "libzstd1_1.6.0-0+ezllmrouter1_arm64.deb"
VERSION = "1.6.0-0+ezllmrouter1"
LIBRARY = "/usr/lib/aarch64-linux-gnu/libzstd.so.1.6.0"
RECIPES = {"zstd.sh", "zstd-package.py", "zstd-regression.c"}


def validate(data: dict) -> None:
    record = data.get("native_codec")
    rows = [row for row in data["packages"] if "native_codec" in row]
    if record is None:
        if rows:
            raise ValueError("codec package lacks its build provenance")
        return
    inputs = record["inputs"]
    parent = data["native_build"]
    if (
        data["format"] != "ezllmrouter-debian-inputs-v4"
        or record["format"] != "ezllmrouter-native-codec-v1"
        or record["id"] != native.canonical(inputs)
        or inputs["builder"] != data["bases"]["python"]["reference"]
        or inputs["native_build"] != parent["id"]
        or inputs["node_sha256"] != parent["outputs"][parent["node"]["filename"]]["sha256"]
        or record["version"] != "1.6.0"
        or record["source_version"] != VERSION
        or set(record["outputs"]) != {NODE, PACKAGE}
        or set(record["code"]) != {LIBRARY, "/usr/local/bin/node"}
        or record["code"]["/usr/local/bin/node"] != record["outputs"][NODE]["sha256"]
    ):
        raise ValueError("unbound Zstandard build")
    if set(inputs["recipes"]) != {"deploy/local/inputs/native/" + name for name in RECIPES}:
        raise ValueError("incomplete Zstandard recipes")
    for sha in [*inputs["recipes"].values(), *record["code"].values()]:
        if not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise ValueError("invalid Zstandard code identity")
    for row in record["outputs"].values():
        native.identity(row)
    source = inputs["artifacts"].get("zstd-1.6.0.tar.gz", {})
    if (
        source.get("sha256") != "2ba599ae2a257976278e7e71e998433a387bfd18aa7b78678229fd5d84f5e9b8"
        or source.get("url")
        != "https://github.com/meta/zstd/releases/download/v1.6.0/zstd-1.6.0.tar.gz"
    ):
        raise ValueError("unreviewed Zstandard source")
    review = record["fixed_advisory"]
    if (
        review["id"] != "DEBIAN-CVE-2026-124851"
        or not re.fullmatch(r"[0-9a-f]{64}", review["advisory_sha256"])
        or review["patch_sha256"] != inputs["artifacts"].get("fix-5023.patch", {}).get("sha256")
        or not review["reason"].strip()
    ):
        raise ValueError("unbound Zstandard advisory review")
    for name, row in inputs["artifacts"].items():
        native.identity(row)
        url = urlsplit(row.get("url", ""))
        if not native.safe_path(name) or (
            "url" in row
            and (
                url.scheme != "https"
                or url.netloc not in {"github.com", "deb.debian.org"}
                or url.query
                or url.fragment
            )
        ):
            raise ValueError("unsafe Zstandard build input")
    if len(rows) != 1:
        raise ValueError("incomplete Zstandard package closure")
    selected = rows[0]
    if (
        selected["package"] != "libzstd1"
        or selected["source"] != "libzstd"
        or selected["version"] != VERSION
        or selected["source_version"] != VERSION
        or selected["filename"] != PACKAGE
        or set(selected["roles"]) != {"python", "node"}
        or selected["origin_suite"] != "trixie"
        or selected["origin_version_id"] != "13"
        or selected["native_codec"] != record["id"]
        or selected["url"] != "urn:ezllmrouter:native-codec:" + record["id"] + ":" + PACKAGE
        or any(selected[key] != value for key, value in record["outputs"][PACKAGE].items())
    ):
        raise ValueError("unbound Zstandard package output")


def directory(store: Path, record: dict) -> Path:
    return store / "inputs/native-codec" / record["id"]


def verify_recipes(root: Path, data: dict) -> None:
    if "native_codec" not in data:
        return
    for name, sha in data["native_codec"]["inputs"]["recipes"].items():
        path = root / name
        if path.is_symlink() or not path.is_file() or native.digest(path) != sha:
            raise ValueError("Zstandard build recipe identity mismatch")


def verify_outputs(store: Path, data: dict) -> None:
    record = data.get("native_codec")
    if record is None:
        return
    path = directory(store, record)
    if (
        path.is_symlink()
        or not path.resolve().is_relative_to(store.resolve())
        or {entry.name for entry in path.iterdir()} != set(record["outputs"])
    ):
        raise ValueError("unexpected Zstandard output store")
    for name, row in record["outputs"].items():
        output = path / name
        if (
            output.is_symlink()
            or not output.is_file()
            or output.stat().st_size != row["bytes"]
            or native.digest(output) != row["sha256"]
        ):
            raise ValueError("Zstandard output identity mismatch")


def node_output(store: Path, data: dict) -> tuple[Path, dict] | None:
    if "native_codec" in data:
        record = data["native_codec"]
        return directory(store, record) / NODE, record["outputs"][NODE]
    if "native_build" in data:
        record = data["native_build"]
        name = record["node"]["filename"]
        return native.directory(store, record) / name, record["outputs"][name]
    return None
