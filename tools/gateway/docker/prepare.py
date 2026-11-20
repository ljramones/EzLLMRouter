#!/usr/bin/env python3
"""Bounded DKR-01 data preparation. Never builds, installs, or starts services."""

import argparse
import ast
import base64
import csv
import datetime as dt
import email.parser
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[3]
KIT = Path(__file__).resolve().parent
INPUTS = (
    Path(
        os.environ.get(
            "EZLLMROUTER_BUILD_INPUTS", str(ROOT / ".artifacts/retained-inputs/BUILD-INPUTS.json")
        )
    )
    .expanduser()
    .resolve()
)
SOURCE = (
    Path(
        os.environ.get(
            "EZLLMROUTER_LITELLM_SOURCE",
            str(ROOT / ".artifacts/retained-inputs/litellm-1.105.1.tar.gz"),
        )
    )
    .expanduser()
    .resolve()
)
SOURCE_SHA = "f1a274db0b2bcc78c34ed34c06df2c1dcd0dc038469193684927f6bb2cab2d97"
PKG_INFO_SHA = "2781e2079443c555c32c49d7bd06fc9beb70c9d0936d05805dea34dd500e127c"
UV = Path(os.environ.get("EZLLMROUTER_REVIEWED_UV", shutil.which("uv") or "/usr/bin/uv"))
UV_SHA = "cfe5e5695316639f9820e8e57d0732e8a361311c03f1ea1786f4fc879cebf4c5"
RUN_PARENT = Path("/private/tmp/ezllmrouter-wp-b-docker-01")
MAX_AGGREGATE = 2 * 1024 * 1024 * 1024
MAX_TRANSFER = 50_000_000
TRANSFER_SECONDS = 60
RESOLVE_SECONDS = 180
HOSTS = {
    "pypi.org",
    "files.pythonhosted.org",
    "auth.docker.io",
    "registry-1.docker.io",
    "static.crates.io",
    "index.crates.io",
    "static.rust-lang.org",
    "api.github.com",
    "raw.githubusercontent.com",
    "codeload.github.com",
}
CONFIG_DELIVERY_ORIGIN = "https://production.cloudfront.docker.com"
OWNER_HANDOFF_PARENT = (
    Path(os.environ.get("EZLLMROUTER_HANDOFF_ROOT", str(Path.home() / "Downloads")))
    .expanduser()
    .resolve()
)
PREDECESSOR_ZIP = (
    OWNER_HANDOFF_PARENT / "ezllmrouter-wpb-inputs-run-20261017-40/INPUTS-EVIDENCE.zip"
)
PREDECESSOR_MANIFEST = PREDECESSOR_ZIP.with_name("EVIDENCE-MANIFEST.json")
PREDECESSOR_ZIP_SHA = "1cca3b26fe9850d3fdb1b000d9937146c9aff10bf9c3a1971f1149551aad6a67"
PREDECESSOR_MANIFEST_SHA = "8988ddca74afaea8b1578ec94f3d2f796d08bd836eafeae84122e481626c9b73"
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
RUN_RE = re.compile(r"run-[0-9]{8}-[0-9]{2}\Z")
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
PHASES = ("wheel", "runtime", "tools")
TARGET_PYTHON = (3, 12, 15)
TARGET_GLIBC = (2, 36)
INPUTS02_PARENT = Path("/private/tmp/ezllmrouter-wp-b-inputs-02")
INPUTS02_PACKET = (
    OWNER_HANDOFF_PARENT / "ezllmrouter-wpb-inputs-run-20261018-41/INPUTS-EVIDENCE.zip"
)
INPUTS02_SIDECAR = INPUTS02_PACKET.with_name("EVIDENCE-MANIFEST.json")
INPUTS02_PACKET_SHA = "84823f52252b104bcf5c57d91b398f64a25f4cbfeb64b35be3a6dabf7640f081"
INPUTS02_SIDECAR_SHA = "823f5842c827a94ae784e53d70134475d0c259767cf6d881b0b3a60cfd008f73"
INPUTS02_LOCK_SHA = "6f2bfaea5f46c24688d5a815e7264892e4104945cb37516ecc1a339e9239f1ce"
INPUTS02_CUTOFF = dt.datetime(2026, 10, 17, 23, 59, 59, tzinfo=dt.timezone.utc)
INPUTS02_MAX_TOTAL = 2 * 1024 * 1024 * 1024
INPUTS02_MAX_ARTIFACT = 512 * 1024 * 1024
INPUTS02_MAX_METADATA = 10 * 1024 * 1024
OCI_QUERIES = {
    "python_builder": {
        "role": "python_builder",
        "repository": "library/python",
        "tag": "3.12.15-bookworm",
        "platform": "linux/arm64/v8",
    },
    "python_runtime_and_tools": {
        "role": "python_runtime_and_tools",
        "repository": "library/python",
        "tag": "3.12.15-slim-bookworm",
        "platform": "linux/arm64/v8",
    },
    "rust_toolchain": {
        "role": "rust_toolchain",
        "repository": "library/rust",
        "tag": "1.88.0-bookworm",
        "platform": "linux/arm64/v8",
    },
}
HARNESS = {
    "driver.py",
    "receiver.py",
    "app_wrapper.py",
    "transport_guard.py",
    "intent_file.py",
    "fixtures.json",
    "route-config.yaml",
}
KIT_FILES = {
    "Dockerfile.gateway",
    "Dockerfile.tools",
    ".dockerignore",
    "requirements-build.lock",
    "requirements-runtime.lock",
}


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def pairs_unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def strict_json(raw):
    return json.loads(
        raw,
        object_pairs_hook=pairs_unique,
        parse_constant=lambda x: (_ for _ in ()).throw(ValueError("nonfinite JSON: " + x)),
    )


def read_json(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("missing or linked JSON input: " + str(path))
    return strict_json(path.read_text(encoding="utf-8"))


def safe_component_path(path, anchor, require_file=False):
    path = Path(path)
    anchor = Path(anchor)
    if not path.is_absolute() or not anchor.is_absolute():
        raise ValueError("absolute path required")
    try:
        parts = path.relative_to(anchor).parts
    except ValueError as caught_error:
        raise ValueError("path outside approved anchor") from caught_error
    for part in parts:
        if part in ("", ".", ".."):
            raise ValueError("unsafe path component")
    current = anchor
    for part in (None,) + parts:
        if part is not None:
            current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError as caught_error:
            raise ValueError("missing path component: " + str(current)) from caught_error
        if stat.S_ISLNK(mode):
            raise ValueError("symlink component: " + str(current))
        if current != path and not stat.S_ISDIR(mode):
            raise ValueError("non-directory path component: " + str(current))
    mode = path.lstat().st_mode
    if require_file and not stat.S_ISREG(mode):
        raise ValueError("regular file required: " + str(path))
    if not require_file and not stat.S_ISDIR(mode):
        raise ValueError("directory required: " + str(path))
    return path


def run_path(value, create=False):
    RUN_PARENT.mkdir(mode=0o700, exist_ok=True)
    safe_component_path(RUN_PARENT, Path("/private/tmp"))
    path = Path(value)
    if path.parent != RUN_PARENT or not RUN_RE.fullmatch(path.name):
        raise ValueError("run must be a direct named child of DKR-01 scratch parent")
    if create:
        path.mkdir(mode=0o700, exist_ok=False)
    return safe_component_path(path, RUN_PARENT)


def child_dir(run, name):
    if not NAME_RE.fullmatch(name):
        raise ValueError("unsafe run child")
    path = run / name
    if not path.exists() and not path.is_symlink():
        path.mkdir(mode=0o700)
    return safe_component_path(path, run)


def write_new(path, data):
    if path.exists() or path.is_symlink():
        raise ValueError("output collision: " + str(path))
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(str(path), flags, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    return path


def json_bytes(data):
    return (json.dumps(data, indent=2, sort_keys=True) + "\n").encode()


def receipt(run, kind, data):
    directory = child_dir(run, "receipts")
    record = {"kind": kind, "utc": utc(), **data}
    name = kind + "-" + uuid.uuid4().hex + ".json"
    write_new(directory / name, json_bytes(record))
    return record


def run_bytes(run):
    total = 0
    for base, dirs, files in os.walk(run, followlinks=False):
        for name in dirs + files:
            p = Path(base) / name
            mode = p.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise ValueError("linked run content: " + str(p))
            if name in files:
                if not stat.S_ISREG(mode):
                    raise ValueError("special run content: " + str(p))
                total += p.stat().st_size
    return total


def load_inputs():
    data = read_json(INPUTS)
    if data.get("schema") != "ezllmrouter-wp-b-dkr01-c02-inputs-1":
        raise ValueError("input schema mismatch")
    if data.get("selected_source", {}).get("sdist_sha256") != SOURCE_SHA:
        raise ValueError("selected source input mismatch")
    queue = data.get("acquisition_queue")
    if (
        not isinstance(queue, list)
        or any(not isinstance(x, dict) for x in queue)
        or len(queue) != len({x.get("id") for x in queue})
    ):
        raise ValueError("invalid or duplicate acquisition IDs")
    target = data.get("target", {})
    if (
        target.get("python_version") != "3.12.15 proposed; image tag existence unverified"
        or target.get("python_resolver_patch") != "3.12.15"
        or target.get("glibc_minimum") != [2, 36]
    ):
        raise ValueError("proposed Python/glibc target mismatch")
    images = data.get("oci_images")
    if (
        not isinstance(images, list)
        or len(images) != len(OCI_QUERIES)
        or any(not isinstance(x, dict) or x.get("role") not in OCI_QUERIES for x in images)
        or {x["role"] for x in images} != set(OCI_QUERIES)
    ):
        raise ValueError("exact OCI role set absent or duplicated")
    for image in images:
        expected = OCI_QUERIES[image["role"]]
        if (
            image.get("metadata_query") != expected
            or image.get("proposed_tag")
            != "docker.io/" + expected["repository"] + ":" + expected["tag"]
            or image.get("platform") != expected["platform"]
        ):
            raise ValueError("OCI role/query/tag mismatch: " + image["role"])
    return data


def validate_url(url):
    p = urllib.parse.urlsplit(url)
    if (
        p.scheme != "https"
        or p.hostname not in HOSTS
        or p.port is not None
        or p.username
        or p.password
        or p.fragment
        or not p.path.startswith("/")
        or p.netloc != p.hostname
    ):
        raise ValueError("noncanonical publisher HTTPS URL")
    return p


def url_evidence(url):
    """Capture a URL's location without credential or signed-query values."""
    parsed = urllib.parse.urlsplit(url)
    return {
        "origin": parsed.scheme + "://" + (parsed.hostname or ""),
        "path": parsed.path,
        "query_keys": sorted(
            {key for key, _ in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)}
        ),
        "url_sha256": hashlib.sha256(url.encode()).hexdigest(),
    }


def safe_http_error(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return "HTTP status " + str(exc.code)
    if isinstance(exc, urllib.error.URLError):
        return "URL transport error (" + type(exc.reason).__name__ + ")"
    return str(exc)


class CheckedRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, trace=None, config_binding=None):
        self.chain = []
        self.trace = trace if trace is not None else []
        self.config_binding = config_binding
        super().__init__()

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        event = {
            "event": "redirect",
            "status": code,
            "from": url_evidence(req.full_url),
            "to": url_evidence(newurl),
        }
        self.trace.append(event)
        if code not in (301, 302, 303, 307, 308) or len(self.chain) >= 5:
            raise ValueError("redirect status/count not allowed")
        target = urllib.parse.urlsplit(newurl)
        source = urllib.parse.urlsplit(req.full_url)
        delivery = target.scheme + "://" + (target.hostname or "") == CONFIG_DELIVERY_ORIGIN
        if delivery:
            binding = self.config_binding
            if (
                not binding
                or binding.get("initial_url") != binding.get("verified_url")
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", binding.get("digest", ""))
                or type(binding.get("size")) is not int
                or not 0 < binding["size"] <= 5_000_000
                or (
                    source.hostname
                    not in ("registry-1.docker.io", "production.cloudfront.docker.com")
                )
            ):
                raise ValueError("unbound OCI config delivery redirect")
            if (
                target.scheme != "https"
                or target.netloc != target.hostname
                or target.port is not None
                or target.username
                or target.password
                or target.fragment
                or not target.path.startswith("/")
            ):
                raise ValueError("noncanonical OCI config delivery URL")
        elif self.config_binding is not None and newurl != self.config_binding["initial_url"]:
            raise ValueError("OCI config redirect location not approved")
        else:
            validate_url(newurl)
        self.chain.append(event)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            raise ValueError("redirect refused by HTTP handler")
        if source.netloc != target.netloc:
            # HTTPRedirectHandler copies headers, including Authorization. Rebuild without secrets.
            safe = {
                k: v
                for k, v in redirected.headers.items()
                if k.lower() not in ("authorization", "proxy-authorization", "cookie", "cookie2")
            }
            redirected = urllib.request.Request(
                newurl, headers=safe, method=redirected.get_method()
            )
            event["cross_origin_credentials_removed"] = True
        return redirected


class DeadlineExceeded(Exception):
    pass


def with_deadline(seconds, action):
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)

    def alarm(_signum, _frame):
        raise DeadlineExceeded("total transfer deadline exceeded")

    signal.signal(signal.SIGALRM, alarm)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        return action()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, *previous_timer)


def http_bytes(
    url, limit, headers=None, opener=None, trace=None, config_binding=None, transport_handler=None
):
    validate_url(url)
    if config_binding is not None and (
        config_binding.get("initial_url") != url or config_binding.get("verified_url") != url
    ):
        raise ValueError("OCI config binding/initial URL mismatch")
    if not isinstance(limit, int) or not 0 < limit <= MAX_TRANSFER:
        raise ValueError("transfer bound invalid")
    trace = trace if trace is not None else []
    trace.append({"event": "request", "url": url_evidence(url)})
    redirect = CheckedRedirect(trace, config_binding)
    opener = opener or urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        redirect,
        *([transport_handler] if transport_handler else []),
    )
    request = urllib.request.Request(
        url, headers={"User-Agent": "EzLLMRouter-DKR-01-c02-data/1", **(headers or {})}
    )
    started = time.monotonic()

    def transfer():
        with opener.open(request, timeout=10) as response:
            status = getattr(response, "status", None)
            if status != 200:
                raise ValueError("final HTTP status is not 200: " + str(status))
            final_url = response.geturl()
            if final_url != url:
                if not redirect.chain:
                    raise ValueError("unobserved final URL change")
                if redirect.chain[-1]["to"] != url_evidence(final_url):
                    raise ValueError("final URL not last checked redirect")
            elif not redirect.chain:
                validate_url(final_url)
            raw_length = response.headers.get("Content-Length")
            length = int(raw_length) if raw_length is not None else None
            if length is not None and (length < 0 or length > limit):
                raise ValueError("declared HTTP length exceeds bound")
            blocks = []
            total = 0
            while True:
                block = response.read(min(1024 * 1024, limit - total + 1))
                if not block:
                    break
                total += len(block)
                if total > limit:
                    raise ValueError("HTTP body exceeds bound")
                blocks.append(block)
            if length is not None and total != length:
                raise ValueError("HTTP Content-Length mismatch")
            return b"".join(blocks), {
                "status": status,
                "final_url": url_evidence(final_url),
                "declared_length": length,
                "content_digest_header": response.headers.get("Docker-Content-Digest"),
                "redirect_chain": redirect.chain,
            }

    body, meta = with_deadline(TRANSFER_SECONDS, transfer)
    meta.update(
        {
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
    )
    return body, meta


def fetch_entry(run, item, opener=None):
    if set(item) != {
        "id",
        "kind",
        "url",
        "filename",
        "max_bytes",
        "expected_bytes",
        "expected_sha256",
    }:
        raise ValueError("acquisition entry has missing or extra fields")
    if not NAME_RE.fullmatch(item["id"]) or not NAME_RE.fullmatch(item["filename"]):
        raise ValueError("unsafe acquisition ID/filename")
    validate_url(item["url"])
    maximum = item["max_bytes"]
    if not isinstance(maximum, int) or not 0 < maximum <= MAX_TRANSFER:
        raise ValueError("invalid per-transfer bound")
    if item["expected_sha256"] is not None and not SHA_RE.fullmatch(item["expected_sha256"]):
        raise ValueError("invalid expected SHA-256")
    if item["expected_bytes"] is not None and (
        type(item["expected_bytes"]) is not int
        or item["expected_bytes"] < 0
        or item["expected_bytes"] > maximum
    ):
        raise ValueError("invalid expected length")
    downloads = child_dir(run, "downloads")
    partial = child_dir(run, "partial")
    child_dir(run, "receipts")
    destination = downloads / item["filename"]
    if destination.exists() or destination.is_symlink():
        raise ValueError("download collision")
    if run_bytes(run) + maximum > MAX_AGGREGATE:
        raise ValueError("2 GiB aggregate reservation exceeded")
    record = {
        "id": item["id"],
        "kind": item["kind"],
        "original_url": item["url"],
        "expected_sha256": item["expected_sha256"],
        "expected_bytes": item["expected_bytes"],
        "max_bytes": maximum,
        "total_deadline_seconds": TRANSFER_SECONDS,
    }
    part = partial / (item["id"] + "-" + uuid.uuid4().hex + ".part")
    try:
        body, meta = http_bytes(item["url"], maximum, opener=opener)
        if item["kind"] == "official-pypi-version-metadata":
            metadata = strict_json(body.decode("utf-8"))
            parts = validate_url(item["url"]).path.split("/")
            expected_name, expected_version = parts[2], parts[3]
            info = metadata.get("info", {})
            normalize = lambda x: re.sub(r"[-_.]+", "-", x).lower()
            if (
                normalize(info.get("name", "")) != normalize(expected_name)
                or info.get("version") != expected_version
                or not isinstance(metadata.get("urls"), list)
            ):
                raise ValueError("PyPI version metadata identity mismatch")
            record["metadata_name"] = info["name"]
            record["metadata_version"] = info["version"]
        record.update(meta)
        record["hash_match"] = (
            item["expected_sha256"] is None or meta["sha256"] == item["expected_sha256"]
        )
        record["size_match"] = (
            item["expected_bytes"] is None or meta["bytes"] == item["expected_bytes"]
        )
        if not (record["hash_match"] and record["size_match"]):
            raise ValueError("published hash or size mismatch")
        write_new(part, body)
        os.link(part, destination, follow_symlinks=False)
        part.unlink()
        if sha(destination) != meta["sha256"] or destination.stat().st_size != meta["bytes"]:
            raise ValueError("committed output drift")
        record["committed_path"] = str(destination)
        record["status"] = (
            "DOWNLOADED_AND_HASH_MATCHED"
            if item["expected_sha256"]
            else "OFFICIAL_METADATA_LOCAL_HASH_RECORDED"
        )
    except Exception as exc:
        record.update({"status": "FAILED", "error_type": type(exc).__name__, "error": str(exc)})
    receipt(run, "fetch", record)
    return record


def static_requirements():
    if SOURCE.is_symlink() or sha(SOURCE) != SOURCE_SHA:
        raise ValueError("selected source mismatch")
    with tarfile.open(SOURCE, "r:gz") as archive:
        matches = [m for m in archive.getmembers() if m.name == "litellm-1.105.1/PKG-INFO"]
        if len(matches) != 1 or not matches[0].isreg():
            raise ValueError("regular PKG-INFO member missing")
        raw = archive.extractfile(matches[0]).read()
    if hashlib.sha256(raw).hexdigest() != PKG_INFO_SHA:
        raise ValueError("PKG-INFO mismatch")
    selected = []
    for line in raw.decode().splitlines():
        if not line.startswith("Requires-Dist: "):
            continue
        value = line[len("Requires-Dist: ") :]
        if " ; " not in value:
            selected.append(value)
            continue
        name, marker = value.split(" ; ", 1)
        if "extra == 'proxy'" in marker:
            marker = (
                marker.replace(" and extra == 'proxy'", "").replace("extra == 'proxy'", "").strip()
            )
            if "extra" in marker:
                raise ValueError("unhandled extra marker")
            selected.append(name + (" ; " + marker if marker else ""))
        elif "extra" not in marker:
            selected.append(value)
    if (
        len(selected) != 54
        or "litellm-enterprise==0.1.73" not in selected
        or "litellm-proxy-extras==0.4.105" not in selected
    ):
        raise ValueError("selected proxy root changed")
    return selected


def uv_argv(run, requirement_path):
    return [
        str(UV),
        "--no-config",
        "--no-python-downloads",
        "pip",
        "compile",
        str(requirement_path),
        "--no-build",
        "--no-sources",
        "--no-header",
        "--no-annotate",
        "--python-version",
        ".".join(map(str, TARGET_PYTHON)),
        "--python-platform",
        "aarch64-manylinux_2_36",
        "--generate-hashes",
        "--keyring-provider",
        "disabled",
        "--default-index",
        "https://pypi.org/simple",
        "--cache-dir",
        str(run / "uv-cache"),
        "--exclude-newer",
        "2026-10-17T23:59:59Z",
        "--output-file",
        str(run / "candidate-runtime.lock"),
    ]


def validate_marker(marker):
    """Accept only inert PEP 508-style comparisons; never evaluate a marker."""
    names = {
        "implementation_name",
        "implementation_version",
        "os_name",
        "platform_machine",
        "platform_python_implementation",
        "platform_release",
        "platform_system",
        "platform_version",
        "python_full_version",
        "python_version",
        "sys_platform",
        "extra",
        "extras",
        "dependency_groups",
    }
    try:
        tree = ast.parse(marker, mode="eval")
    except SyntaxError as caught_error:
        raise ValueError("malformed resolver marker") from caught_error

    def operand(node):
        return (isinstance(node, ast.Name) and node.id in names) or (
            isinstance(node, ast.Constant) and isinstance(node.value, str)
        )

    def expression(node):
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            return len(node.values) >= 2 and all(expression(value) for value in node.values)
        if isinstance(node, ast.Compare):
            return (
                operand(node.left)
                and all(operand(x) for x in node.comparators)
                and all(
                    isinstance(
                        op, (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn)
                    )
                    for op in node.ops
                )
            )
        return False

    if not expression(tree.body):
        raise ValueError("unsupported resolver marker")


def parse_resolver_lock(raw):
    """Validate uv's hashed requirements as data; comments never grant a pin."""
    text = raw.decode("utf-8")
    if "\x00" in text:
        raise ValueError("NUL in resolver output")
    pins = {}
    current = None
    for number, line in enumerate(text.splitlines(), 1):
        active = line.strip()
        if not active or active.startswith("#"):
            continue
        active = re.split(r"\s+#", active, maxsplit=1)[0].rstrip()
        if active.endswith("\\"):
            active = active[:-1].rstrip()
        if active.startswith("--hash=sha256:"):
            digest = active[len("--hash=sha256:") :]
            if current is None or not SHA_RE.fullmatch(digest):
                raise ValueError("orphan or invalid hash at line " + str(number))
            pins[current]["hashes"].add(digest)
            continue
        match = re.fullmatch(
            r"([A-Za-z0-9][A-Za-z0-9._-]*)==([0-9][A-Za-z0-9.!+_-]*)(?:\s*;\s*(.+))?", active
        )
        if not match:
            raise ValueError("unsupported active resolver line " + str(number))
        name, version, marker = match.groups()
        if marker is not None:
            if (
                not re.fullmatch(r"""[A-Za-z0-9_ .'"<>=!()+-]+""", marker)
                or "://" in marker
                or "@" in marker
            ):
                raise ValueError("unsupported marker at line " + str(number))
            validate_marker(marker)
        normalized = re.sub(r"[-_.]+", "-", name).lower()
        if normalized in pins:
            raise ValueError("duplicate normalized resolver package: " + normalized)
        if current is not None and not pins[current]["hashes"]:
            raise ValueError("unhashed resolver pin: " + current)
        pins[normalized] = {"version": version, "marker": marker, "hashes": set()}
        current = normalized
    if not pins or any(not item["hashes"] for item in pins.values()):
        raise ValueError("resolver output has missing hashed exact pins")
    return pins


def execute_uv(argv, run, env):
    process = subprocess.Popen(
        argv,
        cwd=run,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    started = time.monotonic()
    reason = None
    while True:
        try:
            stdout, stderr = process.communicate(timeout=0.2)
            break
        except subprocess.TimeoutExpired:
            if time.monotonic() - started > RESOLVE_SECONDS:
                reason = "TOTAL_RESOLUTION_TIMEOUT"
            else:
                try:
                    if run_bytes(run) > MAX_AGGREGATE:
                        reason = "AGGREGATE_BYTE_LIMIT"
                except ValueError as exc:
                    reason = "UNSAFE_RUN_CONTENT: " + str(exc)
            if reason:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                stdout, stderr = process.communicate()
                break
    try:
        if run_bytes(run) > MAX_AGGREGATE:
            reason = reason or "AGGREGATE_BYTE_LIMIT"
    except ValueError as exc:
        reason = reason or "UNSAFE_RUN_CONTENT: " + str(exc)
    return {
        "exit_status": process.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "stop_reason": reason,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def resolve_online(run, runner=None):
    if UV.is_symlink() and sha(UV) != UV_SHA:
        raise ValueError("uv tool receipt changed")
    if sha(UV) != UV_SHA:
        raise ValueError("uv tool receipt changed")
    roots = static_requirements()
    requirement_path = run / "proxy-runtime.in"
    write_new(requirement_path, ("\n".join(roots) + "\n").encode())
    child_dir(run, "uv-cache")
    child_dir(run, "home")
    child_dir(run, "tmp")
    argv = uv_argv(run, requirement_path)
    env = {
        "PATH": "/usr/bin:/bin:/opt/homebrew/bin",
        "HOME": str(run / "home"),
        "TMPDIR": str(run / "tmp"),
        "UV_NO_PROGRESS": "1",
        "UV_PYTHON_DOWNLOADS": "never",
        "UV_HTTP_TIMEOUT": "10",
        "UV_HTTP_RETRIES": "0",
        "UV_KEYRING_PROVIDER": "disabled",
    }
    record = {
        "argv": argv,
        "cwd": str(run),
        "environment": env,
        "input_sha256": sha(requirement_path),
        "input_count": len(roots),
    }
    try:
        result = (runner or execute_uv)(argv, run, env)
    except Exception as exc:
        record.update(
            {
                "status": "PROCESS_INVOCATION_FAILED",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )
        receipt(run, "resolve", record)
        return record
    if isinstance(result, dict):
        record.update(result)
    output = run / "candidate-runtime.lock"
    try:
        if not isinstance(result, dict) or type(result.get("exit_status")) is not int:
            raise ValueError("resolver process result lacks integer exit status")
        if output.exists() or output.is_symlink():
            safe_component_path(output, run, require_file=True)
            if output.stat().st_size > MAX_TRANSFER:
                raise ValueError("resolver output exceeds 50 MB data bound")
            record.update({"output_sha256": sha(output), "output_bytes": output.stat().st_size})
        if result["exit_status"] == 0 and not result.get("stop_reason"):
            if run_bytes(run) > MAX_AGGREGATE:
                raise ValueError("resolver aggregate byte limit exceeded")
            safe_component_path(output, run, require_file=True)
            pins = parse_resolver_lock(output.read_bytes())
            record.update(
                {
                    "status": "METADATA_RESOLUTION_PROPOSAL_ONLY",
                    "pins": len(pins),
                    "hashed_exact_pins": len(pins),
                }
            )
        else:
            record["status"] = "UNRESOLVED_NO_BACKEND_EXECUTED"
    except Exception as exc:
        record.update(
            {
                "status": "OUTPUT_VALIDATION_FAILED",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )
    receipt(run, "resolve", record)
    return record


def validate_oci_query(image):
    if not isinstance(image, dict) or set(image) != {"role", "repository", "tag", "platform"}:
        raise ValueError("OCI query has missing or extra fields")
    role = image["role"]
    if not isinstance(role, str) or role not in OCI_QUERIES or image != OCI_QUERIES[role]:
        raise ValueError("OCI role/repository/tag/platform mismatch")
    return role


def oci_metadata(run, image, opener=None, transport_handler=None):
    record = {
        "role_supplied": repr(image.get("role"))[:128]
        if isinstance(image, dict)
        else repr(image)[:128]
    }
    try:
        role = validate_oci_query(image)  # Before directory creation or any request.
        record.update(
            {
                "role": role,
                "repository": image["repository"],
                "tag": image["tag"],
                "platform": image["platform"],
            }
        )
        oci = child_dir(run, "oci")
        outputs = {
            label: oci / (role + "-" + label + ".json") for label in ("index", "manifest", "config")
        }
        if any(path.exists() or path.is_symlink() for path in outputs.values()):
            raise ValueError("OCI output collision for " + role)
        record["stages"] = []

        def fetch_stage(stage, url, limit, headers=None, binding=None):
            trace = []
            stage_record = {"stage": stage, "request": url_evidence(url), "trace": trace}
            record["stages"].append(stage_record)
            try:
                if run_bytes(run) + limit > MAX_AGGREGATE:
                    raise ValueError("2 GiB aggregate reservation exceeded")
                body, meta = http_bytes(
                    url, limit, headers, opener, trace, binding, transport_handler
                )
                stage_record.update({"status": "HTTP_CHECKED", "response": meta})
                return body, meta, stage_record
            except Exception as exc:
                stage_record.update(
                    {
                        "status": "FAILED",
                        "error_type": type(exc).__name__,
                        "error": safe_http_error(exc),
                    }
                )
                raise

        def commit(label, body):
            path = outputs[label]
            write_new(path, body)
            safe_component_path(path, run, require_file=True)
            digest = hashlib.sha256(body).hexdigest()
            if sha(path) != digest:
                raise ValueError("OCI committed output drift: " + label)
            record.setdefault("checked_outputs", []).append(
                {
                    "stage": label,
                    "path": str(path.relative_to(run)),
                    "bytes": len(body),
                    "sha256": digest,
                }
            )

        token_url = (
            "https://auth.docker.io/token?service=registry.docker.io&scope=repository%3A"
            + urllib.parse.quote(image["repository"], safe="")
            + "%3Apull"
        )
        token_body, token_meta, _ = fetch_stage("token", token_url, 100_000)
        token = strict_json(token_body.decode())["token"]
        if not isinstance(token, str) or not token:
            raise ValueError("anonymous registry token absent")
        base = "https://registry-1.docker.io/v2/" + image["repository"] + "/manifests/"
        headers = {
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json",
        }
        index_body, index_meta, _ = fetch_stage("index", base + image["tag"], 5_000_000, headers)
        index_hash = hashlib.sha256(index_body).hexdigest()
        if index_meta["content_digest_header"] not in (None, "sha256:" + index_hash):
            raise ValueError("OCI index header/content digest mismatch")
        index = strict_json(index_body.decode())
        commit("index", index_body)
        choices = [
            m
            for m in index.get("manifests", [])
            if m.get("platform", {}).get("os") == "linux"
            and m.get("platform", {}).get("architecture") == "arm64"
            and m.get("platform", {}).get("variant", "v8") == "v8"
        ]
        if len(choices) != 1:
            raise ValueError("exactly one Linux ARM64/v8 manifest required")
        child_digest = choices[0]["digest"]
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", child_digest):
            raise ValueError("invalid OCI child digest")
        child_size = choices[0].get("size")
        if type(child_size) is not int or not 0 < child_size <= 5_000_000:
            raise ValueError("invalid OCI child descriptor size")
        child_body, child_meta, _ = fetch_stage(
            "manifest", base + child_digest, child_size, headers
        )
        if "sha256:" + hashlib.sha256(child_body).hexdigest() != child_digest:
            raise ValueError("OCI child body digest mismatch")
        if len(child_body) != child_size:
            raise ValueError("OCI child descriptor size mismatch")
        child = strict_json(child_body.decode())
        commit("manifest", child_body)
        config_digest = child["config"]["digest"]
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", config_digest):
            raise ValueError("invalid OCI config digest")
        config_size = child["config"].get("size")
        if type(config_size) is not int or not 0 < config_size <= 5_000_000:
            raise ValueError("invalid OCI config descriptor size")
        config_url = (
            "https://registry-1.docker.io/v2/" + image["repository"] + "/blobs/" + config_digest
        )
        binding = {
            "initial_url": config_url,
            "verified_url": config_url,
            "digest": config_digest,
            "size": config_size,
        }
        config_body, config_meta, _ = fetch_stage(
            "config", config_url, config_size, headers, binding
        )
        if "sha256:" + hashlib.sha256(config_body).hexdigest() != config_digest:
            raise ValueError("OCI config body digest mismatch")
        if len(config_body) != config_size:
            raise ValueError("OCI config descriptor size mismatch")
        config = strict_json(config_body.decode())
        if config.get("os") != "linux" or config.get("architecture") != "arm64":
            raise ValueError("OCI config platform mismatch")
        commit("config", config_body)
        record.update(
            {
                "index_digest": "sha256:" + index_hash,
                "selected_manifest_digest": child_digest,
                "config_digest": config_digest,
                "layers": [
                    {"digest": l["digest"], "size": l["size"]} for l in child.get("layers", [])
                ],
                "layers_acquired": False,
                "token_response_bytes": token_meta["bytes"],
                "index_response": index_meta,
                "manifest_response": child_meta,
                "config_response": config_meta,
                "status": "OCI_METADATA_ONLY_NO_LAYERS",
            }
        )
    except Exception as exc:
        if record.get("stages") and record["stages"][-1].get("status") == "HTTP_CHECKED":
            record["stages"][-1].update(
                {
                    "status": "FAILED_VALIDATION",
                    "error_type": type(exc).__name__,
                    "error": safe_http_error(exc),
                }
            )
        record.update(
            {"status": "FAILED", "error_type": type(exc).__name__, "error": safe_http_error(exc)}
        )
    receipt(run, "oci", record)
    return record


def lock_entries(raw, kind):
    lines = raw.decode("utf-8").splitlines()
    marker = "# COMPLETE: DKR-01 " + kind + " lock"
    if not lines or lines[0] != marker:
        raise ValueError("actual staged lock lacks exact COMPLETE marker")
    text = "\n".join(lines)
    if any(s in text for s in ("file://", "git+", "-e ", "../", "http://", "https://")):
        raise ValueError("lock contains local/remote source")
    entries = {}
    current = None
    for line in lines[1:]:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z0-9_.-]+)==([A-Za-z0-9_.!+-]+)(?:\s*\\)?$", s)
        if m:
            current = (m.group(1).lower().replace("_", "-"), m.group(2))
            if current in entries:
                raise ValueError("duplicate lock pin")
            entries[current] = set()
        elif s.startswith("--hash=sha256:") and current:
            h = s[len("--hash=sha256:") :].rstrip(" \\")
            if not SHA_RE.fullmatch(h):
                raise ValueError("invalid lock hash")
            entries[current].add(h)
        else:
            raise ValueError("unsupported lock syntax")
    if not entries or any(not hashes for hashes in entries.values()):
        raise ValueError("lock has no hashed exact entries")
    if kind == "build" and ("maturin", "1.15.0") not in entries:
        raise ValueError("Maturin build pin missing")
    if kind == "runtime" and any(name == "litellm" for name, _ in entries):
        raise ValueError("published LiteLLM runtime pin forbidden")
    return entries


def wheel_identity(filename):
    if not filename.endswith(".whl"):
        raise ValueError("non-wheel artifact")
    parts = filename[:-4].split("-")
    if len(parts) not in (5, 6) or not parts[0] or not parts[1]:
        raise ValueError("invalid wheel filename")
    python_tag, abi_tag, platform_tag = parts[-3:]
    py_tags = python_tag.split(".")
    abi_tags = abi_tag.split(".")
    platforms = platform_tag.split(".")
    if any(not x for x in py_tags + abi_tags + platforms):
        raise ValueError("empty compressed wheel tag")

    def platform_compatible(value):
        if value in ("any", "linux_aarch64"):
            return True
        if value == "manylinux2014_aarch64":
            return (2, 17) <= TARGET_GLIBC
        match = re.fullmatch(r"manylinux_([0-9]+)_([0-9]+)_aarch64", value)
        return bool(match) and (int(match.group(1)), int(match.group(2))) <= TARGET_GLIBC

    def interpreter_abi_compatible(py, abi):
        if abi == "none":
            return py in ("py3", "py312", "cp312")
        if abi == "cp312":
            return py == "cp312"
        if abi == "abi3":
            match = re.fullmatch(r"cp3([0-9]+)", py)
            return bool(match) and 6 <= int(match.group(1)) <= TARGET_PYTHON[1]
        return False

    if not any(
        platform_compatible(platform)
        and (platform != "any" or abi == "none")
        and interpreter_abi_compatible(py, abi)
        for py in py_tags
        for abi in abi_tags
        for platform in platforms
    ):
        raise ValueError("wheel tag incompatible with Python 3.12.15/Linux ARM64/glibc 2.36")
    return (parts[0].lower().replace("_", "-"), parts[1])


def stage_source(entry, dest, run, phase):
    source = Path(entry["source"])
    fixed = {
        "wheel": {"Dockerfile.gateway", ".dockerignore", "requirements-build.lock"},
        "runtime": {"Dockerfile.gateway", ".dockerignore", "requirements-runtime.lock"},
        "tools": {"Dockerfile.tools", ".dockerignore"},
    }
    harness = {
        "wheel": set(),
        "runtime": {
            "app_wrapper.py",
            "transport_guard.py",
            "intent_file.py",
            "fixtures.json",
            "route-config.yaml",
        },
        "tools": {"driver.py", "receiver.py", "fixtures.json"},
    }
    artifacts = {
        "wheel": ("artifacts/build-wheels/", "artifacts/cargo-vendor/"),
        "runtime": ("artifacts/runtime-wheels/", "artifacts/local-wheel/"),
        "tools": (),
    }
    if dest in fixed[phase]:
        expected = KIT / dest
    elif phase == "wheel" and dest == "artifacts/litellm-1.105.1.tar.gz":
        expected = SOURCE
    elif (
        dest.startswith("harness/")
        and dest.count("/") == 1
        and dest.split("/")[1] in harness[phase]
    ):
        expected = ROOT / "tools/gateway" / dest.split("/")[1]
    elif any(dest.startswith(prefix) for prefix in artifacts[phase]) or (
        phase == "wheel" and dest == "artifacts/cargo-config.toml"
    ):
        tail = dest.split("/")[2:] if "/" in dest else []
        if any(x in (".git", ".aws", ".ssh", ".env", "credentials", "id_rsa") for x in tail):
            raise ValueError("protected artifact path class")
        if dest.startswith(
            ("artifacts/build-wheels/", "artifacts/runtime-wheels/", "artifacts/local-wheel/")
        ) and (dest.count("/") != 2 or not dest.endswith(".whl")):
            raise ValueError("wheelhouse accepts one-level wheel files only")
        try:
            source.relative_to(run / "validated-artifacts")
        except ValueError as caught_error:
            raise ValueError("artifact source outside validated run store") from caught_error
        expected = run / "validated-artifacts" / dest
    else:
        raise ValueError("staging destination outside exact phase allowlist")
    if source != expected:
        raise ValueError("source identity mismatch for " + dest)
    anchor = run if source.is_relative_to(run) else ROOT
    safe_component_path(source, anchor, require_file=True)
    return source


def stage_phase(run, phase, data=None, copier=shutil.copyfileobj):
    if phase not in PHASES:
        raise ValueError("invalid phase")
    data = data or load_inputs()
    if data.get("ready_for_build") is not True:
        raise ValueError("real incomplete-input gate: staging refused")
    proof = data.get("closure_evidence", {})
    needed = ("python_runtime", "python_build", "oci", "cargo", "native")
    for category in needed:
        claim = proof.get(category)
        if (
            not isinstance(claim, dict)
            or claim.get("status") != "STATIC_DEPENDENCY_CHECKED"
            or not isinstance(claim.get("receipt_sha256"), str)
            or not SHA_RE.fullmatch(claim["receipt_sha256"])
        ):
            raise ValueError("closed graph/category receipt absent: " + category)
        source = run / "closure" / (category + ".json")
        safe_component_path(source, run, require_file=True)
        if sha(source) != claim["receipt_sha256"]:
            raise ValueError("closure receipt hash mismatch: " + category)
        content = read_json(source)
        if (
            content.get("category") != category
            or content.get("status") != "STATIC_DEPENDENCY_CHECKED"
            or not content.get("evidence")
        ):
            raise ValueError("closure receipt contents incomplete: " + category)
    images = data.get("oci_images", [])
    if len(images) != 3 or {x.get("role") for x in images} != {
        "python_builder",
        "python_runtime_and_tools",
        "rust_toolchain",
    }:
        raise ValueError("exact three OCI image roles absent")
    for image in images:
        role = image["role"]
        if image.get("platform") != "linux/arm64/v8" or image.get("layers_acquired") is not True:
            raise ValueError("Linux ARM64 image/layer custody incomplete: " + role)
        for label, field in (
            ("index", "index_digest"),
            ("manifest", "selected_manifest_digest"),
            ("config", "config_digest"),
        ):
            digest = image.get(field)
            if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                raise ValueError("OCI digest absent: " + role + "/" + label)
            path = run / "oci" / (role + "-" + label + ".json")
            safe_component_path(path, run, require_file=True)
            if "sha256:" + sha(path) != digest:
                raise ValueError("OCI metadata bytes mismatch: " + role + "/" + label)
        index = read_json(run / "oci" / (role + "-index.json"))
        choices = [
            x
            for x in index.get("manifests", [])
            if x.get("digest") == image["selected_manifest_digest"]
            and x.get("platform", {}).get("os") == "linux"
            and x.get("platform", {}).get("architecture") == "arm64"
            and x.get("platform", {}).get("variant", "v8") == "v8"
        ]
        config = read_json(run / "oci" / (role + "-config.json"))
        manifest = read_json(run / "oci" / (role + "-manifest.json"))
        if (
            len(choices) != 1
            or manifest.get("config", {}).get("digest") != image["config_digest"]
            or (config.get("os"), config.get("architecture")) != ("linux", "arm64")
        ):
            raise ValueError("OCI index/child/config relationship mismatch: " + role)
    entries = data.get("staging_files", {}).get(phase)
    if not isinstance(entries, list) or not entries:
        raise ValueError("phase staging manifest absent")
    required = {
        "wheel": {
            "Dockerfile.gateway",
            ".dockerignore",
            "requirements-build.lock",
            "artifacts/litellm-1.105.1.tar.gz",
            "artifacts/cargo-config.toml",
        },
        "runtime": {
            "Dockerfile.gateway",
            ".dockerignore",
            "requirements-runtime.lock",
            "harness/app_wrapper.py",
            "harness/transport_guard.py",
            "harness/intent_file.py",
            "harness/fixtures.json",
            "harness/route-config.yaml",
        },
        "tools": {
            "Dockerfile.tools",
            ".dockerignore",
            "harness/driver.py",
            "harness/receiver.py",
            "harness/fixtures.json",
        },
    }[phase]
    destinations = set()
    normalized = set()
    checked = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "source",
            "destination",
            "sha256",
            "bytes",
            "kind",
        }:
            raise ValueError("malformed/extra staging entry")
        dest = entry["destination"]
        if (
            not isinstance(dest, str)
            or not dest
            or dest.startswith("/")
            or "\\" in dest
            or any(x in ("", ".", "..") for x in dest.split("/"))
        ):
            raise ValueError("unsafe staging destination")
        norm = unicodedata.normalize("NFC", dest).casefold()
        if dest in destinations or norm in normalized:
            raise ValueError("duplicate/casefold/Unicode staging destination")
        destinations.add(dest)
        normalized.add(norm)
        if (
            not isinstance(entry["sha256"], str)
            or not SHA_RE.fullmatch(entry["sha256"])
            or type(entry["bytes"]) is not int
            or entry["bytes"] < 0
        ):
            raise ValueError("invalid staged receipt")
        source = stage_source(entry, dest, run, phase)
        actual = sha(source)
        if actual != entry["sha256"] or source.stat().st_size != entry["bytes"]:
            raise ValueError("precopy staged file hash/size mismatch")
        checked.append((source, dest, actual, entry["bytes"], entry["kind"]))
    for dest in destinations:
        parts = Path(dest).parts
        for i in range(1, len(parts)):
            if "/".join(parts[:i]) in destinations:
                raise ValueError("file/directory staging conflict")
    if not required.issubset(destinations):
        raise ValueError("phase required files missing")
    if phase == "wheel":
        if not any(x.startswith("artifacts/build-wheels/") for x in destinations) or not any(
            x.startswith("artifacts/cargo-vendor/") for x in destinations
        ):
            raise ValueError("build wheelhouse or Cargo vendor input absent")
    if phase == "runtime":
        if (
            not any(x.startswith("artifacts/runtime-wheels/") for x in destinations)
            or len([x for x in destinations if x.startswith("artifacts/local-wheel/")]) != 1
        ):
            raise ValueError("runtime wheelhouse or exactly one local wheel absent")
    lock_name = (
        "requirements-build.lock"
        if phase == "wheel"
        else "requirements-runtime.lock"
        if phase == "runtime"
        else None
    )
    if lock_name:
        source = next(item[0] for item in checked if item[1] == lock_name)
        lock = lock_entries(source.read_bytes(), "build" if phase == "wheel" else "runtime")
        prefix = "artifacts/build-wheels/" if phase == "wheel" else "artifacts/runtime-wheels/"
        wheels = [(s, d, h) for s, d, h, _, _ in checked if d.startswith(prefix)]
        matched = set()
        for _source, dest, digest in wheels:
            identity = wheel_identity(Path(dest).name)
            if identity not in lock or digest not in lock[identity]:
                raise ValueError("wheel not selected by actual lock")
            matched.add(identity)
        if matched != set(lock):
            raise ValueError("lock entry lacks matching wheel")
        if phase == "runtime":
            local = [x for x in checked if x[1].startswith("artifacts/local-wheel/")][0]
            if wheel_identity(Path(local[1]).name) != ("litellm", "1.105.1"):
                raise ValueError("wrong local LiteLLM wheel identity")
    target = run / ("context-" + phase)
    if target.exists() or target.is_symlink():
        raise ValueError("context collision")
    target.mkdir(mode=0o700)
    copied = []
    try:
        for source, dest, expected_hash, expected_bytes, kind in checked:
            output = target / dest
            output.parent.mkdir(parents=True, exist_ok=True)
            safe_component_path(output.parent, target)
            anchor = run if source.is_relative_to(run) else ROOT
            safe_component_path(source, anchor, require_file=True)
            input_fd = os.open(str(source), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            output_fd = os.open(
                str(output),
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            with os.fdopen(input_fd, "rb") as inp, os.fdopen(output_fd, "wb") as out:
                if not stat.S_ISREG(os.fstat(inp.fileno()).st_mode):
                    raise ValueError("source changed to non-regular file")
                copier(inp, out)
            actual_hash = sha(output)
            if actual_hash != expected_hash or output.stat().st_size != expected_bytes:
                raise ValueError("postcopy byte drift: " + dest)
            copied.append(
                {"path": dest, "sha256": actual_hash, "bytes": expected_bytes, "kind": kind}
            )
        actual = {str(p.relative_to(target)) for p in target.rglob("*") if p.is_file()}
        if actual != destinations:
            raise ValueError("undeclared or missing context entry")
        context_manifest = {
            "phase": phase,
            "status": "STAGED_DATA_ONLY_BUILD_NOT_AUTHORIZED",
            "owner_build_approval": False,
            "files": sorted(copied, key=lambda x: x["path"]),
            "manifest_self_excluded": True,
        }
        write_new(target / "CONTEXT-MANIFEST.json", json_bytes(context_manifest))
        verify = read_json(target / "CONTEXT-MANIFEST.json")
        if verify != context_manifest or {x["path"] for x in verify["files"]} != destinations:
            raise ValueError("context manifest verification failed")
        for item in verify["files"]:
            p = target / item["path"]
            if sha(p) != item["sha256"] or p.stat().st_size != item["bytes"]:
                raise ValueError("context census mismatch")
        result = {
            "status": "STAGED_DATA_ONLY_BUILD_NOT_AUTHORIZED",
            "phase": phase,
            "context": str(target),
            "manifest_sha256": sha(target / "CONTEXT-MANIFEST.json"),
            "files": len(copied),
        }
    except Exception as exc:
        receipt(
            run,
            "stage",
            {
                "status": "FAILED",
                "phase": phase,
                "context": str(target),
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        raise
    receipt(run, "stage", result)
    return result


def packet(run, handoff_parent=None):
    safe_component_path(run, RUN_PARENT)
    run_bytes(run)
    if handoff_parent is None:
        outdir = child_dir(run, "handoff")
    else:
        parent = Path(handoff_parent)
        if parent != OWNER_HANDOFF_PARENT:
            raise ValueError("handoff parent must match EZLLMROUTER_HANDOFF_ROOT")
        safe_component_path(parent, Path("/"))
        outdir = parent / ("ezllmrouter-wpb-inputs-" + run.name)
        outdir.mkdir(mode=0o700, exist_ok=False)
    allowed_files = [
        run / "proxy-runtime.in",
        run / "candidate-runtime.lock",
        run / "proposal-status.json",
    ]
    allowed_dirs = [run / "receipts", run / "downloads", run / "oci", run / "predecessor"]
    files = []
    for p in allowed_files:
        if p.exists() or p.is_symlink():
            safe_component_path(p, run, require_file=True)
            files.append(p)
    for d in allowed_dirs:
        if d.exists() or d.is_symlink():
            safe_component_path(d, run)
            for p in d.rglob("*"):
                if p.is_file() or p.is_symlink():
                    safe_component_path(p, run, require_file=True)
                    files.append(p)
    records = []
    for p in sorted(files):
        records.append(
            {"path": str(p.relative_to(run)), "bytes": p.stat().st_size, "sha256": sha(p)}
        )
    manifest = {
        "packet": "DKR-01-C02-owner-inputs",
        "run": run.name,
        "status": "DATA_ONLY_NOT_BUILD_AUTHORITY",
        "files": records,
        "manifest_self_excluded": True,
    }
    sidecar = outdir / "EVIDENCE-MANIFEST.json"
    write_new(sidecar, json_bytes(manifest))
    archive = outdir / "INPUTS-EVIDENCE.zip"
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(files):
            z.write(p, str(p.relative_to(run)))
        z.write(sidecar, "EVIDENCE-MANIFEST.json")
    with zipfile.ZipFile(archive) as z:
        if set(z.namelist()) != {x["path"] for x in records} | {"EVIDENCE-MANIFEST.json"}:
            raise ValueError("packet member census mismatch")
        if z.read("EVIDENCE-MANIFEST.json") != sidecar.read_bytes():
            raise ValueError("sidecar mismatch")
        for item in records:
            raw = z.read(item["path"])
            if len(raw) != item["bytes"] or hashlib.sha256(raw).hexdigest() != item["sha256"]:
                raise ValueError("packet payload mismatch")
    return {
        "zip": str(archive),
        "zip_sha256": sha(archive),
        "manifest": str(sidecar),
        "manifest_sha256": sha(sidecar),
        "payloads": len(records),
    }


def check():
    if Path.cwd().resolve() != ROOT:
        raise ValueError("run from independent EzLLMRouter root")
    data = load_inputs()
    selected = static_requirements()
    for name in (
        "compose.yaml",
        "Dockerfile.gateway",
        "Dockerfile.tools",
        ".dockerignore",
        "compose.env.example",
        "requirements-build.lock",
        "requirements-runtime.lock",
        "prepare.py",
        "README.md",
    ):
        safe_component_path(KIT / name, ROOT, require_file=True)
    state = (
        "INCOMPLETE"
        if data.get("ready_for_build") is False
        else "CANDIDATE_REQUIRES_STAGING_EVIDENCE"
    )
    return {
        "status": "STATIC_CHECK_PASS",
        "input_state": state,
        "selected_source_sha256": SOURCE_SHA,
        "static_proxy_roots": len(selected),
    }


def selftest():
    validate_url("https://files.pythonhosted.org/packages/example")
    for bad in (
        "http://pypi.org/x",
        "https://evil.example/x",
        "https://pypi.org:444/x",
        "https://u:p@pypi.org/x",
    ):
        try:
            validate_url(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("unsafe URL accepted")
    strict_json('{"a":1}')
    try:
        strict_json('{"a":1,"a":2}')
    except ValueError:
        pass
    else:
        raise AssertionError("duplicate JSON key accepted")
    return {"status": "SELFTEST_PASS", "static_proxy_roots": len(static_requirements())}


def owner(args, opener=None, runner=None):
    data = load_inputs()
    run = run_path(RUN_PARENT / args.new_run, create=True)
    events = []
    for item in data["acquisition_queue"]:
        events.append(fetch_entry(run, item, opener=opener))
    for image in data["oci_images"]:
        try:
            events.append(oci_metadata(run, image["metadata_query"], opener=opener))
        except Exception as exc:
            events.append(
                receipt(
                    run,
                    "oci",
                    {
                        "status": "UNRESOLVED",
                        "role": image["role"],
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
            )
    try:
        events.append(resolve_online(run, runner=runner))
    except Exception as exc:
        events.append(
            receipt(
                run,
                "resolve",
                {"status": "UNRESOLVED", "error_type": type(exc).__name__, "error": str(exc)},
            )
        )
    status = {
        "status": "INPUT_PROPOSAL_INCOMPLETE",
        "run": run.name,
        "selected_source": "LITELLM_1.105.1_SELECTED",
        "events": [
            {
                "kind": e.get("kind", e.get("role", "operation")),
                "status": e.get("status", "UNRESOLVED"),
            }
            for e in events
        ],
        "unresolved_edges": data["unresolved_edges"],
        "owner_build_approval": False,
        "runtime_proof": "NOT_ISSUED",
    }
    write_new(run / "proposal-status.json", json_bytes(status))
    handoff = packet(run, args.handoff_parent)
    return {
        "status": status["status"],
        "run": str(run),
        "handoff": handoff,
        "successful_events": sum(
            e.get("status")
            in (
                "DOWNLOADED_AND_HASH_MATCHED",
                "OFFICIAL_METADATA_LOCAL_HASH_RECORDED",
                "OCI_METADATA_ONLY_NO_LAYERS",
                "METADATA_RESOLUTION_PROPOSAL_ONLY",
            )
            for e in events
        ),
        "total_events": len(events),
    }


def verify_predecessor(
    archive_path=PREDECESSOR_ZIP,
    sidecar_path=PREDECESSOR_MANIFEST,
    archive_digest=PREDECESSOR_ZIP_SHA,
    sidecar_digest=PREDECESSOR_MANIFEST_SHA,
):
    """Verify the entire immutable packet before selecting its seven successes."""
    for path, expected in ((archive_path, archive_digest), (sidecar_path, sidecar_digest)):
        safe_component_path(path, Path("/"), require_file=True)
        if sha(path) != expected:
            raise ValueError("predecessor packet hash drift: " + path.name)
    sidecar = sidecar_path.read_bytes()
    manifest = strict_json(sidecar.decode())
    records = manifest.get("files")
    if manifest.get("run") != "run-20261017-40" or not isinstance(records, list):
        raise ValueError("predecessor manifest identity mismatch")
    expected_paths = set()
    for item in records:
        if not isinstance(item, dict) or set(item) != {"path", "bytes", "sha256"}:
            raise ValueError("malformed predecessor manifest entry")
        name = item["path"]
        if (
            not isinstance(name, str)
            or name.startswith("/")
            or "\\" in name
            or any(x in ("", ".", "..") for x in name.split("/"))
            or name in expected_paths
            or type(item["bytes"]) is not int
            or item["bytes"] < 0
            or not isinstance(item["sha256"], str)
            or not SHA_RE.fullmatch(item["sha256"])
        ):
            raise ValueError("unsafe predecessor manifest entry")
        expected_paths.add(name)
    with zipfile.ZipFile(archive_path) as archive:
        names, normalized = set(), set()
        for member in archive.infolist():
            name = member.filename
            mode = stat.S_IFMT(member.external_attr >> 16)
            folded = unicodedata.normalize("NFC", name).casefold()
            if (
                name.startswith("/")
                or "\\" in name
                or any(x in ("", ".", "..") for x in name.split("/"))
                or name in names
                or folded in normalized
                or member.is_dir()
                or mode not in (0, stat.S_IFREG)
                or member.flag_bits & 1
            ):
                raise ValueError("unsafe predecessor archive member")
            names.add(name)
            normalized.add(folded)
        if (
            names != expected_paths | {"EVIDENCE-MANIFEST.json"}
            or archive.read("EVIDENCE-MANIFEST.json") != sidecar
        ):
            raise ValueError("predecessor archive/manifest mismatch")
        payloads = {}
        for item in records:
            body = archive.read(item["path"])
            if len(body) != item["bytes"] or hashlib.sha256(body).hexdigest() != item["sha256"]:
                raise ValueError("predecessor payload drift: " + item["path"])
            payloads[item["path"]] = body
    queue = {item["id"]: item for item in load_inputs()["acquisition_queue"]}
    fetches = [
        (name, strict_json(body.decode()))
        for name, body in payloads.items()
        if name.startswith("receipts/fetch-") and name.endswith(".json")
    ]
    if len(fetches) != 7 or len(queue) != 7:
        raise ValueError("expected seven predecessor fetch receipts")
    selected = []
    seen = set()
    for name, record in fetches:
        item = queue.get(record.get("id"))
        if item is None or record["id"] in seen:
            raise ValueError("predecessor fetch identity mismatch")
        seen.add(record["id"])
        dest = "downloads/" + item["filename"]
        body = payloads.get(dest)
        expected_status = (
            "DOWNLOADED_AND_HASH_MATCHED"
            if item["expected_sha256"]
            else "OFFICIAL_METADATA_LOCAL_HASH_RECORDED"
        )
        if (
            body is None
            or record.get("status") != expected_status
            or record.get("sha256") != hashlib.sha256(body).hexdigest()
            or record.get("bytes") != len(body)
            or (item["expected_sha256"] is not None and record["sha256"] != item["expected_sha256"])
            or (item["expected_bytes"] is not None and len(body) != item["expected_bytes"])
        ):
            raise ValueError("predecessor success/receipt mismatch: " + record["id"])
        selected.append(
            {
                "id": record["id"],
                "path": dest,
                "receipt": name,
                "bytes": len(body),
                "sha256": record["sha256"],
            }
        )
    return {
        "manifest": manifest,
        "sidecar_bytes": sidecar,
        "payloads": payloads,
        "selected": sorted(selected, key=lambda x: x["id"]),
        "archive_sha256": archive_digest,
        "manifest_sha256": sidecar_digest,
    }


def recover(args, oci_runner=None, runner=None, predecessor=None):
    verified = predecessor or verify_predecessor()
    run = run_path(RUN_PARENT / args.new_run, create=True)
    downloads = child_dir(run, "downloads")
    predecessor_dir = child_dir(run, "predecessor")
    predecessor_receipts = child_dir(run, "predecessor") / "receipts"
    predecessor_receipts.mkdir(mode=0o700, exist_ok=False)
    for item in verified["selected"]:
        output = downloads / Path(item["path"]).name
        write_new(output, verified["payloads"][item["path"]])
        if sha(output) != item["sha256"] or output.stat().st_size != item["bytes"]:
            raise ValueError("copied predecessor input drift")
    for name, body in verified["payloads"].items():
        if name.startswith("receipts/"):
            write_new(predecessor_receipts / Path(name).name, body)
    write_new(predecessor_dir / "EVIDENCE-MANIFEST.json", verified["sidecar_bytes"])
    if sha(predecessor_dir / "EVIDENCE-MANIFEST.json") != verified["manifest_sha256"]:
        raise ValueError("copied predecessor manifest drift")
    parent_record = {
        "status": "SEVEN_INPUTS_REUSED_AS_DATA_NOT_NETWORK_ACQUISITION",
        "parent_run": "run-20261017-40",
        "parent_archive_sha256": verified["archive_sha256"],
        "parent_manifest_sha256": verified["manifest_sha256"],
        "reused_files": verified["selected"],
    }
    write_new(predecessor_dir / "REUSE-RECORD.json", json_bytes(parent_record))
    if run_bytes(run) > MAX_AGGREGATE:
        raise ValueError("aggregate byte limit after predecessor copy")
    events = []
    for image in load_inputs()["oci_images"]:
        events.append((oci_runner or oci_metadata)(run, image["metadata_query"]))
    events.append(resolve_online(run, runner=runner))
    status = {
        "status": "INPUT_PROPOSAL_INCOMPLETE",
        "run": run.name,
        "predecessor_reuse": parent_record,
        "events": [
            {
                "kind": e.get("kind", e.get("role", "operation")),
                "status": e.get("status", "UNRESOLVED"),
            }
            for e in events
        ],
        "unresolved_edges": load_inputs()["unresolved_edges"],
        "owner_build_approval": False,
        "runtime_proof": "NOT_ISSUED",
    }
    write_new(run / "proposal-status.json", json_bytes(status))
    handoff = packet(run, args.handoff_parent)
    return {
        "status": status["status"],
        "run": str(run),
        "handoff": handoff,
        "reused_inputs": len(verified["selected"]),
        "new_operations": len(events),
    }


def inputs02_packet():
    """Read the exact run-41 packet as data; do not use its original uv cache."""
    for path, expected in (
        (INPUTS02_PACKET, INPUTS02_PACKET_SHA),
        (INPUTS02_SIDECAR, INPUTS02_SIDECAR_SHA),
    ):
        safe_component_path(path, Path("/"), require_file=True)
        if sha(path) != expected:
            raise ValueError("run-41 packet receipt mismatch")
    sidecar = INPUTS02_SIDECAR.read_bytes()
    manifest = strict_json(sidecar.decode())
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
            or not SHA_RE.fullmatch(item["sha256"])
        ):
            raise ValueError("unsafe run-41 manifest entry")
        names.add(name)
    payloads = {}
    with zipfile.ZipFile(INPUTS02_PACKET) as archive:
        seen, folded = set(), set()
        for member in archive.infolist():
            name = member.filename
            normalized = unicodedata.normalize("NFC", name).casefold()
            mode = stat.S_IFMT(member.external_attr >> 16)
            if (
                name.startswith("/")
                or "\\" in name
                or any(x in ("", ".", "..") for x in name.split("/"))
                or name in seen
                or normalized in folded
                or member.is_dir()
                or mode not in (0, stat.S_IFREG)
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
            if len(body) != item["bytes"] or hashlib.sha256(body).hexdigest() != item["sha256"]:
                raise ValueError("run-41 payload mismatch: " + item["path"])
            if item["path"] == "candidate-runtime.lock" or item["path"].startswith(
                "downloads/pypi-"
            ):
                payloads[item["path"]] = body
    if hashlib.sha256(payloads["candidate-runtime.lock"]).hexdigest() != INPUTS02_LOCK_SHA:
        raise ValueError("frozen run-41 lock mismatch")
    pins = parse_resolver_lock(payloads["candidate-runtime.lock"])
    if len(pins) != 116:
        raise ValueError("frozen run-41 pin count mismatch")
    return pins, payloads


def inputs02_url(url, host):
    parsed = urllib.parse.urlsplit(url)
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


class Inputs02NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("INPUTS-02 redirect requires separate publisher review")


def inputs02_fetch(url, limit, expected_size=None, expected_sha=None):
    host = "pypi.org" if "/pypi/" in urllib.parse.urlsplit(url).path else "files.pythonhosted.org"
    inputs02_url(url, host)
    if type(limit) is not int or not 0 < limit <= INPUTS02_MAX_ARTIFACT:
        raise ValueError("invalid INPUTS-02 transfer limit")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), Inputs02NoRedirect())
    request = urllib.request.Request(url, headers={"User-Agent": "EzLLMRouter-INPUTS-02-data/1"})

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

    body = with_deadline(120, transfer)
    digest = hashlib.sha256(body).hexdigest()
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
    if not spec:
        return True
    target = TARGET_PYTHON
    for term in spec.split(","):
        match = re.fullmatch(r"\s*(>=|<=|==|!=|>|<)\s*([0-9]+(?:\.[0-9]+){0,2})\s*", term)
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
    if not isinstance(filename, str) or not filename.endswith(".whl") or "/" in filename:
        return None
    parts = filename[:-4].split("-")
    if (
        len(parts) not in (5, 6)
        or re.sub(r"[-_.]+", "-", parts[0]).lower() != name
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
        match = re.fullmatch(r"manylinux_2_([0-9]+)_aarch64", platform)
        if match and int(match.group(1)) <= 36:
            platform_score = max(platform_score, 100 + int(match.group(1)))
        if platform == "manylinux2014_aarch64":
            platform_score = max(platform_score, 117)
    return (platform_score, py_score, filename) if platform_score else None


def inputs02_select(metadata, name, version, hashes=None, source=False):
    if (
        re.sub(r"[-_.]+", "-", metadata.get("info", {}).get("name", "")).lower() != name
        or metadata.get("info", {}).get("version") != version
        or not isinstance(metadata.get("urls"), list)
    ):
        raise ValueError("exact PyPI metadata identity mismatch")
    if not inputs02_python_spec(metadata["info"].get("requires_python")):
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
            or not SHA_RE.fullmatch(digest)
            or type(size) is not int
            or not 0 < size <= INPUTS02_MAX_ARTIFACT
            or item.get("yanked") is not False
            or not isinstance(stamp, str)
        ):
            continue
        try:
            uploaded = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            inputs02_url(url, "files.pythonhosted.org")
            if not inputs02_python_spec(item.get("requires_python")):
                continue
        except (ValueError, TypeError):
            continue
        if uploaded > INPUTS02_CUTOFF:
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
                inputs02_wheel_score(filename, name, version)
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
    names, folded, types = set(), set(), {}
    for name, is_file, is_dir, is_link, is_special in members:
        clean = name[:-1] if is_dir and name.endswith("/") else name
        normalized = unicodedata.normalize("NFC", clean).casefold()
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
    with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as archive:
        members = archive.getmembers()
        inputs02_archive_members(
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
        if sum(m.size for m in members if m.isfile()) > INPUTS02_MAX_TOTAL:
            raise ValueError("sdist expansion budget exceeded")
        pkg_infos = [m for m in members if m.isfile() and m.name.endswith("/PKG-INFO")]
        if len(pkg_infos) != 1:
            raise ValueError("sdist PKG-INFO absent/ambiguous")
        parsed = email.parser.BytesParser().parsebytes(archive.extractfile(pkg_infos[0]).read())
        if (
            re.sub(r"[-_.]+", "-", parsed.get("Name", "")).lower() != name
            or parsed.get("Version") != version
        ):
            raise ValueError("sdist PKG-INFO identity mismatch")
        return {
            "members": len(members),
            "pkg_info_path": pkg_infos[0].name,
            "pkg_info_sha256": hashlib.sha256(archive.extractfile(pkg_infos[0]).read()).hexdigest(),
        }


def inputs02_check_wheel(body, name, version, selected):
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        members = archive.infolist()
        inputs02_archive_members(
            [
                (
                    m.filename,
                    not m.is_dir(),
                    m.is_dir(),
                    stat.S_IFMT(m.external_attr >> 16) == stat.S_IFLNK,
                    stat.S_IFMT(m.external_attr >> 16)
                    not in (0, stat.S_IFREG, stat.S_IFDIR, stat.S_IFLNK),
                )
                for m in members
            ]
        )
        if (
            any(m.flag_bits & 1 for m in members)
            or sum(m.file_size for m in members) > INPUTS02_MAX_TOTAL
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
        metadata = email.parser.BytesParser().parsebytes(archive.read(metadata_paths[0]))
        wheel = email.parser.BytesParser().parsebytes(archive.read(wheel_path))
        if (
            re.sub(r"[-_.]+", "-", metadata.get("Name", "")).lower() != name
            or metadata.get("Version") != version
            or not inputs02_python_spec(metadata.get("Requires-Python"))
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
        rows = list(csv.reader(io.StringIO(archive.read(record_path).decode("utf-8"))))
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
            expected = base64.urlsafe_b64decode(row[1][7:] + "=" * (-len(row[1][7:]) % 4))
            if len(raw) != int(row[2]) or hashlib.sha256(raw).digest() != expected:
                raise ValueError("wheel RECORD byte mismatch")
        if seen != files:
            raise ValueError("wheel RECORD file census mismatch")
        return {
            "members": len(members),
            "metadata_sha256": hashlib.sha256(archive.read(metadata_paths[0])).hexdigest(),
            "wheel_sha256": hashlib.sha256(archive.read(wheel_path)).hexdigest(),
            "record_sha256": hashlib.sha256(archive.read(record_path)).hexdigest(),
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
    metadata_dir = child_dir(outdir, "metadata")
    wheel_dir = child_dir(outdir, "wheels")
    source_dir = child_dir(outdir, "sources")
    records = {}
    transferred = 0
    stop = None
    metadata = {}

    def get(url, limit, expected_size=None, expected_sha=None):
        nonlocal transferred
        remaining = INPUTS02_MAX_TOTAL - transferred
        if expected_size is not None and expected_size > remaining:
            raise ValueError("INPUTS-02 2 GiB aggregate transfer budget exceeded")
        if remaining <= 0:
            raise ValueError("INPUTS-02 aggregate transfer budget exhausted")
        body, evidence = fetcher(url, min(limit, remaining), expected_size, expected_sha)
        if (
            len(body) > min(limit, remaining)
            or evidence.get("sha256") != hashlib.sha256(body).hexdigest()
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
                    "sha256": hashlib.sha256(body).hexdigest(),
                }
            else:
                url = (
                    "https://pypi.org/pypi/"
                    + urllib.parse.quote(name, safe="")
                    + "/"
                    + urllib.parse.quote(version, safe="")
                    + "/json"
                )
                body, evidence = get(url, INPUTS02_MAX_METADATA)
            parsed = strict_json(body.decode("utf-8"))
            if (
                re.sub(r"[-_.]+", "-", parsed.get("info", {}).get("name", "")).lower() != name
                or parsed.get("info", {}).get("version") != version
            ):
                raise ValueError("exact metadata name/version mismatch")
            output = metadata_dir / (key + ".json")
            write_new(output, body)
            record["metadata"] = {"path": str(output), **evidence}
            metadata[name] = parsed
            selected = inputs02_select(parsed, name, version, pin["hashes"])
            record["wheel_candidate"] = selected
            record["status"] = "EXACT_WHEEL_METADATA_SELECTED_BYTES_PENDING"
            if name in ("openai", "anyio"):
                source = inputs02_select(parsed, name, version, source=True)
                record["source_candidate"] = source
                source_body, source_evidence = get(
                    source["url"], INPUTS02_MAX_ARTIFACT, source["bytes"], source["sha256"]
                )
                source_inspection = inputs02_check_sdist(source_body, name, version)
                source_output = source_dir / source["filename"]
                write_new(source_output, source_body)
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
                    "error": safe_http_error(exc),
                }
            )
            stop = {
                "name": name,
                "phase": "metadata_or_source",
                "error_type": type(exc).__name__,
                "error": safe_http_error(exc),
            }
            break
    if stop is None:
        try:
            maturin = strict_json(packet_payloads["downloads/pypi-maturin-1.15.0.json"].decode())
            expected_maturin = maturin_receipt or {
                "filename": "maturin-1.15.0-py3-none-manylinux_2_17_aarch64.manylinux2014_aarch64.musllinux_1_1_aarch64.whl",
                "sha256": "0ebf9767892725083138e671c34482c660317a2f3d6a29fc0e0f34e9d8c99136",
                "bytes": 10_083_468,
            }
            selected = inputs02_select(maturin, "maturin", "1.15.0", {expected_maturin["sha256"]})
            if any(
                selected[key] != expected_maturin[key] for key in ("filename", "sha256", "bytes")
            ):
                raise ValueError("Maturin candidate receipt drift")
            write_new(
                metadata_dir / "maturin-1.15.0.json",
                packet_payloads["downloads/pypi-maturin-1.15.0.json"],
            )
            body, evidence = get(
                selected["url"], INPUTS02_MAX_ARTIFACT, selected["bytes"], selected["sha256"]
            )
            inspection = inputs02_check_wheel(body, "maturin", "1.15.0", selected)
            output = wheel_dir / selected["filename"]
            write_new(output, body)
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
                "error": safe_http_error(exc),
            }
            records["maturin_build"] = {"status": "BLOCKED", **stop}
    if stop is None:
        for name in sorted(pins):
            record = records[name]
            selected = record["wheel_candidate"]
            try:
                body, evidence = get(
                    selected["url"], INPUTS02_MAX_ARTIFACT, selected["bytes"], selected["sha256"]
                )
                inspection = inputs02_check_wheel(body, name, record["version"], selected)
                output = wheel_dir / selected["filename"]
                write_new(output, body)
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
                        "error": safe_http_error(exc),
                    }
                )
                stop = {
                    "name": name,
                    "phase": "runtime_wheel",
                    "error_type": type(exc).__name__,
                    "error": safe_http_error(exc),
                }
                break
    return {
        "status": "PARTIAL_INPUTS_NOT_BUILD_AUTHORITY"
        if stop
        else "ARTIFACT_DATA_ACQUIRED_NOT_BUILD_AUTHORITY",
        "parent_packet_sha256": INPUTS02_PACKET_SHA,
        "parent_lock_sha256": INPUTS02_LOCK_SHA,
        "target": "CPython 3.12.15 aarch64 manylinux glibc<=2.36",
        "cutoff": INPUTS02_CUTOFF.isoformat(),
        "new_transfer_bytes": transferred,
        "stop": stop,
        "records": records,
        "ready_for_build": False,
        "owner_build_approval": False,
    }


def inputs02_collect(args):
    pins, payloads = inputs02_packet()  # Every predecessor byte checked before output creation.
    if Path.cwd().resolve() != ROOT:
        raise ValueError("run INPUTS-02 from independent EzLLMRouter root")
    if args.handoff_parent != str(OWNER_HANDOFF_PARENT):
        raise ValueError("INPUTS-02 handoff parent must match EZLLMROUTER_HANDOFF_ROOT")
    INPUTS02_PARENT.mkdir(mode=0o700, exist_ok=True)
    safe_component_path(INPUTS02_PARENT, Path("/private/tmp"))
    if not RUN_RE.fullmatch(args.new_run):
        raise ValueError("unsafe INPUTS-02 run name")
    run = INPUTS02_PARENT / args.new_run
    handoff = OWNER_HANDOFF_PARENT / ("ezllmrouter-wpb-artifacts-" + args.new_run)
    if run.exists() or run.is_symlink() or handoff.exists() or handoff.is_symlink():
        raise ValueError("INPUTS-02 run/handoff collision")
    run.mkdir(mode=0o700, exist_ok=False)
    handoff.mkdir(mode=0o700, exist_ok=False)
    result = inputs02_collect_core(handoff, pins, payloads)
    files = []
    for path in sorted(handoff.rglob("*")):
        if path.is_file() or path.is_symlink():
            safe_component_path(path, handoff, require_file=True)
            files.append(
                {
                    "path": str(path.relative_to(handoff)),
                    "bytes": path.stat().st_size,
                    "sha256": sha(path),
                }
            )
    manifest = {
        "status": result["status"],
        "parent_packet_sha256": INPUTS02_PACKET_SHA,
        "parent_lock_sha256": INPUTS02_LOCK_SHA,
        "files": files,
        "result": result,
        "manifest_self_excluded": True,
    }
    write_new(handoff / "ACQUISITION-MANIFEST.json", json_bytes(manifest))
    write_new(
        run / "HANDOFF-RECEIPT.json",
        json_bytes(
            {
                "handoff": str(handoff),
                "manifest_sha256": sha(handoff / "ACQUISITION-MANIFEST.json"),
                "status": result["status"],
            }
        ),
    )
    return {
        "status": result["status"],
        "handoff": str(handoff),
        "manifest_sha256": sha(handoff / "ACQUISITION-MANIFEST.json"),
        "candidate_packages": len(pins),
        "new_transfer_bytes": result["new_transfer_bytes"],
        "stop": result["stop"],
        "ready_for_build": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action")
    sub.add_parser("check")
    sub.add_parser("selftest")
    p = sub.add_parser(
        "owner", help="fresh bounded official metadata + no-build uv + handoff packet"
    )
    p.add_argument("--new-run", required=True)
    p.add_argument("--handoff-parent", required=True)
    p = sub.add_parser(
        "recover",
        help="verify seven predecessor inputs; attempt only three OCI metadata queries and uv",
    )
    p.add_argument("--new-run", required=True)
    p.add_argument("--handoff-parent", required=True)
    p = sub.add_parser(
        "inputs02-collect", help="exact run-41 Python artifacts as inert data; no installation"
    )
    p.add_argument("--new-run", required=True)
    p.add_argument("--handoff-parent", required=True)
    p = sub.add_parser("fetch")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--id", required=True)
    p = sub.add_parser("resolve-online")
    p.add_argument("--run-dir", required=True)
    p = sub.add_parser("stage")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--phase", required=True, choices=PHASES)
    p = sub.add_parser("evidence")
    p.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    if not args.action:
        parser.print_help()
        return 0
    try:
        if args.action == "check":
            result = check()
        elif args.action == "selftest":
            result = selftest()
        elif args.action == "owner":
            result = owner(args)
        elif args.action == "recover":
            result = recover(args)
        elif args.action == "inputs02-collect":
            result = inputs02_collect(args)
        else:
            run = run_path(args.run_dir)
            if args.action == "fetch":
                matches = [x for x in load_inputs()["acquisition_queue"] if x["id"] == args.id]
                if len(matches) != 1:
                    raise ValueError("ID not in fixed acquisition queue")
                result = fetch_entry(run, matches[0])
            elif args.action == "resolve-online":
                result = resolve_online(run)
            elif args.action == "stage":
                result = stage_phase(run, args.phase)
            else:
                result = packet(run)
        print(json.dumps(result, sort_keys=True))
        return (
            2
            if result.get("status")
            in (
                "FAILED",
                "UNRESOLVED_NO_BACKEND_EXECUTED",
                "PROCESS_INVOCATION_FAILED",
                "OUTPUT_VALIDATION_FAILED",
                "INPUT_PROPOSAL_INCOMPLETE",
                "PARTIAL_INPUTS_NOT_BUILD_AUTHORITY",
            )
            else 0
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "operation": args.action,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
