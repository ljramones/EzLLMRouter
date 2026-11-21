"""Operator integration handlers."""

from __future__ import annotations

from typing import cast
from urllib.parse import SplitResult
from ..records import Record
from ..integration_accounting import ExternalAccounting
from .context import OperatorContext, Session


import json
from urllib.parse import parse_qs

from ..integration_accounting import IntegrationError, route_id
from ..observability import log_failure


class IntegrationRoutes:
    def get_operator_v1_integration_identity(
        self: OperatorContext, path: SplitResult, session: Session, body: None, scope: str | None
    ) -> None:
        if not self.application.integration_only or session[1]["role"] != "registry_admin":
            return self._fail(404, "NOT_FOUND")
        lookup = self.application.identity_lookup
        user = lookup(self.headers.get("Cookie", "")) if lookup else None
        return self._send(200, {"user": user})

    def get_operator_v1_scripted_demo(
        self: OperatorContext, path: SplitResult, session: Session, body: None, scope: str | None
    ) -> None:
        if self.application.scripted_demo is None or session[1]["role"] not in (
            "registry_admin",
            "read_only_operator",
        ):
            return self._fail(404, "NOT_FOUND")
        query = parse_qs(path.query, strict_parsing=True, keep_blank_values=True)
        if any((len(value) != 1 for value in query.values())):
            raise ValueError("invalid demo selector")
        if path.path == "/operator/v1/scripted-demo/report":
            selected = {key: values[0] for key, values in query.items() if key != "export"}
            report = self.application.scripted_demo.report(selected)
            export = query.get("export", [None])[0]
            if export in (None, "json"):
                return self._send(
                    200,
                    report,
                    extra=(
                        (
                            "Content-Disposition",
                            "attachment; filename=ezllmrouter-scripted-demo-report.json",
                        ),
                    )
                    if export
                    else (),
                )
            if export == "csv":
                columns = (
                    "demo_provenance",
                    "dataset_id",
                    "attempt_id",
                    "workflow_id",
                    "task_id",
                    "run_id",
                    "executing_actor_id",
                    "initiating_user_id",
                    "charging_owner_id",
                    "provider_id",
                    "model_id",
                    "started_at",
                    "ended_at",
                    "local_date",
                    "provider_result",
                    "usage_revision_id",
                    "usage_observed_at",
                    "usage_state",
                    "input_tokens",
                    "output_tokens",
                    "cost_state",
                    "currency",
                    "amount_decimal",
                )
                return self._send_csv(
                    "ezllmrouter-scripted-demo-report.csv",
                    columns,
                    (
                        {
                            **row,
                            "demo_provenance": self.application.scripted_demo.meta[
                                "required_banner"
                            ],
                        }
                        for row in report["attempts"]
                    ),
                )
            raise ValueError("invalid demo export")
        if path.path == "/operator/v1/scripted-demo/workflow" and set(query) == {"workflow_id"}:
            try:
                return self._send(
                    200, self.application.scripted_demo.workflow(query["workflow_id"][0])
                )
            except KeyError:
                return self._fail(404, "NOT_FOUND")
        return self._fail(404, "NOT_FOUND")

    def get_operator_v1_integration(
        self: OperatorContext, path: SplitResult, session: Session, body: None, scope: str | None
    ) -> None:
        principal = cast(Record, self._registry.principal(session[1]["principal_id"]))
        ledger = self._registry.integration
        if path.path == "/operator/v1/integration/datasets" and (not path.query):
            return self._send(200, ledger.datasets(principal))
        query = parse_qs(path.query, strict_parsing=True, keep_blank_values=True)
        allowed = (
            {
                "dataset_id",
                "actor_id",
                "provider_account_id",
                "task_id",
                "model_id",
                "initiating_user_id",
                "root_run_id",
                "run_id",
                "from",
                "to",
                "export",
            }
            if path.path == "/operator/v1/integration/report"
            else {"dataset_id"}
        )
        if (
            any((len(values) != 1 for values in query.values()))
            or "dataset_id" not in query
            or set(query) - allowed
        ):
            raise ValueError("invalid integration selector")
        dataset_id = query["dataset_id"][0]
        if path.path == "/operator/v1/integration/connections":
            return self._send(
                200,
                self._credentials.list(principal, dataset_id),
            )
        if path.path == "/operator/v1/integration/accounts":
            return self._send(200, ledger.accounts(principal, dataset_id))
        if path.path == "/operator/v1/integration/report":
            return _send_integration_report(dataset_id, ledger, principal, query, self)
        if path.path == "/operator/v1/integration/export" and set(query) == {"dataset_id"}:
            return self._send(
                200,
                ledger.dataset_export(principal, dataset_id, "3"),
                extra=(
                    (
                        "Content-Disposition",
                        "attachment; filename=ezllmrouter-integration-dataset.json",
                    ),
                ),
            )
        return self._fail(404, "NOT_FOUND")

    def post_operator_v1_integration(
        self: OperatorContext, path: None, session: Session, body: Record, scope: str | None
    ) -> None:
        if session[1]["role"] != "registry_admin":
            return self._fail(403, "ADMIN_REQUIRED")
        principal = cast(Record, self._registry.principal(session[1]["principal_id"]))
        try:
            if self.path == "/operator/v1/integration/datasets":
                status, result = self._registry.integration.create_dataset(principal, body)
            elif self.path == "/operator/v1/integration/connections":
                result = self._credentials.connect(principal, body)
                status = 201
            elif self.path.startswith("/operator/v1/integration/connections/"):
                parts = self.path.split("/")
                if len(parts) != 7 or parts[-1] not in (
                    "save",
                    "refresh",
                    "replace",
                    "disable",
                    "retire",
                ):
                    return self._fail(404, "NOT_FOUND")
                account_id = route_id(parts[-2])
                result = getattr(self._registry.integration_credentials, parts[-1])(
                    principal, account_id, body
                )
                status = 200
            elif self.path == "/operator/v1/integration/accounts":
                status, result = self._registry.integration.create_account(
                    principal, body, "3" if "allowed_operations" in body else "1"
                )
            elif self.path.endswith("/permissions") and self.path.startswith(
                "/operator/v1/integration/accounts/"
            ):
                account_raw = self.path[
                    len("/operator/v1/integration/accounts/") : -len("/permissions")
                ]
                if "/" in account_raw:
                    return self._fail(404, "NOT_FOUND")
                status, result = self._registry.integration.set_account_permissions(
                    principal, route_id(account_raw), body
                )
            elif self.path.endswith("/state") and self.path.startswith(
                "/operator/v1/integration/accounts/"
            ):
                account_raw = self.path[len("/operator/v1/integration/accounts/") : -len("/state")]
                if "/" in account_raw:
                    return self._fail(404, "NOT_FOUND")
                account_id = route_id(account_raw)
                status, result = self._registry.integration.set_account_state(
                    principal, account_id, body
                )
            else:
                return self._fail(404, "NOT_FOUND")
            return self._send(status, result)
        except IntegrationError as exc:
            return self._fail(exc.status, exc.code)
        except Exception:
            log_failure("operator_http.integration.post_operator_v1_integration.failed")
            return self._fail(503, "INTEGRATION_UNAVAILABLE")


def _send_integration_report(
    dataset_id: str,
    ledger: ExternalAccounting,
    principal: Record,
    query: dict[str, list[str]],
    self: OperatorContext,
) -> None:
    filters = {key: value[0] for key, value in query.items() if key not in ("dataset_id", "export")}
    report = ledger.report(principal, dataset_id, filters, version="3")
    export = query.get("export", [None])[0]
    if export in (None, "json"):
        return self._send(
            200,
            report,
            extra=(
                (
                    "Content-Disposition",
                    "attachment; filename=ezllmrouter-integration-report.json",
                ),
            )
            if export
            else (),
        )
    if export == "csv":
        columns = (
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
        return self._send_csv(
            "ezllmrouter-integration-report.csv",
            columns,
            (
                {
                    key: json.dumps(value, sort_keys=True)
                    if key in ("native_units", "eligibility_record", "selected_action")
                    and value is not None
                    else value
                    for key, value in row.items()
                }
                for row in report["attempts"]
            ),
        )
    raise ValueError("invalid report export")
