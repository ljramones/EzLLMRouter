"""Work API dispatch after version selection and authentication."""

import re
from urllib.parse import unquote, urlsplit
from ..canonical import ContractError, SAFE, ident, strict_loads
from ..identifiers import valid_identifier
from ..integration_accounting import IntegrationError
from .integration import IntegrationRoutes


class WireHandler(IntegrationRoutes):
    def do_GET(self) -> None:
        if re.match("^/integration/v[123]/", urlsplit(self.path).path):
            return self._integration_get()
        if self.application.integration_only:
            return self._integration_error(IntegrationError("NOT_FOUND_OR_FORBIDDEN", 404))
        try:
            trusted = self._context()
            path = self._path()
            if self.selected_version == "0.3" and (
                self.headers.get("Content-Length") not in (None, "0")
                or self.headers.get("Transfer-Encoding")
            ):
                raise ContractError("SCHEMA_INVALID", 400)
            if path == "/v1/capabilities":
                self._reply(200, self.work_service.capabilities(trusted))
            elif (
                self.selected_version == "0.2"
                and self.application.coordinator.registry
                and re.fullmatch("/v1/attribution-runs/[A-Za-z0-9._:-]+", path)
            ):
                run = self.application.coordinator.registry.attribution.run(path.rsplit("/", 1)[1])
                if not run or run["principal_id"] != trusted["principal_id"]:
                    raise ContractError("NOT_FOUND_OR_FORBIDDEN", 404)
                self._reply(
                    200, {"contract_version": "0.2", "attribution_version": "1", "run": run}
                )
            elif (
                self.selected_version == "0.2"
                and self.application.coordinator.registry
                and re.fullmatch("/v1/outcomes/[A-Za-z0-9._:-]+", path)
            ):
                receipt = self.application.coordinator.registry.attribution.outcome_receipt(
                    trusted, path.rsplit("/", 1)[1]
                )
                self._reply(
                    200, {"contract_version": "0.2", "outcome_version": "1", "receipt": receipt}
                )
            elif path.startswith("/v1/submissions/by-work/"):
                parts = [unquote(x) for x in path[len("/v1/submissions/by-work/") :].split("/")]
                if (
                    len(parts) != 4
                    or not re.fullmatch("[1-9][0-9]*", parts[2])
                    or int(parts[2]) > SAFE
                ):
                    raise ContractError("SCHEMA_INVALID", 400)
                for part in (parts[0], parts[1], parts[3]):
                    ident(part)
                key = {
                    "principal_id": trusted["principal_id"],
                    "task_id": parts[0],
                    "step_id": parts[1],
                    "step_revision": int(parts[2]),
                    "execution_generation": parts[3],
                }
                self._reply(200, self.work_service.status_by_work(key, trusted))
            elif re.fullmatch("/v1/submissions/[A-Za-z0-9._:-]+", path):
                self._reply(200, self.work_service.status(path.rsplit("/", 1)[1], trusted))
            else:
                raise ContractError("NOT_FOUND_OR_FORBIDDEN", 404)
        except Exception as exc:
            self._log_error("web.serve.Handler.do_GET", exc)
            self._error(exc)

    def do_POST(self) -> None:
        if re.match("^/integration/v[123]/", urlsplit(self.path).path):
            return self._integration_post()
        if self.application.integration_only:
            return self._integration_error(IntegrationError("NOT_FOUND_OR_FORBIDDEN", 404))
        try:
            trusted = self._context()
            path = self._path()
            if self.selected_version == "0.3" and path != "/v1/submissions":
                raise ContractError("NOT_FOUND_OR_FORBIDDEN", 404)
            if path not in ("/v1/submissions", "/v1/attribution-runs", "/v1/outcomes") or (
                path != "/v1/submissions" and (not self.application.coordinator.registry)
            ):
                raise ContractError("NOT_FOUND_OR_FORBIDDEN", 404)
            waits = self.headers.get_all("EzLLMRouter-Wait-Ms")
            if waits:
                if (
                    len(waits) != 1
                    or not re.fullmatch("(?:0|[1-9][0-9]*)", waits[0])
                    or int(waits[0]) > 30000
                ):
                    raise ContractError("SCHEMA_INVALID", 400)
                wait = int(waits[0])
            else:
                wait = 1000
            max_bytes = 262144 if self.selected_version == "0.3" else 65536
            data = self._json_bytes(max_bytes)
            if self.selected_version == "0.3":
                from ..successor_contract import strict_decode

                request = strict_decode(data)
                if type(request) is not dict or request.get("contract_version") != "0.3":
                    raise ContractError("UNSUPPORTED_VERSION", 426)
                status, reply = self.work_service.submit(
                    request, trusted, wait, credential=self.headers["Authorization"][7:]
                )
                return self._reply(status, reply)
            request = strict_loads(data)
            if path == "/v1/attribution-runs":
                run = self.application.coordinator.registry.attribution.start_run(trusted, request)
                return self._reply(
                    200, {"contract_version": "0.2", "attribution_version": "1", "run": run}
                )
            if path == "/v1/outcomes":
                receipt = self.application.coordinator.registry.attribution.append_outcome(
                    trusted, request
                )
                return self._reply(
                    201, {"contract_version": "0.2", "outcome_version": "1", "receipt": receipt}
                )
            run_headers = self.headers.get_all("EzLLMRouter-Attribution-Run")
            versions = self.headers.get_all("EzLLMRouter-Attribution-Version", [])
            if bool(run_headers) != bool(versions) or (
                run_headers
                and (
                    len(run_headers) != 1
                    or len(versions) != 1
                    or versions[0] != "1"
                    or (not valid_identifier(run_headers[0]))
                )
            ):
                raise ContractError("SCHEMA_INVALID", 400)
            status, reply = self.application.coordinator.submit(
                request,
                trusted,
                wait,
                credential=self.headers["Authorization"][7:],
                run_id=run_headers[0] if run_headers else None,
            )
            self._reply(status, reply)
        except Exception as exc:
            self._log_error("web.serve.Handler.do_POST", exc)
            self._error(exc)
