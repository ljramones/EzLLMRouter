"""Product wire-0.3 projection checked against the adopted A1 goldens."""
import base64
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/src"))
from duranki_server import successor_contract as subject  # noqa: E402
from duranki_server.canonical import ContractError  # noqa: E402

VECTORS = json.loads((ROOT / "tests/fixtures/contracts/dev12-successor-01/vectors.json").read_text())


class SuccessorContractTests(unittest.TestCase):
    def test_positive_work_and_result_goldens(self):
        examples = {case["id"]: case for case in VECTORS["examples"]}
        for case in examples.values():
            with self.subTest(case=case["id"]):
                self.assertEqual(subject.classify_request(case["request"], case["trusted_context"]), "ACCEPT")
                work = subject.work_projection(case["request"], case["trusted_context"])
                self.assertEqual(work, case["canonical_work"])
                self.assertEqual(subject.canonical(work).encode(),
                                 base64.b64decode(case["canonical_bytes_base64"], validate=True))
                self.assertEqual(subject.work_digest(work), case["work_digest"])
                self.assertEqual(subject.digest("duranki-admission-v1\n", case["admission_snapshot"]),
                                 case["admission_snapshot_digest"])
        for fixture in VECTORS["result_examples"]:
            with self.subTest(result=fixture["id"]):
                request = examples[fixture["request_case"]]["request"]
                self.assertTrue(subject.result_valid(fixture["value"], request,
                                                     fixture["value"]["attempt_id"]))

    def test_negative_corpus(self):
        examples = {case["id"]: case for case in VECTORS["examples"]}
        results = {case["id"]: case for case in VECTORS["result_examples"]}
        for case in VECTORS["negative_cases"]:
            with self.subTest(case=case["id"]):
                if case["target"] == "raw":
                    raw = (base64.b64decode(case["raw_bytes_base64"]) if "raw_bytes_base64" in case else
                           case["raw"].encode())
                    with self.assertRaises(ContractError):
                        subject.strict_decode(raw)
                    continue
                result_fixture = results.get(case["base"]) if case["target"] == "result" else None
                base = examples[result_fixture["request_case"] if result_fixture else case["base"]]
                obj = deepcopy(base["request"] if case["target"] == "request" else result_fixture["value"])
                parts = case["path"].split(".")
                parent = obj
                for part in parts[:-1]:
                    parent = parent[int(part) if type(parent) is list else part]
                parent[int(parts[-1]) if type(parent) is list else parts[-1]] = case["value"]
                if case["target"] == "request":
                    got = subject.classify_request(obj, base["trusted_context"])
                elif not subject.schema_valid(obj, subject.SCHEMAS["$defs"]["Result"]):
                    got = "SCHEMA_INVALID"
                else:
                    got = ("ACCEPT" if subject.result_valid(obj, base["request"],
                           result_fixture["value"]["attempt_id"]) else "RESULT_INVALID")
                self.assertEqual(got, case["expect"])

    def test_native_tariff_domains(self):
        fixture = VECTORS["examples"][1]["request"]
        prices = subject.REGISTRATIONS["price_contracts"]
        schedules = {price["schedule_kind"]: price for price in prices}
        for count in range(1, 26):
            request = deepcopy(fixture)
            request["input"]["candidates"] = [deepcopy(fixture["input"]["candidates"][0]) for _ in range(count)]
            for kind, column in (("tariff_a", "tariff_a"), ("tariff_b", "tariff_b")):
                with self.subTest(count=count, kind=kind):
                    result = subject.tariff(request, schedules[kind])
                    expected = subject.TARIFFS["rows"][count - 1][column]
                    self.assertEqual(Decimal(result["settled"]), Decimal(expected["settled_usd"]))
                    self.assertEqual(Decimal(result["bound"]), Decimal(expected["request_bound_usd"]))
        self.assertEqual(subject.tariff(VECTORS["examples"][2]["request"], schedules["embedding_query"])["bound"],
                         "0.000200000")


if __name__ == "__main__":
    unittest.main()
