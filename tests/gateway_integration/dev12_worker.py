"""Networkless DEV-12 synthetic adapter; prepares bytes but cannot send them."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import socketserver

from choice_b_wire import receive, send


def prepare(request, recipe):
    if (
        type(request) is not dict
        or type(recipe) is not dict
        or recipe.get("operation") != request.get("operation")
        or recipe.get("handling_profile") != "public-synthetic-retained@1"
        or recipe.get("timeout_ms") != 5000
    ):
        raise ValueError("invalid bounded synthetic recipe")
    operation = request["operation"]
    if operation == {"type": "embedding.create", "version": 1}:
        if (
            recipe.get("adapter_ref") != "adapter.embed.synthetic.v1"
            or recipe.get("route") != "/synthetic/v1/embeddings"
        ):
            raise ValueError("unregistered embedding adapter")
        body = {
            "operation": "embedding.create@1",
            "configuration_ref": request["requested_configuration_ref"],
            "role": request["input"]["role"],
            "profile": request["input"]["profile"],
            "items": request["input"]["items"],
        }
    elif operation == {"type": "rerank", "version": 1}:
        if (
            recipe.get("adapter_ref") != "adapter.rerank.synthetic.v1"
            or recipe.get("route") != "/synthetic/v1/rerank"
        ):
            raise ValueError("unregistered rerank adapter")
        body = {
            "operation": "rerank@1",
            "configuration_ref": request["requested_configuration_ref"],
            "query": request["input"]["query"],
            "ranking_profile_id": request["input"]["ranking_profile_id"],
            "corpus_version": request["input"]["corpus_version"],
            "index_version": request["input"]["index_version"],
            "candidates": request["input"]["candidates"],
            "top_k": request["input"]["top_k"],
        }
    else:
        raise ValueError("unsupported synthetic operation")
    raw = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    if not 0 < len(raw) <= 262144:
        raise ValueError("synthetic body size")
    return {
        "method": "POST",
        "host": "synthetic.invalid",
        "route": recipe["route"],
        "transport": "trusted_sender_tls@1",
        "content_type": "application/json",
        "timeout_ms": 5000,
        "body_b64": base64.b64encode(raw).decode(),
    }


class _Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = False


def main():
    if any(
        name in os.environ
        for name in ("EZLLMROUTER_DEV04_PROVIDER_KEY", "OPENAI_API_KEY", "EZLLMROUTER_DEV_TOKEN")
    ):
        raise RuntimeError("credential in networkless DEV-12 worker")
    link = Path(os.environ.get("EZLLMROUTER_DEV12_LINK", "/link"))
    path = link / "dev12-worker.sock"
    if path.exists() or path.is_symlink():
        raise RuntimeError("DEV-12 worker socket collision")

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            try:
                command = receive(self.request)
                if set(command) != {"kind", "request", "recipe"} or command["kind"] != "prepare":
                    raise ValueError("worker command")
                answer = prepare(command["request"], command["recipe"])
            except Exception as exc:
                answer = {"error_type": type(exc).__name__}
            send(self.request, answer)

    server = _Server(str(path), Handler)
    os.chmod(path, 0o600)
    server.serve_forever()


if __name__ == "__main__":
    main()
