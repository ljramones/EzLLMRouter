"""Stable integration CSV columns and structured-cell projection."""

import json
from collections.abc import Iterable, Mapping
from ..csv_export import csv_bytes


def usage_csv(version: str, attempts: Iterable[Mapping[str, object]]) -> bytes:
    columns: tuple[str, ...] = (
        "dataset_id",
        "platform_id",
        "environment_id",
        "owner_id",
        "attempt_id",
        "started_at",
        "task_id",
        "step_id",
        "run_id",
        "root_run_id",
        "parent_run_id",
        "actor_kind",
        "actor_id",
        "initiating_user_id",
        "provider_account_id",
        "model_id",
        "context_ref",
        "result_state",
        "result_observed_at",
        "task_outcome",
        "task_outcome_observed_at",
        "usage_revision",
        "usage_observed_at",
        "cost_status",
        "currency",
        "amount_decimal",
        "native_units",
        "cost_basis",
        "price_ref",
        "price_version",
    )
    if version in ("2", "3"):
        columns += (
            "operation_family_version",
            "operation_family",
            "model_identity_state",
            "logical_operation_id",
            "attempt_role",
            "predecessor_attempt_id",
            "lineage_status",
            "account_resolution_status",
            "resolved_account_id",
            "decision_ref",
            "eligibility_evidence_status",
            "eligibility_assessment",
            "eligibility_record",
            "selected_action",
            "feature_snapshot_status",
            "feature_snapshot_digest",
            "feature_available_before_start",
            "decision_snapshot_status",
            "decision_snapshot_digest",
            "usage_provenance",
            "usage_state",
        )
    return csv_bytes(
        columns,
        (
            dict(
                {
                    **row,
                    **{
                        key: json.dumps(row[key], sort_keys=True)
                        if row.get(key) is not None
                        else ""
                        for key in ("native_units", "eligibility_record", "selected_action")
                    },
                }
            )
            for row in attempts
        ),
    )
