"""Coordinator admission steps under the existing instance context."""

from __future__ import annotations

from typing import TYPE_CHECKING
from .records import Record
from .core_types import Reply

if TYPE_CHECKING:
    from .core import Coordinator
    from . import core as _api

import sqlite3
from copy import deepcopy
from decimal import Decimal
from .cache_accounting import SEMANTICS as CACHE_SEMANTICS
from .cache_accounting import exposure_bound
from .canonical import (
    ContractError,
    jcs,
    validate_text_request,
)
from .states import CandidateAccess, DeliveryState, DispatchState, SettlementState, SubmissionState


def _validate_admission(
    self: Coordinator, req: Record, trusted: Record, wait_ms: int
) -> tuple[Record, Record | None, list[Record], Record, str, str]:
    if type(wait_ms) is not int or not 0 <= wait_ms <= 30000:
        raise ContractError("SCHEMA_INVALID", 400)
    decision = None
    if self.registry:
        # The request supplies only the exact reference. Identity and owner
        # came from the authenticated service credential, never the body.
        if type(req) is not dict or any(
            type(req.get(field)) is not str
            for field in ("requested_configuration_ref", "purpose", "task_class")
        ):
            raise ContractError("SCHEMA_INVALID", 400)
        # The existing strict wire/source validator runs before policy
        # lookup; it uses only the reference field of this placeholder.
        messages, settings, deadline, prompt_digest = validate_text_request(
            req,
            trusted,
            {"configuration_ref": req["requested_configuration_ref"]},
            self.prompt_blocks,
            self.allowed_lineages,
        )
        self._verify_sources(messages, trusted)
        admitted_config, decision = self.registry.admit(
            trusted["principal_id"],
            req["requested_configuration_ref"],
            req["purpose"],
            req["task_class"],
            req["requested_features"],
        )
    else:
        admitted_config = deepcopy(self.config)
        messages, settings, deadline, prompt_digest = validate_text_request(
            req, trusted, admitted_config, self.prompt_blocks, self.allowed_lineages
        )
        self._verify_sources(messages, trusted)
    return admitted_config, decision, messages, settings, deadline, prompt_digest


def _check_admission_exposure(
    self: Coordinator, decision: Record | None, settings: Record, projected: Record
) -> None:
    if decision and decision["price_schedule"]:
        schedule = decision["price_schedule"]
        policy = self.authority.policy
        if schedule["currency"] != policy["currency"]:
            raise ContractError("FINANCIAL_AUTH_REQUIRED", 403)
        if schedule["usage_semantics_version"] == CACHE_SEMANTICS:
            try:
                upper = exposure_bound(schedule, settings["max_output_tokens"])
            except (KeyError, ValueError):
                raise ContractError("FINANCIAL_AUTH_REQUIRED", 403) from None
            if upper > Decimal(policy["max_attempt_charge_decimal"]):
                raise ContractError("FINANCIAL_AUTH_REQUIRED", 403)
        else:
            # Historical synthetic and DEV-10 prices keep their original
            # behavior. They are not eligible for a new live campaign.
            input_bound = len(jcs(projected["work"]["messages"])) + 1024
            upper = (
                Decimal(input_bound) * Decimal(schedule["rates"]["input_uncached"])
                + Decimal(settings["max_output_tokens"]) * Decimal(schedule["rates"]["output_text"])
            ) / Decimal(schedule["unit_denominator"])
            if upper > Decimal(policy["max_attempt_charge_decimal"]):
                raise ContractError("FINANCIAL_AUTH_REQUIRED", 403)


def _admission_record(
    self: Coordinator,
    admitted: _api.AdmittedWork,
    req: Record,
    trusted: Record,
    attribution: Record | None,
) -> Record:
    from . import core as _api

    principal = self.registry.principal(trusted["principal_id"]) if self.registry else None
    record = {
        "submission_id": admitted.sid,
        "attempt_id": admitted.aid,
        "principal_id": trusted["principal_id"],
        "principal_kind": principal["kind"] if principal else None,
        "charging_owner_id": trusted["charging_owner_id"],
        "task_id": req["task_id"],
        "work_key": admitted.key,
        "work_digest": admitted.wd,
        "created_at": _api.now(),
        "task_class": req["task_class"],
        "purpose": req["purpose"],
        "provenance": "synthetic_local"
        if admitted.admitted_config.get("service") == "litellm.dev04"
        else "live_personal_test"
        if (self.registry.personal_campaign if self.registry is not None else None)
        else "controlled_provider_test"
        if (self.registry.controlled_provider_proof if self.registry is not None else False)
        else "selected_provider_attempt",
        "selected_destination": deepcopy(admitted.admitted_config),
        **(
            {"attribution": attribution, "attribution_digest": admitted.attribution_digest}
            if attribution
            else {}
        ),
        "source_authority_id": trusted["source_authority_id"],
        "context_id": trusted["context_id"],
        "classification_snapshot": admitted.admitted_classification,
        **({"registry_decision": admitted.decision} if admitted.decision else {}),
        "submission_state": SubmissionState.ADMITTED.value,
        "dispatch_state": DispatchState.PREPARED.value,
        "delivery_state": DeliveryState.NONE.value,
        "cancel_state": "none",
        "settlement_state": SettlementState.UNSETTLED.value,
        "generation_state": "current",
        "status_revision": 1,
        "attempt_revision": 1,
        "updated_at": _api.now(),
        "candidate_access": CandidateAccess.NOT_YET_AVAILABLE.value,
        "content_store_allowed": admitted.admitted_retention["content_store_allowed"],
        "content_expires_at": admitted.admitted_retention.get("content_expires_at"),
        "wait_expired_no_store": False,
    }
    return record


def _persist_admission(
    self: Coordinator, admitted: _api.AdmittedWork, record: Record, req: Record, settings: Record
) -> Reply | None:
    from . import core as _api

    campaign = (
        (self.registry.personal_campaign if self.registry is not None else None)
        if self.registry
        else None
    )
    provider_work = admitted.admitted_config.get("service") == "openai.responses.v1"
    if (
        provider_work
        and (not (self.registry.controlled_provider_proof if self.registry is not None else False))
        and (campaign is None)
    ):
        raise ContractError("FINANCIAL_AUTH_REQUIRED", 403)
    if provider_work and (
        "tools" in req["requested_features"]
        or admitted.projected["work"].get("tools")
        or admitted.projected["work"].get("tool_choice") != "none"
    ):
        raise ContractError("FINANCIAL_AUTH_REQUIRED", 403)
    try:
        if provider_work and campaign is not None:
            message_bytes = len(jcs(admitted.projected["work"]["messages"]))
            self.store.create(
                record,
                reserve=lambda db, item: campaign.reserve(
                    db, item, message_bytes, settings["max_output_tokens"]
                ),
            )
        else:
            self.store.create(record)
    except ContractError:
        raise
    except sqlite3.IntegrityError as caught_error:
        owner = self.store.work_owner(admitted.key)
        if owner and owner["contract_version"] != "0.2":
            raise ContractError("WORK_VERSION_CONFLICT", 409) from None
        duplicate = self.store.by_work(admitted.key)
        if (
            duplicate
            and duplicate["work_digest"] == admitted.wd
            and (duplicate.get("attribution_digest") == admitted.attribution_digest)
        ):
            return (202, self._pending(duplicate))
        raise ContractError("WORK_CONFLICT", 409) from caught_error
    except Exception as exc:
        _api.log_failure("core.Coordinator.admission_persist.failed")
        raise ContractError("INTERNAL_UNAVAILABLE", 503) from exc
    return None
