"""Malformed native observations cannot become calculated usage."""
from pathlib import Path
import base64
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "server/src"), str(ROOT / "tests/development_slice")]
from dev12_executor import Dev12SyntheticExecutor, receiver_decode  # noqa: E402
from ezllmrouter_server.canonical import ContractError  # noqa: E402


class ReceiverDecodeTests(unittest.TestCase):
    def test_missing_null_and_invalid_native_component_remain_distinct(self):
        self.assertEqual(receiver_decode(b'{"result":{},"usage_component":null}')["usage_component"], None)
        self.assertNotIn("usage_component", receiver_decode(b'{"result":{}}'))
        self.assertEqual(receiver_decode(b'{"result":{},"usage_component":{"quantity":1.5}}')
                         ["usage_component"]["quantity"], 1.5)
        self.assertEqual(receiver_decode(
            b'{"result":{},"usage_component":{"quantity":"\\ud800"}}')
            ["usage_component"]["quantity"], chr(0xD800))
        with self.assertRaises(ValueError):
            receiver_decode(b'{"result":{},"result":{}}')
        with self.assertRaises(ValueError):
            receiver_decode(b'{"result":{},"usage_component":NaN}')

    def test_post_callback_controls_match_signed_descriptor(self):
        descriptor = {"method": "POST", "host": "synthetic.invalid", "route": "/synthetic/v1/rerank",
                      "transport": "trusted_sender_tls@1", "content_type": "application/json",
                      "timeout_ms": 5000, "max_request_bytes": 262144}
        body = b'{"operation":"rerank@1"}'
        proposal = {key: descriptor[key] for key in
                    ("method", "host", "route", "transport", "content_type", "timeout_ms")}
        proposal["body_b64"] = base64.b64encode(body).decode()
        plan = {"execution_descriptor": descriptor}
        Dev12SyntheticExecutor._validate_proposal(plan, proposal, body)
        for field, replacement in (("host", "other.invalid"), ("transport", "plain"),
                                   ("timeout_ms", 6000), ("route", "/elsewhere")):
            changed = dict(proposal, **{field: replacement})
            with self.subTest(field=field), self.assertRaises(ContractError):
                Dev12SyntheticExecutor._validate_proposal(plan, changed, body)
        with self.assertRaises(ContractError):
            Dev12SyntheticExecutor._validate_proposal(plan, proposal, body + b" ")


if __name__ == "__main__":
    unittest.main()
