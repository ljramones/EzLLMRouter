"""Source-checkout bridge for the logger copied into the isolated worker."""

from ezllmrouter_server.observability import configure_logging, log_failure

__all__ = ["configure_logging", "log_failure"]
