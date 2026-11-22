"""Actual database key rotation interrupted only at fixture-owned checkpoints."""

import json
from types import SimpleNamespace
from unittest.mock import patch

from ezllmrouter_server.database import Database
from ezllmrouter_server.local_connectors import LocalConnectors
from ezllmrouter_server.secret_rotation import main as rotate
from tests.operator_console import test_integration_credentials as credentials
from tests.fixtures.schema_upgrades import table_manifest


def seed(root, scope):
    fixture = credentials.CredentialTests()
    with patch.object(
        credentials.tempfile,
        "TemporaryDirectory",
        return_value=SimpleNamespace(name=str(root), cleanup=lambda: None),
    ):
        fixture.setUp()
    if scope == "integration":
        accounts = [fixture.connect(operation=f"op.crash.connect.{index}") for index in range(2)]
        box = fixture.credentials.box
        identities = [value["account_id"] for value in accounts]
    else:
        local = LocalConnectors(fixture.registry)
        identities = [
            local.create(
                "owner.local",
                {
                    "display_name": "Synthetic crash connector",
                    "kind": "ollama",
                    "base_url": "http://localhost:11434",
                    "api_key": f"synthetic-rotation-secret-{index}",
                },
            )["connector_id"]
            for index in range(2)
        ]
        box = local.box
        local.close()
    metadata = {
        "scope": scope,
        "ids": identities,
        "keyring": str(box.path),
        "old_key": box.active_id,
        "digest": box.request_digest(b"synthetic-crash-operation"),
        "db": str(fixture.store.path),
        "before": table_manifest(fixture.store.db),
        "connector_records": list(
            fixture.store.db.execute("SELECT id,record FROM local_connectors ORDER BY id")
        ),
    }
    (root / "rotation.json").write_text(json.dumps(metadata))
    fixture.doCleanups()
    return metadata


def rotation_case(root, scope, point, checkpoint):
    metadata = seed(root, scope)
    execute = Database.execute

    def interrupted(database, query, parameters=()):
        value = execute(database, query, parameters)
        if (
            point == "during_rewrite"
            and query.sql.startswith("UPDATE ")
            and ("integration_credential_versions" in query.sql or "local_connectors" in query.sql)
        ):
            checkpoint()
        return value

    from ezllmrouter_server.secret_box import SecretBox

    publish = SecretBox.rotate

    def after_key(box):
        value = publish(box)
        if point == "after_key_publish":
            checkpoint()
        return value

    from ezllmrouter_server.store import SQLiteStore

    open_store = SQLiteStore.open_existing.__func__

    def observed(cls, *args, **kwargs):
        store = open_store(cls, *args, **kwargs)
        if point == "before_commit":
            store.db.set_trace_callback(lambda sql: checkpoint() if sql == "COMMIT" else None)
        return store

    with (
        patch.object(Database, "execute", interrupted),
        patch.object(SecretBox, "rotate", after_key),
        patch.object(SQLiteStore, "open_existing", classmethod(observed)),
        patch("ezllmrouter_server.secret_rotation.print", create=True),
    ):
        result = rotate(
            ["rotate", "--scope", scope, "--db", metadata["db"], "--keyring", metadata["keyring"]]
        )
    if result != 0:
        raise AssertionError("fixture rotation failed before checkpoint")
    if point == "after_commit":
        checkpoint()
    raise AssertionError("rotation checkpoint was not reached")
