"""Import the exact staged isolated worker package without importing LiteLLM."""

import atexit
from importlib import import_module
from pathlib import Path
import sys
import tempfile

from tools.gateway.worker_package import stage_worker

_temporary = tempfile.TemporaryDirectory(prefix="ezllmrouter-worker-package-")
atexit.register(_temporary.cleanup)
_directory = Path(_temporary.name)
stage_worker(Path(__file__).resolve().parents[1], _directory / "ezllmrouter_worker")
sys.path.insert(0, str(_directory))
runtime = import_module("ezllmrouter_worker.worker")
