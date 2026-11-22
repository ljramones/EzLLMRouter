"""Accidental-network guards for regression processes and their Python/Node children."""

from contextlib import ExitStack
from collections.abc import Mapping
import ipaddress
import os
from pathlib import Path
import shlex
import socket
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
CHILD = ROOT / "tools/test_child.py"
NODE = ROOT / "tools/test_network.cjs"
UNIX_FAMILY = getattr(socket, "AF_UNIX", -1)


def denied(*_args, **_kwargs):
    raise AssertionError("network/socket operation in the offline regression suite")


def local(host):
    try:
        value = host.decode("ascii") if isinstance(host, bytes) else host
        return (
            value == "localhost"
            or isinstance(value, str)
            and ipaddress.ip_address(value).is_loopback
        )
    except (ValueError, UnicodeError):
        return False


def python_command(command):
    """Preserve startup flags, including -I/-S, while guarding the target code."""
    if str(CHILD) in command:
        return command
    index = 1
    while (
        index < len(command)
        and command[index].startswith("-")
        and command[index] not in ("-c", "-m", "-", "--")
    ):
        if command[index] in ("-W", "-X"):
            index += 1
        index += 1
    return command[:index] + [str(CHILD), "--"] + command[index:]


def child_environment(
    environment: Mapping[str, str] | None = None, *, loopback: bool = False
) -> dict[str, str]:
    result = dict(os.environ if environment is None else environment)
    result["EZLLMROUTER_TEST_NETWORK"] = "loopback" if loopback else "offline"
    require = "--require=" + NODE.as_posix()
    options = shlex.split(result.get("NODE_OPTIONS", ""))
    if require not in options:
        options.insert(0, require)
    result["NODE_OPTIONS"] = shlex.join(options)
    for key in (
        "EZLLMROUTER_TEST_COVERAGE",
        "EZLLMROUTER_TEST_HEALTH",
        "NODE_V8_COVERAGE",
        "EZLLMROUTER_JS_COVERAGE",
        "EZLLMROUTER_LOCK_AUDIT",
    ):
        if key in os.environ:
            result[key] = os.environ[key]
    return result


def process_command(command):
    if not isinstance(command, (list, tuple)) or not command:
        raise AssertionError("regression subprocesses require an argument list")
    command = [os.fsdecode(value) for value in command]
    program = Path(command[0]).name
    if Path(program).suffix.lower() in {".exe", ".cmd"}:
        program = Path(program).stem
    if program.startswith("python") or Path(command[0]) == Path(sys.executable):
        return python_command(command)
    if program in {"node", "nodejs"}:
        return command
    if program == "git":
        index = 1
        while index < len(command) and command[index].startswith("-"):
            index += 2 if command[index] in {"-C", "-c", "--git-dir", "--work-tree"} else 1
        if command[index:] in (
            ["rev-list", "--objects", "--all", "--no-object-names"],
            ["cat-file", "--batch-check"],
            ["cat-file", "--batch"],
        ):
            return command
        if index < len(command) and command[index] in {
            "init",
            "add",
            "commit",
            "status",
            "diff",
            "show",
            "rev-parse",
            "ls-files",
            "hash-object",
        }:
            return command
    if (
        program == "openssl"
        and len(command) > 1
        and command[1] in {"req", "x509", "verify", "version", "pkey", "rsa"}
    ):
        return command
    if (
        program in {"npm", "npm-cli.js"}
        and "--offline" in command
        and "--ignore-scripts" in command
    ):
        return command
    if program == "bash":
        if len(command) > 1 and command[1] == "-n":
            return command
        # Existing offline exit-code fixture sources definitions, overrides capture,
        # and never starts a container. No arbitrary shell commands are accepted.
        if (
            len(command) == 6
            and command[1] == "-c"
            and command[4] == str(ROOT / "tools/gateway/evidence/dev05_steps.sh")
        ):
            expected = 'source "$1"; run_dir=$2; started=0; built_images=(); capture() { printf "synthetic capture failure\\n" >&2; return 2; }; finish_dev05 7'
            if command[2] == expected:
                return command
        if (
            len(command) == 9
            and command[1] == "-c"
            and command[3] == "bash"
            and command[4] == str(ROOT / "tools/gateway/evidence/dev05_steps.sh")
            and command[7] == sys.executable
            and command[8] == str(ROOT / "tools/gateway/evidence/capture_runtime.py")
        ):
            expected = (
                'source "$1"; run_dir=$2; result_dir=$3; capture_tool=$4; '
                "capture_script=$5; python_tool=/usr/bin/true; started=1; built_images=(); "
                'compose() { if [[ "$1" == logs && "$*" == *worker_choice_b* ]]; '
                'then printf "synthetic worker startup failure\\n"; fi; }; '
                'capture() { "$capture_tool" -I -B "$capture_script" '
                '"$run_dir" "$result_dir" DEV-05; }; '
                "finish_dev05 1"
            )
            if command[2] == expected:
                # The audited shell's only Python consumer must enter the same
                # guard as ordinary Popen children; environment hooks cannot
                # guard Python's isolated (-I) startup.
                command[2] = expected.replace(
                    "capture_script=$5;", "capture_script=$5; guard_script=$6;"
                ).replace('"$capture_script"', '"$guard_script" -- "$capture_script"')
                return [*command, str(CHILD)]
    raise AssertionError("unapproved regression subprocess: " + program)


def block_network(stack: ExitStack, *, loopback=False):
    def guarded(operation):
        def call(connection, address, *args, **kwargs):
            if connection.family != UNIX_FAMILY and (
                not loopback or not isinstance(address, tuple) or not local(address[0])
            ):
                denied()
            return operation(connection, address, *args, **kwargs)

        return call

    resolve = socket.getaddrinfo

    def local_resolve(host, *args, **kwargs):
        if not local(host):
            denied()
        addresses = resolve(host, *args, **kwargs)
        if any(not local(address[4][0]) for address in addresses):
            denied()
        return addresses

    def local_fqdn(host=""):
        # HTTPServer names its bound address during server_bind. Keep this
        # metadata local instead of performing the usual reverse-DNS lookup.
        if not local(host):
            denied()
        return host.decode("ascii") if isinstance(host, bytes) else host

    for attribute in ("connect", "connect_ex", "bind"):
        operation = guarded(getattr(socket.socket, attribute)) if loopback else denied
        stack.enter_context(patch.object(socket.socket, attribute, operation))
    original_sendto = socket.socket.sendto

    def sendto(connection, data, *args):
        address = args[-1]
        if connection.family != UNIX_FAMILY and (
            not loopback or not isinstance(address, tuple) or not local(address[0])
        ):
            denied()
        return original_sendto(connection, data, *args)

    stack.enter_context(patch.object(socket.socket, "sendto", sendto))
    if hasattr(socket.socket, "sendmsg"):
        original_sendmsg = socket.socket.sendmsg

        def sendmsg(connection, buffers, ancdata=(), flags=0, address=None):
            if connection.family != UNIX_FAMILY and (
                not loopback or not isinstance(address, tuple) or not local(address[0])
            ):
                denied()
            if address is None:
                return original_sendmsg(connection, buffers, ancdata, flags)
            return original_sendmsg(connection, buffers, ancdata, flags, address)

        stack.enter_context(patch.object(socket.socket, "sendmsg", sendmsg))
    stack.enter_context(patch.object(socket, "getaddrinfo", local_resolve if loopback else denied))
    stack.enter_context(patch.object(socket, "getfqdn", local_fqdn if loopback else denied))
    for name in ("gethostbyname", "gethostbyname_ex", "gethostbyaddr", "getnameinfo"):
        stack.enter_context(patch.object(socket, name, denied))
    original_popen = subprocess.Popen

    def popen(args, *values, **kwargs):
        if kwargs.get("shell"):
            raise AssertionError("shell=True is not allowed in offline regressions")
        kwargs["env"] = child_environment(kwargs.get("env"), loopback=loopback)
        return original_popen(process_command(args), *values, **kwargs)

    stack.enter_context(patch.object(subprocess, "Popen", popen))
