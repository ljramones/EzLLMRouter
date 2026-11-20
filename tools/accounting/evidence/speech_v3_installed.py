"""Installed v3 service/Python/JavaScript synthetic loopback qualification.

Run only with the clean consumer interpreter and a new ignored one-use run ID.
No model worker or external provider is started.
"""

import csv
import io
from http import client as http_client
import json
import os
from decimal import Decimal
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

from ezllmrouter_client.integration import IntegrationClient
from ezllmrouter_server.registry import Registry
from ezllmrouter_server.store import SQLiteStore
from ezllmrouter_server.web import serve

ROOT = Path(__file__).resolve().parents[3]
RUN = ROOT / "deploy/local/.state/integration-v3-runs" / sys.argv[1]
if RUN.exists():
    raise SystemExit("one-use run directory already exists")
RUN.mkdir(parents=True)
STORE = SQLiteStore(RUN / "service.sqlite")


class Authority:
    def __init__(self):
        self.gate = threading.RLock()
        self.epoch = 0


def at(seconds):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


registry = Registry(
    STORE,
    Authority(),
    legacy_destination={
        "configuration_ref": "cfg.synthetic.v3",
        "service": "litellm.dev04",
        "endpoint": "127.0.0.1",
        "model": "model.synthetic",
        "model_version": "v1",
        "processing_region": "local",
    },
    legacy_token="synthetic-legacy-service-token-000000000000",
    legacy_trusted={"principal_id": "svc.synthetic", "charging_owner_id": "team.synthetic"},
)
registry.mutate(
    "owner.local",
    {
        "operation_id": "op.v3.principal",
        "action": "create_principal",
        "subject": "svc.v3",
        "expected_revision": 0,
        "data": {
            "display_name": "Synthetic v3 ingest",
            "kind": "service",
            "owner": "owner.local",
            "role": "ordinary",
        },
    },
)
_, ingest_token = registry.provision_credential("owner.local", "svc.v3", 1, "op.v3.credential")
registry.mutate(
    "owner.local",
    {
        "operation_id": "op.v3.activate",
        "action": "principal_state",
        "subject": "svc.v3",
        "expected_revision": 2,
        "data": {"status": "active", "reason": "isolated installed test"},
    },
)
admin_token = registry.issue_local_operator_token("owner.local")
with socket.socket() as probe:
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
http = serve("127.0.0.1", port, SimpleNamespace(registry=registry))
thread = threading.Thread(target=http.serve_forever)
thread.start()

dataset_id = "dataset.synthetic.speech.installed"
account_id = "account.synthetic.speech.installed"
base = f"http://127.0.0.1:{port}/"
try:
    with (
        IntegrationClient(base, admin_token, version="3") as admin,
        IntegrationClient(base, ingest_token, version="3") as ingest,
    ):
        dataset = {
            "dataset_id": dataset_id,
            "platform_id": "platform.synthetic",
            "environment_id": "environment.synthetic",
            "owner_id": "owner.local",
            "ingest_principal_id": "svc.v3",
            "activated_at": "2026-10-29T00:00:00Z",
        }
        admin.create_dataset(dataset)
        admin.register_account(
            {
                "account_id": account_id,
                "dataset_id": dataset_id,
                "provider_id": "provider.synthetic.xai",
                "credential_ref": "credential.synthetic.xai",
                "allowed_models": [],
                "allowed_operations": ["speech_input", "speech_output"],
                "state": "usable",
            }
        )
        denied = ingest.operation_eligibility(
            dataset_id,
            account_id,
            {
                "operation_family": "speech_input",
                "capability": "transcription",
                "selection_kind": "known_model",
                "model_id": "model.unpermitted",
            },
        )
        assert denied["reason"] == "model_not_permitted"
        selector = {
            "operation_family": "speech_input",
            "capability": "transcription",
            "selection_kind": "provider_selected",
        }
        allowed = ingest.operation_eligibility(dataset_id, account_id, selector)
        assert allowed["usable"] and "model_id" not in allowed
        attempt = "attempt.synthetic.speech.python"
        start_at, done_at = at(2), at(3)
        evidence = {"status": "verified", "eligibility_id": allowed["eligibility_id"]}
        action = {
            "selected_account_id": account_id,
            **selector,
            "policy_version": "policy.synthetic.v3",
            "eligibility_evidence": evidence,
        }
        common = {
            "integration_version": "3",
            "dataset_id": dataset_id,
            "attempt_id": attempt,
            "schema_version": "1",
            "producer_version": "test.installed.v3",
            "provenance": "synthetic",
            "source_at": at(0),
            "available_at": at(0),
            "classification": "low",
            "retention_until": at(86400),
        }
        ingest.submit_snapshot(
            {
                **common,
                "snapshot_id": "feature.synthetic.python",
                "snapshot_kind": "feature",
                "status": "not_collected",
            }
        )
        ingest.submit_snapshot(
            {
                **common,
                "snapshot_id": "decision.synthetic.python",
                "snapshot_kind": "decision",
                "status": "captured",
                "selected_action": action,
            }
        )
        decision = {
            "integration_version": "3",
            "event_id": "event.synthetic.python.decision",
            "dataset_id": dataset_id,
            "kind": "decision",
            "occurred_at": start_at,
            "attempt_id": attempt,
            "decision_ref": "decision.synthetic.python",
            **action,
        }
        ingest.submit_observation(decision)
        start = {
            "integration_version": "3",
            "event_id": "event.synthetic.python.start",
            "dataset_id": dataset_id,
            "kind": "attempt_started",
            "occurred_at": start_at,
            "started_at": start_at,
            "attempt_id": attempt,
            "task_id": "task.synthetic.python",
            "step_id": "step.synthetic.python",
            "run_id": "run.synthetic.python",
            "root_run_id": "run.synthetic.python",
            "actor_kind": "service",
            "actor_id": "service.synthetic.python",
            "provider_account_id": account_id,
            "context_ref": "feature.synthetic.python",
            "operation_family_version": "1",
            "operation_family": "speech_input",
            "model_identity_state": "unknown",
            "logical_operation_id": "operation.synthetic.python",
            "attempt_role": "initial",
        }
        ingest.submit_observation(start)
        ingest.submit_observation(
            {
                "integration_version": "3",
                "event_id": "event.synthetic.python.result",
                "dataset_id": dataset_id,
                "kind": "result",
                "occurred_at": done_at,
                "attempt_id": attempt,
                "result_state": "completed",
            }
        )
        usage = {
            "integration_version": "3",
            "event_id": "event.synthetic.python.usage",
            "dataset_id": dataset_id,
            "kind": "usage",
            "occurred_at": done_at,
            "attempt_id": attempt,
            "usage_revision": 1,
            "usage_state": "known",
            "cost_state": "unknown",
            "native_units": [{"unit": "bytes", "quantity_decimal": "17"}],
            "usage_provenance": "provider_reported",
        }
        ingest.submit_observation(usage)
        assert ingest.submit_observation(usage)["event_id"] == usage["event_id"]

        js_dir = Path(
            os.environ.get(
                "SPEECH_V3_CLIENT_DIR",
                str(
                    ROOT
                    / "deploy/local/.state/integration-v3-js-consumer/node_modules/@cognitivedynamics/ezllmrouter-client"
                ),
            )
        )
        script = ROOT / "tools/accounting/evidence/speech_v3_js_actor.cjs"
        env = {
            **os.environ,
            "SPEECH_V3_JS_CLIENT": str(js_dir),
            "SPEECH_V3_BASE": base,
            "SPEECH_V3_TOKEN": ingest_token,
            "SPEECH_V3_DATASET": dataset_id,
            "SPEECH_V3_ACCOUNT": account_id,
        }
        js = subprocess.run(
            ("/Users/larrymitchell/.nvm/versions/node/v24.22.1/bin/node", str(script)),
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        assert json.loads(js.stdout)["attempts"] == 1
        platform = Path(sys.argv[2]) if len(sys.argv) > 2 else None
        if platform:
            token_file = RUN / "ingest.token"
            token_file.write_text(ingest_token)
            token_file.chmod(0o600)
            platform_env = {
                **env,
                "M33_EZLLMROUTER_ENABLED": "1",
                "M33_EZLLMROUTER_SYNTHETIC_ONLY": "1",
                "M33_EZLLMROUTER_API_URL": base,
                "M33_EZLLMROUTER_DATASET_ID": dataset_id,
                "M33_EZLLMROUTER_ACCOUNT_ID": account_id,
                "M33_EZLLMROUTER_ACCOUNT_XAI": account_id,
                "M33_EZLLMROUTER_PROVIDER_XAI": "provider.synthetic.xai",
                "M33_EZLLMROUTER_CREDENTIAL_REF_XAI": "credential.synthetic.xai",
                "M33_EZLLMROUTER_CLIENT_MODULE": str(js_dir),
                "M33_EZLLMROUTER_INGEST_TOKEN_FILE": str(token_file),
                "M33_EZLLMROUTER_OUTBOX_FILE": str(RUN / "platform-outbox.sqlite"),
            }
            platform_script = platform / "tests/ezllmrouter-integration/speech-installed.cjs"
            platform_run = subprocess.run(
                ("/Users/larrymitchell/.nvm/versions/node/v24.22.1/bin/node", str(platform_script)),
                env=platform_env,
                capture_output=True,
                text=True,
                check=True,
            )
            assert json.loads(platform_run.stdout)["delivered"] == 30
            for provider, model in (
                ("anthropic", "model.synthetic.newton.anthropic"),
                ("xai", "model.synthetic.newton.xai"),
            ):
                admin.register_account(
                    {
                        "account_id": "account.synthetic.newton." + provider,
                        "dataset_id": dataset_id,
                        "provider_id": "provider.synthetic." + provider,
                        "credential_ref": "credential.synthetic." + provider,
                        "allowed_models": [model],
                        "allowed_operations": [],
                        "state": "usable",
                    }
                )
            newton_env = {
                **platform_env,
                "M33_EZLLMROUTER_ACCOUNT_ANTHROPIC": "account.synthetic.newton.anthropic",
                "M33_EZLLMROUTER_ACCOUNT_XAI": "account.synthetic.newton.xai",
                "M33_EZLLMROUTER_OUTBOX_FILE": str(RUN / "newton-outbox.sqlite"),
            }
            newton_script = platform / "tests/ezllmrouter-integration/newton-installed.cjs"
            newton = subprocess.run(
                ("/Users/larrymitchell/.nvm/versions/node/v24.22.1/bin/node", str(newton_script)),
                env=newton_env,
                capture_output=True,
                text=True,
                check=True,
            )
            assert json.loads(newton.stdout)["delivered"] == 12
            for provider, model in (("deepgram", "nova-2"), ("elevenlabs", "eleven_v3")):
                admin.register_account(
                    {
                        "account_id": "account.synthetic.proto." + provider,
                        "dataset_id": dataset_id,
                        "provider_id": "provider.synthetic." + provider,
                        "credential_ref": "credential.synthetic." + provider,
                        "allowed_models": [model],
                        "allowed_operations": [],
                        "state": "usable",
                    }
                )
            proto_env = {
                **platform_env,
                "M33_EZLLMROUTER_ACCOUNT_DEEPGRAM": "account.synthetic.proto.deepgram",
                "M33_EZLLMROUTER_PROVIDER_DEEPGRAM": "provider.synthetic.deepgram",
                "M33_EZLLMROUTER_CREDENTIAL_REF_DEEPGRAM": "credential.synthetic.deepgram",
                "M33_EZLLMROUTER_ACCOUNT_ELEVENLABS": "account.synthetic.proto.elevenlabs",
                "M33_EZLLMROUTER_PROVIDER_ELEVENLABS": "provider.synthetic.elevenlabs",
                "M33_EZLLMROUTER_CREDENTIAL_REF_ELEVENLABS": "credential.synthetic.elevenlabs",
                "M33_EZLLMROUTER_OUTBOX_FILE": str(RUN / "proto-outbox.sqlite"),
            }
            proto_script = platform / "tests/ezllmrouter-integration/proto-speech-installed.cjs"
            proto = subprocess.run(
                ("/Users/larrymitchell/.nvm/versions/node/v24.22.1/bin/node", str(proto_script)),
                env=proto_env,
                capture_output=True,
                text=True,
                check=True,
            )
            assert json.loads(proto.stdout)["delivered"] == 12
        # Let both synthetic future-dated start instants pass before the
        # administrative mutation; late accounting then cannot be mistaken
        # for a newly authorized dispatch.
        time.sleep(3)
        admin.set_account_state(
            account_id, {"dataset_id": dataset_id, "expected_revision": 1, "state": "disabled"}
        )
        denied_after_disable = ingest.operation_eligibility(dataset_id, account_id, selector)
        assert denied_after_disable["reason"] == "account_disabled"
        late_usage = {
            **usage,
            "event_id": "event.synthetic.python.usage2",
            "occurred_at": at(0),
            "usage_revision": 2,
            "native_units": [{"unit": "bytes", "quantity_decimal": "19"}],
        }
        ingest.submit_observation(late_usage)
        report = admin.report(dataset_id)
        exported = admin.export_dataset(dataset_id)
        connection = http_client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request(
            "GET",
            "/integration/v3/reports/usage?dataset_id=" + dataset_id + "&export=csv",
            headers={
                "Authorization": "Bearer " + admin_token,
                "EzLLMRouter-Integration-Version": "3",
            },
        )
        csv_response = connection.getresponse()
        csv_text = csv_response.read().decode("utf-8")
        connection.close()
        assert csv_response.status == 200
        csv_rows = list(csv.DictReader(io.StringIO(csv_text)))
        expected_count = 11 if platform else 2
        assert (
            report["attempt_count"] == expected_count
            and report["unknown_cost_attempts"] == expected_count
        )
        assert (
            len(exported["attempts"]) == expected_count
            and len(exported["events"]) == expected_count * 4 + 1
        )
        assert report["known_total_by_currency"] == {}
        assert len(csv_rows) == expected_count
        assert {row["attempt_id"] for row in csv_rows} == {
            row["attempt_id"] for row in report["attempts"]
        }
        independent_known = sum(
            (Decimal(row["amount_decimal"]) for row in csv_rows if row["cost_status"] == "known"),
            Decimal(0),
        )
        assert independent_known == Decimal(0)
        assert sum(row["cost_status"] != "known" for row in csv_rows) == expected_count
        assert {"attempt.synthetic.speech.python", "attempt.synthetic.speech.javascript"} <= {
            r["attempt_id"] for r in report["attempts"]
        }
        python_row = next(r for r in report["attempts"] if r["attempt_id"] == attempt)
        assert python_row["usage_revision"] == 2
        assert python_row["native_units"] == late_usage["native_units"]
        if platform:
            actors = [r["actor_id"] for r in report["attempts"]]
            assert actors.count("service.vega.voice") == 2
            assert actors.count("agent.relay") == 1
            assert actors.count("service.my-assistant.voice") == 2
            assert actors.count("agent.newton-light") == 2
            assert {
                r["initiating_user_id"]
                for r in report["attempts"]
                if r["actor_id"] == "service.vega.voice"
            } == {"user.synthetic.vega"}
            assert {
                r["initiating_user_id"]
                for r in report["attempts"]
                if r["actor_id"] == "service.my-assistant.voice"
            } == {"user.synthetic.assistant"}
            assert {
                r["initiating_user_id"]
                for r in report["attempts"]
                if r["actor_id"] == "agent.relay"
            } == {None}
            newton_rows = [r for r in report["attempts"] if r["actor_id"] == "agent.newton-light"]
            assert {r["provider_account_id"] for r in newton_rows} == {
                "account.synthetic.newton.anthropic",
                "account.synthetic.newton.xai",
            }
            assert {
                tuple((unit["unit"], unit["quantity_decimal"]) for unit in r["native_units"])
                for r in newton_rows
            } == {
                (("input_tokens", "11"), ("output_tokens", "4")),
                (("input_tokens", "9"), ("output_tokens", "3")),
            }
            proto_rows = [r for r in report["attempts"] if r["actor_id"] == "service.proto.voice"]
            assert {(r["provider_account_id"], r["model_id"]) for r in proto_rows} == {
                ("account.synthetic.proto.deepgram", "nova-2"),
                ("account.synthetic.proto.elevenlabs", "eleven_v3"),
            }
            assert {r["initiating_user_id"] for r in proto_rows} == {"user.synthetic.proto"}
        (RUN / "report.json").write_text(json.dumps(report, sort_keys=True, indent=2))
        (RUN / "export.json").write_text(json.dumps(exported, sort_keys=True, indent=2))
        (RUN / "report.csv").write_text(csv_text)
        (RUN / "summary.json").write_text(
            json.dumps(
                {
                    "attempts": expected_count,
                    "unknown_cost": expected_count,
                    "known_total_by_currency": {},
                    "controlled_provider_callbacks": 9 if platform else 0,
                    "real_provider_requests": 0,
                    "python_initial_native_bytes": "17",
                    "python_effective_native_bytes": "19",
                    "js_native_characters": "8",
                },
                sort_keys=True,
                indent=2,
            )
        )
        print(
            json.dumps(
                {
                    "run": sys.argv[1],
                    "attempts": expected_count,
                    "unknown_cost": expected_count,
                    "controlled_provider_callbacks": 9 if platform else 0,
                    "real_provider_requests": 0,
                },
                sort_keys=True,
            )
        )
finally:
    http.shutdown()
    http.server_close()
    thread.join(timeout=3)
    STORE.close()
