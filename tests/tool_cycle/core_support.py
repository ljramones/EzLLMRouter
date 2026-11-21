"""Shared fixture for ToolCoreTests behaviour suites; contains no discovered tests."""

from __future__ import annotations


class ToolCoreFixture:
    def setUp(self):
        from tests.tool_cycle import test_core as _api

        self.temp = _api.tempfile.TemporaryDirectory(
            prefix="core-", dir=_api.os.environ.get("EZLLMROUTER_TEST_SCRATCH")
        )
        self.store = _api.SQLiteStore(_api.Path(self.temp.name) / "store.sqlite")
        self.adapter = _api.FakeAdapter()
        self.trusted = _api.deepcopy(_api.FIXTURE["trusted_context"])
        self.authority = _api.CapturingAuthority()
        self.coordinator = _api.Coordinator(
            self.store,
            identity={"token": self.trusted},
            config=_api.deepcopy(_api.FIXTURE["destination"]),
            prompt_blocks=_api.deepcopy(_api.FIXTURE["prompt_blocks"]),
            allowed_lineages=_api.deepcopy(_api.FIXTURE["allowed_lineages"]),
            authority=self.authority,
            adapter=self.adapter,
            retention=_api.deepcopy(_api.FIXTURE["retention"]),
            classification=_api.deepcopy(_api.FIXTURE["classification"]),
            recipe=_api.SyntheticDevelopmentRecipe(),
            trusted_source_labels=_api.deepcopy(_api.FIXTURE["trusted_source_labels"]),
        )

    def tearDown(self):
        self.coordinator.pool.shutdown(wait=True)
        self.store.close()
        self.temp.cleanup()

    def request(self, generation="gen.1"):
        from tests.tool_cycle import test_core as _api

        value = _api.deepcopy(_api.BASE)
        value.update(
            step_id="step.component",
            execution_generation=generation,
            requested_features=["text", "tools"],
            tool_definitions=[_api.deepcopy(_api.CORPUS["tool_definition"])],
            tool_choice="auto",
        )
        value["messages"][1]["blocks"][0]["text"] = "Use lookup for synthetic."
        return value

    def _restricted(self, lineage):
        labels = {
            "lineage_ids": [lineage],
            "sensitivity": "confidential",
            "restrictions": ["no.content.store"],
        }
        self.coordinator.trusted_source_labels[lineage] = labels
        return labels
