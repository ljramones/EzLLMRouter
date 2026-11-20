# Database and operator server structure

## Versioned schema

The service's schema module owns database initialization and upgrades. A new
installation applies the ordered SQL resources, currently `v001_initial.sql` and
`v002_observation_retention.sql` and `v003_database_queries.sql`, in one
`BEGIN IMMEDIATE` transaction. It records
their SHA-256 checksums in `schema_revisions`, sets the application identifier and
sets `user_version=3`.
All credential, accounting, authority, campaign and console tables exist before
components start. Constructors bootstrap their own data or recover interrupted
operations; they do not create or alter tables.

An existing version 1 or 2 database validates its recorded checksums before applying
the pending migrations in an atomic transaction. A failed upgrade rolls back the migration,
revision record and version change together. The version 1 and 2 SQL resources remain
unchanged. Unversioned populated databases,
databases owned by another application, unknown versions and mismatched migration
checksums are refused. There are no importers for unversioned development
databases. An ordinary restart or restoration of a consistent backup validates
the recorded revisions and applies any pending supported migration.
Future schema changes belong in another numbered SQL resource and the ordered
migration list; never change a previously applied SQL file in place.

## Probe observation retention

Version 2 adds connection indexes and trims stored probe diagnostics to the most
recent 20 observations per connection, plus up to three inventory anchors: the
latest inventory result, latest usable result and latest complete result. Each
new probe write prunes that connection in the same transaction. The total is at
most 23 observations per connection; the history endpoint returns the latest 20.
An older retained complete snapshot still supplies models after partial or failed
discovery. Inventory reads and permission updates decode at most three indexed
observation records instead of loading the connection's entire probe history.

Probe operation IDs are deduplicated while their observations remain stored.
Repeating an ID after its diagnostic record has been pruned can run another
metadata probe. This policy does not prune execution attempts, authority audits,
prices, grants or external accounting events.

## Repository queries and transactions

`repositories/` owns named SQL queries by domain. Application modules pass query
objects and bound values through the public `store.database` interface. Dynamic
tables, key columns and supported predicate shapes are checked against explicit
repository allowlists. Services do not use the store's raw connection, private lock
or private transaction implementation.

`database.read()` holds the database gate and a SQLite read snapshot across a
group of reads. SQLite `query_only` rejects writes in that scope; nested reads
share the snapshot and restore the previous connection setting on exit. A read
cannot be promoted into a write transaction. Registry explanation, admission and current-authority checks hold one such scope
across policy revisions, destination selection and prices, so a concurrent writer
cannot produce a mixed admission record.

`database.transaction(action)` shares one transaction across repository domains,
including credential changes, audit rows, budget reservations and sender ownership.
Nested write actions use savepoints: an inner failure rolls back its own changes,
and an outer failure also rolls back successful inner actions. If SQLite already
rolled back a transaction, savepoint cleanup preserves the original exception.
Rollback failures add only their exception type as a note; they do not replace
the action/commit error or establish a definite rollback. Operator recovery
and completion writes use transactions. Legacy candidate expiry rechecks the latest
record inside a write transaction before changing its status revision. Results are materialized while the gate is held and the SQLite cursor
is closed before a result is returned. Connection setup, commit/rollback and
maintenance opening remain in `SQLiteStore`. Offline maintenance validates an
existing schema and never creates a database or initializes its tables.

Writable stores hold an exclusive instance lease until close. A second service
cannot open the same database or recover another process's in-flight state.
Read-only offline tools share a lease with one another after the writer stops.
Encryption maintenance and the local backup command require an exclusive lease
and reject live store owners before changing keys or creating backup targets.
Keep the owner-only `DATABASE_PATH.instance.lock` sidecar in place; never unlink it to
clear a busy instance. Older processes and external SQLite tools must also be
stopped. See [offline maintenance and filesystem requirements](ENCRYPTION.md).

The local implementation still uses one serialized SQLite connection. This
change centralizes ownership and keeps atomic behavior; it does not claim a new
database backend or parallel-read throughput.

Account mutations, event/snapshot ingestion and recorded eligibility reads
recheck dataset existence and authorization inside their write transaction.
Dataset expiry removes its encrypted credential versions, credential operation
records and bindings in the same transaction as the accounting cohort, retaining
the expiry tombstone. A writer admitted before purge cannot recreate orphan rows
after that transaction commits.

Credential connect, refresh and replacement take a secret snapshot under the
credential gate, release it during provider discovery, then recheck dataset and
binding revision inside the publishing transaction. Credential release, key
rotation and permission changes can proceed while discovery waits. A stale
discovery result cannot overwrite newer permissions or restore a disabled
binding. Concurrent replacements reserve separate encrypted versions and discard
unused staged versions without deleting a selected or pending credential.

## Indexed reporting and ingestion

Version 3 adds 26 indexes for attempt identity, attribution step scope, registry
roles and connections, grants, campaigns, account history, event references,
lineage and expiry. It changes no historical rows, prices, grants or audit values.

Operator usage loads each attempt's latest usage revision in one query, retaining
the existing 10,000-attempt cap and truncation flag. Inventory batches its models,
prices and grants; principal/model grant views use scoped bulk queries. Campaign
reconciliation joins latest usage revisions. Decimal totals retain Python's exact
decimal handling. Attribution checks indexed run/step existence rather than decoding
all submissions. Account history reads include the dataset in SQL.

Ingestion walks the affected lineage component with indexed predecessor lookups;
cycle detection visits each edge once. Unrelated attempts do not add work to that
validation. Missing predecessors, late starts, lineage overrides and snapshot
references remain supported. Snapshot binding checks select only matching references.
External integration dataset reports and exports still read their requested
dataset in full. The controlled usage-cost report instead uses a store-owned,
read-only WAL snapshot, with at most four concurrent report readers and a ten-second
SQL execution budget. It selects visibility, cutoff and latest usage revisions in
SQL, then releases the snapshot before JSON decoding and aggregation. Writers do
not wait for those report readers. In-memory test stores use their existing read
scope. Shutdown interrupts and drains readers before releasing the service lease.

Usage-cost attempts and exports use `attempt_page` (1–10,000) and `attempt_limit`
(1–100, default 100). `attempt_pagination` includes the total count. Agent inventory
retains its independent `page`/`limit` fields. Totals and cohorts cover all matching
attempts, regardless of the displayed page. Cohort costs retain full descendant
costs through the cutoff, including attempts outside the task-start interval;
those aggregates still require all visible attempt metadata. Exports contain the
selected attempt page, and the console labels this explicitly.

Snapshot and successor-result expiry use indexed cutoffs and preserve identity,
digest and accounting evidence. Maintenance checks for due work before taking a
write transaction, then rechecks under write ownership. Idle sweeps do not start
`BEGIN IMMEDIATE`. Dataset maintenance scans only the local-real ID prefix.

## Integration ownership and integrity audit

Version 3 uses immediate insert/update and parent-restriction triggers for dataset
ownership and encrypted credential bindings. These cover direct SQL writes as well
as the service boundary. Purge removes children before their parent. Attempts,
lineage and snapshots intentionally have no arrival-order foreign keys: a reference
may precede the referenced observation.

The triggers enforce future ownership changes without rebuilding tables or deleting
historical orphan evidence. Existing violations survive the migration and can be
reported with a read-only audit:

```sh
uv run --locked python -m ezllmrouter_server.database_audit --db /absolute/path/service.sqlite
```

The audit opens an existing database in SQLite read-only mode, validates the schema,
and reports quick-check status, foreign-key violations and ownership counts. It
returns exit code 1 for violations and never upgrades or repairs the database.
Its output excludes IDs, credentials and record contents.

## Measured local scale

Reproduce the disposable benchmark without a service database or provider calls:

```sh
uv run --locked python -m tools.database_benchmark \
  --sizes 1000 10000 100000 --operations-per-worker 500 \
  --output .artifacts/code-review/database-batch/benchmark.json
```

On the local ARM64 macOS host with Python 3.12.15 and SQLite 3.53.1, each size seeded
that many controlled submissions and external attempts, with two usage revisions
per controlled attempt. Observed usage reports took 7 ms, 76 ms and 82 ms respectively,
always using one query; the final report returned 10,000 attempts with truncation.
Independent-attempt ingestion used 12 reads at each size and took approximately
0.9–1.3 ms. These timings include query instrumentation.

At each size, eight threads ran 4,000 small operations with 20% writes, first on one
connection and then on two independent connections. All 24,000 operations completed
without SQLite errors and integrity checks passed. Observed p95 latency was
0.045–0.059 ms; worst waits reached 79 ms. Long reports still serialize callers
sharing a connection, and SQLite still permits one writer at a time.

This measures local synthetic metadata through 100,000 attempts per domain. It is
not an HTTP throughput or production capacity guarantee; payload sizes, disk latency,
large connected lineage components, full exports and other machines need their own
measurements. Database plus WAL/SHM files reached about 545 MB at the largest size.

## Shared server logic

`formatting.py` owns decimal rendering and UTC formatting. Callers select the
existing representation: exact decimal scale, compact report strings or nine
fixed places; UTC seconds ending in `Z` or precise UTC ISO timestamps. Financial
calculations retain their existing quantization and rounding rules. Rendering
does not convert through floating point or change recorded history.

`json_validation.py` shares decoding, duplicate-key checks, safe integers,
restricted-value validation and canonical serialization. Its explicit policies
retain the adopted protocol differences:

| Policy | Work 0.2 | Work 0.3 |
| --- | --- | --- |
| Input limit | 65,536 bytes | 262,144 bytes |
| Nesting limit | 16 | 32 |
| Null values | Rejected | Supported |
| Escaped control characters | Supported by decoding; field rules still apply | Rejected |
| Negative zero | Rejected | Decodes to zero |
| Object member limit | 1,024 | No separate member limit |
| Canonical key order | UTF-16 | Adopted ASCII key order |

Public contract functions retain their error codes, status codes and digest
domains. Operator-body and connector parsers use the common duplicate-key hook
with their own error translations. Contract schemas and signed resources are
unchanged.

`repositories/authority.py` owns shared active-principal role checks, authority
revision advancement, audit insertion and the management-value allowlist. User,
connector and registry mutations call it inside their existing publishing
transaction under the sender gate. A failed audit rolls back the mutation and
revision together. The in-memory authority epoch changes after commit, and
replaying a registry operation returns its saved receipt without another audit.
The store also shares one in-transaction usage append for updates and candidate
completion, preserving revision linkage and caller input values.

`errors.py` groups server domain errors under `ServerError`, retaining existing
`ValueError`/`RuntimeError` catches, public codes and status defaults. Retry
guidance remains attached to the error types that originally supplied it.
`states.py` names submission, dispatch, delivery, settlement, candidate and launch
states with `StrEnum`; persistence and wire records receive plain string values.

The registry declares optional accounts, connectors, credentials and campaign
dependencies. Coordinator accepts an owned successor and an optional guarded
sender; the local service wires its guarded sender explicitly. Readiness can be
injected into Registry. Attribution imports shared validation, time and conflict
types directly without importing Registry inside its methods.

Registry mutations dispatch to focused action handlers. Coordinator carries an
explicit admission snapshot into preparation/dispatch. Usage reporting separates
snapshot reads, visibility, attempt projection and aggregation; external reports
carry one database snapshot into per-attempt and version-specific projections.
Strict type checking covers 36 modules, including the shared policies and
authority repository; the remaining service bodies are outside that gate.

## Operator HTTP server

`operator_web.serve` composes an `OperatorApplication` and an `OperatorHandler`.
The application owns that server's sessions, dependencies, executor and scheduled
maintenance. Shutdown waits for background work before the caller closes its
database. Separate servers have separate session dictionaries.

`operator_http/routing.py` declares each HTTP method, exact path or resource
family, handler, query policy, optional dependency and authorization stage.
Requests resolve once: exact paths take precedence over families, then the
longest family prefix wins. Duplicate registrations fail during construction;
handlers no longer participate in route discovery by returning a sentinel.
Family handlers retain resource ID, action and selector validation.

`operator_http/handler.py` applies the stages in order: public assets, session
recovery, required password changes, account/integration routes, integration-only
restrictions, resource routes, then ordinary-user report scope. Authenticated
mutations validate origin, session and CSRF before reading bodies. Unknown paths
still pass through the applicable authentication and permission boundaries.

Transport parsing, authentication, accounts/connectors, registry operations,
integration routes and reports live in separate modules and import dependencies
directly. `assets.py` contains the single public asset allowlist; directory
contents never register routes. CSV exports share one serializer and response
helper, preserving column order, UTF-8, CRLF, exact decimal strings, report-specific
JSON transformations and attachment filenames.

Application dependencies, optional collaborators, session records and lifecycle
fields have concrete types. Strict mypy covers the application state, route
registry and shared serialization helpers alongside the existing typed modules.
The remaining handler mixins are outside the strict type gate. Scheduler threads
start only when a registry exists, and state supports cleanup before startup.
Failure events identify the actual route or operation, including separate
validation preparation/execution and scheduler listing/probing failures. They
continue to omit exception messages, request bodies and query strings.

Session dictionary access uses a short memory lock. Authentication releases it
before account queries, reads principal/account state under one database gate,
then checks that the same session still exists and has not expired before
publishing a request snapshot. Login also rechecks the authenticated account
version before insertion. Database access, wire-token creation/revocation and
HTTP writes never hold the session lock. Logout can remove a session while a
lookup waits; its late result cannot recreate that session.

Offline tests exercise actual handlers through in-memory HTTP streams, including
route dispatch, isolation between servers, body rejection and background jobs.
The HTTP structure regressions cover precedence, permission stages, static-file
boundaries, all four CSV exports and secret-safe failure events. An additional
old/new handler comparison checks 1,033 requests and identical bytes for the four
CSV exports; its generated evidence is under ignored
`.artifacts/code-review/http-batch/`.
The explicit `--http-only` command exercises socket-level fixtures when the host
allows loopback binds. Neither check invokes a model provider.
