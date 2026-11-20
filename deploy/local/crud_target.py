#!/usr/bin/env python3
"""One owner invocation: scoped update, browser CRUD, restart and no-send readback."""

from __future__ import annotations

import json
import sys

from catalogue_import import OperatorClient
from crud_browser import run_browser
import crud_update
from check import wait_health
import local_profile as profile


def require_unchanged_traffic(before, after):
    for key in ("database", "usage", "receiver_arrivals"):
        if before[key] != after[key]:
            raise RuntimeError("CRUD changed model traffic: " + key)


def verify_records(client, model_ref, user_id, synthetic_ref):
    model = client.get("/operator/v1/models/" + model_ref)
    user = client.get("/operator/v1/principals/" + user_id)
    m, p = model["model"], user["principal"]
    if (
        m["status"] != "archived"
        or m["destination"] is not None
        or m["catalogue"]["price_reference"]["snapshot_id"] != "test.reference.v2"
        or m["catalogue"]["price_reference"]["verified_on"] is not None
        or not any(
            item["price"]["snapshot_id"] == "test.reference.v1"
            for item in m["reference_price_history"]
        )
        or p["status"] != "revoked"
        or p["credential_state"] != "unbound"
        or p["display_name"] != "Edited disposable identity"
        or not any(
            g["configuration_ref"] == synthetic_ref and g["status"] == "removed"
            for g in user["grants"]
        )
    ):
        raise RuntimeError("browser CRUD persistence readback failed")
    expected_model = {
        "register_catalogue",
        "publish_reference_price",
        "edit_catalogue_model",
        "archive_model",
    }
    expected_user = {"create_principal", "edit_principal", "set_grant", "principal_state"}
    model_actions = {item["action"] for item in model["history"]}
    user_actions = {item["action"] for item in user["history"]}
    if (
        not expected_model <= model_actions
        or not expected_user <= user_actions
        or sum(item["action"] == "set_grant" for item in user["history"]) != 2
    ):
        raise RuntimeError("disposable CRUD audit history incomplete")
    return {
        "model_ref": model_ref,
        "model_status": m["status"],
        "current_price_snapshot": m["catalogue"]["price_reference"]["snapshot_id"],
        "prior_price_snapshot": "test.reference.v1",
        "user_id": user_id,
        "user_status": p["status"],
        "grant_status": "removed",
        "model_audit_actions": sorted(model_actions),
        "user_audit_actions": sorted(user_actions),
    }


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: crud_target.py crud-YYYYMMDD-NN")
    run_id = sys.argv[1]
    crud_update.main()  # claims a fresh namespace and records its own service update result
    run = crud_update.RUNS / run_id
    try:
        build = profile.current()
        env = profile.environment(build)
        _, password = profile.secrets_on_disk()
        client = OperatorClient(password)
        before = crud_update.snapshot(client, env)
        model_ref = "catalogue.operator." + run_id
        user_id = "user." + run_id
        if any(item["configuration_ref"] == model_ref for item in before["models"]) or any(
            item["principal_id"] == user_id for item in before["principals"]
        ):
            raise RuntimeError("disposable test identity collision")
        synthetic = next(
            (
                m["configuration_ref"]
                for m in before["models"]
                if m.get("kind") != "real_catalogue" and m["status"] == "enabled"
            ),
            None,
        )
        if synthetic is None:
            raise RuntimeError("no enabled synthetic configuration for exact grant test")
        browser = run_browser(run, password, model_ref, user_id, synthetic)
        after_browser = crud_update.snapshot(OperatorClient(password), env)
        require_unchanged_traffic(before, after_browser)
        records = verify_records(OperatorClient(password), model_ref, user_id, synthetic)
        profile.command(
            "crud-persistence-stop", profile.compose_args("down", "--remove-orphans"), env
        )
        profile.command("crud-persistence-up", profile.compose_args("up", "-d", "--no-build"), env)
        profile.check_console_port(env)
        _, live = wait_health(password)
        if live["build"]["fingerprint"] != build["fingerprint"]:
            raise RuntimeError("unexpected source after persistence restart")
        after_restart = crud_update.snapshot(OperatorClient(password), env)
        require_unchanged_traffic(before, after_restart)
        if (
            after_browser["models"] != after_restart["models"]
            or after_browser["principals"] != after_restart["principals"]
        ):
            raise RuntimeError("registry records changed across ordinary restart")
        verify_records(OperatorClient(password), model_ref, user_id, synthetic)
        result = {
            "status": "PASS",
            "source_commit": build["commit"],
            "source_fingerprint": build["fingerprint"],
            "browser": browser,
            "records": records,
            "traffic_before_after": {
                "database": before["database"],
                "usage": before["usage"],
                "receiver_arrivals": before["receiver_arrivals"],
            },
            "ordinary_restart": "PASS",
        }
        (run / "browser-result.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n"
        )
        print(json.dumps(result, sort_keys=True))
    except Exception as exc:
        (run / "browser-failure.json").write_text(
            json.dumps(
                {"status": "FAILED", "type": type(exc).__name__, "reason": str(exc)[:300]}, indent=2
            )
            + "\n"
        )
        raise


if __name__ == "__main__":
    main()
