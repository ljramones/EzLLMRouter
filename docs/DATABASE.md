# Database and operator server structure

## Initial schema

The service's schema module owns database initialization. A new installation applies
`schema/v001_initial.sql` in one `BEGIN IMMEDIATE` transaction, records its SHA-256
in `schema_revisions`, and sets the application identifier and `user_version=1`.
All credential, accounting, authority, campaign and console tables exist before
components start. Constructors bootstrap their own data or recover interrupted
operations; they do not create or alter tables.

This is the initial layout for a fresh database. Unversioned populated databases,
databases owned by another application, unknown versions and mismatched migration
checksums are refused. There are no importers or upgrade paths for earlier
development databases. An ordinary restart or restoration of a consistent backup
created by this layout validates the recorded revision and preserves its data.
Future schema changes belong in another numbered SQL resource and the ordered
migration list; never change a previously applied SQL file in place.

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

Offline tests exercise actual handlers through in-memory HTTP streams, including
route dispatch, isolation between servers, body rejection and background jobs.
The explicit `--http-only` command exercises socket-level fixtures when the host
allows loopback binds. Neither check invokes a model provider.
