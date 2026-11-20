"""Explicit operator exposure and browser-origin policy; forwarded headers confer no trust."""

from collections.abc import Collection
from dataclasses import dataclass
import ipaddress
from urllib.parse import urlsplit


def _local_authority(value: str) -> bool:
    parsed = urlsplit("http://" + value)
    if (
        parsed.netloc != value
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        return False
    _ = parsed.port
    if parsed.hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(parsed.hostname or "").is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class OperatorPolicy:
    hosts: frozenset[str]
    origins: frozenset[str]
    secure_cookies: bool

    @classmethod
    def build(
        cls,
        host: str,
        port: int,
        allowed_hosts: Collection[str] | None,
        *,
        unix_socket: bool,
        public_origin: str | None,
    ) -> "OperatorPolicy":
        if host != "127.0.0.1":
            raise ValueError("operator TCP binding must be loopback")
        if public_origin is not None:
            origin = urlsplit(public_origin)
            if (
                not unix_socket
                or origin.scheme != "https"
                or not origin.hostname
                or origin.path
                or origin.query
                or origin.fragment
                or origin.username is not None
                or origin.password is not None
                or public_origin != "https://" + origin.netloc
            ):
                raise ValueError("HTTPS operator origins require an explicit Unix proxy boundary")
            _ = origin.port
            hosts = frozenset(allowed_hosts or (origin.netloc,))
            if hosts != {origin.netloc}:
                raise ValueError("operator host must match the HTTPS public origin")
            return cls(hosts, frozenset((public_origin,)), True)
        hosts = frozenset(allowed_hosts or (f"127.0.0.1:{port}", f"localhost:{port}"))
        if not all(_local_authority(value) for value in hosts):
            raise ValueError("non-loopback operator hosts require an HTTPS public origin")
        return cls(hosts, frozenset("http://" + value for value in hosts), False)
