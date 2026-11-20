"""One bounded, non-retrying operator transport for local command tools."""

import http.client
import json


class OperatorSession:
    def __init__(self, password, port=8780, timeout=10):
        self._password, self.port, self.timeout = password, port, timeout
        self.cookie = None
        self.csrf = None

    def __repr__(self):
        return f"{type(self).__name__}(port={self.port})"

    def request(self, method, path, body=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=self.timeout)
        headers = {"Host": f"127.0.0.1:{self.port}", "Origin": f"http://127.0.0.1:{self.port}"}
        if self.cookie:
            headers["Cookie"] = self.cookie
        if method not in ("GET", "HEAD") and self.csrf:
            headers["X-EzLLMRouter-CSRF"] = self.csrf
        raw = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            raw = json.dumps(body, separators=(",", ":"), allow_nan=False).encode()
        try:
            connection.request(method, path, raw, headers)
            response = connection.getresponse()
            data = response.read(16 * 1024 * 1024 + 1)
            if len(data) > 16 * 1024 * 1024:
                raise ValueError("operator response limit exceeded")
            value = json.loads(data)
            if type(value) is not dict:
                raise ValueError("invalid operator response")
            cookie = response.getheader("Set-Cookie")
            if not 200 <= response.status < 300:
                raise RuntimeError(f"operator request failed: HTTP {response.status}")
            if path == "/operator/v1/login":
                if not cookie or type(value.get("csrf")) is not str:
                    raise ValueError("operator login omitted its session")
                self.cookie, self.csrf = cookie.split(";", 1)[0], value["csrf"]
            return {"status": response.status, "cookie": cookie, "body": value}
        finally:
            connection.close()

    def call(self, method, path, body=None):
        return self.request(method, path, body)["body"]

    def login(self):
        return self.call("POST", "/operator/v1/login", {"password": self._password})
