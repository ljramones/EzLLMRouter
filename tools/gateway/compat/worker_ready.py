"""Compatibility entry point; implementation lives in duranki_server.gateway.worker_ready."""
import sys as _sys
from importlib import import_module as _import_module
_runtime = _import_module('duranki_server.gateway.worker_ready')
if __name__ == "__main__":
    _runtime.main()
else:
    _sys.modules[__name__] = _runtime
    globals().update(vars(_runtime))
