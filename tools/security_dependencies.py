"""Validate declared dependency inputs offline; query OSV only with --audit."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import re
import shlex
import sys
from typing import Any, Callable
from urllib.parse import quote
from urllib.request import Request, HTTPRedirectHandler, ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT))
from tools.security_lockfiles import INPUTS as INPUTS, locked_inputs
from tools.security_bootstrap import errors as bootstrap_errors
from tools.security_cvss import classification

API = "https://api.osv.dev/v1/"
MAX_RESPONSE = 10 * 1024 * 1024


def forbidden_release(version: str) -> bool:
    # Compare the PEP 440 numeric release component, including abbreviated and
    # zero-padded spellings. Local/pre/post suffixes cannot bypass the banned
    # release family. This is a deny rule, not an approval of other versions.
    match = re.match(r"(?i)^(?:[0-9]+!)?v?([0-9]+(?:\.[0-9]+)*)", version.strip())
    if match is None:
        return False
    release = [int(part) for part in match[1].split(".")]
    while release and release[-1] == 0:
        release.pop()
    return release == [1, 107]


def deployment_images(root: Path) -> dict[str, str]:
    paths = set((root / "deploy").rglob("Dockerfile*"))
    paths.update(
        path
        for pattern in ("*compose*.yml", "*compose*.yaml")
        for path in (root / "deploy").rglob(pattern)
    )
    paths.update(
        path
        for pattern in ("*.yml", "*.yaml")
        for path in (root / ".github/workflows").glob(pattern)
    )
    hashes = {}
    fields = [
        re.compile(
            r"""(?<!\w)["']?""" + key + r"""["']?\s*:\s*(?:"([^"]*)"|'([^']*)'|([^\s,}]+))"""
        )
        for key in ("image", "container")
    ]

    def check(image: str, source: str) -> None:
        if image.startswith((">", "|", "&", "*")):
            raise ValueError("unresolved image declaration: " + source)
        base = image.split("@", 1)[0].rsplit("/", 1)[-1]
        if "litellm" not in base.lower():
            return
        tag = base.split(":", 1)[1] if ":" in base else ""
        if tag.lower() in {"latest", "main-latest", "main-stable"} or forbidden_release(tag):
            raise ValueError("forbidden LiteLLM image reference: " + source)
        if not re.search(r"@sha256:[0-9a-f]{64}$", image):
            raise ValueError("LiteLLM image requires a pinned digest: " + source)

    for path in sorted(paths):
        if not path.is_file():
            continue
        raw = path.read_bytes()
        source = path.relative_to(root).as_posix()
        hashes[source] = hashlib.sha256(raw).hexdigest()
        for line in raw.decode().replace("\\\n", " ").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if path.name.startswith("Dockerfile"):
                tokens = shlex.split(line, comments=True)
                if tokens and tokens[0].upper() == "FROM":
                    images = [token for token in tokens[1:] if not token.startswith("--")]
                    if not images:
                        raise ValueError("missing Docker image declaration: " + source)
                    check(images[0], source)
                elif tokens and tokens[0].upper() == "ARG":
                    for token in tokens[1:]:
                        if "=" in token:
                            check(token.split("=", 1)[1], source)
            else:
                for field in fields:
                    for match in field.finditer(line):
                        check(next(value for value in match.groups() if value is not None), source)
    return hashes


def inventory(root: Path = ROOT) -> dict[str, Any]:
    packages: dict[tuple[str, str, str], set[str]] = {}
    hashes = {}

    def add(ecosystem: str, name: str, version: str, source: str) -> None:
        if ecosystem == "PyPI":
            name = re.sub(r"[-_.]+", "-", name).lower()
        if name == "litellm" and forbidden_release(version):
            raise ValueError("forbidden LiteLLM artifact in dependency inventory")
        packages.setdefault((ecosystem, name, version), set()).add(source)

    inputs = locked_inputs(root, add)
    failures = bootstrap_errors(root)
    if failures:
        raise ValueError("; ".join(failures))
    hashes = inputs["source_sha256"]
    rows = [
        {"ecosystem": eco, "name": name, "version": version, "sources": sorted(sources)}
        for (eco, name, version), sources in sorted(packages.items())
    ]
    payload: dict[str, Any] = {
        "format": "ezllmrouter-lock-inventory-v2",
        **inputs,
        "packages": rows,
        "source_sha256": hashes,
        "image_source_sha256": deployment_images(root),
    }
    payload["sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return payload


def sbom(data: dict[str, Any]) -> dict[str, Any]:
    components = []
    for row in data["packages"]:
        kind = (
            "deb"
            if row["ecosystem"].startswith("Debian:")
            else {
                "PyPI": "pypi",
                "npm": "npm",
                "crates.io": "cargo",
                "Go": "golang",
                "Maven": "maven",
                "NuGet": "nuget",
            }[row["ecosystem"]]
        )
        purl = (
            "pkg:"
            + kind
            + "/"
            + quote(row["name"].replace(":", "/") if kind == "maven" else row["name"], safe="/")
            + "@"
            + quote(row["version"], safe="")
        )
        if kind == "deb":
            purl += "?distro=debian-" + quote(row["ecosystem"].split(":", 1)[1], safe="")
        components.append(
            {
                "type": "library",
                "name": row["name"],
                "version": row["version"],
                "purl": purl,
                "bom-ref": purl,
                "properties": [
                    {"name": "ezllmrouter:lock-sources", "value": ",".join(row["sources"])}
                ],
            }
        )
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {
            "properties": [
                {
                    "name": "ezllmrouter:scope",
                    "value": "Declared locks plus resolved Rust and installed image OS/application packages; base runtime binary internals are outside this inventory"
                    if "images" in data
                    else "Declared Python/npm locks and resolved Rust closure; installed image contents require a target inventory",
                },
                {"name": "ezllmrouter:inventory-sha256", "value": data["sha256"]},
            ]
        },
        "components": components,
    }


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def fetch(route: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    if not re.fullmatch(r"query|querybatch|vulns/[A-Za-z0-9._:-]+", route):
        raise ValueError("invalid advisory route")
    request = Request(
        API + route,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", "User-Agent": "EzLLMRouter-advisory-audit/1"},
    )
    opener = build_opener(ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=15) as response:
        raw = response.read(MAX_RESPONSE + 1)
    if len(raw) > MAX_RESPONSE:
        raise ValueError("advisory response exceeds limit")
    result = json.loads(raw)
    if type(result) is not dict:
        raise ValueError("invalid advisory response")
    return result


def query_versions(data: dict[str, Any]) -> list[str]:
    """A local rebuild label must not hide advisories for its upstream version."""
    overrides = {}
    for row in data.get("advisory_versions", []):
        key = row["ecosystem"], row["name"], row["version"]
        upstream = row["upstream_version"]
        if (
            key[:2] not in {("Debian:13", "openssl"), ("PyPI", "cryptography")}
            or key in overrides
            or not re.fullmatch(re.escape(upstream) + r"\+ezllmrouter[1-9][0-9]*", row["version"])
            or not re.fullmatch(r"[0-9a-f]{64}", row["native_build"])
        ):
            raise ValueError("unreviewed native advisory version mapping")
        overrides[key] = upstream
    return [
        overrides.get((row["ecosystem"], row["name"], row["version"]), row["version"])
        for row in data["packages"]
    ]


def query(data: dict[str, Any], fetcher: Callable[..., dict[str, Any]] = fetch) -> dict[str, Any]:
    results = []
    versions = query_versions(data)
    for offset in range(0, len(data["packages"]), 100):
        rows = data["packages"][offset : offset + 100]
        response = fetcher(
            "querybatch",
            {
                "queries": [
                    {
                        "package": {"ecosystem": row["ecosystem"], "name": row["name"]},
                        "version": version,
                    }
                    for row, version in zip(
                        rows, versions[offset : offset + len(rows)], strict=True
                    )
                ]
            },
        )
        batch = response.get("results")
        if not isinstance(batch, list) or len(batch) != len(rows):
            raise ValueError("incomplete advisory batch")
        for package, first, version in zip(
            rows, batch, versions[offset : offset + len(rows)], strict=True
        ):
            pages, seen, result = [], set(), first
            vulnerabilities = []
            for _page in range(100):
                if (
                    type(result) is not dict
                    or "error" in result
                    or type(result.get("vulns", [])) is not list
                ):
                    raise ValueError("invalid package advisory page")
                pages.append(result)
                vulnerabilities.extend(result.get("vulns", []))
                token = result.get("next_page_token")
                if token is None or token == "":
                    break
                if not isinstance(token, str) or len(token) > 4096 or token in seen:
                    raise ValueError("invalid/repeated advisory page token")
                seen.add(token)
                result = fetcher(
                    "query",
                    {
                        "package": {"ecosystem": package["ecosystem"], "name": package["name"]},
                        "version": version,
                        "page_token": token,
                    },
                )
            else:
                raise ValueError("advisory pagination limit")
            results.append({"vulns": vulnerabilities, "pages": pages})
    identifiers = set()
    for result in results:
        if (
            type(result) is not dict
            or "error" in result
            or type(result.get("vulns", [])) is not list
            or result.get("next_page_token")
        ):
            raise ValueError("invalid package advisory result")
        for vulnerability in result.get("vulns", []):
            identifier = vulnerability["id"]
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{1,200}", identifier):
                raise ValueError("invalid advisory identity")
            identifiers.add(identifier)
    details = {identifier: fetcher("vulns/" + identifier) for identifier in sorted(identifiers)}
    if any(value.get("id") != identifier for identifier, value in details.items()):
        raise ValueError("advisory identity mismatch")
    return {
        "inventory_sha256": data["sha256"],
        "queried_at": datetime.now(timezone.utc).isoformat(),
        "complete": True,
        "queried_versions": versions,
        "results": results,
        "vulnerabilities": details,
    }


def validate_pages(result: dict[str, Any]) -> None:
    pages = result.get("pages")
    if pages is None:
        return  # Legacy snapshots without a page token remain explicit owner inputs.
    if not isinstance(pages, list) or not 1 <= len(pages) <= 100:
        raise ValueError("invalid advisory page evidence")
    merged = []
    seen = set()
    for index, page in enumerate(pages):
        if type(page) is not dict or "error" in page or type(page.get("vulns", [])) is not list:
            raise ValueError("invalid advisory page evidence")
        merged.extend(page.get("vulns", []))
        token = page.get("next_page_token")
        if index == len(pages) - 1:
            if token not in (None, ""):
                raise ValueError("unconsumed advisory page")
        elif not isinstance(token, str) or not token or len(token) > 4096 or token in seen:
            raise ValueError("invalid advisory page evidence")
        else:
            seen.add(token)
    if merged != result.get("vulns", []):
        raise ValueError("advisory page results differ from retained evidence")


def findings(
    data: dict[str, Any], snapshot: dict[str, Any], *, now: datetime | None = None
) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    observed = datetime.fromisoformat(snapshot["queried_at"])
    if (
        snapshot.get("complete") is not True
        or snapshot["inventory_sha256"] != data["sha256"]
        or not timedelta(0) <= now - observed <= timedelta(days=7)
    ):
        raise ValueError("stale, incomplete or mismatched advisory snapshot")
    if len(snapshot["results"]) != len(data["packages"]):
        raise ValueError("missing package advisory result")
    if data.get("advisory_versions") and snapshot.get("queried_versions") != query_versions(data):
        raise ValueError("native advisory query versions differ from reviewed upstream versions")
    issues = []
    for package, result in zip(data["packages"], snapshot["results"], strict=True):
        if (
            type(result) is not dict
            or "error" in result
            or type(result.get("vulns", [])) is not list
            or result.get("next_page_token")
        ):
            raise ValueError("invalid package advisory result")
        validate_pages(result)
        for item in result.get("vulns", []):
            detail = snapshot["vulnerabilities"][item["id"]]
            if detail.get("id") != item["id"]:
                raise ValueError("advisory identity mismatch")
            if detail.get("withdrawn"):
                withdrawn = datetime.fromisoformat(detail["withdrawn"])
                if withdrawn.tzinfo is None or withdrawn > now:
                    raise ValueError("invalid advisory withdrawal time")
            if not detail.get("withdrawn"):
                issues.append(
                    {
                        "package": package,
                        "id": item["id"],
                        "severity": detail.get("severity", []),
                        **classification(detail),
                    }
                )
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--audit", action="store_true", help="query public OSV metadata; never install packages"
    )
    mode.add_argument(
        "--snapshot", type=Path, help="validate a complete matching OSV snapshot offline"
    )
    parser.add_argument("--output", type=Path, default=ROOT / ".artifacts/security/dependencies")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"audit_state": "not_requested", "passed": False}
    try:
        data = inventory()
        (args.output / "inventory.json").write_text(json.dumps(data, indent=2) + "\n")
        (args.output / "sbom.cdx.json").write_text(json.dumps(sbom(data), indent=2) + "\n")
        if args.audit or args.snapshot:
            snapshot = query(data) if args.audit else json.loads(args.snapshot.read_text())
            (args.output / "osv-snapshot.json").write_text(json.dumps(snapshot, indent=2) + "\n")
            issues = findings(data, snapshot)
            report.update(
                audit_state="complete",
                findings=issues,
                passed=not any(row["blocking"] for row in issues),
            )
        else:
            report["inventory_valid"] = True
        print(
            f"Dependency inventory: {len(data['packages'])} declared Python/npm/native versions; advisory state: {report['audit_state']}"
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        report.update(audit_state="unavailable", error_type=type(error).__name__)
    finally:
        (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return 0 if report.get("inventory_valid") or report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
