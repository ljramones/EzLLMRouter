"""local_connectors local connector http domain; entry points remain on the facade."""

from __future__ import annotations


def allowed_address(value):
    from ezllmrouter_server import local_connectors as _api

    try:
        address = _api.ipaddress.ip_address(value)
        if isinstance(address, _api.ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        return any(
            address.version == network.version and address in network for network in _api.NETWORKS
        )
    except ValueError:
        return False


def normalize_url(value, kind="openai_compatible"):
    from ezllmrouter_server import local_connectors as _api

    if type(value) is not str or not value.strip() or len(value) > 512:
        raise _api.ConnectorError("INVALID_SERVER_URL")
    value = value.strip()
    if any(ord(char) < 33 for char in value) or "\\" in value:
        raise _api.ConnectorError("INVALID_SERVER_URL")
    try:
        url = _api.urlsplit(value)
        port = url.port
        if (
            url.scheme not in ("http", "https")
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or url.query
            or url.fragment
            or (port is not None and not 1 <= port <= 65535)
            or "%" in url.hostname
        ):
            raise ValueError()
        host = url.hostname.encode("idna").decode("ascii").lower()
        try:
            _api.ipaddress.ip_address(host)
        except ValueError as caught_error:
            if any(char not in "abcdefghijklmnopqrstuvwxyz0123456789.-_" for char in host):
                raise ValueError() from caught_error
        else:
            if not _api.allowed_address(host):
                raise _api.ConnectorError("LOCAL_ADDRESS_REQUIRED")
        path = url.path.rstrip("/")
        if path not in (("",) if kind == "ollama" else ("", "/v1")):
            raise _api.ConnectorError("USE_SERVER_ORIGIN_OR_V1")
        authority = "[" + host + "]" if ":" in host else host
        if port is not None:
            authority += ":" + str(port)
        return _api.urlunsplit((url.scheme, authority, path, "", ""))
    except (ValueError, UnicodeError) as exc:
        if isinstance(exc, _api.ConnectorError):
            raise
        raise _api.ConnectorError("INVALID_SERVER_URL") from exc


def _pairs(items):
    from ezllmrouter_server import local_connectors as _api

    try:
        return _api.unique_pairs(items)
    except ValueError as exc:
        raise _api.ConnectorError("INVALID_SERVER_RESPONSE", 502) from exc


def _reject_constant(_value):
    from ezllmrouter_server import local_connectors as _api

    raise _api.ConnectorError("INVALID_SERVER_RESPONSE", 502)


def _read_json(base_url, path, api_key, *, timeout=3):
    """GET one fixed inventory path, with pinned local DNS and a bounded body."""
    from ezllmrouter_server import local_connectors as _api

    if path not in _api.ROUTES:
        raise _api.ConnectorError("INVALID_DISCOVERY_PATH")
    url = _api.urlsplit(_api.normalize_url(base_url))
    host, port = url.hostname, url.port or (443 if url.scheme == "https" else 80)
    deadline = _api.time.monotonic() + timeout
    raw = stream = None
    try:
        addresses = _api.socket.getaddrinfo(host, port, type=_api.socket.SOCK_STREAM)
        if not addresses or any(not _api.allowed_address(item[4][0]) for item in addresses):
            raise _api.ConnectorError("LOCAL_ADDRESS_REQUIRED")
        addresses = sorted(addresses, key=lambda item: item[0] != _api.socket.AF_INET)
        last_error = None
        for family, socktype, protocol, _, address in addresses[:8]:
            remaining = deadline - _api.time.monotonic()
            if remaining <= 0:
                raise TimeoutError()
            raw = _api.socket.socket(family, socktype, protocol)
            raw.settimeout(remaining)
            try:
                raw.connect(address)
                break
            except OSError as exc:
                last_error = exc
                raw.close()
                raw = None
        if raw is None:
            raise last_error or OSError()
        stream = raw
        if url.scheme == "https":
            stream = _api.ssl.create_default_context().wrap_socket(raw, server_hostname=host)
        remaining = deadline - _api.time.monotonic()
        if remaining <= 0:
            raise TimeoutError()
        stream.settimeout(remaining)
        authority = ("[" + host + "]") if ":" in host else host
        if port != (443 if url.scheme == "https" else 80):
            authority += ":" + str(port)
        request = (
            f"GET {path} HTTP/1.1\r\nHost: {authority}\r\nAccept: application/json\r\n"
            "Accept-Encoding: identity\r\nConnection: close\r\n"
        )
        if api_key:
            request += "Authorization: Bearer " + api_key + "\r\n"
        stream.sendall((request + "\r\n").encode("ascii"))
        response = _api.http.client.HTTPResponse(stream)
        response.begin()
        if 300 <= response.status <= 399:
            raise _api.ConnectorError("REDIRECT_NOT_ALLOWED", 502)
        if response.status in (401, 403):
            raise _api.ConnectorError("SERVER_AUTHENTICATION_REQUIRED", 502)
        if response.status == 404:
            raise _api.ConnectorError("DISCOVERY_ENDPOINT_NOT_FOUND", 502)
        if response.status == 429:
            raise _api.ConnectorError("SERVER_RATE_LIMITED", 502)
        if response.status != 200:
            raise _api.ConnectorError("SERVER_UNAVAILABLE", 502)
        content_type = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
        if not (
            content_type == "application/json"
            or content_type.startswith("application/")
            and content_type.endswith("+json")
        ):
            raise _api.ConnectorError("INVALID_SERVER_RESPONSE", 502)
        if response.getheader("Content-Encoding", "identity").lower() != "identity":
            raise _api.ConnectorError("COMPRESSED_RESPONSE_NOT_SUPPORTED", 502)
        if response.length is not None and response.length > _api.MAX_RESPONSE:
            raise _api.ConnectorError("SERVER_RESPONSE_TOO_LARGE", 502)
        data = bytearray()
        while True:
            remaining = deadline - _api.time.monotonic()
            if remaining <= 0:
                raise TimeoutError()
            stream.settimeout(remaining)
            chunk = response.read1(min(16384, _api.MAX_RESPONSE + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > _api.MAX_RESPONSE:
                raise _api.ConnectorError("SERVER_RESPONSE_TOO_LARGE", 502)
        return _api.json.loads(
            data, object_pairs_hook=_api._pairs, parse_constant=_api._reject_constant
        )
    except _api.ConnectorError:
        raise
    except _api.socket.gaierror as exc:
        raise _api.ConnectorError("SERVER_NAME_NOT_RESOLVED", 502) from exc
    except (TimeoutError, _api.socket.timeout) as exc:
        raise _api.ConnectorError("SERVER_TIMEOUT", 502) from exc
    except _api.ssl.SSLError as exc:
        raise _api.ConnectorError("SERVER_TLS_FAILED", 502) from exc
    except (ValueError, UnicodeError, _api.http.client.HTTPException) as exc:
        raise _api.ConnectorError("INVALID_SERVER_RESPONSE", 502) from exc
    except PermissionError as exc:
        raise _api.ConnectorError("SERVER_CHECK_BLOCKED", 502) from exc
    except OSError as exc:
        raise _api.ConnectorError("SERVER_UNREACHABLE", 502) from exc
    finally:
        if stream is not None:
            stream.close()
        if raw is not None and raw is not stream:
            raw.close()
