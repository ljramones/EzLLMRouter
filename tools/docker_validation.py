"""Parse supported validation entry points without executing a Dockerfile or shell."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
import fnmatch
import io
import json
import posixpath
import re
import shlex
from collections.abc import Mapping
from pathlib import Path, PurePosixPath


@dataclass(frozen=True)
class TestCommand:
    kind: str
    selectors: tuple[str, ...]
    directory: str = ""
    pattern: str = "test*.py"
    cwd: str = "/"
    pythonpath: tuple[str, ...] = ()


def instructions(source: str) -> list[tuple[str, str]]:
    rows = []
    pending = ""
    for line in source.splitlines():
        if line.lower().lstrip().startswith("# escape=") and not line.rstrip().endswith("\\"):
            raise ValueError("unsupported Docker escape directive")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        pending += line.rstrip().removesuffix("\\") + " "
        if line.rstrip().endswith("\\"):
            continue
        match = re.fullmatch(r"\s*([A-Za-z]+)\s+(.*?)\s*", pending, re.S)
        if match is None:
            raise ValueError("unparsed Docker instruction")
        instruction, body = match[1].upper(), match[2]
        if instruction not in {
            "ARG",
            "FROM",
            "ENV",
            "COPY",
            "ADD",
            "WORKDIR",
            "RUN",
            "USER",
            "CMD",
            "ENTRYPOINT",
            "LABEL",
            "EXPOSE",
            "VOLUME",
            "STOPSIGNAL",
            "SHELL",
            "HEALTHCHECK",
            "ONBUILD",
            "MAINTAINER",
        }:
            raise ValueError("unsupported Docker instruction: " + instruction)
        if instruction == "RUN" and "<<" in body:
            raise ValueError("Docker validation heredocs are not qualified")
        if instruction == "ONBUILD" and _validation_hint(body):
            raise ValueError("deferred Docker validation is not qualified")
        rows.append((instruction, body))
        pending = ""
    if pending:
        raise ValueError("truncated Docker instruction")
    return rows


def flags(body: str) -> tuple[dict[str, str], str]:
    result: dict[str, str] = {}
    body = body.lstrip()
    while body.startswith("--"):
        stream = io.StringIO(body)
        lexer = shlex.shlex(stream, posix=True)
        lexer.whitespace_split = True
        token = lexer.get_token()
        if not isinstance(token, str):
            raise ValueError("invalid Docker flag")
        key, separator, value = token[2:].partition("=")
        if not separator:
            value = "true"
        # Multiple bind mounts are intentionally retained in source order.
        unique = key if key != "mount" else "mount:" + str(len(result))
        result[unique] = value
        body = body[stream.tell() :].lstrip()
    return result, body


def expand(value: str, environment: Mapping[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match[1] or match[2]
        if name not in environment:
            raise ValueError("unresolved validation variable: " + name)
        return environment[name]

    return re.sub(r"\$\{([A-Za-z_]\w*)\}|\$([A-Za-z_]\w*)", replace, value)


def location(value: str, cwd: str) -> str:
    return posixpath.normpath(posixpath.join(cwd, value))


def _validation_hint(value: str) -> bool:
    return bool(re.search(r"\b(?:unittest|pytest)\b|\btests[/\.]|\.py(?:[\s\"']|$)", value))


def _command(
    arguments: list[str], cwd: str, environment: dict[str, str], depth: int
) -> list[TestCommand]:
    if not arguments:
        return []
    if arguments[0] == "env":
        arguments = arguments[1:]
    local = dict(environment)
    while arguments and re.fullmatch(r"[A-Za-z_]\w*=.*", arguments[0], re.S):
        name, value = arguments.pop(0).split("=", 1)
        local[name] = expand(value, local)
    if not arguments:
        return []
    program = posixpath.basename(arguments[0])
    if program == "rm":
        return [
            TestCommand(
                "remove",
                tuple(
                    location(expand(value, local), cwd)
                    for value in arguments[1:]
                    if not value.startswith("-")
                ),
                cwd=cwd,
            )
        ]
    if program in {"cp", "mv", "install", "tar", "unzip", "rsync", "ln", "sed"}:
        raise ValueError("unmodeled filesystem mutation in validation recipe: " + program)
    if program in {"sh", "bash"} and len(arguments) >= 3 and "c" in arguments[1].lstrip("-"):
        return shell_commands(arguments[2], cwd, local, depth + 1)
    python = bool(re.fullmatch(r"python(?:3(?:\.\d+)?)?", program))
    pytest = program in {"pytest", "py.test"}
    if not python and not pytest:
        if program not in {
            "test",
            "find",
            "chmod",
            "chown",
            "mkdir",
            "rm",
            "sha256sum",
        } and _validation_hint(" ".join(arguments)):
            raise ValueError("unsupported validation wrapper: " + program)
        return []
    args = list(arguments[1:])
    if python:
        while args and args[0] not in {"-m", "-c"} and args[0].startswith("-"):
            option = args.pop(0)
            if option in {"-W", "-X"}:
                if not args:
                    raise ValueError("missing Python option value")
                args.pop(0)
        if not args:
            return []
        if args[0] == "-c":
            if _validation_hint(" ".join(args[1:])):
                raise ValueError("inline Python validation needs an explicit supported entry point")
            return []
        if args[0] == "-m":
            if len(args) < 2:
                raise ValueError("missing Python module")
            module, args = args[1], args[2:]
            if module not in {"unittest", "pytest"}:
                if _validation_hint(" ".join(args)):
                    raise ValueError("unsupported Python validation wrapper: " + module)
                return []
            pytest = module == "pytest"
        else:
            script = expand(args[0], local)
            if not script.endswith(".py"):
                if _validation_hint(" ".join(args)):
                    raise ValueError("unsupported Python validation input")
                return []
            return [TestCommand("script", (location(script, cwd),), cwd=cwd)]
    paths = tuple(
        location(path, cwd)
        for path in expand(local.get("PYTHONPATH", ""), local).split(":")
        if path
    )
    args = [expand(value, local) for value in args]
    if not pytest and args and args[0] == "discover":
        directory, pattern = cwd, "test*.py"
        index = 1
        while index < len(args):
            option = args[index]
            if option in {
                "-s",
                "--start-directory",
                "-p",
                "--pattern",
                "-t",
                "--top-level-directory",
            }:
                if index + 1 == len(args):
                    raise ValueError("missing unittest discovery option value")
                value = args[index + 1]
                if option in {"-s", "--start-directory"}:
                    directory = location(value, cwd)
                elif option in {"-p", "--pattern"}:
                    pattern = value
                index += 2
            elif option in {"-v", "-q", "--verbose", "--quiet", "-f", "-b"}:
                index += 1
            else:
                raise ValueError("unsupported unittest discovery option: " + option)
        return [TestCommand("discover", (), directory, pattern, cwd, paths)]
    selectors = []
    index = 0
    while index < len(args):
        value = args[index]
        if value in {"-q", "-v", "-vv", "--quiet", "--verbose", "-f", "-b", "-x"}:
            index += 1
        elif pytest and value in {"-k", "-m", "--maxfail"}:
            if index + 1 == len(args):
                raise ValueError("missing pytest option value")
            index += 2
        elif value.startswith("-"):
            raise ValueError("unsupported validation selector option: " + value)
        else:
            if "$" in value or "`" in value:
                raise ValueError("unresolved validation selector")
            selectors.append(value)
            index += 1
    if not selectors:
        raise ValueError("Docker validation needs explicit supported selectors")
    return [
        TestCommand("pytest" if pytest else "module", tuple(selectors), cwd=cwd, pythonpath=paths)
    ]


def shell_commands(
    body: str, cwd: str = "/", environment: Mapping[str, str] | None = None, depth: int = 0
) -> list[TestCommand]:
    if depth > 8:
        raise ValueError("validation shell nesting limit")
    local = dict(environment or {})
    # shlex needs whitespace_split to preserve paths and options as single tokens.
    lexer = shlex.shlex(body, posix=True, punctuation_chars=";&|()<>")
    lexer.whitespace_split = True
    tokens = list(lexer)
    result, segment = [], []
    for token in [*tokens, ";"]:
        if token not in {";", "&&", "||", "|"}:
            segment.append(token)
            continue
        if segment and segment[0] == "cd":
            if len(segment) != 2:
                raise ValueError("unsupported validation working directory")
            cwd = location(expand(segment[1], local), cwd)
        elif segment and segment[0] == "export":
            for assignment in segment[1:]:
                name, separator, value = assignment.partition("=")
                if not separator:
                    raise ValueError("unsupported validation environment")
                local[name] = expand(value, local)
        else:
            result.extend(_command(segment, cwd, local, depth))
        segment = []
    return result


def run_commands(
    body: str, cwd: str = "/", environment: Mapping[str, str] | None = None
) -> list[TestCommand]:
    _options, command = flags(body)
    if command.startswith("["):
        arguments = json.loads(command)
        if not isinstance(arguments, list) or not all(
            isinstance(value, str) for value in arguments
        ):
            raise ValueError("invalid exec-form validation command")
        return _command(arguments, cwd, dict(environment or {}), 0)
    return shell_commands(command, cwd, environment)


def test_commands(dockerfile: str) -> list[TestCommand]:
    if not any(
        instruction == "RUN" and _validation_hint(body)
        for instruction, body in instructions(dockerfile)
    ):
        return []
    commands: list[TestCommand] = []
    resolve_recipe(dockerfile, "", {}, commands)
    return commands


@dataclass
class Stage:
    files: dict[str, Path] = field(default_factory=dict)
    cwd: str = "/"
    environment: dict[str, str] = field(default_factory=dict)


def copy_files(
    files: Mapping[str, Path], sources: list[str], target: str, destination: dict[str, Path]
) -> None:
    directory = target.endswith("/") or len(sources) > 1
    target = posixpath.normpath(target)
    directory = directory or any(key.startswith(target.rstrip("/") + "/") for key in destination)
    for source in sources:
        source = source.rstrip("/") or "."
        if ".." in PurePosixPath(source).parts:
            raise ValueError("COPY source escapes its context")
        if source in files:
            name = posixpath.join(target, posixpath.basename(source)) if directory else target
            destination[name] = files[source]
            continue
        prefix = "" if source == "." else source.rstrip("/") + "/"
        children = {
            key[len(prefix) :]: value for key, value in files.items() if key.startswith(prefix)
        }
        if children:
            destination.update(
                {
                    posixpath.join(target, name.lstrip("/")): value
                    for name, value in children.items()
                }
            )
            continue
        pattern = PurePosixPath(source)
        for key, value in files.items():
            candidate = PurePosixPath(key)
            if len(candidate.parts) == len(pattern.parts) and candidate.match(source):
                destination[posixpath.join(target, candidate.name)] = value


def _available(source: Path | None) -> bool:
    return source is not None and source.is_file() and not source.is_symlink()


def command_errors(command: TestCommand, files: Mapping[str, Path]) -> list[str]:
    errors = []
    if command.kind == "script":
        return [
            "unstaged Docker test script: " + path
            for path in command.selectors
            if not _available(files.get(path))
        ]
    if command.kind == "discover":
        prefix = command.directory.rstrip("/") + "/"
        if not any(
            path.startswith(prefix)
            and fnmatch.fnmatch(posixpath.basename(path), command.pattern)
            and _available(source)
            for path, source in files.items()
        ):
            errors.append("empty Docker discovery: " + command.directory + "/" + command.pattern)
        return errors
    for selector in command.selectors:
        if command.kind == "pytest" or selector.endswith(".py"):
            path = location(selector.split("::", 1)[0], command.cwd)
            if not _available(files.get(path)) and not any(
                key.startswith(path.rstrip("/") + "/")
                and _available(source)
                and fnmatch.fnmatch(posixpath.basename(key), "test*.py")
                for key, source in files.items()
            ):
                errors.append("unstaged Docker test path: " + path)
            continue
        parts = selector.split(".")
        matches = [
            posixpath.join(root, *parts[:end]) + ".py"
            for root in (command.cwd, *command.pythonpath)
            for end in range(len(parts), 0, -1)
        ]
        if not any(_available(files.get(path)) for path in matches):
            errors.append("unstaged Docker test module: " + selector)
    return errors


def _environment(body: str, current: dict[str, str]) -> None:
    tokens = shlex.split(body)
    if tokens and "=" not in tokens[0]:
        tokens = [tokens[0] + "=" + " ".join(tokens[1:])]
    for token in tokens:
        name, separator, value = token.partition("=")
        if not separator:
            raise ValueError("unsupported Docker environment")
        try:
            current[name] = expand(value, current)
        except ValueError:
            current[name] = value


def _copy(body: str, current: Stage, pool: Mapping[str, Path], stages: Mapping[str, Stage]) -> None:
    options, text = flags(body)
    if options.keys() - {"from", "chmod", "chown", "link"}:
        raise ValueError("unsupported Docker COPY options")
    tokens = json.loads(text) if text.startswith("[") else shlex.split(text)
    if (
        not isinstance(tokens, list)
        or len(tokens) < 2
        or not all(isinstance(value, str) for value in tokens)
    ):
        raise ValueError("unparsed Docker COPY")
    values = [expand(value, current.environment) for value in tokens]
    source_files = pool
    if "from" in options:
        previous = stages.get(options["from"])
        source_files = previous.files if previous else {}
        values[:-1] = [location(value, "/") for value in values[:-1]]
    destination = location(values[-1], current.cwd)
    if values[-1].endswith("/"):
        destination += "/"
    copy_files(source_files, values[:-1], destination, current.files)


def _run(
    body: str,
    current: Stage,
    pool: Mapping[str, Path],
    stages: Mapping[str, Stage],
    commands: list[TestCommand] | None = None,
) -> list[str]:
    options, _text = flags(body)
    virtual = dict(current.files)
    mounted = []
    for key, value in options.items():
        if not key.startswith("mount:"):
            continue
        fields = dict(part.split("=", 1) for part in value.split(",") if "=" in part)
        target = fields.get("target", fields.get("dst", fields.get("destination")))
        if target is None:
            raise ValueError("Docker mount requires an explicit target")
        target = location(expand(target, current.environment), current.cwd)
        mounted.append(target)
        virtual = {
            path: source
            for path, source in virtual.items()
            if path != target and not path.startswith(target.rstrip("/") + "/")
        }
        if fields.get("type", "bind") == "bind":
            source_pool = (
                stages.get(fields.get("from", ""), Stage()).files if "from" in fields else pool
            )
            source = fields.get("source", fields.get("src", "."))
            if "from" in fields:
                source = location(source, "/")
            copy_files(source_pool, [source], target, virtual)
    errors = []
    for command in run_commands(body, current.cwd, current.environment):
        if command.kind == "remove":
            for target in command.selectors:
                if any(
                    target == path or target.startswith(path.rstrip("/") + "/") for path in mounted
                ):
                    raise ValueError("unmodeled mutation of a validation mount")
                for mapping in (current.files, virtual):
                    for path in list(mapping):
                        if path == target or path.startswith(target.rstrip("/") + "/"):
                            del mapping[path]
        else:
            if commands is not None:
                commands.append(command)
            errors.extend(command_errors(command, virtual))
    return errors


def resolve_recipe(
    dockerfile: str,
    context: str,
    staged: Mapping[str, Path],
    commands: list[TestCommand] | None = None,
) -> list[str]:
    pool = {
        key[len(context) + 1 :]: value
        for key, value in staged.items()
        if key.startswith(context + "/")
    }
    stages: dict[str, Stage] = {}
    current = Stage()
    stage_index = 0
    errors = []
    for instruction, body in instructions(dockerfile):
        if instruction == "FROM":
            _options, text = flags(body)
            parts = shlex.split(text)
            if not parts:
                raise ValueError("missing Docker base image")
            inherited = stages.get(parts[0], Stage())
            current = Stage(dict(inherited.files), inherited.cwd, dict(inherited.environment))
            stages[str(stage_index)] = current
            stage_index += 1
            if len(parts) == 3 and parts[1].upper() == "AS":
                stages[parts[2]] = current
        elif instruction == "ENV":
            _environment(body, current.environment)
        elif instruction == "WORKDIR":
            current.cwd = location(expand(body, current.environment), current.cwd)
        elif instruction == "COPY":
            _copy(body, current, pool, stages)
        elif instruction == "ADD":
            raise ValueError("ADD is not qualified for validation source staging")
        elif instruction == "SHELL":
            shell = json.loads(body)
            if (
                not isinstance(shell, list)
                or len(shell) != 2
                or posixpath.basename(shell[0]) not in {"sh", "bash"}
                or shell[1] != "-c"
            ):
                raise ValueError("unsupported Docker validation shell")
        elif instruction == "RUN":
            errors.extend(_run(body, current, pool, stages, commands))
    return errors
