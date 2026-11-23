"""Check frozen wheel metadata against the selected Linux ARM64 environment."""

from __future__ import annotations

import email
from pathlib import Path
from typing import Any
import zipfile


def validate_dependencies(inventory: dict[str, Any], directory: Path) -> None:
    # Parsers come from the pinned development environment. Wheel code is never
    # imported, and requirement URLs never trigger acquisition.
    from packaging.requirements import Requirement
    from packaging.specifiers import SpecifierSet
    from packaging.utils import canonicalize_name
    from tools.security_dependencies import forbidden_release

    python = inventory.get("python_full_version", "3.12.16")
    environment = {
        "implementation_name": "cpython",
        "implementation_version": python,
        "os_name": "posix",
        "platform_machine": "aarch64",
        "platform_system": "Linux",
        "platform_release": "",
        "platform_version": "",
        "platform_python_implementation": "CPython",
        "python_version": ".".join(python.split(".")[:2]),
        "python_full_version": python,
    }
    versions, requirements, extras = {}, {}, {}
    for row in inventory["wheels"]:
        name = canonicalize_name(row["name"])
        if name == "litellm" and forbidden_release(row["version"]):
            raise ValueError("forbidden LiteLLM artifact")
        with zipfile.ZipFile(directory / row["filename"]) as archive:
            names = [entry for entry in archive.namelist() if entry.endswith(".dist-info/METADATA")]
            if len(names) != 1:
                raise ValueError("wheel requires exactly one distribution metadata record")
            metadata = email.message_from_bytes(archive.read(names[0]))
        if (
            canonicalize_name(metadata.get("Name", "")) != name
            or metadata.get("Version") != row["version"]
        ):
            raise ValueError("wheel distribution identity mismatch: " + name)
        if metadata.get("Requires-Python") and not SpecifierSet(
            metadata["Requires-Python"]
        ).contains(python, prereleases=True):
            raise ValueError("wheel Python requirement mismatch: " + name)
        versions[name] = row["version"]
        requirements[name] = [Requirement(value) for value in metadata.get_all("Requires-Dist", [])]
        extras[name] = set()
    if inventory.get("root_extra"):
        root = Requirement(inventory["root_extra"])
        name = canonicalize_name(root.name)
        if (
            root.url
            or name not in versions
            or not root.specifier.contains(versions[name], prereleases=True)
        ):
            raise ValueError("frozen root requirement mismatch")
        extras[name].update(root.extras)
    changed = True
    errors = set()
    while changed:
        changed = False
        for name, declared in requirements.items():
            for requirement in declared:
                active = requirement.marker is None or any(
                    requirement.marker.evaluate(dict(environment, extra=extra))
                    for extra in {"", *extras[name]}
                )
                if not active:
                    continue
                dependency = canonicalize_name(requirement.name)
                if (
                    requirement.url
                    or dependency not in versions
                    or not requirement.specifier.contains(versions[dependency], prereleases=True)
                ):
                    errors.add(
                        name
                        + " requires "
                        + dependency
                        + str(requirement.specifier)
                        + "; selected "
                        + versions.get(dependency, "missing")
                    )
                if dependency not in extras:
                    continue
                added = set(requirement.extras) - extras[dependency]
                if added:
                    extras[dependency].update(added)
                    changed = True
    if errors:
        raise ValueError("frozen dependency constraint mismatch: " + " | ".join(sorted(errors)))
