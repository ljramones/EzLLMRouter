"""Independent FIRST examples and fail-closed advisory classification."""

from copy import deepcopy
from datetime import datetime, timezone
import unittest

from tools.security_cvss import base_score, classification
from tools.security_dependencies import findings


class CvssTests(unittest.TestCase):
    def test_first_published_v31_examples(self):
        # FIRST https://www.first.org/cvss/v3.1/examples, MySQL replication,
        # POODLE and VMware VMX: the published metric tables and base scores.
        for metrics, expected in (
            ("AV:N/AC:L/PR:L/UI:N/S:C/C:L/I:L/A:N", 6.4),
            ("AV:N/AC:H/PR:N/UI:R/S:U/C:L/I:N/A:N", 3.1),
            ("AV:N/AC:L/PR:L/UI:N/S:C/C:H/I:H/A:H", 9.9),
            ("AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", 9.8),
            ("AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:N", 0.0),
        ):
            for version in ("3.0", "3.1"):
                with self.subTest(metrics=metrics, version=version):
                    self.assertEqual(base_score("CVSS:" + version + "/" + metrics), expected)

    def test_optional_metrics_cannot_lower_base_score(self):
        base = "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"
        self.assertEqual(base_score(base + "/E:U/RL:O/RC:U/CR:L/IR:L/AR:L/MC:N/MI:N/MA:N"), 9.8)
        self.assertEqual(base_score("CVSS:3.1/" + "/".join(reversed(base.split("/")[1:]))), 9.8)

    def test_invalid_duplicate_missing_and_version_mismatched_vectors_fail(self):
        base = "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"
        for vector in (
            None,
            1,
            "",
            base + "/AV:N",
            base + "/E:",
            base + "/E:UU",
            base + "/E:Q",
            base + "/unexpected:N",
            base + "/",
            base.replace("/A:H", ""),
            base.replace("AV:N", "AV:X"),
            base.replace("3.1", "4.0"),
            base + " ",
        ):
            with self.subTest(vector=vector), self.assertRaises(ValueError):
                base_score(vector)

    def test_worst_severity_wins_and_unsupported_ratings_remain_blocking(self):
        vector = "CVSS:3.1/AV:N/AC:H/PR:N/UI:R/S:U/C:L/I:N/A:N"
        low = {"type": "CVSS_V3", "score": vector}
        high = {"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}
        self.assertEqual(classification({"severity": [low]})["effective_severity"], "LOW")
        for severity in ("HIGH", "CRITICAL"):
            result = classification(
                {"database_specific": {"severity": severity}, "severity": [low]}
            )
            self.assertEqual(result["effective_severity"], severity)
            self.assertTrue(result["blocking"])
        self.assertEqual(
            classification({"severity": [low, high]})["effective_severity"], "CRITICAL"
        )
        for ratings in (
            [low, {"type": "CVSS_V4", "score": "CVSS:4.0/AV:N"}],
            [None],
            "bad",
            [dict(low, score="bad")],
        ):
            result = classification({"database_specific": {"severity": "LOW"}, "severity": ratings})
            self.assertTrue(result["blocking"])
            self.assertTrue(result["unsupported_or_invalid_rating"])
        self.assertTrue(classification({})["blocking"])

    def test_actual_findings_gate_uses_vectors_without_changing_source_evidence(self):
        data = {"sha256": "synthetic", "packages": [{"name": "synthetic", "version": "1"}]}
        detail = {
            "id": "TEST-CVSS",
            "severity": [
                {"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:H/PR:N/UI:R/S:U/C:L/I:N/A:N"}
            ],
        }
        snapshot = {
            "complete": True,
            "inventory_sha256": "synthetic",
            "queried_at": datetime.now(timezone.utc).isoformat(),
            "results": [{"vulns": [{"id": "TEST-CVSS"}]}],
            "vulnerabilities": {"TEST-CVSS": detail},
        }
        before = deepcopy(snapshot)
        result = findings(data, snapshot)[0]
        self.assertFalse(result["blocking"])
        self.assertEqual(result["database_severity"], "UNRATED")
        self.assertEqual(result["effective_severity"], "LOW")
        self.assertEqual(result["severity"], detail["severity"])
        self.assertEqual(snapshot, before)


if __name__ == "__main__":
    unittest.main()
