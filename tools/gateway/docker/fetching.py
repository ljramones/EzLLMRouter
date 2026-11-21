"""prepare fetching domain; entry points remain on the facade."""

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


def validate_url(url):
    from tools.gateway.docker import prepare as _api

    p = _api.urllib.parse.urlsplit(url)
    if (
        p.scheme != "https"
        or p.hostname not in _api.HOSTS
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
    from tools.gateway.docker import prepare as _api

    parsed = _api.urllib.parse.urlsplit(url)
    return {
        "origin": parsed.scheme + "://" + (parsed.hostname or ""),
        "path": parsed.path,
        "query_keys": sorted(
            {key for key, _ in _api.urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)}
        ),
        "url_sha256": _api.hashlib.sha256(url.encode()).hexdigest(),
    }


def safe_http_error(exc):
    from tools.gateway.docker import prepare as _api

    if isinstance(exc, _api.urllib.error.HTTPError):
        return "HTTP status " + str(exc.code)
    if isinstance(exc, _api.urllib.error.URLError):
        return "URL transport error (" + type(exc.reason).__name__ + ")"
    return str(exc)


def with_deadline(seconds, action):
    from tools.gateway.docker import prepare as _api

    previous_handler = _api.signal.getsignal(_api.signal.SIGALRM)
    previous_timer = _api.signal.getitimer(_api.signal.ITIMER_REAL)

    def alarm(_signum, _frame):
        raise _api.DeadlineExceeded("total transfer deadline exceeded")

    _api.signal.signal(_api.signal.SIGALRM, alarm)
    _api.signal.setitimer(_api.signal.ITIMER_REAL, seconds)
    try:
        return action()
    finally:
        _api.signal.setitimer(_api.signal.ITIMER_REAL, 0)
        _api.signal.signal(_api.signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            _api.signal.setitimer(_api.signal.ITIMER_REAL, *previous_timer)


def http_bytes(
    url, limit, headers=None, opener=None, trace=None, config_binding=None, transport_handler=None
):
    from tools.gateway.docker import prepare as _api

    _api.validate_url(url)
    if config_binding is not None and (
        config_binding.get("initial_url") != url or config_binding.get("verified_url") != url
    ):
        raise ValueError("OCI config binding/initial URL mismatch")
    if not isinstance(limit, int) or not 0 < limit <= _api.MAX_TRANSFER:
        raise ValueError("transfer bound invalid")
    trace = trace if trace is not None else []
    trace.append({"event": "request", "url": _api.url_evidence(url)})
    redirect = _api.CheckedRedirect(trace, config_binding)
    opener = opener or _api.urllib.request.build_opener(
        _api.urllib.request.ProxyHandler({}),
        redirect,
        *([transport_handler] if transport_handler else []),
    )
    request = _api.urllib.request.Request(
        url, headers={"User-Agent": "EzLLMRouter-DKR-01-c02-data/1", **(headers or {})}
    )
    started = _api.time.monotonic()

    def transfer():
        with opener.open(request, timeout=10) as response:
            status = getattr(response, "status", None)
            if status != 200:
                raise ValueError("final HTTP status is not 200: " + str(status))
            final_url = response.geturl()
            if final_url != url:
                if not redirect.chain:
                    raise ValueError("unobserved final URL change")
                if redirect.chain[-1]["to"] != _api.url_evidence(final_url):
                    raise ValueError("final URL not last checked redirect")
            elif not redirect.chain:
                _api.validate_url(final_url)
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
                "final_url": _api.url_evidence(final_url),
                "declared_length": length,
                "content_digest_header": response.headers.get("Docker-Content-Digest"),
                "redirect_chain": redirect.chain,
            }

    body, meta = _api.with_deadline(_api.TRANSFER_SECONDS, transfer)
    meta.update(
        {
            "bytes": len(body),
            "sha256": _api.hashlib.sha256(body).hexdigest(),
            "elapsed_seconds": round(_api.time.monotonic() - started, 3),
        }
    )
    return body, meta


def fetch_entry(run, item, opener=None):
    from tools.gateway.docker import prepare as _api

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
    if not _api.NAME_RE.fullmatch(item["id"]) or not _api.NAME_RE.fullmatch(item["filename"]):
        raise ValueError("unsafe acquisition ID/filename")
    _api.validate_url(item["url"])
    maximum = item["max_bytes"]
    if not isinstance(maximum, int) or not 0 < maximum <= _api.MAX_TRANSFER:
        raise ValueError("invalid per-transfer bound")
    if item["expected_sha256"] is not None and not _api.SHA_RE.fullmatch(item["expected_sha256"]):
        raise ValueError("invalid expected SHA-256")
    if item["expected_bytes"] is not None and (
        type(item["expected_bytes"]) is not int
        or item["expected_bytes"] < 0
        or item["expected_bytes"] > maximum
    ):
        raise ValueError("invalid expected length")
    downloads = _api.child_dir(run, "downloads")
    partial = _api.child_dir(run, "partial")
    _api.child_dir(run, "receipts")
    destination = downloads / item["filename"]
    if destination.exists() or destination.is_symlink():
        raise ValueError("download collision")
    if _api.run_bytes(run) + maximum > _api.MAX_AGGREGATE:
        raise ValueError("2 GiB aggregate reservation exceeded")
    record = {
        "id": item["id"],
        "kind": item["kind"],
        "original_url": item["url"],
        "expected_sha256": item["expected_sha256"],
        "expected_bytes": item["expected_bytes"],
        "max_bytes": maximum,
        "total_deadline_seconds": _api.TRANSFER_SECONDS,
    }
    part = partial / (item["id"] + "-" + _api.uuid.uuid4().hex + ".part")
    try:
        body, meta = _api.http_bytes(item["url"], maximum, opener=opener)
        if item["kind"] == "official-pypi-version-metadata":
            metadata = _api.strict_json(body.decode("utf-8"))
            parts = _api.validate_url(item["url"]).path.split("/")
            expected_name, expected_version = parts[2], parts[3]
            info = metadata.get("info", {})
            normalize = lambda x: _api.re.sub(r"[-_.]+", "-", x).lower()
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
        _api.write_new(part, body)
        _api.os.link(part, destination, follow_symlinks=False)
        part.unlink()
        if _api.sha(destination) != meta["sha256"] or destination.stat().st_size != meta["bytes"]:
            raise ValueError("committed output drift")
        record["committed_path"] = str(destination)
        record["status"] = (
            "DOWNLOADED_AND_HASH_MATCHED"
            if item["expected_sha256"]
            else "OFFICIAL_METADATA_LOCAL_HASH_RECORDED"
        )
    except Exception as exc:
        record.update({"status": "FAILED", "error_type": type(exc).__name__, "error": str(exc)})
    _api.receipt(run, "fetch", record)
    return record
