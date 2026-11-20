"""Keep new client resources and cross-language cases tied to adopted contracts."""

import json
import importlib.util
from pathlib import Path
import unittest

from tests.client_languages.build_cases import cases

ROOT = Path(__file__).resolve().parents[2]


class NativeClientContracts(unittest.TestCase):
    def test_embedded_schemas_match_the_contract_sources(self):
        sources = {
            "wire02.json": "tests/fixtures/contracts/wp-a-03-c01/EZLLMROUTER-WP-A-SCHEMAS-v0.3-CORRECTION-01.json",
            **{
                name: "clients/js/" + name
                for name in (
                    "dev12_schemas.json",
                    "integration_schema.json",
                    "integration_schema_v2.json",
                    "integration_schema_v3.json",
                )
            },
        }
        for directory in (
            "clients/go/schemas",
            "clients/java/src/main/resources/com/cognitivedynamics/ezllmrouter/schemas",
            "clients/dotnet/EzLLMRouter.Client/Schemas",
            "clients/rust/schemas",
        ):
            for name, source in sources.items():
                with self.subTest(language=directory, schema=name):
                    self.assertEqual(
                        (ROOT / directory / name).read_bytes(), (ROOT / source).read_bytes()
                    )

    def test_typescript_payload_types_match_the_contract_sources(self):
        spec = importlib.util.spec_from_file_location(
            "generate_client_types", ROOT / "clients/js/generate_types.py"
        )
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        self.assertEqual((ROOT / "clients/js/contracts.d.cts").read_text(), generator.generate())
        package = json.loads((ROOT / "clients/js/package.json").read_text())
        for name in ("index.d.cts", "index.d.mts", "contracts.d.cts", "index.mjs"):
            self.assertIn(name, package["files"])
        self.assertEqual(package["exports"]["."]["import"]["types"], "./index.d.mts")
        self.assertEqual(package["exports"]["."]["require"]["types"], "./index.d.cts")

    def test_shared_cases_match_the_existing_python_client(self):
        stored = json.loads((ROOT / "tests/client_languages/cases.json").read_text())
        self.assertEqual(stored, cases())
        indexed = {case["name"]: case for case in stored}
        for name in (
            "embedding",
            "v3_speech_eligibility",
            "v3_permissions",
            "start_run",
            "recover_outcome",
            "multiline_assistant",
            "multiline_status",
            "escaped_text_assistant",
            "escaped_text_status",
            "multiline_tool_arguments",
            "multiline_request",
            "escaped_text_request",
        ):
            self.assertTrue(indexed[name]["expected"]["ok"])
        for name in ("foreign_handle", "foreign_ranking", "v2_foreign_digest", "v3_foreign_digest"):
            self.assertEqual(indexed[name]["expected"]["retry_guidance"], "query_first")
        for name in ("newline_identifier", "newline_public_text", "tab_public_text"):
            self.assertEqual(indexed[name]["expected"]["code"], "SCHEMA_INVALID")
            self.assertEqual(indexed[name]["expected"]["calls"], [])


if __name__ == "__main__":
    unittest.main()
