"""Explicit synthetic-only HTTPX transport, injected by service_main."""
import json
from urllib.parse import urlsplit
import hashlib

import httpx
from ezllmrouter_server.canonical import ContractError


class NativeSyntheticAdapter:
    def __init__(self, url: str, expected_host: str, fault=None):
        parsed = urlsplit(url)
        if parsed.scheme != "http" or parsed.hostname != expected_host or parsed.path != "/v1/chat/completions" or parsed.query:
            raise ValueError("synthetic destination mismatch")
        self.url = url
        self.fault = fault

    def prepare(self, body: dict) -> bytes:
        return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def describe(self, prepared: bytes, timeout_ms: int, destination: dict):
        if destination["endpoint"] != urlsplit(self.url).hostname:
            raise ValueError("destination drift")
        return {"method": "POST", "url": self.url, "content_type": "application/json",
                "content_length": len(prepared), "body_sha256": hashlib.sha256(prepared).hexdigest(),
                "timeout_ms": timeout_ms, "processing_region": destination["processing_region"]}

    def send(self, prepared: bytes, timeout_ms: int, expected: dict):
        if self.fault == "connection_loss":
            raise OSError("synthetic connection loss before or after transmission is ambiguous")
        transport = httpx.HTTPTransport(retries=0, trust_env=False)
        with httpx.Client(transport=transport, follow_redirects=False, trust_env=False,
                          timeout=httpx.Timeout(timeout_ms / 1000)) as client:
            request = httpx.Request("POST", self.url, content=prepared,
                                    headers={"Content-Type": "application/json",
                                             "Content-Length": str(len(prepared))})
            actual = self.describe(request.content, timeout_ms,
                                   {"endpoint": urlsplit(self.url).hostname,
                                    "processing_region": expected["processing_region"]})
            if (request.method != expected["method"] or str(request.url) != expected["url"] or
                request.headers.get("Content-Type") != expected["content_type"] or
                request.headers.get("Content-Length") != str(expected["content_length"]) or
                actual != expected):
                raise ContractError("FDC_REJECTED", 409)
            response = client.send(request)
            try:
                value = response.json()
            except ValueError:
                value = None
            return {"status": response.status_code, "body": value}
