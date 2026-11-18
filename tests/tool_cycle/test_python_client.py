"""Installed-client tool-only contract vector and unusable-call controls."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from duranki_client import _validation as v

HERE = Path(__file__).resolve().parent
VECTOR_PATH = HERE / "vectors.json"
if not VECTOR_PATH.exists():
    VECTOR_PATH = HERE.parents[1] / "docs/contracts/wp-a-03-c01/DURANKI-WP-A-VECTORS-v0.3-CORRECTION-01.json"
VECTORS = json.loads(VECTOR_PATH.read_text())


class ToolClientTests(unittest.TestCase):
    def test_adopted_tool_only_reply_and_bad_call(self):
        reply = deepcopy(VECTORS["examples"]["reply_tool"])
        self.assertTrue(v.reply(reply, 200))
        wrong = deepcopy(reply)
        wrong["candidate"]["output_blocks"][0]["arguments"]["key"] = 1
        self.assertFalse(v.reply(wrong, 200))
        duplicate = deepcopy(reply)
        duplicate["candidate"]["output_blocks"].append({**duplicate["candidate"]["output_blocks"][0],
                                                       "block_id": "block.call.2"})
        self.assertFalse(v.reply(duplicate, 200))


if __name__ == "__main__":
    unittest.main()
