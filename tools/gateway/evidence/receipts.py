"""Small, data-only DEV-04 wheel inventory and PyPI advisory receipt."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
import hashlib
import json
import re
import sys
from urllib.parse import quote
from urllib.request import urlopen
import zipfile


ROOT_WHEEL = "litellm-1.105.1-cp310-abi3-manylinux_2_28_aarch64.whl"
ROOT_SHA256 = "beb5044645144308b39560049c0f68875ad7de07e681ad0b73e2bc6c3705ba61"


def inventory(directory: Path) -> list[dict]:
    rows = []
    for path in sorted(directory.glob("*.whl")):
        with zipfile.ZipFile(path) as archive:
            bad = archive.testzip()
            if bad:
                raise ValueError(f"bad ZIP member: {path.name}: {bad}")
            names = archive.namelist()
            if len(names) != len(set(names)) or any(
                name.startswith("/") or ".." in Path(name).parts for name in names
            ):
                raise ValueError(f"unsafe wheel members: {path.name}")
            metadata = [name for name in names if name.endswith(".dist-info/METADATA")]
            if len(metadata) != 1:
                raise ValueError(f"missing or duplicate METADATA: {path.name}")
            msg = BytesParser(policy=default).parsebytes(archive.read(metadata[0]))
            name, version = msg["Name"], msg["Version"]
            if not name or not version or not re.fullmatch(r"[A-Za-z0-9_.-]+", name + version):
                raise ValueError(f"invalid wheel identity: {path.name}")
            rows.append(
                {
                    "name": name,
                    "version": version,
                    "filename": path.name,
                    "bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "license_expression": msg.get("License-Expression"),
                    "license": msg.get("License"),
                }
            )
    if len(rows) != 117:
        raise ValueError(f"expected 117 resolved wheels, found {len(rows)}")
    roots = [row for row in rows if row["filename"] == ROOT_WHEEL]
    if len(roots) != 1 or roots[0]["sha256"] != ROOT_SHA256:
        raise ValueError("exact LiteLLM root wheel mismatch")
    keys = [re.sub(r"[-_.]+", "-", row["name"]).lower() for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate normalized distribution name")
    return rows


def advisory(row: dict) -> dict:
    url = f"https://pypi.org/pypi/{quote(row['name'])}/{quote(row['version'])}/json"
    try:
        with urlopen(url, timeout=12) as response:
            report = json.load(response)
        findings = report.get("vulnerabilities")
        if not isinstance(findings, list):
            raise ValueError("PyPI did not provide vulnerabilities list")
        return {
            "name": row["name"],
            "version": row["version"],
            "url": url,
            "status": "queried",
            "vulnerabilities": findings,
        }
    except Exception as exc:
        return {
            "name": row["name"],
            "version": row["version"],
            "url": url,
            "status": "unavailable",
            "error": type(exc).__name__,
        }


def main():
    if len(sys.argv) != 4 or sys.argv[1] not in {"inventory", "advisories"}:
        raise SystemExit("usage: receipts.py inventory|advisories WHEEL_DIR OUTPUT_DIR")
    mode, wheel_dir, output_dir = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = inventory(wheel_dir)
    if mode == "inventory":
        lock = "".join(
            f"{row['name']}=={row['version']} --hash=sha256:{row['sha256']}\n" for row in rows
        )
        (output_dir / "requirements.gateway.lock").write_text(lock)
        target = output_dir / "WHEEL-INVENTORY.json"
        value = {
            "target": "CPython 3.12 Linux ARM64, manylinux_2_28/manylinux2014",
            "root_extra": "litellm[proxy]==1.105.1",
            "wheels": rows,
        }
    else:
        with ThreadPoolExecutor(max_workers=8) as pool:
            findings = list(pool.map(advisory, rows))
        target = output_dir / "PYPI-ADVISORIES.json"
        value = {
            "checked_at_utc": datetime.now(timezone.utc).isoformat(),
            "scope": "Exact-version PyPI JSON vulnerability notices; not a complete security clearance",
            "packages": findings,
        }
    target.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "path": str(target),
                "packages": len(rows),
                "unavailable": sum(
                    x.get("status") == "unavailable" for x in value.get("packages", [])
                ),
                "notices": sum(
                    len(x.get("vulnerabilities", [])) for x in value.get("packages", [])
                ),
            }
        )
    )


if __name__ == "__main__":
    main()
