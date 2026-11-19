# Encryption keys and rotation

This is the initial encryption format for a new installation. There are no
earlier-format readers, shared master keys, automatic imports or data migrations.

Each credential store uses `SecretBox` with an independently generated keyring:

| Store | Purpose | Keyring location |
| --- | --- | --- |
| Integration provider accounts | `integration-credentials` | `SECRETS_DIR/integration.keys.json` |
| Local connectors | `local-connector-credentials` | `DATABASE_PATH.secrets/local-connectors.keys.json` |
| Execution provider vault | `provider-credentials` | `VAULT_DIR/provider.keys.json` |

Keyrings are owner-only JSON files, saved atomically with mode `0600` inside
directories with mode `0700`. They contain a current AES-256-GCM encryption key,
its identifier, retained encryption keys, and an independent HMAC key for request
idempotency. No store borrows key material from another store. Encryption rotation
keeps the HMAC key stable so retries still match their original operation.

Every encryption uses a random 12-byte nonce. Authenticated associated data binds
the format version, purpose, key identifier and record identity. Integration
credentials additionally bind their version and provider; vault credentials bind
their connection and version. Swapping a ciphertext between records, purposes or
versions fails authentication. Missing keys and malformed files fail closed;
existing ciphertext never causes a replacement keyring to be generated.

## Rotate a write key and re-encrypt stored credentials

Stop services and other maintenance commands using the instance, then back up
its database, keyrings and vault files together. Run maintenance in the same
Python environment as the server. For the instance created by `start.sh`, from
the repository root:

```sh
uv run --project server --frozen --no-python-downloads \
  python -m ezllmrouter_server.secret_rotation rotate \
  --scope integration \
  --db "$PWD/local-instance/service.sqlite" \
  --keyring "$PWD/local-instance/secrets/integration.keys.json"

uv run --project server --frozen --no-python-downloads \
  python -m ezllmrouter_server.secret_rotation rotate \
  --scope connectors \
  --db "$PWD/local-instance/service.sqlite"
```

The provider vault belongs to the execution profile. Run its maintenance inside
the service environment, with that service stopped and its data volume available:

```sh
python -m ezllmrouter_server.secret_rotation rotate \
  --scope provider --db /data/store.sqlite --vault /data/provider-vault
```

Use the actual database path configured for that profile. `--keyring` can override
the connector keyring location for a separately configured connector store.
The command requires existing absolute paths and does not initialize an instance,
register accounts, discover models or call a provider. Its output contains only
the scope, active key identifier and number of rewritten secrets.

Rotation publishes the new write key durably before rewriting ciphertext.
Database rewrites commit in one transaction per store. Vault files are replaced
atomically one at a time. Credential versions, account/connector revisions,
permissions, history and idempotency records stay unchanged.

If maintenance is interrupted, correct the reported fault and run the same
command with `resume` in place of `rotate`. Resume uses the already active key;
it does not generate another key. A completed resume reports zero rewrites when
all records already use that key. The keyring retains predecessors so partially
rewritten data and older backups remain decryptable. Automatic key deletion and
HMAC-key rotation are outside this command.

## Back up and restore an instance

With the service and maintenance stopped, preserve the database, its
`DATABASE_PATH.secrets` directory, the configured integration secrets directory,
and the entire provider vault when present. Restore them as one consistent set,
keeping their private permissions. A SQLite-only backup does not contain the
decryption keys. Never put these files in Git or an evidence export; generated
default keyring names, lock files and sealed credentials are ignored by the
repository and excluded from runtime evidence capture. Keep custom keyring paths
outside the source and evidence trees as well.
