"""Compatibility entry point; implementation lives in duranki_server.gateway.owned_tls_sender_transport."""
import sys as _sys
from importlib import import_module as _import_module
_runtime = _import_module('duranki_server.gateway.owned_tls_sender_transport')
_sys.modules[__name__] = _runtime
globals().update(vars(_runtime))
