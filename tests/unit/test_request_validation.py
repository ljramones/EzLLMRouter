"""Preserve public import paths and observable validation-error precedence."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from ezllmrouter_server.request_validation import validate_text_request as validate_direct
from ezllmrouter_server.canonical import ContractError, validate_text_request

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((ROOT / "tests/development_slice/fixture.json").read_text())
REQUEST = json.loads((ROOT / "tests/development_slice/request.json").read_text())


class RequestValidationTests(unittest.TestCase):
    def request(self):
        return {**deepcopy(REQUEST), "deadline": "2099-01-01T00:00:00Z"}

    def validate(self, request, function=validate_text_request):
        return function(
            request,
            FIXTURE["trusted_context"],
            FIXTURE["destination"],
            FIXTURE["prompt_blocks"],
            FIXTURE["allowed_lineages"],
        )

    def assert_error(self, request, code, status):
        with self.assertRaises(ContractError) as caught:
            self.validate(request)
        self.assertEqual((caught.exception.code, caught.exception.status), (code, status))

    def test_original_and_direct_imports_resolve_the_same_request(self):
        self.assertEqual(
            self.validate(self.request()), self.validate(self.request(), validate_direct)
        )

    def test_envelope_shape_precedes_unsupported_version(self):
        self.assert_error(
            {**self.request(), "profile": "unsupported", "unexpected": True},
            "SCHEMA_INVALID",
            400,
        )

    def test_version_precedes_identifier_validation(self):
        self.assert_error(
            {**self.request(), "profile": "unsupported", "task_id": "invalid identifier"},
            "UNSUPPORTED_VERSION",
            426,
        )

    def test_scope_denial_precedes_feature_shape(self):
        self.assert_error(
            {
                **self.request(),
                "requested_configuration_ref": "cfg.other",
                "requested_features": False,
            },
            "POLICY_DENIED",
            403,
        )

    def test_tool_profile_precedes_step_revision_validation(self):
        request = self.request()
        request.update(
            step_revision=0,
            tool_definitions=[
                {
                    "name": "unsupported",
                    "description": "Synthetic lookup",
                    "input_schema": {
                        "type": "object",
                        "properties": {"key": {"type": "string"}},
                        "required": ["key"],
                    },
                }
            ],
        )
        self.assert_error(request, "CAPABILITY_UNSUPPORTED", 422)
