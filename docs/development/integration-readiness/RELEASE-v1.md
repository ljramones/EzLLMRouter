# Duranki external accounting local release 0.1.0

This private local release implements Duranki integration contract v1, recorded in the repository at `docs/contracts/integration-readiness-v1/CONTRACT.md`. It runs an accounting-only Duranki service with no model worker, sender, provider credential or execution route. The examples are synthetic. It does not activate a real Vega collection dataset or alter the owner profile.

## Compatibility and boundaries

| Component | Version | Supported runtime |
| --- | --- | --- |
| Integration HTTP contract | 1 | `Duranki-Integration-Version: 1` on `/integration/v1/` |
| Service `mach33-duranki-server` | 0.1.0 | CPython 3.12 |
| Python `mach33-duranki-client` | 0.1.0 | CPython 3.12; frozen `httpx==0.28.1` dependency |
| JavaScript `@mach33/duranki-client` | 0.1.0 | Node.js 24 (`>=24 <25`) |

The inspected Vega checkout at `e69a1fce53917603d110bdd386bde1547a82196d` declares Node 24; no Python runtime declaration was found in its top three directory levels. The interface accepts credential-manager references, never the referenced provider secret. Account eligibility is a versioned read; Vega must enforce it before selecting a provider in the following milestone. The HTTP clients do not retry model work or observation delivery automatically. On an unknown delivery outcome, recover the receipt, then redeliver the **same** observation and ID if absent.

## Clean local installation

Use the exact 0.1.0 files in this private release and verify them against its adjacent `MANIFEST.sha256`. The service wheel and `web/` directory are supplied together in the ZIP. These commands create a **new isolated** local instance; choose unused loopback ports and a new directory. They are not an owner-profile update.

```sh
RELEASE_ZIP=/absolute/private/duranki-integration-service-0.1.0.zip
RELEASE_DIR=/absolute/private/duranki-integration-release
INSTANCE_DIR=/absolute/private/duranki-integration-instance
mkdir -p "$RELEASE_DIR" "$INSTANCE_DIR"
unzip -q "$RELEASE_ZIP" -d "$RELEASE_DIR"
/opt/homebrew/bin/python3.12 -m venv "$INSTANCE_DIR/service-venv"
"$INSTANCE_DIR/service-venv/bin/python" -m pip install --no-index --no-deps \
  "$RELEASE_DIR/packages/mach33_duranki_server-0.1.0-py3-none-any.whl"
"$INSTANCE_DIR/service-venv/bin/python" -m duranki_server.integration_local \
  --db "$INSTANCE_DIR/accounting.sqlite" --secrets-dir "$INSTANCE_DIR/secrets" \
  --web-root "$RELEASE_DIR/web" --api-port 48760 --operator-port 48761
```

The service binds only `127.0.0.1`. It generates an owner-only operator password, owner API token and ingest token in `secrets/`; protect that directory. On restart, use the same DB, secrets directory and web root. A new database creates a new isolated namespace and requires an explicit dataset activation via the authenticated API or operator UI. The service rejects a DB whose original ingest token file is missing. It does not provision a provider secret or perform a connection test.

For a consistent online SQLite backup, run the same installed module with `--db /absolute/path/accounting.sqlite --backup /absolute/new/path/backup.sqlite`. Keep the associated secret directory in a protected backup. Restore to a new private instance by copying the backup DB and the associated secrets; point the service at that DB and a clean installation of the same tested build. Do not overwrite a running database file. Schema migrations are additive and automatically applied at startup; unknown future schema versions are rejected.

The bundle includes the exact frozen Python client dependency wheels and [hash lock](client-requirements.lock). Install clean consumers from the private release without a registry:

```sh
/opt/homebrew/bin/python3.12 -m venv "$INSTANCE_DIR/client-venv"
"$INSTANCE_DIR/client-venv/bin/python" -m pip install --no-index \
  --find-links "$RELEASE_DIR/packages" --require-hashes \
  -r "$RELEASE_DIR/client-requirements.lock"
PATH=/absolute/path/to/node24/bin:$PATH /absolute/path/to/node24/bin/npm install \
  --prefix "$INSTANCE_DIR/node-consumer" --offline --ignore-scripts --no-audit --no-fund \
  "$RELEASE_DIR/packages/mach33-duranki-client-0.1.0.tgz"
```

Both clients export `IntegrationClient`; examples are in their package READMEs. Their service compatibility is contract v1, not controlled-execution wire 0.2/0.3.

## Remaining limits

This is a local SQLite and loopback release. The 16 MiB client JSON response bound and unpaginated reports limit very large datasets; the next deployment topology must qualify pagination/scale. The operator UI is for account registration, state and reporting; the platform exporter, backlog/loss visibility, real dataset activation and coverage of Vega execution paths remain the following milestone. No historical usage import, learned routing, commercial price claim or production PostgreSQL qualification is included. DEV-12 `CT02-02b` remains open and separate from this observation path.
