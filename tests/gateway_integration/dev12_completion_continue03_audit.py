"""Offline self-audit of the complete Continue03 portable primary-evidence packet."""

from __future__ import annotations

from hashlib import sha256
import io
import json
from pathlib import Path
import sys
import tarfile
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dev12_completion_packet_audit import audit as successor_audit
from dev12_completion_source_audit import audit as source_audit


def digest(raw):
    return sha256(raw).hexdigest()


def document(path):
    return json.loads(path.read_text())


def verify_manifest(root):
    lines = (root / "MANIFEST.sha256").read_text().splitlines()
    listed = set()
    for line in lines:
        expected, name = line.split("  ", 1)
        path = root / name
        assert path.is_file() and not path.is_symlink() and digest(path.read_bytes()) == expected
        listed.add(name)
    assert listed == {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() and path.name != "MANIFEST.sha256"
    }
    return len(listed)


def audit(root, source):
    if (root / "MANIFEST.sha256").is_file():
        listed = {}
        for line in (root / "MANIFEST.sha256").read_text().splitlines():
            expected, name = line.split("  ", 1)
            assert name not in listed and not name.startswith("/") and ".." not in Path(name).parts
            path = root / name
            assert (
                path.is_file() and not path.is_symlink() and digest(path.read_bytes()) == expected
            )
            listed[name] = expected
        actual = {
            str(path.relative_to(root))
            for path in root.rglob("*")
            if path.is_file()
            and path != root / "MANIFEST.sha256"
            and "source" not in path.relative_to(root).parts
        }
        assert set(listed) == actual
    export = root / "evidence/final"
    if (root / "IDENTITY.json").is_file():
        identity = document(root / "IDENTITY.json")
        assert digest((root / "source.tar").read_bytes()) == identity["source_tar_sha256"]
        assert (
            digest((root / "focused-281bd6f-to-successor.diff").read_bytes())
            == identity["focused_diff_sha256"]
        )
    lineage = root / "evidence/source-lineage"
    assert verify_manifest(export) == 177
    assert verify_manifest(lineage) == 23
    base = successor_audit(
        export, source / "tests/fixtures/contracts/dev12-successor-01/registrations.json"
    )
    custody = source_audit(lineage, export)
    assert (
        base["status"],
        base["admissions"],
        base["possible_sends"],
        base["receiver_arrivals"],
        base["usage_revision_rows"],
        base["effective_known_usd"],
        base["held_reservations"],
        base["held_reservation_usd"],
        base["retained_failed_stops"],
    ) == ("PASS", 123, 108, 93, 139, "0.028000022", 3, "0.000600000", 13)
    mixed = base["mixed"]
    assert document(root / "evidence/MIXED-RECONCILIATION.json") == mixed
    assert (
        mixed["mixed_admissions"],
        mixed["mixed_possible_send_conservative_upper_count"],
        mixed["legacy_admissions"],
        mixed["legacy_committed_intents"],
        mixed["mixed_financial_upper_bound"],
        mixed["new_release_eligible"],
    ) == (124, 109, 1, 1, None, False)
    assert custody["complete_source_snapshots"] == 22 and custody["releases"] == 17
    assert custody["mounted_files_rehashed"] == 4771

    wheel = root / "packages/corrected/cognitivedynamics_ezllmrouter_client-0.3.0-py3-none-any.whl"
    tarball = root / "packages/corrected/cognitivedynamics-ezllmrouter-client-0.3.0.tgz"
    assert (
        digest(wheel.read_bytes())
        == "955b15582de0739377a1f1206a686283ba3b8d4b39212ef36d3f02baf63210c0"
    )
    assert (
        digest(tarball.read_bytes())
        == "cfe563b1c50a597e6d65876432436b9cf9cb6d9bfeb22dee80520b90a69ac52d"
    )
    with ZipFile(wheel) as z:
        assert (
            z.read("ezllmrouter_client/_successor_validation.py")
            == (
                source / "clients/python/src/ezllmrouter_client/_successor_validation.py"
            ).read_bytes()
        )
    with tarfile.open(fileobj=io.BytesIO(tarball.read_bytes()), mode="r:gz") as tar:
        assert (
            tar.extractfile("package/successor.cjs").read()
            == (source / "clients/js/successor.cjs").read_bytes()
        )
    assert (
        digest(
            (
                export / "packages/cognitivedynamics_ezllmrouter_client-0.3.0-py3-none-any.whl"
            ).read_bytes()
        )
        == "d4cdea6ffabd7aa62985040e4a92a4870d73dc8e4240f43d4472d86ce595bb98"
    )
    assert (
        digest((export / "packages/cognitivedynamics-ezllmrouter-client-0.3.0.tgz").read_bytes())
        == "b871b64c98e299e031e4a6e11766a06e7a494f6e4b8b787fd70bfb8144694a3f"
    )

    auth = document(root / "evidence/auth/AUTH-HTTP.json")
    js = document(root / "evidence/auth/COMMONJS-HTTP.json")
    auth_final = document(root / "evidence/auth/FINAL.json")
    assert auth["status"] == js["status"] == auth_final["status"] == "PASS"
    assert auth["target_database_sha256"] == mixed["source_database_sha256"]
    assert auth_final["counts_unchanged_after_js"] and auth_final["target_database_unchanged"]
    assert auth["counts_before_after"][0] == auth["counts_before_after"][1]
    failures = [
        row
        for row in auth["raw_http"]
        if row["credential_state"] in {"missing", "malformed", "invalid", "revoked"}
    ]
    assert len(failures) == 12 and len(auth["raw_http"]) == 16
    for row in failures:
        assert row["http_status"] == 401 and row["contract_header"] == "0.3"
        assert set(row["body"]) == {"contract_version", "code", "correlation_id", "retry_guidance"}
        assert (row["body"]["code"], row["body"]["retry_guidance"]) == ("POLICY_DENIED", "never")
        assert digest(row["exact_body_utf8"].encode()) == row["body_sha256"]
    assert len([row for row in auth["raw_http"] if row["credential_state"] == "renewed"]) == 2
    assert (
        len(
            [
                row
                for row in auth["raw_http"]
                if row["credential_state"] == "authenticated_foreign" and row["http_status"] == 404
            ]
        )
        == 2
    )
    for calls in (auth["python_wheel_calls"], js["calls"]):
        assert len(calls) == 6
        assert sorted(row["credential_state"] for row in calls) == sorted(
            ["revoked", "renewed", "authenticated_foreign"] * 2
        )
    assert all(js["protocol_controls"].values())

    zero = document(root / "evidence/zero-send/OBSERVATION.json")
    rollback = zero["rollback"]
    denial = zero["gate_wait_denial"]
    positive = zero["gate_wait_positive"]
    assert zero["source_database_sha256"] == mixed["source_database_sha256"]
    assert zero["new_admissions_or_possible_sends"] == 0
    assert rollback["status"] == denial["status"] == positive["status"] == "PASS"
    assert rollback["definite_rollback_from_store"] is True
    assert rollback["all_table_hashes_before"] == rollback["all_table_hashes_after"]
    trace = rollback["sql_operations"]
    assert all(operation in trace for operation in ("BEGIN", "UPDATE", "INSERT", "ROLLBACK"))
    assert "COMMIT" not in trace
    assert denial["gate_attempt_observed_before_revoke"]
    assert denial["denial"]["error_type"] == "PermissionError"
    assert denial["non_authority_table_hashes_unchanged"]
    assert positive["result"] == {"value": "accepted"}
    assert positive["usage_rows_before_after"][1] == positive["usage_rows_before_after"][0] + 1
    assert positive["campaign_and_ownership_unchanged"]

    browser = document(root / "evidence/overbound/BROWSER-OBSERVATION.json")
    report_final = document(root / "evidence/overbound/FINAL.json")
    screenshot = (root / "evidence/overbound" / browser["screenshot"]).read_bytes()
    historical = document(export / "historical-underbound-ledger.json")
    assert browser["status"] == report_final["status"] == "PASS"
    assert browser["fixture_source_sha256"] == historical["source_sha256"]
    assert digest(screenshot) == browser["screenshot_sha256"]
    context = root / "evidence/overbound/historical-overbound-context.png"
    assert context.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert context.name == browser["context_screenshot"]
    assert digest(context.read_bytes()) == browser["context_screenshot_sha256"]
    assert browser["detail"]["fields"]["Settlement"] == "over_bound · fictional USD 0.000200000"
    assert browser["detail"]["fields"]["Reservation"] == "fictional USD 0.000100000"
    assert browser["local_request_methods"]["POST"] == 1
    assert browser["local_request_methods"]["GET"] > 0
    assert browser["model_submission_requests"] == 0
    assert all(
        row["method"] == "GET" or row == {"method": "POST", "path": "/operator/v1/login"}
        for row in browser["local_request_paths"]
    )
    assert report_final["copy_admissions_ownership_unchanged"]

    contention = document(root / "evidence/contention/PREFLIGHT.json")
    assert contention["status"] == "BLOCKED_BY_CURRENT_AUTHORITY"
    assert contention["blockers"] == [
        "authority_pause:authority",
        "legacy_financial_upper_bound_unestablished",
    ]
    assert contention["mixed_admissions"] == 124
    assert contention["mixed_possible_send_upper_count"] == 109
    assert contention["prospective_allocation"]["new_admissions"] == 1
    assert contention["prospective_allocation"]["new_possible_sends"] == 1
    assert contention["harness_source_sha256"] == digest(
        (source / "tests/gateway_integration/dev12_completion_sync_first_owner.py").read_bytes()
    )
    assert contention["service_source_sha256"] == digest(
        (source / "tools/synthetic/successor_service.py").read_bytes()
    )
    disposition = document(source / "docs/development/dev-12/A2-A4-CONTINUE-03-DISPOSITION.json")
    assert len(disposition["cells"]) == 7
    assert len([row for row in disposition["cells"] if row["status"] == "CLOSED"]) == 6
    assert [row["id"] for row in disposition["cells"] if row["status"] == "BLOCKED"] == ["CT02-02b"]
    return {
        "status": "PASS",
        "source_snapshots": custody["complete_source_snapshots"],
        "releases": custody["releases"],
        "original_pass_pairs": base["original_pass_pairs"],
        "qualified_supplement_pairs": base["qualified_supplement_pairs"],
        "retained_failed_stops": base["retained_failed_stops"],
        "successor_admissions": base["admissions"],
        "mixed_admissions": mixed["mixed_admissions"],
        "mixed_possible_send_conservative_upper_count": mixed[
            "mixed_possible_send_conservative_upper_count"
        ],
        "receiver_arrivals": base["receiver_arrivals"],
        "latest_known_fictional_usd": base["effective_known_usd"],
        "held_reservations": base["held_reservations"],
        "auth_401_raw_checks": len(failures),
        "installed_http_reads": len(auth["python_wheel_calls"]) + len(js["calls"]),
        "browser_local_gets": browser["local_request_methods"]["GET"],
        "browser_local_login_posts": browser["local_request_methods"]["POST"],
        "closed_cells": 6,
        "blocked_cell": "CT02-02b",
        "real_provider_calls": 0,
        "real_spend": 0,
    }


if __name__ == "__main__":
    print(json.dumps(audit(Path(sys.argv[1]), Path(sys.argv[2])), sort_keys=True, indent=2))
