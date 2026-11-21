"""prepare input collection domain; entry points remain on the facade."""

from __future__ import annotations

import argparse as argparse
import ast as ast
import base64 as base64
import csv as csv
import hashlib as hashlib
import io as io
import json as json
import os as os
from pathlib import Path as Path
import re as re
import shutil as shutil
import signal as signal
import stat as stat
import subprocess as subprocess
import sys as sys
import tarfile as tarfile
import time as time
import unicodedata as unicodedata
import uuid as uuid
import zipfile as zipfile


def inputs02_packet():
    """Read the exact run-41 packet as data; do not use its original uv cache."""
    from tools.gateway.docker import prepare as _api

    for path, expected in (
        (_api.INPUTS02_PACKET, _api.INPUTS02_PACKET_SHA),
        (_api.INPUTS02_SIDECAR, _api.INPUTS02_SIDECAR_SHA),
    ):
        _api.safe_component_path(path, _api.Path("/"), require_file=True)
        if _api.sha(path) != expected:
            raise ValueError("run-41 packet receipt mismatch")
    sidecar = _api.INPUTS02_SIDECAR.read_bytes()
    manifest = _api.strict_json(sidecar.decode())
    records = manifest.get("files")
    if manifest.get("run") != "run-20261018-41" or not isinstance(records, list):
        raise ValueError("run-41 manifest identity mismatch")
    names = set()
    for item in records:
        name = item.get("path") if isinstance(item, dict) else None
        if (
            not isinstance(name, str)
            or name.startswith("/")
            or "\\" in name
            or any(x in ("", ".", "..") for x in name.split("/"))
            or name in names
            or type(item.get("bytes")) is not int
            or item["bytes"] < 0
            or not isinstance(item.get("sha256"), str)
            or not _api.SHA_RE.fullmatch(item["sha256"])
        ):
            raise ValueError("unsafe run-41 manifest entry")
        names.add(name)
    payloads = {}
    with _api.zipfile.ZipFile(_api.INPUTS02_PACKET) as archive:
        seen, folded = set(), set()
        for member in archive.infolist():
            name = member.filename
            normalized = _api.unicodedata.normalize("NFC", name).casefold()
            mode = _api.stat.S_IFMT(member.external_attr >> 16)
            if (
                name.startswith("/")
                or "\\" in name
                or any(x in ("", ".", "..") for x in name.split("/"))
                or name in seen
                or normalized in folded
                or member.is_dir()
                or mode not in (0, _api.stat.S_IFREG)
                or member.flag_bits & 1
            ):
                raise ValueError("unsafe run-41 archive member")
            seen.add(name)
            folded.add(normalized)
        if (
            seen != names | {"EVIDENCE-MANIFEST.json"}
            or archive.read("EVIDENCE-MANIFEST.json") != sidecar
        ):
            raise ValueError("run-41 archive/sidecar mismatch")
        for item in records:
            body = archive.read(item["path"])
            if (
                len(body) != item["bytes"]
                or _api.hashlib.sha256(body).hexdigest() != item["sha256"]
            ):
                raise ValueError("run-41 payload mismatch: " + item["path"])
            if item["path"] == "candidate-runtime.lock" or item["path"].startswith(
                "downloads/pypi-"
            ):
                payloads[item["path"]] = body
    if (
        _api.hashlib.sha256(payloads["candidate-runtime.lock"]).hexdigest()
        != _api.INPUTS02_LOCK_SHA
    ):
        raise ValueError("frozen run-41 lock mismatch")
    pins = _api.parse_resolver_lock(payloads["candidate-runtime.lock"])
    if len(pins) != 116:
        raise ValueError("frozen run-41 pin count mismatch")
    return pins, payloads


def inputs02_url(url, host):
    from tools.gateway.docker import prepare as _api

    parsed = _api.urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != host
        or parsed.netloc != host
        or parsed.port is not None
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.query
        or not parsed.path.startswith("/")
    ):
        raise ValueError("noncanonical INPUTS-02 publisher URL")
    return parsed


def inputs02_fetch(url, limit, expected_size=None, expected_sha=None):
    from tools.gateway.docker import prepare as _api

    host = (
        "pypi.org" if "/pypi/" in _api.urllib.parse.urlsplit(url).path else "files.pythonhosted.org"
    )
    _api.inputs02_url(url, host)
    if type(limit) is not int or not 0 < limit <= _api.INPUTS02_MAX_ARTIFACT:
        raise ValueError("invalid INPUTS-02 transfer limit")
    opener = _api.urllib.request.build_opener(
        _api.urllib.request.ProxyHandler({}), _api.Inputs02NoRedirect()
    )
    request = _api.urllib.request.Request(
        url, headers={"User-Agent": "EzLLMRouter-INPUTS-02-data/1"}
    )

    def transfer():
        with opener.open(request, timeout=10) as response:
            if response.status != 200 or response.geturl() != url:
                raise ValueError("INPUTS-02 final HTTP status/URL mismatch")
            header = response.headers.get("Content-Length")
            if header is not None and (
                not header.isdigit()
                or int(header) > limit
                or (expected_size is not None and int(header) != expected_size)
            ):
                raise ValueError("INPUTS-02 declared length mismatch")
            body = response.read(limit + 1)
            if len(body) > limit:
                raise ValueError("INPUTS-02 transfer limit exceeded")
            return body

    body = _api.with_deadline(120, transfer)
    digest = _api.hashlib.sha256(body).hexdigest()
    if (expected_size is not None and len(body) != expected_size) or (
        expected_sha is not None and digest != expected_sha
    ):
        raise ValueError("INPUTS-02 published byte receipt mismatch")
    return body, {
        "url": url,
        "bytes": len(body),
        "sha256": digest,
        "status": "DOWNLOADED_DATA_ONLY",
    }


def inputs02_python_spec(spec):
    """Only simple numeric Requires-Python bounds are accepted; other forms fail closed."""
    from tools.gateway.docker import prepare as _api

    if not spec:
        return True
    target = _api.TARGET_PYTHON
    for term in spec.split(","):
        match = _api.re.fullmatch(r"\s*(>=|<=|==|!=|>|<)\s*([0-9]+(?:\.[0-9]+){0,2})\s*", term)
        if not match:
            raise ValueError("unsupported Requires-Python range: " + spec)
        op, value = match.groups()
        parts = tuple(int(x) for x in value.split("."))
        actual = target[: len(parts)]
        if not {
            ">=": actual >= parts,
            "<=": actual <= parts,
            "==": actual == parts,
            "!=": actual != parts,
            ">": actual > parts,
            "<": actual < parts,
        }[op]:
            return False
    return True


def inputs02_wheel_score(filename, name, version):
    from tools.gateway.docker import prepare as _api

    if not isinstance(filename, str) or not filename.endswith(".whl") or "/" in filename:
        return None
    parts = filename[:-4].split("-")
    if (
        len(parts) not in (5, 6)
        or _api.re.sub(r"[-_.]+", "-", parts[0]).lower() != name
        or parts[1] != version
    ):
        return None
    python_tags, abi_tags, platforms = parts[-3:]
    py_score = 0
    for py in python_tags.split("."):
        for abi in abi_tags.split("."):
            if py == "cp312" and abi == "cp312":
                py_score = max(py_score, 30)
            elif py.startswith("cp3") and py[2:].isdigit() and int(py[2:]) <= 312 and abi == "abi3":
                py_score = max(py_score, 20)
            elif py in ("py3", "py312") and abi == "none":
                py_score = max(py_score, 10)
    if py_score == 0:
        return None
    platform_score = 0
    for platform in platforms.split("."):
        if platform == "any":
            platform_score = max(platform_score, 1)
        match = _api.re.fullmatch(r"manylinux_2_([0-9]+)_aarch64", platform)
        if match and int(match.group(1)) <= 36:
            platform_score = max(platform_score, 100 + int(match.group(1)))
        if platform == "manylinux2014_aarch64":
            platform_score = max(platform_score, 117)
    return (platform_score, py_score, filename) if platform_score else None


def inputs02_select(metadata, name, version, hashes=None, source=False):
    from tools.gateway.docker import prepare as _api

    if (
        _api.re.sub(r"[-_.]+", "-", metadata.get("info", {}).get("name", "")).lower() != name
        or metadata.get("info", {}).get("version") != version
        or not isinstance(metadata.get("urls"), list)
    ):
        raise ValueError("exact PyPI metadata identity mismatch")
    if not _api.inputs02_python_spec(metadata["info"].get("requires_python")):
        raise ValueError("selected version excludes Python 3.12.15")
    choices = []
    for item in metadata["urls"]:
        if not isinstance(item, dict):
            continue
        filename = item.get("filename")
        digest = item.get("digests", {}).get("sha256")
        size = item.get("size")
        url = item.get("url")
        stamp = item.get("upload_time_iso_8601")
        if (
            not isinstance(filename, str)
            or not isinstance(digest, str)
            or not _api.SHA_RE.fullmatch(digest)
            or type(size) is not int
            or not 0 < size <= _api.INPUTS02_MAX_ARTIFACT
            or item.get("yanked") is not False
            or not isinstance(stamp, str)
        ):
            continue
        try:
            uploaded = _api.dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            _api.inputs02_url(url, "files.pythonhosted.org")
            if not _api.inputs02_python_spec(item.get("requires_python")):
                continue
        except (ValueError, TypeError):
            continue
        if uploaded > _api.INPUTS02_CUTOFF:
            continue
        if source:
            score = (
                (1, 0, filename)
                if (
                    item.get("packagetype") == "sdist"
                    and filename == name.replace("-", "_") + "-" + version + ".tar.gz"
                )
                else None
            )
            # Some publishers use a hyphenated sdist basename.
            if (
                score is None
                and item.get("packagetype") == "sdist"
                and filename == name + "-" + version + ".tar.gz"
            ):
                score = (1, 0, filename)
        else:
            score = (
                _api.inputs02_wheel_score(filename, name, version)
                if item.get("packagetype") == "bdist_wheel"
                else None
            )
        if score is None or (hashes is not None and digest not in hashes):
            continue
        choices.append(
            (
                score,
                {
                    "filename": filename,
                    "url": url,
                    "bytes": size,
                    "sha256": digest,
                    "uploaded": stamp,
                    "yanked": False,
                    "tags": filename[:-4].split("-")[-3:] if not source else [],
                },
            )
        )
    if not choices:
        raise ValueError("no compatible exact-version artifact with allowed digest/cutoff")
    return max(choices, key=lambda x: x[0])[1]


def inputs02_archive_members(members):
    from tools.gateway.docker import prepare as _api

    names, folded, types = set(), set(), {}
    for name, is_file, is_dir, is_link, is_special in members:
        clean = name[:-1] if is_dir and name.endswith("/") else name
        normalized = _api.unicodedata.normalize("NFC", clean).casefold()
        if (
            not clean
            or clean.startswith("/")
            or "\\" in clean
            or any(x in ("", ".", "..") for x in clean.split("/"))
            or normalized in folded
            or name in names
            or is_link
            or is_special
            or not (is_file or is_dir)
        ):
            raise ValueError("unsafe INPUTS-02 archive member")
        names.add(name)
        folded.add(normalized)
        types[clean] = is_file
    for name in types:
        parts = name.split("/")
        if any(types.get("/".join(parts[:i])) for i in range(1, len(parts))):
            raise ValueError("file/directory archive path conflict")
    return names


def inputs02_check_sdist(body, name, version):
    from tools.gateway.docker import prepare as _api

    with _api.tarfile.open(fileobj=_api.io.BytesIO(body), mode="r:gz") as archive:
        members = archive.getmembers()
        _api.inputs02_archive_members(
            [
                (
                    m.name,
                    m.isfile(),
                    m.isdir(),
                    m.issym() or m.islnk(),
                    not (m.isfile() or m.isdir() or m.issym() or m.islnk()),
                )
                for m in members
            ]
        )
        if sum(m.size for m in members if m.isfile()) > _api.INPUTS02_MAX_TOTAL:
            raise ValueError("sdist expansion budget exceeded")
        pkg_infos = [m for m in members if m.isfile() and m.name.endswith("/PKG-INFO")]
        if len(pkg_infos) != 1:
            raise ValueError("sdist PKG-INFO absent/ambiguous")
        parsed = _api.email.parser.BytesParser().parsebytes(
            archive.extractfile(pkg_infos[0]).read()
        )
        if (
            _api.re.sub(r"[-_.]+", "-", parsed.get("Name", "")).lower() != name
            or parsed.get("Version") != version
        ):
            raise ValueError("sdist PKG-INFO identity mismatch")
        return {
            "members": len(members),
            "pkg_info_path": pkg_infos[0].name,
            "pkg_info_sha256": _api.hashlib.sha256(
                archive.extractfile(pkg_infos[0]).read()
            ).hexdigest(),
        }


def inputs02_check_wheel(body, name, version, selected):
    from tools.gateway.docker import prepare as _api

    with _api.zipfile.ZipFile(_api.io.BytesIO(body)) as archive:
        members = archive.infolist()
        _api.inputs02_archive_members(
            [
                (
                    m.filename,
                    not m.is_dir(),
                    m.is_dir(),
                    _api.stat.S_IFMT(m.external_attr >> 16) == _api.stat.S_IFLNK,
                    _api.stat.S_IFMT(m.external_attr >> 16)
                    not in (0, _api.stat.S_IFREG, _api.stat.S_IFDIR, _api.stat.S_IFLNK),
                )
                for m in members
            ]
        )
        if (
            any(m.flag_bits & 1 for m in members)
            or sum(m.file_size for m in members) > _api.INPUTS02_MAX_TOTAL
        ):
            raise ValueError("encrypted or oversized wheel expansion")
        if archive.testzip() is not None:
            raise ValueError("wheel CRC mismatch")
        files = {m.filename for m in members if not m.is_dir()}
        metadata_paths = [x for x in files if x.endswith(".dist-info/METADATA")]
        if len(metadata_paths) != 1:
            raise ValueError("wheel METADATA absent/ambiguous")
        dist = metadata_paths[0][: -len("METADATA")]
        wheel_path, record_path = dist + "WHEEL", dist + "RECORD"
        if wheel_path not in files or record_path not in files:
            raise ValueError("wheel WHEEL/RECORD absent")
        metadata = _api.email.parser.BytesParser().parsebytes(archive.read(metadata_paths[0]))
        wheel = _api.email.parser.BytesParser().parsebytes(archive.read(wheel_path))
        if (
            _api.re.sub(r"[-_.]+", "-", metadata.get("Name", "")).lower() != name
            or metadata.get("Version") != version
            or not _api.inputs02_python_spec(metadata.get("Requires-Python"))
        ):
            raise ValueError("wheel METADATA identity/Python mismatch")
        tags = wheel.get_all("Tag", [])
        declared = set(tags)
        filename_tags = {
            a + "-" + b + "-" + c
            for a in selected["tags"][0].split(".")
            for b in selected["tags"][1].split(".")
            for c in selected["tags"][2].split(".")
        }
        if not declared.intersection(filename_tags):
            raise ValueError("wheel WHEEL tag mismatch")
        rows = list(_api.csv.reader(_api.io.StringIO(archive.read(record_path).decode("utf-8"))))
        seen = set()
        for row in rows:
            if len(row) != 3 or row[0] not in files or row[0] in seen:
                raise ValueError("wheel RECORD path/row mismatch")
            seen.add(row[0])
            if row[0] == record_path:
                if row[1] or row[2]:
                    raise ValueError("wheel RECORD self-hash must be empty")
                continue
            if not row[1].startswith("sha256=") or not row[2].isdigit():
                raise ValueError("wheel RECORD hash/size absent")
            raw = archive.read(row[0])
            expected = _api.base64.urlsafe_b64decode(row[1][7:] + "=" * (-len(row[1][7:]) % 4))
            if len(raw) != int(row[2]) or _api.hashlib.sha256(raw).digest() != expected:
                raise ValueError("wheel RECORD byte mismatch")
        if seen != files:
            raise ValueError("wheel RECORD file census mismatch")
        return {
            "members": len(members),
            "metadata_sha256": _api.hashlib.sha256(archive.read(metadata_paths[0])).hexdigest(),
            "wheel_sha256": _api.hashlib.sha256(archive.read(wheel_path)).hexdigest(),
            "record_sha256": _api.hashlib.sha256(archive.read(record_path)).hexdigest(),
            "requires_dist": metadata.get_all("Requires-Dist", []),
            "requires_python": metadata.get("Requires-Python"),
            "tags": tags,
        }


def inputs02_collect_core(
    outdir, pins, packet_payloads, fetcher=inputs02_fetch, maturin_receipt=None
):
    """Inert exact-version metadata/wheel/source collection. No resolver or backend."""

    if not outdir.is_dir() or outdir.is_symlink():
        raise ValueError("INPUTS-02 output must be a real fresh directory")
    metadata_dir = _api.child_dir(outdir, "metadata")
    wheel_dir = _api.child_dir(outdir, "wheels")
    source_dir = _api.child_dir(outdir, "sources")
    records = {}
    transferred = 0
    stop = None
    metadata = {}

    def get(url, limit, expected_size=None, expected_sha=None):
        nonlocal transferred
        remaining = _api.INPUTS02_MAX_TOTAL - transferred
        if expected_size is not None and expected_size > remaining:
            raise ValueError("INPUTS-02 2 GiB aggregate transfer budget exceeded")
        if remaining <= 0:
            raise ValueError("INPUTS-02 aggregate transfer budget exhausted")
        body, evidence = fetcher(url, min(limit, remaining), expected_size, expected_sha)
        if (
            len(body) > min(limit, remaining)
            or evidence.get("sha256") != _api.hashlib.sha256(body).hexdigest()
        ):
            raise ValueError("INPUTS-02 fetcher byte evidence mismatch")
        transferred += len(body)
        return body, evidence

    order = ["openai", "anyio"] + sorted(set(pins) - {"openai", "anyio"})
    for name in order:
        pin = pins[name]
        version = pin["version"]
        key = name + "-" + version
        record = {
            "name": name,
            "version": version,
            "status": "PENDING",
            "lock_hash_count": len(pin["hashes"]),
        }
        records[name] = record
        try:
            snapshot_name = "downloads/pypi-" + key + ".json"
            if snapshot_name in packet_payloads:
                body = packet_payloads[snapshot_name]
                evidence = {
                    "status": "REUSED_RUN41_PACKET",
                    "bytes": len(body),
                    "sha256": _api.hashlib.sha256(body).hexdigest(),
                }
            else:
                url = (
                    "https://pypi.org/pypi/"
                    + _api.urllib.parse.quote(name, safe="")
                    + "/"
                    + _api.urllib.parse.quote(version, safe="")
                    + "/json"
                )
                body, evidence = get(url, _api.INPUTS02_MAX_METADATA)
            parsed = _api.strict_json(body.decode("utf-8"))
            if (
                _api.re.sub(r"[-_.]+", "-", parsed.get("info", {}).get("name", "")).lower() != name
                or parsed.get("info", {}).get("version") != version
            ):
                raise ValueError("exact metadata name/version mismatch")
            output = metadata_dir / (key + ".json")
            _api.write_new(output, body)
            record["metadata"] = {"path": str(output), **evidence}
            metadata[name] = parsed
            selected = _api.inputs02_select(parsed, name, version, pin["hashes"])
            record["wheel_candidate"] = selected
            record["status"] = "EXACT_WHEEL_METADATA_SELECTED_BYTES_PENDING"
            if name in ("openai", "anyio"):
                source = _api.inputs02_select(parsed, name, version, source=True)
                record["source_candidate"] = source
                source_body, source_evidence = get(
                    source["url"], _api.INPUTS02_MAX_ARTIFACT, source["bytes"], source["sha256"]
                )
                source_inspection = _api.inputs02_check_sdist(source_body, name, version)
                source_output = source_dir / source["filename"]
                _api.write_new(source_output, source_body)
                record["source_acquired"] = {
                    "path": str(source_output),
                    **source_evidence,
                    "inspection": source_inspection,
                }
        except Exception as exc:
            record.update(
                {
                    "status": "BLOCKED",
                    "error_type": type(exc).__name__,
                    "error": _api.safe_http_error(exc),
                }
            )
            stop = {
                "name": name,
                "phase": "metadata_or_source",
                "error_type": type(exc).__name__,
                "error": _api.safe_http_error(exc),
            }
            break
    if stop is None:
        try:
            maturin = _api.strict_json(
                packet_payloads["downloads/pypi-maturin-1.15.0.json"].decode()
            )
            expected_maturin = maturin_receipt or {
                "filename": "maturin-1.15.0-py3-none-manylinux_2_17_aarch64.manylinux2014_aarch64.musllinux_1_1_aarch64.whl",
                "sha256": "0ebf9767892725083138e671c34482c660317a2f3d6a29fc0e0f34e9d8c99136",
                "bytes": 10_083_468,
            }
            selected = _api.inputs02_select(
                maturin, "maturin", "1.15.0", {expected_maturin["sha256"]}
            )
            if any(
                selected[key] != expected_maturin[key] for key in ("filename", "sha256", "bytes")
            ):
                raise ValueError("Maturin candidate receipt drift")
            _api.write_new(
                metadata_dir / "maturin-1.15.0.json",
                packet_payloads["downloads/pypi-maturin-1.15.0.json"],
            )
            body, evidence = get(
                selected["url"], _api.INPUTS02_MAX_ARTIFACT, selected["bytes"], selected["sha256"]
            )
            inspection = _api.inputs02_check_wheel(body, "maturin", "1.15.0", selected)
            output = wheel_dir / selected["filename"]
            _api.write_new(output, body)
            records["maturin_build"] = {
                "name": "maturin",
                "version": "1.15.0",
                "status": "ACQUIRED_DATA_ONLY_NOT_INSTALLED",
                "candidate": selected,
                "path": str(output),
                "evidence": evidence,
                "inspection": inspection,
            }
        except Exception as exc:
            stop = {
                "name": "maturin",
                "phase": "build_wheel",
                "error_type": type(exc).__name__,
                "error": _api.safe_http_error(exc),
            }
            records["maturin_build"] = {"status": "BLOCKED", **stop}
    if stop is None:
        for name in sorted(pins):
            record = records[name]
            selected = record["wheel_candidate"]
            try:
                body, evidence = get(
                    selected["url"],
                    _api.INPUTS02_MAX_ARTIFACT,
                    selected["bytes"],
                    selected["sha256"],
                )
                inspection = _api.inputs02_check_wheel(body, name, record["version"], selected)
                output = wheel_dir / selected["filename"]
                _api.write_new(output, body)
                record.update(
                    {
                        "status": "ACQUIRED_DATA_ONLY_NOT_INSTALLED",
                        "wheel_acquired": {
                            "path": str(output),
                            **evidence,
                            "inspection": inspection,
                        },
                    }
                )
            except Exception as exc:
                record.update(
                    {
                        "status": "BLOCKED",
                        "error_type": type(exc).__name__,
                        "error": _api.safe_http_error(exc),
                    }
                )
                stop = {
                    "name": name,
                    "phase": "runtime_wheel",
                    "error_type": type(exc).__name__,
                    "error": _api.safe_http_error(exc),
                }
                break
    return {
        "status": "PARTIAL_INPUTS_NOT_BUILD_AUTHORITY"
        if stop
        else "ARTIFACT_DATA_ACQUIRED_NOT_BUILD_AUTHORITY",
        "parent_packet_sha256": _api.INPUTS02_PACKET_SHA,
        "parent_lock_sha256": _api.INPUTS02_LOCK_SHA,
        "target": "CPython 3.12.15 aarch64 manylinux glibc<=2.36",
        "cutoff": _api.INPUTS02_CUTOFF.isoformat(),
        "new_transfer_bytes": transferred,
        "stop": stop,
        "records": records,
        "ready_for_build": False,
        "owner_build_approval": False,
    }


def inputs02_collect(args):
    from tools.gateway.docker import prepare as _api

    pins, payloads = (
        _api.inputs02_packet()
    )  # Every predecessor byte checked before output creation.
    if _api.Path.cwd().resolve() != _api.ROOT:
        raise ValueError("run INPUTS-02 from independent EzLLMRouter root")
    if args.handoff_parent != str(_api.OWNER_HANDOFF_PARENT):
        raise ValueError("INPUTS-02 handoff parent must match EZLLMROUTER_HANDOFF_ROOT")
    _api.INPUTS02_PARENT.mkdir(mode=0o700, exist_ok=True)
    _api.safe_component_path(_api.INPUTS02_PARENT, _api.Path("/private/tmp"))
    if not _api.RUN_RE.fullmatch(args.new_run):
        raise ValueError("unsafe INPUTS-02 run name")
    run = _api.INPUTS02_PARENT / args.new_run
    handoff = _api.OWNER_HANDOFF_PARENT / ("ezllmrouter-wpb-artifacts-" + args.new_run)
    if run.exists() or run.is_symlink() or handoff.exists() or handoff.is_symlink():
        raise ValueError("INPUTS-02 run/handoff collision")
    run.mkdir(mode=0o700, exist_ok=False)
    handoff.mkdir(mode=0o700, exist_ok=False)
    result = _api.inputs02_collect_core(handoff, pins, payloads)
    files = []
    for path in sorted(handoff.rglob("*")):
        if path.is_file() or path.is_symlink():
            _api.safe_component_path(path, handoff, require_file=True)
            files.append(
                {
                    "path": str(path.relative_to(handoff)),
                    "bytes": path.stat().st_size,
                    "sha256": _api.sha(path),
                }
            )
    manifest = {
        "status": result["status"],
        "parent_packet_sha256": _api.INPUTS02_PACKET_SHA,
        "parent_lock_sha256": _api.INPUTS02_LOCK_SHA,
        "files": files,
        "result": result,
        "manifest_self_excluded": True,
    }
    _api.write_new(handoff / "ACQUISITION-MANIFEST.json", _api.json_bytes(manifest))
    _api.write_new(
        run / "HANDOFF-RECEIPT.json",
        _api.json_bytes(
            {
                "handoff": str(handoff),
                "manifest_sha256": _api.sha(handoff / "ACQUISITION-MANIFEST.json"),
                "status": result["status"],
            }
        ),
    )
    return {
        "status": result["status"],
        "handoff": str(handoff),
        "manifest_sha256": _api.sha(handoff / "ACQUISITION-MANIFEST.json"),
        "candidate_packages": len(pins),
        "new_transfer_bytes": result["new_transfer_bytes"],
        "stop": result["stop"],
        "ready_for_build": False,
    }


# Delay the facade binding until definitions exist so either import order works.
from tools.gateway.docker import prepare as _api
