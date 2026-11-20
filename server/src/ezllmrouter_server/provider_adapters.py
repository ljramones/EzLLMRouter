"""Code-owned, versioned provider management protocols.

These probes are explicit administrator actions. They never generate model work.
The selected wire operation is fixed by the adapter, not by registry data.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import re
import socket
import ssl
from typing import Any, TypedDict, cast
from urllib.parse import quote, urlsplit


class ProbeError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Adapter(TypedDict):
    provider: str
    access: tuple[str, str] | None
    inventory: tuple[str, str] | None
    readiness: tuple[str, str] | None
    inference: str | None


ADAPTERS: dict[str, Adapter] = {
    "openai.responses.v1": {
        "provider": "openai",
        "access": ("GET", "/v1/models"),
        "inventory": ("GET", "/v1/models"),
        "readiness": None,
        "inference": "Responses text candidate · frozen target pending",
    },
    "anthropic.messages.2023-06-01": {
        "provider": "anthropic",
        "access": ("GET", "/v1/models"),
        "inventory": ("GET", "/v1/models"),
        "readiness": None,
        "inference": None,
    },
    "gemini.developer.v1beta": {
        "provider": "google",
        "access": ("GET", "/v1beta/models"),
        "inventory": ("GET", "/v1beta/models"),
        "readiness": None,
        "inference": None,
    },
    "vllm.openai-compatible.v1": {
        "provider": "vllm",
        "access": ("GET", "/v1/models"),
        "inventory": ("GET", "/v1/models"),
        "readiness": ("GET", "/health"),
        "inference": None,
    },
    "xai.responses.v1": {
        "provider": "xai",
        "access": ("GET", "/v1/models"),
        "inventory": ("GET", "/v1/models"),
        "readiness": None,
        "inference": None,
    },
    "deepseek.chat.v1": {
        "provider": "deepseek",
        "access": None,
        "inventory": None,
        "readiness": None,
        "inference": None,
    },
}
PROVIDERS = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google": "Google Gemini Developer API",
    "vllm": "vLLM private or lab",
    "xai": "xAI",
    "deepseek": "DeepSeek",
}
PUBLIC_HOSTS = {
    "openai": "api.openai.com",
    "anthropic": "api.anthropic.com",
    "google": "generativelanguage.googleapis.com",
    "xai": "api.x.ai",
    "deepseek": "api.deepseek.com",
}


def validate_settings(
    adapter_id: str, settings: dict[str, Any], *, controlled: bool = False
) -> str:
    if adapter_id not in ADAPTERS or type(settings) is not dict:
        raise ValueError("unsupported API adapter")
    provider = ADAPTERS[adapter_id]["provider"]
    required = {"origin", "location", "site"}
    optional = (
        {"project"} if provider == "openai" else {"workspace"} if provider == "anthropic" else set()
    )
    if provider == "vllm":
        optional = {"ca_pem", "engine_version"}
    elif controlled:
        optional |= {"ca_pem"}
    if not required <= set(settings) or set(settings) - required - optional:
        raise ValueError("invalid adapter settings")
    if settings["location"] not in ("commercial", "private_cloud", "office_lab"):
        raise ValueError("invalid hosting location")
    if provider != "vllm" and settings["location"] != "commercial":
        raise ValueError("commercial adapter requires commercial location")
    if provider == "vllm" and settings["location"] == "commercial":
        raise ValueError("vLLM requires private or lab location")
    if (
        type(settings["site"]) is not str
        or not 1 <= len(settings["site"]) <= 100
        or any(ord(c) < 32 for c in settings["site"])
    ):
        raise ValueError("invalid site")
    for key in optional - {"ca_pem"}:
        if key in settings and (
            type(settings[key]) is not str
            or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", settings[key])
        ):
            raise ValueError("invalid adapter scope")
    if "ca_pem" in settings and (
        type(settings["ca_pem"]) is not str
        or len(settings["ca_pem"]) > 8192
        or not settings["ca_pem"].startswith("-----BEGIN CERTIFICATE-----\n")
    ):
        raise ValueError("invalid certificate trust material")
    if type(settings["origin"]) is not str or len(settings["origin"]) > 512:
        raise ValueError("invalid HTTPS origin")
    url = urlsplit(settings["origin"])
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.path not in ("", "/")
        or url.query
        or url.fragment
        or not 1 <= (url.port or 443) <= 65535
        or ":" in url.hostname
        or (url.port not in (None, 443) and provider != "vllm" and not controlled)
    ):
        raise ValueError("invalid HTTPS origin")
    if not controlled and provider != "vllm" and url.hostname != PUBLIC_HOSTS[provider]:
        raise ValueError("commercial origin is not approved")
    if not controlled and provider == "vllm" and not settings.get("ca_pem"):
        raise ValueError("private TLS trust root required")
    return provider


def _allowed_ip(address: str, provider: str, *, controlled: bool) -> bool:
    ip = ipaddress.ip_address(address)
    if ip.is_loopback:
        return controlled or provider == "vllm"
    if ip.is_multicast or ip.is_unspecified or ip.is_link_local or ip.is_reserved:
        return False
    if ip == ipaddress.ip_address("169.254.169.254"):
        return False
    return controlled or provider == "vllm" or ip.is_global


def _headers(adapter_id: str, key: str | None, settings: dict[str, Any]) -> dict[str, str]:
    if not key or any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise ProbeError("credential_unavailable")
    if adapter_id.startswith("anthropic."):
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
        if settings.get("workspace"):
            # Workspace is metadata only until an authenticated workspace API is implemented.
            pass
        return headers
    if adapter_id.startswith("gemini."):
        return {"x-goog-api-key": key}
    headers = {"Authorization": "Bearer " + key}
    if adapter_id.startswith("openai.") and settings.get("project"):
        headers["OpenAI-Project"] = settings["project"]
    return headers


def _wire_get(
    settings: dict[str, Any],
    provider: str,
    path: str,
    headers: dict[str, str],
    *,
    timeout: float,
    controlled: bool,
) -> tuple[int, str, bytes]:
    url = urlsplit(settings["origin"])
    host, port = url.hostname, url.port or 443
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not addresses or any(
        not _allowed_ip(cast(str, item[4][0]), provider, controlled=controlled)
        for item in addresses
    ):
        raise ProbeError("destination_rejected")
    family, kind, protocol, _, address = sorted(
        addresses, key=lambda item: item[0] != socket.AF_INET
    )[0]
    try:
        context = ssl.create_default_context(cadata=settings.get("ca_pem"))
    except ValueError as exc:
        raise ProbeError("network_or_tls_failure") from exc
    raw = socket.socket(family, kind, protocol)
    try:
        raw.settimeout(timeout)
        raw.connect(address)
        with context.wrap_socket(raw, server_hostname=host) as tls:
            tls.settimeout(timeout)
            request = (
                "GET " + path + " HTTP/1.1\r\nHost: " + host + (f":{port}" if port != 443 else "")
            )
            request += "\r\nAccept: application/json\r\nConnection: close\r\n"
            for name, value in headers.items():
                request += name + ": " + value + "\r\n"
            tls.sendall((request + "\r\n").encode("ascii"))
            with http.client.HTTPResponse(tls) as response:
                response.begin()
                if response.length is not None and response.length > 262144:
                    raise ProbeError("response_too_large")
                data = response.read(262145)
                if len(data) > 262144:
                    raise ProbeError("response_too_large")
                return response.status, cast(str, response.getheader("Content-Type", "")), data
    finally:
        raw.close()


def _xai_bad_request_reason(content_type: str, data: bytes) -> str:
    """Classify documented key rejection without returning provider text or secret echoes."""
    if "application/json" not in content_type.lower():
        return "provider_rejected_request"
    try:
        body = json.loads(data)
    except (ValueError, UnicodeError):
        return "provider_rejected_request"
    if type(body) is not dict:
        return "provider_rejected_request"
    error = body.get("error")
    code = error.get("code") if type(error) is dict else body.get("code")
    message = (
        error.get("message")
        if type(error) is dict
        else error
        if type(error) is str
        else body.get("message")
    )
    if type(code) is str and code.lower().replace("-", "_") in (
        "invalid_api_key",
        "incorrect_api_key",
        "invalid_authentication",
    ):
        return "credential_rejected"
    if type(message) is str:
        lower = message.lower()
        if "api key" in lower and any(
            word in lower for word in ("incorrect", "invalid", "expired")
        ):
            return "credential_rejected"
    return "provider_rejected_request"


def probe(
    adapter_id: str,
    settings: dict[str, Any],
    credential: str | None,
    operation: str,
    *,
    timeout: float = 3,
    controlled: bool = False,
) -> dict[str, Any]:
    """Return a safe observation; no secret or raw response enters the result."""
    try:
        provider = validate_settings(adapter_id, settings, controlled=controlled)
    except (ValueError, TypeError):
        return {"state": "failed", "reason": "invalid_settings", "models": []}
    if operation not in ("access", "inventory", "readiness"):
        return {"state": "unsupported", "reason": "operation_not_implemented", "models": []}
    try:
        spec = ADAPTERS[adapter_id].get(operation)
        if spec is None:
            return {"state": "unsupported", "reason": "operation_not_implemented", "models": []}
        # These code-owned operation fields contain method/path pairs.
        spec = cast(tuple[str, str], spec)
        models: list[str] = []
        details: dict[str, dict[str, str]] = {}
        path, seen, pages = spec[1], set(), 0
        while True:
            try:
                status, content_type, data = _wire_get(
                    settings,
                    provider,
                    path,
                    _headers(adapter_id, credential, settings)
                    if operation in ("access", "inventory")
                    else {},
                    timeout=timeout,
                    controlled=controlled,
                )
                if status == 401:
                    raise ProbeError("credential_rejected")
                if status == 403:
                    raise ProbeError("access_forbidden")
                if status == 429:
                    raise ProbeError("rate_limited")
                if status == 400:
                    raise ProbeError(
                        _xai_bad_request_reason(content_type, data)
                        if provider == "xai"
                        else "provider_rejected_request"
                    )
                if status == 404:
                    raise ProbeError("discovery_not_supported")
                if status != 200:
                    raise ProbeError("provider_unavailable")
                if operation == "readiness":
                    return {
                        "state": "reachable",
                        "reason": "vllm_health_200_not_model_capacity",
                        "models": [],
                    }
                if "application/json" not in content_type.lower():
                    raise ProbeError("malformed_response")
                value = json.loads(data)
                if type(value) is not dict:
                    raise ProbeError("malformed_response")
                items = (
                    value.get("data")
                    if provider in ("openai", "anthropic", "xai", "vllm")
                    else value.get("models")
                )
                if type(items) is not list or len(items) > 1000:
                    raise ProbeError("malformed_response")
                page_ids = []
                for item in items:
                    field = "name" if provider == "google" else "id"
                    if type(item) is not dict or type(item.get(field)) is not str:
                        raise ProbeError("malformed_response")
                    identifier = item[field]
                    if not 1 <= len(identifier) <= 256 or any(ord(c) < 33 for c in identifier):
                        raise ProbeError("malformed_response")
                    page_ids.append(identifier)
                    display = item.get("display_name") or item.get("name") or identifier
                    details[identifier] = {
                        "id": identifier,
                        "name": display
                        if type(display) is str and len(display) <= 256
                        else identifier,
                    }
                models.extend(page_ids)
                pages += 1
                if operation == "access":
                    return {
                        "state": "observed",
                        "reason": "credential_accepted_for_model_listing_only",
                        "models": [],
                    }
                if provider == "anthropic" and value.get("has_more") is True:
                    token = value.get("last_id")
                    parameter = "after_id"
                elif provider == "google" and value.get("nextPageToken"):
                    token = value["nextPageToken"]
                    parameter = "pageToken"
                else:
                    return {
                        "state": "observed",
                        "reason": "inventory_not_inference_entitlement",
                        "models": sorted(set(models)),
                        "details": [details[key] for key in sorted(details)],
                        "has_more": False,
                        "pages": pages,
                    }
                if (
                    type(token) is not str
                    or not 1 <= len(token) <= 256
                    or any(ord(char) < 33 for char in token)
                    or token in seen
                ):
                    raise ProbeError("malformed_pagination")
                seen.add(token)
                if pages >= 10 or len(models) >= 5000:
                    return {
                        "state": "partial",
                        "reason": "inventory_page_limit",
                        "models": sorted(set(models)),
                        "details": [details[key] for key in sorted(details)],
                        "has_more": True,
                        "pages": pages,
                    }
                path = spec[1] + "?" + parameter + "=" + quote(token, safe="")
            except (
                ProbeError,
                socket.timeout,
                TimeoutError,
                ssl.SSLError,
                OSError,
                json.JSONDecodeError,
                UnicodeError,
                TypeError,
            ) as exc:
                if not models or operation != "inventory":
                    raise
                reason = (
                    exc.reason
                    if isinstance(exc, ProbeError)
                    else "timeout"
                    if isinstance(exc, (socket.timeout, TimeoutError))
                    else "network_or_tls_failure"
                    if isinstance(exc, (ssl.SSLError, OSError))
                    else "malformed_response"
                )
                return {
                    "state": "partial",
                    "reason": "later_page_" + reason,
                    "models": sorted(set(models)),
                    "details": [details[key] for key in sorted(details)],
                    "has_more": True,
                    "pages": pages,
                }
    except ProbeError as exc:
        return {"state": "failed", "reason": exc.reason, "models": []}
    except (socket.timeout, TimeoutError):
        return {"state": "failed", "reason": "timeout", "models": []}
    except (ssl.SSLError, OSError):
        return {"state": "failed", "reason": "network_or_tls_failure", "models": []}
    except (json.JSONDecodeError, UnicodeError, TypeError):
        return {"state": "failed", "reason": "malformed_response", "models": []}
