"""Compatibility entry point; implementation lives in ezllmrouter_server.gateway.dev12_guard."""

import sys as _sys
from importlib import import_module as _import_module

_runtime = _import_module("ezllmrouter_server.gateway.dev12_guard")
_sys.modules[__name__] = _runtime
globals().update(vars(_runtime))
