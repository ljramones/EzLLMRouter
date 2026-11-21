"""Objective, source-bound handlers for the finite DEV-12 target.

The registry intentionally lists only implemented scenario/variant pairs.
An unimplemented assurance variant cannot pass preflight by falling through to
a nominal generic handler.  Each handler retains the concrete HTTP, store,
receiver and accounting observations used by its assertions.
"""

from __future__ import annotations

from tools.gateway.paths import source_root as source_root

from copy import deepcopy as deepcopy
from concurrent.futures import ThreadPoolExecutor as ThreadPoolExecutor
from datetime import datetime as datetime, timezone as timezone
from decimal import (
    Decimal as Decimal,
    ROUND_CEILING as ROUND_CEILING,
    ROUND_HALF_EVEN as ROUND_HALF_EVEN,
)
from hashlib import sha256 as sha256
import json as json
import os as os
from pathlib import Path as Path
import subprocess as subprocess
import sys as sys
import threading as threading
import time as time

from tools.gateway.evidence.dev12_completion_catalog import CaseHandler as CaseHandler
from tools.gateway.evidence.dev12_completion_operator_handlers import (
    OPERATOR_CASE_HANDLERS as OPERATOR_CASE_HANDLERS,
)


SOURCE = Path(__file__).resolve()


from tools.gateway.evidence import (
    dev12_completion_handler_common as _dev12_completion_handler_common,
)
from tools.gateway.evidence import dev12_completion_ingress as _dev12_completion_ingress
from tools.gateway.evidence import dev12_completion_recovery as _dev12_completion_recovery
from tools.gateway.evidence import dev12_completion_accounting as _dev12_completion_accounting
from tools.gateway.evidence import dev12_completion_retrieval as _dev12_completion_retrieval
from tools.gateway.evidence import dev12_completion_clients as _dev12_completion_clients


_current_utc = _dev12_completion_handler_common._current_utc


_case_request = _dev12_completion_handler_common._case_request


_headers = _dev12_completion_handler_common._headers


_census = _dev12_completion_handler_common._census


_post = _dev12_completion_handler_common._post


_trusted = _dev12_completion_handler_common._trusted


_unknown_then_retained_correction = (
    _dev12_completion_handler_common._unknown_then_retained_correction
)


_evidence = _dev12_completion_handler_common._evidence


def ingress_identity(runtime, case):
    return _dev12_completion_ingress.ingress_identity(runtime, case)


def recovery_chain(runtime, case):
    return _dev12_completion_recovery.recovery_chain(runtime, case)


def authority_recovery(runtime, case):
    return _dev12_completion_recovery.authority_recovery(runtime, case)


def native_accounting(runtime, case):
    """Independently recompute all fixed native-unit tariff rows and bounds."""
    return _dev12_completion_accounting.native_accounting(runtime, case)


_retrieval_request = _dev12_completion_retrieval._retrieval_request


def retrieval_workflow(runtime, case):
    return _dev12_completion_retrieval.retrieval_workflow(runtime, case)


_offline_command = _dev12_completion_clients._offline_command


def client_contract(runtime, case):
    return _dev12_completion_clients.client_contract(runtime, case)


def _registration(name, run, supported):
    return CaseHandler(
        name=name,
        source_path=str(SOURCE),
        source_sha256=sha256(SOURCE.read_bytes()).hexdigest(),
        supported=frozenset(supported),
        run=run,
    )


DEV12_CASE_HANDLERS = {
    "ingress_identity": _registration(
        "ingress_identity",
        ingress_identity,
        {("t01", "composed"), ("t02", "composed"), ("t03", "composed"), ("t42", "composed")}
        | {
            (scenario, "composed")
            for scenario in (
                "t77_a",
                "t77_b",
                "t77_c",
                "t77_d",
                "t78_a",
                "t78_b",
                "t78_c",
                "t78_d",
                "t79_a",
                "t79_b",
                "t79_c",
                "t79_d",
            )
        },
    ),
    "recovery_chain": _registration(
        "recovery_chain",
        recovery_chain,
        {
            ("recovery_chain", variant)
            for variant in (
                "unknown_pause",
                "retained_receipt",
                "authorized_late_append",
                "denied_resume",
                "eligible_resume",
            )
        },
    ),
    "native_accounting": _registration(
        "native_accounting",
        native_accounting,
        {
            (scenario, "composed")
            for scenario in (
                "t48_a",
                "t48_b",
                "t48_c",
                "t48_d",
                "t48_e",
                "t48_f",
                "t48_g",
                "t49_a",
                "t49_b",
                "t49_d",
                "t49_e",
                "t50_a",
                "t50_c",
                "t50_d",
                "t50_e",
            )
        }
        | {("t49_c", "consistent_zero"), ("t49_c", "contradictory_zero")}
        | {("t50_b", "duplicate_submission"), ("t50_b", "competing_submission")},
    ),
    "client_contract": _registration(
        "client_contract",
        client_contract,
        {(scenario, "composed") for scenario in ("t47_a", "t47_b", "t47_c", "t47_d")},
    ),
    "authority_recovery": _registration(
        "authority_recovery",
        authority_recovery,
        {("t14_a", "composed")}
        | {
            ("t24_b", variant)
            for variant in (
                "revocation_before_write",
                "write_before_revocation",
                "would_block",
                "partial_write",
            )
        }
        | {("t24_c", "composed")}
        | {
            ("t07_a", variant)
            for variant in (
                "eligible_current",
                "rotated_old_eligible",
                "revoked_key_after_wait",
                "revoked_plan_after_wait",
            )
        }
        | {("t24_a", variant) for variant in ("queued_revocation", "eligible_control")}
        | {
            (scenario, "composed")
            for scenario in (
                "t45_a",
                "t45_b",
                "t45_c",
                "t45_d",
                "t45_e",
                "t46_a",
                "t46_b",
                "t46_c",
                "t46_d",
            )
        },
    ),
    "retrieval_workflow": _registration(
        "retrieval_workflow",
        retrieval_workflow,
        {(scenario, "composed") for scenario in ("t51", "t52", "t53", "t54", "t55")},
    ),
    **OPERATOR_CASE_HANDLERS,
}
