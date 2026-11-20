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
from .secret_box import SecretBox, SecretBoxError
from .instance_lock import InstanceBusy
from .store import SQLiteStore


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("rotate", "resume", "retire"))
    parser.add_argument("--scope", required=True, choices=("integration", "provider", "connectors"))
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--keyring", type=Path)
    parser.add_argument("--vault", type=Path)
    parser.add_argument("--key-id")
    parser.add_argument("--confirm-no-dependent-backups", action="store_true")
    args = parser.parse_args(argv)
    if args.action == "retire":
        if not args.key_id or not args.confirm_no_dependent_backups:
            parser.error("retire requires --key-id and --confirm-no-dependent-backups")
    elif args.key_id or args.confirm_no_dependent_backups:
        parser.error("key retirement options apply only to retire")
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
    retiring = False
    try:
        with closing(SQLiteStore.open_existing(args.db, maintenance=True)) as store:
            if args.scope == "provider":
                identifiers = [
                    json.loads(row[0])["connection_id"]
                    for row in store.database.execute(_queries.MAIN_SELECT_REGISTRY_CONNECTIONS)
                ]
                vault = ProviderVault(args.vault, require_existing=True)
                box = vault.box
                rewrite = lambda **options: vault.reencrypt_secrets(identifiers, **options)
                references = vault.key_references
            elif args.scope == "integration":
                known = {
                    row[0]
                    for row in store.database.execute(
                        _queries.MAIN_SELECT_INTEGRATION_CREDENTIAL_VERSIONS
                    )
                }
                box = SecretBox(
                    args.keyring, "integration-credentials", required_ids=known, required=True
                )
                rewrite = lambda **options: reencrypt_credentials(store, box, **options)
                references = lambda: {
                    row[0]
                    for row in store.database.execute(
                        _queries.MAIN_SELECT_INTEGRATION_CREDENTIAL_VERSIONS
                    )
                }
            else:
                known = {
                    json.loads(row[0])["key_id"]
                    for row in store.database.execute(_queries.MAIN_SELECT_LOCAL_CONNECTORS)
                }
                path = args.keyring or connector_key_path(store.path)
                box = SecretBox(
                    path, "local-connector-credentials", required_ids=known, required=True
                )
                rewrite = lambda **options: reencrypt_connectors(store, box, **options)
                references = lambda: {
                    json.loads(row[0])["key_id"]
                    for row in store.database.execute(_queries.MAIN_SELECT_LOCAL_CONNECTORS)
                }
            if args.action == "rotate":
                box.rotate()
            if args.action == "retire":
                retained = references()
                rewrite(verify_only=True)
                retiring = True
                box.retire_key(args.key_id, referenced_ids=retained, backup_acknowledged=True)
                result = {
                    "scope": args.scope,
                    "key_id": box.active_id,
                    "retired_key_id": args.key_id,
                    "rewritten": 0,
                }
            else:
                result = {"scope": args.scope, "key_id": box.active_id, "rewritten": rewrite()}
        print(json.dumps(result, sort_keys=True))
        return 0
    except InstanceBusy:
        print(
            "Instance is in use; stop services and other maintenance before running.",
            file=sys.stderr,
        )
        return 1
    except SecretBoxError as exc:
        if retiring and str(exc) in {
            "SECRET_KEY_STILL_IN_USE",
            "SECRET_BACKUP_REVIEW_REQUIRED",
            "SECRET_KEY_UNAVAILABLE",
        }:
            print(
                "Key retirement rejected: the key must be retained, inactive and unreferenced; review backup dependencies.",
                file=sys.stderr,
            )
            return 1
        log_failure("secret_rotation.failed")
        print(
            "Encryption maintenance failed; restore the complete key material and use resume.",
            file=sys.stderr,
        )
        return 1
    except Exception:
        log_failure("secret_rotation.failed")
        print(
            "Encryption maintenance failed; restore missing key material or fix the fault, then use resume.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
