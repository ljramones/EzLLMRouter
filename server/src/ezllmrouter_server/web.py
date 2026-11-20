"""Version-selected HTTP boundary; coordinator and successor are injected."""

from __future__ import annotations

from .observability import log_failure

from .http_server import BoundedHTTPServer as ThreadingHTTPServer, SafeHTTPRequestHandler
import json
import re
from urllib.parse import parse_qs, unquote, urlsplit
import uuid

from .canonical import ContractError, SAFE, ident, strict_loads
from .identifiers import valid_identifier
from .integration_accounting import IntegrationError, route_id


def serve(host: str, port: int, coordinator, *, integration_only=False):
    class Handler(SafeHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, _format, *_args):
            return  # Never log token, prompt, response body, or query.

        def _reply(self, status, value):
            body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("EzLLMRouter-Contract-Version", value.get("contract_version", "0.2"))
            if self.close_connection:
                self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def _error(self, exc):
            if isinstance(exc, ContractError):
                code, status = exc.code, exc.status
            else:
                code, status = "INTERNAL_UNAVAILABLE", 503
            if status == 401 and code == "AUTHENTICATION_FAILED":
                # Authentication runs before POST body consumption. Close the
                # connection so unread rejected bytes cannot become a later
                # HTTP request on a persistent connection.
                self.close_connection = True
            if getattr(self, "selected_version", "0.2") == "0.3":
                # Authentication is evaluated before any selected operation.
                # Preserve the 401 transport status while projecting the
                # exact successor public error vocabulary.
                if status == 401 and code == "AUTHENTICATION_FAILED":
                    code = "POLICY_DENIED"
                if code not in {
                    "UNSUPPORTED_VERSION",
                    "MALFORMED_JSON",
                    "SCHEMA_INVALID",
                    "LIMIT_EXCEEDED",
                    "SEMANTIC_INVALID",
                    "CAPABILITY_UNSUPPORTED",
                    "WORK_CONFLICT",
                    "WORK_VERSION_CONFLICT",
                    "NOT_FOUND_OR_FORBIDDEN",
                    "POLICY_DENIED",
                    "FINANCIAL_AUTH_REQUIRED",
                    "PLAN_INVALID_OR_STALE",
                    "FDC_REJECTED",
                    "INTENT_PERSIST_FAILED",
                    "RESULT_INVALID",
                    "USAGE_UNKNOWN",
                }:
                    code = "INTENT_PERSIST_FAILED"
                self._reply(
                    status,
                    {
                        "contract_version": "0.3",
                        "code": code,
                        "correlation_id": "error." + uuid.uuid4().hex,
                        "retry_guidance": getattr(
                            exc, "retry_guidance", "query_first" if status >= 500 else "never"
                        ),
                    },
                )
            else:
                from .core import public_error

                # The internal shared-work reason is specific, while wire 0.2
                # keeps its immutable strict public error vocabulary.
                if code == "WORK_VERSION_CONFLICT":
                    code = "WORK_CONFLICT"
                self._reply(
                    status,
                    {
                        "contract_version": "0.2",
                        "error": public_error(code, "query_first" if status >= 500 else "never"),
                    },
                )

        def _context(self):
            versions = self.headers.get_all("EzLLMRouter-Contract-Version")
            self.selected_version = versions[0] if versions and len(versions) == 1 else "0.2"
            if versions not in (["0.2"], ["0.3"]) or (
                versions == ["0.3"] and getattr(coordinator, "successor", None) is None
            ):
                raise ContractError("UNSUPPORTED_VERSION", 426)
            auth = self.headers.get_all("Authorization")
            if not auth or len(auth) != 1 or not auth[0].startswith("Bearer "):
                raise ContractError("AUTHENTICATION_FAILED", 401)
            return coordinator.authenticate(auth[0][7:])

        def _path(self):
            parsed = urlsplit(self.path)
            if parsed.query or parsed.fragment:
                raise ContractError("SCHEMA_INVALID", 400)
            return parsed.path

        def _integration_reply(self, status, value, *, csv_body=None):
            body = (
                csv_body.encode("utf-8")
                if csv_body is not None
                else json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            )
            self.send_response(status)
            self.send_header(
                "Content-Type",
                "text/csv; charset=utf-8"
                if csv_body is not None
                else "application/json; charset=utf-8",
            )
            self.send_header("Content-Length", str(len(body)))
            self.send_header(
                "EzLLMRouter-Integration-Version", getattr(self, "integration_version", "1")
            )
            self.send_header("Cache-Control", "no-store, max-age=0")
            if self.close_connection:
                self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def _integration_auth(self):
            match = re.match(r"^/integration/v([123])/", urlsplit(self.path).path)
            self.integration_version = match[1] if match else "1"
            if (
                self.headers.get_all("EzLLMRouter-Integration-Version")
                != [self.integration_version]
                or not coordinator.registry
            ):
                raise IntegrationError("UNSUPPORTED_VERSION", 426)
            auth = self.headers.get_all("Authorization")
            if not auth or len(auth) != 1 or not auth[0].startswith("Bearer "):
                raise IntegrationError("AUTHENTICATION_FAILED", 401)
            try:
                return coordinator.registry.credential_principal(auth[0][7:])
            except ContractError as exc:
                raise IntegrationError("AUTHENTICATION_FAILED", 401) from exc

        def _integration_error(self, exc):
            if isinstance(exc, IntegrationError):
                status, code, guidance = exc.status, exc.code, exc.retry_guidance
            else:
                status, code, guidance = 503, "INTERNAL_UNAVAILABLE", "query_first"
            if status == 401:
                self.close_connection = True
            self._integration_reply(
                status,
                {
                    "integration_version": getattr(self, "integration_version", "1"),
                    "error": {"code": code, "retry_guidance": guidance},
                },
            )

        def _integration_get(self):
            try:
                principal = self._integration_auth()
                parsed = urlsplit(self.path)
                query = parse_qs(parsed.query, strict_parsing=True, keep_blank_values=True)
                if any(len(values) != 1 for values in query.values()) or parsed.fragment:
                    raise IntegrationError("SCHEMA_INVALID")
                ledger = coordinator.registry.integration
                path = parsed.path
                base = "/integration/v" + self.integration_version
                if self.integration_version == "3" and path == base + "/credentials/bindings":
                    if set(query) != {"dataset_id"} or not getattr(
                        coordinator.registry, "integration_credentials", None
                    ):
                        raise IntegrationError("SCHEMA_INVALID")
                    return self._integration_reply(
                        200,
                        coordinator.registry.integration_credentials.list_for(
                            principal, query["dataset_id"][0]
                        ),
                    )
                if self.integration_version == "3" and re.fullmatch(
                    re.escape(base) + r"/credentials/[^/]+/resolve", path
                ):
                    expected = {"dataset_id", "purpose", "operation_family"}
                    if query.get("operation_family") == ["generation"]:
                        expected.add("model_id")
                    if set(query) != expected or not getattr(
                        coordinator.registry, "integration_credentials", None
                    ):
                        raise IntegrationError("SCHEMA_INVALID")
                    account_id = route_id(path.split("/")[-2])
                    result = coordinator.registry.integration_credentials.resolve_for(
                        principal,
                        query["dataset_id"][0],
                        account_id,
                        query.get("model_id", [None])[0],
                        query["operation_family"][0],
                        query["purpose"][0],
                    )
                    return self._integration_reply(200, {"integration_version": "3", **result})
                if re.fullmatch(re.escape(base) + r"/accounts/[^/]+/eligibility", path):
                    if self.integration_version == "3":
                        selector = query.get("selection_kind", [None])[0]
                        expected = {
                            "dataset_id",
                            "operation_family",
                            "capability",
                            "selection_kind",
                        }
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
                if re.fullmatch(re.escape(base) + r"/events/[^/]+/receipt", path):
                    if set(query) != {"dataset_id"}:
                        raise IntegrationError("SCHEMA_INVALID")
                    return self._integration_reply(
                        200,
                        ledger.receipt(
                            principal, query["dataset_id"][0], route_id(path.split("/")[-2])
                        ),
                    )
                if self.integration_version in ("2", "3") and re.fullmatch(
                    re.escape(base) + r"/snapshots/[^/]+", path
                ):
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
                if self.integration_version in ("2", "3") and path == base + "/reports/dataset":
                    if set(query) != {"dataset_id"}:
                        raise IntegrationError("SCHEMA_INVALID")
                    return self._integration_reply(
                        200,
                        ledger.dataset_export(
                            principal, query["dataset_id"][0], self.integration_version
                        ),
                    )
                if path == base + "/reports/usage":
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
                    import csv
                    import io

                    out = io.StringIO()
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
                    )
                    if self.integration_version in ("2", "3"):
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
                    writer = csv.DictWriter(out, columns, extrasaction="ignore")
                    writer.writeheader()
                    writer.writerows(
                        {
                            **row,
                            **{
                                key: json.dumps(row[key], sort_keys=True)
                                if row.get(key) is not None
                                else ""
                                for key in ("native_units", "eligibility_record", "selected_action")
                            },
                        }
                        for row in report["attempts"]
                    )
                    return self._integration_reply(200, None, csv_body=out.getvalue())
                raise IntegrationError("NOT_FOUND_OR_FORBIDDEN", 404)
            except Exception as exc:
                log_failure("web.serve.Handler._integration_get.failed")
                self._integration_error(exc)

        def _integration_post(self):
            try:
                principal = self._integration_auth()
                parsed = urlsplit(self.path)
                if parsed.query or parsed.fragment:
                    raise IntegrationError("SCHEMA_INVALID")
                lengths = self.headers.get_all("Content-Length")
                if (
                    self.headers.get_all("Content-Type") != ["application/json"]
                    or len(lengths or []) != 1
                    or not lengths[0].isdigit()
                    or int(lengths[0]) > 65536
                    or self.headers.get("Transfer-Encoding")
                ):
                    raise IntegrationError("LIMIT_EXCEEDED", 413)
                from .canonical import strict_loads

                try:
                    body = strict_loads(self.read_body(int(lengths[0])))
                except ContractError as exc:
                    raise IntegrationError(exc.code, exc.status) from exc
                ledger = coordinator.registry.integration
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
                    re.escape(base) + r"/accounts/[^/]+/permissions", parsed.path
                ):
                    status, reply = ledger.set_account_permissions(
                        principal, route_id(parsed.path.split("/")[-2]), body
                    )
                elif re.fullmatch(re.escape(base) + r"/accounts/[^/]+/state", parsed.path):
                    status, reply = ledger.set_account_state(
                        principal,
                        route_id(parsed.path.split("/")[-2]),
                        body,
                        self.integration_version,
                    )
                else:
                    raise IntegrationError("NOT_FOUND_OR_FORBIDDEN", 404)
                self._integration_reply(status, reply)
            except Exception as exc:
                log_failure("web.serve.Handler._integration_post.failed")
                self._integration_error(exc)

        def do_GET(self):
            if re.match(r"^/integration/v[123]/", urlsplit(self.path).path):
                return self._integration_get()
            if integration_only:
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
                    self._reply(
                        200,
                        coordinator.successor.capabilities(trusted)
                        if self.selected_version == "0.3"
                        else coordinator.capabilities(trusted),
                    )
                elif coordinator.registry and re.fullmatch(
                    r"/v1/attribution-runs/[A-Za-z0-9._:-]+", path
                ):
                    run = coordinator.registry.attribution.run(path.rsplit("/", 1)[1])
                    if not run or run["principal_id"] != trusted["principal_id"]:
                        raise ContractError("NOT_FOUND_OR_FORBIDDEN", 404)
                    self._reply(
                        200, {"contract_version": "0.2", "attribution_version": "1", "run": run}
                    )
                elif coordinator.registry and re.fullmatch(r"/v1/outcomes/[A-Za-z0-9._:-]+", path):
                    receipt = coordinator.registry.attribution.outcome_receipt(
                        trusted, path.rsplit("/", 1)[1]
                    )
                    self._reply(
                        200, {"contract_version": "0.2", "outcome_version": "1", "receipt": receipt}
                    )
                elif path.startswith("/v1/submissions/by-work/"):
                    parts = [unquote(x) for x in path[len("/v1/submissions/by-work/") :].split("/")]
                    if (
                        len(parts) != 4
                        or not re.fullmatch(r"[1-9][0-9]*", parts[2])
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
                    self._reply(
                        200,
                        coordinator.successor.status_by_work(key, trusted)
                        if self.selected_version == "0.3"
                        else coordinator.status_by_work(key, trusted),
                    )
                elif re.fullmatch(r"/v1/submissions/[A-Za-z0-9._:-]+", path):
                    self._reply(
                        200,
                        coordinator.successor.status(path.rsplit("/", 1)[1], trusted)
                        if self.selected_version == "0.3"
                        else coordinator.status(path.rsplit("/", 1)[1], trusted),
                    )
                else:
                    raise ContractError("NOT_FOUND_OR_FORBIDDEN", 404)
            except Exception as exc:
                log_failure("web.serve.Handler.do_GET.failed")
                self._error(exc)

        def do_POST(self):
            if re.match(r"^/integration/v[123]/", urlsplit(self.path).path):
                return self._integration_post()
            if integration_only:
                return self._integration_error(IntegrationError("NOT_FOUND_OR_FORBIDDEN", 404))
            try:
                trusted = self._context()
                path = self._path()
                if self.selected_version == "0.3" and path != "/v1/submissions":
                    raise ContractError("NOT_FOUND_OR_FORBIDDEN", 404)
                if path not in ("/v1/submissions", "/v1/attribution-runs", "/v1/outcomes") or (
                    path != "/v1/submissions" and not coordinator.registry
                ):
                    raise ContractError("NOT_FOUND_OR_FORBIDDEN", 404)
                waits = self.headers.get_all("EzLLMRouter-Wait-Ms")
                if waits:
                    if (
                        len(waits) != 1
                        or not re.fullmatch(r"(?:0|[1-9][0-9]*)", waits[0])
                        or int(waits[0]) > 30000
                    ):
                        raise ContractError("SCHEMA_INVALID", 400)
                    wait = int(waits[0])
                else:
                    wait = 1000
                lengths = self.headers.get_all("Content-Length")
                if self.headers.get_all("Content-Type") != ["application/json"]:
                    raise ContractError("SCHEMA_INVALID", 400)
                max_bytes = 262144 if self.selected_version == "0.3" else 65536
                if (
                    len(lengths or []) != 1
                    or not lengths[0].isdigit()
                    or int(lengths[0]) > max_bytes
                    or self.headers.get("Transfer-Encoding")
                ):
                    raise ContractError("LIMIT_EXCEEDED", 413)
                data = self.read_body(int(lengths[0]))
                if self.selected_version == "0.3":
                    from .successor_contract import strict_decode

                    request = strict_decode(data)
                    if type(request) is not dict or request.get("contract_version") != "0.3":
                        raise ContractError("UNSUPPORTED_VERSION", 426)
                    status, reply = coordinator.successor.submit(
                        request, trusted, wait, credential=self.headers["Authorization"][7:]
                    )
                    return self._reply(status, reply)
                request = strict_loads(data)
                if path == "/v1/attribution-runs":
                    run = coordinator.registry.attribution.start_run(trusted, request)
                    return self._reply(
                        200, {"contract_version": "0.2", "attribution_version": "1", "run": run}
                    )
                if path == "/v1/outcomes":
                    receipt = coordinator.registry.attribution.append_outcome(trusted, request)
                    return self._reply(
                        201, {"contract_version": "0.2", "outcome_version": "1", "receipt": receipt}
                    )
                run_headers = self.headers.get_all("EzLLMRouter-Attribution-Run")
                versions = self.headers.get_all("EzLLMRouter-Attribution-Version")
                if bool(run_headers) != bool(versions) or (
                    run_headers
                    and (
                        len(run_headers) != 1
                        or len(versions) != 1
                        or versions[0] != "1"
                        or not valid_identifier(run_headers[0])
                    )
                ):
                    raise ContractError("SCHEMA_INVALID", 400)
                status, reply = coordinator.submit(
                    request,
                    trusted,
                    wait,
                    credential=self.headers["Authorization"][7:],
                    run_id=run_headers[0] if run_headers else None,
                )
                self._reply(status, reply)
            except Exception as exc:
                log_failure("web.serve.Handler.do_POST.failed")
                self._error(exc)

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server
