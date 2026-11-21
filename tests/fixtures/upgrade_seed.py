"""Additional public historical rows; no usable credentials or private database data."""

from copy import deepcopy


def supplement(rows, version, at, principal):
    record = deepcopy(rows["submissions"][0][-1])
    record.update(
        submission_id="submission.successor",
        attempt_id="attempt.successor",
        candidate_access="present",
        result_available_at=at,
    )
    record["work_key"]["step_id"] = "step.successor"
    dataset, account = rows["integration_accounts"][0][:2][::-1]
    rows.update(
        {
            "dev12_submissions": [
                [
                    record["submission_id"],
                    principal,
                    record["work_key"],
                    "sha256:" + "c" * 64,
                    record,
                ]
            ],
            "dev12_usage_revisions": [
                [
                    "attempt.successor",
                    1,
                    record["submission_id"],
                    {"revision": 1, "cost": {"status": "unknown"}},
                ]
            ],
            "dev12_evidence_events": [
                [
                    1,
                    record["submission_id"],
                    "result_observed",
                    at,
                    {"attempt_id": "attempt.successor"},
                ]
            ],
            "dev12_send_ownership": [
                ["attempt.successor", record["submission_id"], at, {"plan_id": "plan.successor"}]
            ],
            "registry_credentials": [
                ["public-disabled-verifier", principal, "credential.synthetic"]
            ],
            "registry_operations": [
                ["op.synthetic", principal, "sha256:" + "d" * 64, {"status": "recorded"}]
            ],
            "registry_connections": [
                [
                    "connection.synthetic",
                    {"connection_id": "connection.synthetic", "status": "disabled", "revision": 1},
                ]
            ],
            "registry_deployments": [
                [
                    "deployment.synthetic",
                    {
                        "connection_id": "connection.synthetic",
                        "configuration_ref": "cfg.synthetic",
                        "revision": 1,
                    },
                ]
            ],
            "registry_source_permissions": [
                [
                    "permission.synthetic",
                    {"connection_id": "connection.synthetic", "status": "revoked", "revision": 2},
                ]
            ],
            "registry_agents": [
                [
                    "agent.synthetic",
                    {"agent_id": "agent.synthetic", "owner_id": principal, "revision": 1},
                ]
            ],
            "registry_agent_permissions": [
                [
                    "agent.permission",
                    principal,
                    "agent.synthetic",
                    principal,
                    {"status": "revoked", "revision": 2},
                ]
            ],
            "registry_outcome_authorities": [
                ["outcome.authority", {"principal_id": principal, "revision": 1}]
            ],
            "attribution_runs": [
                [
                    "run.synthetic",
                    {
                        "run_id": "run.synthetic",
                        "principal_id": principal,
                        "task_id": "task.synthetic",
                    },
                ]
            ],
            "attribution_outcomes": [
                [
                    principal,
                    "outcome.synthetic",
                    "run.synthetic",
                    1,
                    "sha256:" + "e" * 64,
                    {"outcome": "accepted"},
                    at,
                    {"accepted": True},
                ]
            ],
            "integration_eligibility_reads": [
                [dataset, "eligibility.synthetic", {"state": "recorded", "account_id": account}]
            ],
            "integration_expired_datasets": [["dataset.expired", at]],
            "integration_dataset_retention": [[dataset, 30, at]],
            "integration_credential_bindings": [
                [
                    account,
                    dataset,
                    {
                        "account_id": account,
                        "dataset_id": dataset,
                        "revision": 1,
                        "state": "retired",
                    },
                ]
            ],
            "integration_credential_versions": [
                [
                    account,
                    1,
                    "key.public.synthetic",
                    b"public-nonce",
                    b"public-ciphertext-not-a-secret",
                ]
            ],
            "integration_credential_operations": [
                ["credential.operation", "public-request-digest", account]
            ],
            "integration_credential_meta": [["fixture.release", str(version)]],
            "local_connectors": [
                ["connector.synthetic", {"status": "disabled", "revision": 1}, None]
            ],
            "operator_launches": [
                ["launch.synthetic", "text", "completed", at, at, ["submission.0"], 1, None]
            ],
            "operator_provider_validations": [
                [
                    "validation.synthetic",
                    "connection.synthetic",
                    1,
                    "cfg.synthetic",
                    4,
                    16,
                    "completed",
                    at,
                    at,
                    "submission.0",
                    None,
                ]
            ],
            "console_users": [
                [
                    principal,
                    "public-synthetic-disabled-user",
                    "disabled-public-fixture",
                    1,
                    1,
                    at,
                    at,
                ]
            ],
            "personal_campaign_audit": [[1, "campaign.synthetic", "closed", principal, at]],
            "dev12_authority": [["authority.synthetic", {"revision": 1, "state": "revoked"}]],
            "dev12_authority_audit": [
                [1, "authority.synthetic", {"revision": 1, "state": "revoked"}]
            ],
            "dev12_campaigns": [["campaign.successor", {"state": "closed", "revision": 1}]],
            "dev12_campaign_attempts": [
                ["attempt.successor", "campaign.successor", "settled", 1, "0.500000000"]
            ],
            "dev12_campaign_audit": [[1, "campaign.successor", {"action": "closed", "at": at}]],
        }
    )
    snapshot_and_event_rows(rows, version, at)
    indexed_submission_rows(rows, principal)


def snapshot_and_event_rows(rows, version, at):
    live = deepcopy(rows["integration_snapshots"][0])
    live[1] = "snapshot.live"
    live[5] = dict(live[5], snapshot_id=live[1], retention_until="2030-01-01T00:00:00Z")
    live[6] = {"notice": "public synthetic retained content"}
    rows["integration_snapshots"].append(live)
    dataset_record = dict(rows["integration_datasets"][0][1], dataset_id="dataset.indexed")
    rows["integration_datasets"].append(["dataset.indexed", dataset_record])
    start = deepcopy(rows["integration_attempts"][0][3])
    start.update(
        dataset_id="dataset.indexed",
        attempt_id="attempt.indexed",
        predecessor_attempt_id="attempt.indexed.prior",
        context_ref="context.indexed",
    )
    rows["integration_attempts"].append(
        ["dataset.indexed", "attempt.indexed", "event.indexed.start", start, 1]
    )
    for kind, key in (("lineage", "predecessor_attempt_id"), ("decision", "decision_ref")):
        event = {"kind": kind, "attempt_id": "attempt.indexed", key: "reference.synthetic"}
        rows["integration_events"].append(
            [
                "dataset.indexed",
                "event." + kind,
                kind,
                "attempt.indexed",
                None,
                "sha256:" + "f" * 64,
                event,
                {"accepted": True},
            ]
        )
    for number in range(30, 30 + version - 1):
        observation = {
            "operation_id": f"probe.{number:02}",
            "connection_id": "connection.synthetic",
            "operation": "readiness",
            "state": "failed",
            "observed_at": at,
        }
        rows["registry_observations"].append(
            [observation["operation_id"], observation["connection_id"], observation]
        )


def indexed_submission_rows(rows, principal):
    # All indexed JSON fields have real, non-null values in at least one row.
    indexed_principal = principal + ".indexed"
    indexed = deepcopy(rows["submissions"][0][-1])
    indexed.update(
        submission_id="submission.indexed",
        attempt_id="attempt.indexed",
        principal_id=indexed_principal,
        attribution={"run_id": "run.indexed"},
    )
    indexed["work_key"].update(principal_id=indexed_principal, step_id="step.indexed")
    rows["submissions"].append(
        [
            indexed["submission_id"],
            indexed_principal,
            indexed["task_id"],
            indexed["work_key"],
            indexed["work_digest"],
            indexed,
        ]
    )
    rows["work_key_owners"].append(
        [indexed_principal, indexed["work_key"], "0.2", indexed["submission_id"]]
    )
    rows["registry_principals"].append(
        [
            indexed_principal,
            {"id": indexed_principal, "revision": 1, "role": "ordinary", "status": "active"},
        ]
    )
    rows["attribution_runs"].append(
        [
            "run.indexed",
            {
                "run_id": "run.indexed",
                "principal_id": indexed_principal,
                "task_id": indexed["task_id"],
            },
        ]
    )
