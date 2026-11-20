"""Common domain-error root, retaining established public codes and catch types."""


class ServerError(Exception):
    """A server domain rejected an operation or could not complete it."""


class RequestError(ServerError, ValueError):
    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


class RegistryConflict(ServerError, ValueError):
    """A persisted management operation or expected revision conflicts."""
