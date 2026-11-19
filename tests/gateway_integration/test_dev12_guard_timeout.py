"""Exact final-request timeout controls, before any sender or socket."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "server/src"), str(Path(__file__).resolve().parent),
                str(ROOT / "tests/development_slice")]
from duranki_server.gateway.dev12_guard import check_synthetic_request  # noqa: E402
from duranki_server.gateway.guard import GuardRejected  # noqa: E402


class _URL:
    scheme = "https"
    host = "synthetic.invalid"
    netloc = b"synthetic.invalid:443"

    def __str__(self):
        return "https://synthetic.invalid:443/synthetic/v1/embeddings"


class FinalTimeoutTests(unittest.TestCase):
    def test_exact_four_phase_five_second_controls(self):
        vectors = json.loads((ROOT / "docs/contracts/dev12-successor-01/vectors.json").read_text())
        example = deepcopy(next(row for row in vectors["examples"] if row["id"] == "DIRECT_DOCUMENT"))
        admitted = example["request"]
        expected = {"operation": "embedding.create@1",
                    "configuration_ref": admitted["requested_configuration_ref"],
                    "role": admitted["input"]["role"], "profile": admitted["input"]["profile"],
                    "items": admitted["input"]["items"]}
        body = json.dumps(expected, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":")).encode()
        descriptor = {"method": "POST", "host": "synthetic.invalid",
                      "route": "/synthetic/v1/embeddings", "transport": "trusted_sender_tls@1",
                      "content_type": "application/json", "timeout_ms": 5000,
                      "max_request_bytes": 262144}
        invocation = SimpleNamespace(plan={"execution_descriptor": descriptor,
                                           "work_digest": example["work_digest"],
                                           "admission_snapshot_digest": example["admission_snapshot_digest"],
                                           "plan_id": "plan.synthetic"},
                                     projection={"request": admitted,
                                                 "trusted_context": example["trusted_context"],
                                                 "origin": "https://synthetic.invalid:443"},
                                     attempt_id="attempt.synthetic", provider_key="test-only")
        headers = {"host": "synthetic.invalid:443", "content-type": "application/json",
                   "authorization": "Bearer test-only", "x-duranki-attempt": "attempt.synthetic",
                   "content-length": str(len(body))}
        exact = {phase: 5.0 for phase in ("connect", "read", "write", "pool")}
        cases = (("exact", exact, True), ("short", {**exact, "read": 4.0}, False),
                 ("missing", {"connect": 5.0}, False),
                 ("extra", {**exact, "unsupported": 5.0}, False),
                 ("nan", {**exact, "read": math.nan}, False),
                 ("infinity", {**exact, "read": math.inf}, False),
                 ("boolean", {**exact, "read": True}, False),
                 ("text", {**exact, "read": "5"}, False))
        with patch("duranki_server.gateway.dev12_guard.classify_request", return_value="ACCEPT"), \
             patch("duranki_server.gateway.dev12_guard.plan_valid", return_value=True):
            for name, timeout, valid in cases:
                with self.subTest(name=name):
                    request = SimpleNamespace(method="POST", url=_URL(), headers=headers,
                                              extensions={"timeout": timeout})
                    if not valid:
                        with self.assertRaises(GuardRejected):
                            check_synthetic_request(request, invocation, body)
                    else:
                        receipt = check_synthetic_request(request, invocation, body)
                        self.assertEqual(receipt["timeout_ms"], 5000)
                        self.assertEqual(receipt["verified_timeout_components_ms"],
                                         {phase: 5000 for phase in exact})
                        self.assertEqual(receipt["body_sha256"], hashlib.sha256(body).hexdigest())


if __name__ == "__main__":
    unittest.main()
