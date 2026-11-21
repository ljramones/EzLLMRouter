"""dev12_completion_runner plan domain; entry points remain on the facade."""

from __future__ import annotations

from pathlib import Path


def build_plan(
    *,
    root: Path,
    wheel: Path,
    js_package: Path,
    service_image: str,
    node_image: str,
    operator_port: int,
    campaign_id: str,
    budget_account_id: str,
    financial_owner_id: str,
) -> dict:
    """Write one exact, prospective full inventory without starting a target.

    Every selected catalog pair appears even if its handler remains missing;
    the independent no-send preflight rejects that gap.  Bounds are finite
    allocations against the owner's 512/2/USD6/24h ceiling, not observations.
    """
    from tools.gateway.evidence import dev12_completion_runner as _api
    from tools.gateway.evidence.dev12_completion_catalog import REQUIRED_PAIRS, SCENARIOS
    from tools.gateway.evidence.dev12_completion_handlers import DEV12_CASE_HANDLERS

    if not _api._clean_relevant_source():
        raise RuntimeError("commit reviewed target sources before freezing a plan")
    for value in (campaign_id, budget_account_id, financial_owner_id):
        if not value or len(value) > 120 or any(char.isspace() for char in value):
            raise ValueError("distinct bounded synthetic campaign/scope IDs required")
    if not 1024 <= operator_port <= 65535:
        raise ValueError("fixed operator port out of range")
    if not all(
        item.startswith("sha256:") and len(item) == 71 for item in (service_image, node_image)
    ):
        raise ValueError("exact frozen image IDs required")
    for path in (wheel, js_package):
        if not path.is_file() or path.is_symlink():
            raise ValueError("exact installed-client package absent")
    vectors = _api.ROOT / "tests/fixtures/contracts/dev12-successor-01/vectors.json"
    tariffs = _api.ROOT / "tests/fixtures/contracts/dev12-successor-01/tariffs.json"
    completion_receiver = _api.HERE / "dev12_completion_receiver.py"
    artifacts = [
        {
            "kind": "python_wheel",
            "path": str(wheel.resolve()),
            "sha256": _api.sha256(wheel.read_bytes()).hexdigest(),
        },
        {
            "kind": "js_tarball",
            "path": str(js_package.resolve()),
            "sha256": _api.sha256(js_package.read_bytes()).hexdigest(),
        },
        {
            "kind": "service_image",
            "path": service_image,
            "sha256": service_image.removeprefix("sha256:"),
        },
        {"kind": "node_image", "path": node_image, "sha256": node_image.removeprefix("sha256:")},
    ]
    source_tree = _api._tree()
    sends_by_scenario = {
        "t14_a": 2,
        "t24_c": 1,
        "t47_a": 2,
        "t48_f": 5,
        "t48_g": 4,
        "t49_d": 3,
        "t50_a": 2,
        "t51": 4,
        "t52": 2,
        "t53": 4,
        "t54": 2,
        "t55": 3,
        "t60": 3,
        "t45_a": 1,
        "t45_b": 2,
        "t45_c": 3,
        "t45_d": 4,
        "t45_e": 3,
        "t79_a": 2,
        "t79_b": 2,
    }

    def limits(scenario, variant):
        if scenario == "recovery_chain":
            return 1 if variant == "unknown_pause" else 0
        if scenario in {"t03", "t50_e", "t47_b", "t47_c", "t47_d"} or scenario in {
            "t48_a",
            "t48_b",
            "t48_c",
            "t48_d",
            "t48_e",
            "t61",
            "t62_a",
            "t62_b",
            "t62_c",
            "t62_d",
            "t62_e",
            "t64",
            "t65",
            "t66",
        }:
            return 0
        if scenario == "t50_b":
            return 1
        return sends_by_scenario.get(scenario, 1)

    ordered = []
    ordered.extend(
        sorted(
            pair
            for pair in REQUIRED_PAIRS
            if pair[0]
            not in {
                "recovery_chain",
                "t50_e",
                "t61",
                "t62_a",
                "t62_b",
                "t62_c",
                "t62_d",
                "t62_e",
                "t64",
                "t65",
                "t66",
            }
        )
    )
    ordered.extend(
        ("recovery_chain", variant)
        for variant in (
            "unknown_pause",
            "retained_receipt",
            "authorized_late_append",
            "denied_resume",
            "eligible_resume",
        )
    )
    ordered.append(("t50_e", "composed"))
    ordered.extend(
        (scenario, "composed")
        for scenario in ("t66", "t61", "t62_a", "t62_b", "t62_c", "t62_d", "t62_e", "t64", "t65")
    )
    if len(ordered) != len(REQUIRED_PAIRS) or set(ordered) != REQUIRED_PAIRS:
        raise AssertionError("full fixed scenario inventory construction differs")

    cases = []
    chain_id = lambda variant: "case.recovery_chain." + variant
    for scenario, variant in ordered:
        variant_spec = SCENARIOS[scenario].variants[variant]
        name = "case." + scenario + "." + variant
        handler = DEV12_CASE_HANDLERS.get(variant_spec.handler)
        handler_path = (
            _api.Path(handler.source_path)
            if handler
            else _api.HERE
            / (
                "dev12_completion_operator_handlers.py"
                if variant_spec.handler
                in {"operator_identity", "operator_reporting", "persistence_migration"}
                else "dev12_completion_handlers.py"
            )
        )
        handler_hash = _api.sha256(handler_path.read_bytes()).hexdigest()
        sends = limits(scenario, variant)
        prerequisites = []
        late_dependencies = []
        if scenario == "recovery_chain":
            chain = (
                "unknown_pause",
                "retained_receipt",
                "authorized_late_append",
                "denied_resume",
                "eligible_resume",
            )
            index = chain.index(variant)
            if index:
                prerequisites.append(chain_id(chain[index - 1]))
            if variant in {"denied_resume", "eligible_resume"}:
                late_dependencies.append(chain_id("authorized_late_append"))
        if scenario == "t50_e":
            prerequisites.extend(
                row["id"]
                for row in cases
                if row["max_possible_sends"] or row["scenario_id"] == "recovery_chain"
            )
        if scenario == "t61":
            prerequisites.extend(("case.t60.composed", chain_id("authorized_late_append")))
        if scenario == "t62_b":
            prerequisites.append(chain_id("authorized_late_append"))
        if scenario in {"t62_a", "t62_c", "t62_d", "t62_e"}:
            prerequisites.append("case.t60.composed")
        if scenario == "t64":
            prerequisites.extend(
                "case." + item + ".composed"
                for item in ("t61", "t62_a", "t62_b", "t62_c", "t62_d", "t62_e")
            )
        if scenario == "t65":
            prerequisites.append("case.t64.composed")
        fixture_path = (
            (_api.ROOT / "tests/development_slice/request.json")
            if scenario == "t03"
            else tariffs
            if scenario.startswith("t48_")
            else completion_receiver
            if scenario in {"t49_d", "t51", "t52", "t53", "t54"}
            else vectors
        )
        expected_rejection = None
        if (
            (scenario == "t07_a" and variant.startswith("revoked_"))
            or (scenario == "t24_a" and variant == "queued_revocation")
            or (scenario == "t24_b" and variant == "revocation_before_write")
        ):
            expected_rejection = {
                "stage": "first_write",
                "code": "FDC_REJECTED",
                "http_status": 409,
            }
        elif scenario in {"t52", "t54"}:
            expected_rejection = {"stage": "delivery", "code": "RESULT_INVALID", "http_status": 502}
        cases.append(
            {
                "id": name,
                "scenario_id": scenario,
                "variant": variant,
                "assurance_ids": list(SCENARIOS[scenario].assurance_ids),
                "handler": variant_spec.handler,
                "handler_source_sha256": handler_hash,
                "prerequisites": prerequisites,
                "late_dependencies": late_dependencies,
                "scope": campaign_id,
                "attempt_group": (
                    "attempt-group.recovery-chain"
                    if scenario == "recovery_chain"
                    else "attempt-group." + scenario + "." + variant
                ),
                "installed_client_mode": ("both" if scenario.startswith("t47_") else "none"),
                "fixture": {
                    "path": str(fixture_path),
                    "sha256": _api.sha256(fixture_path.read_bytes()).hexdigest(),
                },
                "source_tree": source_tree,
                "build": {"path": str(handler_path), "sha256": handler_hash},
                "max_admissions": sends,
                "max_possible_sends": sends,
                "max_exposure_decimal": str(
                    (_api.Decimal("0.020000000") * sends).quantize(_api.Decimal("0.000000001"))
                ),
                "expected_stages": list(variant_spec.required_stages),
                "expected_rejection": expected_rejection,
                "terminal_status": (
                    "unknown"
                    if (scenario == "recovery_chain" and variant == "unknown_pause")
                    or (scenario == "t24_b" and variant == "partial_write")
                    or scenario in {"t24_c", "t50_c"}
                    else "failed"
                    if (scenario == "t07_a" and variant.startswith("revoked_"))
                    or (scenario == "t24_a" and variant == "queued_revocation")
                    or (scenario == "t24_b" and variant == "revocation_before_write")
                    or scenario in {"t52", "t54"}
                    else "completed"
                ),
                "evidence_paths": ["cases/" + name + ".json"],
                "predicates": list(variant_spec.assertion_ids),
                "evidence_kind": "new",
                "reuse_identity": None,
                "phase": variant_spec.phase,
            }
        )
    envelope = {
        "campaign_id": campaign_id,
        "budget_account_id": budget_account_id,
        "financial_owner_id": financial_owner_id,
        "currency": "USD",
        "max_admissions": 512,
        "max_possible_sends": 512,
        "max_inflight": 2,
        "ceiling_decimal": "6.000000000",
        "window_hours": 24,
        "real_provider_calls": 0,
        "operator_port": operator_port,
        "service_network_mode": "bridge",
        "rerun_headroom_admissions": 64,
        "rerun_headroom_sends": 64,
        "rerun_headroom_decimal": "1.000000000",
        "preexisting_exposure_decimal": "0.000000000",
    }
    return {
        "envelope": envelope,
        "cases": cases,
        "artifacts": artifacts,
        "source_tree": source_tree,
    }


def build_continuation_plan(*, root: Path, prior_plan: dict, checkpoint: dict) -> dict:
    """Create a successor prospectus without rewriting the original plan."""
    from tools.gateway.evidence import dev12_completion_runner as _api

    artifacts = {item["kind"]: item for item in prior_plan["artifacts"]}
    envelope = prior_plan["envelope"]
    plan = _api.build_plan(
        root=root,
        wheel=_api.Path(artifacts["python_wheel"]["path"]),
        js_package=_api.Path(artifacts["js_tarball"]["path"]),
        service_image=artifacts["service_image"]["path"],
        node_image=artifacts["node_image"]["path"],
        operator_port=envelope["operator_port"],
        campaign_id=envelope["campaign_id"],
        budget_account_id=envelope["budget_account_id"],
        financial_owner_id=envelope["financial_owner_id"],
    )
    if plan["artifacts"] != prior_plan["artifacts"] or {
        k: v for k, v in plan["envelope"].items() if k != "preexisting_exposure_decimal"
    } != {k: v for k, v in envelope.items() if k != "preexisting_exposure_decimal"}:
        raise RuntimeError("continuation changes frozen inputs or finite allowance")
    previous_pairs = [(case["scenario_id"], case["variant"]) for case in prior_plan["cases"]]
    current_pairs = [(case["scenario_id"], case["variant"]) for case in plan["cases"]]
    if previous_pairs != current_pairs:
        raise RuntimeError("continuation changes selected case order")
    inherited_ids = {}
    if checkpoint["continuation_number"] >= 3:
        prior_successor_path = _api.Path(checkpoint["latest_plan_path"])
        if not prior_successor_path.is_file() or prior_successor_path.is_symlink():
            raise RuntimeError("latest reviewed continuation plan absent")
        prior_successor = _api.json.loads(prior_successor_path.read_bytes())
        if [
            (row["scenario_id"], row["variant"]) for row in prior_successor["cases"]
        ] != current_pairs or prior_successor["artifacts"] != plan["artifacts"]:
            raise RuntimeError("latest continuation plan differs from selected inventory")
        for case, predecessor in zip(plan["cases"], prior_successor["cases"], strict=True):
            inherited_ids[case["id"]] = predecessor["id"]
            case["id"] = predecessor["id"]
            case["evidence_paths"] = predecessor["evidence_paths"]
            if predecessor["id"] in checkpoint["passed_ids"]:
                case["max_admissions"] = predecessor["max_admissions"]
                case["max_possible_sends"] = predecessor["max_possible_sends"]
                case["max_exposure_decimal"] = predecessor["max_exposure_decimal"]
    old_id = checkpoint["failed_id"]
    new_id = old_id + ".continuation" + str(checkpoint["continuation_number"])
    for case in plan["cases"]:
        case["prerequisites"] = [
            new_id if value == old_id else inherited_ids.get(value, value)
            for value in case["prerequisites"]
        ]
        case["late_dependencies"] = [
            new_id if value == old_id else inherited_ids.get(value, value)
            for value in case["late_dependencies"]
        ]
        if case["id"] == old_id:
            case["id"] = new_id
            case["evidence_paths"] = ["cases/" + new_id + ".json"]
            case["max_admissions"] = 0
            case["max_possible_sends"] = 0
            case["max_exposure_decimal"] = "0.000000000"
    plan["envelope"]["preexisting_exposure_decimal"] = checkpoint["last_campaign"][
        "cumulative_reserved_decimal"
    ]
    return plan
