# Duranki external accounting local release 0.2.2

**Security update for new JavaScript installations:** use the private 0.2.3 client and verified Node 24.22.1+ on the supported Node 24 line; see the [Node correction and exact tarball identity](../../security/NODE-OCTOBER-2026-FIX-2026-10-28.md). The table and commands below identify the unchanged historical 0.2.2 release archive.

This private local release implements [integration contract v2](../../contracts/integration-readiness-v2/CONTRACT.md). It runs an accounting-only loopback service. It has no model worker, sender, provider credential, or model execution route. The retained [0.1.0](RELEASE-v1.md), [0.2.0](RELEASE-v2.md) and [0.2.1](RELEASE-v3.md) instructions and archives remain historical; v1 HTTP and stored records remain supported by the additive v2 service.

| Component | Version | Runtime |
| --- | --- | --- |
| HTTP integration contract | 2 | `/integration/v2/`, `Duranki-Integration-Version: 2` |
| `mach33-duranki-server` | 0.2.2 | CPython 3.12 |
| `mach33-duranki-client` | 0.2.2 | CPython 3.12; frozen `httpx==0.28.1` |
| `@mach33/duranki-client` | 0.2.2 | Node.js 24 (`>=24 <25`) |

The inspected local Vega checkout declares Node 24. No Python runtime declaration was found in its top three levels. This release records externally executed observations; Vega instrumentation, durable export, selection-time enforcement and the real cohort activation belong to the next milestone. The HTTP clients do not replay model work or automatically redeliver observations. On uncertain delivery, recover the receipt, then redeliver the *same* event ID and body if absent. A real model retry has a distinct attempt ID.

## Exact local installation

Use the exact private `duranki-integration-service-0.2.2.zip` and check its extracted `MANIFEST.sha256`. Choose new private directories and unused loopback ports. The following is a new disposable instance, never an update to the owner profile.

```sh
RELEASE_ZIP=/absolute/private/duranki-integration-service-0.2.2.zip
RELEASE_DIR=/absolute/private/duranki-integration-release-0.2.2
INSTANCE_DIR=/absolute/private/duranki-integration-instance-0.2.2
mkdir -p "$RELEASE_DIR" "$INSTANCE_DIR"
unzip -q "$RELEASE_ZIP" -d "$RELEASE_DIR"
cd "$RELEASE_DIR"
shasum -a 256 -c MANIFEST.sha256
/opt/homebrew/bin/python3.12 -m venv "$INSTANCE_DIR/service-venv"
"$INSTANCE_DIR/service-venv/bin/python" -m pip install --no-index --no-deps \
  "$RELEASE_DIR/packages/mach33_duranki_server-0.2.2-py3-none-any.whl"
"$INSTANCE_DIR/service-venv/bin/python" -m duranki_server.integration_local \
  --db "$INSTANCE_DIR/accounting.sqlite" --secrets-dir "$INSTANCE_DIR/secrets" \
  --web-root "$RELEASE_DIR/web" --api-port 48760 --operator-port 48761
```

The service binds to `127.0.0.1`. It generates protected owner API, ingest and operator credentials in `secrets/`; do not publish them. Use the same database and secrets directory on restart. A new dataset requires explicit authenticated activation. The service rejects a database whose original ingest-token file is missing. No provider secret or connection test is provisioned.

The ZIP includes the exact frozen Python client dependency wheels and `client-requirements.lock`. Install clean clients from this release:

```sh
/opt/homebrew/bin/python3.12 -m venv "$INSTANCE_DIR/client-venv"
"$INSTANCE_DIR/client-venv/bin/python" -m pip install --no-index \
  --find-links "$RELEASE_DIR/packages" --require-hashes \
  -r "$RELEASE_DIR/client-requirements.lock"
PATH=/absolute/path/to/node24/bin:$PATH /absolute/path/to/node24/bin/npm install \
  --prefix "$INSTANCE_DIR/node-consumer" --offline --ignore-scripts --no-audit --no-fund \
  "$RELEASE_DIR/packages/mach33-duranki-client-0.2.2.tgz"
```

Both packages export `IntegrationClient` and include examples in their READMEs. Use contract version `"2"` for the corrected interface. Version 1 remains readable, with absent successor fields explicitly labelled. See the v2 contract for event, snapshot, receipt, account, eligibility, report and export shapes.

This patch release enforces pending v2 lineage constraints when a v1 start arrives and rejects later v2 lineage for an accepted v1 start. Previously accepted contradictory records remain intact and report `binding_conflict`; their unrelated dataset activity can continue. These are compatible admission and reporting corrections. No request schema, client method signature, tariff, account permission or dataset membership rule changed. The clean installed 0.2.2 checks in [RESULT.md](RESULT.md) include both mixed-version arrival orders and a copied 0.2.0 history.

The v2 JSON and CSV report row now includes `usage_state` independently of `cost_status`, plus a server `eligibility_assessment` separate from the caller's immutable eligibility assertion. Dataset export includes eligibility and snapshot-reference assessments. An assessment may be `indeterminate` when second-resolution evidence cannot order a decision and account mutation. An already accepted incompatible lineage or snapshot reference is retained as history but reports `binding_conflict` instead of a trustworthy link or captured content. These are compatible response additions; event IDs, v2 request bodies and client method signatures are unchanged.

## Persistence, migration and feature policy

For a consistent online SQLite backup, run the same installed module with `--db /absolute/path/accounting.sqlite --backup /absolute/new/path/backup.sqlite`. Preserve the corresponding secrets directory in a protected backup. Restore by copying the backup database and those secrets into a separate stopped instance; do not overwrite an active database file. The v1-to-v2 schema migration is additive on startup; an unknown future schema is rejected. Snapshot content expiry is reapplied on startup and reads, including after restoration.

Captured feature content is disabled for real datasets by default. The [proposed retention policy](../../plan/DURANKI-INTEGRATION-FEATURE-RETENTION-POLICY.md) explains the synthetic default and the optional `--feature-policy-file` mechanism. Larry must adopt a real field/classification/source-expiry and backup/export deletion policy before real T0. That decision is separate from qualification of this local interface.

## Boundaries

The local release uses loopback SQLite, a 16 MiB JSON client response bound and unpaginated reports/exports. A chosen deployment topology needs separate database, authentication, scale and persistence qualification. This release makes no commercial tariff claim and does not qualify provider invoices. DEV-12 `CT02-02b` remains open and separate from external observation ingestion. No hosted registry, public publication or off-machine artifact backup is claimed.
