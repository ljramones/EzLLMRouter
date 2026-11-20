"""Operator reports handlers."""

from datetime import datetime, timezone
from urllib.parse import parse_qs

from ..demo_workspace import project_demo
from ..demo_workspace_team import project_team_demo
from ..observability import log_failure
from ..reporting import usage_costs
from ..successor_reporting import usage_report


class ReportsRoutes:
    def get_operator_v1_dev12_usage(self, path, session, body, scope):
        query = parse_qs(path.query, strict_parsing=True, keep_blank_values=True)
        if any((len(values) != 1 for values in query.values())) or set(query) - {
            "from",
            "to",
            "cutoff",
            "operation",
            "actor_id",
            "provider_ref",
            "initiating_user_id",
            "charging_owner_id",
            "root_workflow_id",
            "configuration_ref",
            "task_id",
            "environment",
            "export",
        }:
            raise ValueError("invalid synthetic report filter")
        selected = {key: values[0] for key, values in query.items() if key != "export"}
        report = usage_report(
            self.application.successor_store,
            {"role": session[1]["role"], "principal_id": session[1]["principal_id"]},
            selected,
        )
        export = query.get("export", [None])[0]
        if export in (None, "json"):
            return self._send(
                200,
                report,
                extra=(
                    (
                        "Content-Disposition",
                        "attachment; filename=ezllmrouter-dev12-synthetic-usage.json",
                    ),
                )
                if export
                else (),
            )
        if export == "csv":
            columns = (
                "attempt_id",
                "submission_id",
                "created_at",
                "principal_id",
                "task_id",
                "run_id",
                "parent_run_id",
                "root_workflow_id",
                "environment",
                "operation",
                "input_role",
                "actor_id",
                "initiating_user_id",
                "charging_owner_id",
                "provider_ref",
                "configuration_ref",
                "price_ref",
                "usage_ref",
                "usage_revision",
                "native_components",
                "reservation_decimal",
                "cost_status",
                "currency",
                "amount_decimal",
                "exposure_state",
                "exposure_state_as_of",
                "submission_state",
                "delivery_state",
                "candidate_access",
            )
            return self._send_csv(
                "ezllmrouter-dev12-synthetic-usage.csv", columns, report["attempts"]
            )
        raise ValueError("invalid synthetic report export")

    def get_operator_v1_demo_workspace(self, path, session, body, scope):
        query = parse_qs(path.query, strict_parsing=True, keep_blank_values=True)
        if any((len(values) != 1 for values in query.values())) or set(query) - {
            "collection",
            "story",
            "actor",
            "person",
            "provider",
        }:
            raise ValueError("invalid demo filter")
        collection = query.get("collection", ["legacy"])[0]
        default_story = (
            "main"
            if collection == "legacy"
            else "expanded_all"
            if collection == "expanded"
            else "team"
        )
        filters = {
            "story": query.get("story", [default_story])[0],
            "actor": query.get("actor", [""])[0],
            "provider": query.get("provider", [""])[0],
        }
        if collection == "legacy":
            report = project_demo(
                self.application.root / "dev09_demo_fixture.json",
                person=query.get("person", [""])[0],
                **filters,
            )
        else:
            report = project_team_demo(
                self.application.root / "dev09_demo_fixture.json",
                collection=collection,
                person=query.get("person", [""])[0],
                **filters,
            )
        return self._send(200, report)

    def get_operator_v1_usage_costs(self, path, session, body, scope):
        query = parse_qs(path.query, strict_parsing=True, keep_blank_values=True)
        if any((len(values) != 1 for values in query.values())) or set(query) - {
            "from",
            "to",
            "cutoff",
            "currency",
            "environment",
            "provider",
            "connection_id",
            "model",
            "configuration_ref",
            "agent_id",
            "agent_version",
            "initiating_user_id",
            "charging_owner_id",
            "task_class",
            "purpose",
            "agent_search",
            "page",
            "limit",
            "export",
        }:
            raise ValueError("invalid report filter")
        selected = {
            key: values[0]
            for key, values in query.items()
            if key not in ("page", "limit", "export")
        }
        report = usage_costs(
            self.application.registry,
            {"role": session[1]["role"], "principal_id": session[1]["principal_id"]},
            selected,
            page=int(query.get("page", ["1"])[0]),
            limit=int(query.get("limit", ["50"])[0]),
        )
        export = query.get("export", [None])[0]
        if export == "json":
            return self._send(
                200,
                report,
                extra=(
                    (
                        "Content-Disposition",
                        "attachment; filename=ezllmrouter-usage-costs.json",
                    ),
                ),
            )
        if export == "csv":
            columns = (
                "attempt_id",
                "submission_id",
                "attempt_at",
                "provider",
                "connection_id",
                "configuration_ref",
                "model",
                "agent_id",
                "agent_version",
                "run_id",
                "root_run_id",
                "initiating_user_id",
                "charging_owner_id",
                "task_id",
                "task_class",
                "purpose",
                "environment",
                "cost_status",
                "currency",
                "amount_decimal",
                "estimated_amount_decimal",
                "price_version",
                "usage_revision",
                "input_tokens",
                "output_tokens",
            )
            return self._send_csv("ezllmrouter-usage-costs.csv", columns, report["attempts"])
        if export is not None:
            raise ValueError("invalid report export")
        return self._send(200, report)

    def get_operator_v1_overview(self, path, session, body, scope):
        try:
            worker = self.application.worker_probe()
        except Exception as exc:
            log_failure("operator_http.overview.worker_probe.failed")
            worker = {"state": "unavailable", "error_type": type(exc).__name__}
        return self._send(
            200,
            {
                "profile": "LOCAL DEVELOPMENT · PROVIDER PATH GATED"
                if self.application.registry and self.application.registry.provider_execution_ready
                else "LIVE SYNTHETIC DEVELOPMENT",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "service": {"state": "live"},
                "worker": worker,
                "sender": self.application.sender_status(),
                "counts": self.application.projection.overview_counts(scope),
                "recent": self.application.projection.activity(limit=6, principal_id=scope)[
                    "items"
                ],
                "build": {
                    "commit": self.application.build.get("commit"),
                    "dirty": self.application.build.get("dirty"),
                    "fingerprint": self.application.build.get("fingerprint"),
                },
            },
        )

    def get_operator_v1_activity(self, path, session, body, scope):
        query = parse_qs(path.query, strict_parsing=True, keep_blank_values=True)
        if set(query) - {"page", "limit", "state", "principal_id"} or any(
            (len(x) != 1 for x in query.values())
        ):
            raise ValueError("query")
        selected = query.get("principal_id", [None])[0]
        if selected is not None:
            if not self.application.registry or not self.application.registry.principal(selected):
                raise ValueError("invalid principal filter")
            if session[1]["role"] == "ordinary" and selected != scope:
                return self._fail(404, "NOT_FOUND")
        return self._send(
            200,
            self.application.projection.activity(
                page=int(query.get("page", ["1"])[0]),
                limit=int(query.get("limit", ["20"])[0]),
                state=query.get("state", [None])[0],
                principal_id=selected or scope,
            ),
        )

    def get_activity_detail(self, path, session, body, scope):
        identifier = path.path[len("/operator/v1/activity/") :]
        if "/" in identifier:
            raise ValueError("invalid activity path")
        value = self.application.projection.detail(identifier, scope)
        return self._send(200, value) if value else self._fail(404, "NOT_FOUND")

    def get_operator_v1_usage(self, path, session, body, scope):
        query = parse_qs(path.query, strict_parsing=True, keep_blank_values=True)
        if set(query) - {"principal_id"} or any((len(x) != 1 for x in query.values())):
            raise ValueError("invalid usage filter")
        selected = query.get("principal_id", [None])[0]
        if selected is not None:
            if not self.application.registry or not self.application.registry.principal(selected):
                raise ValueError("invalid principal filter")
            if session[1]["role"] == "ordinary" and selected != scope:
                return self._fail(404, "NOT_FOUND")
        return self._send(200, self.application.projection.usage(selected or scope))

    def get_operator_v1_config(self, path, session, body, scope):
        destination = self.application.fixture["destination"]
        policy = self.application.fixture["policy"]
        return self._send(
            200,
            {
                "configuration": {
                    k: destination[k]
                    for k in (
                        "configuration_ref",
                        "service",
                        "endpoint",
                        "model",
                        "model_version",
                        "processing_region",
                    )
                },
                "policy": {
                    k: policy[k]
                    for k in (
                        "policy_version",
                        "registry_version",
                        "limit_version",
                        "recovery_policy_version",
                    )
                },
                "capabilities": {
                    "text": True,
                    "caller_owned_lookup": True,
                    "configuration_editing": bool(self.application.registry),
                    "approval_revocation": bool(self.application.registry),
                    "budgets": False,
                    "cancellation": False,
                    "real_provider": bool(
                        self.application.registry
                        and self.application.registry.personal_campaign
                        and (
                            self.application.registry.personal_campaign.summary()["effective_state"]
                            == "active"
                        )
                    ),
                },
            },
        )

    def get_operator_v1_build(self, path, session, body, scope):
        return self._send(
            200,
            {
                "profile": "LOCAL DEVELOPMENT · PROVIDER PATH GATED"
                if self.application.registry and self.application.registry.provider_execution_ready
                else "LIVE SYNTHETIC DEVELOPMENT",
                "build": self.application.build,
                "packages": {"python_client": "0.0.4", "litellm": "1.105.1"},
                "environment": "local isolated synthetic HTTP/1.1 and selected provider HTTPS"
                if self.application.registry and self.application.registry.provider_execution_ready
                else "local isolated synthetic HTTP/1.1",
                "milestones": ["DEV-04 Run-11", "DEV-05 Run-16"],
            },
        )

    def get_operator_v1_launch(self, path, session, body, scope):
        identifier = path.path[len("/operator/v1/launch/") :]
        if "/" in identifier:
            raise ValueError("invalid launch path")
        value = self.application.projection.launch(identifier)
        return self._send(200, value) if value else self._fail(404, "NOT_FOUND")

    def post_operator_v1_demos(self, path, session, body, scope):
        if self.application.registry and session[1]["role"] != "registry_admin":
            return self._fail(403, "ADMIN_REQUIRED")
        kind = self.path.rsplit("/", 1)[1]
        if set(body) != {"operation_id"} or kind not in ("text", "tool", "no_store_text"):
            return self._fail(400, "INVALID_BODY")
        try:
            fresh = self.application.projection.begin_launch(body["operation_id"], kind)
            if fresh:
                try:
                    self.application.jobs.submit(
                        self.application.execute, body["operation_id"], kind
                    )
                except RuntimeError:
                    self.application.projection.finish_launch(
                        body["operation_id"], "failed", [], error_code="INTERNAL_UNAVAILABLE"
                    )
                    return self._fail(503, "INTERNAL_UNAVAILABLE")
            return self._send(202, self.application.projection.launch(body["operation_id"]))
        except (ValueError, TypeError):
            return self._fail(409, "INVALID_OPERATION")
