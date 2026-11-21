"""local_connectors local connector inventory domain; entry points remain on the facade."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast
from .records import Record

if TYPE_CHECKING:
    from .local_connectors import InventoryReader


def _text(value: object, secret: str, *, required: bool = False, limit: int = 240) -> str | None:
    from ezllmrouter_server import local_connectors as _api

    if value is None and not required:
        return None
    if (
        type(value) is not str
        or not value
        or len(value) > limit
        or any(ord(char) < 32 for char in value)
    ):
        raise _api.ConnectorError("INVALID_SERVER_RESPONSE", 502)
    if secret and secret in value:
        if required:
            raise _api.ConnectorError("INVALID_SERVER_RESPONSE", 502)
        return None
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise _api.ConnectorError("INVALID_SERVER_RESPONSE", 502) from exc
    return value


def _integer(value: object) -> int | None:
    from ezllmrouter_server import local_connectors as _api

    return value if type(value) is int and 0 <= value <= _api.MAX_SAFE_INTEGER else None


def discover(
    kind: str, base_url: str, api_key: str = "", *, read: InventoryReader | None = None
) -> Record:
    from ezllmrouter_server import local_connectors as _api

    read = read or _api._read_json
    base_url = _api.normalize_url(base_url, kind)
    spec = _api.KINDS[kind]
    value = read(base_url, "/api/tags" if spec["api"] == "ollama" else "/v1/models", api_key)
    rows = (
        value.get("models" if spec["api"] == "ollama" else "data") if type(value) is dict else None
    )
    if type(rows) is not list or any(type(row) is not dict for row in rows):
        raise _api.ConnectorError("INVALID_SERVER_RESPONSE", 502)
    result: Record = {
        "state": "observed",
        "models": [],
        "checked_at": _api.timestamp(),
        "complete": len(rows) <= _api.MAX_MODELS
        and not bool(cast(Record, value).get("has_more") or cast(Record, value).get("next_page")),
        "server_version": None,
        "loaded_inventory_available": False,
        "warnings": [],
    }
    seen = set()
    for row in rows[: _api.MAX_MODELS]:
        model_id = _api._text(
            (row.get("model") or row.get("name")) if spec["api"] == "ollama" else row.get("id"),
            api_key,
            required=True,
        )
        if model_id in seen:
            raise _api.ConnectorError("DUPLICATE_MODEL_ID", 502)
        seen.add(model_id)
        details = row.get("details") if type(row.get("details")) is dict else {}
        model: Record = {"id": model_id, "loaded": None}
        if spec["api"] == "ollama":
            model.update(
                size_bytes=_api._integer(row.get("size")),
                modified_at=_api._text(row.get("modified_at"), api_key),
                digest=_api._text(row.get("digest"), api_key),
                family=_api._text(details.get("family"), api_key),
                format=_api._text(details.get("format"), api_key),
                parameter_size=_api._text(details.get("parameter_size"), api_key),
                quantization=_api._text(details.get("quantization_level"), api_key),
            )
        else:
            model.update(
                owned_by=_api._text(row.get("owned_by"), api_key),
                context_window=_api._integer(row.get("max_model_len") or row.get("context_length")),
            )
        result["models"].append(model)
    if spec["api"] == "ollama":
        try:
            loaded = read(base_url, "/api/ps", api_key)
            if (
                type(loaded) is not dict
                or type(loaded.get("models")) is not list
                or len(loaded["models"]) > _api.MAX_MODELS
            ):
                raise _api.ConnectorError("INVALID_SERVER_RESPONSE", 502)
            loaded_models = {}
            for row in loaded["models"]:
                if type(row) is not dict:
                    raise _api.ConnectorError("INVALID_SERVER_RESPONSE", 502)
                model_id = _api._text(row.get("model") or row.get("name"), api_key, required=True)
                if model_id in loaded_models:
                    raise _api.ConnectorError("DUPLICATE_MODEL_ID", 502)
                loaded_models[model_id] = _api._integer(row.get("size_vram"))
            for model in result["models"]:
                model["loaded"] = model["id"] in loaded_models
                model["vram_bytes"] = loaded_models.get(model["id"])
            result["loaded_inventory_available"] = True
        except _api.ConnectorError as exc:
            result["warnings"].append({"operation": "loaded_models", "code": exc.code})
        try:
            version = read(base_url, "/api/version", api_key)
            result["server_version"] = _api._text(
                version.get("version") if type(version) is dict else None, api_key, required=True
            )
        except _api.ConnectorError as exc:
            result["warnings"].append({"operation": "server_version", "code": exc.code})
    return result
