"""Frozen Linux LiteLLM 1.105.1 Responses discriminator. Run with Docker network=none."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import json
import os
import traceback

import httpx

if __package__:
    from worker.choice_b_worker import Worker
    from worker import choice_b_worker
else:
    from choice_b_worker import Worker
    import choice_b_worker


class CapturedRelay(choice_b_worker.RelayTransport):
    requests = []

    async def handle_async_request(self, request):
        raw = await request.aread()
        self.requests.append(
            {
                "method": request.method,
                "url": str(request.url),
                "headers": dict(request.headers),
                "body": json.loads(raw),
                "timeout": request.extensions.get("timeout"),
            }
        )
        # Deliberate provider rejection: no generation or second request is needed
        # to establish the pinned SDK's final request shape and retry count.
        return httpx.Response(
            400,
            json={
                "error": {
                    "message": "controlled stop",
                    "type": "invalid_request_error",
                    "code": "controlled_stop",
                }
            },
            request=request,
        )


def main():
    if os.environ.get("EZLLMROUTER_DEV_TOKEN") or os.environ.get("EZLLMROUTER_DEV04_PROVIDER_KEY"):
        raise RuntimeError("trusted credentials present in worker target check")
    choice_b_worker.RelayTransport = CapturedRelay
    worker = Worker()
    body = {
        "model": "openai/test-response-model",
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": "Answer briefly."}]},
            {"role": "user", "content": [{"type": "input_text", "text": "Hi"}]},
        ],
        "max_output_tokens": 32,
        "temperature": 0,
        "store": False,
        "stream": False,
        "api_base": "https://api.openai.com/v1",
        "timeout": 3.0,
        "max_retries": 0,
    }
    envelope = {
        "kind": "selected_request",
        "route": "responses",
        "timeout_ms": 3000,
        "deadline": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(),
        "attempt_id": "attempt.dev08.target",
        "prepared_b64": base64.b64encode(json.dumps(body, separators=(",", ":")).encode()).decode(),
    }
    failure = None
    try:
        worker.dispatch(envelope)
    except Exception as exc:
        # The controlled HTTP 400 is expected. If transformation failed before
        # the relay, report only exception types and source locations; exception
        # messages can contain request data or credentials.
        chain = []
        cursor = exc
        while cursor is not None and len(chain) < 4:
            chain.append(type(cursor).__name__)
            cursor = cursor.__cause__ or cursor.__context__
        frames = traceback.extract_tb(exc.__traceback__)
        failure = {
            "exception_types": chain,
            "frames": [
                {
                    "file": os.path.basename(frame.filename),
                    "function": frame.name,
                    "line": frame.lineno,
                }
                for frame in frames[-8:]
            ],
        }
    rows = CapturedRelay.requests
    if len(rows) != 1:
        raise AssertionError(
            "frozen Responses transformation did not produce one final HTTP request: "
            + json.dumps({"captured_requests": len(rows), "failure": failure}, sort_keys=True)
        )
    row = rows[0]
    if row["method"] != "POST" or row["url"] != "https://api.openai.com/v1/responses":
        raise AssertionError("frozen Responses transformation selected wrong operation URL")
    if row["headers"].get("authorization") != "Bearer " + choice_b_worker.WORKER_KEY:
        raise AssertionError("worker did not use its placeholder credential")
    if row["headers"].get("x-ezllmrouter-attempt") != envelope["attempt_id"]:
        raise AssertionError("worker did not bind the selected final request to the attempt")
    payload = row["body"]
    expected = {k: v for k, v in body.items() if k not in ("api_base", "timeout", "max_retries")}
    expected["model"] = "test-response-model"
    if payload != expected:
        safe = {
            "expected_keys": sorted(expected),
            "actual_keys": sorted(payload),
            "expected_model": expected["model"],
            "actual_model": payload.get("model"),
            "expected_store": False,
            "actual_store": payload.get("store"),
            "expected_stream": False,
            "actual_stream": payload.get("stream"),
        }
        raise AssertionError(
            "frozen Responses transformation shape mismatch: " + json.dumps(safe, sort_keys=True)
        )
    print(
        json.dumps(
            {
                "kind": "DEV-08 frozen Responses worker discriminator",
                "status": "PASS",
                "requests": 1,
                "method": row["method"],
                "url": row["url"],
                "body_keys": sorted(payload),
                "placeholder_only": True,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
