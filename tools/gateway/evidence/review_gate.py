"""Stop DEV-04 execution if the bounded artifact review facts change."""
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
import json
import sys
import zipfile


def advisory_shape(rows):
    return sorted((row["ghsa_id"], tuple(sorted(
        (item.get("package", {}).get("name"), item.get("vulnerable_version_range"))
        for item in row.get("vulnerabilities", [])))) for row in rows)


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: review_gate.py ROOT RUN_DIR")
    root, run = map(Path, sys.argv[1:])
    inventory = json.loads((root / "deploy/local/inputs/gateway/WHEEL-INVENTORY.json").read_text())
    advisories = json.loads((run / "PYPI-ADVISORIES.json").read_text())
    current = json.loads((run / "GITHUB-ADVISORIES.json").read_text())
    reviewed = json.loads((root / "deploy/local/inputs/gateway/github-advisories.json").read_text())
    wheels = inventory["wheels"]
    if (len(wheels) != 117 or len(advisories["packages"]) != 117 or
        any(row["status"] != "queried" or row["vulnerabilities"] for row in advisories["packages"])):
        raise ValueError("PyPI advisory query unavailable or new notice")
    if advisory_shape(current) != advisory_shape(reviewed):
        raise ValueError("publisher advisory set changed; review before execution")
    if not any(row["name"] == "litellm" and row["version"] == "1.105.1" for row in wheels):
        raise ValueError("selected release absent")
    missing = {row["name"] for row in wheels if not row["license_expression"] and not row["license"]}
    if missing != {"fastuuid", "Jinja2", "markdown-it-py", "mdurl", "prompt_toolkit",
                   "tokenizers", "wcwidth"}:
        raise ValueError("license metadata set changed")
    wheel_dir = root / "gateway-inputs/dev04/wheels"
    for row in wheels:
        if row["name"] not in missing:
            continue
        with zipfile.ZipFile(wheel_dir / row["filename"]) as archive:
            license_paths = [name for name in archive.namelist() if "license" in name.lower()
                             and not name.endswith("/")]
            if row["name"] == "tokenizers":
                name = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
                metadata = BytesParser(policy=default).parsebytes(archive.read(name))
                if "License :: OSI Approved :: Apache Software License" not in metadata.get_all("Classifier", []):
                    raise ValueError("tokenizers license classifier absent")
            elif not license_paths:
                raise ValueError("license file absent: " + row["name"])
    enterprise = next(row for row in wheels if row["name"] == "litellm-enterprise")
    with zipfile.ZipFile(wheel_dir / enterprise["filename"]) as archive:
        license_name = next(name for name in archive.namelist() if name.endswith("licenses/LICENSE.md"))
        license_text = archive.read(license_name).decode("utf-8")
        if "development and testing purposes, without requiring a" not in license_text:
            raise ValueError("enterprise development/testing grant changed")
    print(json.dumps({"status": "DEV04_ARTIFACT_REVIEW_FACTS_UNCHANGED",
                      "wheels": len(wheels), "pypi_notices": 0,
                      "publisher_advisories": len(current),
                      "limit": "metadata/advisory scope only; no source-to-native proof or production clearance"}))


if __name__ == "__main__":
    main()
