"""Host-test entry point for the stdlib-only module staged in the isolated worker."""

from importlib import import_module
import sys

sys.modules[__name__] = import_module("ezllmrouter_server.runtime_resources")
