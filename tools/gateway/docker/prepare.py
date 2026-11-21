#!/usr/bin/env python3
"""Bounded DKR-01 data preparation. Never builds, installs, or starts services."""

import argparse as argparse
import ast as ast
import base64 as base64
import csv as csv
import datetime as dt
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
import urllib.error
import urllib.parse
import urllib.request
import uuid as uuid
import zipfile as zipfile

import email.parser

email = email
urllib = urllib

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


# Preserve direct script execution and one facade identity for extracted staging.
if not __package__:
    sys.path.insert(0, str(ROOT))
if __name__ == "__main__":
    sys.modules.setdefault("tools.gateway.docker.prepare", sys.modules[__name__])


from tools.gateway.docker import staging as _staging


from tools.gateway.docker import fetching as _fetching
from tools.gateway.docker import resolution as _resolution
from tools.gateway.docker import input_collection as _input_collection


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


validate_url = _fetching.validate_url


url_evidence = _fetching.url_evidence


safe_http_error = _fetching.safe_http_error


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


with_deadline = _fetching.with_deadline


http_bytes = _fetching.http_bytes


fetch_entry = _fetching.fetch_entry


static_requirements = _resolution.static_requirements


uv_argv = _resolution.uv_argv


validate_marker = _resolution.validate_marker


parse_resolver_lock = _resolution.parse_resolver_lock


execute_uv = _resolution.execute_uv


resolve_online = _resolution.resolve_online


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


stage_phase = _staging.stage_phase


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


inputs02_packet = _input_collection.inputs02_packet


inputs02_url = _input_collection.inputs02_url


class Inputs02NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("INPUTS-02 redirect requires separate publisher review")


inputs02_fetch = _input_collection.inputs02_fetch


inputs02_python_spec = _input_collection.inputs02_python_spec


inputs02_wheel_score = _input_collection.inputs02_wheel_score


inputs02_select = _input_collection.inputs02_select


inputs02_archive_members = _input_collection.inputs02_archive_members


inputs02_check_sdist = _input_collection.inputs02_check_sdist


inputs02_check_wheel = _input_collection.inputs02_check_wheel


inputs02_collect_core = _input_collection.inputs02_collect_core


inputs02_collect = _input_collection.inputs02_collect


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
