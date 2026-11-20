# Database and operator server structure

## Versioned schema

The service's schema module owns database initialization and upgrades. A new
installation applies the ordered SQL resources, currently `v001_initial.sql` and
`v002_observation_retention.sql`, in one `BEGIN IMMEDIATE` transaction. It records
their SHA-256 checksums in `schema_revisions`, sets the application identifier and
sets `user_version=2`.
All credential, accounting, authority, campaign and console tables exist before
components start. Constructors bootstrap their own data or recover interrupted
operations; they do not create or alter tables.

An existing version 1 database validates its recorded checksum before applying
version 2 in an atomic transaction. A failed upgrade rolls back the migration,
revision record and version change together. The version 1 SQL resource remains
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
SQL identifiers and the few supported predicate shapes are validated by the
repository helpers. Services do not use the store's raw connection, private lock
or private transaction implementation.

`database.read()` holds the existing database gate across a consistent group of
reads. `database.transaction(action)` shares one transaction across repository
domains, including credential changes, audit rows, budget reservations and sender
ownership. Results are materialized while the gate is held and the SQLite cursor
is closed before a result is returned. Connection setup, commit/rollback and
maintenance opening remain in `SQLiteStore`. Offline maintenance validates an
existing schema and never creates a database or initializes its tables.

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

## Operator HTTP server

`operator_web.serve` composes an `OperatorApplication` and an `OperatorHandler`.
The application owns that server's sessions, dependencies, executor and scheduled
maintenance. Shutdown waits for background work before the caller closes its
database. Separate servers have separate session dictionaries.

`operator_http/handler.py` owns the HTTP entry points and ordered dispatch tables.
Transport parsing, authentication, accounts/connectors, registry operations,
integration routes, reports and static assets live in separate modules. Route
ordering retains the permission boundaries: login and session recovery, required
password changes, integration-only access and ordinary-user report scope.
Authenticated mutations validate origin, session and CSRF before reading bodies.

Session dictionary access uses a short memory lock. Authentication releases it
before account queries, reads principal/account state under one database gate,
then checks that the same session still exists and has not expired before
publishing a request snapshot. Login also rechecks the authenticated account
version before insertion. Database access, wire-token creation/revocation and
HTTP writes never hold the session lock. Logout can remove a session while a
lookup waits; its late result cannot recreate that session.

Offline tests exercise actual handlers through in-memory HTTP streams, including
route dispatch, isolation between servers, body rejection and background jobs.
The explicit `--http-only` command exercises socket-level fixtures when the host
allows loopback binds. Neither check invokes a model provider.
