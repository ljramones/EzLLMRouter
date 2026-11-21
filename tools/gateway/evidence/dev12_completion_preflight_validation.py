"""dev12_completion_preflight preflight validation domain; entry points remain on the facade."""

from __future__ import annotations

from tools.gateway.evidence.dev12_completion_catalog import REQUIRED_PAIRS, SCENARIOS


def selected_ids():
    ids = {
        "T-01",
        "T-02",
        "T-03",
        "T-42",
        "T-60",
        "T-61",
        "T-64",
        "T-65",
        "T-66",
        "T-14.a",
        "T-07.a",
    }
    for parent, letters in (
        ("T-24", "abc"),
        ("T-45", "abcde"),
        ("T-46", "abcd"),
        ("T-47", "abcd"),
        ("T-48", "abcdefg"),
        ("T-49", "abcde"),
        ("T-50", "abcde"),
        ("T-62", "abcde"),
        ("T-77", "abcd"),
        ("T-78", "abcd"),
        ("T-79", "abcd"),
    ):
        ids.update(f"{parent}.{letter}" for letter in letters)
    ids.update(f"T-{number}" for number in range(51, 56))
    return frozenset(ids)


REQUIRED_IDS = selected_ids()


def _continuation_context(plan, root, prior_exposure, errors):
    """Bind a continued prospectus to one unchanged durable parent campaign."""
    from tools.gateway.evidence import dev12_completion_preflight as _api

    if prior_exposure == 0:
        if (root / "campaign.sqlite").exists():
            errors.append("existing durable campaign requires checked continuation")
        return None
    try:
        from tools.gateway.evidence.dev12_completion_runner import continuation_checkpoint

        prior_path = root / "plan.json"
        database = root / "campaign.sqlite"
        if (
            not prior_path.is_file()
            or prior_path.is_symlink()
            or not database.is_file()
            or database.is_symlink()
        ):
            raise ValueError("original plan or campaign database absent")
        prior_bytes = prior_path.read_bytes()
        prior = _api.json.loads(prior_bytes)
        checkpoint = continuation_checkpoint(root, prior, prior_bytes)
        new, passed, continuation_number, latest_failed, previous_failed = (
            _validate_continuation_inventory(_api, checkpoint, plan, prior, root)
        )
        durable = _read_unchanged_campaign(_api, database, new)
        _validate_continuation_campaign(
            _api,
            checkpoint,
            continuation_number,
            durable,
            new,
            passed,
            previous_failed,
            prior_exposure,
        )
        if continuation_number in (7, 8):
            from tools.gateway.evidence.dev12_completion_runner import _journal_rows

            if any(
                row.get("kind") in {"case_begin", "case_end"}
                and row.get("case_id") == latest_failed
                for row in _journal_rows(root / "case-journal.jsonl")
            ):
                raise ValueError("operator capture stop must precede case begin")
        if continuation_number == 4:
            failed_attempts = checkpoint.get("failed_attempt_ids")
            if (
                type(failed_attempts) is not list
                or len(failed_attempts) != 3
                or any(type(value) is not str or not value for value in failed_attempts)
                or len(set(failed_attempts)) != 3
            ):
                raise ValueError("retained T49d three-attempt evidence unavailable")
        if continuation_number in (5, 6, 7, 8):
            positives = checkpoint.get("retained_t60_positive_attempt_ids")
            if (
                (
                    continuation_number == 5
                    and (
                        previous_failed["scenario_id"],
                        previous_failed["variant"],
                        previous_failed["expected_stages"],
                    )
                    != ("t60", "composed", ["operator"])
                )
                or type(positives) is not list
                or len(positives) != 3
                or any(type(value) is not str or not value for value in positives)
                or len(set(positives)) != 3
            ):
                raise ValueError("retained T60 positive attempts are unverified")
        retained_live_clients = set()
        if continuation_number == 3:
            attempts = checkpoint.get("failed_attempt_ids")
            if (
                previous_failed["id"] != "case.t47_a.composed"
                or previous_failed["installed_client_mode"] != "both"
                or previous_failed["evidence_kind"] != "new"
                or previous_failed["max_possible_sends"] != 2
                or type(attempts) is not list
                or len(attempts) != 2
                or any(type(value) is not str or not value for value in attempts)
                or attempts[0] == attempts[1]
            ):
                raise ValueError("retained installed-client submissions are unverified")
            # The checkpoint independently verifies both completed attempts,
            # receiver arrivals, campaign deltas and exact retained T47a evidence.
            retained_live_clients.update(("python_wheel", "js_tarball"))
        if continuation_number in (4, 5, 6, 7, 8):
            attempts = checkpoint.get("retained_t47_live_attempt_ids")
            evidence = checkpoint.get("retained_t47_live_evidence")
            source = root / "cases/case.t47_a.composed.json"
            if (
                type(attempts) is not list
                or len(attempts) != 2
                or any(type(value) is not str or not value for value in attempts)
                or attempts[0] == attempts[1]
                or type(evidence) is not dict
                or set(evidence) != {"path", "sha256", "bytes"}
                or evidence["path"] != str(source)
                or not source.is_file()
                or source.is_symlink()
                or evidence["bytes"] != source.stat().st_size
                or evidence["sha256"] != _api.sha256(source.read_bytes()).hexdigest()
            ):
                raise ValueError("retained installed-client submissions are unverified")
            # The checkpoint proves these two IDs came from actual completed
            # Python and CommonJS sends in this same durable campaign.
            retained_live_clients.update(("python_wheel", "js_tarball"))
        return {
            "checkpoint": checkpoint,
            "prior_plan": prior,
            "prior_attempts": durable["attempt_count"],
            "prior_sends": durable["possible_send_count"],
            "prior_reserved": prior_exposure,
            "passed_ids": passed,
            "retained_live_client_modes": retained_live_clients,
        }
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        _api.sqlite3.Error,
        RuntimeError,
        _api.json.JSONDecodeError,
    ) as exc:
        errors.append("continuation checkpoint unavailable or changed: " + str(exc))
        return None


def validate(
    plan,
    *,
    handlers,
    artifact_root,
    image_ids,
    required_ids=REQUIRED_IDS,
    catalog=SCENARIOS,
    required_pairs=REQUIRED_PAIRS,
    handler_source_path=None,
):
    """Fail closed before a target campaign is started or any request is sent."""
    from tools.gateway.evidence import dev12_completion_preflight as _api

    errors = []
    if type(plan) is not dict or set(plan) != {"envelope", "cases", "artifacts", "source_tree"}:
        raise ValueError("exact plan envelope/cases/artifacts/source_tree required")
    envelope, cases, artifacts = plan["envelope"], plan["cases"], plan["artifacts"]
    if type(envelope) is not dict or type(cases) is not list or type(artifacts) is not list:
        raise ValueError("typed plan sections required")
    if (
        envelope.get("max_admissions") != 512
        or envelope.get("max_possible_sends") != 512
        or envelope.get("max_inflight") != 2
        or envelope.get("ceiling_decimal") != "6.000000000"
        or envelope.get("window_hours") != 24
        or envelope.get("real_provider_calls") != 0
    ):
        errors.append("owner's exact prospective envelope absent")
    for field in ("rerun_headroom_admissions", "rerun_headroom_sends"):
        if type(envelope.get(field)) is not int or envelope[field] < 0:
            errors.append(f"declared {field} absent")
    try:
        rerun_headroom = _api._decimal(envelope.get("rerun_headroom_decimal"), "rerun headroom")
        prior_exposure = _api._decimal(
            envelope.get("preexisting_exposure_decimal"), "preexisting exposure"
        )
    except ValueError as exc:
        errors.append(str(exc))
        rerun_headroom = prior_exposure = _api.Decimal("6.000000001")
    if (
        not isinstance(envelope.get("campaign_id"), str)
        or not isinstance(envelope.get("budget_account_id"), str)
        or not isinstance(envelope.get("financial_owner_id"), str)
        or envelope.get("budget_account_id")
        in {"budget.synthetic.dev12", "budget.synthetic.dev12.correction01"}
        or envelope.get("financial_owner_id") in {"team.demo", "team.synthetic.dev12.correction01"}
    ):
        errors.append("distinct durable campaign/account/owner absent")
    if type(plan["source_tree"]) is not str or len(plan["source_tree"]) != 40:
        errors.append("exact source tree absent")
    root_input = _api.Path(artifact_root)
    root = root_input.resolve()
    if not root.is_dir() or root_input.is_symlink():
        errors.append("durable artifact directory unavailable")
    else:
        try:
            probe = root / "preflight-write-probe.json"
            with probe.open("a") as output:
                output.write('{"kind":"dev12_no_send_preflight"}\n')
                output.flush()
        except OSError:
            errors.append("durable artifact directory not exclusively writable")
    continuation = _api._continuation_context(plan, root, prior_exposure, errors)

    artifact_kinds = set()
    for artifact in artifacts:
        if type(artifact) is not dict or set(artifact) != {"kind", "path", "sha256"}:
            errors.append("incomplete artifact identity")
            continue
        kind, path, digest = artifact["kind"], artifact["path"], artifact["sha256"]
        if kind in artifact_kinds or kind not in {
            "python_wheel",
            "js_tarball",
            "service_image",
            "node_image",
        }:
            errors.append("duplicate/unknown artifact kind")
        artifact_kinds.add(kind)
        if kind.endswith("image"):
            if path not in image_ids or digest != path.removeprefix("sha256:"):
                errors.append(f"{kind}: exact local image unavailable")
        elif not _api.Path(path).is_file() or _api._hash(path) != digest:
            errors.append(f"{kind}: package bytes differ")
    if artifact_kinds != {"python_wheel", "js_tarball", "service_image", "node_image"}:
        errors.append("both installed packages and both frozen images required")

    by_id = {}
    covered = set()
    covered_pairs = set()
    client_modes = set()
    live_client_modes = set(continuation["retained_live_client_modes"]) if continuation else set()
    handler_identities = {}
    registered_runs = {}
    admissions = continuation["prior_attempts"] if continuation else 0
    sends = continuation["prior_sends"] if continuation else 0
    exposure = continuation["prior_reserved"] if continuation else _api.Decimal(0)
    admissions, sends, exposure = _validate_cases(
        _api,
        admissions,
        by_id,
        cases,
        catalog,
        client_modes,
        continuation,
        covered,
        covered_pairs,
        envelope,
        errors,
        exposure,
        handler_identities,
        handler_source_path,
        handlers,
        live_client_modes,
        plan,
        registered_runs,
        required_ids,
        required_pairs,
        root,
        sends,
    )
    if covered != required_ids:
        errors.append("assurance coverage incomplete: " + ", ".join(sorted(required_ids - covered)))
    if covered_pairs != required_pairs:
        errors.append(
            "scenario/variant inventory incomplete: "
            + ", ".join(
                f"{scenario}/{variant}"
                for scenario, variant in sorted(required_pairs - covered_pairs)
            )
        )
    if not {"python_wheel", "js_tarball"}.issubset(client_modes):
        errors.append("both installed client modes absent from executable inventory")
    if not {"python_wheel", "js_tarball"}.issubset(live_client_modes):
        errors.append("both installed clients absent from fresh target submissions")
    if (
        admissions + envelope.get("rerun_headroom_admissions", 513) > 512
        or sends + envelope.get("rerun_headroom_sends", 513) > 512
        or exposure + rerun_headroom > _api.Decimal("6.000000000")
    ):
        errors.append("mixed inventory exceeds aggregate admission/send/fictional USD limits")

    visited, visiting = set(), set()
    case_positions = {
        case["id"]: index
        for index, case in enumerate(cases)
        if type(case) is dict and type(case.get("id")) is str
    }

    def visit(ident):
        if ident in visiting:
            errors.append("cyclic prerequisite: " + ident)
            return
        if ident in visited:
            return
        visiting.add(ident)
        for dependency in by_id[ident]["prerequisites"] + by_id[ident]["late_dependencies"]:
            if dependency not in by_id:
                errors.append(f"{ident}: missing prerequisite {dependency}")
            else:
                if case_positions.get(dependency, len(cases)) >= case_positions.get(ident, -1):
                    errors.append(f"{ident}: executable order precedes prerequisite {dependency}")
                visit(dependency)
        visiting.remove(ident)
        visited.add(ident)

    for ident in by_id:
        visit(ident)
    terminal = [case for case in cases if case.get("phase") == "terminal"]
    fresh = [
        case
        for case in cases
        if case.get("evidence_kind") == "new" and case.get("max_possible_sends", 0)
    ]
    recovery = [case for case in cases if case.get("scenario_id") == "recovery_chain"]
    for case in terminal:
        must_precede = {row["id"] for row in fresh + recovery if row["id"] != case["id"]}
        missing = must_precede - set(case["prerequisites"])
        if missing:
            errors.append(f"{case['id']}: terminal pause precedes fresh sends")
    _api._validate_recovery_chain(by_id, errors)
    _api._validate_reporting_dependencies(cases, errors)
    return {
        "status": "PASS" if not errors else "BLOCKED_NO_SEND",
        "errors": errors,
        "case_count": len(by_id),
        "covered_ids": sorted(covered),
        "covered_pairs": [list(pair) for pair in sorted(covered_pairs)],
        "handler_identities": handler_identities,
        "max_admissions": admissions,
        "max_possible_sends": sends,
        "max_exposure_decimal": str(exposure),
    }


def _validate_cases(
    _api,
    admissions,
    by_id,
    cases,
    catalog,
    client_modes,
    continuation,
    covered,
    covered_pairs,
    envelope,
    errors,
    exposure,
    handler_identities,
    handler_source_path,
    handlers,
    live_client_modes,
    plan,
    registered_runs,
    required_ids,
    required_pairs,
    root,
    sends,
):
    for case in cases:
        if type(case) is not dict or set(case) != _api.CASE_FIELDS:
            errors.append("case has missing/extra fields")
            continue
        ident = case["id"]
        if type(ident) is not str or _api.CASE_ID.fullmatch(ident) is None or ident in by_id:
            errors.append("duplicate/invalid case ID")
            continue
        variant_spec, pair, handler = _validate_case_catalogue(
            _api,
            by_id,
            case,
            catalog,
            covered,
            covered_pairs,
            errors,
            handler_identities,
            handler_source_path,
            handlers,
            ident,
            registered_runs,
            required_ids,
            required_pairs,
        )
        if case["phase"] not in _api.PHASES:
            errors.append(f"{ident}: invalid phase")
        rejection = case["expected_rejection"]
        if (
            case["terminal_status"] not in {"completed", "failed", "unknown", "blocked", "reused"}
            or (case["evidence_kind"] == "new" and case["terminal_status"] == "reused")
            or (case["evidence_kind"] == "reused" and case["terminal_status"] != "reused")
            or (
                rejection is not None
                and (
                    type(rejection) is not dict
                    or set(rejection) != {"stage", "code", "http_status"}
                    or rejection.get("stage") not in _api._PRIMARY_STAGE_ORDER
                    or type(rejection.get("code")) is not str
                    or not _api.re.fullmatch(r"[A-Z][A-Z0-9_]{1,79}", rejection["code"])
                    or type(rejection.get("http_status")) is not int
                    or not 400 <= rejection["http_status"] <= 599
                )
            )
        ):
            errors.append(f"{ident}: terminal/rejection expectation unavailable")
        if case["installed_client_mode"] not in {
            "python_wheel",
            "js_tarball",
            "both",
            "none",
        } or case["scope"] != envelope.get("campaign_id"):
            errors.append(f"{ident}: unsupported client/scope")
        if case["installed_client_mode"] == "both":
            client_modes.update(("python_wheel", "js_tarball"))
        else:
            client_modes.add(case["installed_client_mode"])
        if case["evidence_kind"] == "new" and case["max_possible_sends"]:
            if case["installed_client_mode"] == "both":
                live_client_modes.update(("python_wheel", "js_tarball"))
            else:
                live_client_modes.add(case["installed_client_mode"])
        if pair[0].startswith("t47_") and case["installed_client_mode"] != "both":
            errors.append(f"{ident}: installed-client parity requires both artifacts")
        for key in (
            "prerequisites",
            "late_dependencies",
            "expected_stages",
            "evidence_paths",
            "predicates",
        ):
            if type(case[key]) is not list:
                errors.append(f"{ident}: {key} must be an explicit list")
        if (
            not case["expected_stages"]
            or set(case["expected_stages"]) - _api.STAGES
            or not case["evidence_paths"]
            or not case["predicates"]
            or not all(type(item) is str and item for item in case["predicates"])
        ):
            errors.append(f"{ident}: objective stage/evidence predicates absent")
        admissions, sends, exposure = _validate_case_custody_and_bounds(
            _api,
            admissions,
            case,
            continuation,
            errors,
            exposure,
            handler,
            ident,
            pair,
            plan,
            root,
            sends,
            variant_spec,
        )
        if case["evidence_kind"] == "reused":
            reuse = case["reuse_identity"]
            if (
                variant_spec is None
                or not variant_spec.reuse_permitted
                or type(reuse) is not dict
                or set(reuse) != {"source_commit", "evidence_path", "sha256", "correspondence"}
                or not _api.Path(reuse["evidence_path"]).is_file()
                or _api._hash(reuse["evidence_path"]) != reuse["sha256"]
                or type(reuse["source_commit"]) is not str
                or len(reuse["source_commit"]) != 40
                or type(reuse["correspondence"]) is not dict
                or set(reuse["correspondence"]) != {"current_inputs", "source_inputs", "reason"}
                or not reuse["correspondence"]["current_inputs"]
                or not reuse["correspondence"]["source_inputs"]
                or not reuse["correspondence"]["reason"]
                or case["max_admissions"]
                or case["max_possible_sends"]
            ):
                errors.append(f"{ident}: reused evidence lacks exact correspondence")
        elif case["evidence_kind"] != "new" or case["reuse_identity"] is not None:
            errors.append(f"{ident}: evidence provenance invalid")
    return admissions, sends, exposure


def _validate_case_catalogue(
    _api,
    by_id,
    case,
    catalog,
    covered,
    covered_pairs,
    errors,
    handler_identities,
    handler_source_path,
    handlers,
    ident,
    registered_runs,
    required_ids,
    required_pairs,
):
    by_id[ident] = case
    if (
        type(case["assurance_ids"]) is not list
        or (not case["assurance_ids"] and case["scenario_id"] != "recovery_chain")
        or any(item not in required_ids for item in case["assurance_ids"])
    ):
        errors.append(f"{ident}: invalid assurance IDs")
    else:
        covered.update(case["assurance_ids"])
    pair = (case["scenario_id"], case["variant"])
    scenario = catalog.get(pair[0])
    variant_spec = (
        scenario.variants.get(pair[1]) if isinstance(scenario, _api.ScenarioSpec) else None
    )
    if variant_spec is None or pair not in required_pairs:
        errors.append(f"{ident}: unregistered scenario/variant")
    elif pair in covered_pairs:
        errors.append(f"{ident}: duplicate scenario/variant {pair[0]}/{pair[1]}")
    else:
        covered_pairs.add(pair)
        if (
            case["assurance_ids"] != list(scenario.assurance_ids)
            or case["handler"] != variant_spec.handler
            or case["expected_stages"] != list(variant_spec.required_stages)
            or case["predicates"] != list(variant_spec.assertion_ids)
            or case["phase"] != variant_spec.phase
        ):
            errors.append(f"{ident}: case contract differs from fixed scenario/variant")
    handler = handlers.get(case["handler"]) if type(handlers) is dict else None
    if (
        not isinstance(handler, _api.CaseHandler)
        or handler.name != case["handler"]
        or pair not in handler.supported
    ):
        errors.append(f"{ident}: registered executable handler absent")
    else:
        try:
            allowed_handler_source = _api.Path(
                handler_source_path or _api.source_path_for_handler(handler.name)
            ).resolve()
            source = _api.Path(handler.source_path).resolve(strict=True)
            run_source = _api.Path(_api.inspect.getsourcefile(handler.run) or "").resolve(
                strict=True
            )
            digest = _api._hash(source)
            if (
                source != allowed_handler_source
                or run_source != source
                or handler.source_sha256 != digest
                or case["handler_source_sha256"] != digest
                or not _api.inspect.isfunction(handler.run)
                or getattr(handler.run, "dev12_placeholder", False)
            ):
                raise ValueError("source identity mismatch")
            handler_identities[handler.name] = {"path": str(source), "sha256": digest}
            previous = registered_runs.setdefault(id(handler.run), handler.name)
            if previous != handler.name:
                errors.append(
                    f"{ident}: one nominal function registered for multiple handler families"
                )
        except (OSError, ValueError, TypeError):
            errors.append(f"{ident}: registered handler source identity mismatch")
    return variant_spec, pair, handler


def _validate_case_custody_and_bounds(
    _api,
    admissions,
    case,
    continuation,
    errors,
    exposure,
    handler,
    ident,
    pair,
    plan,
    root,
    sends,
    variant_spec,
):
    if case["evidence_kind"] == "new":
        if continuation and ident in continuation["passed_ids"]:
            if not case["evidence_paths"] or not all(
                type(path) is str
                and _api._resolved_evidence(path, root).is_file()
                and not _api._resolved_evidence(path, root).is_symlink()
                for path in case["evidence_paths"]
            ):
                errors.append(f"{ident}: checkpoint-verified passed evidence missing")
        elif not case["evidence_paths"] or not all(
            _api._capture_path_ok(path, root) for path in case["evidence_paths"]
        ):
            errors.append(f"{ident}: evidence capture path unavailable or outside durable root")
    elif case["evidence_kind"] == "reused":
        if not case["evidence_paths"] or not all(
            type(path) is str
            and (root / path).resolve().is_relative_to(root)
            and (root / path).is_file()
            for path in case["evidence_paths"]
        ):
            errors.append(f"{ident}: reused evidence not retained under durable root")
    for label in ("fixture", "build"):
        ref = case[label]
        if (
            type(ref) is not dict
            or set(ref) != {"path", "sha256"}
            or not _api.Path(ref["path"]).is_file()
            or _api._hash(ref["path"]) != ref["sha256"]
        ):
            errors.append(f"{ident}: exact {label} bytes unavailable")
    if variant_spec is not None:
        try:
            expected_fixture = _api._fixture_path_for_scenario(pair[0]).resolve(strict=True)
            supplied_fixture = _api.Path(case["fixture"]["path"]).resolve(strict=True)
            if supplied_fixture != expected_fixture:
                errors.append(f"{ident}: fixture is not the fixed scenario input")
            if handler is not None and isinstance(handler, _api.CaseHandler):
                supplied_build = _api.Path(case["build"]["path"]).resolve(strict=True)
                if (
                    supplied_build != _api.Path(handler.source_path).resolve(strict=True)
                    or case["build"]["sha256"] != case["handler_source_sha256"]
                ):
                    errors.append(f"{ident}: build does not identify reviewed handler bytes")
        except (KeyError, OSError, TypeError, ValueError):
            errors.append(f"{ident}: fixed fixture/build identity unavailable")
    if case["source_tree"] != plan["source_tree"]:
        errors.append(f"{ident}: source tree differs")
    for field in ("max_admissions", "max_possible_sends"):
        if type(case[field]) is not int or not 0 <= case[field] <= 512:
            errors.append(f"{ident}: invalid {field}")
    if type(case["max_admissions"]) is int and type(case["max_possible_sends"]) is int:
        if not continuation or ident not in continuation["passed_ids"]:
            admissions += case["max_admissions"]
            sends += case["max_possible_sends"]
        if case["max_possible_sends"] > case["max_admissions"]:
            errors.append(f"{ident}: send bound exceeds admissions")
        retained_t60_repair = bool(
            continuation
            and continuation["checkpoint"].get("continuation_number") in (5, 6, 7, 8)
            and pair == ("t60", "composed")
            and ident == "case.t60.composed.continuation5"
            and (
                continuation["checkpoint"]["continuation_number"] == 5
                or ident in continuation["passed_ids"]
            )
            and case["evidence_kind"] == "new"
            and case["max_admissions"] == case["max_possible_sends"] == 0
        )
        if (
            variant_spec is not None
            and (
                case["max_admissions"] < variant_spec.minimum_admissions
                or case["max_possible_sends"] < variant_spec.minimum_possible_sends
            )
            and not retained_t60_repair
        ):
            errors.append(f"{ident}: case resource bound below fixed scenario minimum")
        imported_historical_underbound = (
            (
                pair == ("t50_e", "composed")
                and case["phase"] == "terminal"
                and case["evidence_kind"] == "new"
                and case["max_admissions"] == 0
                and case["max_possible_sends"] == 0
                and case["expected_stages"] == list(variant_spec.required_stages)
                and case["predicates"] == list(variant_spec.assertion_ids)
            )
            if variant_spec
            else False
        )
        retained_t49d_repair = bool(
            continuation
            and continuation["checkpoint"].get("continuation_number") in (4, 5, 6, 7, 8)
            and pair == ("t49_d", "composed")
            and ident == "case.t49_d.composed.continuation4"
            and (
                continuation["checkpoint"]["continuation_number"] == 4
                or ident in continuation["passed_ids"]
            )
            and case["evidence_kind"] == "new"
            and case["max_admissions"] == case["max_possible_sends"] == 0
        )
        if (
            variant_spec is not None
            and case["evidence_kind"] == "new"
            and "receiver" in variant_spec.required_stages
            and case["phase"] not in {"late_evidence", "resume"}
            and case["max_possible_sends"] < 1
            and not imported_historical_underbound
            and not retained_t49d_repair
        ):
            errors.append(f"{ident}: receiver case lacks a possible-send bound")
    try:
        case_exposure = _api._decimal(case["max_exposure_decimal"], ident)
        if not continuation or ident not in continuation["passed_ids"]:
            exposure += case_exposure
        if case["max_possible_sends"] and case_exposure == 0:
            errors.append(
                f"{ident}: positive possible-send bound lacks a finite exposure allocation"
            )
    except ValueError as exc:
        errors.append(str(exc))
    return admissions, sends, exposure


def _validate_continuation_inventory(_api, checkpoint, plan, prior, root):
    old, new = prior["envelope"], plan["envelope"]
    if (
        plan["artifacts"] != prior["artifacts"]
        or {key: value for key, value in new.items() if key != "preexisting_exposure_decimal"}
        != {key: value for key, value in old.items() if key != "preexisting_exposure_decimal"}
        or old["preexisting_exposure_decimal"] != "0.000000000"
        or len(plan["cases"]) != len(prior["cases"])
    ):
        raise ValueError("continuation changes original inputs or allowance")
    passed = set(checkpoint["passed_ids"])
    failed = checkpoint["failed_id"]
    latest_failed = checkpoint.get("latest_failed_id", failed)
    continuation_number = checkpoint.get("continuation_number")
    if continuation_number is None:
        continuation_number = (
            2 if latest_failed == failed + ".continuation1" else 1 if latest_failed == failed else 0
        )
    if continuation_number not in (1, 2, 3, 4, 5, 6, 7, 8):
        raise ValueError("unsupported or skipped continuation checkpoint")
    if (
        continuation_number == 1
        and latest_failed != failed
        or continuation_number == 2
        and latest_failed != failed + ".continuation1"
        or continuation_number == 3
        and (failed != "case.t47_a.composed" or latest_failed != failed)
        or continuation_number == 4
        and (failed != "case.t49_d.composed" or latest_failed != failed)
        or continuation_number == 5
        and (failed != "case.t60.composed" or latest_failed != failed)
        or continuation_number == 6
        and (failed != "case.t62_b.composed" or latest_failed != failed)
        or continuation_number == 7
        and (failed != "case.t62_e.composed" or latest_failed != failed)
        or continuation_number == 8
        and (failed != "case.t64.composed" or latest_failed != failed)
    ):
        raise ValueError("continuation failed case identity differs")
    previous = prior
    for previous_number in range(1, continuation_number):
        previous_path = root / ("plan.continuation" + str(previous_number) + ".json")
        previous_receipt_path = root / (
            "preflight-receipt-continuation" + str(previous_number) + ".json"
        )
        if (
            not previous_path.is_file()
            or previous_path.is_symlink()
            or not previous_receipt_path.is_file()
            or previous_receipt_path.is_symlink()
        ):
            raise ValueError("prior continuation plan or receipt absent")
        previous_bytes = previous_path.read_bytes()
        previous = _api.json.loads(previous_bytes)
        previous_receipt = _api.json.loads(previous_receipt_path.read_bytes())
        if (
            previous_receipt.get("plan_sha256") != _api.sha256(previous_bytes).hexdigest()
            or previous_receipt.get("source_tree") != previous.get("source_tree")
            or previous_receipt.get("case_count") != len(previous["cases"])
        ):
            raise ValueError("prior continuation receipt differs from exact plan")
    previous_failed = next(
        (case for case in previous["cases"] if case["id"] == latest_failed), None
    )
    if previous_failed is None or (
        continuation_number > 1
        and previous_failed["evidence_paths"] != ["cases/" + latest_failed + ".json"]
    ):
        raise ValueError("prior continuation failed case identity differs")
    previous_evidence = root / previous_failed["evidence_paths"][0]
    if (
        continuation_number > 1
        and continuation_number not in (5, 6, 7, 8)
        and (not previous_evidence.is_file() or previous_evidence.is_symlink())
    ):
        raise ValueError("prior continuation failed evidence absent")
    if continuation_number in (5, 6, 7, 8) and previous_evidence.exists():
        raise ValueError("operator case stopped before original evidence capture")
    if latest_failed in passed or len(passed) + 1 > len(plan["cases"]):
        raise ValueError("continuation checkpoint case census invalid")
    if len(previous["cases"]) != len(prior["cases"]):
        raise ValueError("prior continuation case census differs")
    repair_id = (
        (failed if continuation_number <= 2 else latest_failed)
        + ".continuation"
        + str(continuation_number)
    )
    for current, original, preceding in zip(
        plan["cases"], prior["cases"], previous["cases"], strict=True
    ):
        pair = (
            "scenario_id",
            "variant",
            "scope",
            "attempt_group",
            "assurance_ids",
            "handler",
            "phase",
            "predicates",
            "expected_stages",
            "fixture",
            "installed_client_mode",
        )
        if (
            any(current[key] != original[key] or current[key] != preceding[key] for key in pair)
            or current["prerequisites"]
            != [
                repair_id if value == latest_failed else value
                for value in preceding["prerequisites"]
            ]
            or current["late_dependencies"]
            != [
                repair_id if value == latest_failed else value
                for value in preceding["late_dependencies"]
            ]
        ):
            raise ValueError("continuation changes selected case identity")
        if preceding["id"] == latest_failed:
            expected_allocation = (0, 0, _api.Decimal(0))
            actual_allocation = (
                current["max_admissions"],
                current["max_possible_sends"],
                _api._decimal(current["max_exposure_decimal"], "repair exposure"),
            )
            if (
                current["id"] != repair_id
                or current["evidence_paths"] != ["cases/" + repair_id + ".json"]
                or actual_allocation != expected_allocation
            ):
                raise ValueError("continued failed-case allocation differs")
        elif (
            current["id"] != preceding["id"]
            or current["evidence_paths"] != preceding["evidence_paths"]
        ):
            raise ValueError("continuation changes retained case or evidence identity")
    return new, passed, continuation_number, latest_failed, previous_failed


def _read_unchanged_campaign(_api, database, new):
    wal = _api.Path(str(database) + "-wal")
    shm = _api.Path(str(database) + "-shm")
    journal = _api.Path(str(database) + "-journal")
    if (
        journal.exists()
        or wal.exists() != shm.exists()
        or any(path.is_symlink() for path in (wal, shm, journal))
    ):
        raise ValueError("campaign database has an incomplete or unsafe sidecar")
    had_wal = wal.exists()
    inspected = (database, wal) if had_wal else (database,)
    before = {
        path: (
            path.stat().st_size,
            path.stat().st_mtime_ns,
            _api.sha256(path.read_bytes()).hexdigest(),
        )
        for path in inspected
    }
    shm_size = shm.stat().st_size if had_wal else None
    # A stopped WAL-mode database can retain both sidecars. Read the WAL
    # through SQLite's read-only mode; immutable=1 would silently omit it.
    mode = "mode=ro" if had_wal else "immutable=1"
    with _api.sqlite3.connect("file:" + str(database) + "?" + mode, uri=True) as connection:
        rows = connection.execute(
            "SELECT record FROM dev12_campaigns WHERE campaign_id=?", (new["campaign_id"],)
        ).fetchall()
    if (
        any(
            not path.is_file()
            or path.is_symlink()
            or (
                path.stat().st_size,
                path.stat().st_mtime_ns,
                _api.sha256(path.read_bytes()).hexdigest(),
            )
            != before[path]
            for path in inspected
        )
        or wal.exists() != had_wal
        or shm.exists() != had_wal
        or (had_wal and (not shm.is_file() or shm.is_symlink() or shm.stat().st_size != shm_size))
        or journal.exists()
    ):
        raise ValueError("campaign database or WAL bytes changed during read")
    if len(rows) != 1:
        raise ValueError("original durable campaign record absent")
    durable = _api.json.loads(rows[0][0])
    return durable


def _validate_continuation_campaign(
    _api, checkpoint, continuation_number, durable, new, passed, previous_failed, prior_exposure
):
    prior_state = checkpoint["last_campaign"]
    if (
        durable != prior_state
        or durable["start_at"] != checkpoint["original_start_at"]
        or durable["expires_at"] != checkpoint["original_expires_at"]
        or durable["campaign_id"] != new["campaign_id"]
        or durable["budget_account_id"] != new["budget_account_id"]
        or durable["financial_owner_id"] != new["financial_owner_id"]
        or _api._decimal(durable["cumulative_reserved_decimal"], "durable exposure")
        != prior_exposure
    ):
        raise ValueError("continuation prior exposure or durable counters differ")
    if (
        type(durable["attempt_count"]) is not int
        or type(durable["possible_send_count"]) is not int
        or not 0 <= durable["possible_send_count"] <= durable["attempt_count"] <= 512
    ):
        raise ValueError("continuation prior attempt/send counters invalid")
    if continuation_number == 2 and (
        durable.get("paused") is not False
        or durable["attempt_count"] != 11
        or durable["possible_send_count"] != 11
        or prior_exposure != _api.Decimal("0.002900002")
    ):
        raise ValueError("second continuation changes observed stopped campaign")
    if continuation_number == 3 and (
        durable.get("paused") is not False
        or durable["attempt_count"] != 35
        or durable["possible_send_count"] != 35
        or prior_exposure != _api.Decimal("0.008000003")
        or len(passed) != 25
        or "case.t24_b.partial_write.continuation2" not in passed
    ):
        raise ValueError("third continuation changes observed stopped campaign")
    if continuation_number == 4 and (
        durable.get("paused") is not False
        or durable["attempt_count"] != 51
        or durable["possible_send_count"] != 51
        or prior_exposure != _api.Decimal("0.012200008")
        or len(passed) != 40
        or "case.t47_a.composed.continuation3" not in passed
        or previous_failed["max_possible_sends"] != 3
        or previous_failed["evidence_kind"] != "new"
    ):
        raise ValueError("fourth continuation changes observed stopped campaign")
    if continuation_number == 5 and (
        durable.get("paused") is not False
        or durable["attempt_count"] != 76
        or durable["possible_send_count"] != 76
        or prior_exposure != _api.Decimal("0.020400018")
        or len(passed) != 52
        or "case.t49_d.composed.continuation4" not in passed
        or previous_failed["max_possible_sends"] != 3
        or previous_failed["evidence_kind"] != "new"
    ):
        raise ValueError("fifth continuation changes observed stopped campaign")
    if continuation_number == 6 and (
        durable.get("paused") is not False
        or durable["attempt_count"] != 91
        or durable["possible_send_count"] != 91
        or prior_exposure != _api.Decimal("0.027600030")
        or len(passed) != 74
        or "case.t60.composed.continuation5" not in passed
        or "case.t62_a.composed" not in passed
        or previous_failed["scenario_id"] != "t62_b"
        or previous_failed["variant"] != "composed"
        or checkpoint.get("failed_attempt_ids") != []
        or checkpoint.get("latest_failed_evidence") is not None
    ):
        raise ValueError("sixth continuation changes no-send stopped campaign")
    if continuation_number == 7 and (
        durable.get("paused") is not False
        or durable["attempt_count"] != 91
        or durable["possible_send_count"] != 91
        or prior_exposure != _api.Decimal("0.027600030")
        or len(passed) != 77
        or not {
            "case.t62_b.composed.continuation6",
            "case.t62_c.composed",
            "case.t62_d.composed",
        }.issubset(passed)
        or previous_failed["scenario_id"] != "t62_e"
        or previous_failed["variant"] != "composed"
        or checkpoint.get("failed_attempt_ids") != []
        or checkpoint.get("latest_failed_evidence") is not None
    ):
        raise ValueError("seventh continuation changes no-send stopped campaign")
    if continuation_number == 8 and (
        durable.get("paused") is not False
        or durable["attempt_count"] != 91
        or durable["possible_send_count"] != 91
        or prior_exposure != _api.Decimal("0.027600030")
        or len(passed) != 78
        or "case.t62_e.composed.continuation7" not in passed
        or previous_failed["scenario_id"] != "t64"
        or previous_failed["variant"] != "composed"
        or checkpoint.get("failed_attempt_ids") != []
        or checkpoint.get("latest_failed_evidence") is not None
    ):
        raise ValueError("eighth continuation changes no-send stopped campaign")
