"""Local API discovery, destination controls, encrypted keys, and durable selections."""
import copy
import io
import json
import socket
import ssl
import unittest
from unittest.mock import patch

from tests.operator_console.test_user_management import UserFixture
from ezllmrouter_server.local_connectors import (
    ConnectorError, KINDS, LocalConnectors, MAX_RESPONSE, _read_json,
    allowed_address, discover, normalize_url,
)


INVENTORY = {"models": [{"name": "llama3.2:latest", "model": "llama3.2:latest", "size": 2019393189,
    "digest": "sha256:synthetic", "modified_at": "2026-11-18T12:00:00Z",
    "details": {"family": "llama", "format": "gguf", "parameter_size": "3.2B", "quantization_level": "Q4_K_M"}},
    {"name": "qwen3:8b", "size": 5200000000}]}


class LocalFixture(UserFixture):
    def setUp(self):
        super().setUp()
        self.calls = []
        self.inventory = copy.deepcopy(INVENTORY)
        def read(url, path, key):
            self.calls.append((url, path, key))
            if path == "/api/tags":
                return copy.deepcopy(self.inventory)
            if path == "/api/ps":
                return {"models": [{"name": "llama3.2:latest", "size_vram": 3100000000}]}
            if path == "/api/version":
                return {"version": "0.12.0"}
            return {"data": [{"id": "local/model:exact", "owned_by": "local-server", "max_model_len": 32768}]}
        self.reader = read
        self.connectors = LocalConnectors(self.registry,
            discover_fn=lambda kind, url, key: discover(kind, url, key, read=self.reader))
        self.addCleanup(self.connectors.close)

    def connector(self, **changes):
        body = {"display_name": "Office Ollama", "kind": "ollama", "base_url": "http://localhost:11434"}
        body.update(changes)
        return self.connectors.create("owner.local", body)

    def discover_connector(self, item):
        return self.connectors.discover("owner.local", item["connector_id"], {"expected_revision": item["revision"]})

    def select(self, item, enabled=True, models=None):
        return self.connectors.configure("owner.local", item["connector_id"], {"expected_revision": item["revision"],
            "selected_models": models if models is not None else ["llama3.2:latest"], "enabled": enabled})


class LocalConnectorTests(LocalFixture):
    def test_create_and_browse_do_not_make_network_requests(self):
        item = self.connector()
        self.assertEqual(self.calls, [])
        self.assertFalse(item["enabled"])
        self.assertEqual(self.connectors.get("owner.local", item["connector_id"])["discovery"]["state"], "not_checked")
        self.connectors.list("owner.local")
        self.assertEqual(self.calls, [])

    def test_ollama_inventory_and_loaded_models_use_metadata_gets(self):
        item = self.discover_connector(self.connector())
        discovery = item["discovery"]
        self.assertEqual([path for _, path, _ in self.calls], ["/api/tags", "/api/ps", "/api/version"])
        self.assertEqual(discovery["server_version"], "0.12.0")
        model = discovery["models"][0]
        self.assertEqual((model["id"], model["parameter_size"], model["quantization"]), ("llama3.2:latest", "3.2B", "Q4_K_M"))
        self.assertTrue(model["loaded"])
        self.assertEqual(model["vram_bytes"], 3100000000)
        self.assertFalse(discovery["models"][1]["loaded"])
        self.assertFalse(item["enabled"], "discovery cannot enable model use")
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0], 0)

    def test_other_server_profiles_use_openai_model_inventory(self):
        for kind in KINDS:
            if kind == "ollama":
                continue
            with self.subTest(kind=kind):
                self.calls.clear()
                item = self.discover_connector(self.connector(kind=kind, base_url="http://local-server:8000/v1"))
                self.assertEqual([path for _, path, _ in self.calls], ["/v1/models"])
                self.assertEqual(item["discovery"]["models"][0]["id"], "local/model:exact")
                self.assertEqual(item["discovery"]["models"][0]["context_window"], 32768)
                self.assertIsNone(item["discovery"]["models"][0]["loaded"])

    def test_model_selection_and_disabled_state_survive_reopen(self):
        item = self.select(self.discover_connector(self.connector()))
        self.assertTrue(item["usable"])
        reopened = LocalConnectors(self.registry)
        self.addCleanup(reopened.close)
        self.assertTrue(reopened.get("owner.local", item["connector_id"])["usable"])
        item = self.select(item, enabled=False)
        self.assertEqual(item["status"], "disabled")
        self.assertFalse(reopened.get("owner.local", item["connector_id"])["enabled"])

    def test_selection_requires_complete_fresh_inventory_and_exact_ids(self):
        item = self.connector()
        with self.assertRaises(ConnectorError):
            self.select(item)
        self.inventory["has_more"] = True
        item = self.discover_connector(item)
        with self.assertRaises(ConnectorError):
            self.select(item)
        self.inventory.pop("has_more")
        item = self.discover_connector(item)
        with self.assertRaises(ConnectorError):
            self.select(item, models=["model.not-discovered"])
        self.assertTrue(self.select(item)["usable"])

    def test_endpoint_and_key_changes_clear_previous_inventory_and_selections(self):
        item = self.select(self.discover_connector(self.connector()))
        item = self.connectors.update("owner.local", item["connector_id"], {
            "display_name": item["display_name"], "kind": "ollama", "base_url": "http://ollama:11434",
            "expected_revision": item["revision"]})
        self.assertEqual(item["discovery"]["state"], "not_checked")
        self.assertEqual(item["selected_models"], [])
        self.assertFalse(item["enabled"])

    def test_api_key_is_encrypted_and_bound_to_the_connector(self):
        secret = "private-local-connector-api-key"
        item = self.discover_connector(self.connector(api_key=secret))
        self.assertTrue(all(key == secret for _, _, key in self.calls))
        self.assertNotIn(secret, json.dumps(item))
        self.assertNotIn(secret, "\n".join(self.store.db.iterdump()))
        sealed = self.store.db.execute("SELECT secret FROM local_connectors WHERE id=?", (item["connector_id"],)).fetchone()[0]
        other = self.connector()
        self.store.db.execute("UPDATE local_connectors SET secret=? WHERE id=?", (sealed, other["connector_id"]))
        failed = self.discover_connector(other)
        self.assertEqual(failed["discovery"]["reason"], "CREDENTIAL_UNAVAILABLE")

    def test_address_change_does_not_forward_an_existing_api_key(self):
        item = self.connector(api_key="original-endpoint-private-key")
        item = self.connectors.update("owner.local", item["connector_id"], {
            "display_name": "New endpoint", "kind": "ollama", "base_url": "http://another-container:11434",
            "expected_revision": item["revision"]})
        self.assertFalse(item["credential_present"])
        self.discover_connector(item)
        self.assertTrue(all(key == "" for _, _, key in self.calls))

    def test_missing_key_does_not_replace_or_erase_encrypted_credentials(self):
        item = self.connector(api_key="private-api-key-for-container")
        sealed = self.store.db.execute("SELECT secret FROM local_connectors WHERE id=?", (item["connector_id"],)).fetchone()[0]
        self.connectors.key_path.unlink()
        failed = self.discover_connector(item)
        self.assertEqual(failed["discovery"]["reason"], "CREDENTIAL_UNAVAILABLE")
        self.assertEqual(self.store.db.execute("SELECT secret FROM local_connectors WHERE id=?", (item["connector_id"],)).fetchone()[0], sealed)
        self.assertEqual(self.calls, [])
        with self.assertRaises(ConnectorError):
            self.connector(api_key="another-api-key-for-container")

    def test_remote_credential_error_is_recorded_without_exposing_provider_text(self):
        self.connectors.discover_fn = lambda *_: (_ for _ in ()).throw(ConnectorError("SERVER_AUTHENTICATION_REQUIRED", 502))
        item = self.discover_connector(self.connector())
        self.assertEqual(item["discovery"]["state"], "failed")
        self.assertEqual(item["discovery"]["reason"], "SERVER_AUTHENTICATION_REQUIRED")

    def test_concurrent_setting_change_prevents_stale_discovery_commit(self):
        item = self.connector()
        def changed(kind, url, key):
            self.connectors.update("owner.local", item["connector_id"], {
                "display_name": "Moved", "kind": kind, "base_url": "http://ollama:11434",
                "expected_revision": item["revision"]})
            return discover(kind, url, key, read=self.reader)
        self.connectors.discover_fn = changed
        with self.assertRaises(ConnectorError) as exc:
            self.discover_connector(item)
        self.assertEqual(exc.exception.code, "CONNECTOR_CHANGED")
        self.assertEqual(self.connectors.get("owner.local", item["connector_id"])["discovery"]["state"], "not_checked")

    def test_removed_models_do_not_remain_usable(self):
        item = self.select(self.discover_connector(self.connector()))
        self.inventory["models"] = self.inventory["models"][1:]
        item = self.discover_connector(item)
        self.assertFalse(item["usable"])
        self.assertEqual(item["status"], "needs_attention")
        self.assertFalse(self.select(item, enabled=False)["enabled"])

    def test_readonly_can_inspect_but_cannot_change_or_discover(self):
        viewer = self.create("viewer", "read_only_operator")["principal_id"]
        ordinary = self.create("regular")["principal_id"]
        item = self.connector()
        self.assertEqual(len(self.connectors.list(viewer)["items"]), 1)
        for actor in (viewer, ordinary):
            with self.assertRaises(ConnectorError) as exc:
                self.connectors.discover(actor, item["connector_id"], {"expected_revision": item["revision"]})
            self.assertEqual(exc.exception.status, 403)
        with self.assertRaises(ConnectorError):
            self.connectors.list(ordinary)
        self.assertEqual(self.calls, [])

    def test_deleted_connector_loses_key_and_does_not_modify_container(self):
        item = self.connector(api_key="private-key-for-removal-test")
        self.connectors.delete("owner.local", item["connector_id"], {"expected_revision": item["revision"]})
        self.assertEqual(self.connectors.list("owner.local")["items"], [])
        self.assertIsNone(self.store.db.execute("SELECT secret FROM local_connectors").fetchone()[0])
        self.assertEqual(self.calls, [])

    def test_optional_ollama_metadata_failure_preserves_installed_inventory(self):
        def read(url, path, key):
            if path != "/api/tags":
                raise ConnectorError("DISCOVERY_ENDPOINT_NOT_FOUND", 502)
            return INVENTORY
        result = discover("ollama", "http://localhost:11434", read=read)
        self.assertEqual(result["state"], "observed")
        self.assertEqual(len(result["models"]), 2)
        self.assertIsNone(result["models"][0]["loaded"])
        self.assertEqual(len(result["warnings"]), 2)

    def test_duplicate_and_secret_echo_models_are_rejected(self):
        for value in ({"models": [{"name": "duplicate"}, {"name": "duplicate"}]},
                      {"models": [{"name": "server-echoes-private-secret-key"}]},
                      {"models": [{"name": "\ud800"}]}):
            with self.assertRaises(ConnectorError):
                discover("ollama", "http://localhost:11434", "private-secret-key", read=lambda *_: value)

    def test_optional_metadata_matching_a_local_token_is_redacted(self):
        result = discover("openai_compatible", "http://localhost:8000", "local",
            read=lambda *_: {"data": [{"id": "llama3.2", "owned_by": "local"}]})
        self.assertEqual(result["state"], "observed")
        self.assertIsNone(result["models"][0]["owned_by"])


class FakeSocket:
    def __init__(self):
        self.sent, self.address, self.closed = b"", None, False
    def settimeout(self, value):
        pass
    def connect(self, address):
        self.address = address
    def sendall(self, data):
        self.sent += data
    def close(self):
        self.closed = True


class FakeResponse:
    def __init__(self, data=b'{"data":[]}', status=200, **headers):
        self.status, self.length = status, len(data)
        self.headers = {"Content-Type": "application/json", **headers}
        self.data = io.BytesIO(data)
    def begin(self):
        pass
    def getheader(self, name, default=None):
        return self.headers.get(name, default)
    def read1(self, count):
        return self.data.read(count)


class LocalTransportTests(unittest.TestCase):
    def test_url_and_address_scope(self):
        for address in ("127.0.0.1", "10.2.3.4", "172.17.0.2", "192.168.65.254", "::1", "fd00::1"):
            self.assertTrue(allowed_address(address), address)
        for address in ("0.0.0.0", "169.254.169.254", "8.8.8.8", "224.0.0.1", "::", "::ffff:169.254.169.254"):
            self.assertFalse(allowed_address(address), address)
        self.assertEqual(normalize_url("http://ollama:11434/", "ollama"), "http://ollama:11434")
        self.assertEqual(normalize_url("http://[::1]:11434"), "http://[::1]:11434")
        for url in ("file:///etc/passwd", "http://user:secret@localhost", "http://localhost?key=secret",
                    "http://localhost/#fragment", "http://8.8.8.8:8000", "http://localhost:0", "http://localhost/other-api"):
            with self.assertRaises(ConnectorError, msg=url):
                normalize_url(url)

    def call(self, response, *, addresses=None, url="http://localhost:8000/v1", secret=""):
        sock = FakeSocket()
        addresses = addresses or [(2, 1, 6, "", ("127.0.0.1", 8000))]
        with patch("ezllmrouter_server.local_connectors.socket.getaddrinfo", return_value=addresses), \
                patch("ezllmrouter_server.local_connectors.socket.socket", return_value=sock) as connect, \
                patch("ezllmrouter_server.local_connectors.http.client.HTTPResponse", return_value=response):
            result = _read_json(url, "/v1/models", secret)
        return result, sock, connect

    def test_dns_is_pinned_and_request_is_fixed_read_only(self):
        result, sock, _ = self.call(FakeResponse(), secret="local-test-token")
        self.assertEqual(result, {"data": []})
        self.assertEqual(sock.address, ("127.0.0.1", 8000))
        self.assertTrue(sock.sent.startswith(b"GET /v1/models HTTP/1.1\r\n"))
        self.assertIn(b"Authorization: Bearer local-test-token\r\n", sock.sent)
        self.assertTrue(sock.closed)

    def test_public_or_metadata_dns_answer_is_rejected_before_connect(self):
        for address in ("169.254.169.254", "8.8.8.8"):
            with patch("ezllmrouter_server.local_connectors.socket.getaddrinfo", return_value=[
                    (2, 1, 6, "", ("127.0.0.1", 8000)), (2, 1, 6, "", (address, 8000))]), \
                    patch("ezllmrouter_server.local_connectors.socket.socket") as sock:
                with self.assertRaises(ConnectorError):
                    _read_json("http://container-name:8000", "/v1/models", "")
                sock.assert_not_called()

    def test_redirect_auth_and_content_failures_do_not_return_server_body(self):
        for response, expected in ((FakeResponse(status=302), "REDIRECT_NOT_ALLOWED"),
                (FakeResponse(status=401), "SERVER_AUTHENTICATION_REQUIRED"),
                (FakeResponse(**{"Content-Type": "text/html"}), "INVALID_SERVER_RESPONSE"),
                (FakeResponse(**{"Content-Encoding": "gzip"}), "COMPRESSED_RESPONSE_NOT_SUPPORTED"),
                (FakeResponse(b'{"data":[],"data":[]}'), "INVALID_SERVER_RESPONSE")):
            with self.assertRaises(ConnectorError) as exc:
                self.call(response)
            self.assertEqual(exc.exception.code, expected)

    def test_response_limit_and_unapproved_path(self):
        with self.assertRaises(ConnectorError) as exc:
            self.call(FakeResponse(b" " * (MAX_RESPONSE + 1)))
        self.assertEqual(exc.exception.code, "SERVER_RESPONSE_TOO_LARGE")
        streamed = FakeResponse(b" " * (MAX_RESPONSE + 1))
        streamed.length = None
        with self.assertRaises(ConnectorError) as exc:
            self.call(streamed)
        self.assertEqual(exc.exception.code, "SERVER_RESPONSE_TOO_LARGE")
        with self.assertRaises(ConnectorError):
            _read_json("http://localhost:11434", "/api/pull", "")

    def test_https_preserves_certificate_validation_and_hostname(self):
        raw, tls = FakeSocket(), FakeSocket()
        with patch("ezllmrouter_server.local_connectors.socket.getaddrinfo", return_value=[
                (2, 1, 6, "", ("192.168.1.20", 443))]), \
                patch("ezllmrouter_server.local_connectors.socket.socket", return_value=raw), \
                patch("ezllmrouter_server.local_connectors.ssl.create_default_context") as context, \
                patch("ezllmrouter_server.local_connectors.http.client.HTTPResponse", return_value=FakeResponse()):
            context.return_value.wrap_socket.return_value = tls
            _read_json("https://model-server.local", "/v1/models", "private-token")
        context.assert_called_once_with()
        context.return_value.wrap_socket.assert_called_once_with(raw, server_hostname="model-server.local")
        self.assertEqual(raw.sent, b"")
        self.assertIn(b"Authorization: Bearer private-token", tls.sent)
        self.assertTrue(raw.closed and tls.closed)

    def test_dns_and_tls_errors_are_classified_without_echoing_exceptions(self):
        with patch("ezllmrouter_server.local_connectors.socket.getaddrinfo", side_effect=socket.gaierror("private diagnostic")):
            with self.assertRaises(ConnectorError) as exc:
                _read_json("http://container-name:11434", "/api/tags", "")
        self.assertEqual(exc.exception.code, "SERVER_NAME_NOT_RESOLVED")
        raw = FakeSocket()
        with patch("ezllmrouter_server.local_connectors.socket.getaddrinfo", return_value=[
                (2, 1, 6, "", ("127.0.0.1", 443))]), \
                patch("ezllmrouter_server.local_connectors.socket.socket", return_value=raw), \
                patch("ezllmrouter_server.local_connectors.ssl.create_default_context") as context:
            context.return_value.wrap_socket.side_effect = ssl.SSLCertVerificationError("private diagnostic")
            with self.assertRaises(ConnectorError) as exc:
                _read_json("https://localhost", "/v1/models", "")
        self.assertEqual(exc.exception.code, "SERVER_TLS_FAILED")
        self.assertTrue(raw.closed)
