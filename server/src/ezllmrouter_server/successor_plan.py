"""Synthetic wire-0.3 plan minting and independently bound eligibility.

The signer is injected by the trusted service. Worker and installed clients do
not receive it. Current authority records are supplied separately from plans.
"""

from __future__ import annotations

from typing import Protocol, cast
from .records import Record

import base64
from decimal import Decimal

from .retrieval_descriptor import execution_descriptor
from .successor_contract import (
    SCHEMAS,
    canonical,
    config_for,
    domain_digest,
    price_for,
    schema_valid,
    tariff,
    valid_utc_second,
    work_digest,
    work_projection,
)


class PlanSigner(Protocol):
    def sign(self, data: bytes) -> bytes: ...


def signing_message(plan: Record) -> bytes:
    unsigned = {key: value for key, value in plan.items() if key != "signature"}
    return ("ezllmrouter-plan-v1\n" + canonical(unsigned)).encode("utf-8")


def mint_plan(
    request: Record,
    work_hash: str,
    admission_hash: str,
    submission_id: str,
    attempt_id: str,
    owner_id: str,
    budget_account_id: str,
    authority_revisions: Record,
    activation: Record,
    key_id: str,
    key_version: str,
    private_key: PlanSigner,
) -> Record:
    """Mint only for an already validated admitted request and assessed work."""
    config = config_for(request)
    price = price_for(request)
    if not config or not price:
        raise ValueError("unregistered synthetic operation")
    bound = tariff(request, price)["bound"]
    descriptor = execution_descriptor(request, work_hash, config)
    reservation = {
        "reservation_id": "reservation." + attempt_id,
        "budget_account_id": budget_account_id,
        "financial_owner_id": owner_id,
        "currency": "USD",
        "max_exposure_decimal": bound,
        "price_ref": price["price_ref"],
        "usage_ref": price["usage_ref"],
    }
    plan = {
        "plan_version": "dev12-plan@1",
        "plan_id": "plan." + attempt_id,
        "submission_id": submission_id,
        "attempt_id": attempt_id,
        "work_digest": work_hash,
        "admission_snapshot_digest": admission_hash,
        "operation": request["operation"],
        "adapter_ref": config["adapter_ref"],
        "price_ref": price["price_ref"],
        "usage_ref": price["usage_ref"],
        "destination_ref": config["destination_ref"],
        "financial_owner_id": owner_id,
        "authority_revisions": authority_revisions,
        "execution_context": activation,
        "key_id": key_id,
        "key_version": key_version,
        "expires_at": request["deadline"],
        "signature_scheme": "ed25519",
        "reservation": reservation,
        "execution_descriptor": descriptor,
    }
    if not schema_valid(plan | {"signature": "A" * 86}, SCHEMAS["$defs"]["SignedPlan"]):
        raise ValueError("invalid signed plan shape")
    signature = private_key.sign(signing_message(plan))
    if len(signature) != 64:
        raise ValueError("invalid synthetic signer")
    plan["signature"] = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return plan


def verified_signature(plan: Record, key: Record) -> bool:
    """Use exact signed tuple/material; malformed base64 and wrong key type fail."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.exceptions import InvalidSignature

    signature = plan.get("signature")
    if (
        type(signature) is not str
        or len(signature) != 86
        or any(
            char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
            for char in signature
        )
    ):
        return False
    try:
        raw = base64.urlsafe_b64decode(signature + "==")
        if len(raw) != 64 or base64.urlsafe_b64encode(raw).decode().rstrip("=") != signature:
            return False
        der_text = key["public_key_spki_base64"]
        der = base64.b64decode(der_text, validate=True)
        if base64.b64encode(der).decode() != der_text:
            return False
        public = serialization.load_der_public_key(der)
        if not isinstance(public, Ed25519PublicKey):
            return False
        public.verify(raw, signing_message(plan))
        return True
    except (ValueError, KeyError, InvalidSignature):
        return False


def plan_valid(
    plan: Record,
    request: Record,
    admitted_work_hash: str,
    admitted_snapshot_hash: str,
    owner_id: str,
    *,
    permit_historical_underbound: bool = False,
) -> bool:
    if not schema_valid(plan, SCHEMAS["$defs"]["SignedPlan"]):
        return False
    config, price = config_for(request), price_for(request)
    if not config or not price:
        return False
    descriptor, reservation = plan["execution_descriptor"], plan["reservation"]
    if (
        plan["work_digest"] != admitted_work_hash
        or plan["admission_snapshot_digest"] != admitted_snapshot_hash
        or canonical(plan["operation"]) != canonical(request["operation"])
        or plan["adapter_ref"] != config["adapter_ref"]
        or plan["destination_ref"] != config["destination_ref"]
        or plan["price_ref"] != price["price_ref"]
        or plan["usage_ref"] != price["usage_ref"]
        or plan["financial_owner_id"] != owner_id
        or reservation["financial_owner_id"] != owner_id
        or reservation["price_ref"] != price["price_ref"]
        or reservation["usage_ref"] != price["usage_ref"]
        or reservation["currency"] != "USD"
    ):
        return False
    if not permit_historical_underbound and Decimal(reservation["max_exposure_decimal"]) < Decimal(
        tariff(request, price)["bound"]
    ):
        return False
    if descriptor != execution_descriptor(request, admitted_work_hash, config):
        return False
    return valid_utc_second(plan["expires_at"]) and cast(
        bool, plan["expires_at"] <= request["deadline"]
    )


def execution_eligible(
    plan: Record,
    request: Record,
    admitted_work: Record,
    admission_snapshot: Record,
    context: Record,
) -> bool:
    """Full work+assessment prevalidation and independently resolved current gate."""
    if not schema_valid(context, SCHEMAS["$defs"]["ExecutionEligibilityContext"]):
        return False
    if (
        not schema_valid(admitted_work, SCHEMAS["$defs"]["CanonicalWork"])
        or work_projection(request, {"identity": admitted_work["trusted"]}) != admitted_work
    ):
        return False
    work_hash = work_digest(admitted_work)
    admission_hash = domain_digest("ezllmrouter-admission-v1\n", admission_snapshot)
    if (
        not schema_valid(admission_snapshot, SCHEMAS["$defs"]["AdmissionSnapshot"])
        or admission_snapshot["work_digest"] != work_hash
        or admission_snapshot.get("commission", {}).get("status") == "verified"
        or admission_snapshot.get("delegation", {}).get("coverage") != "none"
        or admission_snapshot.get("delegation", {}).get("verified_link_indices")
        or not valid_utc_second(admission_snapshot.get("assessed_at"))
        or (
            "commission" not in request["metadata"]
            and admission_snapshot["commission"].get("absence_reason") != "caller_omitted"
        )
    ):
        return False
    if not plan_valid(
        plan, request, work_hash, admission_hash, admitted_work["trusted"]["charging_owner_id"]
    ):
        return False
    if (
        not valid_utc_second(context["evaluation_time"])
        or context["evaluation_time"] >= plan["expires_at"]
        or not context["send_permission"]
        or context["plan_revoked"]
    ):
        return False
    for expected, actual in (
        (context["expected_submission_id"], plan["submission_id"]),
        (context["expected_attempt_id"], plan["attempt_id"]),
        (context["expected_work_digest"], plan["work_digest"]),
        (context["expected_admission_snapshot_digest"], plan["admission_snapshot_digest"]),
        (context["expected_financial_owner_id"], plan["financial_owner_id"]),
    ):
        if expected != actual:
            return False
    if (
        canonical(context["expected_reservation"]) != canonical(plan["reservation"])
        or canonical(context["expected_execution_context"]) != canonical(plan["execution_context"])
        or canonical(context["current_authority_revisions"])
        != canonical(plan["authority_revisions"])
    ):
        return False
    tuples = [(item["key_id"], item["key_version"]) for item in context["verification_keys"]]
    if len(tuples) != len(set(tuples)):
        return False
    key = next(
        (
            item
            for item in context["verification_keys"]
            if (item["key_id"], item["key_version"]) == (plan["key_id"], plan["key_version"])
        ),
        None,
    )
    return bool(key and key["eligibility"] == "eligible" and verified_signature(plan, key))
