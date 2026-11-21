"""dev12_completion_supplement_handlers supplement state domain; entry points remain on the facade."""

from __future__ import annotations


def _recovery(runtime, case):
    """Exact installed SDK status/duplicate recovery under logical retention."""
    from tools.gateway.evidence import dev12_completion_supplement_handlers as _api
    from ezllmrouter_client import EzLLMRouterClient, EzLLMRouterError

    variant = case["variant"]
    # A retry of the wheel's status-only recovery must use the original
    # selector even if its evidence document needs a new one-use case ID.
    request_case = {**case, "id": "case.ct02_recovery.wheel"} if variant == "wheel" else case
    request = _api._case_request(runtime, request_case)
    before = _api._census(runtime)
    key = {
        "principal_id": runtime.contexts_by_credential[runtime.credentials["DIRECT_DOCUMENT"]][
            "identity"
        ]["principal_id"],
        **request["work_selector"],
    }
    prior = runtime.store.successor_by_work(key)
    if prior is not None:
        # A stopped case may already have performed its one authorized send.
        # Reuse its exact admitted bytes and independent ownership/arrival;
        # never resubmit under a new WorkKey merely to repair test plumbing.
        if variant != "wheel" or prior["campaign_id"] != runtime.allowance.campaign_id:
            raise AssertionError("unexpected retained recovery setup")
        sid = prior["submission_id"]
        request = _api.deepcopy(prior["request"])
        with runtime.store._lock:
            ownership = runtime.store.db.execute(
                "SELECT COUNT(*) FROM dev12_send_ownership WHERE attempt_id=? AND submission_id=?",
                (prior["attempt_id"], sid),
            ).fetchone()[0]
        arrivals = sum(
            row.get("attempt_id") == prior["attempt_id"]
            for row in (
                _api.json.loads(line) for line in runtime.receiver_log.read_text().splitlines()
            )
        )
        observed = _api._post_status(runtime, {"submission_id": sid}, _api._headers(runtime))
        if (
            ownership != 1
            or arrivals != 1
            or observed["http_status"] != 200
            or observed["body"].get("submission_state") != "completed"
        ):
            raise AssertionError("retained recovery setup lacks one owned receiver arrival")
        sent = {
            "http_status": observed["http_status"],
            "reply": {"handle": {"submission_id": sid}, "attempt_id": prior["attempt_id"]},
            "status": observed["body"],
            "retained_prior_setup": True,
            "owned_receiver_arrivals": arrivals,
        }
    else:
        sent = _api._post(runtime, request, _api._headers(runtime))
        sid = sent["reply"].get("handle", {}).get("submission_id")
    if not sid or not sent["status"] or sent["status"].get("submission_state") != "completed":
        raise AssertionError("recovery control did not complete once")
    admitted = _api._census(runtime)
    record = runtime.store.successor_get(sid)
    old_direct_token = runtime.credentials["DIRECT_DOCUMENT"]
    if variant == "wheel":
        retained = runtime.root / "continuation-direct-secret.json"
        if retained.exists():
            # The previous stopped case committed the one-use registry change.
            # _bind_contexts loaded this private token; never provision twice.
            if retained.is_symlink() or retained.stat().st_mode & 0o077:
                raise RuntimeError("retained disposable credential unsafe")
            if (
                runtime.registry.credential_principal(old_direct_token)["principal_id"]
                != record["work_key"]["principal_id"]
            ):
                raise AssertionError("renewed credential does not bind original owner")
            old_direct_token = "dev12.completion02.synthetic.0." + "x" * 32
        else:
            principal = runtime.registry.principal(record["work_key"]["principal_id"])
            _credential, new_token = runtime.registry.provision_credential(
                "owner.local",
                record["work_key"]["principal_id"],
                principal["revision"],
                "op.dev12.ct02.renew.direct",
            )
            if not new_token:
                raise AssertionError("one-use synthetic credential renewal unavailable")
            with _api.os.fdopen(
                _api.os.open(retained, _api.os.O_WRONLY | _api.os.O_CREAT | _api.os.O_EXCL, 0o600),
                "wb",
            ) as stream:
                stream.write((_api.json.dumps({"direct": new_token}) + "\n").encode())
                stream.flush()
                _api.os.fsync(stream.fileno())
            context = runtime.contexts_by_credential.pop(old_direct_token)
            runtime.contexts_by_credential[new_token] = context
            runtime.coordinator.identity[new_token] = runtime.coordinator.identity.pop(
                old_direct_token
            )
            runtime.credentials["DIRECT_DOCUMENT"] = new_token
    selector_id = {"submission_id": sid}
    selector_work = {"work_selector": _api.deepcopy(request["work_selector"])}
    cutoff = _api.datetime.fromisoformat(
        record["result_available_at"].replace("Z", "+00:00")
    ) + _api.timedelta(days=7)
    before_cutoff = (cutoff - _api.timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    at_cutoff = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    # This is a renewed disposable credential, evaluated at a seven-day
    # logical retention clock. Keep its synthetic authenticated context valid
    # for that clock; the original admitted context and real campaign expiry
    # remain immutable. No registry grant or operational identity is changed.
    synthetic_expiry = (cutoff + _api.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    current_token = runtime.credentials["DIRECT_DOCUMENT"]
    runtime.contexts_by_credential[current_token]["expires_at"] = synthetic_expiry
    runtime.coordinator.identity[current_token]["expires_at"] = synthetic_expiry
    original_clock = runtime.successor.clock
    outcomes = {}

    def wheel(duplicate):
        with EzLLMRouterClient(
            runtime.base_url, runtime.credentials["DIRECT_DOCUMENT"], timeout=12
        ) as client:
            selected = {
                "by_id": client.get_successor_status(selector_id),
                "by_work": client.get_successor_status(selector_work),
            }
            if duplicate:
                try:
                    selected["duplicate"] = client.submit_embedding(request, {"wait_ms": 5000})
                except EzLLMRouterError as exc:
                    selected["duplicate_error"] = {
                        "code": exc.code,
                        "http_status": exc.http_status,
                        "retry_guidance": exc.retry_guidance,
                        "handle": exc.handle,
                    }
            return selected

    def tarball(duplicate, label):
        private = runtime.root / "cases" / (case["id"] + "." + label + ".js-private-input.json")
        data = {
            "package_path": str(runtime.installed_js_root),
            "base_url": runtime.base_url,
            "token": runtime.credentials["DIRECT_DOCUMENT"],
            "action": "recover",
            "selectors": {"by_id": selector_id, "by_work": selector_work},
            "duplicate_request": request if duplicate else None,
        }
        raw = (_api.json.dumps(data, sort_keys=True, ensure_ascii=True) + "\n").encode()
        with _api.os.fdopen(
            _api.os.open(private, _api.os.O_WRONLY | _api.os.O_CREAT | _api.os.O_EXCL, 0o600), "wb"
        ) as stream:
            stream.write(raw)
            stream.flush()
            _api.os.fsync(stream.fileno())
        run = _api.subprocess.run(
            [
                "/dev12-node",
                str(_api.Path(_api.__file__).with_name("dev12_completion_js_actor.cjs")),
                str(private),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if run.returncode:
            raise AssertionError("exact installed CommonJS recovery failed: " + run.stderr[-400:])
        return _api.json.loads(run.stdout)

    selected = wheel if variant == "wheel" else tarball
    try:
        runtime.successor.clock = lambda: before_cutoff
        outcomes["before"] = selected(True) if variant == "wheel" else selected(True, "before")
        outcomes["old_credential_denial"] = (
            _api._post_status(
                runtime,
                selector_id,
                {
                    "Authorization": "Bearer " + old_direct_token,
                    "EzLLMRouter-Contract-Version": "0.3",
                },
            )
            if variant == "wheel"
            else None
        )
        identity = record["trusted_identity"]
        runtime.authority.set_historical_access(
            identity, read=False, write=True, resume=True, observed_at=before_cutoff
        )
        outcomes["current_denial"] = _api._post_status(runtime, selector_id, _api._headers(runtime))
        runtime.authority.set_historical_access(
            identity, read=True, write=True, resume=True, observed_at=before_cutoff
        )
        outcomes["renewed"] = _api._post_status(runtime, selector_work, _api._headers(runtime))
        runtime.successor.clock = lambda: at_cutoff
        outcomes["cutoff"] = selected(True) if variant == "wheel" else selected(True, "cutoff")
        changed = _api.deepcopy(request)
        changed["input"]["items"][0]["text"] = "River"
        outcomes["changed"] = _api._post(runtime, changed, _api._headers(runtime))
        legacy = _api.json.loads(
            (_api.source_root(_api.__file__) / "tests/development_slice/request.json").read_text()
        )
        legacy["task_id"] = request["work_selector"]["task_id"]
        legacy["step_id"] = request["work_selector"]["step_id"]
        legacy["step_revision"] = request["work_selector"]["step_revision"]
        legacy["execution_generation"] = request["work_selector"]["execution_generation"]
        legacy["requested_configuration_ref"] = "cfg.demo"
        legacy["deadline"] = at_cutoff
        _api._legacy_prewrite_setup(runtime)
        outcomes["wrong_version"] = _api._post(
            runtime, legacy, _api._headers(runtime, version="0.2")
        )
    finally:
        runtime.successor.clock = original_clock
        if not runtime.authority.historical_allowed(record["trusted_identity"], record, "read"):
            runtime.authority.set_historical_access(
                record["trusted_identity"],
                read=True,
                write=True,
                resume=True,
                observed_at=_api.datetime.now(_api.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
    after = _api._census(runtime)

    def status(item, key):
        return item[key] if variant == "wheel" else item[key].get("status")

    def duplicate(item):
        return item.get("duplicate") if variant == "wheel" else item["duplicate"]

    before_result = outcomes["before"]
    cutoff_result = outcomes["cutoff"]
    initial_visible = all(
        status(before_result, key) and status(before_result, key)["candidate_access"] == "present"
        for key in ("by_id", "by_work")
    )
    expired_visible = all(
        status(cutoff_result, key)
        and status(cutoff_result, key)["candidate_access"] == "expired"
        and "result" not in status(cutoff_result, key)["attempts"][0]
        and status(cutoff_result, key)["attempts"][0]["settlement_state"]
        == sent["status"]["attempts"][0]["settlement_state"]
        for key in ("by_id", "by_work")
    )
    before_duplicate = duplicate(before_result) or {}
    cutoff_duplicate = duplicate(cutoff_result) or {}
    duplicate_before_ok = (
        before_duplicate.get("handle", {}).get("submission_id") == sid
        if variant == "wheel"
        else before_duplicate.get("reply", {}).get("handle", {}).get("submission_id") == sid
    )
    cutoff_error = (
        outcomes["cutoff"].get("duplicate_error")
        if variant == "wheel"
        else cutoff_duplicate.get("error")
    ) or {}
    checks = {
        f"ct02_recovery.{variant}.selectors": (
            bool(initial_visible and expired_visible),
            "Both installed-client selectors retain same attempt and finance before/at cutoff",
        ),
        f"ct02_recovery.{variant}.duplicate": (
            bool(
                duplicate_before_ok
                and cutoff_error.get("code") == "POLICY_DENIED"
                and cutoff_error.get("http_status") == 403
                and cutoff_error.get("retry_guidance") == "query_first"
            ),
            "Unchanged duplicate recovers before cutoff and becomes strict query-first at cutoff",
        ),
        f"ct02_recovery.{variant}.denial": (
            bool(
                outcomes["current_denial"]["http_status"] == 404
                and (variant != "wheel" or outcomes["old_credential_denial"]["http_status"] == 401)
                and outcomes["renewed"]["http_status"] == 200
                and outcomes["changed"]["http_status"] == 409
                and outcomes["wrong_version"]["http_status"] == 409
            ),
            "Current denial is non-enumerating; restored auth reads; conflicts remain conflicts",
        ),
        f"ct02_recovery.{variant}.no_repeat": (
            bool(
                after["submissions"] == admitted["submissions"]
                and after["guard_ownership"] == admitted["guard_ownership"]
                and after["receiver_arrivals"] == admitted["receiver_arrivals"]
                and after["campaign"]["cumulative_reserved_decimal"]
                == admitted["campaign"]["cumulative_reserved_decimal"]
            ),
            "Read, duplicate and denied recovery allocated no additional attempt or send",
        ),
    }
    return _api._evidence(
        runtime,
        case,
        {
            "client": {"artifact": variant, "selectors": ["submission_id", "work_selector"]},
            "admission": {"new": admitted["submissions"] - before["submissions"]},
            "settlement": {
                "before": sent["status"]["attempts"][0]["settlement_state"],
                "after": status(cutoff_result, "by_id")["attempts"][0]["settlement_state"],
            },
        },
        checks,
        {
            "request": request,
            "sent": sent,
            "outcomes": outcomes,
            "before": before,
            "admitted": admitted,
            "after": after,
            "cutoff_origin": record["result_available_at"],
            "cutoff": at_cutoff,
            "renewed_synthetic_context_expires_at": synthetic_expiry,
        },
        record["attempt_id"],
    )


def _authority_atomic(runtime, case):
    """Commit/publication ordering, definite rollback and fail-closed restart."""
    from tools.gateway.evidence import dev12_completion_supplement_handlers as _api
    from ezllmrouter_server.successor_plan import execution_eligible

    before = _api._census(runtime)
    control_request = _api._case_request(runtime, case)
    control_request["work_selector"]["step_id"] += ".before"
    control = _api._post(runtime, control_request, _api._headers(runtime))
    control_sid = control["reply"].get("handle", {}).get("submission_id")
    if not control_sid or control["status"]["submission_state"] != "completed":
        raise AssertionError("authority order control did not complete")
    old = runtime.store.successor_get(control_sid)
    original_revision = runtime.authority.revisions()["grant"]
    original_transaction = runtime.store._transaction

    class DefiniteRollback(RuntimeError):
        ezllmrouter_definite_rollback = True

    def fail_definitely(_action):
        raise DefiniteRollback("synthetic rollback before durable commit")

    runtime.store._transaction = fail_definitely
    try:
        try:
            runtime.authority.update(
                lambda state: state["revisions"].__setitem__(
                    "grant", state["revisions"]["grant"] + 1
                ),
                {"kind": "ct02_definite_rollback"},
            )
        except DefiniteRollback:
            rollback_caught = True
        else:
            rollback_caught = False
    finally:
        runtime.store._transaction = original_transaction
    rollback_revision = runtime.authority.revisions()["grant"]
    rollback_coherent = not runtime.authority.revoked and rollback_revision == original_revision

    entered, release, read_done = (
        _api.threading.Event(),
        _api.threading.Event(),
        _api.threading.Event(),
    )
    order = []
    errors = []

    def stalled_transaction(action):
        order.append("gate_held_transaction_entered")
        entered.set()
        if not release.wait(5):
            raise TimeoutError("synthetic authority commit stall exceeded bound")
        result = original_transaction(action)
        order.append("durable_authority_audit_committed")
        return result

    original_publish = runtime.authority._publish

    def observed_publish(state):
        order.append("matching_view_published")
        return original_publish(state)

    runtime.store._transaction = stalled_transaction
    runtime.authority._publish = observed_publish

    def writer():
        try:
            runtime.authority.update(
                lambda state: state["revisions"].__setitem__(
                    "grant", state["revisions"]["grant"] + 1
                ),
                {"kind": "ct02_stalled_commit"},
            )
            order.append("update_acknowledged")
        except BaseException as exc:
            errors.append(type(exc).__name__)

    def reader():
        runtime.authority.revisions()
        order.append("reader_acquired_released_gate")
        read_done.set()

    try:
        commit_thread = _api.threading.Thread(target=writer, daemon=True)
        commit_thread.start()
        if not entered.wait(5):
            raise TimeoutError("authority update never entered stalled transaction")
        read_thread = _api.threading.Thread(target=reader, daemon=True)
        read_thread.start()
        reader_blocked = not read_done.wait(0.05)
        release.set()
        commit_thread.join(5)
        read_thread.join(5)
        if commit_thread.is_alive() or read_thread.is_alive():
            raise TimeoutError("authority gate stall did not resolve")
    finally:
        release.set()
        runtime.store._transaction = original_transaction
        runtime.authority._publish = original_publish
    stalled_revision = runtime.authority.revisions()["grant"]

    def fail_publish(_state):
        raise RuntimeError("synthetic publication interruption after commit")

    runtime.authority._publish = fail_publish
    try:
        try:
            runtime.authority.update(
                lambda state: state["revisions"].__setitem__(
                    "grant", state["revisions"]["grant"] + 1
                ),
                {"kind": "ct02_committed_unpublished"},
            )
        except RuntimeError:
            publication_failed = True
        else:
            publication_failed = False
    finally:
        runtime.authority._publish = original_publish
    with runtime.store._lock:
        durable = _api.json.loads(
            runtime.store.db.execute(
                "SELECT state FROM dev12_authority WHERE authority_id='standalone.synthetic'"
            ).fetchone()[0]
        )
    revoked_before_restart = runtime.authority.revoked
    try:
        runtime.authority.snapshot_epoch()
    except PermissionError:
        denied_unpublished = True
    else:
        denied_unpublished = False
    before_restart = _api._census(runtime)
    restarted = runtime.restart_service()
    after_restart = _api._census(runtime)
    current = runtime.authority.current_context(
        old, _api.datetime.now(_api.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    old_ineligible = not execution_eligible(
        old["signed_plan"],
        old["request"],
        old["canonical_work"],
        old["admission_snapshot"],
        current,
    )
    new_request = _api._case_request(runtime, case)
    new_request["work_selector"]["step_id"] += ".after.restart"
    fresh = _api._post(runtime, new_request, _api._headers(runtime))
    after = _api._census(runtime)
    ordered = (
        not errors
        and reader_blocked
        and order[:3]
        == [
            "gate_held_transaction_entered",
            "durable_authority_audit_committed",
            "matching_view_published",
        ]
        and "update_acknowledged" in order
        and "reader_acquired_released_gate" in order
    )
    checks = {
        "ct02_authority_atomic.definite_rollback": (
            bool(rollback_caught and rollback_coherent),
            "Definite rollback retained old coherent verification and send view",
        ),
        "ct02_authority_atomic.stalled_commit": (
            bool(ordered and stalled_revision == original_revision + 1),
            "Gate blocked readers until authority/audit commit, matching publication and acknowledgement",
        ),
        "ct02_authority_atomic.unpublished": (
            bool(
                publication_failed
                and revoked_before_restart
                and denied_unpublished
                and durable["revisions"]["grant"] == stalled_revision + 1
            ),
            "Committed but unpublished revision failed closed before any new send",
        ),
        "ct02_authority_atomic.restart": (
            bool(
                restarted["campaign_before"]["attempt_count"]
                == restarted["campaign_after"]["attempt_count"]
                and before_restart["receiver_arrivals"] == after_restart["receiver_arrivals"]
                and runtime.authority.revisions()["grant"] == durable["revisions"]["grant"]
                and old_ineligible
                and fresh["status"]["submission_state"] == "completed"
                and after["receiver_arrivals"] == after_restart["receiver_arrivals"] + 1
            ),
            "Same-campaign restart loaded durable authority and fresh current plan sent once",
        ),
    }
    return _api._evidence(
        runtime,
        case,
        {
            "authority": {
                "ordered_events": order,
                "durable_grant_revision": durable["revisions"]["grant"],
                "revoked_before_restart": revoked_before_restart,
            },
            "persistence": {"restart": restarted},
            "receiver": {"new_arrivals": after["receiver_arrivals"] - before["receiver_arrivals"]},
        },
        checks,
        {
            "control": control,
            "fresh": fresh,
            "old_plan": old["signed_plan"],
            "order": order,
            "errors": errors,
            "rollback_caught": rollback_caught,
            "publication_failed": publication_failed,
            "denied_unpublished": denied_unpublished,
            "before": before,
            "before_restart": before_restart,
            "after_restart": after_restart,
            "after": after,
            "durable_authority": durable,
        },
        fresh["reply"].get("attempt_id", "none"),
    )
