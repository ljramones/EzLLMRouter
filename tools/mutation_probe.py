"""One isolated test process; emit structured results before the parent classifies it."""

import importlib
import io
import json
import os
from pathlib import Path
import sys
import unittest


def main():
    selector, target, output = sys.argv[1:]
    destination = Path(output)
    os.environ["EZLLMROUTER_TEST_HEALTH"] = str(destination.parent / "health")
    os.environ["EZLLMROUTER_TEST_SEED"] = "20261120"
    os.environ["EZLLMROUTER_TEST_EXAMPLES"] = "48"
    result = {"format": "ezllmrouter.mutation-probe.v1", "valid": False}
    try:
        suite = unittest.defaultTestLoader.loadTestsFromName(selector)
        if unittest.defaultTestLoader.errors or not suite.countTestCases():
            raise ValueError("mutation selector did not load")
        package = importlib.import_module("ezllmrouter_server")
        root = Path.cwd()
        if not Path(package.__file__).resolve().is_relative_to(root / "server/src"):
            raise ValueError("mutation did not load the isolated server package")
        module = importlib.import_module(
            target.removeprefix("server/src/").removesuffix(".py").replace("/", ".")
        )
        if Path(module.__file__).resolve() != (root / target).resolve():
            raise ValueError("mutation target was not imported from its isolated copy")
        stream = io.StringIO()
        observed = unittest.TextTestRunner(stream=stream, verbosity=1).run(suite)
        print(stream.getvalue(), end="")
        result.update(
            valid=observed.testsRun > len(observed.skipped),
            tests_run=observed.testsRun,
            skipped=len(observed.skipped),
            failures=len(observed.failures),
            errors=len(observed.errors),
            passed=observed.wasSuccessful(),
        )
    except Exception as error:
        result["error_type"] = type(error).__name__
    finally:
        destination.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
