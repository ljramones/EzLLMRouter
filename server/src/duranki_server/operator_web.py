"""Loopback-only synthetic operator console and authenticated metadata API."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http import cookies
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import csv
import hmac
import io
import json
import os
from pathlib import Path
import secrets
import socket
import socketserver
import threading
import time
import uuid
from urllib.parse import parse_qs, urlsplit

from .registry import RegistryConflict
from .provider_adapters import ADAPTERS, PROVIDERS
from .reporting import usage_costs
from .successor_reporting import usage_report
from .demo_workspace import project_demo
from .demo_workspace_team import project_team_demo
from .integration_accounting import IntegrationError, route_id


SESSION_SECONDS = 1800


def _pairs(items):
    value = {}
    for key, item in items:
        if key in value:
            raise ValueError("duplicate operator key")
        value[key] = item
    return value


def _reject_number(_text):
    raise ValueError("unsupported operator number")


def serve(host, port, *, projection, runner, password, fixture, build, web_root,
          worker_probe, sender_status, allowed_hosts=None, socket_path=None, registry=None,
          provider_validation=None, successor_store=None, integration_only=False, mach33_demo=None):
    if host not in ("0.0.0.0", "127.0.0.1") or not password or len(password) < 32:
        raise ValueError("unsafe operator binding or credential")
    allowed_hosts = allowed_hosts or {f"127.0.0.1:{port}", f"localhost:{port}"}
    allowed_origins = {"http://" + value for value in allowed_hosts}
    sessions = {}
    session_lock = threading.Lock()
    jobs = ThreadPoolExecutor(max_workers=2, thread_name_prefix="duranki-operator-demo")
    root = Path(web_root)

    def execute(operation_id, kind):
        try:
            result = runner.run(kind, lambda sid: projection.record_launch_submission(operation_id, sid))
            projection.finish_launch(operation_id, "completed", result["submission_ids"],
                                     result["caller_lookups"])
        except Exception as exc:
            prior = projection.launch(operation_id)
            ids = prior["submission_ids"] if prior else []
            code = getattr(exc, "code", None)
            if code is None and str(exc) in ("DEMO_OUTCOME_UNKNOWN", "DEMO_NO_CANDIDATE"):
                code = str(exc)
            projection.finish_launch(operation_id,
                "outcome_unknown" if code in ("DEMO_OUTCOME_UNKNOWN", "TRANSPORT_OUTCOME_UNKNOWN")
                else "failed", ids, error_code=code or "DEMO_FAILED")

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args):
            return  # No credential, cookie, query or content logging.

        def _send(self, status, payload, *, content_type="application/json; charset=utf-8", extra=()):
            data = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
                    if not isinstance(payload, bytes) else payload)
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; "
                "style-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            for name, value in extra:
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(data)

        def _fail(self, status, code):
            self._send(status, {"error": code})

        def _origin_ok(self, mutation=False):
            if self.headers.get_all("Host") not in ([value] for value in allowed_hosts):
                return False
            origin = self.headers.get("Origin")
            return (origin in allowed_origins if mutation else origin is None or origin in allowed_origins)

        def _session(self):
            header = self.headers.get("Cookie", "")
            jar = cookies.SimpleCookie()
            try:
                jar.load(header)
                token = jar["duranki_operator"].value
            except (cookies.CookieError, KeyError):
                return None
            with session_lock:
                item = sessions.get(token)
                if not item:
                    return None
                if item["expires"] <= time.monotonic():
                    sessions.pop(token, None)
                    return None
                if registry:
                    principal = registry.principal(item["principal_id"])
                    if not principal or principal["status"] != "active":
                        sessions.pop(token, None)
                        return None
                    item["role"] = principal["role"]
                return token, item

        def _registry_read(self, path, session):
            actor = session[1]["principal_id"]
            role = session[1]["role"]
            admin_view = role in ("registry_admin", "read_only_operator")
            if path.path == "/operator/v1/providers" and not path.query:
                if not admin_view:
                    return self._fail(403, "OPERATOR_REQUIRED")
                return self._send(200, {"providers": PROVIDERS, "adapters": ADAPTERS})
            if path.path.startswith("/operator/v1/provider-validations/") and not path.query:
                if not admin_view:
                    return self._fail(403, "OPERATOR_REQUIRED")
                operation_id = path.path.rsplit("/", 1)[1]
                value = projection.provider_validation(operation_id)
                return self._send(200, value) if value else self._fail(404, "NOT_FOUND")
            if path.path == "/operator/v1/connections" and not path.query:
                if not admin_view:
                    return self._fail(403, "OPERATOR_REQUIRED")
                return self._send(200, {"items": registry.list_connections()})
            if path.path == "/operator/v1/personal-campaign" and not path.query:
                if actor != "owner.local" or not getattr(registry, "personal_campaign", None):
                    return self._fail(403, "OWNER_REQUIRED")
                return self._send(200, registry.personal_campaign.summary())
            if path.path.startswith("/operator/v1/connections/") and path.path.endswith("/inventory") and not path.query:
                if not admin_view:
                    return self._fail(403, "OPERATOR_REQUIRED")
                connection_id = path.path[len("/operator/v1/connections/"):-len("/inventory")]
                if "/" in connection_id or not registry.connection(connection_id):
                    return self._fail(404, "NOT_FOUND")
                return self._send(200, registry.source_inventory(connection_id))
            if path.path.startswith("/operator/v1/connections/") and not path.query:
                if not admin_view:
                    return self._fail(403, "OPERATOR_REQUIRED")
                connection_id = path.path[len("/operator/v1/connections/"):]
                if "/" in connection_id:
                    raise ValueError("invalid connection path")
                connection = registry.connection(connection_id)
                if not connection:
                    return self._fail(404, "NOT_FOUND")
                return self._send(200, {"connection": connection,
                    "deployments": registry.deployments(connection_id),
                    "observations": registry.observations(connection_id),
                    "history": registry.history(connection_id)})
            if path.path == "/operator/v1/models" and not path.query:
                models = registry.list_models()
                if not admin_view:
                    models = [model for model in models if registry.explain(
                        actor, model["configuration_ref"], "execution", "class.demo")["allowed"]]
                return self._send(200, {"items": [{**model,
                    "readiness": registry.readiness(model),
                    "current_price": (registry.prices(model["configuration_ref"]) or [None])[-1]}
                    for model in models]})
            if path.path.startswith("/operator/v1/models/") and not path.query:
                ref = path.path[len("/operator/v1/models/"):]
                if "/" in ref:
                    raise ValueError("invalid model path")
                model = registry.model(ref)
                if not model:
                    return self._fail(404, "NOT_FOUND")
                if not admin_view and not registry.explain(actor, ref, "execution", "class.demo")["allowed"]:
                    return self._fail(404, "NOT_FOUND")
                grants = []
                if admin_view:
                    grants = [registry.grant(principal["principal_id"], ref) for principal in
                              registry.list_principals()]
                return self._send(200, {"model": model, "readiness": registry.readiness(model),
                    "prices": registry.prices(ref),
                    "grants": [grant for grant in grants if grant],
                    "history": registry.history(ref) if admin_view else []})
            if path.path == "/operator/v1/principals" and not path.query:
                principals = registry.list_principals() if admin_view else [registry.principal(actor)]
                models = {model["configuration_ref"]: model for model in registry.list_models()}
                items = []
                for principal in principals:
                    grants = [registry.grant(principal["principal_id"], ref) for ref in models]
                    items.append({**principal, "grant_summary": [
                        {**grant, "display_name": models[grant["configuration_ref"]]["display_name"],
                         "readiness": registry.readiness(models[grant["configuration_ref"]])}
                        for grant in grants if grant]})
                return self._send(200, {"items": items})
            if path.path.startswith("/operator/v1/principals/") and not path.query:
                principal_id = path.path[len("/operator/v1/principals/"):]
                if "/" in principal_id:
                    raise ValueError("invalid principal path")
                if not admin_view and principal_id != actor:
                    return self._fail(404, "NOT_FOUND")
                principal = registry.principal(principal_id)
                if not principal:
                    return self._fail(404, "NOT_FOUND")
                models = {model["configuration_ref"]: model for model in registry.list_models()}
                grants = [registry.grant(principal_id, ref) for ref in models]
                return self._send(200, {"principal": principal,
                    "grants": [{**grant, "display_name": models[grant["configuration_ref"]]["display_name"],
                                "readiness": registry.readiness(models[grant["configuration_ref"]])}
                               for grant in grants if grant],
                    "history": registry.history(principal_id) if admin_view else []})
            if path.path == "/operator/v1/access/explain":
                query = parse_qs(path.query, strict_parsing=True, keep_blank_values=True)
                if set(query) != {"principal_id", "configuration_ref", "purpose", "task_class"} or any(
                        len(values) != 1 for values in query.values()):
                    raise ValueError("invalid explain query")
                principal_id = query["principal_id"][0]
                if not admin_view and principal_id != actor:
                    return self._fail(404, "NOT_FOUND")
                return self._send(200, registry.explain(principal_id,
                    query["configuration_ref"][0], query["purpose"][0], query["task_class"][0]))
            return self._fail(404, "NOT_FOUND")

        def _body(self):
            lengths = self.headers.get_all("Content-Length")
            if (self.headers.get_all("Content-Type") != ["application/json"] or
                    len(lengths or []) != 1 or not lengths[0].isdigit() or
                    not 0 < int(lengths[0]) <= (8192 if self.path == "/operator/v1/provider-credential" or
                        self.path.startswith("/operator/v1/integration/connections") else
                        4096 if self.path in ("/operator/v1/registry", "/operator/v1/provider-probe") else 2048) or
                    self.headers.get("Transfer-Encoding")):
                raise ValueError("body shape")
            value = json.loads(self.rfile.read(int(lengths[0])), object_pairs_hook=_pairs,
                               parse_float=_reject_number, parse_constant=_reject_number)
            if type(value) is not dict:
                raise ValueError("body shape")
            return value

        def do_GET(self):
            if not self._origin_ok():
                return self._fail(403, "ORIGIN_REJECTED")
            path = urlsplit(self.path)
            if path.fragment:
                return self._fail(400, "INVALID_PATH")
            if path.path in ("/", "/integration", "/app.js", "/catalogue_view.js", "/activity_usage_view.js", "/crud_view.js", "/providers_view.js", "/source_pages.js", "/usage_costs_view.js", "/demo_workspace_view.js", "/demo_workspace_team_view.js", "/mach33_demo_view.js", "/integration_view.js", "/integration_console.js", "/integration_accounting.js", "/app.css", "/integration_console.css") and not path.query:
                filename, content_type = {
                    "/": ("index.html", "text/html; charset=utf-8"),
                    "/integration": ("index.html", "text/html; charset=utf-8"),
                    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                    "/integration_view.js": ("integration_view.js", "text/javascript; charset=utf-8"),
                    "/integration_console.js": ("integration_console.js", "text/javascript; charset=utf-8"),
                    "/integration_accounting.js": ("integration_accounting.js", "text/javascript; charset=utf-8"),
                    "/catalogue_view.js": ("catalogue_view.js", "text/javascript; charset=utf-8"),
                    "/activity_usage_view.js": ("activity_usage_view.js", "text/javascript; charset=utf-8"),
                    "/crud_view.js": ("crud_view.js", "text/javascript; charset=utf-8"),
                    "/providers_view.js": ("providers_view.js", "text/javascript; charset=utf-8"),
                    "/source_pages.js": ("source_pages.js", "text/javascript; charset=utf-8"),
                    "/usage_costs_view.js": ("usage_costs_view.js", "text/javascript; charset=utf-8"),
                    "/demo_workspace_view.js": ("demo_workspace_view.js", "text/javascript; charset=utf-8"),
                    "/demo_workspace_team_view.js": ("demo_workspace_team_view.js", "text/javascript; charset=utf-8"),
                    "/mach33_demo_view.js": ("mach33_demo_view.js", "text/javascript; charset=utf-8"),
                    "/app.css": ("app.css", "text/css; charset=utf-8"),
                    "/integration_console.css": ("integration_console.css", "text/css; charset=utf-8")}[path.path]
                return self._send(200, (root / filename).read_bytes(), content_type=content_type)
            session = self._session()
            if not session:
                return self._fail(401, "AUTH_REQUIRED")
            try:
                if path.path == "/operator/v1/session" and not path.query:
                    return self._send(200, {"authenticated": True, "csrf": session[1]["csrf"],
                        "role": session[1]["role"], "principal_id": session[1]["principal_id"]})
                if path.path == "/operator/v1/integration/vega-me" and not path.query:
                    if not integration_only or session[1]["role"] != "registry_admin":
                        return self._fail(404, "NOT_FOUND")
                    jar = cookies.SimpleCookie()
                    try:
                        jar.load(self.headers.get("Cookie", ""))
                    except cookies.CookieError:
                        return self._send(200, {"user": None})
                    session_cookies = [f"{name}={morsel.value}" for name, morsel in jar.items()
                                       if name == "m33_session" or name.startswith("m33_session_")]
                    if not session_cookies:
                        return self._send(200, {"user": None})
                    connection = HTTPConnection("127.0.0.1", 3049, timeout=2)
                    try:
                        connection.request("GET", "/api/me", headers={"Cookie": "; ".join(session_cookies)})
                        response = connection.getresponse()
                        body = response.read(4097)
                        if response.status != 200 or len(body) > 4096:
                            return self._send(200, {"user": None})
                        identity = json.loads(body).get("user") or {}
                        if not isinstance(identity.get("id"), str) or not isinstance(identity.get("name"), str):
                            return self._send(200, {"user": None})
                        return self._send(200, {"user": {"id": identity["id"], "name": identity["name"]}})
                    except (OSError, ValueError, json.JSONDecodeError):
                        return self._send(200, {"user": None})
                    finally:
                        connection.close()
                if path.path.startswith("/operator/v1/mach33-demo/"):
                    if mach33_demo is None or session[1]["role"] not in ("registry_admin", "read_only_operator"):
                        return self._fail(404, "NOT_FOUND")
                    query = parse_qs(path.query, strict_parsing=True, keep_blank_values=True)
                    if any(len(value) != 1 for value in query.values()):
                        raise ValueError("invalid demo selector")
                    if path.path == "/operator/v1/mach33-demo/report":
                        selected = {key: values[0] for key, values in query.items() if key != "export"}
                        report = mach33_demo.report(selected)
                        export = query.get("export", [None])[0]
                        if export in (None, "json"):
                            return self._send(200, report, extra=(("Content-Disposition",
                                "attachment; filename=ezllmrouter-scripted-demo-report.json"),) if export else ())
                        if export == "csv":
                            columns = ("demo_provenance", "dataset_id", "attempt_id", "workflow_id", "task_id",
                                "run_id", "executing_actor_id", "initiating_user_id", "charging_owner_id",
                                "provider_id", "model_id", "started_at", "ended_at", "local_date",
                                "provider_result", "usage_revision_id", "usage_observed_at", "usage_state",
                                "input_tokens", "output_tokens", "cost_state", "currency", "amount_decimal")
                            out = io.StringIO()
                            writer = csv.DictWriter(out, columns, extrasaction="ignore")
                            writer.writeheader()
                            writer.writerows({**row, "demo_provenance": mach33_demo.meta["required_banner"]}
                                             for row in report["attempts"])
                            return self._send(200, out.getvalue().encode(), content_type="text/csv; charset=utf-8",
                                extra=(("Content-Disposition", "attachment; filename=ezllmrouter-scripted-demo-report.csv"),))
                        raise ValueError("invalid demo export")
                    if path.path == "/operator/v1/mach33-demo/workflow" and set(query) == {"workflow_id"}:
                        try:
                            return self._send(200, mach33_demo.workflow(query["workflow_id"][0]))
                        except KeyError:
                            return self._fail(404, "NOT_FOUND")
                    return self._fail(404, "NOT_FOUND")
                if registry and path.path.startswith("/operator/v1/integration/"):
                    principal = registry.principal(session[1]["principal_id"])
                    ledger = registry.integration
                    if path.path == "/operator/v1/integration/datasets" and not path.query:
                        return self._send(200, ledger.datasets(principal))
                    query = parse_qs(path.query, strict_parsing=True, keep_blank_values=True)
                    allowed = ({"dataset_id", "actor_id", "provider_account_id", "task_id", "model_id",
                                "initiating_user_id", "root_run_id", "run_id", "from", "to", "export"}
                               if path.path == "/operator/v1/integration/report" else {"dataset_id"})
                    if any(len(values) != 1 for values in query.values()) or "dataset_id" not in query or set(query) - allowed:
                        raise ValueError("invalid integration selector")
                    dataset_id = query["dataset_id"][0]
                    if path.path == "/operator/v1/integration/connections":
                        return self._send(200, registry.integration_credentials.list(principal, dataset_id))
                    if path.path == "/operator/v1/integration/accounts":
                        return self._send(200, ledger.accounts(principal, dataset_id))
                    if path.path == "/operator/v1/integration/report":
                        filters = {key: value[0] for key, value in query.items()
                                   if key not in ("dataset_id", "export")}
                        report = ledger.report(principal, dataset_id, filters, version="3")
                        export = query.get("export", [None])[0]
                        if export in (None, "json"):
                            return self._send(200, report, extra=(("Content-Disposition",
                                "attachment; filename=duranki-integration-report.json"),) if export else ())
                        if export == "csv":
                            columns = ("dataset_id", "platform_id", "environment_id", "owner_id", "attempt_id",
                                "started_at", "task_id", "step_id", "run_id", "root_run_id", "parent_run_id",
                                "actor_kind", "actor_id", "initiating_user_id", "provider_account_id", "model_id",
                                "context_ref", "result_state", "result_observed_at", "task_outcome",
                                "task_outcome_observed_at", "usage_revision", "usage_observed_at", "cost_status",
                                "currency", "amount_decimal", "native_units", "cost_basis", "price_ref", "price_version",
                                "operation_family_version", "operation_family", "model_identity_state",
                                "logical_operation_id", "attempt_role", "predecessor_attempt_id", "lineage_status",
                                "account_resolution_status", "resolved_account_id", "decision_ref",
                                "eligibility_evidence_status", "eligibility_assessment", "eligibility_record",
                                "selected_action", "feature_snapshot_status", "feature_snapshot_digest",
                                "feature_available_before_start", "decision_snapshot_status", "decision_snapshot_digest",
                                "usage_provenance", "usage_state")
                            out = io.StringIO()
                            writer = csv.DictWriter(out, columns, extrasaction="ignore")
                            writer.writeheader()
                            for row in report["attempts"]:
                                writer.writerow({key: json.dumps(value, sort_keys=True) if key in
                                    ("native_units", "eligibility_record", "selected_action") and value is not None
                                    else value for key, value in row.items()})
                            return self._send(200, out.getvalue().encode(), content_type="text/csv; charset=utf-8",
                                extra=(("Content-Disposition", "attachment; filename=duranki-integration-report.csv"),))
                        raise ValueError("invalid report export")
                    if path.path == "/operator/v1/integration/export" and set(query) == {"dataset_id"}:
                        return self._send(200, ledger.dataset_export(principal, dataset_id, "3"),
                            extra=(("Content-Disposition", "attachment; filename=duranki-integration-dataset.json"),))
                    return self._fail(404, "NOT_FOUND")
                if integration_only and path.path not in ("/operator/v1/usage-costs",
                                                         "/operator/v1/models",
                                                         "/operator/v1/principals",
                                                         "/operator/v1/usage",
                                                         "/operator/v1/demo-workspace"):
                    return self._fail(404, "NOT_FOUND")
                if successor_store is not None and path.path == "/operator/v1/dev12-usage":
                    query = parse_qs(path.query, strict_parsing=True, keep_blank_values=True)
                    if any(len(values) != 1 for values in query.values()) or set(query) - {
                            "from", "to", "cutoff", "operation", "actor_id", "provider_ref", "initiating_user_id",
                            "charging_owner_id", "root_workflow_id", "configuration_ref", "task_id",
                            "environment", "export"}:
                        raise ValueError("invalid synthetic report filter")
                    selected = {key: values[0] for key, values in query.items() if key != "export"}
                    report = usage_report(successor_store, {"role": session[1]["role"],
                        "principal_id": session[1]["principal_id"]}, selected)
                    export = query.get("export", [None])[0]
                    if export in (None, "json"):
                        return self._send(200, report, extra=(("Content-Disposition",
                            "attachment; filename=duranki-dev12-synthetic-usage.json"),) if export else ())
                    if export == "csv":
                        out = io.StringIO()
                        columns = ("attempt_id", "submission_id", "created_at", "principal_id", "task_id",
                            "run_id", "parent_run_id", "root_workflow_id", "environment", "operation", "input_role",
                            "actor_id", "initiating_user_id", "charging_owner_id", "provider_ref", "configuration_ref",
                            "price_ref", "usage_ref", "usage_revision", "native_components",
                            "reservation_decimal", "cost_status", "currency", "amount_decimal",
                            "exposure_state", "exposure_state_as_of", "submission_state",
                            "delivery_state", "candidate_access")
                        writer = csv.DictWriter(out, columns, extrasaction="ignore")
                        writer.writeheader()
                        writer.writerows(report["attempts"])
                        return self._send(200, out.getvalue().encode(), content_type="text/csv; charset=utf-8",
                            extra=(("Content-Disposition", "attachment; filename=duranki-dev12-synthetic-usage.csv"),))
                    raise ValueError("invalid synthetic report export")
                if path.path == "/operator/v1/demo-workspace":
                    query = parse_qs(path.query, strict_parsing=True, keep_blank_values=True)
                    if any(len(values) != 1 for values in query.values()) or set(query) - {"collection", "story", "actor", "person", "provider"}:
                        raise ValueError("invalid demo filter")
                    collection = query.get("collection", ["legacy"])[0]
                    default_story = "main" if collection == "legacy" else "expanded_all" if collection == "expanded" else "team"
                    filters = {"story": query.get("story", [default_story])[0],
                               "actor": query.get("actor", [""])[0], "provider": query.get("provider", [""])[0]}
                    if collection == "legacy":
                        report = project_demo(root / "dev09_demo_fixture.json",
                            person=query.get("person", [""])[0], **filters)
                    else:
                        report = project_team_demo(root / "dev09_demo_fixture.json", collection=collection,
                            person=query.get("person", [""])[0], **filters)
                    return self._send(200, report)
                if registry and path.path == "/operator/v1/usage-costs":
                    query = parse_qs(path.query, strict_parsing=True, keep_blank_values=True)
                    if any(len(values) != 1 for values in query.values()) or set(query) - {
                            "from", "to", "cutoff", "currency", "environment", "provider",
                            "connection_id", "model", "configuration_ref", "agent_id", "agent_version", "initiating_user_id",
                            "charging_owner_id", "task_class", "purpose", "agent_search", "page", "limit", "export"}:
                        raise ValueError("invalid report filter")
                    selected = {key: values[0] for key, values in query.items() if key not in ("page", "limit", "export")}
                    report = usage_costs(registry, {"role": session[1]["role"],
                        "principal_id": session[1]["principal_id"]}, selected,
                        page=int(query.get("page", ["1"])[0]), limit=int(query.get("limit", ["50"])[0]))
                    export = query.get("export", [None])[0]
                    if export == "json":
                        return self._send(200, report, extra=(("Content-Disposition", "attachment; filename=duranki-usage-costs.json"),))
                    if export == "csv":
                        out = io.StringIO()
                        columns = ("attempt_id", "submission_id", "attempt_at", "provider", "connection_id",
                            "configuration_ref", "model", "agent_id", "agent_version", "run_id", "root_run_id",
                            "initiating_user_id", "charging_owner_id", "task_id", "task_class", "purpose",
                            "environment", "cost_status", "currency", "amount_decimal", "estimated_amount_decimal", "price_version",
                            "usage_revision", "input_tokens", "output_tokens")
                        writer = csv.DictWriter(out, columns, extrasaction="ignore")
                        writer.writeheader()
                        writer.writerows(report["attempts"])
                        return self._send(200, out.getvalue().encode(), content_type="text/csv; charset=utf-8",
                            extra=(("Content-Disposition", "attachment; filename=duranki-usage-costs.csv"),))
                    if export is not None:
                        raise ValueError("invalid report export")
                    return self._send(200, report)
                if registry and (path.path.startswith("/operator/v1/models") or
                                 path.path.startswith("/operator/v1/principals") or
                                 path.path.startswith("/operator/v1/connections") or
                                 path.path.startswith("/operator/v1/provider-validations/") or
                                 path.path == "/operator/v1/personal-campaign" or
                                 path.path == "/operator/v1/providers" or
                                 path.path == "/operator/v1/access/explain"):
                    return self._registry_read(path, session)
                scope = ("*" if session[1]["role"] != "ordinary" else
                         session[1]["principal_id"]) if registry else None
                if registry and session[1]["role"] == "ordinary" and not (
                        path.path == "/operator/v1/overview" or
                        path.path == "/operator/v1/activity" or
                        path.path.startswith("/operator/v1/activity/") or
                        path.path == "/operator/v1/usage"):
                    return self._fail(403, "OPERATOR_REQUIRED")
                if path.path == "/operator/v1/overview" and not path.query:
                    try:
                        worker = worker_probe()
                    except Exception as exc:
                        worker = {"state": "unavailable", "error_type": type(exc).__name__}
                    return self._send(200, {"profile": ("LOCAL DEVELOPMENT · PROVIDER PATH GATED"
                        if registry and registry.provider_execution_ready else "LIVE SYNTHETIC DEVELOPMENT"),
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                        "service": {"state": "live"}, "worker": worker,
                        "sender": sender_status(), "counts": projection.overview_counts(scope),
                        "recent": projection.activity(limit=6, principal_id=scope)["items"],
                        "build": {"commit": build.get("commit"), "dirty": build.get("dirty"),
                                  "fingerprint": build.get("fingerprint")}})
                if path.path == "/operator/v1/activity":
                    query = parse_qs(path.query, strict_parsing=True, keep_blank_values=True)
                    if set(query) - {"page", "limit", "state", "principal_id"} or any(len(x) != 1 for x in query.values()):
                        raise ValueError("query")
                    selected = query.get("principal_id", [None])[0]
                    if selected is not None:
                        if not registry or not registry.principal(selected):
                            raise ValueError("invalid principal filter")
                        if session[1]["role"] == "ordinary" and selected != scope:
                            return self._fail(404, "NOT_FOUND")
                    return self._send(200, projection.activity(
                        page=int(query.get("page", ["1"])[0]),
                        limit=int(query.get("limit", ["20"])[0]),
                        state=query.get("state", [None])[0], principal_id=selected or scope))
                if path.path.startswith("/operator/v1/activity/") and not path.query:
                    identifier = path.path[len("/operator/v1/activity/"):]
                    if "/" in identifier:
                        raise ValueError("invalid activity path")
                    value = projection.detail(identifier, scope)
                    return self._send(200, value) if value else self._fail(404, "NOT_FOUND")
                if path.path == "/operator/v1/usage":
                    query = parse_qs(path.query, strict_parsing=True, keep_blank_values=True)
                    if set(query) - {"principal_id"} or any(len(x) != 1 for x in query.values()):
                        raise ValueError("invalid usage filter")
                    selected = query.get("principal_id", [None])[0]
                    if selected is not None:
                        if not registry or not registry.principal(selected):
                            raise ValueError("invalid principal filter")
                        if session[1]["role"] == "ordinary" and selected != scope:
                            return self._fail(404, "NOT_FOUND")
                    return self._send(200, projection.usage(selected or scope))
                if path.path == "/operator/v1/config" and not path.query:
                    destination = fixture["destination"]
                    policy = fixture["policy"]
                    return self._send(200, {"configuration": {k: destination[k] for k in
                        ("configuration_ref", "service", "endpoint", "model", "model_version", "processing_region")},
                        "policy": {k: policy[k] for k in
                            ("policy_version", "registry_version", "limit_version", "recovery_policy_version")},
                        "capabilities": {"text": True, "caller_owned_lookup": True,
                            "configuration_editing": bool(registry), "approval_revocation": bool(registry),
                            "budgets": False, "cancellation": False,
                            "real_provider": bool(registry and getattr(registry, "personal_campaign", None) and
                                registry.personal_campaign.summary()["effective_state"] == "active")}})
                if path.path == "/operator/v1/build" and not path.query:
                    return self._send(200, {"profile": ("LOCAL DEVELOPMENT · PROVIDER PATH GATED"
                        if registry and registry.provider_execution_ready else "LIVE SYNTHETIC DEVELOPMENT"), "build": build,
                        "packages": {"python_client": "0.0.4", "litellm": "1.105.1"},
                        "environment": ("local isolated synthetic HTTP/1.1 and selected provider HTTPS"
                            if registry and registry.provider_execution_ready else
                            "local isolated synthetic HTTP/1.1"),
                        "milestones": ["DEV-04 Run-11", "DEV-05 Run-16"]})
                if path.path.startswith("/operator/v1/launch/") and not path.query:
                    identifier = path.path[len("/operator/v1/launch/"):]
                    if "/" in identifier:
                        raise ValueError("invalid launch path")
                    value = projection.launch(identifier)
                    return self._send(200, value) if value else self._fail(404, "NOT_FOUND")
            except IntegrationError as exc:
                return self._fail(exc.status, exc.code)
            except (ValueError, KeyError, TypeError):
                return self._fail(400, "INVALID_SELECTOR")
            except Exception:
                return self._fail(503, "METADATA_UNAVAILABLE")
            return self._fail(404, "NOT_FOUND")

        def do_POST(self):
            if not self._origin_ok(mutation=True) or urlsplit(self.path).query:
                return self._fail(403, "ORIGIN_REJECTED")
            try:
                body = self._body()
            except (ValueError, UnicodeError, json.JSONDecodeError):
                return self._fail(400, "INVALID_BODY")
            if self.path == "/operator/v1/login":
                if set(body) != {"password"} or type(body["password"]) is not str:
                    return self._fail(400, "INVALID_BODY")
                if hmac.compare_digest(password, body["password"]):
                    principal = registry.principal("owner.local") if registry else None
                    if registry and (not principal or principal["status"] != "active"):
                        return self._fail(401, "AUTH_FAILED")
                    principal_id = "owner.local"
                elif registry:
                    try:
                        principal = registry.credential_principal(body["password"], "human")
                        principal_id = principal["principal_id"]
                    except Exception:
                        return self._fail(401, "AUTH_FAILED")
                else:
                    return self._fail(401, "AUTH_FAILED")
                token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                with session_lock:
                    for key in tuple(sessions):
                        if sessions[key]["expires"] <= time.monotonic():
                            sessions.pop(key)
                    if len(sessions) >= 64:
                        return self._fail(429, "SESSION_LIMIT")
                    sessions[token] = {"csrf": csrf, "expires": time.monotonic() + SESSION_SECONDS,
                                       "principal_id": principal_id,
                                       "role": principal["role"] if registry else "registry_admin",
                                       "wire_token": registry.issue_local_operator_token(principal_id)
                                           if registry and principal_id == "owner.local" and
                                              getattr(registry, "personal_campaign", None) else None}
                return self._send(200, {"authenticated": True, "csrf": csrf,
                    "expires_in_seconds": SESSION_SECONDS,
                    "role": principal["role"] if registry else "registry_admin",
                    "principal_id": principal_id},
                    extra=(("Set-Cookie", "duranki_operator=" + token +
                            "; Path=/operator; HttpOnly; SameSite=Strict; Max-Age=1800"),))
            session = self._session()
            if not session:
                return self._fail(401, "AUTH_REQUIRED")
            if not hmac.compare_digest(self.headers.get("X-Duranki-CSRF", ""), session[1]["csrf"]):
                return self._fail(403, "CSRF_REJECTED")
            if registry and self.path.startswith("/operator/v1/integration/"):
                if session[1]["role"] != "registry_admin":
                    return self._fail(403, "ADMIN_REQUIRED")
                principal = registry.principal(session[1]["principal_id"])
                try:
                    if self.path == "/operator/v1/integration/datasets":
                        status, result = registry.integration.create_dataset(principal, body)
                    elif self.path == "/operator/v1/integration/connections":
                        result = registry.integration_credentials.connect(principal, body)
                        status = 201
                    elif self.path.startswith("/operator/v1/integration/connections/"):
                        parts = self.path.split("/")
                        if len(parts) != 7 or parts[-1] not in ("save", "refresh", "replace", "disable", "retire"):
                            return self._fail(404, "NOT_FOUND")
                        account_id = route_id(parts[-2])
                        result = getattr(registry.integration_credentials, parts[-1])(
                            principal, account_id, body)
                        status = 200
                    elif self.path == "/operator/v1/integration/accounts":
                        status, result = registry.integration.create_account(
                            principal, body, "3" if "allowed_operations" in body else "1")
                    elif self.path.endswith("/permissions") and self.path.startswith("/operator/v1/integration/accounts/"):
                        account_raw = self.path[len("/operator/v1/integration/accounts/"):-len("/permissions")]
                        if "/" in account_raw:
                            return self._fail(404, "NOT_FOUND")
                        status, result = registry.integration.set_account_permissions(
                            principal, route_id(account_raw), body)
                    elif self.path.endswith("/state") and self.path.startswith("/operator/v1/integration/accounts/"):
                        account_raw = self.path[len("/operator/v1/integration/accounts/"):-len("/state")]
                        if "/" in account_raw:
                            return self._fail(404, "NOT_FOUND")
                        account_id = route_id(account_raw)
                        status, result = registry.integration.set_account_state(principal, account_id, body)
                    else:
                        return self._fail(404, "NOT_FOUND")
                    return self._send(status, result)
                except IntegrationError as exc:
                    return self._fail(exc.status, exc.code)
                except Exception:
                    return self._fail(503, "INTEGRATION_UNAVAILABLE")
            if integration_only and self.path != "/operator/v1/logout":
                return self._fail(404, "NOT_FOUND")
            if self.path == "/operator/v1/logout":
                if body:
                    return self._fail(400, "INVALID_BODY")
                with session_lock:
                    sessions.pop(session[0], None)
                if registry and session[1].get("wire_token"):
                    registry.revoke_local_operator_token(session[1]["wire_token"])
                return self._send(200, {"authenticated": False},
                    extra=(("Set-Cookie", "duranki_operator=; Path=/operator; HttpOnly; SameSite=Strict; Max-Age=0"),))
            if registry and self.path == "/operator/v1/registry":
                if session[1]["role"] != "registry_admin":
                    return self._fail(403, "ADMIN_REQUIRED")
                try:
                    return self._send(200, registry.mutate(session[1]["principal_id"], body))
                except RegistryConflict:
                    return self._fail(409, "REGISTRY_CONFLICT")
                except ValueError:
                    return self._fail(400, "INVALID_REGISTRY_CHANGE")
                except PermissionError:
                    return self._fail(403, "ADMIN_REQUIRED")
                except Exception:
                    return self._fail(503, "REGISTRY_UNAVAILABLE")
            if registry and self.path == "/operator/v1/personal-campaign":
                if session[1]["principal_id"] != "owner.local" or not getattr(registry, "personal_campaign", None):
                    return self._fail(403, "OWNER_REQUIRED")
                try:
                    if set(body) == {"action", "configuration"} and body["action"] == "configure":
                        result = registry.personal_campaign.configure("owner.local", body["configuration"])
                    elif set(body) == {"action"} and body["action"] in ("active", "paused", "closed"):
                        result = registry.personal_campaign.transition("owner.local", body["action"])
                    elif set(body) == {"action"} and body["action"] == "reconcile":
                        result = {"reconciled_attempts": registry.personal_campaign.reconcile_recorded_usage("owner.local")}
                    elif set(body) == {"action"} and body["action"] == "revalidate":
                        result = registry.personal_campaign.revalidate("owner.local")
                    else:
                        return self._fail(400, "INVALID_CAMPAIGN")
                    return self._send(200, result)
                except ValueError:
                    return self._fail(409, "CAMPAIGN_NOT_ELIGIBLE")
                except Exception:
                    return self._fail(503, "CAMPAIGN_UNAVAILABLE")
            if registry and self.path == "/operator/v1/provider-credential":
                if session[1]["role"] != "registry_admin":
                    return self._fail(403, "ADMIN_REQUIRED")
                if set(body) != {"operation_id", "connection_id", "expected_revision", "mode", "secret"}:
                    return self._fail(400, "INVALID_BODY")
                try:
                    return self._send(200, registry.set_provider_credential(session[1]["principal_id"],
                        body["connection_id"], body["expected_revision"], body["operation_id"],
                        body["mode"], body["secret"]))
                except RegistryConflict:
                    return self._fail(409, "REGISTRY_CONFLICT")
                except ValueError:
                    return self._fail(400, "INVALID_CREDENTIAL_CHANGE")
                except PermissionError:
                    return self._fail(403, "ADMIN_REQUIRED")
                except Exception:
                    return self._fail(503, "CREDENTIAL_UNAVAILABLE")
            if registry and self.path == "/operator/v1/provider-probe":
                if session[1]["role"] != "registry_admin":
                    return self._fail(403, "ADMIN_REQUIRED")
                if set(body) != {"operation_id", "connection_id", "expected_revision", "operation"}:
                    return self._fail(400, "INVALID_BODY")
                try:
                    return self._send(200, registry.probe_connection(session[1]["principal_id"],
                        body["connection_id"], body["expected_revision"], body["operation_id"], body["operation"]))
                except RegistryConflict:
                    return self._fail(409, "REGISTRY_CONFLICT")
                except ValueError:
                    return self._fail(400, "INVALID_PROBE")
                except PermissionError:
                    return self._fail(403, "ADMIN_REQUIRED")
                except Exception:
                    return self._fail(503, "PROBE_UNAVAILABLE")
            if registry and self.path == "/operator/v1/provider-validation":
                if session[1]["role"] != "registry_admin":
                    return self._fail(403, "ADMIN_REQUIRED")
                if (not provider_validation or not registry.provider_execution_ready or
                        set(body) != {"operation_id", "connection_id", "connection_revision",
                                      "configuration_ref", "configuration_revision",
                                      "max_output_tokens", "acknowledge_external_send"} or
                        body["acknowledge_external_send"] is not True or
                        type(body["max_output_tokens"]) is not int or
                        not 1 <= body["max_output_tokens"] <= 32 or
                        type(body["connection_revision"]) is not int or
                        type(body["configuration_revision"]) is not int):
                    return self._fail(400, "INVALID_VALIDATION_REQUEST")
                try:
                    previous = projection.provider_validation(body["operation_id"])
                    if previous:
                        if any(previous[key] != body[key] for key in (
                                "connection_id", "connection_revision", "configuration_ref",
                                "configuration_revision", "max_output_tokens")):
                            return self._fail(409, "VALIDATION_OPERATION_CONFLICT")
                        return self._send(200, previous)
                    connection = registry.connection(body["connection_id"])
                    model = registry.model(body["configuration_ref"])
                    campaign = getattr(registry, "personal_campaign", None)
                    allowance = campaign.summary() if campaign else None
                    if (not connection or not model or
                            connection["revision"] != body["connection_revision"] or
                            model["revision"] != body["configuration_revision"] or
                            model["destination"].get("connection_id") != body["connection_id"] or
                            model["destination"].get("adapter_id") != "openai.responses.v1" or
                            (campaign and (allowance["effective_state"] != "active" or
                                allowance["connection_id"] != body["connection_id"] or
                                allowance["configuration_ref"] != body["configuration_ref"] or
                                allowance["principal_id"] != session[1]["principal_id"] or
                                body["max_output_tokens"] > allowance["max_output_tokens"])) or
                            not registry.explain(session[1]["principal_id"] if getattr(registry, "personal_campaign", None)
                                else provider_validation.principal_id,
                                body["configuration_ref"], "execution", "class.demo")["allowed"]):
                        return self._fail(409, "VALIDATION_NOT_ELIGIBLE")
                    fresh = projection.begin_provider_validation(body["operation_id"],
                        body["connection_id"], body["connection_revision"],
                        body["configuration_ref"], body["configuration_revision"],
                        body["max_output_tokens"])
                    if not fresh:
                        return self._send(200, projection.provider_validation(body["operation_id"]))
                except ValueError:
                    return self._fail(409, "VALIDATION_OPERATION_CONFLICT")
                except Exception:
                    return self._fail(503, "VALIDATION_UNAVAILABLE")
                live_candidate = None
                try:
                    result = provider_validation.run(body["configuration_ref"], body["operation_id"],
                        body["max_output_tokens"], lambda sid:
                            projection.record_provider_validation_submission(body["operation_id"], sid),
                        **({"token": session[1]["wire_token"]} if session[1].get("wire_token") else {}))
                    state = result["state"] if type(result) is dict else result
                    projection.finish_provider_validation(body["operation_id"], state)
                    live_candidate = result.get("candidate") if type(result) is dict else None
                except Exception as exc:
                    handle = getattr(exc, "handle", None)
                    if type(handle) is dict and type(handle.get("submission_id")) is str:
                        projection.record_provider_validation_submission(body["operation_id"],
                            handle["submission_id"])
                    code = getattr(exc, "code", None)
                    state = ("failed" if code and getattr(exc, "retry_guidance", None) == "never"
                             else "outcome_unknown")
                    projection.finish_provider_validation(body["operation_id"], state,
                        code if type(code) is str else "VALIDATION_UNAVAILABLE")
                response = projection.provider_validation(body["operation_id"])
                if live_candidate is not None:
                    response = {**response, "live_candidate": live_candidate}
                    if response.get("submission_id"):
                        response["provider_model_reported"] = projection.detail(
                            response["submission_id"], "*").get("provider_model_reported")
                return self._send(200, response)
            if registry and self.path == "/operator/v1/provision":
                if session[1]["role"] != "registry_admin":
                    return self._fail(403, "ADMIN_REQUIRED")
                if set(body) != {"operation_id", "principal_id", "expected_revision"}:
                    return self._fail(400, "INVALID_BODY")
                try:
                    record, secret = registry.provision_credential(session[1]["principal_id"],
                        body["principal_id"], body["expected_revision"], body["operation_id"])
                    return self._send(200, {"record": record, "one_time_credential": secret})
                except RegistryConflict:
                    return self._fail(409, "REGISTRY_CONFLICT")
                except ValueError:
                    return self._fail(400, "INVALID_REGISTRY_CHANGE")
                except Exception:
                    return self._fail(503, "REGISTRY_UNAVAILABLE")
            if self.path.startswith("/operator/v1/demos/"):
                if registry and session[1]["role"] != "registry_admin":
                    return self._fail(403, "ADMIN_REQUIRED")
                kind = self.path.rsplit("/", 1)[1]
                if set(body) != {"operation_id"} or kind not in ("text", "tool", "no_store_text"):
                    return self._fail(400, "INVALID_BODY")
                try:
                    fresh = projection.begin_launch(body["operation_id"], kind)
                    if fresh:
                        jobs.submit(execute, body["operation_id"], kind)
                    return self._send(202, projection.launch(body["operation_id"]))
                except (ValueError, TypeError):
                    return self._fail(409, "INVALID_OPERATION")
            return self._fail(404, "NOT_FOUND")

    if socket_path is None:
        server = ThreadingHTTPServer((host, port), Handler)
    else:
        class UnixHTTPServer(ThreadingHTTPServer):
            address_family = socket.AF_UNIX

            def server_bind(self):
                socketserver.TCPServer.server_bind(self)
                self.server_name = "localhost"
                self.server_port = port

        server = UnixHTTPServer(socket_path, Handler)
        os.chmod(socket_path, 0o600)
    server.daemon_threads = True
    server.operator_jobs = jobs
    scheduler_stop = threading.Event()
    def scheduled_checks():
        due = {}
        while not scheduler_stop.wait(2):
            try:
                connections = registry.list_connections() if registry else []
            except Exception:
                continue
            active = set()
            for connection in connections:
                if not connection.get("checks_scheduled") or connection["status"] not in ("draft", "active"):
                    continue
                key = connection["connection_id"]
                active.add(key)
                now = time.monotonic()
                interval = connection["check_interval_seconds"]
                state = (connection["revision"], connection["scheduled_operation"])
                if key not in due or due[key][0] != state:
                    due[key] = (state, now + interval)
                    continue
                if now < due[key][1]:
                    continue
                due[key] = (state, now + interval)
                try:
                    registry.probe_connection("owner.local", key, connection["revision"],
                        "probe.scheduled." + uuid.uuid4().hex, connection["scheduled_operation"])
                except Exception:
                    pass  # The next bounded interval may record a new observation.
            for key in set(due) - active:
                due.pop(key, None)
    scheduler_thread = threading.Thread(target=scheduled_checks, daemon=True,
                                        name="duranki-provider-checks")
    scheduler_thread.start()
    original_close = server.server_close
    def close_with_scheduler():
        scheduler_stop.set()
        scheduler_thread.join(timeout=4)
        original_close()
    server.server_close = close_with_scheduler
    return server
