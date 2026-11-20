"""Opt-in user display lookup with an explicit origin and cookie allowlist."""

from dataclasses import dataclass
from http.client import HTTPConnection, HTTPSConnection, HTTPException
from http.cookies import CookieError, SimpleCookie
import json
from urllib.parse import urlsplit


@dataclass(frozen=True)
class IdentityLookup:
    origin: str
    cookie_names: tuple[str, ...]

    def __post_init__(self) -> None:
        parsed = urlsplit(self.origin)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or any(c in self.origin for c in "?#\\")
            or any(ord(c) <= 32 or ord(c) == 127 for c in self.origin)
            or parsed.scheme == "http"
            and parsed.hostname not in ("127.0.0.1", "::1", "localhost")
            or not self.cookie_names
            or len(set(self.cookie_names)) != len(self.cookie_names)
            or any(
                not name
                or any(
                    c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
                    for c in name
                )
                for name in self.cookie_names
            )
        ):
            raise ValueError(
                "identity lookup needs an HTTPS or loopback origin and exact cookie names"
            )
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError("invalid identity lookup port")

    def __call__(self, cookie_header: str) -> dict[str, str] | None:
        jar: SimpleCookie = SimpleCookie()
        try:
            jar.load(cookie_header)
        except CookieError:
            return None
        selected = [jar[name].OutputString() for name in self.cookie_names if name in jar]
        if not selected:
            return None
        parsed = urlsplit(self.origin)
        connection_type = HTTPSConnection if parsed.scheme == "https" else HTTPConnection
        connection = connection_type(parsed.hostname or "", parsed.port, timeout=2)
        try:
            connection.request("GET", "/api/me", headers={"Cookie": "; ".join(selected)})
            response = connection.getresponse()
            body = response.read(4097)
            if response.status != 200 or len(body) > 4096:
                return None
            value = json.loads(body)
            user = value.get("user") if type(value) is dict else None
            if type(user) is not dict or any(
                type(user.get(key)) is not str for key in ("id", "name")
            ):
                return None
            return {"id": user["id"], "name": user["name"]}
        except (OSError, ValueError, HTTPException):
            return None
        finally:
            connection.close()
