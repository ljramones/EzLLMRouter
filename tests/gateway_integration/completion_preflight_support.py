"""Shared fixture for CompletionPreflightTests behaviour suites; contains no discovered tests."""

from __future__ import annotations


class CompletionPreflightFixture:
    def setUp(self):
        from tests.gateway_integration import test_completion_preflight as _api

        self.temporary = _api.TemporaryDirectory(
            prefix=".dev12-preflight-test-",
            dir=_api.Path(
                _api.os.environ.get(
                    "DEV12_TEST_SCRATCH_ROOT", _api.Path(_api.__file__).resolve().parents[2]
                )
            ),
        )
        self.addCleanup(self.temporary.cleanup)
        self.root = _api.Path(self.temporary.name)
        wheel = self.root / "client.whl"
        wheel.write_bytes(b"test wheel bytes")
        tarball = self.root / "client.tgz"
        tarball.write_bytes(b"test tarball bytes")
        self.images = {"sha256:" + "a" * 64, "sha256:" + "b" * 64}
        ref = lambda file: {"path": str(file), "sha256": _api.sha256(file.read_bytes()).hexdigest()}
        source_sha = _api.sha256(_api.Path(_api.__file__).read_bytes()).hexdigest()
        self.handlers = {
            name: _api.CaseHandler(
                name,
                str(_api.Path(_api.__file__).resolve()),
                source_sha,
                frozenset(
                    pair
                    for pair in _api.REQUIRED_PAIRS
                    if _api.SCENARIOS[pair[0]].variants[pair[1]].handler == name
                ),
                run,
            )
            for name, run in _api._RUNS.items()
        }
        chain_ids = {
            variant: f"case.recovery_chain.{variant}"
            for variant in _api.SCENARIOS["recovery_chain"].variants
        }
        order = (
            "unknown_pause",
            "retained_receipt",
            "authorized_late_append",
            "denied_resume",
            "eligible_resume",
        )
        cases = []
        for scenario, variant in sorted(_api.REQUIRED_PAIRS):
            scenario_spec = _api.SCENARIOS[scenario]
            spec = scenario_spec.variants[variant]
            ident = f"case.{scenario}.{variant}"
            recovery = scenario == "recovery_chain"
            sends = max(
                spec.minimum_possible_sends,
                int(
                    "receiver" in spec.required_stages
                    and spec.phase not in {"late_evidence", "resume"}
                ),
            )
            if (scenario, variant) == ("t50_e", "composed"):
                sends = 0  # Imported historical underbound; no new target admission.
            prerequisites = []
            late_dependencies = []
            if recovery and variant != "unknown_pause":
                prerequisites = [chain_ids[order[order.index(variant) - 1]]]
                if variant in {"denied_resume", "eligible_resume"}:
                    late_dependencies = [chain_ids["authorized_late_append"]]
            cases.append(
                {
                    "id": ident,
                    "scenario_id": scenario,
                    "variant": variant,
                    "assurance_ids": list(scenario_spec.assurance_ids),
                    "handler": spec.handler,
                    "handler_source_sha256": source_sha,
                    "prerequisites": prerequisites,
                    "late_dependencies": late_dependencies,
                    "attempt_group": "attempt.recovery" if recovery else ident,
                    "scope": "campaign.new",
                    "installed_client_mode": "both",
                    "fixture": ref(_api._fixture_path_for_scenario(scenario)),
                    "source_tree": "c" * 40,
                    "build": ref(_api.Path(_api.__file__)),
                    "max_admissions": sends,
                    "max_possible_sends": sends,
                    "max_exposure_decimal": "0.010000000" if sends else "0.000000000",
                    "expected_stages": list(spec.required_stages),
                    "expected_rejection": None,
                    "terminal_status": "completed",
                    "evidence_paths": [str(self.root / "cases" / (ident + ".json"))],
                    "predicates": list(spec.assertion_ids),
                    "evidence_kind": "new",
                    "reuse_identity": None,
                    "phase": spec.phase,
                }
            )
        fresh_ids = {
            case["id"]
            for case in cases
            if case["max_possible_sends"] or case["scenario_id"] == "recovery_chain"
        }
        reporting_order = {
            "t61": ("t60", "recovery_chain.authorized_late_append"),
            "t62_a": ("t60",),
            "t62_b": ("recovery_chain.authorized_late_append",),
            "t62_c": ("t60",),
            "t62_d": ("t60",),
            "t62_e": ("t60",),
            "t64": ("t61", "t62_a", "t62_b", "t62_c", "t62_d", "t62_e"),
            "t65": ("t64",),
        }
        case_ids = {f"{case['scenario_id']}.{case['variant']}": case["id"] for case in cases}
        for case in cases:
            if case["scenario_id"] in reporting_order:
                case["prerequisites"].extend(
                    case_ids[name if "." in name else name + ".composed"]
                    for name in reporting_order[case["scenario_id"]]
                )
            if case["phase"] == "terminal":
                case["prerequisites"] = sorted(fresh_ids - {case["id"]})
        ordered, pending = [], list(cases)
        while pending:
            ready = next(
                (
                    case
                    for case in pending
                    if set(case["prerequisites"] + case["late_dependencies"]).issubset(
                        {row["id"] for row in ordered}
                    )
                ),
                None,
            )
            if ready is None:
                raise AssertionError("test catalog contains a dependency cycle")
            pending.remove(ready)
            ordered.append(ready)
        cases = ordered
        self.plan = {
            "source_tree": "c" * 40,
            "envelope": {
                "campaign_id": "campaign.new",
                "budget_account_id": "budget.new",
                "financial_owner_id": "team.new",
                "max_admissions": 512,
                "max_possible_sends": 512,
                "max_inflight": 2,
                "ceiling_decimal": "6.000000000",
                "window_hours": 24,
                "real_provider_calls": 0,
                "rerun_headroom_admissions": 2,
                "rerun_headroom_sends": 2,
                "rerun_headroom_decimal": "0.020000000",
                "preexisting_exposure_decimal": "0.000000000",
            },
            "artifacts": [
                {"kind": "python_wheel", **ref(wheel)},
                {"kind": "js_tarball", **ref(tarball)},
                {"kind": "service_image", "path": "sha256:" + "a" * 64, "sha256": "a" * 64},
                {"kind": "node_image", "path": "sha256:" + "b" * 64, "sha256": "b" * 64},
            ],
            "cases": cases,
        }

    def check(self, plan=None, handlers=None):
        from tests.gateway_integration import test_completion_preflight as _api

        return _api.validate(
            plan if plan is not None else self.plan,
            handlers=handlers if handlers is not None else self.handlers,
            artifact_root=self.root,
            image_ids=self.images,
            handler_source_path=_api.Path(_api.__file__),
        )

    def case(self, plan, scenario, variant="composed"):
        return next(
            case
            for case in plan["cases"]
            if (case["scenario_id"], case["variant"]) == (scenario, variant)
        )
