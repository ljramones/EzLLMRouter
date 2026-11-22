"""The six-client decoder corpus is reproducible and preserves typed values."""

import json
import unittest

from ezllmrouter_client._json import strict_reply
from tests.decoder_corpus import DESTINATION, corpus


class DecoderCorpusTests(unittest.TestCase):
    def test_checked_in_oracles_are_reproducible_and_include_real_boundaries(self):
        policy = json.loads(DESTINATION.read_text())
        self.assertEqual(policy, corpus())
        self.assertEqual(len(policy["cases"]), 536)
        by_id = {row["id"]: row for row in policy["cases"]}
        self.assertIsNotNone(by_id["depth-32"]["canonical"])
        self.assertIsNone(by_id["depth-33"]["canonical"])
        self.assertIsNone(by_id["escaped-duplicate"]["canonical"])

    def test_python_decoder_matches_every_independent_expectation(self):
        for row in json.loads(DESTINATION.read_text())["cases"]:
            with self.subTest(case=row["id"]):
                raw = bytes.fromhex(row["raw_hex"])
                try:
                    value = strict_reply(raw)
                    canonical = (
                        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                        if type(value) is dict
                        else None
                    )
                except (ValueError, UnicodeError, RecursionError):
                    canonical = None
                self.assertEqual(canonical, row["canonical"])
