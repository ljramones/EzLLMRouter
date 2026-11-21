"""Read-only retained-work HTTP and exact installed-wheel auth projection.

Runs a disposable Coordinator over a consistent private copy, without an
executor/worker/sender. Its synthetic credentials are local to this process.
The service remains up for a bounded CommonJS client check until STOP appears.
"""

from __future__ import annotations

if not __package__:
    import sys
    from pathlib import Path

    for _parent in Path(__file__).resolve().parents:
        if (_parent / "tools/gateway/__init__.py").is_file():
            sys.path.insert(0, str(_parent))
            break
        if (_parent / "server/tools/gateway/__init__.py").is_file():
            sys.path.insert(0, str(_parent / "server"))
            break


from tools.gateway.paths import source_root

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys
import threading
import time

ROOT = source_root(__file__)
from cryptography.hazmat.primitives import serialization
import httpx
from ezllmrouter_server.canonical import ContractError
from ezllmrouter_server.core import Coordinator
from ezllmrouter_server.store import SQLiteStore
from tools.synthetic.successor_authority import SyntheticSuccessorAuthority
from tools.synthetic.successor_campaign import FiniteSuccessorCampaign
from tools.synthetic.successor_service import SuccessorService
from ezllmrouter_server.web import serve

PORT = 8768
RENEWED = "dev12.continue03.renewed.synthetic"
OLD = "dev12.continue03.revoked.synthetic"
FOREIGN = "dev12.continue03.foreign.synthetic"


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def census(store):
    names = (
        "submissions",
        "intents",
        "work_key_owners",
        "dev12_submissions",
        "dev12_send_ownership",
        "dev12_usage_revisions",
        "dev12_campaign_attempts",
    )
    with store._lock:
        return {
            name: store.db.execute("SELECT COUNT(*) FROM " + name).fetchone()[0] for name in names
        }


def main(target, package_root, output):
    source = target / "campaign.sqlite"
    if (
        output.exists()
        or not source.is_file()
        or not (package_root / "ezllmrouter_client").is_dir()
    ):
        raise ValueError("fresh owned output, target and exact unpacked wheel required")
    source_hash, receiver_hash = digest(source), digest(target / "receiver.jsonl")
    output.mkdir(parents=True)
    copy = output / "private-retained-copy.sqlite"
    with sqlite3.connect("file:" + str(source) + "?mode=ro", uri=True) as original:
        with sqlite3.connect(copy) as destination:
            original.backup(destination)
    store = SQLiteStore(copy)
    with store._lock:
        state = json.loads(
            store.db.execute(
                "SELECT state FROM dev12_authority WHERE authority_id='standalone.synthetic'"
            ).fetchone()[0]
        )
        records = [
            json.loads(row[0])
            for row in store.db.execute(
                "SELECT record FROM dev12_submissions WHERE "
                "json_extract(record,'$.work_key.principal_id')='user.demo' "
                "AND json_extract(record,'$.submission_state')='completed' ORDER BY rowid"
            )
        ]
    record = next(
        (row for row in records if row["campaign_id"] == "campaign.dev12.c02.20261026.continue01"),
        None,
    )
    if record is None:
        raise AssertionError("retained completed source absent")
    selector = state["active_minting_key"]
    key_path = target / ("signing-key-" + selector["key_version"] + ".pem")
    if selector["key_version"] == "v1":
        key_path = target / "signing-key.pem"
    private = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    authority = SyntheticSuccessorAuthority(
        store, private, selector["key_id"], selector["key_version"]
    )
    campaign = FiniteSuccessorCampaign(
        store,
        "campaign.dev12.c02.20261026.continue01",
        "budget.dev12.c02.20261026.continue01",
        financial_owner_id="team.dev12.c02.20261026.continue01",
    )
    assert campaign.inspect()["paused"]
    trusted = {
        **record["trusted_identity"],
        "task_id": record["work_key"]["task_id"],
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
    }
    # A former token is deliberately absent from the current identity map.
    # No operational token or real account is loaded into this assembly.
    foreign = {**trusted, "principal_id": "user.foreign"}
    coordinator = Coordinator(
        None,
        identity={RENEWED: trusted, FOREIGN: foreign},
        config={},
        prompt_blocks={},
        allowed_lineages={},
        authority=None,
        adapter=None,
        retention={},
        classification={},
        recipe=None,
    )
    successor = SuccessorService(
        store,
        {},
        authority,
        object(),
        campaign,
        read_allowed=lambda _identity, _record: True,
        usage_write_allowed=lambda _identity, _record: True,
    )
    coordinator.successor = successor
    for token in (OLD, "invalid.synthetic"):
        try:
            coordinator.authenticate(token)
        except ContractError as exc:
            assert (exc.code, exc.status) == ("AUTHENTICATION_FAILED", 401)
        else:
            raise AssertionError("revoked/invalid synthetic credential unexpectedly accepted")
    before = census(store)
    server = serve("0.0.0.0", PORT, coordinator)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{PORT}"
    sid = record["submission_id"]
    work = {
        key: record["work_key"][key]
        for key in ("task_id", "step_id", "step_revision", "execution_generation")
    }
    paths = (
        "/v1/submissions/" + sid,
        "/v1/submissions/by-work/" + "/".join(str(work[key]) for key in work),
    )
    raw = []
    return _serve_retained_authorization_checks(
        before,
        coordinator,
        copy,
        origin,
        output,
        package_root,
        paths,
        raw,
        receiver_hash,
        record,
        server,
        sid,
        source,
        source_hash,
        store,
        successor,
        target,
        thread,
        work,
    )


def _serve_retained_authorization_checks(
    before,
    coordinator,
    copy,
    origin,
    output,
    package_root,
    paths,
    raw,
    receiver_hash,
    record,
    server,
    sid,
    source,
    source_hash,
    store,
    successor,
    target,
    thread,
    work,
):
    try:
        legacy = _check_retained_raw_authorization(origin, paths, raw, record, sid, store)
        sys.path.insert(0, str(package_root))
        from ezllmrouter_client import EzLLMRouterClient, EzLLMRouterError
        import ezllmrouter_client

        assert Path(ezllmrouter_client.__file__).resolve().is_relative_to(package_root)
        client_results = []
        for label, token in (
            ("revoked", OLD),
            ("renewed", RENEWED),
            ("authenticated_foreign", FOREIGN),
        ):
            with EzLLMRouterClient(origin, token) as client:
                for query in ({"submission_id": sid}, {"work_selector": work}):
                    try:
                        value = client.get_successor_status(query)
                    except EzLLMRouterError as exc:
                        expected = (
                            ("POLICY_DENIED", 401, "never")
                            if label == "revoked"
                            else ("NOT_FOUND_OR_FORBIDDEN", 404, "never")
                        )
                        if (
                            label == "renewed"
                            or (exc.code, exc.http_status, exc.retry_guidance) != expected
                            or exc.selector != query.get("work_selector", query)
                        ):
                            raise
                        client_results.append(
                            {
                                "credential_state": label,
                                "selector": "submission_id"
                                if "submission_id" in query
                                else "work_key",
                                "http_status": exc.http_status,
                                "code": exc.code,
                                "retry_guidance": exc.retry_guidance,
                            }
                        )
                    else:
                        assert label == "renewed" and value["handle"]["submission_id"] == sid
                        client_results.append(
                            {
                                "credential_state": label,
                                "selector": "submission_id"
                                if "submission_id" in query
                                else "work_key",
                                "submission_id": value["handle"]["submission_id"],
                                "attempt_id": value["attempts"][0]["attempt_id"],
                            }
                        )
        after = census(store)
        assert (
            before == after
            and digest(source) == source_hash
            and digest(target / "receiver.jsonl") == receiver_hash
        )
        evidence = {
            "kind": "dev12_completion02_continue03_retained_auth_http_v1",
            "status": "PASS",
            "target_database_sha256": source_hash,
            "target_receiver_sha256": receiver_hash,
            "private_copy_sha256_before_js": digest(copy),
            "installed_python_source": str(Path(ezllmrouter_client.__file__).resolve()),
            "selected_submission_id": sid,
            "selected_attempt_id": record["attempt_id"],
            "selected_work_key": record["work_key"],
            "raw_http": raw,
            "legacy_auth_http": legacy.status_code,
            "legacy_auth_code": legacy.json()["error"]["code"],
            "python_wheel_calls": client_results,
            "counts_before_after": [before, after],
            "executor_worker_guard_sender_receiver_started": False,
            "new_admissions_or_sends": 0,
        }
        (output / "AUTH-HTTP.json").write_text(
            json.dumps(evidence, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
        )
        (output / "READY.json").write_text(
            json.dumps(
                {
                    "origin": origin,
                    "submission_id": sid,
                    "work_selector": work,
                    "database_sha256": source_hash,
                },
                sort_keys=True,
            )
            + "\n"
        )
        print(
            json.dumps(
                {
                    "status": "READY",
                    "port": PORT,
                    "raw_checks": len(raw),
                    "python_client_checks": len(client_results),
                }
            ),
            flush=True,
        )
        stop = output / "STOP"
        until = time.monotonic() + 600
        while not stop.exists() and time.monotonic() < until:
            time.sleep(0.1)
        if not stop.exists():
            raise TimeoutError("bounded CommonJS check did not signal completion")
        assert (
            census(store) == before
            and digest(source) == source_hash
            and digest(target / "receiver.jsonl") == receiver_hash
        )
        (output / "FINAL.json").write_text(
            json.dumps(
                {
                    "status": "PASS",
                    "counts_unchanged_after_js": True,
                    "target_database_unchanged": True,
                    "target_receiver_unchanged": True,
                    "new_admissions_or_sends": 0,
                },
                sort_keys=True,
                indent=2,
            )
            + "\n"
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        successor.pool.shutdown(wait=True)
        coordinator.pool.shutdown(wait=True)
        store.close()


def _check_retained_raw_authorization(origin, paths, raw, record, sid, store):
    with httpx.Client(base_url=origin, timeout=5, trust_env=False) as client:
        for path in ("/v1/submissions", *paths):
            for label, header in (
                ("missing", None),
                ("malformed", "Broken synthetic"),
                ("invalid", "Bearer invalid.synthetic"),
                ("revoked", "Bearer " + OLD),
            ):
                headers = {"EzLLMRouter-Contract-Version": "0.3"}
                if header is not None:
                    headers["Authorization"] = header
                response = (
                    client.post(
                        path,
                        content=b"{malformed-json",
                        headers={**headers, "Content-Type": "application/json"},
                    )
                    if path == "/v1/submissions"
                    else client.get(path, headers=headers)
                )
                try:
                    value = response.json()
                except ValueError as exc:
                    raise AssertionError(
                        f"non-JSON {label} {path}: HTTP {response.status_code} "
                        f"{response.text[:120]!r}"
                    ) from exc
                assert response.status_code == 401
                assert response.headers["EzLLMRouter-Contract-Version"] == "0.3"
                assert set(value) == {
                    "contract_version",
                    "code",
                    "correlation_id",
                    "retry_guidance",
                }
                assert (value["contract_version"], value["code"], value["retry_guidance"]) == (
                    "0.3",
                    "POLICY_DENIED",
                    "never",
                )
                assert value["correlation_id"].startswith("error.")
                raw.append(
                    {
                        "selector": "pre_body_post"
                        if path == "/v1/submissions"
                        else "submission_id"
                        if path == paths[0]
                        else "work_key",
                        "credential_state": label,
                        "http_status": response.status_code,
                        "contract_header": response.headers["EzLLMRouter-Contract-Version"],
                        "body": value,
                        "exact_body_utf8": response.text,
                        "body_sha256": sha256(response.content).hexdigest(),
                    }
                )
            if path == "/v1/submissions":
                continue
            renewed = client.get(
                path,
                headers={
                    "EzLLMRouter-Contract-Version": "0.3",
                    "Authorization": "Bearer " + RENEWED,
                },
            )
            answer = renewed.json()
            assert renewed.status_code == 200 and answer["handle"]["submission_id"] == sid
            assert answer["handle"]["work_key"] == record["work_key"]
            latest = store.successor_latest_usage(record["attempt_id"])
            assert answer["attempts"][0]["usage_revision"] == latest
            assert answer["attempts"][0]["settlement_state"] == record["settlement_state"]
            raw.append(
                {
                    "selector": "submission_id" if path == paths[0] else "work_key",
                    "credential_state": "renewed",
                    "http_status": renewed.status_code,
                    "contract_header": renewed.headers["EzLLMRouter-Contract-Version"],
                    "handle": answer["handle"],
                    "attempt_id": answer["attempts"][0]["attempt_id"],
                    "settlement_state": answer["attempts"][0]["settlement_state"],
                    "usage_revision": latest,
                }
            )
            denied = client.get(
                path,
                headers={
                    "EzLLMRouter-Contract-Version": "0.3",
                    "Authorization": "Bearer " + FOREIGN,
                },
            )
            denied_body = denied.json()
            assert (
                denied.status_code,
                denied.headers["EzLLMRouter-Contract-Version"],
                denied_body["code"],
                denied_body["retry_guidance"],
            ) == (404, "0.3", "NOT_FOUND_OR_FORBIDDEN", "never")
            raw.append(
                {
                    "selector": "submission_id" if path == paths[0] else "work_key",
                    "credential_state": "authenticated_foreign",
                    "http_status": denied.status_code,
                    "contract_header": denied.headers["EzLLMRouter-Contract-Version"],
                    "body": denied_body,
                }
            )
        legacy = client.get(paths[0], headers={"EzLLMRouter-Contract-Version": "0.2"})
        assert (
            legacy.status_code == 401 and legacy.json()["error"]["code"] == "AUTHENTICATION_FAILED"
        )
    return legacy


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
