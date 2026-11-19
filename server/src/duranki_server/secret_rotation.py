"""Offline encryption maintenance. Stop services using the database before running."""
from __future__ import annotations

from .repositories import secret_rotation as _queries

import argparse
from contextlib import closing
import json
from pathlib import Path
import sys

from .integration_credentials import reencrypt_credentials
from .local_connectors import connector_key_path, reencrypt_connectors
from .observability import configure_logging, log_failure
from .provider_vault import ProviderVault
from .secret_box import SecretBox
from .store import SQLiteStore


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("rotate", "resume"))
    parser.add_argument("--scope", required=True, choices=("integration", "provider", "connectors"))
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--keyring", type=Path)
    parser.add_argument("--vault", type=Path)
    args = parser.parse_args(argv)
    if not args.db.is_absolute() or args.db.is_symlink() or not args.db.is_file():
        parser.error("an existing absolute database path is required")
    if args.scope == "integration" and not args.keyring:
        parser.error("--keyring is required for integration credentials")
    if args.scope == "provider" and not args.vault:
        parser.error("--vault is required for provider credentials")
    for path in (args.keyring, args.vault):
        if path is not None and (not path.is_absolute() or path.is_symlink() or not path.exists()):
            parser.error("keyring/vault paths must be existing absolute paths")
    if (args.scope == "provider" and args.keyring) or (args.scope != "provider" and args.vault):
        parser.error("use --vault for provider scope, --keyring for database scopes")
    configure_logging()
    try:
        with closing(SQLiteStore.open_existing(args.db)) as store:
            if args.scope == "provider":
                identifiers = [json.loads(row[0])["connection_id"] for row in store.database.execute(
                    _queries.MAIN_SELECT_REGISTRY_CONNECTIONS)]
                vault = ProviderVault(args.vault, require_existing=True)
                box = vault.box
                rewrite = lambda: vault.reencrypt_secrets(identifiers)
            elif args.scope == "integration":
                known = {row[0] for row in store.database.execute(
                    _queries.MAIN_SELECT_INTEGRATION_CREDENTIAL_VERSIONS)}
                box = SecretBox(args.keyring, "integration-credentials", required_ids=known, required=True)
                rewrite = lambda: reencrypt_credentials(store, box)
            else:
                known = {json.loads(row[0])["key_id"] for row in store.database.execute(
                    _queries.MAIN_SELECT_LOCAL_CONNECTORS)}
                path = args.keyring or connector_key_path(store.path)
                box = SecretBox(path, "local-connector-credentials", required_ids=known, required=True)
                rewrite = lambda: reencrypt_connectors(store, box)
            if args.action == "rotate":
                box.rotate()
            result = {"scope": args.scope, "key_id": box.active_id, "rewritten": rewrite()}
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        log_failure("secret_rotation.failed")
        print("Encryption maintenance failed; restore missing key material or fix the fault, then use resume.",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
