"""prepare staging domain; entry points remain on the facade."""

from __future__ import annotations

import shutil


def stage_phase(run, phase, data=None, copier=shutil.copyfileobj):
    from tools.gateway.docker import prepare as _api

    if phase not in _api.PHASES:
        raise ValueError("invalid phase")
    data = data or _api.load_inputs()
    if data.get("ready_for_build") is not True:
        raise ValueError("real incomplete-input gate: staging refused")
    _validate_staging_custody(_api, data, run)
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
        norm = _api.unicodedata.normalize("NFC", dest).casefold()
        if dest in destinations or norm in normalized:
            raise ValueError("duplicate/casefold/Unicode staging destination")
        destinations.add(dest)
        normalized.add(norm)
        if (
            not isinstance(entry["sha256"], str)
            or not _api.SHA_RE.fullmatch(entry["sha256"])
            or type(entry["bytes"]) is not int
            or entry["bytes"] < 0
        ):
            raise ValueError("invalid staged receipt")
        source = _api.stage_source(entry, dest, run, phase)
        actual = _api.sha(source)
        if actual != entry["sha256"] or source.stat().st_size != entry["bytes"]:
            raise ValueError("precopy staged file hash/size mismatch")
        checked.append((source, dest, actual, entry["bytes"], entry["kind"]))
    for dest in destinations:
        parts = _api.Path(dest).parts
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
        lock = _api.lock_entries(source.read_bytes(), "build" if phase == "wheel" else "runtime")
        prefix = "artifacts/build-wheels/" if phase == "wheel" else "artifacts/runtime-wheels/"
        wheels = [(s, d, h) for s, d, h, _, _ in checked if d.startswith(prefix)]
        matched = set()
        for _source, dest, digest in wheels:
            identity = _api.wheel_identity(_api.Path(dest).name)
            if identity not in lock or digest not in lock[identity]:
                raise ValueError("wheel not selected by actual lock")
            matched.add(identity)
        if matched != set(lock):
            raise ValueError("lock entry lacks matching wheel")
        if phase == "runtime":
            local = [x for x in checked if x[1].startswith("artifacts/local-wheel/")][0]
            if _api.wheel_identity(_api.Path(local[1]).name) != ("litellm", "1.105.1"):
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
            _api.safe_component_path(output.parent, target)
            anchor = run if source.is_relative_to(run) else _api.ROOT
            _api.safe_component_path(source, anchor, require_file=True)
            input_fd = _api.os.open(
                str(source), _api.os.O_RDONLY | getattr(_api.os, "O_NOFOLLOW", 0)
            )
            output_fd = _api.os.open(
                str(output),
                _api.os.O_WRONLY
                | _api.os.O_CREAT
                | _api.os.O_EXCL
                | getattr(_api.os, "O_NOFOLLOW", 0),
                0o600,
            )
            with _api.os.fdopen(input_fd, "rb") as inp, _api.os.fdopen(output_fd, "wb") as out:
                if not _api.stat.S_ISREG(_api.os.fstat(inp.fileno()).st_mode):
                    raise ValueError("source changed to non-regular file")
                copier(inp, out)
            actual_hash = _api.sha(output)
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
        _api.write_new(target / "CONTEXT-MANIFEST.json", _api.json_bytes(context_manifest))
        verify = _api.read_json(target / "CONTEXT-MANIFEST.json")
        if verify != context_manifest or {x["path"] for x in verify["files"]} != destinations:
            raise ValueError("context manifest verification failed")
        for item in verify["files"]:
            p = target / item["path"]
            if _api.sha(p) != item["sha256"] or p.stat().st_size != item["bytes"]:
                raise ValueError("context census mismatch")
        result = {
            "status": "STAGED_DATA_ONLY_BUILD_NOT_AUTHORIZED",
            "phase": phase,
            "context": str(target),
            "manifest_sha256": _api.sha(target / "CONTEXT-MANIFEST.json"),
            "files": len(copied),
        }
    except Exception as exc:
        _api.receipt(
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
    _api.receipt(run, "stage", result)
    return result


def _validate_staging_custody(_api, data, run):
    proof = data.get("closure_evidence", {})
    needed = ("python_runtime", "python_build", "oci", "cargo", "native")
    for category in needed:
        claim = proof.get(category)
        if (
            not isinstance(claim, dict)
            or claim.get("status") != "STATIC_DEPENDENCY_CHECKED"
            or not isinstance(claim.get("receipt_sha256"), str)
            or not _api.SHA_RE.fullmatch(claim["receipt_sha256"])
        ):
            raise ValueError("closed graph/category receipt absent: " + category)
        source = run / "closure" / (category + ".json")
        _api.safe_component_path(source, run, require_file=True)
        if _api.sha(source) != claim["receipt_sha256"]:
            raise ValueError("closure receipt hash mismatch: " + category)
        content = _api.read_json(source)
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
            if not isinstance(digest, str) or not _api.re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                raise ValueError("OCI digest absent: " + role + "/" + label)
            path = run / "oci" / (role + "-" + label + ".json")
            _api.safe_component_path(path, run, require_file=True)
            if "sha256:" + _api.sha(path) != digest:
                raise ValueError("OCI metadata bytes mismatch: " + role + "/" + label)
        index = _api.read_json(run / "oci" / (role + "-index.json"))
        choices = [
            x
            for x in index.get("manifests", [])
            if x.get("digest") == image["selected_manifest_digest"]
            and x.get("platform", {}).get("os") == "linux"
            and x.get("platform", {}).get("architecture") == "arm64"
            and x.get("platform", {}).get("variant", "v8") == "v8"
        ]
        config = _api.read_json(run / "oci" / (role + "-config.json"))
        manifest = _api.read_json(run / "oci" / (role + "-manifest.json"))
        if (
            len(choices) != 1
            or manifest.get("config", {}).get("digest") != image["config_digest"]
            or (config.get("os"), config.get("architecture")) != ("linux", "arm64")
        ):
            raise ValueError("OCI index/child/config relationship mismatch: " + role)
