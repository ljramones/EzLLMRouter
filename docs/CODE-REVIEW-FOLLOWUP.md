# Code review follow-up

This tracks the 2026-11-19 review of commit `26ea4d1`. The browser baseline was
saved separately in `4474504`: 381 owner-Terminal cases passed, with 127 each in
Chromium, Firefox and WebKit, and no skips or retry-only passes. That run predates
the fixes below. Generated reports and logs belong under ignored `.artifacts/`.

## Implemented fixes

| Review item | Change and regression evidence |
| --- | --- |
| 3.1: Multiline model results rejected | Python, Go, Java, .NET and Rust JSON handling accepts escaped controls in free text while retaining NUL, surrogate and field-specific restrictions. Request, reply, status and tool-argument regressions join the shared corpus, now 125 cases. Python and JavaScript also check exact multiline preservation. |
| 3.2: Credential initializer loses chmod permission | Set mode before transferring ownership. A host regression models the ownership transition; an isolated container check verifies the actual CHOWN-only capability set. |
| 3.3: Silent test omissions | The runner rejects unclassified Python test files. It registers offline, loopback and standalone suites, and records five runtime/evidence-dependent exclusions. Expired fixture clocks and broken installed-consumer setup are repaired. Separate CI jobs run installed JavaScript runtime and actual HTTP checks. |
| 4.1.1: Pre-transmit exception strands an attempt | Unexpected errors at the final authority check enter the existing no-send failure path. Runtime, database and type-error regressions verify terminal status, no adapter calls and no repeated dispatch. |
| 4.1.2: Unbounded probe observations and inventory decoding | New schema version 2 adds connection and inventory indexes, retaining 20 recent diagnostics plus up to three inventory anchors per connection. Inventory and permission reads decode at most three records. Regressions cover 2,000 historical rows, indexed query plans, partial/failed discovery fallback, pruning, version 1 upgrade/restart, exact price preservation and full rollback on migration failure. The adopted version 1 SQL remains unchanged. |
| 4.1.3: Rejected database changed to WAL | Validate ownership/schema before setting journal mode. Rejection preserves the database bytes and creates no WAL/SHM sidecars. |
| 4.1.3: Dataset purge races | Account, event, snapshot, recorded eligibility and credential mutations recheck dataset existence inside their publishing transaction. Purge also removes encrypted credential versions, bindings and operation records atomically. Deterministic thread regressions cover eleven delayed writer paths and discovery returning after purge; no orphan rows or credentials reappear. |
| 4.1.3 / 5.10: Database boundaries and query growth | Version 3 adds 26 indexes and prospective dataset/credential ownership constraints without rewriting history. Read scopes enforce SQLite read-only snapshots; nested writes use savepoints. Usage and campaign reconciliation batch latest revisions, inventory batches models/prices/grants, grant views use scoped bulk reads, attribution uses indexed step existence, account history is dataset-scoped, and lineage/snapshot validation avoids unrelated records. Maintenance avoids idle write transactions. A read-only audit reports preserved historical ownership violations. |
| 4.1.3 / 5.2 edge cases: IPv6 probe failure and TLS socket leak | Provider metadata probes connect using the approved DNS result's socket family and complete sockaddr, preserving IPv6 flow/scope fields and the original hostname for TLS verification. Trust configuration is created before opening a socket. Raw sockets, TLS streams and response readers close on success and transport/size failures. IPv4 preference, address-policy rejection and the response cap remain covered. |
| 4.2.1: Inconsistent worker/sender timeouts | One bounded absolute attempt deadline reaches worker dispatch, relay waits, provider reading and first-byte gates. Text execution rejects timeout values above five minutes before admission. Tests cover the limit and a 60-second budget. |
| 4.2.2: Worker error races a trusted relay | Await the trusted relay even after a worker error. Abandonment is recorded under the authority gate and checked before commit and first byte. Failure classification uses socket acceptance; in-flight paid response content and usage survive a worker error. |
| 4.2.3: Worker identity grows indefinitely | Keep a bounded 512-attempt diagnostic window, with duplicate counts saturated at two. A 10,000-attempt regression verifies bounded state and socket-frame size. Trusted sender registration remains the one-use authority. |
| 4.2.4: Sender checks size after buffering | Check declared length and incrementally stop at 64 KiB, closing the response on success or failure. Declared-length and unknown-length stream regressions verify early termination. |
| 4.2.5: Diagnostic fsync blocks or fails execution | Use a bounded best-effort queue and background writer. Tests block fsync and simulate a disk failure while guarded requests complete. Durable intent/accounting commits remain synchronous. |
| 4.2.6: Fault hooks and missing gateway/worker logging | Runtime adapters no longer read mutation, context-swap, bypass, destination-override, trace-file or pool-probe switches. Explicit fixture adapters retain the negative controls under `tools/gateway/` and require opt-in staging. Worker raw egress probes exist only in the fixture entry point. The isolated worker receives the same standard-library-only, secret-safe logger as the server. Command, relay, reply, transport and worker startup failures log exception types and stack locations without messages or payloads. |
| 4.3.4: JavaScript client drift | All JavaScript protocols use a shared streamed byte reader and strict decoder: 1 MiB for wire 0.2/attribution, 16 MiB for wire 0.3/accounting. Results match submitted profiles instead of a synthetic configuration list. Error handles are validated against the original selector and copied; foreign/malformed handles are discarded. Installed-package checks cover all 125 shared contract cases and 35 additional transport/recovery/result cases, including exact byte-cap boundaries, an embedding above 64 KiB and newly registered profiles. |
| 5.1: Credential gate held during provider discovery | Connect, refresh and replacement release the gate for network discovery, then recheck dataset and captured binding revision before publishing. Tests hold discovery while credential release, key rotation, disable and permission changes complete. Overlapping replacements reserve distinct versions, reject stale results and clean up unused versions. |
| 5.1: Session lock held across database work | Authentication snapshots sessions under a short dictionary lock, reads account state under the database gate, then verifies session identity and expiry before publishing. Login rechecks account/auth version after password verification. Database operations, wire-token creation/revocation and response writes run outside the session lock. Thread regressions cover logout, expiry, password change/reset, permission changes and replacement races. Expired/invalid sessions and rejected logins discard their associated wire credentials. |
| 4.3.5: Python client has no total response deadline | Both clients default to a configurable 60-second HTTP budget. The owned HTTPX transport clamps pool/connect/TLS/write/read operations to the remaining monotonic budget through public HTTPcore interfaces, including incomplete headers and slow bodies. Uncoalesced response chunks also bound cooperative injected streams. Socket-pair tests exercise real blocked reads without listeners; deterministic tests cover all four protocol paths, connection reuse, independent concurrent budgets and query-first errors without replay. OS DNS can overrun, but late connections are closed before sending; custom transports own their blocking I/O deadlines. |
| 4.3.5: Provisioning deletes an issued credential after interruption | Reserve credential custody and sync an operation receipt before issuance. Preserve both after possible issuance, including Ctrl-C, broken output, failed fsync, malformed/lost replies and connection-close failure. Existing files block another invocation. Only failures before issuance remove unused files created by that invocation. An uncertain reply can still leave an empty/partial credential, requiring revision inspection and explicit rotation. |
| 4.3.1: Formatting not enforced across runtime sources | A separate formatting commit, `1b297e0`, reformats 363 tracked Python files. AST comparison verifies executable syntax and data literals, normalizing only source locations, docstring indentation and Unicode-prefix spelling. Formatting is now enforced across all six maintained Python trees, including tests. HTTP structural cleanup is recorded separately below. |
| 4.3.1 / 4.3.2: HTTP structure | Resolve routes from explicit method/path metadata before dispatch, retaining authorization stages and selector validation. Consolidate the public asset allowlist and four CSV writers, replace dependency re-exports with direct imports, type application/session/lifecycle state and clarify operation-specific failure events. Twelve offline regressions exercise real handlers, route precedence, permission and body-read boundaries, export values and safe logging. An old/new handler comparison preserves status/error/header behavior across 1,033 requests and identical bytes for all four CSV exports. Strict typing expands to 31 modules. |
| 5.4 / 5.5 / 5.9: Shared server logic | Share exact money/UTC rendering and a JSON engine with explicit policies while retaining wire-version limits, null/control/negative-zero behavior, canonical ordering and digest domains. Centralize active administrator checks, transactional authority/audit bookkeeping and usage revision appends. Introduce a domain-error root and named state types while preserving catch types, retry attributes and plain wire strings. Declare optional collaborators, inject guarded sending/readiness/successor ownership and remove attribution's Registry import cycle. Split the registry action dispatcher (785 to 33 lines), usage report (484 to 93), external report (302 to 100) and Coordinator admission/dispatch with typed snapshots. Add 24 offline regressions; strict typing covers 36 modules. |
| 4.6 / 4.10 / 4.3.5: Login and operator transport policy | Bound failed and pending named logins by backend peer and canonical username, clear failures after success, evict old inactive throttle entries, and cap concurrent work and retained sessions. Expected operator-login rejection has no ERROR stack trace; unexpected faults return a sanitized 503. TCP is loopback-only; an explicit HTTPS origin over a private Unix socket enables Secure session and clearing cookies. Owned socket directories and mode `0600` are checked before listening. Product-specific integration forwarding remains outside this security batch. |
| 4.2.7: Environment-based provider credentials | Trusted adapter constructors receive provider keys explicitly; invocation guards use only the bound credential. Production startup no longer exports service/provider secrets into the environment. Console bootstrap uses a private UTF-8 password file or explicit library argument and preserves password whitespace. Synthetic harness environment inputs and the worker's public placeholder remain fixture mechanisms. |
| 4.3.5: Offline encryption maintenance, key retirement and filesystems | Shared service leases exclude exclusive rotation, resume, retirement and local backup before key changes. Retirement verifies all stored references and decryptability, rejects active/referenced keys, and requires explicit backup-dependency acknowledgment. Keyring generation caching avoids repeated parsing and cipher construction while checking metadata every operation. Atomic publication reports whether a fault followed publication; required local filesystem guarantees and recovery limits are documented. |
| 4.3.2: Narrow lint/type gates | Enable `E9`, all `F` and all `B` rules across server, clients, deployment, worker, tools and tests, with no new blanket rule ignores. Remove unused imports, declare shared exports, bind loop captures, pair equal-length sequences strictly, chain translated exceptions and replace 14 blind exception assertions with expected error types. The quality batch expanded strict mypy to 28 modules, including every SQL repository and provider probes, with imported types retained through `follow_imports="silent"`. Four runner regressions exercise real tools against bad disposable projects and verify runtime-state exclusion. Further type coverage remains incremental. |
| 4.2.7 / 5.11 / 3.10: Resource ownership and lifecycle | Coordinator and successor expose draining, idempotent close methods; execution queues and completed-future retention are bounded. Sender/worker IPC and ingress have connection limits and whole-frame/write deadlines. Worker socket exchange is async and cancellable; rejected executor submissions cannot execute later. Gateway startup failures close partial clients, listeners and loop threads. HTTP input enforces its deadline without per-request timer threads. Registry wire tokens expire/prune under a short memory lock; operator shutdown revokes session tokens and blocks late publication. Local-service startup/shutdown unwinds resources in dependency order. |
| 3.10: Authentication context selection | Empty/malformed expiry contexts return 401. Exact credentials retain their own scope, registry defaults use an explicit or unambiguous common context, and implicit execution credential selection rejects ambiguous aliases. Tests reverse insertion order and verify explicit context/credential behavior. |
| 3.10: Provider vault cleanup after commit | Idempotent credential replacement/removal retries derive the retired version from the committed operation receipt and resume unlinking after a filesystem failure, including after registry/vault reopen and later rotations. Selected credentials, operation receipts and audit history remain intact. |
| 3.10: Null report values and identifier mismatch | Null values cannot match the literal filter string `None`. Shared 1–160-character, alphanumeric-first IDs now cover admission, registry, catalogue, operator projections, run headers and report filters; reserved report buckets retain their field-specific meaning. Long IDs round-trip without truncation. |
| 3.10: Launch completion | The database batch already required an existing `running` row and checked the affected row count. The correctness regression also verifies a full-length operation ID, a missing operation and a repeated terminal completion. |
| 3.10: Output budget and invalid probe settings | Text admission caps output at 32,768 tokens before durable admission; existing campaign/model limits can be lower. Probe validation returns safe `invalid_settings` observations without network access, preserving unsupported-operation and malformed-response classifications. |
| Demo cutoff/cycle and tariff drift | Attempts with no qualifying revision have explicit unknown usage/cost; future attempts/revisions are excluded and replacement counts cannot be negative. Workflow traversal rejects cycles/missing parents. Synthetic rates, minima, quantum and domains now come from the packaged tariff resource, with registration and maximum-bound checks; existing tariff goldens remain unchanged. |

The client consistency batch consolidates all four HTTP exchanges and their
version, header, decoding and transport-error handling into one session. Public
methods and both validators are annotated; all ten client modules pass strict
mypy. Both protocol error types share `ClientError`; accounting input errors keep
`TypeError` compatibility. Origins reject paths, credentials, queries and
fragments before allocating HTTP resources. Credentials are private and redacted
in ordinary diagnostics. Snake_case methods are primary, with documented legacy
camelCase wrappers. The wheel includes `py.typed` and omits unused registrations.
Seven new offline regressions cover these boundaries. The full offline runner
passes 802 cases and the built client wheel passes 37 selected tests, including
all 125 shared contract cases. Evidence is under ignored
`.artifacts/code-review/cleanup-pass/client/`.

The runtime cleanup batch adds explicit instance identity configuration and an
opt-in, exact-cookie identity lookup. Defaults preserve existing principals and
purpose strings; unknown owner changes fail without rewriting history. Synthetic
successor service, allowance, authority, assembly, receipt evidence and their
queries move to `tools/synthetic`, absent from the production wheel and default
staging. Fixture staging explicitly includes them. Descriptor minting/validation,
provider reply projection and demo arithmetic/rendering share helpers. Ordinary
invalid decimals no longer log unexpected-error stacks. Runtime versions come
from distribution/project metadata, and build reports no longer claim stale
client versions or milestone qualification. Scripted-demo and retrieval-usage
implementation/UI routes use descriptive names; adopted wire schemas and IDs
are unchanged. Eight new boundary tests join the offline runner, now 810 cases;
strict mypy covers 47 modules. Both built wheels pass 142 selected tests, with
117 packaged files checked byte-for-byte against source and imported module
origins verified. Evidence is under `.artifacts/code-review/cleanup-pass/runtime/`.
Browser, real listener/TLS and frozen-worker checks remain target gates.

The .NET package test also now uses a fresh package cache for each restore.
Previously, an existing package with the same version could hide SDK changes
from the tests despite a successful local pack.

## Validation and outstanding gates

The expanded offline Python/component runner passes: 820 unittest cases plus
seven console component scripts, Ruff and strict mypy across 51 modules.
Installed JavaScript runtime checks and packaged TypeScript consumers pass with
the existing TypeScript 5.9.3 compiler; Playwright type checking also passes.
JavaScript and Python pass all 125 shared contract cases. Previously recorded
Go, Java and .NET results cover that corpus; those native clients were not rerun
for this cleanup pass.

The owner Terminal subsequently passed
`python3 -I -S tests/client_languages/check_javascript.py --http`: actual fetch,
streamed byte caps, response faults, caller deadline and no request replay.
This closes the JavaScript HTTP gate for that run.

The executor cannot bind localhost or access the Docker daemon. Its Rust
installation contains x86 executables that cannot run on this ARM host. Therefore
the other actual HTTP fixtures, Linux credential-capability test, Rust checks and
frozen-worker integration are **unverified here**. CI jobs are configured for the
first three; the reviewed frozen worker needs its own isolated qualification.
The browser run above is evidence for its saved baseline, not a rerun after
these server changes.

The credential-initializer CI job uses native `ubuntu-24.04-arm` and explicitly
requests Docker platform `linux/arm64`. Its existing base-image digest is an
ARM64 image manifest; the prior AMD64 runner failed with `exec format error`
before executing the check. The digest and capability restrictions are unchanged.
This fixes the runner mismatch; a subsequent CI run must still establish the
actual CHOWN-only result.

The gateway follow-up adds 14 focused runtime/logging checks, including exact
bound requests with every former fixture switch enabled, fixed startup
destination/timeout, probe rejection, coroutine cancellation, secret canaries
and reply failures without retry. Packaging tests verify that the minimal worker
needs only its runtime, wire codec and standalone logger; fixture scripts
require an explicit harness source map. The frozen Docker/worker and real HTTP
checks still require their target environment.

The earlier retention/concurrency batch adds 14 focused tests. Migration checks verify upgrade and
rollback against a version 1 database; concurrency checks use held provider
fixtures and explicit thread barriers without real sockets or provider calls.
The server wheel includes all three numbered migration resources.

The query/transaction database batch adds 24 offline regressions for version 2
upgrade/restart and failed-upgrade rollback, byte-exact historical preservation,
read snapshots, write rejection, savepoints, candidate expiry, terminal launcher
state, query growth, late lineage, snapshot binding/expiry, batched inventory and
campaign reconciliation, ownership constraints, report truncation and indexed plans.
A built server wheel is checked with isolated imports and fresh/upgraded databases.

A disposable benchmark seeds 1,000, 10,000 and 100,000 attempts per domain, plus two
controlled usage revisions per attempt. Usage reports use one query and retain their
10,000-row cap; independent ingestion uses 12 reads at every size. Eight-thread
single/two-connection runs complete 24,000 mixed operations without SQLite errors;
all integrity checks pass. Timings and limits are recorded in the [database guide](DATABASE.md).
This is local synthetic metadata evidence, not production throughput qualification.

The resource batch adds 41 offline tests using socket pairs, real event loops,
thread barriers and disposable stores. Tests retain paid results while shutdown
waits, prove that rejected queued work cannot execute later, verify native queue
and socket limits, settle unscheduled successor reservations, purge/revoke tokens,
and inject constructor/client/listener cleanup failures. The server wheel and
explicit standalone worker source context are checked without importing LiteLLM.
See [runtime resources](RESOURCES.md) for limits and ownership. The loopback suite
and a rebuilt frozen-worker deployment still require their separate target run.

The correctness batch adds 41 offline tests covering all ten requested cases,
including the already-fixed launch guard. Tests use disposable registry/vault
stores, synthetic reports/demos and injected probe responses. They verify restart
cleanup recovery, insertion-order-independent authentication, null-versus-literal
filtering, end-to-end identifier limits, pre-admission output limits and unchanged
fictional pricing vectors. The packaged server runs the same regressions with
isolated imports; no provider request or existing profile restart is involved.

The session/probe batch adds 23 offline tests: 14 exercise real operator handlers
with memory streams and explicit thread barriers; nine exercise the real HTTP
response parser over synthetic socket/TLS objects. The probe checks verify IPv6
sockaddrs, SNI, address rejection, invalid trust material, connection/handshake/send
failures and declared/streamed response limits. Four selected regressions also
reject the pre-fix implementations from `ed48930`. Actual IPv6/TLS networking and
the browser suite have not been rerun for this batch.

The deadline/provisioning batch adds 24 offline tests: 14 deadline tests and ten
provisioning custody tests. The deadline tests combine the actual HTTPX/HTTPcore
HTTP/1.1 parser with a controlled backend and exercise real blocked header/body
reads through socket pairs. They do not qualify real TCP/TLS or DNS behavior.
HTTPcore 1.0.9 is now an explicit client dependency because its public transport
API is used directly; the selected packages, versions, hashes and frozen gateway
inputs are unchanged. The offline lock check passes.

The built Python wheel passes the deadline tests and all 125 shared contract
cases using isolated package imports. Separate baseline probes confirm the old
reader accepts a stream beyond the new default budget and the old provisioning
command deletes the saved credential after broken output.

The quality batch has zero Ruff diagnostics in the expanded scope and 406 Python
files passing the formatter. The original broader-rule scan reported 270
diagnostics; fixes preserve explicit shared exports instead of deleting imports
that route modules consume. New annotations leave SQL text, contract resources,
applied migrations and frozen dependency inputs unchanged. The four added quality
regressions run the real lint/format/mypy commands without model calls or sockets.
Loopback TLS tests now assert specific guard and certificate errors, but still
require their separate target run. Browser and frozen-worker qualification have
not been rerun for the formatting/lint changes.

The HTTP structure batch passes 728 offline unittest cases, seven console
component scripts, Ruff checks and strict mypy across 31 modules. Twelve of
those cases are new HTTP structure regressions. An isolated built-wheel check
passes 96 tests and verifies that all 96 packaged server files match the source.
The old/new handler comparison uses commit `26b8686` as its baseline; 1,033
requests preserve status/error/header behavior and all four CSV exports preserve
their bytes. Generated logs, comparison results and wheel evidence are under
ignored `.artifacts/code-review/http-batch/`. These are in-memory and offline
checks; browser and socket-listener suites still require their separate target
run for this batch.

The shared-server batch passes 752 offline unittest cases, seven console
component scripts, Ruff checks and strict mypy across 36 modules. Its 24 new
regressions cover protocol policy differences, exact rendering, domain errors,
state serialization, constructor injection, audit rollback/replay, usage revision
linkage and report versions 1–3. The built wheel passes 199 tests, including the
staged runtime import checks; all 101 packaged files match the source, and every
imported server module is verified to come from the extracted wheel. The verifier
uses the declared virtual environment for native dependencies and prepends the
wheel under Python isolated mode.

An additional old/new comparison against the pre-batch source snapshot finds no
differences across 1,352 JSON decode cases, 804 canonicalization cases, 32 usage
revisions, 36 usage reports and 15 external accounting reports. Evidence and the
source snapshot are under ignored `.artifacts/code-review/shared-server-batch/`.
Browser, listener and frozen-worker target qualification remain separate checks.

The security/encryption batch passes 795 offline unittest cases, seven console
component scripts, Ruff and strict mypy across 38 modules; 427 Python files pass
formatting checks. Its 43 new regressions cover throttling, cookie and origin
policy, pre-listen permissions, expected-error logging, explicit secret inputs,
cross-process maintenance exclusion, key cache invalidation, retirement reference
and backup guards, and filesystem publication failures. Fixtures use disposable
stores, memory HTTP handlers, socket pairs and child processes without listeners
or provider requests.

The built wheel passes 211 selected tests; all 103 packaged files match the
source and imported server modules come from the extracted wheel. Evidence is
under ignored `.artifacts/code-review/security-encryption-batch/`. No existing
instance, private key material, applied migration or frozen dependency input was
changed. Browser, actual listener/TLS and frozen-worker qualification remain
pending for this batch, including the explicit ASGI proxy credential input.

The local deployment evidence driver now observes the durable guard receipt
and held receiver request before revocation. It no longer reads private pool
queues; any new deployment run must validate this before-first-write evidence
against its actual receiver and sender observations.

Run the pending development checks from the repository root in a Terminal with
the required runtimes and socket/Docker access:

```sh
uv run --locked python -m tools.check --http-only
python3 -I -S tests/security/check_credential_init.py
bash tests/client_languages/check_rust.sh
python3 -I -S tests/client_languages/http_fixture.py --client rust
```

These use disposable fixtures and make no model calls. Frozen-worker validation
must use the already reviewed locked inputs and a separate disposable target;
these changes do not authorize dependency replacement or an existing profile
restart. Do not declare the review release gate complete until the required
target checks pass.

The deployment cleanup batch replaces `profile.py` with `local_profile.py`,
shares bounded command capture/private redacted records and source/run helpers,
and consolidates the host operator transport with response bounds and cleanup.
Run dates are validated instead of fixed to October 21. Docker context is
explicitly configurable; up/restart use the prepared build without automatic
source preparation. Backup/migration connections close, and target cleanup
attempts every owned removal even after another cleanup fails. Installed-client
evidence versions come from package metadata. BuildKit mounts prevent wheel and
client archives entering image layers; service validation sources stay outside
the final runtime stage. Disposable proof commands explicitly mount staged
fixtures. Seven new offline regressions cover command timeouts, redaction,
permissions, profiler coexistence, dates/collisions, tree comparisons and lookup
bounds. The offline runner passes 817 cases; strict mypy covers 49 modules.
Evidence is under `.artifacts/code-review/cleanup-pass/deployment/`. Docker builds
and mounted proof commands have not been run here and remain target gates.

The test/tooling cleanup moves gateway evidence commands and operator/browser
proof drivers into `tools/`, removes flat runtime/evidence shims and duplicate
worker support copies, and replaces fixture path injection with package imports.
Repeatable milestone-named tests have descriptive names. Shared custody/transport
helpers remove repetition between separately scoped historical supplements.
Poll loops use bounded observable-state helpers, the no-store fixture uses an
event instead of a fixed delay, and the operator updates Host/Origin policy to
its actual bound ephemeral port. HTTP tests retain that bound socket rather than
closing a temporary port reservation. Imported reporting tests no longer execute
twice; helper assertions survive optimized Python, expected equality assertions
use unittest methods, environment overrides restore reliably, and optional tool
fixtures explain missing prerequisites. JavaScript has standard npm test commands
and omits unused registration data. Contracts, frozen inputs, prices and recorded
proof identities retain their bytes/values.

Four new offline tests cover canonical imports, extracted-source roots, ephemeral
operator policy and private-stdin actors executed without image source files.
The full runner passes 820 cases and seven component scripts; 415 Python files
pass formatting, and strict typing covers 51 modules. Both built wheels pass 204
selected tests; all 117 packaged files match source and imported namespaces come
from the extracted wheels. Positive and negative installed-wheel consumer checks
verify Python typing. An isolated copy of selected validation-stage inputs passed
15 regressions and imported its HTTP test with the built client. That check did
not execute the Dockerfile's full validation command; two stale module names
remained and were subsequently caught by report 3. Docker build execution
remains a separate target check. Installed JavaScript, packaged TypeScript 5.9.3
consumer checks and Playwright type checking pass. The updated actual HTTP test
was attempted here and listener binding is still denied. Evidence, path maps and
resource hashes are under `.artifacts/code-review/cleanup-pass/tooling/`.

A subsequent CI fixture repair gives the CommonJS personal-campaign test its own
complete cache-aware price contract while retaining the historical controlled
fixture's price. The shared setup now runs offline through normal admission and
settlement, including rejection after credential rotation. Worker readiness uses
the installed package's module entry point; its four listener-free checks run in
the offline suite. All loopback suites also load under an offline import check,
which covers the corrected client-boundary and socket-lease imports. The full
runner passes 827 cases and seven component scripts; 416 Python files pass
formatting and strict typing covers 51 modules. The CommonJS fixture now reaches
listener creation here, where the executor denies binding. Its actual wire
exchange and live worker handshakes still require the target checks. The log is
`.artifacts/code-review/cleanup-pass/tooling/ci-fixture-regressions.log`.

A browser CI follow-up fixes Build & context rendering after historical
milestones were removed from the API. The page uses current build/package
metadata and displays the server version. Its new offline regression reproduces
the former `milestones.join` exception and passes with the fix, including when
LiteLLM is absent. All seven console scripts, nine browser-fixture tests and
Playwright type checking pass. The focused three-browser run was attempted but
stopped at the executor's denied fixture bind; browser verification remains a
CI gate. Evidence is under `.artifacts/code-review/build-context/`.

The HTTP fixture follow-up passes the bound test port directly to the shared
host client and replaces the credential journey's retired identity URL with
`/operator/v1/integration/identity`. An offline route check covers authentication,
disabled display lookup and the integration-profile boundary. Both reported
failures reproduce against the prior fixtures; both corrected journeys pass
with real HTTP handlers and parsers over socket pairs. All 28 focused offline
checks, Ruff lint and formatting pass. Actual TCP verification remains a CI gate.
Replay evidence is under `.artifacts/code-review/http-fixtures/`.

## Report 3 release fixes

The six before-release groups in the 2026-11-20 review are implemented. This is
a source/test result, not a completed deployment or release qualification.

| Review item | Change and evidence |
| --- | --- |
| 3.1: Compressed paid responses | The trusted relay requests identity encoding. The Responses lower adapter removes encoding and length headers after bounded decoding, so a compressed provider reply is decoded once. Gzip/deflate regressions retain candidate text and usage, enforce the decoded cap and close streams. Real TLS fixture cases are also registered. |
| 3.2: Service build validation | Dockerfile test names match the staged files. An offline check resolves every operator validation module against the staging list. The exact four-module Dockerfile list passes eight tests on disposable staged sources over socket pairs; this is not a Docker build. The earlier validation claim above is corrected. |
| 3.3: Unread request bodies | Both servers inherit central body-consumption tracking and close before a response when declared body bytes remain or framing is ambiguous. Actual HTTP parser/socket-pair tests cover rejected POST bodies, GET bodies, duplicate lengths, transfer encoding and legitimate pipelining after a fully consumed body. |
| 4.3.1–4.3.2: Login/session exhaustion | Throttling uses a backend peer/account pair with inactive-entry eviction. Successful logins replace the principal's oldest session at a four-session limit. Ordinary sessions occupy at most 56 of 64 slots; administrator admission can displace an ordinary session. Evicted wire tokens are revoked outside the session lock. Proxy client-level throttling remains the proxy's responsibility. |
| 4.2.1: Trusted dependency isolation | The service installs an 11-package subset of the existing reviewed worker lock plus the client wheel. LiteLLM is absent from service dependency, validation and runtime stages, with build/startup assertions. Preparation inspects dependency and client wheel archives before installation. Both previously orphaned frozen checks now name real Docker runners: the service's frozen interface counterexamples and the worker's usage-model test. LiteLLM-dependent checks use a temporary read-only worker validation mount. |
| 4.1.1–4.1.2: Campaign recovery and service ownership | Owner-only exposure acknowledgement records a reason, retains the full bound or higher known cost, leaves provider usage unchanged and preserves attempt counts/audits. Closed-campaign exposure remains visible without blocking a new explicit allowance; late corrections remain reconcilable. Admission and summary share exposure arithmetic. Writable stores take an exclusive lease; a second process is rejected before recovery. Read-only offline tools share leases after the writer stops. |

Verification passes 846 unittest cases across 103 module registrations and two
script suites, seven console scripts, lint, formatting on 417 files, and strict
mypy on 51 files. Built server/client wheels pass 245 selected tests; all 117
checked package files match source and imported namespaces come from those wheels.
The runtime lock resolves offline for CPython 3.12 Linux ARM64 using the existing
reviewed artifacts. All 117 wheel hashes match and archive inspection finds no
startup hooks. The three frozen interface counterexamples pass against the shipped
HTTP dependency versions. Evidence is under `.artifacts/code-review/report-3/`.

Actual image builds, the worker's LiteLLM-dependent checks, real listener/TLS
fixtures and browser journeys still require their target environments. No
existing profile was restarted, no provider inference was invoked, and the
frozen worker requirements, wheel inventory and migration bytes are unchanged.

## Remaining review work

This is the maintained checklist from the conversation, with stable numbers.
Update the status and evidence as each batch proceeds. Last updated: 2026-11-20.
The six release-fix groups above are implemented at `ee6c444`; their outstanding
target checks are tracked in item 1.

Statuses: **Open** means work has not started; **In progress** means active work;
**Partial** means implemented work has a known source follow-up remaining;
**Implemented** means source changes and local checks pass, with any remaining
target checks stated explicitly; **Complete** means the required verification
also passes. A pending or unavailable check is never a passing result.

| # | Workstream | Status | Remaining scope / evidence |
| --- | --- | --- | --- |
| 1 | Deployment qualification | Open — target checks pending | Build both images; run real HTTP/TLS, browser, credential-initialization and frozen-worker checks. Previously orphaned checks now have runners; worker execution remains pending. Current local evidence: 904 unittest cases, seven console scripts and 370 packaged-wheel tests; socket-pair HTTP/TLS checks pass. Real listener/deployment checks remain pending. |
| 2 | Blocking work and performance | Implemented — local checks pass | Paginated usage attempts/exports; SQL visibility/cutoff/latest-revision selection; independent bounded read snapshots; decoding outside writer locks; sender checks and atomic first writes on bounded check threads; password hashing outside shared locks. `OperatorProjection.overview_counts` now aggregates states in SQL using an independent snapshot (4.1.4). Full cohort aggregates intentionally still process all visible attempt metadata (4.1.3, 4.2.2, 4.3.3). |
| 3 | Remaining authentication/HTTP hardening | Implemented — local checks pass | Login backoff/unknown-user budgets, password-change throttling, non-ASCII CSRF rejection, safe asset/body failures, CSP/conditional HSTS and spreadsheet-safe CSV exports. Commit `b04dafb` (4.3.1, 4.3.5). |
| 4 | Gateway correctness | Implemented — target checks pending in item 1 | Definite pre-send rejection, sender-owned forwarding headers and exact timeout keys, committed campaign authority epochs, separate socket volumes with peer read-only mounts and an owner-operated topology probe. Commit `a698cdf` (4.2.3). |
| 5 | Worker lifecycle and diagnostics | Implemented — target checks pending in item 1 | Worker SIGTERM cleanup, ordered loop/listener closure, one five-second handler join budget, Compose init/grace periods, bounded rotating diagnostics and cached tails. Overview/API show queue, drop and write-error counts. Commit `a698cdf` (4.2.3). |
| 6 | Persistence recovery | Implemented — local checks pass | Authorized retries replace only uncommitted vault successors; ambiguous commits retain sealed files. Nested rollback preserves the original error; admission uses one snapshot. Probe retry retention is documented/tested. Failed executors drain accepted work, replace their pool and expose readiness/counters (4.1.4). |
| 7 | Logging | Implemented — local checks pass | Expected wire rejections log public codes at INFO; empty/idle connections are quiet, incomplete-request timeouts remain visible; operator route words derive from routing; Coordinator failures identify their stage (4.3.4–4.3.5, 5.1). |
| 8 | Client fixes | Implemented — Rust/.NET/TypeScript target checks pending | JS total deadlines and definite local serialization errors; Python strict identifiers, typed errors, status/retry handling and private CAs; private credentials/transport ownership; aligned protocol codes and input policies across clients. 144 shared cases, installed JS/52 safety checks, Go race/vet and Java checks pass. Commit `cfe549d` (4.5.1–4.5.3). |
| 9 | Dependencies and CI | Open — broader CI hardening deferred | Declare gateway/client dependencies; test shipped library versions; pin remaining actions, bootstrap downloads, toolchains and TypeScript inputs (4.4.2–4.4.3). |
| 10 | Test-runner gaps | Implemented — Docker credential-volume check pending in item 1 | Class/inherited-class and JS/TS inventories; guarded Python/Node children and UDP/DNS; empty/all-skipped suites fail; runtime failures are collected. Compose-based named-volume/UID qualification is implemented. Latest Python executable-line coverage measures 86.69% (4.4.4). |
| 11 | Structural cleanup | Partial — class/file-size follow-up remains | Initial cleanup is implemented in `8c43850`: HTTP/Coordinator steps, direct registry routes, checked Store interface, shared helpers, explicit composition, identity/time handling, worker isolation and source organization. The subsequent file-size work order adds stricter completion targets: Registry/accounting domain splits, smaller Coordinator/module files, retained evidence/test splits and a size ratchet. Follow-up W1–W7 status and measured counts are recorded below. Strict scope is 66 files; 2,383 existing library typing errors remain budgeted debt. |

### Implementation pass: items 2–5

The authorized changes were delivered in these reviewable commits. The checklist
review below identifies an additional item 2 follow-up that remains open:

- `b04dafb`: authentication/HTTP hardening and password hashing outside shared locks.
- `25f1835`: independent report snapshots and usage-attempt pagination.
- `a698cdf`: atomic authorization/first writes off the response loop, campaign
  invalidation, socket ownership, worker shutdown and bounded diagnostics.

Validation for this pass:

- Full offline suite: **864 unittest cases**, 103 module registrations, two script
  suites and seven console scripts. Ruff passes, **419 Python files** are formatted,
  and strict mypy passes on **51 source files**. The final atomic epoch-publication
  refinement also passes the 14 campaign and 24 database-batch tests.
- Barrier/socket-pair checks verify that report readers do not block a writer,
  a blocked final check does not stall a paid reply, revocation/would-block cases
  still prevent unauthorized first writes, and attempt pages preserve full totals,
  cohort costs and visibility. A real child process verifies worker SIGTERM cleanup.
- The two previously reported HTTP journeys pass over real HTTP parsing on socket
  pairs. The service Dockerfile's exact four-module validation list passes **nine
  tests** on staged source with the frozen dependency fixture. These are source
  replays, not image builds or real TCP/TLS qualification.
- Built server/client wheels match **119 packaged namespace files** to current
  source and pass **251 installed-wheel tests**. Server wheel SHA-256:
  `ac0336d8a39d44c988f69474462bd32d25c34b57500172e2f7ebe1af357604f1`.
- Evidence is retained under ignored `.artifacts/code-review/review-items-2-5/`.

Item 1 remains open for actual image builds, peer read-only socket mounts and
signal/grace-period behavior on Docker, real HTTP/TLS, browsers, credential setup
and the LiteLLM-dependent frozen-worker checks. No profile was restarted or model
request issued. Frozen worker versions, wheel inventories and migration bytes are
unchanged. Broader CI hardening remains deferred in item 9. Keep all 11 stable
numbers when updating this checklist in future passes.


### Checklist review and recommended next work

The earlier checklist review identified a missed performance detail from report 3
§4.1.4: overview counts decoded every submission under the shared lock. The current
pass fixed it with SQL aggregation and an independent snapshot while preserving
visibility/count semantics. Item 2 is now **Implemented**, with the report, sender
and password-hashing fixes retained.

The authorized coding batch is now implemented:

1. Finish item 2's overview aggregation follow-up.
2. Item 7: classify routine wire rejections and idle closes correctly, derive safe
   route labels from routing, and distinguish Coordinator failure events.
3. Item 8: start with JavaScript total deadlines and definite local serialization
   failures, then cover Python schema/status/retry handling, credential/transport
   exposure, private CAs and the remaining cross-language validation differences.

Items 6 and 10 are implemented in the subsequent pass below.
Item 1 remains a release gate for target verification; item 9 stays deferred as
requested. Keep item 11's broad structural work after the correctness fixes.

Broader GitHub Actions hardening is deferred to a separate activity at the owner's
request. This includes reviewing and pinning the remaining CI bootstrap artifacts
and action revisions (4.3.3).

Other lower-severity findings and carried-forward structural items remain open
unless explicitly listed as fixed above. Added coverage is not a substitute for
deployment, security or performance qualification.

### Current pass: overview, logging and clients

Items **2, 7 and 8** are implemented in `efba749`, `13b2f98` and `cfe549d`:

- Overview counts aggregate states in SQL using an independent read snapshot;
  no submission JSON is decoded under the writer lock. Scope, empty states,
  unknown states and all existing count meanings are preserved.
- Expected wire `RequestError` responses log public codes/status at INFO without
  duplicate stacks. Unexpected failures retain sanitized stack locations. Empty
  connections and idle expiry are quiet; partial/pipelined request timeouts remain
  visible. Operator route words derive from the routing table. Coordinator failures
  identify admission persistence, preparation, description, intent persistence,
  failure persistence and attempt waiting separately.
- Every JS client exchange has a 35,000 ms total fetch/body budget (`timeoutMs`,
  explicit `null` to disable). Abort paths cancel/release active readers and clean
  up late responses. Invalid local serialization gives `SCHEMA_INVALID`/`never`
  before fetch. Credentials and injected fetch functions are private fields.
- Python adds private-CA `verify=` support without replacing its deadline transport;
  identifiers reject final newlines while unanchored patterns retain substring
  behavior. Closed clients, invalid request objects, attribution status checks and
  accounting retry guidance use the documented typed behavior. The public raw
  accounting transport property and dead decoder/closed check are removed.
- Decoded schema/correspondence failures use `PROTOCOL_INVALID`; valid server error
  codes are preserved. Accounting 5xx guidance defaults safely to `query_first`
  when missing/invalid. Wire 0.3 C0/DEL and wire 0.2 null-request policies align
  across languages. JS accounting errors expose snake_case fields while retaining
  existing camelCase getters. Compatibility details are in the client guides.

Validation:

- **873 unittest cases** across 103 offline module registrations, two script suites
  and seven console scripts pass. Ruff, formatting of **419 Python files** and
  strict mypy on **51 source files** pass. The final typed-503 logging refinement
  also passes all 22 HTTP-structure tests.
- **144 shared client cases** pass against Python, a freshly installed JS package,
  Go with the race detector, and a freshly built Java JAR. Go vet passes. The JS
  installed-consumer runner passes all its checks, including **52 safety tests**
  for stalled fetch/body reads, slow chunks, late responses, cancellation, local
  serialization and credential redaction. No real network calls are made there.
- Python private-CA tests perform actual TLS handshakes over socket pairs: both
  clients accept the configured CA and the default trust store rejects it before
  HTTP request bytes. Deadline and serialization tests pass without listeners.
- Built server/client wheels match **119 packaged namespace files** to source and
  pass **293 installed-wheel tests**. The exact service image validation module
  list passes **nine staged-source tests** over socket pairs with the dependency
  fixture. These checks do not constitute an image build or deployment acceptance.
- Package exports and TypeScript declaration syntax pass. Full TypeScript type
  checking was unavailable because the pinned compiler is not available on the
  configured tool paths.
  Rust could not execute: the installed Cargo/toolchain is x86_64, while this
  executor requires ARM64. .NET is unavailable. Their source/tests are updated;
  Rust/.NET runtime and TypeScript compiler checks remain **pending**, never passed.
- Fresh wheel SHA-256 values: server
  `cb3b5070219bd782105129348da555a124cb93f8e9e7f083c2d63fab7c59d5d4`;
  Python client
  `a3824c8a6dc78ed528972f333cba36bf20c262946fbd922d943de1c4a75058cf`.
  Evidence is under ignored `.artifacts/code-review/items-2-7-8/`.

No deployment was restarted, no provider inference was issued, and frozen worker
inputs/migrations were unchanged. Item 1 remains open for target qualification;
item 9 remains deferred. Items 6 (persistence recovery) and 10 (test-runner gaps) were selected for the
subsequent pass below; item 11 remains structural work.

### Implementation pass: items 6 and 10

Persistence recovery and test-runner changes follow the pushed `c2712db` baseline
in separate commits. Item 6 is delivered in `1ec40a6`; the item 10 commit records
the runner changes and combined evidence below. Deployment/toolchain checks
remain distinct gates.


### Implementation pass: item 6

Persistence recovery now permits an authorized credential replacement to overwrite
only the sealed version immediately above the committed version. A restart after
sealing no longer wedges later replacement. Ambiguous commit acknowledgements
preserve the selected file, and idempotent retries restore the authority epoch and
resume retired-file cleanup. No unrelated vault files are swept.

Nested savepoint cleanup preserves the action's original exception after SQLite
has already rolled back; rollback errors add safe type-only notes. Registry
explanation, admission and current-authority checks now share one read snapshot
across policy, destination and price selection. Probe operation IDs retain the
existing bounded observation window; API/database guidance and a prune/retry
regression make that limit explicit.

A failed executor submission cannot replay rejected work. Accepted actions drain
once before a fresh bounded pool accepts new work; failed replacement remains
visibly recovering and shutdown prevents replacement. Sender status includes pool
states/counters and readiness requires both execution and sender-check pools ready.

The 62 focused persistence/database/resource/observation tests pass. Final combined
suite, package and coverage evidence is recorded with item 10 below. Frozen worker
inputs, migrations, deployment state and provider execution are unchanged.


### Implementation pass: item 10 and combined validation

The runner audits every local class when a file is registered by class, including
inherited classes and TestCase aliases, and rejects method-only registrations.
The JavaScript/TypeScript inventory classifies 45 sources with executable commands
or explicit target/helper reasons. Both runners consume it. The previously
orphaned CommonJS package-import check now runs against a fresh installed package;
installed-SDK evidence actors retain explicit target status.

Python socket/DNS/UDP guards now propagate through Python children/grandchildren,
including isolated `-I -S` consumers and replaced environments. Node children use
a socket/DNS/UDP/fetch preload; native helper commands are restricted to audited
local operations. The existing shell capture fixture explicitly wraps its Python
consumer. These are accidental-network guards, not an OS sandbox for hostile code
or native extensions. Empty/all-skipped modules fail, and module, script, console
and installed-client runtime failures are collected before exit.

Credential qualification now reads Compose's actual isolation and credential
mounts. Two separate initializer containers create/replace credentials on one
fresh named volume, then a service-UID container verifies persisted replacement
and read-only access. Configuration regressions reject tmpfs, extra capabilities,
external volumes and live-profile volume names. This source/configuration work
passes; the actual Linux ARM64 Docker run remains pending under item 1.

Combined verification:

- **889 unittest cases** across **104 module registrations**, two script suites,
  seven console scripts and the **522-check** JavaScript conformance script pass.
- Ruff passes; **423 Python files** satisfy formatting and strict mypy passes on
  **51 source files**. The isolated-child guard, class/JS inventories, failure
  collection and coverage recorder have executable regression cases.
- Fresh server/client wheels match **119 namespace files** byte-for-byte and pass
  **355 installed-wheel tests**, including the new recovery regressions. Server
  wheel SHA-256: `997a35d09fa06704706a8f705f773947c28bb3d6dbffc55677f680d73331a437`.
- Guarded installed JavaScript checks pass **144 shared cases**, **52 safety
  cases**, package import, client/actor/transport checks and nine output cases.
- `tools.check --coverage` measures **86.02%** Python executable-line coverage
  (**16,994 / 19,756** lines) for service and Python client source. Fresh per-run
  JSON retains file hashes and missing lines, including wholly unexecuted files.
  This bytecode line-table measurement includes worker threads and guarded Python
  children; it makes no branch/native/JavaScript coverage claim or threshold.
- Evidence is retained under ignored `.artifacts/code-review/items-6-10/` and
  `.artifacts/coverage/python-uacjjhuz/`.

Items 6 and 10 are **Implemented**. Item 1 still requires actual Docker, real
HTTP/TLS, browsers, named-volume credential permissions and frozen-worker checks.
Item 8's Rust/.NET/TypeScript target checks remain pending. Item 9 stays deferred
at the owner's request, and item 11 remains the broad structural cleanup. No
profile restart, provider inference, frozen-input update or migration change was
performed in this pass.


### Implementation pass: item 11

Structural cleanup is implemented across the requested boundaries:

| Area | Result |
| --- | --- |
| HTTP/Coordinator functions | `web.serve` is six lines of composition, replacing its 575-line closure. Transport/authentication, work operations, integration routes and CSV projection are separate. Operator registry reads resolve directly to named route handlers with explicit roles on restricted reads. Coordinator `_submit` falls from 202 to 59 lines, `_start_attempt` from 175 to 51 and `_observe_response` from 181 to 41, with named validation, persistence, preparation, waiting and response steps. |
| Store and typing | The Store protocol covers database access, close, work ownership, guard/intent and all successor methods. SQLite conforms under strict mypy. Checked scope grows from 51 to 66 files, adding the Store implementation, canonical validator, wire HTTP package, shared policy/executor and IPC framing. Whole-library debt falls from 2,934 to 2,383 errors; per-file budgets now block increases and give new files a zero-error budget. Full-library typing remains tracked debt. |
| Shared implementation | Twelve duplicated SQL definitions have one shared owner; 34 numbered query names have descriptive replacements. CSV serialization/body framing and worker/proxy credential policy are shared. Credential-read audits use one helper without advancing authority. Shared reporting helpers have public names. Optional accounting configuration is passed into construction, and guarded sending is selected during composition. |
| Worker isolation | The isolated worker stages as `ezllmrouter_worker` and imports only its explicit package helpers. The in-process LiteLLM adapter moves to tooling and leaves the server wheel. Frozen negative validation mounts its minimal tooling explicitly and supplies the required synthetic constructor credential; a mock-vendor replay passes. Actual frozen-image execution remains pending. |
| Time and identity | New precise timestamps have fixed six-place UTC `Z` formatting; expiry compares instants and preserves the chosen stored representation. New defaults use generic EzLLMRouter project/image/diagnostic and consumer names. Persisted instance identity, an older default consumer and an existing Compose ownership marker retain their IDs/project. Conflicting identity changes and unowned resource collisions are rejected. A custom-owner policy/restart regression passes. |
| Source/evidence organization | Accounting evidence and historical Docker-input tools move out of `tests/`; installed-SDK proof runners move to gateway tooling. Runtime staging uses byte-identical fixture copies under `deploy/local/inputs/fixtures/`. Internal schema filenames use `retrieval` while all schema IDs and bytes remain identical. Preparation rejects dirty runtime sources; `RUF100` rejects dead lint suppressions. |
| Recorded decisions | Database/encryption/development guides record the unchanged adopted digest-domain baseline, requirements for future versions, preserved historical IDs, explicit module ownership and local POSIX publication/lease constraints. Existing migrations, locks, prices, signed resources and adopted fixtures are unchanged. |

Verification:

- **904 unittest cases** across **105 module registrations**, two script suites,
  seven console scripts and **522** JavaScript conformance checks pass.
- Ruff, formatting on **439 Python files** and strict mypy on **66 files** pass.
  The whole-library budget audit passes with **2,383** existing errors; this is a
  regression budget, not a passing whole-library type check.
- Fresh server/client wheels match **129 namespace files** byte-for-byte and pass
  **370 installed-wheel tests**. The server wheel excludes the in-process LiteLLM
  adapter. Its SHA-256 is
  `8d24d5c19ac6ba8e0d706f95334b0ce46491adf84834576afef0a135cc2d3054`.
- Installed JavaScript passes **144 shared cases**, **52 safety cases**, package,
  actor/transport and output checks. Go formatting/vet/race and Java packaged-JAR
  checks pass, including **144** shared cases for each client.
- Python executable-line coverage is **86.69%**, **17,390 / 20,059** lines. It covers
  the service and Python client, including worker threads/guarded Python children;
  it does not measure branches, native code or JavaScript.
- The final tooling-only staging changes pass 11 packaging/import checks and five
  tooling checks. These include the relocated adapter and staged service entry points.
- Nine renamed schema/registration/tariff resources match their previous bytes;
  digest-domain constants, frozen/runtime locks, migration files and adopted
  contract fixtures match the `9a40046` baseline.
- Evidence is under ignored `.artifacts/code-review/item11/`,
  `.artifacts/coverage/python-tci43q9y/` and `.artifacts/type-audit/library-14f0m6u6/`.

Nine of the eleven workstreams are now **Implemented**. Item 1 remains open for
actual image builds, real listeners/TLS, browsers, named-volume/capability and
frozen-worker qualification. Item 8's Rust/.NET/TypeScript target checks remain
pending. Item 9 stays deferred at the owner's request. This pass changed source
and disposable test artifacts, without restarting the existing daemon, issuing
provider inference, acquiring gateway inputs or changing migrations.


### Item 11 follow-up: class and file-size work order

The owner's `EzLLMRouter-file-size-report-2026-11-20.md`, outside the repository,
measures `c2712db`. The following reconciliation measures current source at
`8c43850`, using physical Python source lines and AST function/class spans. This
work order supplies completion targets beyond the initial structural pass above;
item 11 is therefore reopened as **Partial**. The current checklist has eight
implemented workstreams, one partial workstream and two open workstreams.
No additional runtime refactoring is included in this reconciliation.

| Work item | Current status | Remaining finish line |
| --- | --- | --- |
| W1 — wire HTTP package | Implemented — local checks pass | `web.py` is composition only, and every function in `wire_http/` is at most 80 lines. Existing HTTP regressions pass; real listener qualification remains item 1. |
| W2 — Registry domains | Implemented — local checks pass | The facade is 510 lines, down from 1,911; all Registry/domain functions are at most 80 lines and domain modules at most 600. Public methods/signatures remain available, locks and publishing transactions retain ownership, and new domain modules pass strict typing. Move and cleanup are separate commits. |
| W3 — ExternalAccounting domains/tests | Implemented — HTTP target checks pending | Accounting facade/domain modules are each below 600 lines and all runtime functions at most 80. All eight modules pass strict typing. The 16 HTTP tests retain their assertions in six files below 400 lines; actual listener execution remains pending. Oversized individual test journeys remain explicitly budgeted for the W6 test cleanup. |
| W4 — Coordinator pipeline | Implemented — local checks pass | The facade is 577 lines, below the 900-line target; every Coordinator/domain function is at most 80 lines. Public imports and constructor arguments remain available. The facade, step modules and cache accounting pass strict typing, with concrete checks for authority, registry and sender capabilities. Failure/unknown-outcome boundaries remain around the same operations. |
| W5 — medium runtime modules | Partial | Direct operator routes, CLI composition, public reporting helpers and the checked Store interface are implemented. Canonical validation, demo projection, report/probe/admin functions and Store decomposition remain. |
| W6 — evidence and large tests | Partial | Historical Docker-input tooling moved under `tools/`; private input locations are configurable. Large retained runners, preflight/tool-cycle tests and deployment exercises still need decomposition. No evidence runners have been deleted. Obtain the owner's decision before deleting or archiving any `dev12_*` or `ct02b_*` runners. |
| W7 — source-size ratchet | Implemented — local checks pass | Registered `tests.unit.test_source_size` measures tracked and new non-ignored source. The 98 existing allowances are capped at the `33f7a45` baseline; growth and new offenders fail, and reductions require tightening/removing entries. Runtime thresholds: 800-line files, 100-line functions and 600-line classes; tooling/test thresholds: 1,500-line files and 200-line functions. Remove allowances once below their thresholds. |

| Server measure | Report baseline `c2712db` | Current `8c43850` | Work-order target |
| --- | ---: | ---: | ---: |
| Files over 1,000 lines | 3 | 3 | 0 |
| Files over 800 lines | 5 | 5 | 0, or shrinking explicit allowances |
| Functions over 150 lines | 16 | 9 | 0 |
| Functions over 100 lines | 38 | 31 | At most 10, explicitly allowlisted |
| Largest class span | 1,805 | 1,816 (`Registry`) | At most 600 |

Recommended implementation order: W7 to freeze growth, then W2, W3, and the
remaining W4/W5/W6 work. Keep code moves and subsequent cleanup in separate
commits. Public imports/signatures and all route/error/schema/contract bytes stay
stable. Existing lock, transaction and read-snapshot scopes must enclose the same
statements after extraction. Run the full `tools.check` gate and `git diff --check`
before each implementation commit; real HTTP checks require an environment that
allows loopback. New split modules should enter strict typing when clean. Frozen
LiteLLM inputs and the existing daemon remain outside this refactoring scope.

Reconciliation validation: the full `tools.check` gate passes with 904 Python
cases, lint/formatting, strict mypy on 66 files, the library typing-debt budget
and the maintained script/console checks. Markdown links and `git diff --check`
pass. This documentation-only update performs no additional target qualification.


### Item 11 follow-up: W7 size ratchet

`tools/source_size.py` measures source files and Python AST class/function spans,
including nested and async definitions with qualified names. Runtime limits are
800/100/600 lines for files/functions/classes; tooling/test limits are
1,500/200/1,500. Non-Python source files receive the file-size gate; function and
class spans are measured for Python. New non-ignored files participate before
staging. Every existing oversized symbol has an explicit ceiling in
`tools/source_size_budget.json`. Growth fails, reductions require lowering the
ceiling, and resolved/deleted definitions require removal of their allowance.
The five gate regressions cover new/growing offenders, shrinking/resolved debt,
qualified nested/async definitions, class limits and non-Python file limits.

W7 verification: full `tools.check` passes 909 Python cases, lint/formatting,
strict mypy on 67 files, the library typing budget and script/console checks.
The frozen inputs, schemas and runtime behavior are unchanged.


### Item 11 follow-up: W2 Registry code move

The first Registry commit relocates 38 methods into reads, source permissions,
credentials/probes, local tokens and six mutation-family modules. Existing
`Registry` methods remain descriptors on the original class, with the same
signatures and shared instance context. Common constants/value validators and
`ConnectionSchedule` retain their original public imports. The existing
`registry.provider_probe` injection point is preserved.

An AST comparison against `3894723` verifies every moved executable body/signature
(normalizing only docstring indentation) and every
retained method, including lock/read/transaction statements. The sole expression
rebinding routes the probe import through its existing patch point. The facade
is now 540 lines; cleanup of long methods and typing follows separately. Existing
size/type allowances transfer with their code and never increase in aggregate;
the moved Registry typing diagnostics change from 178 to 149. That count alone
is not a claim that the new domain modules are already strictly typed.

W2 move verification: the full gate passes 909 Python cases and strict mypy
on the existing 67-file scope. The unchanged resource-lifecycle tests also pass
after retaining their original clock injection point. No routes, contracts,
locks, migrations, frozen inputs or deployment state changed.


### Item 11 follow-up: W2 Registry cleanup

The cleanup separates inventory reads, per-model projection and discovery status;
credential validation/publication, probe observations and provisioning checks;
model-change families; bootstrap construction; and management request parsing.
Existing gate/read/transaction owners call these steps at their original points.
Public method descriptors retain their argument/default signatures. Record typing
is applied at the persisted JSON boundary, with typed Store, authority and vault
capabilities; casts do not add runtime validation or change errors.

All 15 newly checked domain/catalogue modules pass strict mypy. The existing
Registry facade retains six typing errors at older lifecycle/attribution
collaborators; these are explicitly budgeted, not claimed as fully typed.
Whole-library diagnostics fall to 2,179 and no per-file budget increases. Six
resolved source-size allowances are removed, leaving 90. Typed catalogue
interfaces use named band validators so typing does not inflate long functions.

W2 cleanup verification: full `tools.check` passes 909 Python cases, lint and
formatting, strict mypy on 82 files, the typing-debt budget, the size ratchet and
the maintained script/console checks. All Registry/domain files are at most 600
lines and every function is at most 80. A real loopback bind is denied with
`PermissionError` (errno 1), so provider/HTTP target checks remain pending.


### Item 11 follow-up: W3 accounting code and test move

The first W3 commit relocates 23 methods under the original ExternalAccounting
instance context. Facade imports, schema resources, errors and clock injection
remain available at `integration_accounting`. AST comparisons preserve all moved
executable bodies/signatures, with only facade-qualified global references and
docstring indentation normalized. In-transaction dataset authorization rechecks
and all read/write scopes are preserved.

The 2,257-line HTTP test module becomes six domain files (299–382 lines) plus one
shared fixture. All 16 test bodies, decorators and assertions are identical. The
new modules are registered in the loopback suite; their actual HTTP execution
remains pending because this host denies listener binds. Offline accounting
recovery, concurrency and database regressions run in the normal suite.

Full `tools.check` passes 909 Python cases, lint/formatting, strict mypy on the
existing 82-file scope, size/type budgets and script/console checks. Existing
typing debt transfers explicitly with the code, without an aggregate increase;
the whole-library count is 2,137. The move resolves five size allowances, leaving
85. These figures do not claim the newly moved accounting modules are already
strictly typed. Cleanup follows separately.


### Item 11 follow-up: W3 accounting cleanup

Ingestion now names parse/admission, receipt recovery, run/lineage validation,
attempt start, decision/account-resolution checks and receipt persistence. The
original transaction wrapper still encloses its first dataset authorization
recheck and every subsequent write. Snapshot publication retains the same
transaction recheck and separates retention policy from reference binding.

Report/export snapshot reads remain inside their original caller read scopes.
Filtering, account/snapshot state, usage/result selection, money rendering and
export reference projection have named owners; no totals, currencies, decimal
rounding, snapshot digests, status strings or response fields change. Connected
lineage has one focused module and traverses the same affected component in the
same validation order. Shared validators separate shape, string/time traversal
and event/snapshot semantics without changing schema bytes or public errors.

Every accounting runtime module is below 600 lines and every runtime function at
most 80. All eight facade/domain modules pass strict mypy, bringing checked scope
to 90 files. Whole-library typing diagnostics fall to 2,003, with no increased
per-file allowance. The 16 HTTP test bodies/assertions remain in their domain
files; individual long test journeys are still explicitly size-budgeted and will
be decomposed with the remaining oversized-test work in W6.

W3 cleanup verification: full `tools.check` passes 909 Python cases, lint and
formatting, strict mypy on 90 files, the 2,003-error library-debt budget, the
size ratchet and all maintained script/console checks. Real HTTP qualification
remains pending; the listener-bind denial is not a passing HTTP result. No
schema, migration, frozen dependency, provider execution or live-profile change
was made.


### Item 11 follow-up: W4 Coordinator code move

The Coordinator facade is now 516 lines; its public class and constructor remain
at `ezllmrouter_server.core`. Twenty-nine methods move to policy, admission,
attempt, outcome and status modules, using the same instance context. An AST
comparison against `3f94e21` verifies executable bodies, signatures/defaults and
all `try`/`except`, gate/read/transaction statements. Shared helper and logging
references still resolve through their original facade injection points.

The full gate passes 909 Python cases, including tool-cycle, recovery, unknown
outcome and release-safety regressions. Strict typing still covers the prior
90-file scope; typing cleanup of the new modules follows separately. Existing
debt transfers without aggregate growth; whole-library diagnostics are 1,924.
Removing the resolved Coordinator file/class allowances leaves 76 size entries.
There are now no server Python files over 1,000 lines. Frozen inputs, contracts,
schemas, migrations and live deployment state remain unchanged.


### Item 11 follow-up: W4 Coordinator typing cleanup

Typed interfaces describe preparation, legacy direct sending, context-aware sending,
plan issuance, registry/attribution and campaign actions. Compile-time conformance
checks cover the real authority, Registry and isolated-worker sender; the latter
correctly exposes context sending rather than a legacy direct-send method.
Construction keeps the same runtime collaborators and selection behavior.

Current-authority checks and text-output validation gain focused helpers inside
their existing exception boundaries. Provider usage and cache-aware observations/
pricing have named helpers; all arithmetic, category subtraction, zero/unknown
semantics, currency/rounding and model matching remain unchanged. Record/future
boundaries are typed without adding runtime validation or moving locks.

The facade is 577 lines and all Coordinator/domain functions are at most 80.
Strict checking expands to the whole Coordinator family and cache accounting.
The source-size ratchet removes the resolved cache-usage allowance. Final gate
evidence is recorded after validation below.

W4 cleanup verification: the full gate passes 909 Python cases, lint and
formatting, strict mypy on 98 files, the library-debt ratchet (1,805 existing
errors), size budgets (75 allowances) and script/console checks. The tool-cycle,
release-safety and cache-accounting suites also pass focused checks. No provider
call, daemon restart, schema/migration or frozen-input change was performed.


### Item 11 follow-up: W5 canonical validator move

The first canonical-validation commit moves the 277-line validator unchanged
to `request_validation.py`, preserving its executable AST, arguments/defaults and
error order. The public `canonical.validate_text_request` signature delegates
lazily so either module can be imported first. Canonical primitives, digest
domains and the existing timeout-constant import remain available. The existing
size allowance transfers without increasing; the new module is strictly typed.
Full `tools.check` passes 909 Python cases, strict mypy on 99 files, lint/format,
source/type budgets and script/console checks. Field/phase decomposition follows
in a separate cleanup commit.


### Item 11 follow-up: W5 canonical validator cleanup

The 277-line validator becomes a 25-line phase orchestrator. An immutable ordered
field-validator table preserves version/identifier/observation/trace precedence;
separate phases own tool definitions, scope/features, generation settings, prompt
binding and message resolution. Shared message IDs, call/result binding, labels
and tool-content state retain the original validation order and final checks.
Every request-validation function is at most 80 lines, so its size allowance is
removed. Public canonical imports/signatures and digest/schema bytes stay stable.

A differential replay against `bc2ab78` compares 2,203 synthetic request mutations,
including pairwise error combinations and text/tool messages. All 44 accepted
cases have identical serialized outputs; every rejection has the same exception
type, public code, status and message. Evidence is retained under ignored
`.artifacts/code-review/god-class/request-validation-differential.json`. Five new
maintained tests protect import equivalence and important error precedence.

Canonical cleanup verification: full `tools.check` passes 914 Python cases,
strict mypy on 99 files, lint/formatting, the 1,805-error library-debt budget,
74 size allowances and all maintained script/console checks.
