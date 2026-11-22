"""Execute the marked README examples verbatim through the real accounting API."""

from copy import deepcopy
import json
from pathlib import Path
import re
import subprocess
import unittest

from .accounting_support import AccountingHTTPFixture, ROOT

EXAMPLES = json.loads(
    (ROOT / "tests/fixtures/contracts/integration-readiness-v2/examples.json").read_text()
)
DOCUMENTS = {
    "python-accounting-v2": ("clients/python/README.md", "python"),
    "javascript-accounting-v2": ("clients/js/README.md", "js"),
}


def extract(text, name, language):
    marker = "<!-- executable-example: " + name + " -->"
    if text.count(marker) != 1:
        raise ValueError("missing or duplicate executable example: " + name)
    match = re.match(r"\s*```" + language + r"\n(.*?)\n```", text.split(marker)[1], re.S)
    if match is None or not match[1].strip():
        raise ValueError("missing code fence or wrong language: " + name)
    return match[1]


class ExampleExtractionTests(unittest.TestCase):
    def test_every_declared_example_exists_once_in_its_actual_document(self):
        found = []
        for name, (document, language) in DOCUMENTS.items():
            self.assertTrue(extract((ROOT / document).read_text(), name, language))
            found.extend(
                re.findall(r"<!-- executable-example: ([\w-]+) -->", (ROOT / document).read_text())
            )
        self.assertEqual(sorted(found), sorted(DOCUMENTS))

    def test_missing_duplicate_empty_or_retagged_examples_cannot_silently_skip(self):
        marker = "<!-- executable-example: example -->"
        for text in ("", marker * 2, marker + "\n```js\npass\n```", marker + "\n```python\n\n```"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                extract(text, "example", "python")


class DocumentedExamplesHTTPTests(AccountingHTTPFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.dataset = deepcopy(EXAMPLES["dataset"])
        self.account = deepcopy(EXAMPLES["account"])
        self.assertEqual(
            self.request("POST", "/integration/v2/datasets", self.dataset, admin=True, version="2")[
                0
            ],
            201,
        )
        self.assertEqual(
            self.request("POST", "/integration/v2/accounts", self.account, admin=True, version="2")[
                0
            ],
            201,
        )

    def scope(self):
        return {
            "origin": f"http://127.0.0.1:{self.port}",
            "ingest_token": self.ingest_token,
            "dataset_id": self.dataset["dataset_id"],
            "account_id": self.account["account_id"],
            "model_id": "model.synthetic",
            "event": deepcopy(EXAMPLES["events"][0]),
            "feature_snapshot": deepcopy(EXAMPLES["snapshots"][0]),
        }

    def assert_result(self, result):
        self.assertEqual(result["receipt"], result["recovered"])
        self.assertTrue(result["eligibility"]["usable"])
        self.assertEqual(result["snapshot"]["snapshot_id"], "feature.synthetic")
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM integration_events").fetchone()[0], 1
        )
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0], 0)
        report = self.registry.integration.report(
            self.registry.principal("owner.local"), self.dataset["dataset_id"], version="2"
        )
        self.assertEqual(report["attempt_count"], 1)
        self.assertEqual(report["unknown_cost_attempts"], 1)
        self.assertEqual(report["known_total_by_currency"], {})

    def test_python_readme_example_against_real_service(self):
        name = "python-accounting-v2"
        document, language = DOCUMENTS[name]
        scope = self.scope()
        exec(
            compile(extract((ROOT / document).read_text(), name, language), document, "exec"), scope
        )
        self.assert_result(scope)

    def test_javascript_readme_example_against_real_service(self):
        name = "javascript-accounting-v2"
        document, language = DOCUMENTS[name]
        code = extract((ROOT / document).read_text(), name, language)
        scope = self.scope()
        inputs = {
            "origin": scope["origin"],
            "ingestToken": scope["ingest_token"],
            "datasetId": scope["dataset_id"],
            "accountId": scope["account_id"],
            "modelId": scope["model_id"],
            "event": scope["event"],
            "featureSnapshot": scope["feature_snapshot"],
        }
        script = Path(self.tmp.name) / "documented-example.cjs"
        script.write_text(
            'const fs=require("node:fs"); const {createRequire}=require("node:module");\n'
            + "const clientRequire=createRequire(process.argv[2]);\n(async()=>{\n"
            + 'const require=clientRequire;\nconst {origin,ingestToken,datasetId,accountId,modelId,event,featureSnapshot}=JSON.parse(fs.readFileSync(0,"utf8"));\n'
            + code
            + "\nprocess.stdout.write(JSON.stringify({eligibility,receipt,recovered,snapshot}));\n"
            + "})().catch(error=>{console.error(error);process.exitCode=1;});\n",
            encoding="utf-8",
        )
        output = subprocess.check_output(
            ["node", str(script), str(ROOT / "clients/js/package.json")],
            input=json.dumps(inputs),
            text=True,
            timeout=20,
        )
        self.assert_result(json.loads(output))
