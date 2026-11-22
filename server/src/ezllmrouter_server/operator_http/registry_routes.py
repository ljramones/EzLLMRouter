"""Operator registry routes handlers."""

from __future__ import annotations

from typing import cast
from urllib.parse import SplitResult
from ..records import Record
from ..personal_campaign import PersonalCampaign
from .context import OperatorContext, Session


from urllib.parse import parse_qs

from ..errors import RequestError
from ..observability import log_failure
from ..provider_adapters import ADAPTERS, PROVIDERS
from ..errors import RegistryConflict
from ..user_management import UserError


class RegistryRoutes:
    def get_registry_providers(
        self: OperatorContext, path: SplitResult, session: Session, body: None, scope: str | None
    ) -> None:
        return self._send(200, {"providers": PROVIDERS, "adapters": ADAPTERS})

    def get_registry_validation(
        self: OperatorContext, path: SplitResult, session: Session, body: None, scope: str | None
    ) -> None:
        operation_id = path.path[len("/operator/v1/provider-validations/") :]
        if not operation_id or "/" in operation_id:
            return self._fail(404, "NOT_FOUND")
        value = self.application.projection.provider_validation(operation_id)
        return self._send(200, value) if value else self._fail(404, "NOT_FOUND")

    def get_registry_connections(
        self: OperatorContext, path: SplitResult, session: Session, body: None, scope: str | None
    ) -> None:
        return self._send(200, {"items": self._registry.list_connections()})

    def get_registry_campaign(
        self: OperatorContext, path: SplitResult, session: Session, body: None, scope: str | None
    ) -> None:
        actor = session[1]["principal_id"]
        if actor != self.application.owner_id or not getattr(
            self.application.registry, "personal_campaign", None
        ):
            return self._fail(403, "OWNER_REQUIRED")
        return self._send(200, self._campaign.summary())

    def get_registry_inventory(
        self: OperatorContext, path: SplitResult, session: Session, body: None, scope: str | None
    ) -> None:
        connection_id = path.path[len("/operator/v1/connections/") : -len("/inventory")]
        if "/" in connection_id or not self._registry.connection(connection_id):
            return self._fail(404, "NOT_FOUND")
        return self._send(200, self._registry.source_inventory(connection_id))

    def get_registry_connection(
        self: OperatorContext, path: SplitResult, session: Session, body: None, scope: str | None
    ) -> None:
        if path.path.endswith("/inventory"):
            return self.get_registry_inventory(path, session, body, scope)
        connection_id = path.path[len("/operator/v1/connections/") :]
        if "/" in connection_id:
            raise ValueError("invalid connection path")
        connection = self._registry.connection(connection_id)
        if not connection:
            return self._fail(404, "NOT_FOUND")
        return self._send(
            200,
            {
                "connection": connection,
                "deployments": self._registry.deployments(connection_id),
                "observations": self._registry.observations(connection_id),
                "history": self._registry.history(connection_id),
            },
        )

    def get_registry_models(
        self: OperatorContext, path: SplitResult, session: Session, body: None, scope: str | None
    ) -> None:
        actor = session[1]["principal_id"]
        admin_view = session[1]["role"] in ("registry_admin", "read_only_operator")
        models = self._registry.list_models()
        if not admin_view:
            models = [
                model
                for model in models
                if self._registry.explain(
                    actor, model["configuration_ref"], "execution", self.application.task_class
                )["allowed"]
            ]
        return self._send(
            200,
            {
                "items": [
                    {
                        **model,
                        "readiness": self._registry.readiness(model),
                        "current_price": (
                            cast(
                                list[Record | None],
                                self._registry.prices(model["configuration_ref"]),
                            )
                            or [None]
                        )[-1],
                    }
                    for model in models
                ]
            },
        )

    def get_registry_model(
        self: OperatorContext, path: SplitResult, session: Session, body: None, scope: str | None
    ) -> None:
        actor = session[1]["principal_id"]
        admin_view = session[1]["role"] in ("registry_admin", "read_only_operator")
        ref = path.path[len("/operator/v1/models/") :]
        if "/" in ref:
            raise ValueError("invalid model path")
        model = self._registry.model(ref)
        if not model:
            return self._fail(404, "NOT_FOUND")
        if not admin_view and (
            not self._registry.explain(actor, ref, "execution", self.application.task_class)[
                "allowed"
            ]
        ):
            return self._fail(404, "NOT_FOUND")
        grants = []
        if admin_view:
            grants = self._registry.grants(configuration_ref=ref)
        return self._send(
            200,
            {
                "model": model,
                "readiness": self._registry.readiness(model),
                "prices": self._registry.prices(ref),
                "grants": [grant for grant in grants if grant],
                "history": self._registry.history(ref) if admin_view else [],
            },
        )

    def get_registry_principals(
        self: OperatorContext, path: SplitResult, session: Session, body: None, scope: str | None
    ) -> None:
        actor = session[1]["principal_id"]
        admin_view = session[1]["role"] in ("registry_admin", "read_only_operator")
        principals = (
            self._registry.list_principals()
            if admin_view
            else [cast(Record, self._registry.principal(actor))]
        )
        models = {model["configuration_ref"]: model for model in self._registry.list_models()}
        grants_by_principal: dict[str, list[Record]] = {}
        for grant in self._registry.grants(principal_id=None if admin_view else actor):
            if grant["configuration_ref"] in models:
                grants_by_principal.setdefault(grant["principal_id"], []).append(grant)
        items = []
        for principal in principals:
            grants = grants_by_principal.get(principal["principal_id"], [])
            items.append(
                {
                    **principal,
                    "grant_summary": [
                        {
                            **grant,
                            "display_name": models[grant["configuration_ref"]]["display_name"],
                            "readiness": self._registry.readiness(
                                models[grant["configuration_ref"]]
                            ),
                        }
                        for grant in grants
                        if grant
                    ],
                }
            )
        return self._send(200, {"items": items})

    def get_registry_principal(
        self: OperatorContext, path: SplitResult, session: Session, body: None, scope: str | None
    ) -> None:
        actor = session[1]["principal_id"]
        admin_view = session[1]["role"] in ("registry_admin", "read_only_operator")
        principal_id = path.path[len("/operator/v1/principals/") :]
        if "/" in principal_id:
            raise ValueError("invalid principal path")
        if not admin_view and principal_id != actor:
            return self._fail(404, "NOT_FOUND")
        principal = self._registry.principal(principal_id)
        if not principal:
            return self._fail(404, "NOT_FOUND")
        models = {model["configuration_ref"]: model for model in self._registry.list_models()}
        grants = [
            grant
            for grant in self._registry.grants(principal_id=principal_id)
            if grant["configuration_ref"] in models
        ]
        return self._send(
            200,
            {
                "principal": principal,
                "grants": [
                    {
                        **grant,
                        "display_name": models[grant["configuration_ref"]]["display_name"],
                        "readiness": self._registry.readiness(models[grant["configuration_ref"]]),
                    }
                    for grant in grants
                    if grant
                ],
                "history": self._registry.history(principal_id) if admin_view else [],
            },
        )

    def get_registry_explanation(
        self: OperatorContext, path: SplitResult, session: Session, body: None, scope: str | None
    ) -> None:
        actor = session[1]["principal_id"]
        admin_view = session[1]["role"] in ("registry_admin", "read_only_operator")
        query = parse_qs(path.query, strict_parsing=True, keep_blank_values=True)
        if set(query) != {"principal_id", "configuration_ref", "purpose", "task_class"} or any(
            (len(values) != 1 for values in query.values())
        ):
            raise ValueError("invalid explain query")
        principal_id = query["principal_id"][0]
        if not admin_view and principal_id != actor:
            return self._fail(404, "NOT_FOUND")
        return self._send(
            200,
            self._registry.explain(
                principal_id,
                query["configuration_ref"][0],
                query["purpose"][0],
                query["task_class"][0],
            ),
        )

    def post_operator_v1_registry(
        self: OperatorContext, path: None, session: Session, body: Record, scope: str | None
    ) -> None:
        if session[1]["role"] != "registry_admin":
            return self._fail(403, "ADMIN_REQUIRED")
        try:
            return self._send(200, self._registry.mutate(session[1]["principal_id"], body))
        except UserError as exc:
            return self._fail(exc.status, exc.code)
        except RegistryConflict:
            return self._fail(409, "REGISTRY_CONFLICT")
        except RequestError as exc:
            return self._fail(exc.status, exc.code)
        except ValueError:
            return self._fail(400, "INVALID_REGISTRY_CHANGE")
        except PermissionError:
            return self._fail(403, "ADMIN_REQUIRED")
        except Exception:
            log_failure("operator_http.registry_routes.post_operator_v1_registry.failed")
            return self._fail(503, "REGISTRY_UNAVAILABLE")

    def post_operator_v1_personal_campaign(
        self: OperatorContext, path: None, session: Session, body: Record, scope: str | None
    ) -> None:
        if session[1]["principal_id"] != self.application.owner_id or not getattr(
            self.application.registry, "personal_campaign", None
        ):
            return self._fail(403, "OWNER_REQUIRED")
        try:
            if set(body) == {"action", "configuration"} and body["action"] == "configure":
                result = self._campaign.configure(self.application.owner_id, body["configuration"])
            elif set(body) == {"action"} and body["action"] in ("active", "paused", "closed"):
                result = self._campaign.transition(self.application.owner_id, body["action"])
            elif set(body) == {"action"} and body["action"] == "reconcile":
                result = {
                    "reconciled_attempts": self._campaign.reconcile_recorded_usage(
                        self.application.owner_id
                    )
                }
            elif set(body) == {"action"} and body["action"] == "revalidate":
                result = self._campaign.revalidate(self.application.owner_id)
            elif body.get("action") == "acknowledge_exposure" and set(body) == {
                "action",
                "campaign_id",
                "attempt_id",
                "expected_revision",
                "reason",
            }:
                result = self._campaign.acknowledge_exposure(
                    self.application.owner_id,
                    {key: value for key, value in body.items() if key != "action"},
                )
            else:
                return self._fail(400, "INVALID_CAMPAIGN")
            return self._send(200, result)
        except RequestError as exc:
            return self._fail(exc.status, exc.code)
        except ValueError:
            return self._fail(409, "CAMPAIGN_NOT_ELIGIBLE")
        except PermissionError:
            return self._fail(403, "OWNER_REQUIRED")
        except Exception:
            log_failure("operator_http.registry_routes.post_operator_v1_personal_campaign.failed")
            return self._fail(503, "CAMPAIGN_UNAVAILABLE")

    def post_operator_v1_provider_credential(
        self: OperatorContext, path: None, session: Session, body: Record, scope: str | None
    ) -> None:
        if session[1]["role"] != "registry_admin":
            return self._fail(403, "ADMIN_REQUIRED")
        if set(body) != {
            "operation_id",
            "connection_id",
            "expected_revision",
            "mode",
            "secret",
        }:
            return self._fail(400, "INVALID_BODY")
        try:
            return self._send(
                200,
                self._registry.set_provider_credential(
                    session[1]["principal_id"],
                    body["connection_id"],
                    body["expected_revision"],
                    body["operation_id"],
                    body["mode"],
                    body["secret"],
                ),
            )
        except RegistryConflict:
            return self._fail(409, "REGISTRY_CONFLICT")
        except RequestError as exc:
            return self._fail(exc.status, exc.code)
        except ValueError:
            return self._fail(400, "INVALID_CREDENTIAL_CHANGE")
        except PermissionError:
            return self._fail(403, "ADMIN_REQUIRED")
        except Exception:
            log_failure("operator_http.registry_routes.post_operator_v1_provider_credential.failed")
            return self._fail(503, "CREDENTIAL_UNAVAILABLE")

    def post_operator_v1_provider_probe(
        self: OperatorContext, path: None, session: Session, body: Record, scope: str | None
    ) -> None:
        if session[1]["role"] != "registry_admin":
            return self._fail(403, "ADMIN_REQUIRED")
        if set(body) != {"operation_id", "connection_id", "expected_revision", "operation"}:
            return self._fail(400, "INVALID_BODY")
        try:
            return self._send(
                200,
                self._registry.probe_connection(
                    session[1]["principal_id"],
                    body["connection_id"],
                    body["expected_revision"],
                    body["operation_id"],
                    body["operation"],
                ),
            )
        except RegistryConflict:
            return self._fail(409, "REGISTRY_CONFLICT")
        except RequestError as exc:
            return self._fail(exc.status, exc.code)
        except ValueError:
            return self._fail(400, "INVALID_PROBE")
        except PermissionError:
            return self._fail(403, "ADMIN_REQUIRED")
        except Exception:
            log_failure("operator_http.registry_routes.post_operator_v1_provider_probe.failed")
            return self._fail(503, "PROBE_UNAVAILABLE")

    def post_operator_v1_provider_validation(
        self: OperatorContext, path: None, session: Session, body: Record, scope: str | None
    ) -> None:
        if session[1]["role"] != "registry_admin":
            return self._fail(403, "ADMIN_REQUIRED")
        if (
            not self.application.provider_validation
            or not self._registry.provider_execution_ready
            or set(body)
            != {
                "operation_id",
                "connection_id",
                "connection_revision",
                "configuration_ref",
                "configuration_revision",
                "max_output_tokens",
                "acknowledge_external_send",
            }
            or (body["acknowledge_external_send"] is not True)
            or (type(body["max_output_tokens"]) is not int)
            or (not 1 <= body["max_output_tokens"] <= 32)
            or (type(body["connection_revision"]) is not int)
            or (type(body["configuration_revision"]) is not int)
        ):
            return self._fail(400, "INVALID_VALIDATION_REQUEST")
        try:
            previous = self.application.projection.provider_validation(body["operation_id"])
            if previous:
                if any(
                    (
                        previous[key] != body[key]
                        for key in (
                            "connection_id",
                            "connection_revision",
                            "configuration_ref",
                            "configuration_revision",
                            "max_output_tokens",
                        )
                    )
                ):
                    return self._fail(409, "VALIDATION_OPERATION_CONFLICT")
                return self._send(200, previous)
            connection = self._registry.connection(body["connection_id"])
            model = self._registry.model(body["configuration_ref"])
            campaign = self._registry.personal_campaign
            allowance = campaign.summary() if campaign else None
            if _provider_validation_denied(
                allowance, body, campaign, connection, model, self, session
            ):
                return self._fail(409, "VALIDATION_NOT_ELIGIBLE")
            fresh = self.application.projection.begin_provider_validation(
                body["operation_id"],
                body["connection_id"],
                body["connection_revision"],
                body["configuration_ref"],
                body["configuration_revision"],
                body["max_output_tokens"],
            )
            if not fresh:
                return self._send(
                    200, self.application.projection.provider_validation(body["operation_id"])
                )
        except RequestError as exc:
            return self._fail(exc.status, exc.code)
        except ValueError:
            return self._fail(409, "VALIDATION_OPERATION_CONFLICT")
        except Exception:
            log_failure("operator_http.provider_validation.prepare.failed")
            return self._fail(503, "VALIDATION_UNAVAILABLE")
        live_candidate = _execute_provider_validation(body, self, session)
        response = self.application.projection.provider_validation(body["operation_id"])
        if live_candidate is not None:
            response = {**cast(Record, response), "live_candidate": live_candidate}
            if response.get("submission_id"):
                response["provider_model_reported"] = cast(
                    Record, self.application.projection.detail(response["submission_id"], "*")
                ).get("provider_model_reported")
        return self._send(200, response)

    def post_operator_v1_provision(
        self: OperatorContext, path: None, session: Session, body: Record, scope: str | None
    ) -> None:
        if session[1]["role"] != "registry_admin":
            return self._fail(403, "ADMIN_REQUIRED")
        if set(body) != {"operation_id", "principal_id", "expected_revision"}:
            return self._fail(400, "INVALID_BODY")
        try:
            record, secret = self._registry.provision_credential(
                session[1]["principal_id"],
                body["principal_id"],
                body["expected_revision"],
                body["operation_id"],
            )
            return self._send(200, {"record": record, "one_time_credential": secret})
        except RegistryConflict:
            return self._fail(409, "REGISTRY_CONFLICT")
        except RequestError as exc:
            return self._fail(exc.status, exc.code)
        except ValueError:
            return self._fail(400, "INVALID_REGISTRY_CHANGE")
        except Exception:
            log_failure("operator_http.registry_routes.post_operator_v1_provision.failed")
            return self._fail(503, "REGISTRY_UNAVAILABLE")


def _execute_provider_validation(
    body: Record, self: OperatorContext, session: Session
) -> Record | None:
    live_candidate = None
    try:
        result = self._validation.run(
            body["configuration_ref"],
            body["operation_id"],
            body["max_output_tokens"],
            lambda sid: self.application.projection.record_provider_validation_submission(
                body["operation_id"], sid
            ),
            **{"token": session[1]["wire_token"]} if session[1].get("wire_token") else {},
        )
        state = result["state"] if type(result) is dict else result
        self.application.projection.finish_provider_validation(
            body["operation_id"], cast(str, state)
        )
        live_candidate = result.get("candidate") if type(result) is dict else None
    except Exception as exc:
        log_failure("operator_http.provider_validation.execute.failed")
        handle = getattr(exc, "handle", None)
        if type(handle) is dict and type(handle.get("submission_id")) is str:
            self.application.projection.record_provider_validation_submission(
                body["operation_id"], handle["submission_id"]
            )
        code = getattr(exc, "code", None)
        state = (
            "failed"
            if code and getattr(exc, "retry_guidance", None) == "never"
            else "outcome_unknown"
        )
        self.application.projection.finish_provider_validation(
            body["operation_id"],
            state,
            code if type(code) is str else "VALIDATION_UNAVAILABLE",
        )
    return live_candidate


def _provider_validation_denied(
    allowance: Record | None,
    body: Record,
    campaign: PersonalCampaign | None,
    connection: Record | None,
    model: Record | None,
    self: OperatorContext,
    session: Session,
) -> bool:
    return (
        not connection
        or not model
        or connection["revision"] != body["connection_revision"]
        or (model["revision"] != body["configuration_revision"])
        or (model["destination"].get("connection_id") != body["connection_id"])
        or (model["destination"].get("adapter_id") != "openai.responses.v1")
        or (
            campaign
            and (
                cast(Record, allowance)["effective_state"] != "active"
                or cast(Record, allowance)["connection_id"] != body["connection_id"]
                or cast(Record, allowance)["configuration_ref"] != body["configuration_ref"]
                or (cast(Record, allowance)["principal_id"] != session[1]["principal_id"])
                or (body["max_output_tokens"] > cast(Record, allowance)["max_output_tokens"])
            )
        )
        or (
            not self._registry.explain(
                session[1]["principal_id"]
                if self._registry.personal_campaign
                else self._validation.principal_id,
                body["configuration_ref"],
                "execution",
                self.application.task_class,
            )["allowed"]
        )
    )
