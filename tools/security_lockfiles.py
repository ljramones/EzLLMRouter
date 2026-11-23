"""Validate declared dependency identities and artifact digests without acquiring inputs."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from pathlib import Path
import re
import tomllib
from typing import Any, Callable
from urllib.parse import urlsplit, unquote
import xml.etree.ElementTree as ET
from tools.gateway.os_inputs import (
    advisory_ecosystem,
    LOCK as OS_LOCK,
    INSTALLER as OS_INSTALLER,
    load_lock as load_os_lock,
)

INPUTS = (
    OS_LOCK,
    OS_INSTALLER,
    ".github/bootstrap-inputs.json",
    "uv.lock",
    "clients/python/uv.lock",
    "pyproject.toml",
    "deploy/local/inputs/requirements.runtime.lock",
    "deploy/local/inputs/gateway/requirements.gateway.lock",
    "tests/development_slice/requirements.lock",
    "tests/client_parity/wheelhouse.lock.json",
    "tools/gateway/docker/requirements-runtime.lock",
    "tools/gateway/docker/requirements-build.lock",
    "tests/playwright/package-lock.json",
    "clients/js/package-lock.json",
    "tests/playwright/package.json",
    "clients/js/package.json",
    "server/pyproject.toml",
    "clients/python/pyproject.toml",
    ".github/requirements-bootstrap.lock",
    "clients/go/go.mod",
    "clients/java/pom.xml",
    "clients/rust/Cargo.toml",
    "clients/rust/Cargo.lock",
    "clients/dotnet/EzLLMRouter.Client/EzLLMRouter.Client.csproj",
    "clients/dotnet/EzLLMRouter.Client.Tests/EzLLMRouter.Client.Tests.csproj",
)


def exact(value: str) -> str:
    if not re.fullmatch(r"v?[0-9][A-Za-z0-9.!+_-]*", value) or value.endswith("-SNAPSHOT"):
        raise ValueError("dependency requires an exact version")
    return value


def digest(value: str) -> str:
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise ValueError("invalid or missing artifact hash")
    return value


def https(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("dependency artifact requires an HTTPS origin without credentials")
    return value


def integrity(value: str) -> list[str]:
    values = value.split()
    if not values:
        raise ValueError("missing npm integrity")
    for item in values:
        kind, separator, encoded = item.partition("-")
        if not separator or kind not in {"sha256", "sha384", "sha512"}:
            raise ValueError("unsupported npm integrity")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as error:
            raise ValueError("invalid npm integrity") from error
        if len(raw) != {"sha256": 32, "sha384": 48, "sha512": 64}[kind]:
            raise ValueError("invalid npm integrity digest length")
    return values


def python_artifact(url: str, name: str, version: str) -> str:
    url = https(url)
    filename = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
    if filename.endswith(".whl"):
        parts = filename.split("-")
        if len(parts) < 5:
            raise ValueError("invalid wheel filename")
        actual_name, actual_version = parts[:2]
    else:
        ending = next((suffix for suffix in (".tar.gz", ".zip") if filename.endswith(suffix)), None)
        if ending is None or "-" not in filename[: -len(ending)]:
            raise ValueError("unparsed Python source archive")
        actual_name, actual_version = filename[: -len(ending)].rsplit("-", 1)

    def normalize(value: str) -> str:
        return re.sub(r"[-_.]+", "-", value).lower()

    if normalize(actual_name) != normalize(name) or actual_version != version:
        raise ValueError("Python archive identity differs from locked package")
    return url


def locked_inputs(root: Path, add: Callable[[str, str, str, str], None]) -> dict[str, Any]:
    hashes, artifacts, local, manifests, limits = {}, [], [], [], []

    def artifact(source: str, package: str, version: str, value: str, **fields: Any) -> None:
        artifacts.append(
            {"source": source, "package": package, "version": version, "digest": value, **fields}
        )

    for name in INPUTS:
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("missing/nonregular dependency input: " + name)
        raw = path.read_bytes()
        text = raw.decode()
        hashes[name] = hashlib.sha256(raw).hexdigest()
        if name == OS_LOCK:
            data = load_os_lock(root)
            for row in data["packages"]:
                add(advisory_ecosystem(data, row), row["source"], row["source_version"], name)
                artifact(
                    name,
                    row["package"],
                    row["version"],
                    digest("sha256:" + row["sha256"]),
                    url=row["url"],
                    architecture=row["architecture"],
                    filename=row["filename"],
                )
        elif name == OS_INSTALLER:
            pass  # Exact bytes are bound by the reviewed OS lock above.
        elif name.endswith("uv.lock"):
            for package in tomllib.loads(text)["package"]:
                package_name, version = package["name"], exact(package["version"])
                source = package.get("source", {})
                if "registry" not in source:
                    allowed = {
                        ("uv.lock", "cognitivedynamics-ezllmrouter-client"): (
                            {"editable": "clients/python"},
                            "clients/python/pyproject.toml",
                        ),
                        ("uv.lock", "cognitivedynamics-ezllmrouter-server"): (
                            {"editable": "server"},
                            "server/pyproject.toml",
                        ),
                        ("uv.lock", "ezllmrouter-development"): (
                            {"virtual": "."},
                            "pyproject.toml",
                        ),
                        ("clients/python/uv.lock", "cognitivedynamics-ezllmrouter-client"): (
                            {"editable": "."},
                            "clients/python/pyproject.toml",
                        ),
                    }.get((name, package_name))
                    if allowed is None or source != allowed[0]:
                        raise ValueError("unreviewed nonregistry Python source: " + name)
                    metadata = tomllib.loads((root / allowed[1]).read_text())["project"]
                    if (metadata["name"], metadata["version"]) != (package_name, version):
                        raise ValueError("local Python source identity mismatch")
                    local.append(
                        {
                            "source": name,
                            "name": package_name,
                            "version": version,
                            "origin": source,
                            "project": allowed[1],
                        }
                    )
                    continue
                if set(source) != {"registry"}:
                    raise ValueError("ambiguous Python package source")
                https(source["registry"])
                candidates = package.get("wheels", []) + (
                    [package["sdist"]] if "sdist" in package else []
                )
                if not candidates:
                    raise ValueError("registry package has no hashed artifacts")
                for candidate in candidates:
                    artifact(
                        name,
                        package_name,
                        version,
                        digest(candidate.get("hash", "")),
                        url=python_artifact(candidate["url"], package_name, version),
                    )
                add("PyPI", package_name, version, name)
        elif name.endswith("package-lock.json"):
            data = json.loads(raw)
            if data.get("lockfileVersion") not in (2, 3):
                raise ValueError("unsupported npm lock format")
            manifest = json.loads((path.parent / "package.json").read_text())
            locked_root = data["packages"].get("", {})
            for field in (
                "name",
                "version",
                "dependencies",
                "devDependencies",
                "optionalDependencies",
            ):
                if manifest.get(field, {}) != locked_root.get(field, {}):
                    raise ValueError("npm manifest and lock root differ")
            for field in ("dependencies", "devDependencies", "optionalDependencies"):
                for package, declared in manifest.get(field, {}).items():
                    if data["packages"].get("node_modules/" + package, {}).get("version") != exact(
                        declared
                    ):
                        raise ValueError("npm direct dependency differs from locked package")
            for location, package in data["packages"].items():
                if not location:
                    continue
                if "node_modules/" not in location or package.get("link"):
                    raise ValueError("unresolved npm package in lock")
                package_name = package.get("name") or location.rsplit("node_modules/", 1)[1]
                version = exact(package["version"])
                for value in integrity(package.get("integrity", "")):
                    artifact(name, package_name, version, value, url=https(package["resolved"]))
                add("npm", package_name, version, name)
        elif (
            name.endswith("requirements.lock")
            or name.endswith("requirements.runtime.lock")
            or name.endswith("requirements.gateway.lock")
            or name.endswith("requirements-bootstrap.lock")
            or name.startswith("tools/gateway/docker/requirements-")
        ):
            if "# INCOMPLETE: NOT INSTALLABLE." in text:
                limits.append(
                    {"source": name, "status": "incomplete, not installable; no candidate approval"}
                )
                continue
            for line in text.replace("\\\n", " ").splitlines():
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                match = re.fullmatch(
                    r"\s*([A-Za-z0-9._-]+)==([^\s]+)((?:\s+--hash=sha256:[0-9a-f]{64})+)\s*", line
                )
                if match is None:
                    raise ValueError("unparsed frozen lock record: " + name)
                version = exact(match[2])
                add("PyPI", match[1], version, name)
                for value in re.findall(r"--hash=(\S+)", match[3]):
                    artifact(name, match[1], version, digest(value))
        elif name.endswith("wheelhouse.lock.json"):
            data = json.loads(raw)
            if len(data["wheels"]) != data["wheel_count"]:
                raise ValueError("wheel inventory count mismatch")
            for wheel in data["wheels"]:
                parts = wheel["filename"].split("-")
                if len(parts) < 5 or not wheel["filename"].endswith(".whl"):
                    raise ValueError("unparsed wheel identity")
                version = exact(parts[1])
                add("PyPI", parts[0], version, name)
                artifact(
                    name,
                    parts[0],
                    version,
                    digest("sha256:" + wheel["sha256"]),
                    filename=wheel["filename"],
                )
        elif name.endswith("Cargo.lock"):
            from tools.security_rust import rust_graph

            for package in rust_graph(
                tomllib.loads(text), tomllib.loads((path.parent / "Cargo.toml").read_text())
            ):
                add("crates.io", package["name"], package["version"], name)
                artifact(
                    name,
                    package["name"],
                    package["version"],
                    digest("sha256:" + package["checksum"]),
                )
            manifests.append(
                {
                    "source": name,
                    "ecosystem": "crates.io",
                    "scope": "resolved registry closure with published archive checksums",
                }
            )
        elif name.endswith("bootstrap-inputs.json") or name.endswith("package.json"):
            pass  # Validated by security_bootstrap before producing the inventory.
        elif name.endswith("pyproject.toml"):
            data = tomllib.loads(text)
            for requirement in data.get("build-system", {}).get("requires", []):
                match = re.fullmatch(r"([A-Za-z0-9._-]+)==([^\s]+)", requirement)
                if match is None:
                    raise ValueError("unresolved build backend pin")
                add("PyPI", match[1], exact(match[2]), name)
        else:
            details = native_input(name, text, raw, add)
            local.extend(details["local_sources"])
            manifests.extend(details["native_manifests"])
            limits.extend(details["limits"])
    return {
        "source_sha256": hashes,
        "artifacts": artifacts,
        "local_sources": local,
        "native_manifests": manifests,
        "limits": limits,
        "artifact_verification": "Digest syntax and source identities validated, including the resolved Rust lock; unavailable archives are not byte-verified and installed images require a target inventory.",
    }


def native_input(
    name: str, text: str, raw: bytes, add: Callable[[str, str, str, str], None]
) -> dict[str, Any]:
    local: list[dict[str, Any]] = []
    manifests: list[dict[str, Any]] = []
    limits: list[dict[str, Any]] = []
    if name.endswith("Cargo.toml"):
        data = tomllib.loads(text)
        for group in ("dependencies", "dev-dependencies", "build-dependencies"):
            for package, declaration in data.get(group, {}).items():
                item = {"version": declaration} if isinstance(declaration, str) else declaration
                if set(item) - {
                    "version",
                    "features",
                    "default-features",
                    "optional",
                    "package",
                } or not item.get("version", "").startswith("="):
                    raise ValueError("unresolved/nonregistry Rust dependency")
                add("crates.io", item.get("package", package), exact(item["version"][1:]), name)
        if data.get("target") or data.get("workspace") or data.get("patch") or data.get("replace"):
            raise ValueError("unreviewed Rust workspace/target/override dependencies")
        manifests.append(
            {
                "source": name,
                "ecosystem": "crates.io",
                "scope": "direct runtime and development declarations",
            }
        )
    elif name.endswith("go.mod"):
        module = ""
        block = False
        for line in text.splitlines():
            line = line.split("//", 1)[0].strip()
            if not line:
                continue
            if line == "require (":
                block = True
                continue
            if line == ")" and block:
                block = False
                continue
            if line.startswith("module "):
                module = line[7:]
                continue
            if line.startswith(("go ", "toolchain ")):
                continue
            fields = (line[8:] if line.startswith("require ") else line if block else "").split()
            if len(fields) != 2:
                raise ValueError("unreviewed Go dependency/replace directive")
            add("Go", fields[0], exact(fields[1]), name)
        if not module or block:
            raise ValueError("incomplete Go manifest")
        manifests.append(
            {
                "source": name,
                "ecosystem": "Go",
                "module": module,
                "scope": "direct declarations; no external dependencies currently",
            }
        )
    elif name.endswith("pom.xml"):
        if "<!DOCTYPE" in text or "<!ENTITY" in text:
            raise ValueError("external XML declarations forbidden")
        tree = ET.fromstring(raw)
        ns = {"m": "http://maven.apache.org/POM/4.0.0"}
        for tag in ("dependency", "plugin"):
            for node in tree.findall(".//m:" + tag, ns):
                maven_group = node.findtext("m:groupId", namespaces=ns)
                maven_package = node.findtext("m:artifactId", namespaces=ns)
                maven_version = node.findtext("m:version", namespaces=ns)
                if not maven_group or not maven_package or not maven_version:
                    raise ValueError("unresolved Maven dependency/plugin")
                add("Maven", maven_group + ":" + maven_package, exact(maven_version), name)
        if tree.findall(".//m:parent", ns) or tree.findall(".//m:profiles", ns):
            raise ValueError("unreviewed Maven inherited/profile dependencies")
        manifests.append(
            {"source": name, "ecosystem": "Maven", "scope": "direct runtime/build declarations"}
        )
    elif name.endswith(".csproj"):
        if "<!DOCTYPE" in text or "<!ENTITY" in text:
            raise ValueError("external XML declarations forbidden")
        tree = ET.fromstring(raw)
        for node in tree.iter("PackageReference"):
            nuget_package = node.get("Include")
            nuget_version = node.get("Version")
            if not nuget_package or not nuget_version:
                raise ValueError("unresolved NuGet reference")
            if nuget_package == "CognitiveDynamics.EzLLMRouter.Client":
                if nuget_version != "0.3.0":
                    raise ValueError("unreviewed own-package consumer version")
                local.append(
                    {
                        "source": name,
                        "name": nuget_package,
                        "version": nuget_version,
                        "origin": "fresh local consumer package",
                    }
                )
            else:
                add("NuGet", nuget_package, exact(nuget_version), name)
        if any(node.tag in {"Import", "PackageVersion"} for node in tree.iter()):
            raise ValueError("unreviewed external/central NuGet manifest")
        manifests.append(
            {
                "source": name,
                "ecosystem": "NuGet",
                "scope": "direct declarations; no external packages currently",
            }
        )
    else:
        raise ValueError("unsupported dependency input: " + name)
    return {"local_sources": local, "native_manifests": manifests, "limits": limits}
