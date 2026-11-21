"""dev12_completion_runner checkpoint domain; entry points remain on the facade."""

from __future__ import annotations

from pathlib import Path


def _journal_rows(path: Path) -> list[dict]:
    from tools.gateway.evidence import dev12_completion_runner as _api

    if not path.is_file() or path.is_symlink():
        raise RuntimeError("existing append-only campaign journal absent")
    rows = []
    for number, line in enumerate(path.read_bytes().splitlines(), 1):
        try:
            row = _api.json.loads(line)
        except (UnicodeError, _api.json.JSONDecodeError) as exc:
            raise RuntimeError(f"campaign journal row {number} invalid") from exc
        if type(row) is not dict:
            raise RuntimeError(f"campaign journal row {number} invalid")
        rows.append(row)
    return rows


def continuation_checkpoint(root: Path, prior_plan: dict, prior_plan_bytes: bytes) -> dict:
    """Prove which exact original cases passed before a stopped campaign.

    A pass is accepted only with its retained evidence and independent durable
    correlation result.  No case result is inferred from its position alone.
    """
    from tools.gateway.evidence import dev12_completion_runner as _api
    from tools.gateway.evidence.dev12_completion_preflight import verify_case_result

    prior_receipt_path = root / "preflight-receipt.json"
    if not prior_receipt_path.is_file() or prior_receipt_path.is_symlink():
        raise RuntimeError("original host preflight receipt absent")
    prior_receipt = _api.json.loads(prior_receipt_path.read_bytes())
    if (
        prior_receipt.get("plan_sha256") != _api.sha256(prior_plan_bytes).hexdigest()
        or prior_receipt.get("source_tree") != prior_plan["source_tree"]
        or prior_receipt.get("case_count") != len(prior_plan["cases"])
    ):
        raise RuntimeError("original exact preflight receipt differs from plan bytes")
    journal = _api._journal_rows(root / "case-journal.jsonl")
    started = [row for row in journal if row.get("kind") == "campaign_started"]
    if len(started) != 1:
        raise RuntimeError("continuation requires exactly one original campaign start")
    identity = started[0].get("identity", {})
    if (
        identity.get("plan_sha256") != _api.sha256(_api._json_bytes(prior_plan)).hexdigest()
        or identity.get("campaign_id") != prior_plan["envelope"]["campaign_id"]
    ):
        raise RuntimeError("original journal does not bind original plan/campaign")
    # The on-disk plan has pretty JSON while the original release identity used
    # the canonical compact representation. Both are retained and checked.
    releases = _api._journal_rows(root / "release-identity.jsonl")
    if (
        not releases
        or releases[0].get("plan_sha256") != identity["plan_sha256"]
        or releases[0].get("source_tree") != prior_plan["source_tree"]
    ):
        raise RuntimeError("original release identity absent or changed")
    by_id = {case["id"]: case for case in prior_plan["cases"]}
    ended = [row for row in journal if row.get("kind") == "case_end"]
    if not ended or len({row.get("case_id") for row in ended}) != len(ended):
        raise RuntimeError("original case ends absent or repeated")
    passed = []
    failed = None
    for index, row in enumerate(ended[:11]):
        case = prior_plan["cases"][index]
        if (
            row.get("case_id") != case["id"]
            or row.get("scenario_id") != case["scenario_id"]
            or row.get("variant") != case["variant"]
        ):
            raise RuntimeError("original case journal differs from ordered inventory")
        if row.get("status") == "PASS" and failed is None:
            verified = verify_case_result(
                case,
                row.get("result"),
                root,
                actual=row.get("actual_correlation"),
                require_actual=True,
            )
            if verified["status"] != "PASS" or row.get("verification", {}).get("status") != "PASS":
                raise RuntimeError("historical PASS lacks intact source-bound evidence")
            passed.append(case["id"])
        elif row.get("status") == "FAIL" and failed is None and index == 10:
            failed = row
        else:
            raise RuntimeError("continuation cannot skip a nonterminal or later failed case")
    if failed is None or (failed["scenario_id"], failed["variant"]) != ("t24_b", "partial_write"):
        raise RuntimeError("only the observed partial-write stop is supported")
    failed_case = by_id[failed["case_id"]]
    evidence = root / failed_case["evidence_paths"][0]
    if not evidence.is_file() or evidence.is_symlink():
        raise RuntimeError("original failed case evidence absent")
    original = _api.json.loads(evidence.read_bytes())
    attempt_id = original.get("actual_attempt_id")
    payload = original.get("payload", {})
    if (
        not isinstance(attempt_id, str)
        or payload.get("late", {}).get("collection") != "accepted"
        or payload.get("late", {}).get("resume", {}).get("decision") != "refused"
        or payload.get("late", {})
        .get("status", {})
        .get("attempts", [{}])[0]
        .get("usage_revision", {})
        .get("cost_status")
        != "calculated"
    ):
        raise RuntimeError("original partial-write evidence is not the reviewed stop")
    continuation_number = 1
    latest_failed = failed
    latest_evidence = _api.snapshot(evidence)
    if len(ended) >= 12:
        continuation_number = 2
        cont1_plan_path = root / "plan.continuation1.json"
        cont1_receipt_path = root / "preflight-receipt-continuation1.json"
        if any(
            not path.is_file() or path.is_symlink()
            for path in (cont1_plan_path, cont1_receipt_path)
        ):
            raise RuntimeError("first continuation plan/receipt absent")
        cont1_raw = cont1_plan_path.read_bytes()
        cont1_plan = _api.json.loads(cont1_raw)
        cont1_receipt = _api.json.loads(cont1_receipt_path.read_bytes())
        cont1_case = cont1_plan["cases"][10]
        cont1_end = ended[11]
        cont1_gates = [
            row
            for row in _api._journal_rows(root / "release-gate.jsonl")
            if row.get("plan_sha256") == _api.sha256(cont1_raw).hexdigest()
        ]
        cont1_releases = [
            row
            for row in releases
            if row.get("kind") == "continuation_released"
            and row.get("plan_sha256") == _api.sha256(cont1_raw).hexdigest()
        ]
        if (
            cont1_receipt.get("plan_sha256") != _api.sha256(cont1_raw).hexdigest()
            or cont1_receipt.get("source_tree") != cont1_plan["source_tree"]
            or len(cont1_gates) != 1
            or cont1_gates[0].get("preflight_receipt_sha256")
            != _api.sha256(cont1_receipt_path.read_bytes()).hexdigest()
            or len(cont1_releases) != 1
            or cont1_releases[0].get("plan_sha256") != cont1_receipt["plan_sha256"]
            or cont1_releases[0].get("mounted_source")
            != cont1_receipt.get("mounted_source_identity")
            or cont1_releases[0].get("campaign_id") != identity["campaign_id"]
            or cont1_releases[0].get("original_start_at") != started[0]["allowance"]["start_at"]
            or cont1_case["id"] != failed["case_id"] + ".continuation1"
            or (
                cont1_case["max_admissions"],
                cont1_case["max_possible_sends"],
                cont1_case["max_exposure_decimal"],
            )
            != (0, 0, "0.000000000")
            or cont1_end.get("case_id") != cont1_case["id"]
            or cont1_end.get("status") != "FAIL"
            or (cont1_end.get("scenario_id"), cont1_end.get("variant"))
            != ("t24_b", "partial_write")
        ):
            raise RuntimeError("first continuation identity/result differs")
        cont1_evidence = root / cont1_case["evidence_paths"][0]
        if not cont1_evidence.is_file() or cont1_evidence.is_symlink():
            raise RuntimeError("first continuation failed evidence absent")
        cont1 = _api.json.loads(cont1_evidence.read_bytes())
        cont1_payload = cont1.get("payload", {})
        before, after = (
            cont1_payload.get("campaign_before", {}),
            cont1_payload.get("campaign_after", {}),
        )
        original_blockers = {
            item.removeprefix("unresolved_exposure:")
            for item in payload["late"]["resume"].get("blockers", [])
            if item.startswith("unresolved_exposure:")
        }
        if (
            cont1.get("actual_attempt_id") != attempt_id
            or cont1.get("checks", {}).get("t24_b.partial_write", {}).get("passed") is not False
            or cont1_payload.get("continuation_of_case_id") != failed["case_id"]
            or cont1_payload.get("new_resume_audit", {}).get("decision") != "resumed"
            or len(original_blockers) != 3
            or set(cont1_payload.get("new_resume_audit", {}).get("definite_no_send_reconciled", []))
            != original_blockers
            or cont1_payload.get("new_admissions") != 0
            or cont1_payload.get("new_possible_sends") != 0
            or any(
                before.get(key) != after.get(key)
                for key in (
                    "start_at",
                    "expires_at",
                    "attempt_count",
                    "possible_send_count",
                    "cumulative_reserved_decimal",
                )
            )
            or before.get("paused") is not True
            or after.get("paused") is not False
            or cont1_payload.get("receiver_arrivals_before") != 8
            or cont1_payload.get("receiver_arrivals_after") != 8
            or any(
                cont1_end["campaign_after"].get(key) != after.get(key)
                for key in (
                    "attempt_count",
                    "possible_send_count",
                    "cumulative_reserved_decimal",
                    "paused",
                )
            )
        ):
            raise RuntimeError("first continuation no-send resume evidence differs")
        latest_failed = cont1_end
        latest_evidence = _api.snapshot(cont1_evidence)
    elif len(ended) != 11:
        raise RuntimeError("unsupported stopped continuation chain length")
    failed_id = failed["case_id"]
    latest_plan_path = root / "plan.json"
    failed_attempt_ids = [attempt_id]
    retained_t47_live_attempt_ids = []
    retained_t47_live_evidence = None
    retained_t60_positive_attempt_ids = []
    if len(ended) > 12:
        continuation_number = 3
        cont2_plan_path = root / "plan.continuation2.json"
        cont2_receipt_path = root / "preflight-receipt-continuation2.json"
        if any(
            not path.is_file() or path.is_symlink()
            for path in (cont2_plan_path, cont2_receipt_path)
        ):
            raise RuntimeError("second continuation plan/receipt absent")
        cont2_raw = cont2_plan_path.read_bytes()
        cont2_plan = _api.json.loads(cont2_raw)
        cont2_receipt = _api.json.loads(cont2_receipt_path.read_bytes())
        cont2_gates = [
            row
            for row in _api._journal_rows(root / "release-gate.jsonl")
            if row.get("plan_sha256") == _api.sha256(cont2_raw).hexdigest()
        ]
        cont2_releases = [
            row
            for row in releases
            if row.get("kind") == "continuation_released"
            and row.get("plan_sha256") == _api.sha256(cont2_raw).hexdigest()
        ]
        if (
            cont2_receipt.get("plan_sha256") != _api.sha256(cont2_raw).hexdigest()
            or cont2_receipt.get("source_tree") != cont2_plan["source_tree"]
            or len(cont2_gates) != 1
            or cont2_gates[0].get("preflight_receipt_sha256")
            != _api.sha256(cont2_receipt_path.read_bytes()).hexdigest()
            or len(cont2_releases) != 1
            or cont2_releases[0].get("mounted_source")
            != cont2_receipt.get("mounted_source_identity")
            or cont2_releases[0].get("original_start_at") != started[0]["allowance"]["start_at"]
        ):
            raise RuntimeError("second continuation source/release identity differs")
        if len(ended) < 14:
            raise RuntimeError("second continuation lacks repaired case and next stop")
        for index, row in enumerate(ended[12:27], 10):
            case = cont2_plan["cases"][index]
            if (
                row.get("case_id") != case["id"]
                or row.get("scenario_id") != case["scenario_id"]
                or row.get("variant") != case["variant"]
                or row.get("status") != "PASS"
            ):
                raise RuntimeError("second continuation completed case order differs")
            verified = verify_case_result(
                case,
                row.get("result"),
                root,
                actual=row.get("actual_correlation"),
                require_actual=True,
            )
            if verified["status"] != "PASS" or row.get("verification", {}).get("status") != "PASS":
                raise RuntimeError("second continuation PASS evidence changed")
            passed.append(case["id"])
        latest_failed = ended[27]
        failed_case = cont2_plan["cases"][len(passed)]
        if (
            latest_failed.get("case_id") != failed_case["id"]
            or latest_failed.get("status") != "FAIL"
            or (latest_failed.get("scenario_id"), latest_failed.get("variant"))
            != ("t47_a", "composed")
        ):
            raise RuntimeError("only the observed installed-client T47a stop is supported")
        failed_id = failed_case["id"]
        t47_path = root / failed_case["evidence_paths"][0]
        if not t47_path.is_file() or t47_path.is_symlink():
            raise RuntimeError("installed-client failed evidence absent")
        t47 = _api.json.loads(t47_path.read_bytes())
        live = t47.get("payload", {}).get("live_target", {})
        python_reply = live.get("python_reply", {})
        python_status = live.get("python_status", {})
        js = live.get("commonjs_observed", {})
        js_reply, js_status = js.get("reply", {}), js.get("status", {})
        python_aid, js_aid = python_reply.get("attempt_id"), js_reply.get("attempt_id")
        before, after = live.get("before", {}), live.get("after", {})
        if (
            t47.get("actual_attempt_id") != failed_case["attempt_group"]
            or set(t47.get("checks", {})) != set(failed_case["predicates"])
            or any(value.get("passed") is not True for value in t47["checks"].values())
            or not python_aid
            or not js_aid
            or python_aid == js_aid
            or python_status.get("submission_state") != "completed"
            or js_status.get("submission_state") != "completed"
            or python_status.get("attempts", [{}])[0].get("attempt_id") != python_aid
            or js_status.get("attempts", [{}])[0].get("attempt_id") != js_aid
            or before.get("campaign", {}).get("attempt_count") != 33
            or after.get("campaign", {}).get("attempt_count") != 35
            or before.get("campaign", {}).get("possible_send_count") != 33
            or after.get("campaign", {}).get("possible_send_count") != 35
            or before.get("receiver_arrivals") != 22
            or after.get("receiver_arrivals") != 24
            or after.get("campaign", {}).get("cumulative_reserved_decimal") != "0.008000003"
            or latest_failed["campaign_after"] != after["campaign"]
        ):
            raise RuntimeError("installed-client failure is not the retained two-send case")
        failed_attempt_ids = [python_aid, js_aid]
        retained_t47_live_attempt_ids = [python_aid, js_aid]
        retained_t47_live_evidence = _api.snapshot(t47_path)
        latest_evidence = _api.snapshot(t47_path)
        latest_plan_path = cont2_plan_path
    if len(ended) > 28:
        continuation_number = 4
        cont3_plan_path = root / "plan.continuation3.json"
        cont3_receipt_path = root / "preflight-receipt-continuation3.json"
        if any(
            not path.is_file() or path.is_symlink()
            for path in (cont3_plan_path, cont3_receipt_path)
        ):
            raise RuntimeError("third continuation plan/receipt absent")
        cont3_raw = cont3_plan_path.read_bytes()
        cont3_plan = _api.json.loads(cont3_raw)
        cont3_receipt = _api.json.loads(cont3_receipt_path.read_bytes())
        cont3_gates = [
            row
            for row in _api._journal_rows(root / "release-gate.jsonl")
            if row.get("plan_sha256") == _api.sha256(cont3_raw).hexdigest()
        ]
        cont3_releases = [
            row
            for row in releases
            if row.get("kind") == "continuation_released"
            and row.get("plan_sha256") == _api.sha256(cont3_raw).hexdigest()
        ]
        if (
            cont3_receipt.get("plan_sha256") != _api.sha256(cont3_raw).hexdigest()
            or cont3_receipt.get("source_tree") != cont3_plan["source_tree"]
            or len(cont3_gates) != 1
            or cont3_gates[0].get("preflight_receipt_sha256")
            != _api.sha256(cont3_receipt_path.read_bytes()).hexdigest()
            or len(cont3_releases) != 1
            or cont3_releases[0].get("mounted_source")
            != cont3_receipt.get("mounted_source_identity")
            or cont3_releases[0].get("original_start_at") != started[0]["allowance"]["start_at"]
        ):
            raise RuntimeError("third continuation source/release identity differs")
        if len(ended) < 30:
            raise RuntimeError("third continuation lacks repaired case and next stop")
        for index, row in enumerate(ended[28:43], 25):
            case = cont3_plan["cases"][index]
            if (
                row.get("case_id") != case["id"]
                or row.get("scenario_id") != case["scenario_id"]
                or row.get("variant") != case["variant"]
                or row.get("status") != "PASS"
            ):
                raise RuntimeError("third continuation completed case order differs")
            verified = verify_case_result(
                case,
                row.get("result"),
                root,
                actual=row.get("actual_correlation"),
                require_actual=True,
            )
            if verified["status"] != "PASS" or row.get("verification", {}).get("status") != "PASS":
                raise RuntimeError("third continuation PASS evidence changed")
            passed.append(case["id"])
        latest_failed = ended[43]
        failed_case = cont3_plan["cases"][len(passed)]
        if (
            latest_failed.get("case_id") != failed_case["id"]
            or latest_failed.get("status") != "FAIL"
            or (latest_failed.get("scenario_id"), latest_failed.get("variant"))
            != ("t49_d", "composed")
        ):
            raise RuntimeError("only the observed native-evidence T49d stop is supported")
        t49_path = root / failed_case["evidence_paths"][0]
        if not t49_path.is_file() or t49_path.is_symlink():
            raise RuntimeError("native-evidence failed case absent")
        t49 = _api.json.loads(t49_path.read_bytes())
        observations = t49.get("payload", {}).get("observations", [])
        if len(observations) != 3:
            raise RuntimeError("native-evidence case did not retain three observations")
        aids = [item.get("reply", {}).get("reply", {}).get("attempt_id") for item in observations]
        out_domain = (
            observations[1]
            .get("status_before", {})
            .get("attempts", [{}])[0]
            .get("usage_revision", {})
        )
        if (
            len(set(aids)) != 3
            or any(not aid for aid in aids)
            or t49.get("actual_attempt_id") != aids[0]
            or t49.get("checks", {}).get("t49_d.out_of_domain", {}).get("passed") is not False
            or out_domain.get("revision") != 1
            or out_domain.get("cost_status") != "unknown"
            or "amount_decimal" in out_domain
            or out_domain.get("components", [{}])[0].get("presence") != "known"
            or out_domain.get("components", [{}])[0].get("quantity") != 999999999
            or any(
                item.get("status_after", {})
                .get("attempts", [{}])[0]
                .get("usage_revision", {})
                .get("revision")
                != 2
                or item.get("status_after", {})
                .get("attempts", [{}])[0]
                .get("usage_revision", {})
                .get("cost_status")
                != "calculated"
                for item in observations
            )
            or latest_failed["campaign_after"]["attempt_count"] != 51
            or latest_failed["campaign_after"]["possible_send_count"] != 51
            or latest_failed["campaign_after"]["cumulative_reserved_decimal"] != "0.012200008"
            or latest_failed["campaign_after"]["paused"]
        ):
            raise RuntimeError("native-evidence failure differs from retained observations")
        failed_id = failed_case["id"]
        failed_attempt_ids = aids
        latest_evidence = _api.snapshot(t49_path)
        latest_plan_path = cont3_plan_path
    if len(ended) > 44:
        import sqlite3

        continuation_number = 5
        cont4_plan_path = root / "plan.continuation4.json"
        cont4_receipt_path = root / "preflight-receipt-continuation4.json"
        if any(
            not path.is_file() or path.is_symlink()
            for path in (cont4_plan_path, cont4_receipt_path)
        ):
            raise RuntimeError("fourth continuation plan/receipt absent")
        cont4_raw = cont4_plan_path.read_bytes()
        cont4_plan = _api.json.loads(cont4_raw)
        cont4_receipt = _api.json.loads(cont4_receipt_path.read_bytes())
        cont4_gates = [
            row
            for row in _api._journal_rows(root / "release-gate.jsonl")
            if row.get("plan_sha256") == _api.sha256(cont4_raw).hexdigest()
        ]
        cont4_releases = [
            row
            for row in releases
            if row.get("kind") == "continuation_released"
            and row.get("plan_sha256") == _api.sha256(cont4_raw).hexdigest()
        ]
        if (
            cont4_receipt.get("plan_sha256") != _api.sha256(cont4_raw).hexdigest()
            or cont4_receipt.get("source_tree") != cont4_plan["source_tree"]
            or len(cont4_gates) != 1
            or cont4_gates[0].get("preflight_receipt_sha256")
            != _api.sha256(cont4_receipt_path.read_bytes()).hexdigest()
            or len(cont4_releases) != 1
            or cont4_releases[0].get("mounted_source")
            != cont4_receipt.get("mounted_source_identity")
            or cont4_releases[0].get("original_start_at") != started[0]["allowance"]["start_at"]
        ):
            raise RuntimeError("fourth continuation source/release identity differs")
        if len(ended) < 46:
            raise RuntimeError("fourth continuation lacks repaired case and next stop")
        for index, row in enumerate(ended[44:56], 40):
            case = cont4_plan["cases"][index]
            if (
                row.get("case_id") != case["id"]
                or row.get("scenario_id") != case["scenario_id"]
                or row.get("variant") != case["variant"]
                or row.get("status") != "PASS"
            ):
                raise RuntimeError("fourth continuation completed case order differs")
            verified = verify_case_result(
                case,
                row.get("result"),
                root,
                actual=row.get("actual_correlation"),
                require_actual=True,
            )
            if verified["status"] != "PASS" or row.get("verification", {}).get("status") != "PASS":
                raise RuntimeError("fourth continuation PASS evidence changed")
            passed.append(case["id"])
        latest_failed = ended[56]
        failed_case = cont4_plan["cases"][len(passed)]
        if (
            latest_failed.get("case_id") != failed_case["id"]
            or latest_failed.get("status") != "FAIL"
            or (latest_failed.get("scenario_id"), latest_failed.get("variant"))
            != ("t60", "composed")
            or (root / failed_case["evidence_paths"][0]).exists()
        ):
            raise RuntimeError("only the observed pre-reporting T60 stop is supported")
        with sqlite3.connect(f"file:{root / 'campaign.sqlite'}?immutable=1", uri=True) as db:
            positives = [
                _api.json.loads(row[0])
                for row in db.execute(
                    "SELECT record FROM dev12_submissions WHERE "
                    "json_extract(record,'$.work_key.step_id')=?",
                    ("step.completion02.t60.composed",),
                )
            ]
            guarded = {
                row[0]: row[1]
                for row in db.execute("SELECT attempt_id,submission_id FROM dev12_send_ownership")
            }
            usage = {
                row[0]
                for row in db.execute("SELECT DISTINCT attempt_id FROM dev12_usage_revisions")
            }
        receivers = [
            _api.json.loads(line) for line in (root / "receiver.jsonl").read_bytes().splitlines()
        ]
        by_principal = {row["work_key"]["principal_id"]: row for row in positives}
        if (
            len(positives) != 3
            or set(by_principal) != {"user.demo", "svc.vega", "svc.orion"}
            or len({row["attempt_id"] for row in positives}) != 3
            or any(
                row["submission_state"] != "completed"
                or row["settlement_state"] != "calculated"
                or row["campaign_id"] != prior_plan["envelope"]["campaign_id"]
                or guarded.get(row["attempt_id"]) != row["submission_id"]
                or row["attempt_id"] not in usage
                or sum(item.get("attempt_id") == row["attempt_id"] for item in receivers) != 1
                for row in positives
            )
            or by_principal["user.demo"]["trusted_identity"]["actor_id"] != "user.demo"
            or by_principal["svc.vega"]["trusted_identity"]["actor_id"] != "agent.vega"
            or by_principal["svc.orion"]["trusted_identity"]["actor_id"] != "svc.orion"
            or by_principal["svc.vega"]["request"]["metadata"]["initiating_user_id"] != "user.demo"
            or by_principal["svc.orion"]["request"]["metadata"].get("initiating_user_id")
            is not None
            or latest_failed["campaign_after"]["attempt_count"] != 76
            or latest_failed["campaign_after"]["possible_send_count"] != 76
            or latest_failed["campaign_after"]["cumulative_reserved_decimal"] != "0.020400018"
            or latest_failed["campaign_after"]["paused"]
            or latest_failed["receiver_arrivals_after"] != 65
            or len(receivers) < 65
            or "Cannot open a client instance more than once" not in latest_failed.get("error", "")
        ):
            raise RuntimeError("T60 stopped after a different send/reporting boundary")
        retained_t60_positive_attempt_ids = [
            by_principal[key]["attempt_id"] for key in ("user.demo", "svc.vega", "svc.orion")
        ]
        failed_id = failed_case["id"]
        failed_attempt_ids = retained_t60_positive_attempt_ids
        latest_evidence = None
        latest_plan_path = cont4_plan_path
    if len(ended) > 57:
        continuation_number = 6
        cont5_plan_path = root / "plan.continuation5.json"
        cont5_receipt_path = root / "preflight-receipt-continuation5.json"
        if any(
            not path.is_file() or path.is_symlink()
            for path in (cont5_plan_path, cont5_receipt_path)
        ):
            raise RuntimeError("fifth continuation plan/receipt absent")
        cont5_raw = cont5_plan_path.read_bytes()
        cont5_plan = _api.json.loads(cont5_raw)
        cont5_receipt = _api.json.loads(cont5_receipt_path.read_bytes())
        cont5_gates = [
            row
            for row in _api._journal_rows(root / "release-gate.jsonl")
            if row.get("plan_sha256") == _api.sha256(cont5_raw).hexdigest()
        ]
        cont5_releases = [
            row
            for row in releases
            if row.get("kind") == "continuation_released"
            and row.get("plan_sha256") == _api.sha256(cont5_raw).hexdigest()
        ]
        if (
            cont5_receipt.get("plan_sha256") != _api.sha256(cont5_raw).hexdigest()
            or cont5_receipt.get("source_tree") != cont5_plan["source_tree"]
            or len(cont5_gates) != 1
            or cont5_gates[0].get("preflight_receipt_sha256")
            != _api.sha256(cont5_receipt_path.read_bytes()).hexdigest()
            or len(cont5_releases) != 1
            or cont5_releases[0].get("mounted_source")
            != cont5_receipt.get("mounted_source_identity")
            or cont5_releases[0].get("original_start_at") != started[0]["allowance"]["start_at"]
        ):
            raise RuntimeError("fifth continuation source/release identity differs")
        if len(ended) < 59:
            raise RuntimeError("fifth continuation lacks repaired case and next stop")
        for index, row in enumerate(ended[57:79], 52):
            case = cont5_plan["cases"][index]
            if (
                row.get("case_id") != case["id"]
                or row.get("scenario_id") != case["scenario_id"]
                or row.get("variant") != case["variant"]
                or row.get("status") != "PASS"
            ):
                raise RuntimeError("fifth continuation completed case order differs")
            verified = verify_case_result(
                case,
                row.get("result"),
                root,
                actual=row.get("actual_correlation"),
                require_actual=True,
            )
            if verified["status"] != "PASS" or row.get("verification", {}).get("status") != "PASS":
                raise RuntimeError("fifth continuation PASS evidence changed")
            passed.append(case["id"])
        latest_failed = ended[79]
        failed_case = cont5_plan["cases"][len(passed)]
        latest_begins = [
            row
            for row in journal
            if row.get("kind") == "case_begin" and row.get("case_id") == failed_case["id"]
        ]
        if (
            len(latest_begins) != 1
            or latest_failed.get("case_id") != failed_case["id"]
            or latest_failed.get("status") != "FAIL"
            or (latest_failed.get("scenario_id"), latest_failed.get("variant"))
            != ("t62_b", "composed")
            or (root / failed_case["evidence_paths"][0]).exists()
            or "two accepted revisions at distinct UTC seconds required"
            not in latest_failed.get("error", "")
            or latest_begins[0].get("campaign_before") != latest_failed.get("campaign_after")
            or latest_begins[0].get("receiver_arrivals_before")
            != latest_failed.get("receiver_arrivals_after")
            or latest_failed["campaign_after"]["attempt_count"] != 91
            or latest_failed["campaign_after"]["possible_send_count"] != 91
            or latest_failed["campaign_after"]["cumulative_reserved_decimal"] != "0.027600030"
            or latest_failed["campaign_after"]["paused"]
        ):
            raise RuntimeError("T62b stopped after a different admission/send boundary")
        failed_id = failed_case["id"]
        failed_attempt_ids = []
        latest_evidence = None
        latest_plan_path = cont5_plan_path
    if len(ended) > 80:
        continuation_number = 7
        cont6_plan_path = root / "plan.continuation6.json"
        cont6_receipt_path = root / "preflight-receipt-continuation6.json"
        if any(
            not path.is_file() or path.is_symlink()
            for path in (cont6_plan_path, cont6_receipt_path)
        ):
            raise RuntimeError("sixth continuation plan/receipt absent")
        cont6_raw = cont6_plan_path.read_bytes()
        cont6_plan = _api.json.loads(cont6_raw)
        cont6_receipt = _api.json.loads(cont6_receipt_path.read_bytes())
        cont6_gates = [
            row
            for row in _api._journal_rows(root / "release-gate.jsonl")
            if row.get("plan_sha256") == _api.sha256(cont6_raw).hexdigest()
        ]
        cont6_releases = [
            row
            for row in releases
            if row.get("kind") == "continuation_released"
            and row.get("plan_sha256") == _api.sha256(cont6_raw).hexdigest()
        ]
        if (
            cont6_receipt.get("plan_sha256") != _api.sha256(cont6_raw).hexdigest()
            or cont6_receipt.get("source_tree") != cont6_plan["source_tree"]
            or len(cont6_gates) != 1
            or cont6_gates[0].get("preflight_receipt_sha256")
            != _api.sha256(cont6_receipt_path.read_bytes()).hexdigest()
            or len(cont6_releases) != 1
            or cont6_releases[0].get("mounted_source")
            != cont6_receipt.get("mounted_source_identity")
            or cont6_releases[0].get("original_start_at") != started[0]["allowance"]["start_at"]
        ):
            raise RuntimeError("sixth continuation source/release identity differs")
        if len(ended) < 83:
            raise RuntimeError("sixth continuation has a different completed-case count")
        for index, row in enumerate(ended[80:83], 74):
            case = cont6_plan["cases"][index]
            if (
                row.get("case_id") != case["id"]
                or row.get("scenario_id") != case["scenario_id"]
                or row.get("variant") != case["variant"]
                or row.get("status") != "PASS"
            ):
                raise RuntimeError("sixth continuation completed case order differs")
            verified = verify_case_result(
                case,
                row.get("result"),
                root,
                actual=row.get("actual_correlation"),
                require_actual=True,
            )
            if verified["status"] != "PASS" or row.get("verification", {}).get("status") != "PASS":
                raise RuntimeError("sixth continuation PASS evidence changed")
            passed.append(case["id"])
        unstarted = cont6_plan["cases"][len(passed)]
        if (
            len(passed) != 77
            or (unstarted["scenario_id"], unstarted["variant"]) != ("t62_e", "composed")
            or unstarted["id"] != "case.t62_e.composed"
            or (
                len(ended) == 83
                and any(
                    row.get("kind") in {"case_begin", "case_end"}
                    and row.get("case_id") == unstarted["id"]
                    for row in journal
                )
            )
            or (len(ended) == 83 and (root / unstarted["evidence_paths"][0]).exists())
            or ended[82]["campaign_after"]["attempt_count"] != 91
            or ended[82]["campaign_after"]["possible_send_count"] != 91
            or ended[82]["campaign_after"]["cumulative_reserved_decimal"] != "0.027600030"
            or ended[82]["campaign_after"]["paused"]
            or ended[82]["receiver_arrivals_after"] != 80
            or len(_api._journal_rows(root / "receiver.jsonl")) != 80
        ):
            raise RuntimeError("T62e did not stop before case begin with unchanged exposure")
        failed_id = unstarted["id"]
        latest_failed = {"case_id": failed_id, "campaign_after": ended[82]["campaign_after"]}
        failed_attempt_ids = []
        latest_evidence = None
        latest_plan_path = cont6_plan_path
    if len(ended) > 83:
        continuation_number = 8
        cont7_plan_path = root / "plan.continuation7.json"
        cont7_receipt_path = root / "preflight-receipt-continuation7.json"
        if any(
            not path.is_file() or path.is_symlink()
            for path in (cont7_plan_path, cont7_receipt_path)
        ):
            raise RuntimeError("seventh continuation plan/receipt absent")
        cont7_raw = cont7_plan_path.read_bytes()
        cont7_plan = _api.json.loads(cont7_raw)
        cont7_receipt = _api.json.loads(cont7_receipt_path.read_bytes())
        cont7_gates = [
            row
            for row in _api._journal_rows(root / "release-gate.jsonl")
            if row.get("plan_sha256") == _api.sha256(cont7_raw).hexdigest()
        ]
        cont7_releases = [
            row
            for row in releases
            if row.get("kind") == "continuation_released"
            and row.get("plan_sha256") == _api.sha256(cont7_raw).hexdigest()
        ]
        if (
            cont7_receipt.get("plan_sha256") != _api.sha256(cont7_raw).hexdigest()
            or cont7_receipt.get("source_tree") != cont7_plan["source_tree"]
            or len(cont7_gates) != 1
            or cont7_gates[0].get("preflight_receipt_sha256")
            != _api.sha256(cont7_receipt_path.read_bytes()).hexdigest()
            or len(cont7_releases) != 1
            or cont7_releases[0].get("mounted_source")
            != cont7_receipt.get("mounted_source_identity")
            or cont7_releases[0].get("original_start_at") != started[0]["allowance"]["start_at"]
        ):
            raise RuntimeError("seventh continuation source/release identity differs")
        if len(ended) != 84:
            raise RuntimeError("seventh continuation has a different completed-case count")
        completed = cont7_plan["cases"][77]
        row = ended[83]
        if (
            (completed["scenario_id"], completed["variant"]) != ("t62_e", "composed")
            or row.get("case_id") != completed["id"]
            or row.get("status") != "PASS"
            or row.get("scenario_id") != completed["scenario_id"]
            or row.get("variant") != completed["variant"]
        ):
            raise RuntimeError("seventh continuation completed case differs")
        verified = verify_case_result(
            completed,
            row.get("result"),
            root,
            actual=row.get("actual_correlation"),
            require_actual=True,
        )
        if verified["status"] != "PASS" or row.get("verification", {}).get("status") != "PASS":
            raise RuntimeError("seventh continuation PASS evidence changed")
        passed.append(completed["id"])
        unstarted = cont7_plan["cases"][len(passed)]
        requests = [
            item
            for item in journal
            if item.get("kind") == "browser_capture_requested"
            and item.get("case_id") == unstarted["id"]
        ]
        if (
            len(passed) != 78
            or (unstarted["scenario_id"], unstarted["variant"]) != ("t64", "composed")
            or unstarted["id"] != "case.t64.composed"
            or len(requests) != 1
            or requests[0].get("at", 0) <= row.get("at", 0)
            or requests[0].get("source_tree") != cont7_plan["source_tree"]
            or requests[0].get("campaign_id") != cont7_plan["envelope"]["campaign_id"]
            or requests[0].get("operator_url") != row["campaign_after"]["endpoints"]["operator"]
            or requests[0].get("expected_evidence_path")
            != str(root / "operator-browser-evidence.json")
            or any(
                item.get("kind") in {"case_begin", "case_end"}
                and item.get("case_id") == unstarted["id"]
                for item in journal
            )
            or (root / unstarted["evidence_paths"][0]).exists()
            or (root / "operator-browser-evidence.json").exists()
            or row["campaign_after"]["attempt_count"] != 91
            or row["campaign_after"]["possible_send_count"] != 91
            or row["campaign_after"]["cumulative_reserved_decimal"] != "0.027600030"
            or row["campaign_after"]["paused"]
            or row["receiver_arrivals_after"] != 80
            or len(_api._journal_rows(root / "receiver.jsonl")) != 80
        ):
            raise RuntimeError("T64 capture did not stop before case begin with unchanged exposure")
        failed_id = unstarted["id"]
        latest_failed = {"case_id": failed_id, "campaign_after": row["campaign_after"]}
        failed_attempt_ids = []
        latest_evidence = None
        latest_plan_path = cont7_plan_path
    return {
        "passed_ids": passed,
        "failed_id": failed_id,
        "original_failed_id": failed["case_id"],
        "latest_failed_id": latest_failed["case_id"],
        "latest_failed_evidence": latest_evidence,
        "continuation_number": continuation_number,
        "failed_attempt_id": attempt_id,
        "failed_attempt_ids": failed_attempt_ids,
        "retained_t47_live_attempt_ids": retained_t47_live_attempt_ids,
        "retained_t47_live_evidence": retained_t47_live_evidence,
        "retained_t60_positive_attempt_ids": retained_t60_positive_attempt_ids,
        "failed_evidence": _api.snapshot(evidence),
        "latest_plan_path": str(latest_plan_path),
        "original_plan_sha256": _api.sha256(prior_plan_bytes).hexdigest(),
        "original_release_plan_sha256": identity["plan_sha256"],
        "original_source_tree": prior_plan["source_tree"],
        "original_mounted_source": releases[0].get("mounted_source"),
        "original_start_at": started[0]["allowance"]["start_at"],
        "original_expires_at": started[0]["allowance"]["expires_at"],
        "last_campaign": latest_failed["campaign_after"],
        "prior_journal_rows": len(journal),
    }
