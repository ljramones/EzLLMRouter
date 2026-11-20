"""Fixed, selected DEV-12 Completion 02 scenario contract.

Assurance labels are claims made *by* a case, not permission to invent a case.
Each selected label has an explicit scenario and required variants.  A case
runner may share setup between variants, but must produce separate observations
and objective assertions for every listed pair.  The recovery chain is an
additional required composed scenario; it does not add an assurance label.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping


@dataclass(frozen=True)
class VariantSpec:
    handler: str
    required_stages: tuple[str, ...]
    assertion_ids: tuple[str, ...]
    phase: str = "normal"
    reuse_permitted: bool = False
    minimum_admissions: int = 0
    minimum_possible_sends: int = 0


@dataclass(frozen=True)
class ScenarioSpec:
    assurance_ids: tuple[str, ...]
    variants: Mapping[str, VariantSpec]


@dataclass(frozen=True)
class CaseHandler:
    """Reviewed source registration for a real target handler.

    The source hash is checked against the bytes on disk and the preflight plan.
    The executable must return stage observations and assertions, rather than a
    single success Boolean.  Its objective checks are verified by the runner.
    """

    name: str
    source_path: str
    source_sha256: str
    supported: frozenset[tuple[str, str]]
    run: Callable


# These are separate objective assertions, including positive controls where
# a rejection alone would be misleading.  Related assertions can share one
# composed target case, but each must execute and retain its own evidence.
_VARIANTS = {
    "T-01": "missing_identity invalid_identity valid_identity",
    "T-02": "forbidden_destination fixed_destination",
    "T-03": "missing_taint migration_missing_taint valid_taint",
    "T-07.a": "eligible_current rotated_old_eligible revoked_key_after_wait revoked_plan_after_wait",
    "T-14.a": "assessment_transition omitted_reason_transition delegation_coverage_transition changed_caller_assertion read_denied",
    "T-24.a": "queued_revocation eligible_control",
    "T-24.b": "revocation_before_write write_before_revocation would_block partial_write",
    "T-24.c": "restart_possibly_sent no_replay",
    "T-42": "unsupported_operation mismatched_contract unknown_schema legacy_rejection supported_operation",
    "T-45.a": "source_isolation account_isolation operation_isolation",
    "T-45.b": "source_disallow_after_wait",
    "T-45.c": "grant_revoke_after_wait delegation_revoke_after_wait",
    "T-45.d": "credential_scope_change compromise revocation",
    "T-45.e": "eligible_rotation changed_revision_without_authority",
    "T-46.a": "operation_mutation payload_mutation order_mutation compatibility_mutation",
    "T-46.b": "assessment_status_tamper coverage_tamper reason_tamper digest_link_tamper later_assessment",
    "T-46.c": "activation_mutation eligible_activation",
    "T-46.d": "price_mutation owner_mutation",
    "T-47.a": "python_defaults commonjs_defaults parity",
    "T-47.b": "domain_goldens order_sensitive",
    "T-47.c": "legacy_parser legacy_digest caller_tool_cycle",
    "T-47.d": "unknown_version unknown_field strict_compatibility",
    "T-48.a": "native_non_token_quantity price_contract",
    "T-48.b": "tariff_a_all_25_inputs minimum ceiling",
    "T-48.c": "tariff_b_n10 tariff_b_n11",
    "T-48.d": "half_even_up_tie half_even_down_tie",
    "T-48.e": "reservation_raw reservation_settled",
    "T-48.f": "missing null invalid zero contradictory",
    "T-48.g": "three_distinct_minima one_batch_n3 repeated_attempt split_batch",
    "T-49.a": "absent_counter",
    "T-49.b": "null_counter",
    "T-49.c": "consistent_zero contradictory_zero",
    "T-49.d": "invalid_counter out_of_domain contradictory_counter",
    "T-49.e": "late_revision_no_resend",
    "T-50.a": "two_contenders finite_cap",
    "T-50.b": "duplicate_submission competing_submission",
    "T-50.c": "restart_unknown_exposure",
    "T-50.d": "linked_correction_delta_once",
    "T-50.e": "above_bound_recorded affected_scope_paused",
    "T-51": "ordered_batch wrong_count wrong_dimension nonfinite_vector no_truncation",
    "T-52": "wrong_vector_space wrong_index_profile compatible_positive",
    "T-53": "valid_rerank malformed_duplicate out_of_range wrong_order",
    "T-54": "rerank_failure_unknown labelled_degradation no_hidden_second_call",
    "T-55": "ingest_once distinct_query_rerank unique_allocation",
    "T-60": "direct_human delegated_agent autonomous forged_agent forged_owner forged_delegation cycle",
    "T-61": "direct_inclusive provider_person unknown_uninstrumented_idle",
    "T-62.a": "period_boundary timezone_boundary",
    "T-62.b": "revision_cutoff",
    "T-62.c": "provider_filter actor_filter task_filter environment_filter",
    "T-62.d": "timeline_csv_json_reconcile",
    "T-62.e": "cross_principal_denial",
    "T-64": "keyboard narrow error_reason management_edit_or_disabled no_secret",
    "T-65": "preview_seek replay_no_send no_ledger_mutation",
    "T-66": "old_row_migration backup_readback unknown_exposure one_use_runs",
    "T-77.a": "applicable_fields_reasons",
    "T-77.b": "invalid_reason inconsistent_combination",
    "T-77.c": "preadmission_applicability legacy_applicability",
    "T-77.d": "absence_not_authority",
    "T-78.a": "direct_binding chain_representation",
    "T-78.b": "delegated_binding ordered_asserted_links",
    "T-78.c": "autonomous_owner no_fictitious_person",
    "T-78.d": "forged_endpoint cycle excess_bound record_not_authority",
    "T-79.a": "absent_commission_reason asserted_record_only",
    "T-79.b": "record_only_no_execution_authority",
    "T-79.c": "caller_assertion_mutation signed_status_reason_tamper digest_link_tamper",
    "T-79.d": "later_verification_no_retroactive_upgrade",
}


def _handler_for(label: str) -> str:
    if label == "T-60":
        return "operator_identity"
    if label in {"T-01", "T-02", "T-03", "T-42"} or label.startswith(("T-77", "T-78", "T-79")):
        return "ingress_identity"
    if label in {"T-07.a", "T-14.a"} or label.startswith(("T-24", "T-45", "T-46")):
        return "authority_recovery"
    if label.startswith("T-47"):
        return "client_contract"
    if label.startswith(("T-48", "T-49", "T-50")):
        return "native_accounting"
    if label.startswith(("T-51", "T-52", "T-53", "T-54", "T-55")):
        return "retrieval_workflow"
    if label.startswith(("T-61", "T-62", "T-64", "T-65")):
        return "operator_reporting"
    if label == "T-66":
        return "persistence_migration"
    raise AssertionError(label)


_STAGES = {
    "ingress_identity": ("ingress", "admission"),
    "authority_recovery": ("admission", "signed_plan", "authority", "guard", "first_write"),
    "client_contract": ("client",),
    "native_accounting": ("admission", "receiver", "delivery", "settlement"),
    "retrieval_workflow": ("admission", "receiver", "delivery", "settlement"),
    "operator_reporting": ("settlement", "operator"),
    "operator_identity": ("operator",),
    "persistence_migration": ("persistence",),
    "recovery_chain": ("admission", "guard", "first_write", "receiver", "delivery", "settlement"),
}


def _key(label: str) -> str:
    return "t" + label[2:].replace("-", "_").replace(".", "_")


def _make_scenarios() -> dict[str, ScenarioSpec]:
    result = {}
    split = {"T-07.a", "T-24.a", "T-24.b", "T-49.c", "T-50.b"}
    for label, names in _VARIANTS.items():
        scenario = _key(label)
        handler = _handler_for(label)
        stages = _STAGES[handler]
        if label.startswith("T-48") and label != "T-48.f":
            stages = ("accounting",)
        if label in {
            "T-60",
            "T-61",
            "T-62.a",
            "T-62.b",
            "T-62.c",
            "T-62.d",
            "T-62.e",
            "T-64",
            "T-65",
        }:
            stages = ("operator",)
        objectives = names.split()
        if label in split:
            variants = {
                name: VariantSpec(handler, stages, (f"{scenario}.{name}",)) for name in objectives
            }
        else:
            phase = "terminal" if label == "T-50.e" else "normal"
            minimum_sends = 3 if label == "T-60" else 1 if label in {"T-01", "T-42"} else 0
            variants = {
                "composed": VariantSpec(
                    handler,
                    stages,
                    tuple(f"{scenario}.{name}" for name in objectives),
                    phase=phase,
                    reuse_permitted=(
                        label.startswith("T-47") or (label.startswith("T-48") and label != "T-48.f")
                    ),
                    minimum_admissions=minimum_sends,
                    minimum_possible_sends=minimum_sends,
                )
            }
        result[scenario] = ScenarioSpec((label,), variants)
    # This chain is mandatory even if T-49.e and T-50.d were independently
    # observed.  Its identity is one financial scope and one original attempt.
    chain = {
        "unknown_pause": ("recoverable_pause", _STAGES["recovery_chain"]),
        "retained_receipt": ("late_evidence", ("receiver",)),
        "authorized_late_append": ("late_evidence", ("receiver", "settlement")),
        "denied_resume": ("resume", ("authority", "settlement")),
        "eligible_resume": ("resume", ("authority", "settlement")),
    }
    result["recovery_chain"] = ScenarioSpec(
        (),
        {
            name: VariantSpec(
                "recovery_chain",
                stages,
                (f"recovery_chain.{name}",),
                phase,
                minimum_admissions=int(name == "unknown_pause"),
                minimum_possible_sends=int(name == "unknown_pause"),
            )
            for name, (phase, stages) in chain.items()
        },
    )
    return result


SCENARIOS = _make_scenarios()
REQUIRED_PAIRS = frozenset(
    (scenario, variant) for scenario, spec in SCENARIOS.items() for variant in spec.variants
)
SELECTED_IDS = frozenset(_VARIANTS)


# Append-only completion of the reviewed 80-pair inventory. These pairs use
# the same campaign; they do not alter the original case definitions or plan.
SUPPLEMENT_SCENARIOS = {
    "ct02_workkey": ("wire02_first", "wire03_first", "http_contention"),
    "ct02_recovery": ("wheel", "tarball"),
    "ct02_realized_guard": ("method_host_route", "headers_body", "timeout_matrix"),
    "ct02_authority_wait": ("activation_pause_expiry",),
    "ct02_failed_unknown": ("failed_then_corrected",),
    "ct02_revision33": ("accepted_history",),
    "ct02_historical_auth": ("read_write_resume",),
    "ct02_reporting": ("csv_overbound",),
    "ct02_transport": ("would_block_revoke", "partial_unknown"),
    "ct02_authority_atomic": ("rollback_stall_unpublished_restart",),
}
SUPPLEMENT_REQUIRED_PAIRS = frozenset(
    (scenario, variant)
    for scenario, variants in SUPPLEMENT_SCENARIOS.items()
    for variant in variants
)

# Prospective allocations are maxima, not observed counts. The legacy-first
# setup is counted as one admission even though its row is in the legacy table.
# Terminal authority pause is deliberately last in the supplemental inventory.
SUPPLEMENT_LIMITS = {
    ("ct02_workkey", "wire02_first"): (1, 0),
    ("ct02_workkey", "wire03_first"): (1, 1),
    ("ct02_workkey", "http_contention"): (2, 1),
    ("ct02_recovery", "wheel"): (1, 1),
    ("ct02_recovery", "tarball"): (1, 1),
    ("ct02_realized_guard", "method_host_route"): (4, 1),
    ("ct02_realized_guard", "headers_body"): (5, 1),
    ("ct02_realized_guard", "timeout_matrix"): (6, 1),
    ("ct02_failed_unknown", "failed_then_corrected"): (1, 1),
    ("ct02_transport", "would_block_revoke"): (2, 2),
    ("ct02_transport", "partial_unknown"): (1, 1),
    ("ct02_authority_atomic", "rollback_stall_unpublished_restart"): (2, 2),
    ("ct02_authority_wait", "activation_pause_expiry"): (4, 4),
}
SUPPLEMENT_PREDICATES = {
    ("ct02_workkey", variant): (f"ct02_workkey.{variant}",)
    for variant in SUPPLEMENT_SCENARIOS["ct02_workkey"]
}
SUPPLEMENT_PREDICATES.update(
    {
        ("ct02_recovery", variant): tuple(
            f"ct02_recovery.{variant}.{name}"
            for name in ("selectors", "duplicate", "denial", "no_repeat")
        )
        for variant in SUPPLEMENT_SCENARIOS["ct02_recovery"]
    }
)
for _variant, _names in {
    "method_host_route": ("method", "host", "route"),
    "headers_body": ("authorization", "missing_content_type", "extra_header", "body"),
    "timeout_matrix": ("changed", "missing", "extra", "nonfinite", "wrong_type"),
}.items():
    SUPPLEMENT_PREDICATES[("ct02_realized_guard", _variant)] = tuple(
        f"ct02_realized_guard.{name}" for name in (*_names, "matched_control")
    )
SUPPLEMENT_PREDICATES.update(
    {
        ("ct02_failed_unknown", "failed_then_corrected"): tuple(
            "ct02_failed_unknown." + name
            for name in ("failure_and_unknown", "denied_write", "late_finance", "audited_resume")
        ),
        ("ct02_revision33", "accepted_history"): tuple(
            "ct02_revision33." + name
            for name in ("accepted", "duplicate", "negatives", "latest_once")
        ),
        ("ct02_historical_auth", "read_write_resume"): tuple(
            "ct02_historical_auth." + name
            for name in ("read_denial", "wait_revocation", "post_expiry", "no_resend")
        ),
        ("ct02_reporting", "csv_overbound"): tuple(
            "ct02_reporting." + name
            for name in ("csv_finance", "historical_overbound_http", "read_only")
        ),
        ("ct02_transport", "would_block_revoke"): tuple(
            "ct02_transport." + name
            for name in ("product_drain", "would_block_positive", "would_block_revoked")
        ),
        ("ct02_transport", "partial_unknown"): tuple(
            "ct02_transport." + name
            for name in ("product_drain", "partial_unknown", "partial_no_replay")
        ),
        ("ct02_authority_atomic", "rollback_stall_unpublished_restart"): tuple(
            "ct02_authority_atomic." + name
            for name in ("definite_rollback", "stalled_commit", "unpublished", "restart")
        ),
        ("ct02_authority_wait", "activation_pause_expiry"): tuple(
            "ct02_authority_wait." + name for name in ("positive", "activation", "expiry", "pause")
        ),
    }
)
assert set(SUPPLEMENT_PREDICATES) == SUPPLEMENT_REQUIRED_PAIRS


def source_path_for_handler(name: str | None = None) -> Path:
    filename = (
        "dev12_completion_operator_handlers.py"
        if name in {"operator_identity", "operator_reporting", "persistence_migration"}
        else "dev12_completion_handlers.py"
    )
    return Path(__file__).with_name(filename).resolve()
