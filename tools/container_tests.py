"""Resolve Docker test commands against the actual staged source inventory, offline."""

from __future__ import annotations

import ast
from collections.abc import Mapping
import inspect
from pathlib import Path
import shutil
import subprocess
import tempfile
from unittest.mock import patch
from typing import Any

from deploy.local import prepare
from tools.gateway.stage import source_mapping
from tools.docker_validation import resolve_recipe
from tools.docker_validation import TestCommand as TestCommand
from tools.docker_validation import test_commands as test_commands

ROOT = Path(__file__).resolve().parents[1]


def _path(node: ast.expr, name: str) -> str | None:
    if isinstance(node, ast.Name) and node.id == name:
        return ""
    if (
        isinstance(node, ast.BinOp)
        and isinstance(node.op, ast.Div)
        and isinstance(node.right, ast.Constant)
        and isinstance(node.right.value, str)
    ):
        parent = _path(node.left, name)
        if parent is not None:
            return str(Path(parent) / node.right.value)
    return None


def literal_overlays(source: str) -> dict[str, str]:
    result = {}
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "copy2"
            and len(node.args) >= 2
        ):
            origin, target = _path(node.args[0], "ROOT"), _path(node.args[1], "build")
            if origin and target:
                result[target] = origin
    return result


def staged_sources(root: Path = ROOT) -> dict[str, Path]:
    result = {target: root / source for source, target in source_mapping(root, dev05=True)}
    result.update(
        {
            target: root / source
            for target, source in literal_overlays(inspect.getsource(prepare.prepare_work)).items()
        }
    )
    # These are the same helpers used by preparation, not a second filename list.
    with tempfile.TemporaryDirectory(prefix="ezllmrouter-staged-tests-") as temporary:
        build = Path(temporary)
        package = build / "service/server/ezllmrouter_server"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("")
        original = shutil.copy2

        def capture(source: str | Path, target: str | Path, **options: Any) -> str:
            destination = Path(target)
            if destination.is_dir():
                destination /= Path(source).name
            relative = destination.relative_to(build).as_posix()
            result[relative] = Path(source)
            return original(str(source), str(target), **options)

        with (
            patch.object(prepare, "ROOT", root),
            patch.object(shutil, "copy2", side_effect=capture),
        ):
            prepare.stage_service_validation(build)
            prepare.stage_worker_validation(build)
            prepare.stage_profile_checks(build)
        for path in build.rglob("*"):
            if path.is_file() and path.name == "__init__.py":
                relative = path.relative_to(build).as_posix()
                result.setdefault(relative, root / "tests/__init__.py")
        # The real worker helper copies the entire trusted package into its
        # temporary validation mount; mirror its canonical source identities.
        for target, source in list(result.items()):
            if target.startswith("service/server/"):
                result["worker/validation/server/" + target[len("service/server/") :]] = source
    return result


def resolve(dockerfile: str, context: str, staged: Mapping[str, Path]) -> list[str]:
    return resolve_recipe(dockerfile, context, staged)


def dockerfiles(root: Path = ROOT) -> list[str]:
    names = subprocess.check_output(
        ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        text=True,
    ).split("\0")
    return sorted(
        name
        for name in set(names)
        if Path(name).name.startswith("Dockerfile") and (root / name).is_file()
    )


def repository_errors(root: Path, sources: Mapping[str, Path]) -> list[str]:
    qualified = {
        "deploy/local/Dockerfile.service": "service",
        "deploy/local/Dockerfile.worker": "worker",
    }
    errors = []
    for name in dockerfiles(root):
        recipe = (root / name).read_text()
        try:
            commands = test_commands(recipe)
            if not commands:
                continue
            context = qualified.get(name)
            if context is None:
                errors.append(name + ": validation has no qualified staging context")
                continue
            errors.extend(name + ": " + error for error in resolve(recipe, context, sources))
        except ValueError as error:
            errors.append(name + ": " + str(error))
    return errors


def main() -> int:
    sources = staged_sources()
    failures = repository_errors(ROOT, sources)
    if failures:
        print("\n".join(failures))
        return 1
    print(
        f"Inspected {len(dockerfiles())} Dockerfiles; validation entry points resolve through actual COPY/stage/mount contents."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
