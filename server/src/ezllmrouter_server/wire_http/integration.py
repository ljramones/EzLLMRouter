"""Integration routes resolve once, then validate their own selectors."""

import re
from ..records import Record
from urllib.parse import parse_qs, urlsplit
from ..canonical import ContractError, strict_loads
from ..integration_accounting import IntegrationError, route_id
from .exports import usage_csv
from .transport import WireTransport


class IntegrationRoutes(WireTransport):
    def _integration_get(self) -> None:
        try:
            principal = self._integration_auth()
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query, strict_parsing=True, keep_blank_values=True)
            if any((len(values) != 1 for values in query.values())) or parsed.fragment:
                raise IntegrationError("SCHEMA_INVALID")
            base = "/integration/v" + self.integration_version
            suffix = parsed.path[len(base) :]
            for versions, pattern, action in READ_ROUTES:
                if self.integration_version in versions and re.fullmatch(pattern, suffix):
                    return action(self, principal, query, parsed.path)
            raise IntegrationError("NOT_FOUND_OR_FORBIDDEN", 404)
        except Exception as exc:
            self._log_error("wire_http.integration_get", exc)
            self._integration_error(exc)

    def _credential_bindings(
        self, principal: Record, query: dict[str, list[str]], path: str
    ) -> None:
        if set(query) != {"dataset_id"} or not getattr(
            self.application.coordinator.registry, "integration_credentials", None
        ):
            raise IntegrationError("SCHEMA_INVALID")
        return self._integration_reply(
            200,
            self.application.coordinator.registry.integration_credentials.list_for(
                principal, query["dataset_id"][0]
            ),
        )

    def _credential_resolve(
        self, principal: Record, query: dict[str, list[str]], path: str
    ) -> None:
        expected = {"dataset_id", "purpose", "operation_family"}
        if query.get("operation_family") == ["generation"]:
            expected.add("model_id")
        if set(query) != expected or not getattr(
            self.application.coordinator.registry, "integration_credentials", None
        ):
            raise IntegrationError("SCHEMA_INVALID")
        account_id = route_id(path.split("/")[-2])
        result = self.application.coordinator.registry.integration_credentials.resolve_for(
            principal,
            query["dataset_id"][0],
            account_id,
            query.get("model_id", [None])[0],
            query["operation_family"][0],
            query["purpose"][0],
        )
        return self._integration_reply(200, {"integration_version": "3", **result})

    def _eligibility(self, principal: Record, query: dict[str, list[str]], path: str) -> None:
        ledger = self.application.coordinator.registry.integration
        if self.integration_version == "3":
            selector = query.get("selection_kind", [None])[0]
            expected = {"dataset_id", "operation_family", "capability", "selection_kind"}
            if selector == "known_model":
                expected.add("model_id")
        else:
            expected = {"dataset_id", "model_id"}
        if set(query) != expected:
            raise IntegrationError("SCHEMA_INVALID")
        account_id = route_id(path.split("/")[-2])
        return self._integration_reply(
            200,
            ledger.eligibility(
                principal,
                query["dataset_id"][0],
                account_id,
                query.get("model_id", [None])[0],
                self.integration_version,
                query.get("operation_family", [None])[0],
                query.get("capability", [None])[0],
                query.get("selection_kind", [None])[0],
            ),
        )

    def _receipt(self, principal: Record, query: dict[str, list[str]], path: str) -> None:
        ledger = self.application.coordinator.registry.integration
        if set(query) != {"dataset_id"}:
            raise IntegrationError("SCHEMA_INVALID")
        return self._integration_reply(
            200, ledger.receipt(principal, query["dataset_id"][0], route_id(path.split("/")[-2]))
        )

    def _snapshot(self, principal: Record, query: dict[str, list[str]], path: str) -> None:
        ledger = self.application.coordinator.registry.integration
        if set(query) != {"dataset_id"}:
            raise IntegrationError("SCHEMA_INVALID")
        return self._integration_reply(
            200,
            ledger.snapshot(
                principal,
                query["dataset_id"][0],
                route_id(path.split("/")[-1]),
                self.integration_version,
            ),
        )

    def _dataset_export(self, principal: Record, query: dict[str, list[str]], path: str) -> None:
        ledger = self.application.coordinator.registry.integration
        if set(query) != {"dataset_id"}:
            raise IntegrationError("SCHEMA_INVALID")
        return self._integration_reply(
            200, ledger.dataset_export(principal, query["dataset_id"][0], self.integration_version)
        )

    def _usage_report(self, principal: Record, query: dict[str, list[str]], path: str) -> None:
        ledger = self.application.coordinator.registry.integration
        if "dataset_id" not in query or set(query) - {
            "dataset_id",
            "export",
            "actor_id",
            "provider_account_id",
            "task_id",
            "from",
            "to",
        }:
            raise IntegrationError("SCHEMA_INVALID")
        dataset_id = query.pop("dataset_id")[0]
        export = query.pop("export", [None])[0]
        report = ledger.report(
            principal,
            dataset_id,
            {key: value[0] for key, value in query.items()},
            version=self.integration_version,
        )
        if export is None:
            return self._integration_reply(200, report)
        if export != "csv":
            raise IntegrationError("SCHEMA_INVALID")
        return self._integration_reply(
            200, None, csv_body=usage_csv(self.integration_version, report["attempts"])
        )

    def _integration_post(self) -> None:
        try:
            principal = self._integration_auth()
            parsed = urlsplit(self.path)
            if parsed.query or parsed.fragment:
                raise IntegrationError("SCHEMA_INVALID")
            try:
                body = strict_loads(self._json_bytes(65536, integration=True))
            except ContractError as exc:
                raise IntegrationError(exc.code, exc.status) from exc
            if type(body) is not dict:
                raise IntegrationError("SCHEMA_INVALID")
            ledger = self.application.coordinator.registry.integration
            base = "/integration/v" + self.integration_version
            if parsed.path == base + "/datasets":
                status, reply = ledger.create_dataset(principal, body, self.integration_version)
            elif parsed.path == base + "/accounts":
                status, reply = ledger.create_account(principal, body, self.integration_version)
            elif parsed.path == base + "/events":
                status, reply = ledger.append_event(principal, body, self.integration_version)
            elif self.integration_version in ("2", "3") and parsed.path == base + "/snapshots":
                if body.get("integration_version") != self.integration_version:
                    raise IntegrationError("UNSUPPORTED_VERSION", 426)
                status, reply = ledger.append_snapshot(principal, body)
            elif self.integration_version == "3" and re.fullmatch(
                re.escape(base) + "/accounts/[^/]+/permissions", parsed.path
            ):
                status, reply = ledger.set_account_permissions(
                    principal, route_id(parsed.path.split("/")[-2]), body
                )
            elif re.fullmatch(re.escape(base) + "/accounts/[^/]+/state", parsed.path):
                status, reply = ledger.set_account_state(
                    principal, route_id(parsed.path.split("/")[-2]), body, self.integration_version
                )
            else:
                raise IntegrationError("NOT_FOUND_OR_FORBIDDEN", 404)
            self._integration_reply(status, reply)
        except Exception as exc:
            self._log_error("web.serve.Handler._integration_post", exc)
            self._integration_error(exc)


READ_ROUTES = (
    (("3",), "/credentials/bindings", IntegrationRoutes._credential_bindings),
    (("3",), "/credentials/[^/]+/resolve", IntegrationRoutes._credential_resolve),
    (("1", "2", "3"), "/accounts/[^/]+/eligibility", IntegrationRoutes._eligibility),
    (("1", "2", "3"), "/events/[^/]+/receipt", IntegrationRoutes._receipt),
    (("2", "3"), "/snapshots/[^/]+", IntegrationRoutes._snapshot),
    (("2", "3"), "/reports/dataset", IntegrationRoutes._dataset_export),
    (("1", "2", "3"), "/reports/usage", IntegrationRoutes._usage_report),
)
