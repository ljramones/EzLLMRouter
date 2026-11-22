"""Killable real Coordinator/plan/owned-socket and HTTP reply publication paths."""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import socket
import sys
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import httpx

from ezllmrouter_server.gateway.guard import ACTIVE, Invocation
from ezllmrouter_server.gateway.owned_sender_transport import (
    LocalSendAuthority,
    OwnedHTTPTransport,
    OwnedSocketStream,
)
from ezllmrouter_server.plans import PlanAuthority
from ezllmrouter_server.store import SQLiteStore
from ezllmrouter_server.web import serve
from ezllmrouter_server.wire_http.transport import WireTransport
from tests.development_slice import test_core as core
from tests.fixtures.crash_store import checkpoint
from tests.gateway_integration.test_owned_sender_transport import PairBackend
from tests.operator_console.test_user_management_web import MemoryServer


def metadata(root, store, **extra):
    row = store.db.execute("SELECT record FROM submissions").fetchone()
    record = json.loads(row[0])
    intent = store.db.execute(
        "SELECT intent FROM intents WHERE submission_id=?", (record["submission_id"],)
    ).fetchone()
    if intent:
        extra.setdefault("plan_id", json.loads(intent[0])["plan_id"])
    (root / "execution.json").write_text(
        json.dumps(
            {
                "sid": record["submission_id"],
                "aid": record["attempt_id"],
                "work_key": record["work_key"],
                **extra,
            }
        )
    )


class FirstByteSocket:
    def __init__(self, raw, point, root, store):
        self.raw, self.point, self.root, self.store = raw, point, root, store

    def __getattr__(self, name):
        return getattr(self.raw, name)

    def send(self, data):
        metadata(self.root, self.store)
        if self.point == "before_first_byte":
            checkpoint()
        count = self.raw.send(data[:1])
        if count != 1:
            raise AssertionError("first-byte checkpoint requires a real socket acceptance")
        checkpoint()


def coordinator(root):
    fixture = core.CoreTests("runTest")
    fixture.store = SQLiteStore(root / "store.sqlite")
    fixture.trusted, fixture.adapter = deepcopy(core.FIXTURE["trusted_context"]), core.FakeAdapter()
    runtime = fixture.coordinator()
    runtime.authority = PlanAuthority(
        Ed25519PrivateKey.generate(), deepcopy(core.FIXTURE["policy"])
    )
    return fixture, runtime


def execution(root, point, descriptor):
    root.mkdir(parents=True, exist_ok=True)
    fixture, runtime = coordinator(root)
    store = fixture.store
    if point in ("before_plan", "after_plan"):
        issue = runtime.authority.issue

        def plan(*args, **kwargs):
            if point == "before_plan":
                metadata(root, store)
                checkpoint()
            value = issue(*args, **kwargs)
            metadata(
                root,
                store,
                plan_id=value["plan_id"],
                signed_plan_digest=value["signature_envelope"]["signed_plan_digest"],
            )
            checkpoint()

        runtime.authority.issue = plan
    if point == "after_intent":
        intent = store.intent

        def committed(*args):
            intent(*args)
            metadata(root, store)
            checkpoint()

        store.intent = committed
    if point in ("before_first_byte", "after_first_byte"):
        authority = LocalSendAuthority()
        raw = socket.socket(fileno=descriptor)
        raw.setblocking(False)
        stream = OwnedSocketStream(FirstByteSocket(raw, point, root, store), authority)

        def send(prepared, timeout, expected, context):
            plan = context["plan"]
            context["commit"](
                {
                    "attempt_id": context["attempt_id"],
                    "plan_id": plan["plan_id"],
                    "work_digest": plan["work_digest"],
                }
            )
            item = Invocation(
                context["submission_id"],
                context["attempt_id"],
                plan,
                context["projection"],
                context["fresh_check"],
                context["commit"],
                committed=True,
                released=True,
                authority_epoch=authority.snapshot_epoch(),
            )

            async def request():
                transport = OwnedHTTPTransport(authority)
                transport.pool._network_backend = PairBackend(authority, [])

                async def connect(*_args, **_kwargs):
                    return stream

                transport.pool._network_backend.connect_tcp = connect
                token = ACTIVE.set(item)
                try:
                    response = await transport.handle_async_request(
                        httpx.Request(
                            "POST",
                            "http://127.0.0.1:8766/v1/chat/completions",
                            content=prepared,
                            headers={"Authorization": "Bearer synthetic-crash-provider"},
                        )
                    )
                    await response.aread()
                finally:
                    ACTIVE.reset(token)
                    await transport.aclose()

            asyncio.run(request())
            raise AssertionError("first-byte checkpoint was not reached")

        runtime.context_sender = send
    if point in ("before_reply", "after_reply"):
        raw = socket.socket(fileno=descriptor)
        reply = WireTransport._reply

        def publish(handler, status, value):
            metadata(root, store)
            if status != 200:
                raise AssertionError("reply fixture did not complete its candidate")
            if point == "before_reply":
                checkpoint()
            reply(handler, status, value)
            checkpoint()

        with (
            patch("ezllmrouter_server.web.BoundedHTTPServer", MemoryServer),
            patch.object(WireTransport, "_reply", publish),
        ):
            server = serve("127.0.0.1", 48761, runtime)
            server.handler(raw, ("127.0.0.1", 12345), server)
    else:
        runtime.submit(core.REQUEST, fixture.trusted, credential="token.synthetic", wait_ms=3000)
    raise AssertionError("execution checkpoint was not reached")


if __name__ == "__main__":
    execution(Path(sys.argv[1]), sys.argv[2], int(sys.argv[3]))
