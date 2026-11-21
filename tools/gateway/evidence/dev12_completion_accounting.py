"""dev12_completion_handlers accounting domain; entry points remain on the facade."""

from __future__ import annotations


def native_accounting(runtime, case):
    """Independently recompute all fixed native-unit tariff rows and bounds."""

    if (case["scenario_id"], case["variant"]) == ("t50_e", "composed"):
        # The current fixed mint reserves the upward rounded full tariff, so
        # a fresh supported send cannot exceed its own bound. Exercise the
        # adopted historical-underbound read/settlement path in a distinct,
        # zero-send imported fixture scope; leave the live campaign untouched.
        return _historical_underbound(runtime, case)
    if (case["scenario_id"], case["variant"]) == ("t50_c", "composed"):
        return _restart_unknown_exposure(runtime, case)
    if case["scenario_id"] == "t50_a" and case["variant"] == "composed":
        return _finite_campaign_cap(runtime, case)
    if case["scenario_id"] in {"t49_a", "t49_b", "t49_c", "t49_d", "t49_e", "t50_d", "t48_f"}:
        return _native_counter_corrections(runtime, case)
    if case["scenario_id"] == "t50_b" and case["variant"] in {
        "duplicate_submission",
        "competing_submission",
    }:
        return _work_owner_contention(runtime, case)
    if case["scenario_id"] == "t48_g" and case["variant"] == "composed":
        return _native_minima(runtime, case)
    return _nominal_native_tariffs(runtime, case)


def _historical_underbound(runtime, case):
    from tools.gateway.evidence import dev12_completion_handlers as _api
    from ezllmrouter_server.store import SQLiteStore
    from tools.synthetic.successor_campaign import FiniteSuccessorCampaign
    from ezllmrouter_server.successor_contract import (
        native_usage_row,
        price_for,
        tariff,
        usage_valid,
    )
    from ezllmrouter_server.successor_plan import (
        plan_valid,
        signing_message,
        verified_signature,
    )
    from ezllmrouter_server.successor_reporting import usage_report
    import base64

    before = _api._census(runtime)
    source, source_usage = _completed_historical_attempt(runtime)
    historical = _api.deepcopy(source)
    historical_scope = "campaign.fixture.imported.underbound"
    historical["campaign_id"] = historical_scope
    historical["reservation"]["max_exposure_decimal"] = "0.000100000"
    historical["signed_plan"]["reservation"] = _api.deepcopy(historical["reservation"])
    historical["signed_plan"]["key_id"] = runtime.authority.key_id
    historical["signed_plan"]["key_version"] = runtime.authority.key_version
    historical["signed_plan"]["signature"] = (
        base64.urlsafe_b64encode(
            runtime.authority.private_key.sign(signing_message(historical["signed_plan"]))
        )
        .decode()
        .rstrip("=")
    )
    historical.pop("effective_usage_revision", None)
    historical["settlement_state"] = "pending"
    historical["exposure_state"] = "outstanding"
    fixture_path = runtime.root / "cases" / (case["id"] + "-historical.sqlite")
    fixture_path.parent.mkdir(exist_ok=True)
    if fixture_path.exists():
        raise RuntimeError("historical fixture path already exists")
    fixture = SQLiteStore(fixture_path)
    try:
        fixture.successor_create(historical)  # imported fixture; no reserve callback
        fixture_campaign = FiniteSuccessorCampaign(
            fixture,
            historical_scope,
            historical["reservation"]["budget_account_id"],
            financial_owner_id=historical["trusted_identity"]["charging_owner_id"],
        )
        fixture_campaign.start(
            {"kind": "imported_historical_underbound"},
            [str(fixture_path)],
            max_attempts=0,
            max_concurrent=0,
            ceiling_decimal="0.000100000",
            window_hours=1,
        )
        component = _api.deepcopy(source_usage["components"][0])
        usage = native_usage_row(
            historical["request"],
            historical["attempt_id"],
            1,
            component,
            historical["reservation"]["max_exposure_decimal"],
        )
        import_result = fixture.successor_append_usage(
            historical["submission_id"],
            usage,
            _api._current_utc(),
            write_allowed=True,
            on_settlement=lambda db, state: fixture_campaign.pause_in_transaction(db, "over_bound")
            if state == "over_bound"
            else None,
        )
        retained = fixture.successor_get(historical["submission_id"])
        projected = usage_report(
            fixture, {"role": "registry_admin", "principal_id": "owner.synthetic"}
        )
        fixture_state = fixture_campaign.inspect()
    finally:
        fixture.close()
    after = _api._census(runtime)
    price = price_for(historical["request"])
    exact = tariff(historical["request"], price)["settled"]
    key = next(
        item
        for item in runtime.authority.state["verification_keys"]
        if item["key_id"] == runtime.authority.key_id
        and item["key_version"] == runtime.authority.key_version
    )
    valid_history = plan_valid(
        historical["signed_plan"],
        historical["request"],
        historical["work_digest"],
        historical["admission_snapshot_digest"],
        historical["trusted_identity"]["charging_owner_id"],
        permit_historical_underbound=True,
    )
    no_new = (
        before == after
        and fixture_state["attempt_count"] == 0
        and fixture_state["possible_send_count"] == 0
    )
    checks = {
        "t50_e.above_bound_recorded": (
            bool(
                no_new
                and valid_history
                and verified_signature(historical["signed_plan"], key)
                and import_result == "accepted"
                and usage_valid(
                    usage,
                    historical["request"],
                    historical["attempt_id"],
                    historical["reservation"]["price_ref"],
                    historical["reservation"]["usage_ref"],
                    historical["reservation"]["max_exposure_decimal"],
                )
                and usage["cost_status"] == "over_bound"
                and usage["amount_decimal"] == exact
                and _api.Decimal(exact) > _api.Decimal("0.000100000")
                and projected["total"]["known_usd"] == exact
                and projected["total"]["over_bound_attempts"] == 1
            ),
            "Imported historical underbound fixture records exact actual tariff above bound without clamping or a new send",
        ),
        "t50_e.affected_scope_paused": (
            bool(
                no_new
                and retained["settlement_state"] == "over_bound"
                and retained["exposure_state"] == "over_bound"
                and fixture_state["paused"]
                and "over_bound" in fixture_state["pause_reasons"]
            ),
            "Only the separate zero-send historical fixture scope paused on accepted over-bound usage",
        ),
    }
    stages = {
        "admission": {
            "kind": "imported_historical_fixture",
            "source_submission_id": source["submission_id"],
            "new_live_admissions": 0,
        },
        "receiver": {
            "source_attempt_id": source["attempt_id"],
            "source_receipt": "retained_actual_receiver_arrival",
        },
        "delivery": {
            "source_state": source["submission_state"],
            "fixture_state": retained["submission_state"],
        },
        "settlement": {
            "state": usage["cost_status"],
            "amount_decimal": usage["amount_decimal"],
            "historical_bound_decimal": "0.000100000",
        },
    }
    return _api._evidence(
        runtime,
        case,
        stages,
        checks,
        {
            "kind": "synthetic_imported_historical_underbound_no_live_admission",
            "source_record": source,
            "source_usage": source_usage,
            "imported_record": retained,
            "imported_usage": usage,
            "fixture_campaign": fixture_state,
            "fixture_report": projected,
            "fixture_sqlite_sha256": _api.sha256(fixture_path.read_bytes()).hexdigest(),
            "main_before": before,
            "main_after": after,
        },
        case["attempt_group"],
    )


def _restart_unknown_exposure(runtime, case):
    from tools.gateway.evidence import dev12_completion_handlers as _api

    request = _api._case_request(runtime, case, item_id="doc.unknown.recoverable")
    before = _api._census(runtime)
    first = _api._post(runtime, request, _api._headers(runtime))
    unknown = _api._census(runtime)
    sid = first["reply"].get("handle", {}).get("submission_id")
    if not sid or first["status"].get("submission_state") != "unknown":
        raise AssertionError("recoverable unknown target outcome absent")
    original = runtime.store.successor_get(sid)
    restarted = runtime.restart_service()
    retained = runtime.successor.status(sid, _api._trusted(runtime))
    after_restart = _api._census(runtime)
    denied_request = _api._case_request(runtime, case)
    denied_request["work_selector"]["step_id"] += ".after.restart"
    denied = _api._post(runtime, denied_request, _api._headers(runtime))
    still_paused = _api._census(runtime)
    collected = runtime.successor.collect_receiver_receipt(sid, _api._trusted(runtime))
    resumed = runtime.successor.resume_campaign(
        sid, _api._trusted(runtime), "same campaign retained receipt after restart"
    )
    after = _api._census(runtime)
    passed = bool(
        unknown["campaign"]["paused"]
        and after_restart["campaign"]["paused"]
        and after_restart["campaign"]["start_at"] == before["campaign"]["start_at"]
        and retained["submission_state"] == "unknown"
        and retained["attempts"][0]["attempt_id"] == original["attempt_id"]
        and denied["http_status"] == 403
        and still_paused["submissions"] == unknown["submissions"]
        and still_paused["receiver_arrivals"] == unknown["receiver_arrivals"]
        and still_paused["campaign"]["possible_send_count"]
        == unknown["campaign"]["possible_send_count"]
        and collected == "accepted"
        and resumed.get("decision") == "resumed"
        and after["receiver_arrivals"] == unknown["receiver_arrivals"]
        and after["campaign"]["possible_send_count"] == unknown["campaign"]["possible_send_count"]
    )
    checks = {
        "t50_c.restart_unknown_exposure": (
            passed,
            "Restart retained one possible-send exposure and denied new admission before authenticated receipt correction",
        )
    }
    stages = {
        "admission": {"submission_id": sid, "attempt_id": original["attempt_id"]},
        "receiver": {
            "arrivals_before": before["receiver_arrivals"],
            "arrivals_after": after["receiver_arrivals"],
        },
        "delivery": {
            "retained_state": retained["submission_state"],
            "denied_http": denied["http_status"],
        },
        "settlement": {
            "paused_after_restart": after_restart["campaign"]["paused"],
            "collected": collected,
            "resume": resumed.get("decision"),
        },
    }
    return _api._evidence(
        runtime,
        case,
        stages,
        checks,
        {
            "first": first,
            "original": original,
            "restart": restarted,
            "retained": retained,
            "denied": denied,
            "collected": collected,
            "resumed": resumed,
            "before": before,
            "unknown": unknown,
            "after_restart": after_restart,
            "still_paused": still_paused,
            "after": after,
        },
        original["attempt_id"],
    )


def _finite_campaign_cap(runtime, case):
    from tools.gateway.evidence import dev12_completion_handlers as _api
    import asyncio

    release = _api.threading.Event()
    arrived = _api.threading.Event()
    lock = _api.threading.Lock()
    waiting = []

    async def lower_wait():
        with lock:
            waiting.append(_api.time.monotonic_ns())
            if len(waiting) == 2:
                arrived.set()
        if not await asyncio.to_thread(release.wait, 10):
            raise TimeoutError("bounded first-write concurrency barrier expired")

    before = _api._census(runtime)
    runtime.executor.first_write_wait = lower_wait
    try:
        with _api.ThreadPoolExecutor(max_workers=3) as pool:
            first = pool.submit(
                _api._post,
                runtime,
                _api._retrieval_request(runtime, case, "DIRECT_DOCUMENT", "one", ["doc.one"]),
                _api._headers(runtime),
            )
            second = pool.submit(
                _api._post,
                runtime,
                _api._retrieval_request(runtime, case, "DIRECT_DOCUMENT", "two", ["doc.two"]),
                _api._headers(runtime),
            )
            if not arrived.wait(8):
                raise AssertionError("two in-flight first-write waits were not reached")
            held = _api._census(runtime)
            third = _api._post(
                runtime,
                _api._retrieval_request(runtime, case, "DIRECT_DOCUMENT", "three", ["doc.three"]),
                _api._headers(runtime),
            )
            denied = _api._census(runtime)
            release.set()
            replies = [first.result(timeout=20), second.result(timeout=20)]
    finally:
        release.set()
        runtime.executor.first_write_wait = None
    after = _api._census(runtime)
    checks = {
        "t50_a.two_contenders": (
            len(waiting) == 2
            and held["campaign"]["inflight_count"] == 2
            and all(
                row["status"] and row["status"].get("submission_state") == "completed"
                for row in replies
            )
            and after["receiver_arrivals"] == before["receiver_arrivals"] + 2,
            "Two distinct normal submissions held in flight and each completed one guarded send",
        ),
        "t50_a.finite_cap": (
            third["http_status"] == 403
            and denied["submissions"] == before["submissions"] + 2
            and denied["receiver_arrivals"] == before["receiver_arrivals"]
            and after["campaign"]["inflight_count"] == 0,
            "Third concurrent admission rejected at selected two-in-flight cap before send",
        ),
    }
    stages = {
        "admission": {
            "before": before["submissions"],
            "held": held["submissions"],
            "after": after["submissions"],
        },
        "receiver": {
            "before": before["receiver_arrivals"],
            "after": after["receiver_arrivals"],
        },
        "delivery": {"states": [row["status"].get("submission_state") for row in replies]},
        "settlement": {
            "held_inflight": held["campaign"]["inflight_count"],
            "after_inflight": after["campaign"]["inflight_count"],
        },
    }
    return _api._evidence(
        runtime,
        case,
        stages,
        checks,
        {
            "before": before,
            "held": held,
            "denied": denied,
            "third": third,
            "replies": replies,
            "after": after,
        },
        replies[0]["reply"].get("attempt_id", "none"),
    )


def _native_counter_corrections(runtime, case):
    from tools.gateway.evidence import dev12_completion_handlers as _api

    scenario, variant = case["scenario_id"], case["variant"]
    if scenario == "t49_a" and variant == "composed":
        modes = [("doc.valid.absent", "absent")]
    elif scenario == "t49_b" and variant == "composed":
        modes = [("doc.valid.null", "null")]
    elif scenario == "t49_c" and variant == "contradictory_zero":
        modes = [("doc.valid.zero", "zero")]
    elif scenario == "t48_f" and variant == "composed":
        modes = [
            ("doc.valid.absent", "missing"),
            ("doc.valid.null", "null"),
            ("doc.valid.array", "invalid"),
            ("doc.valid.zero", "zero"),
            ("doc.valid.derived", "contradictory"),
        ]
    elif scenario == "t49_d" and variant == "composed":
        modes = [
            ("doc.valid.malformed_unicode", "invalid"),
            ("doc.valid.out_of_domain", "out_of_domain"),
            ("doc.valid.zero", "contradictory"),
        ]
    elif scenario in {"t49_e", "t50_d"} and variant == "composed":
        modes = [("doc.valid.absent", "late")]
    elif scenario == "t49_c" and variant == "consistent_zero":
        # This profile has no accepted zero-unit operation: every request
        # has at least one item at a strictly positive fictional rate.
        return _consistent_zero_control(runtime, case)
    else:
        raise NotImplementedError("native zero/unknown branch not implemented")
    cases = [
        _api._unknown_then_retained_correction(runtime, case, item, suffix)
        for item, suffix in modes
    ]
    by_mode = {
        suffix: observation for (_item, suffix), observation in zip(modes, cases, strict=True)
    }
    if scenario == "t49_a":
        checks = {
            "t49_a.absent_counter": (
                cases[0]["status_before"]["attempts"][0]["usage_revision"]["components"][0][
                    "presence"
                ]
                == "absent"
                and cases[0]["paused"]["campaign"]["paused"],
                "Absent counter retained as unknown liability before independent late receipt correction",
            )
        }
    elif scenario == "t49_b":
        checks = {
            "t49_b.null_counter": (
                cases[0]["status_before"]["attempts"][0]["usage_revision"]["components"][0][
                    "presence"
                ]
                == "null"
                and cases[0]["paused"]["campaign"]["paused"],
                "Explicit null remains distinct from absence and unknown before correction",
            )
        }
    elif scenario == "t49_c":
        zero_usage = cases[0]["status_before"]["attempts"][0]["usage_revision"]
        checks = {
            "t49_c.contradictory_zero": (
                zero_usage["cost_status"] == "unknown"
                and zero_usage["components"][0].get("quantity") == 0
                and "amount_decimal" not in zero_usage,
                "Reported zero in positive-domain request is retained as unknown with no manufactured amount",
            )
        }
    elif scenario == "t49_d":
        invalid = by_mode["invalid"]
        out_of_domain = by_mode["out_of_domain"]
        contradictory = by_mode["contradictory"]
        invalid_usage = invalid["status_before"]["attempts"][0]["usage_revision"]
        domain_usage = out_of_domain["status_before"]["attempts"][0]["usage_revision"]
        domain_corrected = out_of_domain["status_after"]["attempts"][0]["usage_revision"]
        zero_usage = contradictory["status_before"]["attempts"][0]["usage_revision"]
        checks = {
            "t49_d.invalid_counter": (
                invalid["status_before"]["submission_state"] == "completed"
                and invalid_usage["components"][0]["presence"] == "invalid"
                and invalid_usage["cost_status"] == "unknown",
                "Malformed Unicode native evidence preserves valid delivered content and unknown charge",
            ),
            "t49_d.out_of_domain": (
                domain_usage["cost_status"] == "unknown"
                and domain_usage["components"][0]["presence"] == "known"
                and domain_usage["components"][0]["evidence"] == "reported"
                and domain_usage["components"][0]["quantity"] == 999999999
                and "amount_decimal" not in domain_usage
                and domain_corrected["revision"] == 2
                and domain_corrected["previous_revision"] == 1
                and domain_corrected["cost_status"] == "calculated",
                "Out-of-domain reported quantity remains unpriced until an independent late correction",
            ),
            "t49_d.contradictory_counter": (
                zero_usage["cost_status"] == "unknown"
                and zero_usage["components"][0].get("quantity") == 0,
                "Contradictory reported zero remains explicit and unpriced",
            ),
        }
    elif scenario == "t49_e":
        entry = cases[0]
        first_usage = entry["status_before"]["attempts"][0]["usage_revision"]
        last_usage = entry["status_after"]["attempts"][0]["usage_revision"]
        checks = {
            "t49_e.late_revision_no_resend": (
                first_usage["revision"] == 1
                and last_usage["revision"] == 2
                and last_usage["previous_revision"] == 1
                and entry["after"]["usage_revisions"] == entry["paused"]["usage_revisions"] + 1
                and entry["after"]["receiver_arrivals"] == entry["paused"]["receiver_arrivals"],
                "Independent retained receipt revised one historical attempt without a second send",
            )
        }
    elif scenario == "t50_d":
        entry = cases[0]
        earlier = entry["status_before"]["attempts"][0]["usage_revision"]
        later = entry["status_after"]["attempts"][0]["usage_revision"]
        checks = {
            "t50_d.linked_correction_delta_once": (
                earlier["cost_status"] == "unknown"
                and later["cost_status"] == "calculated"
                and later["revision"] == earlier["revision"] + 1
                and entry["after"]["campaign"]["possible_send_count"]
                == entry["paused"]["campaign"]["possible_send_count"]
                and entry["after"]["receiver_arrivals"] == entry["paused"]["receiver_arrivals"],
                "Linked correction replaces unknown effective amount once without new liability",
            )
        }
    else:
        checks = {
            "t48_f.missing": (
                by_mode["missing"]["status_before"]["attempts"][0]["usage_revision"]["components"][
                    0
                ]["presence"]
                == "absent",
                "Absent native component retained distinctly",
            ),
            "t48_f.null": (
                by_mode["null"]["status_before"]["attempts"][0]["usage_revision"]["components"][0][
                    "presence"
                ]
                == "null",
                "Explicit null native component retained distinctly",
            ),
            "t48_f.invalid": (
                by_mode["invalid"]["status_before"]["attempts"][0]["usage_revision"]["components"][
                    0
                ]["presence"]
                == "invalid",
                "Array native component normalized to bounded invalid evidence",
            ),
            "t48_f.zero": (
                by_mode["zero"]["status_before"]["attempts"][0]["usage_revision"]["components"][
                    0
                ].get("quantity")
                == 0,
                "Explicit zero native component retained rather than erased",
            ),
            "t48_f.contradictory": (
                by_mode["contradictory"]["status_before"]["attempts"][0]["usage_revision"][
                    "cost_status"
                ]
                == "unknown",
                "Derived rather than reported native quantity leaves cost unknown",
            ),
        }
    first, last = cases[0], cases[-1]
    stages = {
        "admission": {
            "attempts_in_case": len(cases),
            "first_submission": first["reply"]["reply"]["handle"]["submission_id"],
        },
        "receiver": {
            "arrival_delta": last["after"]["receiver_arrivals"]
            - first["before"]["receiver_arrivals"]
        },
        "delivery": {"states": [row["status_before"]["submission_state"] for row in cases]},
        "settlement": {
            "unknown_before": [
                row["status_before"]["attempts"][0]["usage_revision"]["cost_status"]
                for row in cases
            ],
            "corrected_after": [
                row["status_after"]["attempts"][0]["usage_revision"]["cost_status"] for row in cases
            ],
        },
    }
    return _api._evidence(
        runtime,
        case,
        stages,
        checks,
        {"observations": cases},
        first["reply"]["reply"].get("attempt_id", "none"),
    )


def _work_owner_contention(runtime, case):
    from tools.gateway.evidence import dev12_completion_handlers as _api

    request = _api._case_request(runtime, case)
    before = _api._census(runtime)
    if case["variant"] == "duplicate_submission":
        first = _api._post(runtime, request, _api._headers(runtime))
        middle = _api._census(runtime)
        second = _api._post(runtime, request, _api._headers(runtime))
        after = _api._census(runtime)
        first_id = first["reply"].get("handle", {}).get("submission_id")
        second_id = second["reply"].get("handle", {}).get("submission_id")
        checks = {
            "t50_b.duplicate_submission": (
                bool(
                    first_id
                    and first_id == second_id
                    and first["status"]
                    and first["status"].get("submission_state") == "completed"
                    and middle["submissions"] == before["submissions"] + 1
                    and after["submissions"] == middle["submissions"]
                    and after["guard_ownership"] == middle["guard_ownership"]
                    and after["receiver_arrivals"] == middle["receiver_arrivals"]
                    and after["campaign"]["cumulative_reserved_decimal"]
                    == middle["campaign"]["cumulative_reserved_decimal"]
                ),
                "Duplicate normal HTTP submit returned original handle without reservation or send",
            )
        }
        payload = {
            "first": first,
            "duplicate": second,
            "before": before,
            "middle": middle,
            "after": after,
        }
        aid = first["reply"].get("attempt_id", "none")
    else:
        competing = _api.deepcopy(request)
        competing["input"]["items"][0]["text"] = "River"
        with _api.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(_api._post, runtime, item, _api._headers(runtime))
                for item in (request, competing)
            ]
            replies = [future.result(timeout=30) for future in futures]
        after = _api._census(runtime)
        admitted = [row for row in replies if row["reply"].get("handle")]
        conflicts = [
            row
            for row in replies
            if row["http_status"] == 409 and row["reply"].get("code") == "WORK_CONFLICT"
        ]
        checks = {
            "t50_b.competing_submission": (
                bool(
                    len(admitted) == len(conflicts) == 1
                    and admitted[0]["status"]
                    and admitted[0]["status"].get("submission_state") == "completed"
                    and after["submissions"] == before["submissions"] + 1
                    and after["guard_ownership"] == before["guard_ownership"] + 1
                    and after["receiver_arrivals"] == before["receiver_arrivals"] + 1
                ),
                "Concurrent changed-content contenders produced one owner and one 409 conflict",
            )
        }
        payload = {"contenders": replies, "before": before, "after": after}
        aid = admitted[0]["reply"].get("attempt_id", "none") if admitted else "none"
    stages = {
        "admission": {"before": before["submissions"], "after": after["submissions"]},
        "receiver": {
            "arrivals_before": before["receiver_arrivals"],
            "arrivals_after": after["receiver_arrivals"],
        },
        "delivery": {
            "guard_ownership_before": before["guard_ownership"],
            "guard_ownership_after": after["guard_ownership"],
        },
        "settlement": {
            "reserved_before": before["campaign"]["cumulative_reserved_decimal"],
            "reserved_after": after["campaign"]["cumulative_reserved_decimal"],
        },
    }
    return _api._evidence(runtime, case, stages, checks, payload, aid)


def _native_minima(runtime, case):
    from tools.gateway.evidence import dev12_completion_handlers as _api

    before = _api._census(runtime)
    one_batch = _api._retrieval_request(
        runtime, case, "DELEGATED_RERANK", "one_batch", ["doc.a", "doc.b", "doc.c"]
    )
    batch = _api._post(runtime, one_batch, _api._headers(runtime, "DELEGATED_RERANK"))
    after_batch = _api._census(runtime)
    duplicate = _api._post(runtime, one_batch, _api._headers(runtime, "DELEGATED_RERANK"))
    after_duplicate = _api._census(runtime)
    splits = []
    for index in range(3):
        request = _api._retrieval_request(
            runtime, case, "DELEGATED_RERANK", "split_" + str(index), ["doc." + str(index)]
        )
        splits.append(_api._post(runtime, request, _api._headers(runtime, "DELEGATED_RERANK")))
    after = _api._census(runtime)
    batch_usage = batch["status"]["attempts"][0]["usage_revision"] if batch["status"] else {}
    split_usage = [
        row["status"]["attempts"][0]["usage_revision"] for row in splits if row["status"]
    ]
    split_total = sum(
        (_api.Decimal(row.get("amount_decimal", "0")) for row in split_usage), _api.Decimal("0")
    )
    checks = {
        "t48_g.three_distinct_minima": (
            len(split_usage) == 3
            and all(
                row.get("cost_status") == "calculated"
                and _api.Decimal(row["amount_decimal"]) == _api.Decimal("0.000300000")
                for row in split_usage
            )
            and split_total == _api.Decimal("0.000900000"),
            "Three distinct n=1 Tariff B attempts each settle the downward half-even tie",
        ),
        "t48_g.one_batch_n3": (
            batch_usage.get("cost_status") == "calculated"
            and batch_usage.get("components", [{}])[0].get("quantity") == 3
            and _api.Decimal(batch_usage.get("amount_decimal", "0")) == _api.Decimal("0.000900002"),
            "One n=3 Tariff B batch settles the opposite half-even tie",
        ),
        "t48_g.repeated_attempt": (
            duplicate["reply"].get("handle") == batch["reply"].get("handle")
            and after_duplicate["submissions"] == after_batch["submissions"]
            and after_duplicate["receiver_arrivals"] == after_batch["receiver_arrivals"]
            and after_duplicate["campaign"]["cumulative_reserved_decimal"]
            == after_batch["campaign"]["cumulative_reserved_decimal"],
            "Exact repeated work returns original attempt with no second minimum or send",
        ),
        "t48_g.split_batch": (
            after["receiver_arrivals"] == before["receiver_arrivals"] + 4
            and after["submissions"] == before["submissions"] + 4
            and split_total == _api.Decimal("0.000900000")
            and split_total < _api.Decimal(batch_usage.get("amount_decimal", "0")),
            "Equal raw aggregate rounds differently when split across three attempts",
        ),
    }
    stages = {
        "accounting": {
            "batch_amount": batch_usage.get("amount_decimal", "unknown"),
            "split_amounts": [row.get("amount_decimal") for row in split_usage],
            "attempt_delta": after["submissions"] - before["submissions"],
        }
    }
    return _api._evidence(
        runtime,
        case,
        stages,
        checks,
        {
            "batch": batch,
            "duplicate": duplicate,
            "splits": splits,
            "before": before,
            "after_batch": after_batch,
            "after_duplicate": after_duplicate,
            "after": after,
        },
        batch["reply"].get("attempt_id", "none"),
    )


def _nominal_native_tariffs(runtime, case):
    from tools.gateway.evidence import dev12_completion_handlers as _api

    if case["variant"] != "composed" or case["scenario_id"] not in {
        "t48_a",
        "t48_b",
        "t48_c",
        "t48_d",
        "t48_e",
    }:
        raise NotImplementedError("native target/evidence branch is not implemented")
    table = _api.json.loads(
        (
            _api.source_root(_api.__file__)
            / "tests/fixtures/contracts/dev12-successor-01/tariffs.json"
        ).read_text()
    )
    quantum = _api.Decimal("0.000000001")
    assert table["fictional"] is True and table["currency"] == "USD"
    calculated = []
    for row in table["rows"]:
        n = row["documents"]
        a_units = (n + 9) // 10
        a_raw = max(_api.Decimal("0.005"), _api.Decimal(a_units) * _api.Decimal("0.003"))
        b_rate = _api.Decimal("0.0003000005" if n <= 10 else "0.0004000005")
        b_raw = _api.Decimal(n) * b_rate
        projection = {
            "documents": n,
            "tariff_a": {
                "search_units": a_units,
                "raw_usd": a_raw,
                "settled_usd": a_raw.quantize(quantum, rounding=_api.ROUND_HALF_EVEN),
                "request_bound_usd": a_raw.quantize(quantum, rounding=_api.ROUND_CEILING),
            },
            "tariff_b": {
                "document_units": n,
                "raw_usd": b_raw,
                "settled_usd": b_raw.quantize(quantum, rounding=_api.ROUND_HALF_EVEN),
                "request_bound_usd": b_raw.quantize(quantum, rounding=_api.ROUND_CEILING),
            },
        }
        calculated.append(projection)

    def row_matches(index, schedule):
        expected = table["rows"][index][schedule]
        actual = calculated[index][schedule]
        return (
            all(
                actual[key] == _api.Decimal(expected[key])
                for key in ("raw_usd", "settled_usd", "request_bound_usd")
            )
            and actual["search_units" if schedule == "tariff_a" else "document_units"]
            == expected["search_units" if schedule == "tariff_a" else "document_units"]
        )

    a_all = all(row_matches(index, "tariff_a") for index in range(25))
    b_all = all(row_matches(index, "tariff_b") for index in range(25))
    bindings = table["operation_bindings"]
    components = {row["component"] for row in bindings}
    calculated_data = []
    for row in calculated:
        projected = {"documents": row["documents"]}
        for schedule in ("tariff_a", "tariff_b"):
            projected[schedule] = {
                key: format(value, "f") if isinstance(value, _api.Decimal) else value
                for key, value in row[schedule].items()
            }
        calculated_data.append(projected)
    scenario = case["scenario_id"]
    if scenario == "t48_a":
        checks = {
            "t48_a.native_non_token_quantity": (
                components == {"search_units", "document_units", "query_units"}
                and all(
                    row["tariff_a"]["search_units"] == (row["documents"] + 9) // 10
                    and row["tariff_b"]["document_units"] == row["documents"]
                    for row in calculated
                ),
                "Search/document/query units are operation-native, not token quantities",
            ),
            "t48_a.price_contract": (
                len(bindings) == 4
                and len({row["price_ref"] for row in bindings}) == 4
                and a_all
                and b_all
                and _api.Decimal(table["embedding_document"]["per_item_usd"])
                == _api.Decimal("0.000200000")
                and _api.Decimal(table["embedding_query"]["per_item_usd"])
                == _api.Decimal("0.000200000"),
                "Four fixed fictional price bindings and all listed rows match independent Decimal arithmetic",
            ),
        }
    elif scenario == "t48_b":
        checks = {
            "t48_b.tariff_a_all_25_inputs": (
                a_all and [row["documents"] for row in table["rows"]] == list(range(1, 26)),
                "All 25 Tariff A input counts match independent ceiling/minimum/settlement arithmetic",
            ),
            "t48_b.minimum": (
                all(row["tariff_a"]["raw_usd"] >= _api.Decimal("0.005") for row in calculated)
                and calculated[0]["tariff_a"]["raw_usd"] == _api.Decimal("0.005"),
                "Per-attempt USD 0.005 minimum applies at low counts",
            ),
            "t48_b.ceiling": (
                calculated[9]["tariff_a"]["search_units"] == 1
                and calculated[10]["tariff_a"]["search_units"] == 2
                and calculated[20]["tariff_a"]["search_units"] == 3,
                "Search-unit ceiling changes at 10/11 and 20/21 documents",
            ),
        }
    elif scenario == "t48_c":
        checks = {
            "t48_c.tariff_b_n10": (
                b_all and calculated[9]["tariff_b"]["raw_usd"] == _api.Decimal("0.0030000050"),
                "Tariff B n=10 uses lower whole-request rate for all ten units",
            ),
            "t48_c.tariff_b_n11": (
                calculated[10]["tariff_b"]["raw_usd"] == _api.Decimal("0.0044000055")
                and calculated[10]["tariff_b"]["settled_usd"] == _api.Decimal("0.004400006"),
                "Tariff B n=11 applies upper rate to all eleven units",
            ),
        }
    elif scenario == "t48_d":
        checks = {
            "t48_d.half_even_up_tie": (
                calculated[2]["tariff_b"]["raw_usd"] == _api.Decimal("0.0009000015")
                and calculated[2]["tariff_b"]["settled_usd"] == _api.Decimal("0.000900002"),
                "Half-even rounds the n=3 tie upward to even nano digit",
            ),
            "t48_d.half_even_down_tie": (
                calculated[0]["tariff_b"]["raw_usd"] == _api.Decimal("0.0003000005")
                and calculated[0]["tariff_b"]["settled_usd"] == _api.Decimal("0.000300000"),
                "Half-even rounds the n=1 tie downward to even nano digit",
            ),
        }
    else:
        checks = {
            "t48_e.reservation_raw": (
                all(
                    row[schedule]["request_bound_usd"] >= row[schedule]["raw_usd"]
                    for row in calculated
                    for schedule in ("tariff_a", "tariff_b")
                ),
                "Upward reservation covers each unrounded raw amount at all 25 counts",
            ),
            "t48_e.reservation_settled": (
                all(
                    row[schedule]["request_bound_usd"] >= row[schedule]["settled_usd"]
                    for row in calculated
                    for schedule in ("tariff_a", "tariff_b")
                ),
                "Upward reservation covers every independently half-even settled amount",
            ),
        }
    return _api._evidence(
        runtime,
        case,
        {
            "accounting": {
                "fictional_currency": "USD",
                "checked_rows": 25,
                "four_price_bindings": len(bindings),
            }
        },
        checks,
        {
            "tariffs_sha256": _api.sha256(
                (
                    _api.source_root(_api.__file__)
                    / "tests/fixtures/contracts/dev12-successor-01/tariffs.json"
                ).read_bytes()
            ).hexdigest(),
            "independent_rows": calculated_data,
            "fixture_rows": table["rows"],
            "operation_bindings": bindings,
        },
        case["attempt_group"],
    )


def _completed_historical_attempt(runtime):
    from tools.gateway.evidence import dev12_completion_handlers as _api

    with runtime.store._lock:
        source_rows = [
            _api.json.loads(row[0])
            for row in runtime.store.db.execute(
                "SELECT record FROM dev12_submissions ORDER BY rowid"
            )
        ]
    chosen = None
    for source in source_rows:
        latest = runtime.store.successor_latest_usage(source["attempt_id"])
        if (
            source["submission_state"] == "completed"
            and latest
            and latest["cost_status"] == "calculated"
            and _api.Decimal(latest["amount_decimal"]) > _api.Decimal("0.000100000")
            and any(
                row["attempt_id"] == source["attempt_id"]
                for row in [
                    _api.json.loads(line) for line in runtime.receiver_log.read_text().splitlines()
                ]
            )
        ):
            chosen = (source, latest)
            break
    if chosen is None:
        raise AssertionError("genuine completed receiver/control attempt unavailable")
    source, source_usage = chosen
    return source, source_usage


def _consistent_zero_control(runtime, case):
    from tools.gateway.evidence import dev12_completion_handlers as _api

    request = _api._case_request(runtime, case)
    before = _api._census(runtime)
    positive = _api._post(runtime, request, _api._headers(runtime))
    after = _api._census(runtime)
    usage = (positive["status"] or {}).get("attempts", [{}])[0].get("usage_revision", {})
    prices = _api.json.loads(
        (
            _api.source_root(_api.__file__)
            / "tests/fixtures/contracts/dev12-successor-01/tariffs.json"
        ).read_text()
    )
    consistent = bool(
        usage.get("cost_status") == "calculated"
        and usage.get("components", [{}])[0].get("quantity") == 1
        and all(
            _api.Decimal(row["tariff_b"]["raw_usd"]) > 0
            and _api.Decimal(row["tariff_a"]["raw_usd"]) > 0
            for row in prices["rows"]
        )
        and _api.Decimal(prices["embedding_document"]["per_item_usd"]) > 0
        and _api.Decimal(prices["embedding_query"]["per_item_usd"]) > 0
        and after["receiver_arrivals"] == before["receiver_arrivals"] + 1
    )
    checks = {
        "t49_c.consistent_zero": (
            consistent,
            "A valid one-unit charged control confirms no zero-unit result is consistent with this fixed positive-domain profile",
        )
    }
    stages = {
        "admission": {
            "submission_id": positive["reply"].get("handle", {}).get("submission_id", "absent")
        },
        "receiver": {"arrivals_delta": after["receiver_arrivals"] - before["receiver_arrivals"]},
        "delivery": {"state": (positive["status"] or {}).get("submission_state", "absent")},
        "settlement": {
            "cost_status": usage.get("cost_status", "absent"),
            "quantity": usage.get("components", [{}])[0].get("quantity", -1),
        },
    }
    return _api._evidence(
        runtime,
        case,
        stages,
        checks,
        {
            "positive": positive,
            "before": before,
            "after": after,
            "fixed_tariff_domain": prices["domain"],
        },
        positive["reply"].get("attempt_id", "none"),
    )
