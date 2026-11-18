"""Frozen LiteLLM response type → sender allowlist preserves counter presence."""
from __future__ import annotations

import unittest

from litellm.types.llms.openai import ResponseAPIUsage
from choice_b_sender import ChoiceBSenderAdapter


class FrozenUsagePresenceTests(unittest.TestCase):
    def test_absent_null_zero_and_mixed_survive_parser_and_sender(self):
        for expected, write in (("absent", "absent"), ("null", None),
                                ("known", 0), ("known", 30)):
            with self.subTest(expected=expected, write=write):
                details = {"cached_tokens": 0}
                if write != "absent":
                    details["cache_write_tokens"] = write
                if write == 30:
                    details["cache_write_tokens_details"] = {
                        "ttl_30m_tokens": 30, "ttl_12h_tokens": 0}
                usage = ResponseAPIUsage.model_validate({
                    "input_tokens": 120, "output_tokens": 20, "total_tokens": 140,
                    "input_tokens_details": details,
                    "output_tokens_details": {"reasoning_tokens": 2}})
                provider = {"object": "response", "model": "fixture.responses.model",
                    "output": [{"type": "message", "content": [
                        {"type": "output_text", "text": "Hello."}]}],
                    "usage": usage.model_dump(mode="json", exclude_unset=True)}
                result = ChoiceBSenderAdapter._candidate(provider, responses=True)["usage"]
                selected = result["input_tokens_details"]
                if expected == "absent":
                    self.assertNotIn("cache_write_tokens", selected)
                else:
                    self.assertIs(selected["cache_write_tokens"], write)
                self.assertEqual(result["total_tokens"], 140)


if __name__ == "__main__":
    unittest.main()
