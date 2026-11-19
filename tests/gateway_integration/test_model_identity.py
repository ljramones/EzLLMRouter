"""Public/private model mapping against actual DEV-04 configuration and packaged clients."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/src"))
sys.path.insert(0, str(ROOT / "tests/development_slice"))
sys.path.insert(0, str(ROOT / "tests/gateway_integration"))
sys.path.insert(0, str(ROOT / "tests/gateway_integration/inputs/cognitivedynamics_ezllmrouter_client-0.3.0-py3-none-any.whl"))

from ezllmrouter_client import EzLLMRouterClient, EzLLMRouterError
from ezllmrouter_server.core import Coordinator
from ezllmrouter_server.plans import PlanAuthority
from ezllmrouter_server.store import SQLiteStore
from ezllmrouter_server.gateway.proxy_recipe import (GatewayProxyRecipe, PROXY_MODEL, PUBLIC_MODEL,
                          public_destination, proxy_policy)


FIXTURE = json.loads((ROOT / "tests/development_slice/fixture.json").read_text())
REQUEST = json.loads((ROOT / "tests/development_slice/request.json").read_text())


class BoundAdapter:
    def __init__(self):
        self.sends = 0
        self.plan = None
        self.projection = None
        self.prepared = None

    def prepare(self, body):
        return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()

    def describe(self, prepared, timeout_ms, destination):
        from hashlib import sha256
        if destination != public_destination(FIXTURE):
            raise ValueError("public destination changed")
        return {"method": "POST", "url": "http://127.0.0.1:8767/v1/chat/completions",
                "content_type": "application/json", "content_length": len(prepared),
                "body_sha256": sha256(prepared).hexdigest(), "timeout_ms": timeout_ms,
                "processing_region": destination["processing_region"]}

    def send_with_context(self, prepared, timeout_ms, expected, context):
        from hashlib import sha256
        if self.describe(prepared, timeout_ms, context["plan"]["destination"]) != expected:
            raise ValueError("front request changed")
        self.plan = deepcopy(context["plan"])
        self.projection = deepcopy(context["projection"])
        self.prepared = json.loads(prepared)
        context["fresh_check"]()
        context["commit"]({"attempt_id": context["attempt_id"],
                           "plan_id": context["plan"]["plan_id"],
                           "work_digest": context["plan"]["work_digest"],
                           "body_sha256": sha256(prepared).hexdigest()})
        self.sends += 1
        return {"status": 200, "body": {"text": "Hello.", "finish_reason": "stop",
                                         "usage": {"input_tokens": 5, "output_tokens": 2}}}


class WireResponse:
    status_code = 200
    headers = {"EzLLMRouter-Contract-Version": "0.2"}

    def __init__(self, body):
        self.content = json.dumps(body, separators=(",", ":")).encode()


class WireTransport:
    def __init__(self, submit, status):
        self.responses = [WireResponse(submit), WireResponse(status)]

    def request(self, *_args, **_kwargs):
        return self.responses.pop(0)

    def close(self):
        pass


class ModelIdentityTests(unittest.TestCase):
    def test_actual_dev04_signed_public_identity_and_packaged_clients(self):
        with tempfile.TemporaryDirectory() as temp:
            store = SQLiteStore(Path(temp) / "store.sqlite")
            adapter = BoundAdapter()
            trusted = deepcopy(FIXTURE["trusted_context"])
            authority = PlanAuthority(Ed25519PrivateKey.generate(), proxy_policy(FIXTURE))
            coordinator = Coordinator(
                store, {"token": trusted}, public_destination(FIXTURE),
                deepcopy(FIXTURE["prompt_blocks"]), deepcopy(FIXTURE["allowed_lineages"]),
                authority, adapter, deepcopy(FIXTURE["retention"]),
                deepcopy(FIXTURE["classification"]), GatewayProxyRecipe(),
                trusted_source_labels=deepcopy(FIXTURE["trusted_source_labels"]),
            )
            request = deepcopy(REQUEST)
            try:
                http_status, reply = coordinator.submit(request, trusted, 3000, credential="token")
                self.assertEqual((http_status, reply["state"], adapter.sends), (200, "delivered", 1))
                sid = reply["handle"]["submission_id"]
                status = coordinator.status(sid, trusted)
                self.assertEqual(request, REQUEST)
                self.assertEqual(adapter.plan["destination"]["model"], PUBLIC_MODEL)
                self.assertEqual(adapter.projection["destination"]["model"], PUBLIC_MODEL)
                self.assertEqual(adapter.prepared["model"], PROXY_MODEL)
                authority.verify(adapter.plan, adapter.plan["work_digest"],
                                 authority.policy["policy_version"])
                self.assertEqual(reply["candidate"]["served_destination"]["model"], PUBLIC_MODEL)
                self.assertEqual(status["candidate"]["served_destination"]["model"], PUBLIC_MODEL)
                self.assertEqual(store.guard_record(reply["candidate"]["attempt_id"])["attempt_id"],
                                 reply["candidate"]["attempt_id"])
                with EzLLMRouterClient("http://127.0.0.1:8765", "token",
                                   transport=WireTransport(reply, status)) as client:
                    self.assertEqual(client.submit(request)["candidate"]["served_destination"]["model"], PUBLIC_MODEL)
                    self.assertEqual(client.getStatus({"submission_id": sid})["candidate"]["served_destination"]["model"], PUBLIC_MODEL)
                self._check_js_package(temp, request, reply, status)
                invalid_reply = deepcopy(reply)
                invalid_status = deepcopy(status)
                invalid_reply["candidate"]["served_destination"]["model"] = PROXY_MODEL
                invalid_status["candidate"]["served_destination"]["model"] = PROXY_MODEL
                with EzLLMRouterClient("http://127.0.0.1:8765", "token",
                                   transport=WireTransport(invalid_reply, invalid_status)) as client:
                    with self.assertRaises(EzLLMRouterError) as first:
                        client.submit(request)
                    with self.assertRaises(EzLLMRouterError) as second:
                        client.getStatus({"submission_id": sid})
                self.assertEqual((first.exception.code, second.exception.code),
                                 ("INTERNAL_UNAVAILABLE", "INTERNAL_UNAVAILABLE"))
                self._check_js_package(temp, request, invalid_reply, invalid_status, reject=True)
            finally:
                coordinator.pool.shutdown(wait=True)
                store.close()

    def test_recipe_is_explicit_and_does_not_mutate_admitted_projection(self):
        projected = {"destination": public_destination(FIXTURE), "work": {
            "messages": deepcopy(REQUEST["messages"]), "requested_features": ["text"],
            "generation_settings": {"max_output_tokens": 32}}}
        original = deepcopy(projected)
        raw, request = GatewayProxyRecipe().expected(projected, 1000)
        self.assertEqual(projected, original)
        self.assertEqual(json.loads(raw)["model"], PROXY_MODEL)
        self.assertEqual(request["url"], "http://127.0.0.1:8767/v1/chat/completions")
        for model in ("openai/model.demo", "model.other", "model.demo.v2"):
            changed = deepcopy(projected)
            changed["destination"]["model"] = model
            with self.assertRaises(ValueError):
                GatewayProxyRecipe().expected(changed, 1000)

    def _check_js_package(self, temp, request, reply, status, reject=False):
        package = Path(temp) / "package/index.cjs"
        if not package.exists():
            packed = subprocess.check_output(["npm", "pack", str(ROOT / "clients/js"),
                "--offline", "--ignore-scripts", "--pack-destination", temp, "--json"],
                text=True, timeout=60,
                env={**os.environ, "npm_config_cache": str(ROOT / ".cache/npm")})
            with tarfile.open(Path(temp) / json.loads(packed)[0]["filename"], "r:gz") as archive:
                archive.extractall(temp, filter="data")
        script = r'''
const fs = require("node:fs");
const {EzLLMRouterClient} = require(process.argv[1]);
const data = JSON.parse(fs.readFileSync(0, "utf8"));
let n = 0;
const fetchImpl = async () => ({status: 200, ok: true,
  headers: {get: () => "0.2"}, json: async () => [data.reply, data.status][n++]});
const client = new EzLLMRouterClient({baseUrl: "http://127.0.0.1:8765", token: "token", fetchImpl});
(async () => {
  if (data.reject) {
    for (const call of [() => client.submit(data.request),
                        () => client.getStatus({submission_id: data.reply.handle.submission_id})]) {
      try { await call(); throw Error("invalid model accepted"); }
      catch (error) { if (error.code !== "INTERNAL_UNAVAILABLE") throw error; }
    }
  } else {
    const a = await client.submit(data.request);
    const b = await client.getStatus({submission_id: a.handle.submission_id});
    if (a.candidate.served_destination.model !== "model.demo" ||
        b.candidate.served_destination.model !== "model.demo") throw Error("model drift");
  }
  if (n !== 2) throw Error("unexpected client request count");
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
        result = subprocess.run(["node", "-e", script, str(package)],
                                input=json.dumps({"request": request, "reply": reply,
                                                  "status": status, "reject": reject}),
                                text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
