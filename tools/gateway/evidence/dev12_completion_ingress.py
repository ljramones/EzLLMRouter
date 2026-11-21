"""dev12_completion_handlers ingress domain; entry points remain on the facade."""

from __future__ import annotations


def ingress_identity(runtime, case):
    """Normal authenticated HTTP ingress; reject before any durable intent."""
    from tools.gateway.evidence import dev12_completion_handlers as _api

    if (case["scenario_id"], case["variant"]) == ("t03", "composed"):
        from tools.gateway.evidence.dev12_completion_boundary_handlers import taint_boundary

        return taint_boundary(runtime, case)
    if case["scenario_id"] in {"t79_c", "t79_d"} and case["variant"] == "composed":
        from ezllmrouter_server.successor_contract import (
            domain_digest,
            work_digest,
            schema_valid,
            SCHEMAS,
        )
        from ezllmrouter_server.successor_plan import execution_eligible

        request = _api._case_request(runtime, case, "DELEGATED_RERANK")
        before = _api._census(runtime)
        first = _api._post(runtime, request, _api._headers(runtime, "DELEGATED_RERANK"))
        admitted = _api._census(runtime)
        sid = first["reply"].get("handle", {}).get("submission_id")
        if not sid:
            raise AssertionError("asserted commission control missing")
        record = runtime.store.successor_get(sid)
        original = _api.deepcopy(record["admission_snapshot"])
        original_digest = record["admission_snapshot_digest"]
        original_work_digest = record["work_digest"]
        original_plan = _api.deepcopy(record["signed_plan"])
        current = runtime.authority.current_context(record, _api._current_utc())
        changed = _api.deepcopy(request)
        changed["metadata"]["commission"]["reference"] = "commission.changed.assertion"
        conflict = _api._post(runtime, changed, _api._headers(runtime, "DELEGATED_RERANK"))
        status_tamper = _api.deepcopy(original)
        status_tamper["commission"] = {
            "status": "verified",
            "evidence_scope": "synthetic.review",
            "evidence_ref": "evidence.synthetic",
        }
        reason_tamper = _api.deepcopy(original)
        reason_tamper["delegation"]["absence_reason"] = "not_yet_issued"
        link_tamper = _api.deepcopy(original)
        link_tamper["work_digest"] = "sha256:" + "0" * 64
        rejected = {
            name: not execution_eligible(
                original_plan,
                record["request"],
                record["canonical_work"],
                changed_snapshot,
                current,
            )
            for name, changed_snapshot in (
                ("status", status_tamper),
                ("reason", reason_tamper),
                ("link", link_tamper),
            )
        }
        at = _api._current_utc()
        evidence = {
            "kind": "later_synthetic_commission_review",
            "status": "recorded_evidence_only",
            "observed_at": at,
            "original_admission_digest": original_digest,
        }
        runtime.store.successor_append_evidence(sid, "later_commission_review", at, evidence)
        duplicate = _api._post(runtime, request, _api._headers(runtime, "DELEGATED_RERANK"))
        after = _api._census(runtime)
        retained = runtime.store.successor_get(sid)
        no_retro = (
            retained["admission_snapshot"] == original
            and retained["admission_snapshot_digest"] == original_digest
            and retained["work_digest"] == original_work_digest
            and retained["signed_plan"] == original_plan
            and duplicate["reply"].get("handle", {}).get("submission_id") == sid
            and after["submissions"] == admitted["submissions"]
            and after["receiver_arrivals"] == admitted["receiver_arrivals"]
        )
        if case["scenario_id"] == "t79_c":
            checks = {
                "t79_c.caller_assertion_mutation": (
                    conflict["http_status"] == 409
                    and conflict["reply"].get("code") == "WORK_CONFLICT"
                    and after["submissions"] == before["submissions"] + 1,
                    "Changed canonical caller commission under same WorkKey conflicts",
                ),
                "t79_c.signed_status_reason_tamper": (
                    schema_valid(status_tamper, SCHEMAS["$defs"]["AdmissionSnapshot"])
                    and schema_valid(reason_tamper, SCHEMAS["$defs"]["AdmissionSnapshot"])
                    and rejected["status"]
                    and rejected["reason"],
                    "Schema-valid assessment status and reason edits fail unchanged signed admission binding",
                ),
                "t79_c.digest_link_tamper": (
                    rejected["link"]
                    and original["work_digest"] == work_digest(record["canonical_work"])
                    and domain_digest("ezllmrouter-admission-v1\n", original) == original_digest,
                    "Changing snapshot work-domain_digest link cannot validate against original plan",
                ),
            }
        else:
            checks = {
                "t79_d.later_verification_no_retroactive_upgrade": (
                    no_retro
                    and rejected["status"]
                    and retained["admission_snapshot"]["commission"]
                    == {"status": "asserted", "evidence_scope": "record_only"},
                    "Later linked review evidence did not upgrade original admission or authorize replay",
                )
            }
        return _api._evidence(
            runtime,
            case,
            {
                "ingress": {
                    "initial_http": first["http_status"],
                    "changed_caller_http": conflict["http_status"],
                    "duplicate_http": duplicate["http_status"],
                },
                "admission": {
                    "submission_id": sid,
                    "original_snapshot_digest": original_digest,
                    "new_submissions": after["submissions"] - before["submissions"],
                },
            },
            checks,
            {
                "first": first,
                "conflict": conflict,
                "duplicate": duplicate,
                "record": record,
                "retained": retained,
                "evidence": evidence,
                "tampered": {"status": status_tamper, "reason": reason_tamper, "link": link_tamper},
                "rejected": rejected,
                "before": before,
                "after": after,
            },
            record["attempt_id"],
        )
    if (
        case["scenario_id"] in {"t77_a", "t77_b", "t77_c", "t77_d"}
        and case["variant"] == "composed"
    ):
        from ezllmrouter_server.successor_contract import (
            SCHEMAS,
            schema_valid,
            domain_digest,
            work_digest,
        )
        from ezllmrouter_server.successor_plan import execution_eligible

        request = _api._case_request(runtime, case)
        before = _api._census(runtime)
        missing = None
        if case["scenario_id"] == "t77_d":
            missing_headers = _api._headers(runtime)
            del missing_headers["Authorization"]
            missing = _api._post(runtime, request, missing_headers)
        response = _api._post(runtime, request, _api._headers(runtime))
        after = _api._census(runtime)
        sid = response["reply"].get("handle", {}).get("submission_id")
        if not sid:
            raise AssertionError("shared-envelope control not admitted")
        record = runtime.store.successor_get(sid)
        snapshot = record["admission_snapshot"]
        plan = record["signed_plan"]
        current = runtime.authority.current_context(record, _api._current_utc())
        original_eligible = execution_eligible(
            plan, record["request"], record["canonical_work"], snapshot, current
        )
        supplemental = {}
        if case["scenario_id"] == "t77_a":
            checks = {
                "t77_a.applicable_fields_reasons": (
                    bool(
                        original_eligible
                        and snapshot["work_digest"] == work_digest(record["canonical_work"])
                        and snapshot["commission"]
                        == {
                            "status": "absent",
                            "evidence_scope": "none",
                            "absence_reason": "caller_omitted",
                        }
                        and snapshot["delegation"]
                        == {
                            "coverage": "none",
                            "verified_link_indices": [],
                            "absence_reason": "not_applicable",
                        }
                    ),
                    "Applicable direct-human snapshot includes exact work linkage and reasoned absence",
                )
            }
        elif case["scenario_id"] == "t77_b":
            invalid_reason = _api.deepcopy(snapshot)
            invalid_reason["commission"]["absence_reason"] = "fabricated"
            inconsistent = _api.deepcopy(snapshot)
            inconsistent["delegation"]["verified_link_indices"] = [0]
            checks = {
                "t77_b.invalid_reason": (
                    not schema_valid(invalid_reason, SCHEMAS["$defs"]["AdmissionSnapshot"])
                    and not execution_eligible(
                        plan, record["request"], record["canonical_work"], invalid_reason, current
                    ),
                    "Unregistered absence reason fails bounded schema and signed admission binding",
                ),
                "t77_b.inconsistent_combination": (
                    schema_valid(inconsistent, SCHEMAS["$defs"]["AdmissionSnapshot"])
                    and not execution_eligible(
                        plan, record["request"], record["canonical_work"], inconsistent, current
                    ),
                    "Syntactically valid none-coverage plus verified link fails semantic/signature binding",
                ),
            }
            supplemental = {"invalid_reason": invalid_reason, "inconsistent": inconsistent}
        elif case["scenario_id"] == "t77_c":
            # A separate pre-successor row is read through the additive store
            # without backfilling a fictional admission assessment.
            from ezllmrouter_server.store import SQLiteStore

            old_path = runtime.root / "cases" / (case["id"] + "-preadmission.sqlite")
            old_path.parent.mkdir(exist_ok=True)
            if old_path.exists():
                raise RuntimeError("preadmission evidence fixture already exists")
            old = SQLiteStore(old_path)
            old_record = {
                "submission_id": "submission.preadmission.synthetic",
                "contract_version": "0.2",
                "attribution_applicability": "pre_admission",
            }
            try:
                with old._lock:
                    old.db.execute(
                        "CREATE TABLE IF NOT EXISTS dev12_preadmission_fixture "
                        "(id TEXT PRIMARY KEY, record TEXT NOT NULL)"
                    )
                    old.db.execute(
                        "INSERT INTO dev12_preadmission_fixture VALUES (?,?)",
                        ("old", _api.json.dumps(old_record, sort_keys=True)),
                    )
                    old.db.commit()
            finally:
                old.close()
            reopened = SQLiteStore(old_path)
            try:
                readback = _api.json.loads(
                    reopened.db.execute(
                        "SELECT record FROM dev12_preadmission_fixture WHERE id='old'"
                    ).fetchone()[0]
                )
            finally:
                reopened.close()
            checks = {
                "t77_c.preadmission_applicability": (
                    readback == old_record and "admission_snapshot" not in readback,
                    "Pre-admission fixture remains explicitly inapplicable without invented snapshot",
                ),
                "t77_c.legacy_applicability": (
                    readback["contract_version"] == "0.2"
                    and snapshot["snapshot_version"] == "dev12-admission@1"
                    and record["contract_version"] == "0.3",
                    "Legacy wire row and successor admission keep distinct applicability",
                ),
            }
            supplemental = {"legacy_path": str(old_path), "readback": readback}
        else:
            checks = {
                "t77_d.absence_not_authority": (
                    snapshot["commission"]["absence_reason"] == "caller_omitted"
                    and missing["http_status"] == 401
                    and after["submissions"] == before["submissions"] + 1
                    and after["receiver_arrivals"] == before["receiver_arrivals"] + 1
                    and original_eligible,
                    "Missing commission remains allowed only with independently authenticated identity",
                )
            }
        return _api._evidence(
            runtime,
            case,
            {
                "ingress": {
                    "positive_http": response["http_status"],
                    "missing_auth_http": missing["http_status"] if missing else "not_tested",
                },
                "admission": {
                    "submission_id": sid,
                    "snapshot_digest": domain_digest("ezllmrouter-admission-v1\n", snapshot),
                    "snapshot_valid": schema_valid(snapshot, SCHEMAS["$defs"]["AdmissionSnapshot"]),
                },
            },
            checks,
            {
                "response": response,
                "record": record,
                "missing": missing,
                "before": before,
                "after": after,
                "supplemental": supplemental,
            },
            record["attempt_id"],
        )
    if case["scenario_id"] in {"t79_a", "t79_b"} and case["variant"] == "composed":
        direct = _api._case_request(runtime, case, "DIRECT_DOCUMENT")
        delegated = _api._case_request(runtime, case, "DELEGATED_RERANK")
        before = _api._census(runtime)
        first = _api._post(runtime, direct, _api._headers(runtime, "DIRECT_DOCUMENT"))
        second = _api._post(runtime, delegated, _api._headers(runtime, "DELEGATED_RERANK"))
        admitted = _api._census(runtime)
        direct_sid = first["reply"].get("handle", {}).get("submission_id")
        delegated_sid = second["reply"].get("handle", {}).get("submission_id")
        if not direct_sid or not delegated_sid:
            raise AssertionError("commission control admissions missing")
        direct_record = runtime.store.successor_get(direct_sid)
        delegated_record = runtime.store.successor_get(delegated_sid)
        absence = direct_record["admission_snapshot"]["commission"]
        asserted = delegated_record["admission_snapshot"]["commission"]
        forged = _api.deepcopy(delegated)
        forged["work_selector"]["step_id"] += ".forged"
        forged["metadata"]["delegation"][-1]["to_actor_id"] = "agent.forged"
        forged["metadata"]["commission"]["reference"] = "commission.claimed.authority"
        negative = _api._post(runtime, forged, _api._headers(runtime, "DELEGATED_RERANK"))
        after = _api._census(runtime)
        no_negative_admission = (
            after["submissions"] == admitted["submissions"]
            and after["receiver_arrivals"] == admitted["receiver_arrivals"]
        )
        if case["scenario_id"] == "t79_a":
            checks = {
                "t79_a.absent_commission_reason": (
                    absence
                    == {
                        "status": "absent",
                        "evidence_scope": "none",
                        "absence_reason": "caller_omitted",
                    }
                    and first["status"].get("submission_state") == "completed",
                    "Omitted commission receives explicit caller-omitted assessment",
                ),
                "t79_a.asserted_record_only": (
                    asserted == {"status": "asserted", "evidence_scope": "record_only"}
                    and second["status"].get("submission_state") == "completed"
                    and direct_record["work_digest"] != delegated_record["work_digest"],
                    "Caller asserted commission is recorded without verified authority",
                ),
            }
        else:
            checks = {
                "t79_b.record_only_no_execution_authority": (
                    asserted["evidence_scope"] == "record_only"
                    and negative["http_status"] == 422
                    and no_negative_admission
                    and after["receiver_arrivals"] == before["receiver_arrivals"] + 2,
                    "Asserted record-only commission could not authorize forged executing actor",
                )
            }
        return _api._evidence(
            runtime,
            case,
            {
                "ingress": {
                    "direct_http": first["http_status"],
                    "delegated_http": second["http_status"],
                    "forged_http": negative["http_status"],
                },
                "admission": {
                    "direct_submission": direct_sid,
                    "delegated_submission": delegated_sid,
                    "negative_admitted": not no_negative_admission,
                },
            },
            checks,
            {
                "direct": first,
                "delegated": second,
                "forged": negative,
                "direct_record": direct_record,
                "delegated_record": delegated_record,
                "before": before,
                "after_positive": admitted,
                "after": after,
            },
            delegated_record["attempt_id"],
        )
    if (
        case["scenario_id"] in {"t78_a", "t78_b", "t78_c", "t78_d"}
        and case["variant"] == "composed"
    ):
        from ezllmrouter_server.successor_contract import classify_request

        scenario = case["scenario_id"]
        vector = (
            "DIRECT_DOCUMENT"
            if scenario == "t78_a"
            else "AUTONOMOUS_QUERY"
            if scenario == "t78_c"
            else "DELEGATED_RERANK"
        )
        request = _api._case_request(runtime, case, vector)
        before = _api._census(runtime)
        positive = _api._post(runtime, request, _api._headers(runtime, vector))
        admitted = _api._census(runtime)
        sid = positive["reply"].get("handle", {}).get("submission_id")
        if not sid:
            raise AssertionError("attribution control was not admitted")
        record = runtime.store.successor_get(sid)
        metadata = record["canonical_work"]["metadata"]
        identity = record["canonical_work"]["trusted"]
        negatives = {}
        classifications = {}
        if scenario == "t78_d":
            forged = _api.deepcopy(request)
            forged["work_selector"]["step_id"] += ".forged"
            forged["metadata"]["delegation"][-1]["to_actor_id"] = "agent.forged"
            cyclic = _api.deepcopy(request)
            cyclic["work_selector"]["step_id"] += ".cycle"
            cyclic["metadata"]["delegation"][-1]["to_actor_id"] = "user.demo"
            excess = _api.deepcopy(request)
            excess["work_selector"]["step_id"] += ".excess"
            excess["metadata"]["delegation"] = excess["metadata"]["delegation"] * 20
            asserted = _api.deepcopy(request)
            asserted["work_selector"]["step_id"] += ".asserted"
            asserted["metadata"]["delegation"][-1]["to_actor_id"] = "agent.forged"
            asserted["metadata"]["commission"]["reference"] = "commission.forged"
            context = runtime.contexts_by_credential[runtime.credentials[vector]]
            for name, value in (
                ("forged", forged),
                ("cycle", cyclic),
                ("excess", excess),
                ("asserted", asserted),
            ):
                classifications[name] = classify_request(value, context)
                negatives[name] = _api._post(runtime, value, _api._headers(runtime, vector))
        after = _api._census(runtime)
        same_control = (
            positive["status"]
            and positive["status"].get("submission_state") == "completed"
            and admitted["submissions"] == before["submissions"] + 1
            and admitted["receiver_arrivals"] == before["receiver_arrivals"] + 1
        )
        if scenario == "t78_a":
            checks = {
                "t78_a.direct_binding": (
                    bool(
                        same_control
                        and metadata["invocation_mode"] == "direct_human"
                        and identity["actor_id"] == metadata["initiating_user_id"]
                        and identity["actor_kind"] == "human"
                    ),
                    "Authenticated direct human is both actor and initiating user",
                ),
                "t78_a.chain_representation": (
                    metadata["delegation"] == [] and "parent_run_id" not in metadata,
                    "Direct-human canonical work has no invented delegation chain",
                ),
            }
        elif scenario == "t78_b":
            links = metadata["delegation"]
            checks = {
                "t78_b.delegated_binding": (
                    bool(
                        same_control
                        and identity["actor_kind"] == "agent"
                        and identity["actor_id"] == links[-1]["to_actor_id"]
                        and metadata["initiating_user_id"] != identity["actor_id"]
                    ),
                    "Authenticated executing agent remains distinct from initiator",
                ),
                "t78_b.ordered_asserted_links": (
                    len(links) == 2
                    and links[0]["to_actor_id"] == links[1]["from_actor_id"]
                    and links[0]["to_run_id"] == links[1]["from_run_id"]
                    and record["admission_snapshot"]["delegation"]["coverage"] == "none"
                    and record["admission_snapshot"]["delegation"]["absence_reason"]
                    == "unavailable",
                    "Ordered caller links are retained as assertions without invented verification",
                ),
            }
        elif scenario == "t78_c":
            checks = {
                "t78_c.autonomous_owner": (
                    bool(
                        same_control
                        and identity["actor_kind"] == "service"
                        and identity["charging_owner_id"]
                        == runtime.plan["envelope"]["financial_owner_id"]
                    ),
                    "Autonomous service has trusted fictional financial owner",
                ),
                "t78_c.no_fictitious_person": (
                    "initiating_user_id" not in metadata
                    and "initiating_user_id" not in record["canonical_work"]["trusted"],
                    "Autonomous canonical work contains no fabricated initiating human",
                ),
            }
        else:
            no_admission = (
                after["submissions"] == admitted["submissions"]
                and after["receiver_arrivals"] == admitted["receiver_arrivals"]
            )
            checks = {
                "t78_d.forged_endpoint": (
                    classifications["forged"] == "SEMANTIC_INVALID"
                    and negatives["forged"]["http_status"] == 422
                    and no_admission,
                    "Forged final actor endpoint rejected against authenticated current actor",
                ),
                "t78_d.cycle": (
                    classifications["cycle"] == "SEMANTIC_INVALID"
                    and negatives["cycle"]["http_status"] == 422
                    and no_admission,
                    "Cyclic delegation rejected before admission",
                ),
                "t78_d.excess_bound": (
                    classifications["excess"] == "SCHEMA_INVALID"
                    and negatives["excess"]["http_status"] == 400
                    and no_admission,
                    "Over-bound delegation chain rejected by bounded schema",
                ),
                "t78_d.record_not_authority": (
                    classifications["asserted"] == "SEMANTIC_INVALID"
                    and negatives["asserted"]["http_status"] == 422
                    and no_admission,
                    "Asserted commission/reference did not authorize a forged actor endpoint",
                ),
            }
        stages = {
            "ingress": {
                "positive_http": positive["http_status"],
                "negative_http": {key: value["http_status"] for key, value in negatives.items()},
            },
            "admission": {
                "submission_id": sid,
                "new_submissions": after["submissions"] - before["submissions"],
                "trusted_actor_id": identity["actor_id"],
            },
        }
        return _api._evidence(
            runtime,
            case,
            stages,
            checks,
            {
                "positive": positive,
                "record": record,
                "negatives": negatives,
                "classifications": classifications,
                "before": before,
                "after_positive": admitted,
                "after": after,
            },
            record["attempt_id"],
        )
    if (case["scenario_id"], case["variant"]) == ("t02", "composed"):
        request = _api._case_request(runtime, case)
        forbidden = _api.deepcopy(request)
        forbidden["requested_configuration_ref"] = "cfg.forbidden.synthetic"
        before = _api._census(runtime)
        rejection = _api._post(runtime, forbidden, _api._headers(runtime))
        denied = _api._census(runtime)
        allowed = _api._post(runtime, request, _api._headers(runtime))
        after = _api._census(runtime)
        checks = {
            "t02.forbidden_destination": (
                rejection["http_status"] == 422
                and denied["submissions"] == before["submissions"]
                and denied["receiver_arrivals"] == before["receiver_arrivals"],
                "Unregistered requested destination configuration rejected before admission",
            ),
            "t02.fixed_destination": (
                allowed["status"]
                and allowed["status"].get("submission_state") == "completed"
                and after["receiver_arrivals"] == before["receiver_arrivals"] + 1
                and after["submissions"] == before["submissions"] + 1,
                "Exact registered fixed destination completed one guarded controlled send",
            ),
        }
        return _api._evidence(
            runtime,
            case,
            {
                "ingress": {
                    "forbidden_http": rejection["http_status"],
                    "fixed_http": allowed["http_status"],
                },
                "admission": {
                    "before": before["submissions"],
                    "after_denial": denied["submissions"],
                    "after_positive": after["submissions"],
                },
            },
            checks,
            {
                "forbidden": rejection,
                "fixed": allowed,
                "before": before,
                "denied": denied,
                "after": after,
            },
            allowed["reply"].get("attempt_id", "none"),
        )
    if (case["scenario_id"], case["variant"]) == ("t01", "composed"):
        request = _api._case_request(runtime, case)
        before = _api._census(runtime)
        missing = _api._headers(runtime)
        del missing["Authorization"]
        invalid = _api._headers(runtime)
        invalid["Authorization"] = "Bearer dev12.invalid.synthetic"
        first = _api._post(runtime, request, missing)
        middle = _api._post(runtime, request, invalid)
        after_rejections = _api._census(runtime)
        good = _api._post(runtime, request, _api._headers(runtime))
        after = _api._census(runtime)
        sid = good["reply"].get("handle", {}).get("submission_id")
        checks = {
            "t01.missing_identity": (
                first["http_status"] == 401
                and first["reply"].get("contract_version") == "0.3"
                and after_rejections["submissions"] == before["submissions"],
                "Missing bearer rejected with HTTP 401 before admission",
            ),
            "t01.invalid_identity": (
                middle["http_status"] == 401
                and after_rejections["guard_ownership"] == before["guard_ownership"]
                and after_rejections["receiver_arrivals"] == before["receiver_arrivals"],
                "Unknown bearer rejected without guard ownership or receiver arrival",
            ),
            "t01.valid_identity": (
                bool(
                    good["http_status"] in (200, 202)
                    and good["status"]
                    and good["status"].get("submission_state") == "completed"
                    and sid
                    and after["submissions"] == before["submissions"] + 1
                    and after["receiver_arrivals"] == before["receiver_arrivals"] + 1
                ),
                "Known synthetic bearer admitted exactly one completed guarded send",
            ),
        }
        stages = {
            "ingress": {
                "missing_status": first["http_status"],
                "invalid_status": middle["http_status"],
                "valid_status": good["http_status"],
            },
            "admission": {
                "before": before["submissions"],
                "after_rejections": after_rejections["submissions"],
                "after_valid": after["submissions"],
            },
        }
        return _api._evidence(
            runtime,
            case,
            stages,
            checks,
            {
                "missing": first,
                "invalid": middle,
                "valid": good,
                "before": before,
                "after_rejections": after_rejections,
                "after": after,
            },
            sid or "none",
        )
    if (case["scenario_id"], case["variant"]) == ("t42", "composed"):
        request = _api._case_request(runtime, case)
        before = _api._census(runtime)
        wrong_operation = _api.deepcopy(request)
        wrong_operation["operation"]["type"] = "text.generate"
        unsupported = _api._post(runtime, wrong_operation, _api._headers(runtime))
        wrong_version = _api.deepcopy(request)
        wrong_version["contract_version"] = "0.2"
        mismatch = _api._post(runtime, wrong_version, _api._headers(runtime))
        unknown_field = _api.deepcopy(request)
        unknown_field["unknown_extension"] = "forbidden"
        schema = _api._post(runtime, unknown_field, _api._headers(runtime))
        legacy = _api._post(runtime, request, _api._headers(runtime, version="0.2"))
        after_rejections = _api._census(runtime)
        valid = _api._post(runtime, request, _api._headers(runtime))
        after = _api._census(runtime)
        rejected_without_send = (
            after_rejections["submissions"] == before["submissions"]
            and after_rejections["guard_ownership"] == before["guard_ownership"]
            and after_rejections["receiver_arrivals"] == before["receiver_arrivals"]
        )
        checks = {
            "t42.unsupported_operation": (
                unsupported["http_status"] >= 400
                and unsupported["reply"].get("contract_version") == "0.3"
                and rejected_without_send,
                "Unsupported operation rejected before successor admission and receiver",
            ),
            "t42.mismatched_contract": (
                mismatch["http_status"] == 426 and rejected_without_send,
                "Mismatched body/header successor contract rejected before admission",
            ),
            "t42.unknown_schema": (
                schema["http_status"] >= 400 and rejected_without_send,
                "Unknown successor request field rejected without transmission",
            ),
            "t42.legacy_rejection": (
                legacy["http_status"] >= 400
                and legacy["reply"].get("contract_version") == "0.2"
                and rejected_without_send,
                "Legacy wire selection did not interpret successor operation",
            ),
            "t42.supported_operation": (
                bool(
                    valid["status"]
                    and valid["status"].get("submission_state") == "completed"
                    and after["submissions"] == before["submissions"] + 1
                    and after["receiver_arrivals"] == before["receiver_arrivals"] + 1
                ),
                "Fixed supported operation completed through guarded receiver once",
            ),
        }
        stages = {
            "ingress": {
                "unsupported": unsupported["http_status"],
                "mismatched": mismatch["http_status"],
                "schema": schema["http_status"],
                "legacy": legacy["http_status"],
                "supported": valid["http_status"],
            },
            "admission": {
                "before": before["submissions"],
                "after_rejections": after_rejections["submissions"],
                "after_valid": after["submissions"],
            },
        }
        return _api._evidence(
            runtime,
            case,
            stages,
            checks,
            {
                "responses": {
                    "unsupported": unsupported,
                    "mismatched": mismatch,
                    "schema": schema,
                    "legacy": legacy,
                    "supported": valid,
                },
                "before": before,
                "after_rejections": after_rejections,
                "after": after,
            },
            valid["reply"].get("attempt_id", "none"),
        )
    raise NotImplementedError(
        f"unimplemented ingress variant: {case['scenario_id']}/{case['variant']}"
    )
