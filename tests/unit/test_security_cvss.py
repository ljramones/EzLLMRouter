"""Independent FIRST examples and fail-closed advisory classification."""

from copy import deepcopy
from datetime import datetime, timezone
import unittest

from tools.security_cvss import base_score, classification
from tools.security_dependencies import findings


class CvssTests(unittest.TestCase):
    def test_v4_base_vectors_are_classified_by_the_actual_gate(self):
        vector = "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:H/SI:H/SA:H"
        result = classification({"severity": [{"type": "CVSS_V4", "score": vector}]})
        self.assertEqual(result["effective_severity"], "CRITICAL")
        self.assertEqual(result["cvss_base_scores"][0]["base_score"], 10.0)
        self.assertFalse(result["unsupported_or_invalid_rating"])

    def test_first_published_v4_examples_and_rounding_boundaries(self):
        # FIRST https://www.first.org/cvss/v4.0/examples, including the base
        # scores whose threat/environmental variants have lower published scores.
        examples = (
            ("AV:L/AC:L/AT:P/PR:L/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N", 7.3),
            ("AV:N/AC:L/AT:P/PR:N/UI:P/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N", 7.7),
            ("AV:N/AC:L/AT:P/PR:N/UI:N/VC:H/VI:L/VA:L/SC:N/SI:N/SA:N", 8.3),
            ("AV:L/AC:L/AT:N/PR:N/UI:A/VC:L/VI:N/VA:N/SC:N/SI:N/SA:N", 4.6),
            ("AV:N/AC:L/AT:N/PR:N/UI:A/VC:N/VI:N/VA:N/SC:L/SI:L/SA:N", 5.1),
            ("AV:N/AC:L/AT:N/PR:N/UI:N/VC:N/VI:N/VA:N/SC:L/SI:L/SA:N", 6.9),
            ("AV:N/AC:L/AT:N/PR:N/UI:N/VC:N/VI:N/VA:N/SC:N/SI:N/SA:N", 0.0),
            # Reference-calculator half-tenth boundaries; exact-rational and
            # Python's compensated sum/round can disagree with FIRST here.
            ("AV:N/AC:L/AT:N/PR:N/UI:P/VC:H/VI:L/VA:N/SC:H/SI:H/SA:H", 8.5),
        )
        for metrics, expected in examples:
            with self.subTest(metrics=metrics):
                self.assertEqual(base_score("CVSS:4.0/" + metrics), expected)

    def test_v4_optional_metrics_cannot_lower_the_base_score(self):
        base = "CVSS:4.0/AV:N/AC:L/AT:P/PR:N/UI:P/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N"
        self.assertEqual(base_score(base + "/E:U"), 7.7)  # Published CVSS-BT is 5.2.
        self.assertEqual(
            base_score(
                base + "/E:U/CR:L/IR:L/AR:L/MVC:N/MVI:N/MVA:N/S:N/AU:N/R:A/V:D/RE:L/U:Clear"
            ),
            7.7,
        )
        self.assertEqual(base_score(base + "/MSI:S/MSA:S"), 7.7)

    def test_v4_invalid_and_out_of_order_metrics_and_mismatched_rating_type_block(self):
        base = "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N"
        for vector in (
            base + "/AV:N",
            base.replace("/AT:N", ""),
            base.replace("/AT:N/PR:N", "/PR:N/AT:N"),
            base + "/CR:H/E:A",
            base + "/E:",
            base + "/E:Q",
            base + "/U:clear",
            base + "/U:Clear/RE:L",
            base.replace("SI:N", "SI:S"),
            base.replace("AV:N", "AV:X"),
            base.replace("4.0", "4.1"),
            base + "/unknown:X",
            base + "/E:A/E:A",
        ):
            with self.subTest(vector=vector):
                result = classification({"severity": [{"type": "CVSS_V4", "score": vector}]})
                self.assertTrue(result["blocking"])
                self.assertTrue(result["unsupported_or_invalid_rating"])
        for kind, vector in (
            ("CVSS_V3", base),
            ("CVSS_V4", "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"),
        ):
            with self.subTest(kind=kind):
                self.assertTrue(
                    classification({"severity": [{"type": kind, "score": vector}]})[
                        "unsupported_or_invalid_rating"
                    ]
                )

    def test_changed_normative_data_fails_closed(self):
        from unittest.mock import patch
        from tools.security_cvss4 import data

        data.cache_clear()
        self.addCleanup(data.cache_clear)
        vector = "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:H/SI:H/SA:H"
        with patch("pathlib.Path.read_bytes", return_value=b"{}"):
            with self.assertRaisesRegex(ValueError, "unreviewed"):
                base_score(vector)
            result = classification({"severity": [{"type": "CVSS_V4", "score": vector}]})
            self.assertTrue(result["blocking"])
            self.assertTrue(result["unsupported_or_invalid_rating"])

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
            [{"type": [], "score": "invalid"}],
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

        detail["severity"] = [
            {
                "type": "CVSS_V4",
                "score": "CVSS:4.0/AV:L/AC:L/AT:N/PR:N/UI:A/VC:L/VI:N/VA:N/SC:N/SI:N/SA:N",
            }
        ]
        before = deepcopy(snapshot)
        result = findings(data, snapshot)[0]
        self.assertFalse(result["blocking"])
        self.assertEqual(result["effective_severity"], "MODERATE")
        self.assertEqual(result["cvss_base_scores"][0]["base_score"], 4.6)
        self.assertEqual(result["severity"], detail["severity"])
        self.assertEqual(snapshot, before)


if __name__ == "__main__":
    unittest.main()
