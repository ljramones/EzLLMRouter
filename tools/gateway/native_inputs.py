"""Verify explicitly reviewed local native builds alongside publisher archives."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from urllib.parse import urlsplit


def canonical(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def safe_path(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        bool(re.fullmatch(r"[A-Za-z0-9._+%~/-]+", value))
        and not path.is_absolute()
        and ".." not in path.parts
        and str(path) == value
    )


def identity(row: dict) -> None:
    if (
        not re.fullmatch(r"[0-9a-f]{64}", row.get("sha256", ""))
        or type(row.get("bytes")) is not int
        or not 0 < row["bytes"] <= 512 * 1024 * 1024
    ):
        raise ValueError("invalid native artifact identity")


def validate(data: dict) -> None:
    native = data["native_build"]
    inputs = native["inputs"]
    if (
        native.get("format") != "ezllmrouter-native-build-v1"
        or native.get("id") != canonical(inputs)
        or inputs["builder"] != data["bases"]["python"]["reference"]
    ):
        raise ValueError("unbound native build inputs")
    if not inputs["recipes"] or not inputs["artifacts"]:
        raise ValueError("incomplete native build inputs")
    for path, sha256 in inputs["recipes"].items():
        if (
            not safe_path(path)
            or not path.startswith("deploy/local/inputs/native/")
            or not re.fullmatch(r"[0-9a-f]{64}", sha256)
        ):
            raise ValueError("unsafe native build recipe")
    for path, row in inputs["artifacts"].items():
        identity(row)
        if not safe_path(path):
            raise ValueError("unsafe native input path")
        if "url" in row:
            url = urlsplit(row["url"])
            if (
                url.scheme != "https"
                or url.netloc
                not in {
                    "deb.debian.org",
                    "github.com",
                    "nodejs.org",
                    "files.pythonhosted.org",
                    "static.crates.io",
                    "keys.openpgp.org",
                }
                or url.query
                or url.fragment
            ):
                raise ValueError("unreviewed native source URL")
    if native["node"]["version"] != data["bases"]["node"]["runtime_version"]:
        raise ValueError("native Node version differs from pinned target")
    for version, upstream in (
        (native["openssl_source_version"], native["openssl_upstream_source_version"]),
        (native["cryptography"]["version"], native["cryptography"]["upstream_version"]),
    ):
        if not re.fullmatch(re.escape(upstream) + r"\+ezllmrouter[1-9][0-9]*", version):
            raise ValueError("local native version must preserve its upstream identity")
    outputs = native["outputs"]
    for filename, row in outputs.items():
        identity(row)
        if not safe_path(filename) or "/" in filename:
            raise ValueError("unsafe native output filename")
    if (
        native["node"]["filename"] not in outputs
        or native["cryptography"]["filename"] not in outputs
    ):
        raise ValueError("incomplete native runtime outputs")
    expected = set()
    for row in data["packages"]:
        if "native_build" not in row:
            continue
        if (
            row["native_build"] != native["id"]
            or row["url"] != "urn:ezllmrouter:native-build:" + native["id"] + ":" + row["filename"]
        ):
            raise ValueError("unbound native package origin")
        output = outputs.get(row["filename"])
        if output is None or any(row[key] != output[key] for key in ("bytes", "sha256")):
            raise ValueError("native package differs from reviewed output")
        expected.add(row["package"])
    if expected != {"libssl3t64", "openssl-provider-legacy", "openssl"}:
        raise ValueError("incomplete native OpenSSL package closure")
    selected = {
        row["package"]: row["filename"] for row in data["packages"] if "native_build" in row
    }
    if native["packages"] != selected or set(outputs) != set(selected.values()) | {
        native["node"]["filename"],
        native["cryptography"]["filename"],
    }:
        raise ValueError("native outputs differ from the exact selected runtime closure")
    if not native["code"] or not native["fixed_advisories"]:
        raise ValueError("missing native code or advisory review")
    expected_code = {
        "/usr/lib/aarch64-linux-gnu/libssl.so.3": "all",
        "/usr/lib/aarch64-linux-gnu/libcrypto.so.3": "all",
        "/usr/lib/aarch64-linux-gnu/ossl-modules/legacy.so": "all",
        "/usr/bin/openssl": "python",
        "/usr/local/bin/node": "node",
        "/usr/local/lib/python3.12/site-packages/cryptography/hazmat/bindings/_rust.abi3.so": "python",
    }
    if (
        len(native["code"]) != len(expected_code)
        or {row["path"]: row["role"] for row in native["code"]} != expected_code
    ):
        raise ValueError("incomplete native runtime copy bindings")
    for row in native["code"]:
        if (
            not row["path"].startswith("/")
            or not safe_path(row["path"][1:])
            or row["role"] not in {"all", "python", "node"}
            or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
        ):
            raise ValueError("unsafe native code binding")
    for name, row in native["fixed_advisories"].items():
        if (
            not re.fullmatch(r"DEBIAN-CVE-[0-9]{4}-[0-9]+", name)
            or not re.fullmatch(r"[0-9a-f]{64}", row["advisory_sha256"])
            or not row["reason"].strip()
        ):
            raise ValueError("invalid native advisory review")
        patch = inputs["security_patches"].get(name)
        if (
            patch is None
            or row["patch_sha256"] != patch["sha256"]
            or inputs["artifacts"].get(patch["path"], {}).get("sha256") != patch["sha256"]
        ):
            raise ValueError("advisory is not bound to its reviewed source patch")


def verify_recipes(root: Path, native: dict) -> None:
    for name, sha256 in native["inputs"]["recipes"].items():
        path = root / name
        if (
            path.is_symlink()
            or not path.is_file()
            or not path.resolve().is_relative_to(root.resolve())
            or digest(path) != sha256
        ):
            raise ValueError("native build recipe identity mismatch")
    inventory = json.loads((root / "deploy/local/inputs/gateway/WHEEL-INVENTORY.json").read_text())
    selected = [row for row in inventory["wheels"] if row["name"] == "cryptography"]
    expected = native["outputs"][native["cryptography"]["filename"]]
    if (
        len(selected) != 1
        or any(selected[0][key] != expected[key] for key in ("sha256", "bytes"))
        or selected[0]["filename"] != native["cryptography"]["filename"]
        or selected[0]["version"] != native["cryptography"]["version"]
    ):
        raise ValueError("frozen cryptography differs from reviewed shared native build")


def directory(store: Path, native: dict) -> Path:
    path = store / "inputs/native" / native["id"] / "outputs"
    if path.is_symlink() or not path.resolve().is_relative_to(store.resolve()):
        raise ValueError("linked native output directory")
    return path


def verify_outputs(store: Path, native: dict) -> None:
    path = directory(store, native)
    if {item.name for item in path.iterdir()} != set(native["outputs"]):
        raise ValueError("incomplete or unexpected native outputs")
    for name, row in native["outputs"].items():
        item = path / name
        if (
            item.is_symlink()
            or not item.is_file()
            or item.stat().st_size != row["bytes"]
            or digest(item) != row["sha256"]
        ):
            raise ValueError("native output identity mismatch: " + name)
