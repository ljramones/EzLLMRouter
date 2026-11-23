"""Verify and stage reviewed Debian archives without acquiring or executing them."""

from __future__ import annotations

import hashlib
import argparse
import json
from pathlib import Path
import re
import shutil
import zipfile
from urllib.parse import urlsplit

LOCK = "deploy/local/inputs/os/debian13-arm64.lock.json"
INSTALLER = "deploy/local/install_os.sh"
CONTEXTS = ("runtime_python", "receiver", "worker", "service", "python", "js")
STORE = "inputs/os/debian13-arm64"
PROTECTED = {
    "base-files",
    "base-passwd",
    "bash",
    "ca-certificates",
    "coreutils",
    "dash",
    "debconf",
    "dpkg",
    "findutils",
    "gcc-14-base",
    "grep",
    "gzip",
    "libc-bin",
    "libc6",
    "libdb5.3t64",
    "libgcc-s1",
    "libncursesw6",
    "libssl3t64",
    "libstdc++6",
    "libtinfo6",
    "libuuid1",
    "openssl",
    "openssl-provider-legacy",
    "perl-base",
    "sed",
    "tar",
    "tzdata",
    "zlib1g",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_lock(data: dict) -> None:
    if (
        data.get("format") not in {"ezllmrouter-debian-inputs-v2", "ezllmrouter-debian-inputs-v3"}
        or data.get("suite") != "trixie"
        or data.get("version_id") != "13"
        or data.get("architecture") != "arm64"
        or set(data.get("bases", {})) != {"python", "node"}
        or not data.get("packages")
        or not re.fullmatch(r"[0-9a-f]{64}", data.get("installer_sha256", ""))
    ):
        raise ValueError("unreviewed Debian target")
    origins = {"trixie": "13"}
    if data["format"] == "ezllmrouter-debian-inputs-v3":
        reviews = data.get("additional_origins", {})
        if set(reviews) != {"forky"}:
            raise ValueError("unreviewed Debian package origin")
        review = reviews["forky"]
        if (
            review.get("version_id") != "14"
            or review.get("url") != "https://deb.debian.org/debian/dists/forky/InRelease"
            or not re.fullmatch(r"[0-9a-f]{64}", review.get("keyring_sha256", ""))
            or not re.fullmatch(r"[0-9a-f]{64}", review.get("inrelease_sha256", ""))
        ):
            raise ValueError("missing authenticated Debian package origin")
        origins["forky"] = "14"
    removals = data.get("runtime_removals")
    if (
        not isinstance(removals, list)
        or not 3 <= len(removals) <= 64
        or any(
            not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9+.-]*", name)
            for name in removals
        )
        or removals != sorted(set(removals))
        or not {"apt", "libapt-pkg7.0", "sqv"} <= set(removals)
        or PROTECTED & set(removals)
    ):
        raise ValueError("unsafe or unreviewed runtime package removals")
    for role, base in data["bases"].items():
        if not re.fullmatch(
            r"docker.io/library/" + role + r"@sha256:[0-9a-f]{64}", base["reference"]
        ) or not re.fullmatch(r"sha256:[0-9a-f]{64}", base["config_sha256"]):
            raise ValueError("immutable reviewed base required")
    seen = set()
    roles = set()
    for row in data["packages"]:
        if data["format"] == "ezllmrouter-debian-inputs-v3":
            if row.get("origin_suite") not in origins or row.get(
                "origin_version_id"
            ) != origins.get(row.get("origin_suite")):
                raise ValueError("unreviewed Debian advisory ecosystem")
        elif "origin_suite" in row or "origin_version_id" in row:
            raise ValueError("package origins require the v3 lock")
        url = urlsplit(row["url"])
        if (
            not re.fullmatch(r"[a-z0-9][a-z0-9+.-]*", row["package"])
            or not re.fullmatch(r"[a-z0-9][a-z0-9+.-]*", row["source"])
            or any(
                not re.fullmatch(r"[0-9][A-Za-z0-9.+:~_-]*", row[key])
                for key in ("version", "source_version")
            )
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+:%~_-]*\.deb", row["filename"])
            or row["architecture"] != "arm64"
            or type(row["bytes"]) is not int
            or row["bytes"] <= 0
            or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
            or not row["roles"]
            or len(set(row["roles"])) != len(row["roles"])
            or not set(row["roles"]) <= {"python", "node"}
            or url.scheme != "https"
            or url.netloc != "deb.debian.org"
            or not url.path.startswith("/debian/pool/main/")
            or not url.path.endswith(".deb")
            or url.query
            or url.fragment
            or row["package"] in seen
        ):
            raise ValueError("invalid or duplicate reviewed Debian archive")
        seen.add(row["package"])
        roles.update(row["roles"])
    if seen & set(removals):
        raise ValueError("reviewed runtime updates cannot be removed")
    if roles != {"python", "node"}:
        raise ValueError("incomplete Debian role coverage")


def advisory_ecosystem(data: dict, row: dict) -> str:
    """Use the reviewed binary's source suite, independently of the base OS."""
    version = (
        row["origin_version_id"]
        if data["format"] == "ezllmrouter-debian-inputs-v3"
        else data["version_id"]
    )
    return "Debian:" + version


def load_lock(root: Path) -> dict:
    path = root / LOCK
    if path.is_symlink() or not path.is_file():
        raise ValueError("reviewed Debian lock missing")
    data = json.loads(path.read_text())
    validate_lock(data)
    installer = root / INSTALLER
    if (
        installer.is_symlink()
        or not installer.is_file()
        or digest(installer) != data["installer_sha256"]
    ):
        raise ValueError("reviewed Debian installer identity mismatch")
    return data


def verify_archives(root: Path, store: Path) -> dict:
    data = load_lock(root)
    directory = store / STORE
    if directory.is_symlink() or not directory.resolve().is_relative_to(store.resolve()):
        raise ValueError("linked Debian artifact directory")
    expected = {row["filename"] for row in data["packages"]}
    if {path.name for path in directory.glob("*.deb")} != expected:
        raise ValueError("incomplete or unexpected Debian archive set")
    for row in data["packages"]:
        path = directory / row["filename"]
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_size != row["bytes"]
            or digest(path) != row["sha256"]
        ):
            raise ValueError("Debian archive identity mismatch: " + row["filename"])
    return data


def stage_archives(root: Path, store: Path, build: Path, contexts=CONTEXTS) -> dict:
    data = verify_archives(root, store)
    rows = []
    for kind in contexts:
        if kind not in {*CONTEXTS, "dev09_js"}:
            raise ValueError("unreviewed Debian build context")
        role = "node" if kind in {"js", "dev09_js"} else "python"
        selected = [row for row in data["packages"] if role in row["roles"]]
        directory = build / kind / "os-inputs"
        directory.mkdir(parents=True)
        shutil.copy2(root / INSTALLER, directory / "install.sh")
        for row in selected:
            shutil.copy2(store / STORE / row["filename"], directory / row["filename"])
        removals = "".join(name + "\n" for name in data["runtime_removals"])
        (directory / "REMOVE-PACKAGES").write_bytes(removals.encode())
        (directory / "SHA256SUMS").write_text(
            "".join(row["sha256"] + "  " + row["filename"] + "\n" for row in selected)
            + hashlib.sha256(removals.encode()).hexdigest()
            + "  REMOVE-PACKAGES\n"
        )
        for path in sorted(directory.iterdir()):
            rows.append(
                {
                    "path": path.relative_to(build).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": digest(path),
                }
            )
    return {"lock": data, "lock_sha256": digest(root / LOCK), "files": rows}


def verify_staging(build: dict) -> dict:
    if "os_inputs" not in build:
        raise ValueError("prepare reviewed OS inputs before rebuilding this staging context")
    record = build["os_inputs"]
    data = record["lock"]
    validate_lock(data)
    root = Path(build["build_dir"])
    actual = {}
    for row in record["files"]:
        path = root / row["path"]
        if (
            Path(row["path"]).is_absolute()
            or ".." in Path(row["path"]).parts
            or path.is_symlink()
            or not path.is_file()
            or not path.resolve().is_relative_to(root.resolve())
            or path.stat().st_size != row["bytes"]
            or digest(path) != row["sha256"]
            or row["path"] in actual
        ):
            raise ValueError("staged Debian input identity mismatch")
        actual[row["path"]] = row["sha256"]
    contexts = {Path(name).parts[0] for name in actual}
    if not set(CONTEXTS) <= contexts or not contexts <= {*CONTEXTS, "dev09_js"}:
        raise ValueError("incomplete staged Debian contexts")
    expected = set()
    for kind in contexts:
        role = "node" if kind in {"js", "dev09_js"} else "python"
        selected = [row for row in data["packages"] if role in row["roles"]]
        prefix = kind + "/os-inputs/"
        if actual.get(prefix + "install.sh") != data["installer_sha256"]:
            raise ValueError("staged Debian installer differs from reviewed lock")
        expected.update(prefix + name for name in ("install.sh", "SHA256SUMS", "REMOVE-PACKAGES"))
        for row in selected:
            name = prefix + row["filename"]
            expected.add(name)
            if actual.get(name) != row["sha256"]:
                raise ValueError("staged Debian archive differs from reviewed lock")
        checksum = "".join(row["sha256"] + "  " + row["filename"] + "\n" for row in selected)
        removals = "".join(name + "\n" for name in data["runtime_removals"])
        if (root / prefix / "REMOVE-PACKAGES").read_bytes() != removals.encode():
            raise ValueError("staged runtime removals differ from reviewed lock")
        checksum += hashlib.sha256(removals.encode()).hexdigest() + "  REMOVE-PACKAGES\n"
        if (root / prefix / "SHA256SUMS").read_text() != checksum:
            raise ValueError("staged Debian checksum manifest mismatch")
    if expected != set(actual):
        raise ValueError("unexpected staged Debian input")
    with zipfile.ZipFile(build["source_packet"]) as packet:
        captured = json.loads(packet.read("SOURCE-MANIFEST.json"))["os_inputs"]
    if captured["lock"] != data or captured["lock_sha256"] != record["lock_sha256"]:
        raise ValueError("staged Debian lock differs from source packet")
    selected_files = {
        name: value for name, value in actual.items() if Path(name).parts[0] in CONTEXTS
    }
    if selected_files != {row["path"]: row["sha256"] for row in captured["files"]}:
        raise ValueError("staged Debian files differ from source packet")
    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
    args = parser.parse_args()
    verify_archives(Path(__file__).resolve().parents[2], args.store)
    print("Reviewed Debian archive set verified")
