"""Qualified-profile adapter: networkless UDS worker, Neti guard, owned TLS sender."""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import socket

import httpx

from choice_b_wire import receive, send
from dev12_tls_transport import OwnedSyntheticTLSHTTPTransport
from guard import ACTIVE, GuardRejected, GuardTransport, Invocation
from duranki_server.canonical import ContractError
from duranki_server.successor_contract import config_for, price_for
from duranki_server.successor_plan import execution_eligible, recipe_for


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def receiver_decode(raw):
    """Bound a receiver observation without promoting malformed usage to known."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate receiver key")
            result[key] = value
        return result
    def reject(_raw):
        raise ValueError("non-finite receiver number")
    value = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=pairs,
                       parse_constant=reject)
    def depth(item, current=0):
        if current > 32:
            raise ValueError("receiver JSON depth")
        if type(item) is dict:
            for child in item.values():
                depth(child, current + 1)
        elif type(item) is list:
            for child in item:
                depth(child, current + 1)
    depth(value)
    return value


class _RealizedRequestProbe(httpx.AsyncBaseTransport):
    """Test-only mutation below HTTPX construction, above the real guard."""

    def __init__(self, guarded, transform):
        self.guarded = guarded
        self.transform = transform

    async def handle_async_request(self, request):
        changed = self.transform(request)
        if not isinstance(changed, httpx.Request):
            raise TypeError("realized request probe must return an HTTPX request")
        return await self.guarded.handle_async_request(changed)

    async def aclose(self):
        await self.guarded.aclose()


class Dev12SyntheticExecutor:
    def __init__(self, worker_socket: str | Path, receiver_port: int, ca_pem: str,
                 test_credential: str, *, first_write_wait=None, proposal_transform=None,
                 realized_request_transform=None):
        self.worker_socket = str(worker_socket)
        self.receiver_port = receiver_port
        self.ca_pem = ca_pem
        self.test_credential = test_credential
        self.origin = f"https://synthetic.invalid:{receiver_port}"
        self.first_write_wait = first_write_wait
        self.proposal_transform = proposal_transform
        self.realized_request_transform = realized_request_transform
        if not test_credential or "\n" in test_credential:
            raise ValueError("owned synthetic credential required")

    @staticmethod
    def _validate_proposal(plan, proposal, body):
        if type(proposal) is not dict or set(proposal) != {
                "method", "host", "route", "transport", "content_type", "timeout_ms", "body_b64"}:
            raise ContractError("FDC_REJECTED", 409)
        descriptor = plan["execution_descriptor"]
        if any(proposal[name] != descriptor[name] for name in
               ("method", "host", "route", "transport", "content_type", "timeout_ms")):
            raise ContractError("FDC_REJECTED", 409)
        try:
            proposed_body = base64.b64decode(proposal["body_b64"], validate=True)
        except (ValueError, TypeError) as exc:
            raise ContractError("FDC_REJECTED", 409) from exc
        if (type(body) is not bytes or body != proposed_body or
                not 0 < len(body) <= descriptor["max_request_bytes"]):
            raise ContractError("FDC_REJECTED", 409)

    def _prepare(self, record):
        plan = record["signed_plan"]
        recipe = recipe_for(record["request"], record["work_digest"],
                            config_for(record["request"]), plan["execution_descriptor"])
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
            stream.settimeout(8)
            stream.connect(self.worker_socket)
            send(stream, {"kind": "prepare", "request": record["request"], "recipe": recipe})
            proposal = receive(stream)
        if "error_type" in proposal:
            raise ContractError("FDC_REJECTED", 409)
        try:
            body = base64.b64decode(proposal["body_b64"], validate=True)
        except (ValueError, TypeError) as exc:
            raise ContractError("FDC_REJECTED", 409) from exc
        self._validate_proposal(plan, proposal, body)
        return proposal, body

    def execute(self, record, authority, store, allowance):
        plan = record["signed_plan"]
        proposal, body = self._prepare(record)
        if self.proposal_transform is not None:
            proposal, body = self.proposal_transform(proposal, body)
        self._validate_proposal(plan, proposal, body)
        sid, aid = record["submission_id"], record["attempt_id"]
        invocation = None

        def fresh_check():
            with authority.gate:
                current, epoch = authority.current_snapshot(record, now())
                if not execution_eligible(plan, record["request"], record["canonical_work"],
                                          record["admission_snapshot"], current):
                    raise GuardRejected("FDC_REJECTED")
                try:
                    allowance.assert_attempt_releasable(record, committed=invocation.committed)
                except PermissionError as exc:
                    raise GuardRejected("FDC_REJECTED") from exc
                with store._lock:
                    prior = store.db.execute("SELECT submission_id FROM dev12_send_ownership "
                                             "WHERE attempt_id=?", (aid,)).fetchone()
                if (prior is not None and (not invocation.committed or prior[0] != sid)) or (
                        invocation.committed and prior is None):
                    raise GuardRejected("SECOND_SEND_REJECTED")
                invocation.authority_epoch = epoch

        def commit(receipt):
            with authority.gate:
                fresh_check()
                store.successor_guard_commit(sid, aid, receipt, now(), allowance)

        invocation = Invocation(submission_id=sid, attempt_id=aid, plan=plan,
                                projection={"request": record["request"],
                                            "trusted_context": record["trusted_context"],
                                            "origin": self.origin},
                                fresh_check=fresh_check, commit=commit,
                                provider_key=self.test_credential)
        invocation.authority_epoch = authority.snapshot_epoch()

        async def transfer():
            lower = OwnedSyntheticTLSHTTPTransport(authority, self.receiver_port, self.ca_pem,
                                                    first_write_wait=self.first_write_wait)
            guard = GuardTransport(lower)
            guarded = (_RealizedRequestProbe(guard, self.realized_request_transform)
                       if self.realized_request_transform is not None else guard)
            token = ACTIVE.set(invocation)
            try:
                async with httpx.AsyncClient(transport=guarded, trust_env=False,
                                             follow_redirects=False, timeout=httpx.Timeout(5.0)) as client:
                    response = await client.request(proposal["method"],
                        self.origin + proposal["route"], content=body,
                        headers={"Content-Type": proposal["content_type"],
                                 "Authorization": "Bearer " + self.test_credential})
                    raw = await response.aread()
                    if len(raw) > plan["execution_descriptor"]["max_response_bytes"]:
                        raise ValueError("synthetic response limit")
                    return response.status_code, raw
            finally:
                ACTIVE.reset(token)

        try:
            status, raw = asyncio.run(transfer())
        except Exception as exc:
            store.successor_append_evidence(sid, "sender_outcome", now(),
                {"first_bytes_accepted": invocation.first_bytes_accepted,
                 "guard_committed": invocation.committed,
                 "response_received": invocation.response_received,
                 "error_type": type(exc).__name__})
            if invocation.first_bytes_accepted:
                return {"state": "unknown"}
            raise ContractError("FDC_REJECTED", 409) from exc
        store.successor_append_evidence(sid, "sender_outcome", now(),
            {"first_bytes_accepted": invocation.first_bytes_accepted,
             "guard_committed": invocation.committed,
             "response_received": invocation.response_received,
             "http_status": status, "raw_response_b64": base64.b64encode(raw).decode(),
             "raw_response_sha256": hashlib.sha256(raw).hexdigest(),
             "first_write_observations": invocation.observations})
        if not invocation.first_bytes_accepted or not invocation.committed:
            raise ContractError("FDC_REJECTED", 409)
        try:
            response = receiver_decode(raw)
        except (UnicodeError, ValueError, TypeError):
            response = {"usage_component": {"component": price_for(record["request"])["component"],
                       "presence": "invalid", "raw_digest": "sha256:" +
                       hashlib.sha256(raw).hexdigest()}}
        if type(response) is not dict:
            response = {"usage_component": {"component": price_for(record["request"])["component"],
                       "presence": "invalid", "raw_digest": "sha256:" +
                       hashlib.sha256(raw).hexdigest()}}
        price = price_for(record["request"])
        if "usage_component" not in response:
            component = {"component": price["component"], "presence": "absent"}
        elif response["usage_component"] is None:
            component = {"component": price["component"], "presence": "null"}
        elif type(response["usage_component"]) is not dict:
            component = {"component": price["component"], "presence": "invalid",
                         "raw_digest": "sha256:" + hashlib.sha256(raw).hexdigest()}
        else:
            component = response["usage_component"]
        return {"state": "observed", "result": response.get("result") if
                set(response) <= {"result", "usage_component"} else None,
                "usage_component": component, "http_status": status}
