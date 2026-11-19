"""No-network checks of the actual TLS first-request-byte gate."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "server/src"), str(Path(__file__).resolve().parent),
                str(ROOT / "tests/development_slice")]
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from ezllmrouter_server.store import SQLiteStore  # noqa: E402
from ezllmrouter_server.successor_authority import SyntheticSuccessorAuthority  # noqa: E402
from ezllmrouter_server.successor_campaign import FiniteSuccessorCampaign  # noqa: E402
from ezllmrouter_server.successor_plan import execution_eligible, mint_plan  # noqa: E402
from ezllmrouter_server.gateway.guard import GuardRejected  # noqa: E402
import owned_tls_sender_transport as tls_sender  # noqa: E402


class _BIO:
    def __init__(self):
        self.pending = 8

    def read(self):
        self.pending = 0
        return b"fake TLS request record"


class _Socket:
    def __init__(self, block=False):
        self.accepted = 0
        self.block = block

    def send(self, data):
        if self.block:
            self.block = False
            raise BlockingIOError()
        self.accepted += len(data)
        return len(data)


class FirstWriteTests(unittest.TestCase):
    def test_first_write_rechecks_after_wait_and_would_block(self):
        vectors = json.loads((ROOT / "tests/fixtures/contracts/dev12-successor-01/vectors.json").read_text())
        example = deepcopy(next(row for row in vectors["examples"] if row["id"] == "DIRECT_DOCUMENT"))
        for change in ("none", "plan_revoked", "campaign_paused", "campaign_expired",
                       "would_block_then_revoked"):
            with self.subTest(change=change), TemporaryDirectory() as temporary:
                store = SQLiteStore(Path(temporary) / "gate.sqlite")
                clock = [datetime(2030, 1, 1, tzinfo=timezone.utc)]
                authority = SyntheticSuccessorAuthority(store, Ed25519PrivateKey.generate(), "key.gate", "v1")
                campaign = FiniteSuccessorCampaign(store, "campaign.gate", "budget.gate",
                                                   wall_clock=lambda: clock[0])
                campaign.start({}, [], window_hours=1)
                revisions, activation, kid, kv, signer = authority.minting_snapshot()
                plan = mint_plan(example["request"], example["work_digest"],
                    example["admission_snapshot_digest"], "submission.gate", "attempt.gate",
                    example["trusted_context"]["identity"]["charging_owner_id"], "budget.gate",
                    revisions, activation, kid, kv, signer)
                record = {"submission_id": "submission.gate", "attempt_id": "attempt.gate",
                    "request": example["request"], "work_key": example["canonical_work"]["work_key"],
                    "work_digest": example["work_digest"], "canonical_work": example["canonical_work"],
                    "admission_snapshot": example["admission_snapshot"],
                    "admission_snapshot_digest": example["admission_snapshot_digest"],
                    "trusted_identity": example["trusted_context"]["identity"],
                    "signed_plan": plan, "reservation": plan["reservation"],
                    "status_revision": 1}
                store.successor_create(record, reserve=campaign.reserve)
                store.successor_guard_commit("submission.gate", "attempt.gate", {
                    "attempt_id": "attempt.gate", "plan_id": plan["plan_id"],
                    "work_digest": record["work_digest"]}, "2030-01-01T00:00:02Z", campaign)
                invocation = SimpleNamespace(committed=True, authority_epoch=authority.snapshot_epoch(),
                                             first_bytes_accepted=False, observations=[], plan=plan)
                def fresh_check():
                    current, epoch = authority.current_snapshot(record, "2030-01-01T00:00:02Z")
                    if not execution_eligible(plan, record["request"], record["canonical_work"],
                                              record["admission_snapshot"], current):
                        raise GuardRejected("FDC_REJECTED")
                    campaign.assert_attempt_releasable(record, committed=True)
                    invocation.authority_epoch = epoch
                invocation.fresh_check = fresh_check
                changed = [False]
                def prohibit():
                    if changed[0]:
                        return
                    changed[0] = True
                    if change in ("plan_revoked", "would_block_then_revoked"):
                        authority.revoke_plan(plan["plan_id"], "2030-01-01T00:00:02Z")
                    elif change == "campaign_paused":
                        with authority.gate:
                            store.database.transaction(lambda: campaign.pause_in_transaction(store.database, "unknown_cost"))
                    elif change == "campaign_expired":
                        clock[0] += timedelta(hours=2)
                async def first_wait():
                    if change != "would_block_then_revoked":
                        prohibit()
                async def fake_writable(_sock, _remaining):
                    prohibit()
                original_writable = tls_sender._writable
                tls_sender._writable = fake_writable
                try:
                    sock = _Socket(block=change == "would_block_then_revoked")
                    stream = tls_sender.OwnedTLSStream(sock, authority, first_write_wait=first_wait)
                    stream.invocation, stream.outgoing = invocation, _BIO()
                    if change == "none":
                        asyncio.run(stream._drain(None, request=True))
                        self.assertGreater(sock.accepted, 0)
                    else:
                        with self.assertRaises((GuardRejected, PermissionError)):
                            asyncio.run(stream._drain(None, request=True))
                        self.assertEqual(sock.accepted, 0)
                finally:
                    tls_sender._writable = original_writable
                    store.close()


if __name__ == "__main__":
    unittest.main()
