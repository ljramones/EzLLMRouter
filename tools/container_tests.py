"""Resolve Docker test commands against the actual staged source inventory, offline."""

from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import dataclass
import fnmatch
import inspect
from pathlib import Path
import shlex
import tempfile

from deploy.local import prepare
from tools.gateway.stage import source_mapping

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class TestCommand:
    kind: str
    selectors: tuple[str, ...]
    directory: str = ""
    pattern: str = "test*.py"


def test_commands(dockerfile: str) -> list[TestCommand]:
    commands = []
    for line in dockerfile.replace("\\\n", " ").splitlines():
        if not line.lstrip().startswith("RUN "):
            continue
        tokens = shlex.split(line)
        for index, token in enumerate(tokens):
            if token == "unittest" and index and tokens[index - 1] == "-m":
                end = next(
                    (i for i in range(index + 1, len(tokens)) if tokens[i] in {"&&", ";", "|"}),
                    len(tokens),
                )
                args = tokens[index + 1 : end]
                if args and args[0] == "discover":
                    directory = args[args.index("-s") + 1] if "-s" in args else "/app"
                    pattern = args[args.index("-p") + 1] if "-p" in args else "test*.py"
                    commands.append(TestCommand("discover", (), directory, pattern))
                else:
                    selectors = tuple(
                        arg for arg in args if arg not in {"-v", "-q", "--verbose", "--quiet"}
                    )
                    if not selectors or any(selector.startswith("-") for selector in selectors):
                        raise ValueError(
                            "Docker unittest command needs explicit supported selectors"
                        )
                    commands.append(TestCommand("module", selectors))
            if (
                token.startswith(("/app/", "/tmp/"))
                and token.endswith(".py")
                and Path(token).name.startswith("test_")
            ):
                commands.append(TestCommand("script", (token,)))
    return commands


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
        prepare.stage_service_validation(build)
        prepare.stage_worker_validation(build)
        for path in build.rglob("*"):
            if path.is_file() and path.name.startswith("test_"):
                relative = path.relative_to(build).as_posix()
                # Keep canonical paths after the temporary tree is removed.
                candidates = [
                    root / "tests/operator_console" / path.name,
                    root / "tests/gateway_integration" / path.name,
                ]
                result[relative] = next(
                    candidate for candidate in candidates if candidate.is_file()
                )
    return result


def resolve(dockerfile: str, context: str, staged: Mapping[str, Path]) -> list[str]:
    base = {
        "/app/" + key[len(context) + 1 :]: source
        for key, source in staged.items()
        if key.startswith(context + "/")
    }
    errors = []
    for line in dockerfile.replace("\\\n", " ").splitlines():
        if not line.lstrip().startswith("RUN "):
            continue
        virtual = dict(base)
        # Bind mounts exist only for this instruction, not later RUN commands.
        for token in shlex.split(line):
            if not token.startswith("--mount="):
                continue
            fields = dict(part.split("=", 1) for part in token[8:].split(",") if "=" in part)
            if "source" in fields and "target" in fields:
                prefix = context + "/" + fields["source"]
                for key, source in staged.items():
                    if key == prefix or key.startswith(prefix + "/"):
                        virtual[fields["target"] + key[len(prefix) :]] = source
        for command in test_commands(line):
            if command.kind == "discover":
                matches = [
                    path
                    for path in virtual
                    if path.startswith(command.directory.rstrip("/") + "/")
                    and fnmatch.fnmatch(Path(path).name, command.pattern)
                ]
                if not matches:
                    errors.append(
                        "empty Docker discovery: " + command.directory + "/" + command.pattern
                    )
            elif command.kind == "script":
                for path in command.selectors:
                    if path not in virtual or not virtual[path].is_file():
                        errors.append("unstaged Docker test script: " + path)
            else:
                for selector in command.selectors:
                    parts = selector.split(".")
                    candidates = [
                        "/app/" + "/".join(parts[:end]) + ".py" for end in range(len(parts), 0, -1)
                    ]
                    selected = next(
                        (
                            path
                            for path in candidates
                            if path in virtual and virtual[path].is_file()
                        ),
                        None,
                    )
                    if selected is None:
                        errors.append("unstaged Docker test module: " + selector)
    return errors


def main() -> int:
    sources = staged_sources()
    failures = []
    for context in ("service", "worker"):
        dockerfile = (ROOT / f"deploy/local/Dockerfile.{context}").read_text()
        failures.extend(resolve(dockerfile, context, sources))
    if failures:
        print("\n".join(failures))
        return 1
    print("Docker validation test modules, discovery patterns and scripts are staged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
