"""Independent final-byte/control comparison for the fixed DEV-12 profile."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math

from ezllmrouter_server.successor_contract import classify_request
from ezllmrouter_server.successor_plan import plan_valid
from .guard import GuardRejected


def check_synthetic_request(request, invocation, body):
    plan = invocation.plan
    descriptor = plan["execution_descriptor"]
    projection = invocation.projection
    admitted = projection["request"]
    origin = projection["origin"]
    if classify_request(admitted, projection["trusted_context"]) != "ACCEPT" or not plan_valid(
        plan,
        admitted,
        plan["work_digest"],
        plan["admission_snapshot_digest"],
        projection["trusted_context"]["identity"]["charging_owner_id"],
    ):
        raise GuardRejected()
    if (
        request.method != descriptor["method"]
        or request.method != "POST"
        or request.url.scheme != "https"
        or request.url.host != descriptor["host"]
        or str(request.url) != origin + descriptor["route"]
        or descriptor["transport"] != "trusted_sender_tls@1"
        or descriptor["content_type"] != "application/json"
        or descriptor["timeout_ms"] != 5000
        or len(body) > descriptor["max_request_bytes"]
    ):
        raise GuardRejected()
    headers = request.headers
    if (
        headers.get("host") != request.url.netloc.decode()
        or headers.get("content-type") != descriptor["content_type"]
        or headers.get("authorization") != "Bearer " + invocation.provider_key
        or headers.get("x-ezllmrouter-attempt") != invocation.attempt_id
        or (
            headers.get("content-length") is not None
            and headers["content-length"] != str(len(body))
        )
        or any(key in headers for key in ("proxy-authorization", "cookie", "idempotency-key"))
    ):
        raise GuardRejected()
    allowed = {
        "host",
        "content-type",
        "authorization",
        "content-length",
        "accept",
        "accept-encoding",
        "user-agent",
        "connection",
        "x-ezllmrouter-attempt",
    }
    if any(key not in allowed for key in headers):
        raise GuardRejected()
    timeout = request.extensions.get("timeout")
    phases = {"connect", "read", "write", "pool"}
    if (
        type(timeout) is not dict
        or set(timeout) != phases
        or any(
            type(value) not in (int, float) or not math.isfinite(value) or value != 5
            for value in timeout.values()
        )
    ):
        raise GuardRejected()
    try:
        actual = json.loads(body.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise GuardRejected() from exc
    if admitted["operation"]["type"] == "embedding.create":
        expected = {
            "operation": "embedding.create@1",
            "configuration_ref": admitted["requested_configuration_ref"],
            "role": admitted["input"]["role"],
            "profile": admitted["input"]["profile"],
            "items": admitted["input"]["items"],
        }
    else:
        data = admitted["input"]
        expected = {
            "operation": "rerank@1",
            "configuration_ref": admitted["requested_configuration_ref"],
            "query": data["query"],
            "ranking_profile_id": data["ranking_profile_id"],
            "corpus_version": data["corpus_version"],
            "index_version": data["index_version"],
            "candidates": data["candidates"],
            "top_k": data["top_k"],
        }
    expected_bytes = json.dumps(
        expected, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    if actual != expected or body != expected_bytes:
        raise GuardRejected()
    return {
        "attempt_id": invocation.attempt_id,
        "plan_id": plan["plan_id"],
        "work_digest": plan["work_digest"],
        "method": request.method,
        "host": descriptor["host"],
        "route": descriptor["route"],
        "transport": descriptor["transport"],
        "timeout_ms": descriptor["timeout_ms"],
        "verified_timeout_components_ms": {phase: 5000 for phase in sorted(phases)},
        "body_sha256": hashlib.sha256(body).hexdigest(),
        "body_bytes": len(body),
        "committed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
