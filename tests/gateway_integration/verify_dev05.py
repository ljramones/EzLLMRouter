"""Compatibility entry point; implementation lives in tools.gateway.evidence.verify_dev05."""

from pathlib import Path as _Path
import sys as _sys

_sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
from importlib import import_module as _import_module

_runtime = _import_module("tools.gateway.evidence.verify_dev05")
if __name__ == "__main__":
    _runtime.main()
else:
    _sys.modules[__name__] = _runtime
    globals().update(vars(_runtime))
