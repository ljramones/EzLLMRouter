"""Interpreter entry point installed before regression child code, even with -I/-S."""

import sys

# -S children have not imported stdlib operator yet; tools/operator must never
# shadow it while the guard itself starts.
if not sys.flags.isolated and sys.path and sys.path[0] == __file__.rsplit("/", 1)[0]:
    sys.path.pop(0)

from contextlib import ExitStack
import importlib.util
import os
from pathlib import Path
import runpy
import types


def main():
    arguments = sys.argv[2:]
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "_ezllmrouter_test_network", root / "tools/test_network.py"
    )
    network = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = network
    spec.loader.exec_module(network)
    if not sys.flags.isolated:
        # The wrapper's own directory must not leak into an isolated source-copy
        # check; restore the target's ordinary -c/-m/script import semantics.
        if sys.path and sys.path[0] == str(root / "tools"):
            sys.path.pop(0)
        target = arguments[0] if arguments else "-"
        sys.path.insert(
            0,
            str(Path(target).resolve().parent)
            if target not in {"-c", "-m", "-", "--"}
            else os.getcwd(),
        )
    with ExitStack() as stack:
        output = os.environ.get("EZLLMROUTER_TEST_COVERAGE")
        if output:
            coverage_spec = importlib.util.spec_from_file_location(
                "_ezllmrouter_test_coverage", root / "tools/test_coverage.py"
            )
            coverage = importlib.util.module_from_spec(coverage_spec)
            coverage_spec.loader.exec_module(coverage)
            stack.enter_context(coverage.LineCoverage(output))
        network.block_network(
            stack, loopback=os.environ.get("EZLLMROUTER_TEST_NETWORK") == "loopback"
        )
        if arguments and arguments[0] == "-m":
            module = arguments[1]
            sys.argv = arguments[1:]
            runpy.run_module(module, run_name="__main__", alter_sys=True)
        elif arguments and arguments[0] not in {"-c", "-", "--"}:
            sys.argv = arguments
            runpy.run_path(arguments[0], run_name="__main__")
        else:
            source = arguments[1] if arguments and arguments[0] == "-c" else sys.stdin.read()
            sys.argv = (
                ["-c", *arguments[2:]]
                if arguments and arguments[0] == "-c"
                else ["-", *arguments[1:]]
            )
            module = types.ModuleType("__main__")
            module.__dict__.update(__builtins__=__builtins__, __package__=None, __spec__=None)
            sys.modules["__main__"] = module
            exec(compile(source, "<string>", "exec"), module.__dict__)


if __name__ == "__main__":
    main()
