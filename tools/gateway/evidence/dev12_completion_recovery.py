"""dev12_completion_handlers recovery domain; entry points remain on the facade."""

from __future__ import annotations


def recovery_chain(runtime, case):
    """One unknown attempt, independent receipt, historical append and resume."""
    from tools.gateway.evidence import dev12_completion_handlers as _api
    from tools.gateway.evidence.dev12_integrated import fixture, observations

    variant = case["variant"]
    chain_path = runtime.root / "recovery-chain-reference.json"
    if variant == "unknown_pause":
        if chain_path.exists():
            raise RuntimeError("recoverable chain already started")
        request = _api._case_request(runtime, case, item_id="doc.unknown.recoverable")
        before = _api._census(runtime)
        sent = _api._post(runtime, request, _api._headers(runtime))
        after = _api._census(runtime)
        status = sent["status"] or {}
        sid = sent["reply"].get("handle", {}).get("submission_id")
        aid = status.get("attempts", [{}])[0].get("attempt_id")
        receipt_rows = observations(runtime.root / "receiver-receipts.jsonl")
        matched = [row for row in receipt_rows if row.get("attempt_id") == aid]
        okay = (
            sid
            and aid
            and status.get("submission_state") == "unknown"
            and after["campaign"]["paused"] is True
            and after["receiver_arrivals"] == before["receiver_arrivals"] + 1
            and len(matched) == 1
            and after["guard_ownership"] == before["guard_ownership"] + 1
        )
        checks = {
            "recovery_chain.unknown_pause": (
                bool(okay),
                "Unknown reply retained receiver arrival, guarded ownership, exposure and same-scope pause",
            )
        }
        stages = {
            "admission": {"submission_id": sid or "absent"},
            "guard": {
                "guard_ownership_delta": after["guard_ownership"] - before["guard_ownership"]
            },
            "first_write": {
                "possible_send_delta": after["campaign"]["possible_send_count"]
                - before["campaign"]["possible_send_count"]
            },
            "receiver": {"arrival_delta": after["receiver_arrivals"] - before["receiver_arrivals"]},
            "delivery": {"state": status.get("submission_state", "absent")},
            "settlement": {
                "paused": after["campaign"]["paused"],
                "exposure_state": status.get("attempts", [{}])[0].get("settlement_state", "absent"),
            },
        }
        result = _api._evidence(
            runtime,
            case,
            stages,
            checks,
            {
                "request": request,
                "reply": sent,
                "before": before,
                "after": after,
                "receiver_receipts": matched,
            },
            aid or "none",
        )
        if result["status"] != "PASS":
            return result
        chain_path.write_text(
            _api.json.dumps(
                {
                    "submission_id": sid,
                    "attempt_id": aid,
                    "credential": "DIRECT_DOCUMENT",
                    "campaign_id": runtime.plan["envelope"]["campaign_id"],
                },
                sort_keys=True,
            )
            + "\n"
        )
        return result

    if not chain_path.is_file():
        raise RuntimeError("recoverable chain predecessor absent")
    ref = _api.json.loads(chain_path.read_text())
    sid, aid = ref["submission_id"], ref["attempt_id"]
    context = runtime.contexts_by_credential[runtime.credentials[ref["credential"]]]
    trusted = {
        **context["identity"],
        "task_id": fixture(ref["credential"])[0]["work_selector"]["task_id"],
        "expires_at": context["expires_at"],
    }
    before = _api._census(runtime)
    if variant == "retained_receipt":
        from tools.synthetic.successor_receiver_evidence import DurableReceiverReceipts

        with runtime.store._lock:
            record = runtime.store.successor_get(sid)
            guard_row = runtime.store.db.execute(
                "SELECT guard_receipt FROM dev12_send_ownership WHERE attempt_id=?", (aid,)
            ).fetchone()
        if not guard_row:
            raise AssertionError("durable guard receipt absent")
        guard = _api.json.loads(guard_row[0])
        retained = DurableReceiverReceipts(runtime.root / "receiver-receipts.jsonl")
        receipt, domain_digest = retained.find(
            aid,
            body_sha256=guard["body_sha256"],
            body_bytes=guard["body_bytes"],
            route=record["signed_plan"]["execution_descriptor"]["route"],
        )
        after = _api._census(runtime)
        checks = {
            "recovery_chain.retained_receipt": (
                receipt["attempt_id"] == aid
                and domain_digest.startswith("sha256:")
                and before == after
                and ref["campaign_id"] == runtime.allowance.campaign_id,
                "Independent retained receipt binds guarded attempt/body/route without a new send",
            )
        }
        stages = {
            "receiver": {
                "attempt_id": aid,
                "receipt_digest": domain_digest,
                "body_sha256": receipt["body_sha256"],
            }
        }
        return _api._evidence(
            runtime,
            case,
            stages,
            checks,
            {"receipt": receipt, "guard": guard, "before": before, "after": after},
            aid,
        )

    if variant == "authorized_late_append":
        # The service records UTC seconds.  Keep the two genuine revision
        # observations separable for the later operator cutoff assertion.
        _api.time.sleep(1.05)
        outcome = runtime.successor.collect_receiver_receipt(sid, trusted)
        after = _api._census(runtime)
        status = runtime.successor.status(sid, trusted)
        usage = status["attempts"][0].get("usage_revision", {})
        checks = {
            "recovery_chain.authorized_late_append": (
                outcome != "duplicate"
                and usage.get("cost_status") == "calculated"
                and after["usage_revisions"] == before["usage_revisions"] + 1
                and after["receiver_arrivals"] == before["receiver_arrivals"]
                and after["campaign"]["possible_send_count"]
                == before["campaign"]["possible_send_count"],
                "Authenticated historical append replaced unknown effective usage once without a send",
            )
        }
        stages = {
            "receiver": {"attempt_id": aid, "arrival_count": after["receiver_arrivals"]},
            "settlement": {
                "previous_revision_count": before["usage_revisions"],
                "revision_count": after["usage_revisions"],
                "cost_status": usage.get("cost_status", "absent"),
            },
        }
        return _api._evidence(
            runtime,
            case,
            stages,
            checks,
            {"append_outcome": outcome, "status": status, "before": before, "after": after},
            aid,
        )

    if variant == "denied_resume":
        runtime.authority.set_historical_access(
            context["identity"],
            read=True,
            write=True,
            resume=False,
            observed_at=_api._current_utc(),
        )
        denied = False
        try:
            runtime.successor.resume_campaign(sid, trusted, "test denied historical resume")
        except PermissionError:
            denied = True
        after = _api._census(runtime)
        checks = {
            "recovery_chain.denied_resume": (
                denied
                and after["campaign"]["paused"]
                and after["campaign"]["attempt_count"] == before["campaign"]["attempt_count"]
                and after["receiver_arrivals"] == before["receiver_arrivals"],
                "Revoked historical resume permission denied while exposure/counters remained fixed",
            )
        }
        stages = {
            "authority": {"historical_resume_permission": False, "denied": denied},
            "settlement": {
                "paused": after["campaign"]["paused"],
                "possible_sends": after["campaign"]["possible_send_count"],
            },
        }
        return _api._evidence(
            runtime, case, stages, checks, {"before": before, "after": after}, aid
        )

    if variant == "eligible_resume":
        runtime.authority.set_historical_access(
            context["identity"], read=True, write=True, resume=True, observed_at=_api._current_utc()
        )
        decision = runtime.successor.resume_campaign(
            sid, trusted, "test same-scope supported recovery"
        )
        after = _api._census(runtime)
        checks = {
            "recovery_chain.eligible_resume": (
                decision.get("decision") == "resumed"
                and not after["campaign"]["paused"]
                and after["campaign"]["attempt_count"] == before["campaign"]["attempt_count"]
                and after["campaign"]["possible_send_count"]
                == before["campaign"]["possible_send_count"]
                and after["receiver_arrivals"] == before["receiver_arrivals"],
                "Audited same-scope eligibility resumed only after retained receipt settlement",
            )
        }
        stages = {
            "authority": {
                "actor_id": decision.get("actor_id", "absent"),
                "decision": decision.get("decision", "absent"),
            },
            "settlement": {
                "paused": after["campaign"]["paused"],
                "blockers": decision.get("blockers", []),
            },
        }
        return _api._evidence(
            runtime,
            case,
            stages,
            checks,
            {"decision": decision, "before": before, "after": after},
            aid,
        )
    raise NotImplementedError(f"unimplemented recovery-chain variant: {variant}")


def authority_recovery(runtime, case):
    """Fresh first-write authority checks under the same accepted plan."""
    from tools.gateway.evidence import dev12_completion_handlers as _api

    if (case["scenario_id"], case["variant"]) == ("t14_a", "composed"):
        from tools.gateway.evidence.dev12_completion_boundary_handlers import assessment_transition

        return assessment_transition(runtime, case)
    if case["scenario_id"] == "t24_b":
        from tools.gateway.evidence.dev12_completion_boundary_handlers import first_write_order

        return first_write_order(runtime, case)
    if (case["scenario_id"], case["variant"]) == ("t24_c", "composed"):
        from tools.gateway.evidence.dev12_completion_boundary_handlers import crash_recovery

        return crash_recovery(runtime, case)
    if case["scenario_id"].startswith("t45_"):
        from ezllmrouter_server.successor_plan import execution_eligible

        scenario = case["scenario_id"]
        before = _api._census(runtime)
        outcomes = {}
        observed = {}

        def changed_revision(name, *, send_permission=None):
            def mutate(state):
                state["revisions"][name] += 1
                if send_permission is not None:
                    state["send_permission"] = send_permission

            runtime.authority.update(
                mutate,
                {
                    "kind": "completion02_named_authority_change",
                    "revision": name,
                    "send_permission": send_permission,
                    "at": _api._current_utc(),
                },
            )

        def queued(label, revision):
            request = _api._case_request(runtime, case)
            request["work_selector"]["step_id"] += "." + label
            fired = []

            async def lower_wait():
                if not fired:
                    fired.append(True)
                    changed_revision(revision)

            runtime.executor.first_write_wait = lower_wait
            try:
                response = _api._post(runtime, request, _api._headers(runtime))
            finally:
                runtime.executor.first_write_wait = None
            response["status"] or {}
            sid = response["reply"].get("handle", {}).get("submission_id")
            record = runtime.store.successor_get(sid) if sid else None
            observations = {
                "fired": bool(fired),
                "response": response,
                "record": record,
                "revision": revision,
            }
            outcomes[label] = observations
            return observations

        def positive(label):
            request = _api._case_request(runtime, case)
            request["work_selector"]["step_id"] += "." + label
            response = _api._post(runtime, request, _api._headers(runtime))
            sid = response["reply"].get("handle", {}).get("submission_id")
            record = runtime.store.successor_get(sid) if sid else None
            item = {"response": response, "record": record}
            outcomes[label] = item
            return item

        if scenario == "t45_a":
            control = positive("control")
            record = control["record"]
            if not record:
                raise AssertionError("source/account/operation control absent")
            context = runtime.authority.current_context(record, _api._current_utc())
            plan = record["signed_plan"]
            negatives = {}
            for name, mutation in (
                ("source_isolation", {"expected_work_digest": "sha256:" + "0" * 64}),
                ("account_isolation", {"expected_financial_owner_id": "team.other.synthetic"}),
                (
                    "operation_isolation",
                    {
                        "expected_reservation": {
                            **context["expected_reservation"],
                            "price_ref": "price.rerank.synthetic.a",
                        }
                    },
                ),
            ):
                changed = _api.deepcopy(context)
                changed.update(mutation)
                negatives[name] = not execution_eligible(
                    plan,
                    record["request"],
                    record["canonical_work"],
                    record["admission_snapshot"],
                    changed,
                )
            observed = {"signed_plan": plan, "negative_decisions": negatives}
            checks = {
                f"t45_a.{name}": (
                    bool(
                        value
                        and control["response"]["status"].get("submission_state") == "completed"
                    ),
                    "Independent source, account or operation scope change cannot execute the admitted signed plan",
                )
                for name, value in negatives.items()
            }
        elif scenario in {"t45_b", "t45_c", "t45_d"}:
            mapping = {
                "t45_b": [("source_disallow_after_wait", "source_permission")],
                "t45_c": [
                    ("grant_revoke_after_wait", "grant"),
                    ("delegation_revoke_after_wait", "registry"),
                ],
                "t45_d": [
                    ("credential_scope_change", "credential_scope"),
                    ("compromise", "source_permission"),
                    ("revocation", "credential_scope"),
                ],
            }
            blocked = {name: queued(name, revision) for name, revision in mapping[scenario]}
            control = positive("after_revision_control")
            checks = {
                f"{scenario}.{name}": (
                    bool(
                        item["fired"]
                        and item["response"]["status"]
                        and item["response"]["status"].get("submission_state") == "failed"
                        and item["record"]
                        and item["record"].get("dispatch_state") == "blocked"
                        and control["response"]["status"]
                        and control["response"]["status"].get("submission_state") == "completed"
                    ),
                    "Named current authority revision changed during lower wait; old plan was blocked and new plan succeeded",
                )
                for name, item in blocked.items()
            }
            observed = {
                "named_revision_cases": list(blocked),
                "control_submission": control["record"]["submission_id"],
            }
        elif scenario == "t45_e":
            from cryptography.hazmat.primitives.asymmetric import ed25519

            first = positive("rotation_control")
            old = first["record"]
            old_plan = old["signed_plan"]
            new_key = ed25519.Ed25519PrivateKey.generate()
            new_version = "v.t45.rotation"
            runtime.persist_signer(new_key, new_version)
            runtime.authority.rotate_minting_key(
                new_key, "key.synthetic.dev12", new_version, _api._current_utc()
            )
            current = runtime.authority.current_context(old, _api._current_utc())
            old_eligible = execution_eligible(
                old_plan, old["request"], old["canonical_work"], old["admission_snapshot"], current
            )
            invalid = queued("changed_revision", "grant")
            control = positive("new_revision_control")
            checks = {
                "t45_e.eligible_rotation": (
                    bool(
                        old_eligible
                        and old_plan["key_version"]
                        != control["record"]["signed_plan"]["key_version"]
                        and control["response"]["status"].get("submission_state") == "completed"
                    ),
                    "Old bound verification key remained eligible during ordinary active minting rotation",
                ),
                "t45_e.changed_revision_without_authority": (
                    bool(
                        invalid["fired"]
                        and invalid["response"]["status"].get("submission_state") == "failed"
                        and invalid["record"].get("dispatch_state") == "blocked"
                    ),
                    "Unrelated changed grant revision remained a first-write blocker after key rotation",
                ),
            }
            observed = {
                "old_plan": old_plan,
                "old_eligible_after_rotation": old_eligible,
                "changed_revision": invalid,
            }
        else:
            raise NotImplementedError("unknown T-45 scenario")
        after = _api._census(runtime)
        if not control["record"]:
            raise AssertionError("T-45 positive control not admitted")
        stages = {
            "admission": {"before": before["submissions"], "after": after["submissions"]},
            "signed_plan": {"positive_plan_id": control["record"]["signed_plan"]["plan_id"]},
            "authority": {"named_revisions": runtime.authority.revisions()},
            "guard": {"before": before["guard_ownership"], "after": after["guard_ownership"]},
            "first_write": {
                "receiver_before": before["receiver_arrivals"],
                "receiver_after": after["receiver_arrivals"],
            },
        }
        return _api._evidence(
            runtime,
            case,
            stages,
            checks,
            {"outcomes": outcomes, "observed": observed, "before": before, "after": after},
            control["record"]["attempt_id"],
        )
    if case["scenario_id"] == "t24_a" and case["variant"] in {
        "queued_revocation",
        "eligible_control",
    }:
        request = _api._case_request(runtime, case)
        before = _api._census(runtime)
        fired = []

        def set_permission(allowed):
            def change(state):
                state["send_permission"] = allowed

            runtime.authority.update(
                change,
                {
                    "kind": "completion02_send_permission",
                    "allowed": allowed,
                    "at": _api._current_utc(),
                },
            )

        async def lower_wait():
            if not fired:
                fired.append(True)
                set_permission(False)

        if case["variant"] == "queued_revocation":
            runtime.executor.first_write_wait = lower_wait
        try:
            reply = _api._post(runtime, request, _api._headers(runtime))
        finally:
            runtime.executor.first_write_wait = None
            if fired:
                set_permission(True)
        after = _api._census(runtime)
        status = reply["status"] or {}
        if case["variant"] == "queued_revocation":
            passed = (
                bool(fired)
                and status.get("submission_state") == "failed"
                and status.get("attempts", [{}])[0].get("dispatch_state") == "blocked"
                and after["receiver_arrivals"] == before["receiver_arrivals"]
                and after["submissions"] == before["submissions"] + 1
            )
            detail = (
                "Durable local send revocation at queued first-write wait blocked receiver bytes"
            )
        else:
            passed = (
                not fired
                and status.get("submission_state") == "completed"
                and after["receiver_arrivals"] == before["receiver_arrivals"] + 1
                and after["submissions"] == before["submissions"] + 1
            )
            detail = "Eligible queued control completed one guarded receiver send"
        checks = {f"t24_a.{case['variant']}": (passed, detail)}
        sid = reply["reply"].get("handle", {}).get("submission_id")
        record = runtime.store.successor_get(sid) if sid else None
        return _api._evidence(
            runtime,
            case,
            {
                "admission": {"submission_id": sid or "absent"},
                "signed_plan": {
                    "plan_id": record["signed_plan"]["plan_id"] if record else "absent"
                },
                "authority": {"revoked_at_lower_wait": bool(fired)},
                "guard": {"ownership_delta": after["guard_ownership"] - before["guard_ownership"]},
                "first_write": {
                    "arrival_delta": after["receiver_arrivals"] - before["receiver_arrivals"]
                },
            },
            checks,
            {"reply": reply, "record": record, "before": before, "after": after},
            record["attempt_id"] if record else "none",
        )
    if (
        case["scenario_id"] in {"t46_a", "t46_b", "t46_c", "t46_d"}
        and case["variant"] == "composed"
    ):
        from ezllmrouter_server.successor_plan import execution_eligible, verified_signature

        request = _api._case_request(runtime, case)
        if case["scenario_id"] == "t46_a":
            request["input"]["items"] = [
                {"item_id": "doc.one", "text": "Sky"},
                {"item_id": "doc.two", "text": "Earth 🌍"},
            ]
        before = _api._census(runtime)
        positive = _api._post(runtime, request, _api._headers(runtime))
        after = _api._census(runtime)
        sid = positive["reply"].get("handle", {}).get("submission_id")
        if not sid:
            raise AssertionError("signed-plan mutation control was not admitted")
        record = runtime.store.successor_get(sid)
        plan = record["signed_plan"]
        current = runtime.authority.current_context(record, _api._current_utc())
        key = next(
            item
            for item in current["verification_keys"]
            if (item["key_id"], item["key_version"]) == (plan["key_id"], plan["key_version"])
        )

        def eligible(
            *,
            changed_plan=None,
            changed_request=None,
            changed_work=None,
            changed_snapshot=None,
            changed_context=None,
        ):
            return execution_eligible(
                changed_plan or plan,
                changed_request or record["request"],
                changed_work or record["canonical_work"],
                changed_snapshot or record["admission_snapshot"],
                changed_context or current,
            )

        original = eligible() and verified_signature(plan, key)
        negatives = {}
        supplemental = {}
        scenario = case["scenario_id"]
        if scenario == "t46_a":
            changes = {}
            op = _api.deepcopy(record["request"])
            op["operation"]["version"] = 2
            changes["operation_mutation"] = op
            payload = _api.deepcopy(record["request"])
            payload["input"]["items"][0]["text"] = "River"
            changes["payload_mutation"] = payload
            ordered = _api.deepcopy(record["request"])
            ordered["input"]["items"].reverse()
            changes["order_mutation"] = ordered
            compatibility = _api.deepcopy(record["request"])
            compatibility["requested_configuration_ref"] = "cfg.rerank.synthetic"
            changes["compatibility_mutation"] = compatibility
            negatives = {
                name: not eligible(changed_request=value) for name, value in changes.items()
            }
            supplemental = {"mutated_requests": changes}
        elif scenario == "t46_b":
            snapshot = record["admission_snapshot"]
            changes = {}
            status = _api.deepcopy(snapshot)
            status["commission"] = {
                "status": "verified",
                "evidence_scope": "synthetic.review",
                "evidence_ref": "evidence.synthetic",
            }
            changes["assessment_status_tamper"] = status
            coverage = _api.deepcopy(snapshot)
            coverage["delegation"]["coverage"] = "partial"
            changes["coverage_tamper"] = coverage
            reason = _api.deepcopy(snapshot)
            reason["commission"]["absence_reason"] = "not_yet_issued"
            changes["reason_tamper"] = reason
            link = _api.deepcopy(snapshot)
            link["work_digest"] = "sha256:" + "0" * 64
            changes["digest_link_tamper"] = link
            negatives = {
                name: not eligible(changed_snapshot=value) for name, value in changes.items()
            }
            before_later = _api.deepcopy(runtime.store.successor_get(sid))
            runtime.store.successor_append_evidence(
                sid,
                "later_assessment",
                _api._current_utc(),
                {"kind": "synthetic_review", "status": "recorded_only"},
            )
            after_later = runtime.store.successor_get(sid)
            negatives["later_assessment"] = (
                after_later["work_digest"] == before_later["work_digest"]
                and after_later["admission_snapshot"] == before_later["admission_snapshot"]
                and after_later["signed_plan"] == before_later["signed_plan"]
            )
            supplemental = {
                "mutated_snapshots": changes,
                "before_later": before_later,
                "after_later": after_later,
            }
        elif scenario == "t46_c":
            activation_plan = _api.deepcopy(plan)
            activation_plan["execution_context"] = {
                "state": "tagged_fixture",
                "epoch": "epoch.synthetic.changed",
            }
            activation_context = _api.deepcopy(current)
            activation_context["expected_execution_context"] = {
                "state": "tagged_fixture",
                "epoch": "epoch.synthetic.changed",
            }
            negatives = {
                "activation_mutation": (
                    not verified_signature(activation_plan, key)
                    and not eligible(changed_plan=activation_plan)
                    and not eligible(changed_context=activation_context)
                ),
                "eligible_activation": original,
            }
            supplemental = {
                "activation_plan": activation_plan,
                "activation_context": activation_context,
            }
        else:
            changed_price = _api.deepcopy(plan)
            changed_price["price_ref"] = "price.rerank.synthetic.a"
            changed_owner = _api.deepcopy(plan)
            changed_owner["financial_owner_id"] = "team.forged"
            negatives = {
                "price_mutation": (
                    not verified_signature(changed_price, key)
                    and not eligible(changed_plan=changed_price)
                ),
                "owner_mutation": (
                    not verified_signature(changed_owner, key)
                    and not eligible(changed_plan=changed_owner)
                ),
            }
            supplemental = {"price_plan": changed_price, "owner_plan": changed_owner}
        checks = {
            f"{scenario}.{name}": (
                bool(
                    original
                    and rejected
                    and positive["status"]
                    and positive["status"].get("submission_state") == "completed"
                    and after["receiver_arrivals"] == before["receiver_arrivals"] + 1
                ),
                "Changed signed/admitted binding rejected by the execution eligibility validator used at first-write guard",
            )
            for name, rejected in negatives.items()
        }
        stages = {
            "admission": {"submission_id": sid},
            "signed_plan": {
                "plan_id": plan["plan_id"],
                "signature_valid": verified_signature(plan, key),
            },
            "authority": {"evaluated_bindings": list(negatives)},
            "guard": {"ownership_delta": after["guard_ownership"] - before["guard_ownership"]},
            "first_write": {
                "arrival_delta": after["receiver_arrivals"] - before["receiver_arrivals"]
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
                "current": current,
                "negative_decisions": negatives,
                "supplemental": supplemental,
                "before": before,
                "after": after,
            },
            record["attempt_id"],
        )
    if case["scenario_id"] != "t07_a" or case["variant"] not in {
        "eligible_current",
        "rotated_old_eligible",
        "revoked_key_after_wait",
        "revoked_plan_after_wait",
    }:
        raise NotImplementedError("authority/recovery variant not implemented")
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from ezllmrouter_server.successor_plan import verified_signature

    request = _api._case_request(runtime, case)
    before = _api._census(runtime)
    variant = case["variant"]
    fired = []
    action_record = {}
    rotation_version = "v.t07.rotated"
    recovery_version = "v.t07.recovery"

    async def after_lower_wait():
        if fired:
            return
        fired.append(True)
        stored = runtime.store.successor_by_work(
            {
                "principal_id": runtime.contexts_by_credential[
                    runtime.credentials["DIRECT_DOCUMENT"]
                ]["identity"]["principal_id"],
                **request["work_selector"],
            }
        )
        if stored is None:
            raise AssertionError("admitted plan not visible at lower wait")
        plan = stored["signed_plan"]
        action_record.update(
            {
                "submission_id": stored["submission_id"],
                "attempt_id": stored["attempt_id"],
                "original_plan_id": plan["plan_id"],
                "original_key_id": plan["key_id"],
                "original_key_version": plan["key_version"],
                "original_signature": plan["signature"],
            }
        )
        if variant == "rotated_old_eligible":
            rotated = ed25519.Ed25519PrivateKey.generate()
            runtime.persist_signer(rotated, rotation_version)
            runtime.authority.rotate_minting_key(
                rotated, "key.synthetic.dev12", rotation_version, _api._current_utc()
            )
        elif variant == "revoked_key_after_wait":
            runtime.authority.revoke_key_version(
                plan["key_id"], plan["key_version"], _api._current_utc()
            )
        elif variant == "revoked_plan_after_wait":
            runtime.authority.revoke_plan(plan["plan_id"], _api._current_utc())

    if variant != "eligible_current":
        runtime.executor.first_write_wait = after_lower_wait
    try:
        outcome = _api._post(runtime, request, _api._headers(runtime))
    finally:
        runtime.executor.first_write_wait = None
    after = _api._census(runtime)
    sid = outcome["reply"].get("handle", {}).get("submission_id")
    if not sid:
        raise AssertionError("admitted authority case lacks submission handle")
    record = runtime.store.successor_get(sid)
    plan = record["signed_plan"]
    key = next(
        (
            item
            for item in runtime.authority.state["verification_keys"]
            if item["key_id"] == plan["key_id"] and item["key_version"] == plan["key_version"]
        ),
        None,
    )
    signature_valid = key is not None and verified_signature(plan, key)
    if variant == "revoked_key_after_wait":
        # Leave the run with a fresh eligible minting tuple; retain revoked v1/v2.
        recovery_key = ed25519.Ed25519PrivateKey.generate()
        runtime.persist_signer(recovery_key, recovery_version)
        runtime.authority.rotate_minting_key(
            recovery_key, "key.synthetic.dev12", recovery_version, _api._current_utc()
        )
    completed = outcome["status"] and outcome["status"].get("submission_state") == "completed"
    blocked = outcome["status"] and outcome["status"].get("submission_state") == "failed"
    common = (
        signature_valid
        and after["submissions"] == before["submissions"] + 1
        and after["campaign"]["attempt_count"] == before["campaign"]["attempt_count"] + 1
    )
    if variant == "eligible_current":
        passed = bool(
            common
            and completed
            and after["receiver_arrivals"] == before["receiver_arrivals"] + 1
            and not fired
        )
        detail = "Eligible current signed key completed one guarded receiver send"
    elif variant == "rotated_old_eligible":
        passed = bool(
            common
            and completed
            and fired
            and plan["key_version"] == action_record.get("original_key_version")
            and runtime.authority.state["active_minting_key"]["key_version"] == rotation_version
            and plan["signature"] == action_record.get("original_signature")
            and after["receiver_arrivals"] == before["receiver_arrivals"] + 1
        )
        detail = "Rotation selected a new signer while the unchanged eligible old plan sent once"
    elif variant == "revoked_key_after_wait":
        passed = bool(
            common
            and blocked
            and fired
            and key["eligibility"] == "revoked"
            and plan["signature"] == action_record.get("original_signature")
            and after["receiver_arrivals"] == before["receiver_arrivals"]
        )
        detail = "Correctly signed plan under newly revoked bound key was denied after lower wait"
    else:
        passed = bool(
            common
            and blocked
            and fired
            and plan["plan_id"] in runtime.authority.state["revoked_plans"]
            and plan["signature"] == action_record.get("original_signature")
            and after["receiver_arrivals"] == before["receiver_arrivals"]
        )
        detail = "Unchanged signed plan was denied after lower-wait plan revocation"
    checks = {f"t07_a.{variant}": (passed, detail)}
    stages = {
        "admission": {"submission_id": sid},
        "signed_plan": {
            "plan_id": plan["plan_id"],
            "key_version": plan["key_version"],
            "signature_valid": signature_valid,
        },
        "authority": {
            "lower_wait_hook_fired": bool(fired),
            "bound_key_eligibility": key["eligibility"],
            "plan_revoked": plan["plan_id"] in runtime.authority.state["revoked_plans"],
        },
        "guard": {"ownership_delta": after["guard_ownership"] - before["guard_ownership"]},
        "first_write": {
            "receiver_arrival_delta": after["receiver_arrivals"] - before["receiver_arrivals"]
        },
    }
    return _api._evidence(
        runtime,
        case,
        stages,
        checks,
        {
            "request": request,
            "outcome": outcome,
            "action_record": action_record,
            "original_plan": plan,
            "before": before,
            "after": after,
        },
        record["attempt_id"],
    )
