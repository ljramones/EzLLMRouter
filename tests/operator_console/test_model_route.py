"""Two fixed public identities retain distinct private proxy model choices."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests/gateway_integration"))
sys.path.insert(0, str(ROOT / "tests/development_slice"))

from proxy_recipe import GatewayProxyRecipe, public_destination


class ModelRouteTests(unittest.TestCase):
    def test_two_distinct_synthetic_models_and_no_arbitrary_route(self):
        fixture = json.loads((ROOT / "tests/gateway_integration/dev05_fixture.json").read_text())
        request = json.loads((ROOT / "tests/development_slice/request.json").read_text())
        base = {
            "destination": public_destination(fixture),
            "work": {
                "messages": request["messages"],
                "requested_features": ["text"],
                "generation_settings": {"max_output_tokens": 32},
            },
        }
        outputs = []
        for model in ("model.demo", "model.demo.alt"):
            work = deepcopy(base)
            work["destination"]["model"] = model
            raw, _ = GatewayProxyRecipe().expected(work, 1000)
            outputs.append(json.loads(raw)["model"])
            self.assertEqual(work["destination"]["model"], model)
        self.assertEqual(outputs, ["openai/model.demo", "openai/model.demo.alt"])
        forbidden = deepcopy(base)
        forbidden["destination"]["endpoint"] = "provider.example"
        with self.assertRaises(ValueError):
            GatewayProxyRecipe().expected(forbidden, 1000)


if __name__ == "__main__":
    unittest.main()
