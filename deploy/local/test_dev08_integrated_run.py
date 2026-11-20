"""Pre-Docker regression for one-use DEV-08 resource collision checks."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location(
    "dev08_integrated_run", HERE / "dev08_integrated_run.py"
)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class CollisionOutputTests(unittest.TestCase):
    def test_actual_run01_missing_volume(self):
        name = "ezllmrouter-dev08-integrated-20261021-01-link"
        self.assertTrue(
            runner.absent_resource(
                "Error response from daemon: get " + name + ": no such volume\n", name
            )
        )

    def test_missing_container_variants(self):
        name = "ezllmrouter-dev08-integrated-20261021-02-worker"
        self.assertTrue(runner.absent_resource("Error: No such object: " + name, name))
        self.assertTrue(runner.absent_resource("Error: no such container: " + name, name))

    def test_access_error_and_other_resource_remain_fatal(self):
        name = "ezllmrouter-dev08-integrated-20261021-02-link"
        self.assertFalse(runner.absent_resource("permission denied", name))
        self.assertFalse(runner.absent_resource("Cannot connect to Docker daemon", name))
        self.assertFalse(runner.absent_resource("no such volume: unrelated", name))


if __name__ == "__main__":
    unittest.main()
