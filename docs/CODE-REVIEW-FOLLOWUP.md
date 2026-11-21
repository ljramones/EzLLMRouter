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
| 1 | Deployment qualification | Open — target checks pending | Build both images; run real HTTP/TLS, browser, credential-initialization and frozen-worker checks. Previously orphaned checks now have runners; worker execution remains pending. Current local evidence at `f6746d4`: 919 unittest cases, seven console scripts and 472 packaged-wheel tests; socket-pair HTTP/TLS checks pass. Real listener/deployment checks remain pending. |
| 2 | Blocking work and performance | Implemented — local checks pass | Paginated usage attempts/exports; SQL visibility/cutoff/latest-revision selection; independent bounded read snapshots; decoding outside writer locks; sender checks and atomic first writes on bounded check threads; password hashing outside shared locks. `OperatorProjection.overview_counts` now aggregates states in SQL using an independent snapshot (4.1.4). Full cohort aggregates intentionally still process all visible attempt metadata (4.1.3, 4.2.2, 4.3.3). |
| 3 | Remaining authentication/HTTP hardening | Implemented — local checks pass | Login backoff/unknown-user budgets, password-change throttling, non-ASCII CSRF rejection, safe asset/body failures, CSP/conditional HSTS and spreadsheet-safe CSV exports. Commit `b04dafb` (4.3.1, 4.3.5). |
| 4 | Gateway correctness | Implemented — target checks pending in item 1 | Definite pre-send rejection, sender-owned forwarding headers and exact timeout keys, committed campaign authority epochs, separate socket volumes with peer read-only mounts and an owner-operated topology probe. Commit `a698cdf` (4.2.3). |
| 5 | Worker lifecycle and diagnostics | Implemented — target checks pending in item 1 | Worker SIGTERM cleanup, ordered loop/listener closure, one five-second handler join budget, Compose init/grace periods, bounded rotating diagnostics and cached tails. Overview/API show queue, drop and write-error counts. Commit `a698cdf` (4.2.3). |
| 6 | Persistence recovery | Implemented — local checks pass | Authorized retries replace only uncommitted vault successors; ambiguous commits retain sealed files. Nested rollback preserves the original error; admission uses one snapshot. Probe retry retention is documented/tested. Failed executors drain accepted work, replace their pool and expose readiness/counters (4.1.4). |
| 7 | Logging | Implemented — local checks pass | Expected wire rejections log public codes at INFO; empty/idle connections are quiet, incomplete-request timeouts remain visible; operator route words derive from routing; Coordinator failures identify their stage (4.3.4–4.3.5, 5.1). |
| 8 | Client fixes | Implemented — Rust/.NET target checks pending | JS total deadlines and definite local serialization errors; Python strict identifiers, typed errors, status/retry handling and private CAs; private credentials/transport ownership; aligned protocol codes and input policies across clients. 144 shared cases, installed JS/53 safety checks, Go race/vet, Java checks and packed TypeScript 5.9.3 consumer compilation pass. Commit `cfe549d` (4.5.1–4.5.3). |
| 9 | Dependencies and CI | Open — broader CI hardening deferred | Declare gateway/client dependencies; test shipped library versions; pin remaining actions, bootstrap downloads, toolchains and TypeScript inputs (4.4.2–4.4.3). |
| 10 | Test-runner gaps | Implemented — Docker credential-volume check pending in item 1 | Class/inherited-class and JS/TS inventories; guarded Python/Node children and UDP/DNS; empty/all-skipped suites fail; runtime failures are collected. Compose-based named-volume/UID qualification is implemented. Python executable-line coverage is recorded for the final structural pass below (4.4.4). |
| 11 | Structural cleanup | Implemented — local checks pass | W1–W7 are implemented through `f6746d4`: wire routing; Registry/accounting domains; Coordinator steps; medium runtime modules; retained evidence/test/deployment phases; and the source-size ratchet. All work-order size targets pass, with 12 shrinking allowances. Strict scope is 107 files; 1,631 existing library typing errors remain budgeted debt. Final source/package evidence and explicit target limits are recorded below; deployment qualification remains item 1. |

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
measures `c2712db`. The completed reconciliation below measures source at
`f6746d4`, using physical Python source lines and AST function/class spans. This
work order extended the initial structural pass at `8c43850`; all seven source
work items are now implemented and the size targets pass. The current checklist
has nine implemented workstreams and two open workstreams: deployment
qualification (item 1) and the owner-deferred dependency/CI work (item 9). Target
checks remain explicit within the implemented workstreams.

| Work item | Current status | Remaining finish line |
| --- | --- | --- |
| W1 — wire HTTP package | Implemented — local checks pass | `web.py` is composition only, and every function in `wire_http/` is at most 80 lines. Existing HTTP regressions pass; real listener qualification remains item 1. |
| W2 — Registry domains | Implemented — local checks pass | The facade is 510 lines, down from 1,911; all Registry/domain functions are at most 80 lines and domain modules at most 600. Public methods/signatures remain available, locks and publishing transactions retain ownership, and new domain modules pass strict typing. Move and cleanup are separate commits. |
| W3 — ExternalAccounting domains/tests | Implemented — HTTP target checks pending | Accounting facade/domain modules are each below 600 lines and all runtime functions at most 80. All eight modules pass strict typing. The 16 HTTP tests retain their assertions in six files below 400 lines; actual listener execution remains pending. Long individual test journeys are decomposed under W6, retaining their assertions. |
| W4 — Coordinator pipeline | Implemented — local checks pass | The facade is 577 lines, below the 900-line target; every Coordinator/domain function is at most 80 lines. Public imports and constructor arguments remain available. The facade, step modules and cache accounting pass strict typing, with concrete checks for authority, registry and sender capabilities. Failure/unknown-outcome boundaries remain around the same operations. |
| W5 — medium runtime modules | Implemented — local checks pass | Canonical fields, Store records, successor reporting, provider probes, attribution actions, demo projections and credential records have named boundaries. Direct operator routes and CLI composition are implemented. No server function exceeds 150 lines; nine exceed 100 under capped allowances. The largest class is 599 lines. |
| W6 — evidence and large tests | Implemented — target checks pending in item 1 | Completion handlers/runtime, retained audits/browser/client runners, long test journeys and deployment exercises have domain/phase boundaries. Every tooling/test function is at most 200 lines. Historical Docker-input tooling lives under `tools/` with configurable private inputs. All `dev12_*`/`ct02b_*` runners are retained; no deletion/archive decision is needed for this implementation. Actual listener/browser/frozen-profile execution remains pending. |
| W7 — source-size ratchet | Implemented — local checks pass | Registered `tests.unit.test_source_size` measures tracked and new non-ignored source. The initial 98 allowances at the `33f7a45` baseline are reduced to 12; growth and new offenders fail, and reductions require tightening/removing entries. Runtime thresholds: 800-line files, 100-line functions and 600-line classes; tooling/test thresholds: 1,500-line files and 200-line functions. Remove allowances once below their thresholds. |

| Server measure | Report baseline `c2712db` | Current `f6746d4` | Work-order target |
| --- | ---: | ---: | ---: |
| Files over 1,000 lines | 3 | 0 | 0 |
| Files over 800 lines | 5 | 1 (`local_connectors.py`, 847; capped) | 0, or shrinking explicit allowances |
| Functions over 150 lines | 16 | 0 | 0 |
| Functions over 100 lines | 38 | 9 (all capped) | At most 10, explicitly allowlisted |
| Largest class span | 1,805 | 599 (`PersonalCampaign`) | At most 600 |

Implementation is complete in separate move and cleanup commits. Future changes
must retain the same size ratchet and ownership boundaries. Public imports/
signatures and all route/error/schema/contract bytes stay stable. Existing lock,
transaction and read-snapshot scopes must enclose the same statements after
extraction. Run the full `tools.check` gate and `git diff --check`
before each implementation commit; real HTTP checks require an environment that
allows loopback. New split modules should enter strict typing when clean. Frozen
LiteLLM inputs and the existing daemon remain outside this refactoring scope.

Initial reconciliation validation at `8c43850`: the full `tools.check` gate passed
with 904 Python cases, lint/formatting, strict mypy on 66 files, the library
typing-debt budget
and the maintained script/console checks. Markdown links and `git diff --check`
passed. That initial documentation-only reconciliation performed no additional
target qualification.


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


### Import-order regression after domain extraction

A fresh-process check exposed a cycle when some extracted domains imported their
facade before defining the functions that facade binds. Runtime facade imports
now occur at the existing operation entry points; annotation-only imports stay
under `TYPE_CHECKING`. This preserves dynamic clock/log/probe injection and
eliminates import-order dependence without changing domain operations or ownership
scopes. All Registry/accounting/Coordinator functions remain at most 80 lines.

The maintained import regression loads each of 27 domain modules first in its
own isolated Python process. It passes, and the full gate passes 915 Python
cases, strict typing on 99 files, lint/formatting, source/type budgets and all
script/console checks. The library typing debt remains 1,805 and size allowances
remain 74. No listener, provider or existing deployment was used.


### Item 11 follow-up: W5 Store record ownership

Twenty-five record methods move unchanged into `store_work.py`,
`store_results.py` and `store_successor.py`. Database opening, instance leases,
reader lifecycle, nested transaction/savepoint ownership and close remain on
SQLiteStore. Public methods and the complete Store protocol still bind at their
original paths. The facade falls from 937 to 349 lines and SQLiteStore from 802
to 213. Every moved executable body, gate/transaction scope and signature is
verified against `66bbcf1`, allowing only explicit self typing and import wiring.

All four Store modules pass strict typing, including the existing concrete
SQLiteStore-to-Store protocol proof. Cold-import checks now cover 30 domains.
Full `tools.check` passes 915 Python cases, strict mypy on 102 files, lint/format,
source/type budgets and script/console checks. The library debt remains 1,805;
two resolved Store size allowances are removed, leaving 72. Schemas, SQL, frozen
inputs, signed fixtures and transaction behavior are unchanged.


### Item 11 follow-up: W5 successor usage report

The 191-line report becomes a 36-line orchestrator with named scope validation,
same-scope snapshot reads, latest revision selection, authorized record/dimension
projection, alternate grouping and inclusive-workflow totals. All functions are
at most 80 lines and the complete module passes strict typing. The UTC predicate
gets an explicit boolean signature; its implementation is unchanged.

A replay against `925293f` compares 1,080 role/principal/filter/record-order cases.
Serialized results, exception type/message and read/query traces match exactly.
The existing retrieval-reporting suite also passes. Evidence is retained in
`.artifacts/code-review/god-class/successor-report-differential.json`. No query,
scope, decimal rounding, output field or snapshot boundary changes.

Successor-report verification: full `tools.check` passes 915 Python cases, strict
mypy on 103 files, lint/formatting, the 1,785-error typing budget, 71 size
allowances and script/console checks.

### Item 11 follow-up: W5 provider probe phases

Provider inventory probing separates HTTP status classification, page decoding,
pagination selection, complete/partial result projection and later-page failure
classification. The public probe keeps the same nested exception boundaries,
credential/header timing, pagination limits and partially accumulated details.
The original 165-line function is below the 100-line budget; its allowance is
removed, leaving 70 entries.

A network-denied replay against `26463dc` compares 2,634 synthetic cases,
including malformed/partial pages, repeated tokens, page limits and transport
failures. Results and wire-call traces match exactly. The nine transport tests
and full `tools.check` pass: 915 Python cases, strict typing on 103 files,
lint/formatting, type/size budgets and maintained script/console checks.

### Item 11 follow-up: W5 attribution and demo phases

The attribution admin dispatcher delegates to five named action helpers. An AST
comparison preserves every original branch body, including revision checks,
validation order, SQL and returns; no transaction is added or moved. Record
annotations add only static casts at existing JSON/record boundaries.

Both demo projections now separate identity/selector validation, timelines,
lineage, attempts, events, reference totals and playback snapshots. Their common
attempt filter lives in `demo_common`, alongside the fictional arithmetic.
Public reporting helpers and Totals gain signatures without changing arithmetic.
All three demo modules join strict checking. A differential replay against
`8187bcc` compares 2,200 selector and malformed-fixture cases: output/error bytes
and fixture-read traces match. The six focused demo cases and three attribution
cases pass. No real provider or registry data is used.

The full gate passes 915 Python cases, strict typing on 106 files, lint/format,
script/console checks and both ratchets. Library typing debt falls to 1,689 and
67 size allowances remain. All server functions are now below 150 lines. The
credential-store class and retained evidence/test decomposition remain before
item 11 can be marked complete.

### Item 11 follow-up: credential-store record move

Eight binding, encryption-context, discovery and pending-cleanup methods move
unchanged to `integration_credential_records.py`; DatabaseCredentialStore keeps
its constructor, locks, mutation flows and original method bindings. AST checks
preserve executable bodies and read/transaction ownership. Clock, validation and
logging references still resolve through the public facade. The credential-store
class falls below 600 lines, eliminating the final oversized server class.

Six credential tests and the 31-domain cold-import regression pass. Full
`tools.check` passes 915 Python cases, strict typing on the existing 106 files,
lint/format, script/console checks and both budgets. Existing typing debt transfers
without growth (1,676 diagnostics); size allowances fall to 66. Typing the new
record boundary and the remaining small save-method extraction follow separately.

### Item 11 follow-up: W5 completion

The credential record module now has checked Store, registry, secret-box and
discovery capabilities, including a static compatibility check against the real
DatabaseCredentialStore. JSON/SQL boundaries use static casts; encryption,
validation, exception handling and transaction behavior stay unchanged. The save
method delegates its unchanged initial schema check to a named helper.

Full `tools.check` passes 915 Python cases, strict typing on 107 files,
lint/format, script/console checks and both ratchets. The six focused credential
cases pass too. Library typing debt is 1,631; 65 size allowances remain. W5 is
implemented locally. Actual HTTP, installed-image and frozen-target qualification
remain tracked separately; none is implied by these source checks.

| Server measure | Report baseline `c2712db` | W5 completion | Target |
| --- | ---: | ---: | ---: |
| Files over 1,000 lines | 3 | 0 | 0 |
| Files over 800 lines | 5 | 1 (`local_connectors.py`, 847; capped) | 0 or shrinking allowances |
| Functions over 150 lines | 16 | 0 | 0 |
| Functions over 100 lines | 38 | 9, all capped | At most 10 |
| Largest class span | 1,805 | 599 (`PersonalCampaign`) | At most 600 |

W6 remains: retain and decompose the completion evidence domains/runtime,
separate the large preflight/tool-cycle suites, shorten retained runners and
extract deployment exercise steps. No evidence runner is deleted or archived.

### Item 11 follow-up: W6 completion-domain and test moves

The retained completion handlers move to common, ingress, recovery, accounting,
retrieval and client modules. The runner separates plan/checkpoint generation,
setup, correlation and write/usage/identity verification. Public functions and
CompletionRuntime methods remain at their existing import paths. Handler entry
wrappers retain their original reviewed source identities; preflight still checks
the complete committed source tree, including the extracted implementations.
Standalone runner execution binds the same facade for its extracted operations.

Scope-aware AST comparisons preserve 37 tooling function/method bodies, comments,
arguments/defaults and ownership/exception boundaries. `dev12_completion_handlers`
falls from 3,556 to below 300 lines and the runner from 3,761 to below 700. The
large accounting and checkpoint functions are intentionally unchanged in this
move commit; phase extraction follows separately. Existing function ceilings
transfer with up to ten lines of import/qualification formatting overhead while
resolved file/class allowances are removed. No runner is deleted or archived.

The preflight suite splits into inventory, continuation, runtime and identity
suites; tool-cycle tests split into history, source authority, retention and
transport. Shared fixtures contain no discovered tests. All 44 original cases
and 51 test/fixture method bodies retain their assertions and executable ASTs.
The new modules are registered in the same offline gate. Fresh-process checks
also import each of 13 tooling domains first and validate all nine real handler
registrations against their expected source path/hash.

Full `tools.check` passes 916 Python cases, strict typing on 107 files,
lint/formatting, script/console checks and both ratchets. Library typing debt
remains 1,631; size allowances fall to 62. This is source validation; real
listeners, Docker, browsers and finite provider executions were not run.

### Item 11 follow-up: W6 completion-handler phases

Completion accounting now dispatches to historical-underbound, restart exposure,
finite cap, counter correction, ownership contention, minima and tariff phases.
Its former 987-line function is 23 lines; its largest phase is 199. Ingress,
authority/recovery, installed-client and retrieval handlers likewise have named
scenario/check phases. Every function in these five domain modules is below 200
lines. Public handler wrappers, scenario selection, call ordering, evidence
fields and failure/transaction scopes remain unchanged.

AST checks preserve the copied bodies of 31 extractions. A guarded 88-case replay
against `647ede5` matches dependency traces, rejections and all five complete
fictional tariff results, with sockets and subprocesses denied. This replay
checks source dispatch and tariff behavior; it does not qualify the real target
scenarios, which still require their retained environment and explicit release.

Full `tools.check` passes 916 Python cases, strict typing on 107 files,
lint/formatting and maintained script/console checks. Library typing debt remains
1,631. Six resolved function allowances are removed, leaving 56. Checkpoint,
runtime-setup, remaining retained tooling/tests and deployment exercises continue
under W6; no runner or historical evidence has been removed.

### Item 11 follow-up: W6 completion setup and continuation phases

Checkpoint verification separates the original release and seven retained
continuation boundaries. Its former 825-line function is now 135 lines; each
phase is at most 132. Inputs and returned state are explicit, while the same
passed-ID list, exact file checks, journal order, SQL reads and failure gates
remain in their original sequence. Expanding all eight helpers reconstructs the
original checkpoint AST exactly.

Runtime setup names registry construction and service endpoint phases. Start is
167 lines and continuation is 183. Inventory case projection, CLI parsing and
retained identity checks likewise have named phases; every function in the
plan, runner, setup, checkpoint and identity-verification modules is below 200.
AST expansion verifies the unchanged six original entry-point bodies across
15 extractions, including callback, try/finally and reader ownership.

A replay against `a32a9b5` matches 19 prospective plan cases (six accepted),
32 synthetic checkpoint cases (two accepted) and eight parse-only CLI cases.
The historical-evidence verifier is stubbed for synthetic checkpoint fixtures;
these are control-flow checks, not approval of a real retained campaign.

Full `tools.check` passes 916 Python cases, strict typing on 107 files,
lint/formatting and script/console checks. Library typing debt remains 1,631;
six resolved function allowances are removed, leaving 50. Remaining W6 work is
operator reporting, other retained tools, oversized individual tests and the
deployment exercises. No target release, input acquisition or daemon change ran.

### HTTP fixture close-race regression

Repeated full-gate execution exposed a macOS socketpair race in the framing test
fixture: an intentional early server close can precede the client's write-half
shutdown, producing `ENOTCONN`. The fixture accepts that specific completed-close
condition and continues reading/asserting the response. Other shutdown errors
still propagate, and server-thread errors, response count and connection-close
assertions remain intact. Production HTTP behavior is unchanged.

A deterministic check injects the closed-peer condition and still requires one
complete rejection response with `Connection: close`. All 23 HTTP-structure cases
pass, and the full maintained gate passes 917 Python cases with strict typing on
107 files, lint/formatting and script/console checks.

### Item 11 follow-up: retained supplement and staging moves

Supplement recovery and atomic-publication operations move unchanged to
`dev12_completion_supplement_state.py`; the supplement entry point and original
private bindings remain available. Its facade shrinks from 1,744 to 1,226 lines.
Historical Docker staging moves unchanged to `tools/gateway/docker/staging.py`,
with the original prepare import/CLI retained. The prepare facade shrinks from
2,536 to 2,302 lines and its file allowance is tightened accordingly.

AST comparisons preserve all three bodies, defaults, copy/receipt behavior and
ownership/exception scopes. A guarded 23-case replay against `2f5db41` matches
entry rejections and dependency traces. The isolated direct-script `--help` path
also passes. No actual staging, metadata acquisition, package installation,
build, target execution or profile restart ran.

Cold-import checks now cover 31 runtime and 15 tooling domains, including all
nine real handler source registrations. Full `tools.check` passes 917 Python
cases, strict typing on 107 files, lint/formatting and script/console checks.
Library typing debt remains 1,631; 49 size allowances remain after explicit
unchanged-body transfers and removal/reduction of resolved file ceilings. Phase
cleanup of the moved functions follows separately.

### Item 11 follow-up: operator, supplement and staging phases

Operator reporting separates grouping, period, revision, filter, export,
visibility and browser-attestation checks while the original client context and
census boundaries stay on the caller. Supplement recovery separates credential
rotation, client-selector construction and retention assertions; its clock and
historical-access restoration remain in the same try/finally. Atomic-publication
checks name the stalled commit observation without changing lock, callback,
thread-join or transaction restoration order. Staging separates custody validation
before the existing copy/receipt/error scope.

All functions in these three modules are below 200 lines. Expanding the 12 new
phases reconstructs all four original entry-point ASTs exactly, including closure
bodies and returned callback/state references. The guarded 23-case helper replay
continues to match the original implementation; actual target and successful
staging qualification remain separate.

Full `tools.check` passes 917 Python cases, strict typing on 107 files,
lint/formatting, script/console checks and both ratchets. Library typing debt
remains 1,631; four resolved function allowances are removed, leaving 45. No
listener, provider request, dependency acquisition, staging run or daemon action
was performed.

### Item 11 follow-up: preflight validation code move

Preflight validation and continuation binding move unchanged into
`dev12_completion_preflight_validation.py`. The selected-label builder and its
immutable required-ID set move with them, and the facade reexports the same
default object. Public import paths, signatures/defaults and CLI behavior remain
available. The facade shrinks from 1,460 to 605 lines; the new domain is 889 lines,
leaving room for named phases without introducing an oversized file.

AST comparisons preserve the three moved functions and constant initializer.
All 20 preflight/continuation/runtime/identity cases and the cold-import check
pass; the latter now covers 31 runtime and 16 tooling domains. The public
required-ID default is still the same object exported by the facade.

Full `tools.check` passes 917 Python cases, strict typing on 107 files,
lint/formatting and script/console checks. Library typing debt remains 1,631.
There are still 45 size allowances: two existing function caps transfer with
six total physical lines of facade-import/qualification overhead. Their phase
cleanup follows separately; no preflight acceptance condition was changed.

### Item 11 follow-up: preflight validation phases

Validation now separates case collection, catalogue/handler identity, custody/
resource bounds, continuation inventory, unchanged database reads and retained
campaign checks. Existing mutable coverage/error collections remain shared;
quota accumulators and continuation state have explicit inputs/returns. Original
continues, rejection ordering and outer exception/read scopes stay intact.

The public validator is 193 lines and continuation binding is 131; all functions
in the domain are below 200. Expanding the six phases reconstructs both original
entry-point ASTs exactly. A replay against `9d7dca4` compares 527 synthetic inputs,
including 38 accepted variants, and matches output, error ordering and exception
identity/message. All 20 maintained preflight/continuation/runtime/identity cases
also pass. These checks do not qualify an actual source or target release.

Full `tools.check` passes 917 Python cases, strict typing on 107 files,
lint/formatting and maintained script/console checks. Typing debt remains 1,631;
the two transferred function allowances are removed, leaving 43. Remaining W6
work is other retained runners/audits, long individual tests and deployment
exercises. No provider, listener, dependency, build or daemon action ran.

### Item 11 follow-up: integrated runner lifecycle phases

DEV-08, DEV-11 cache, DEV-12 integrated and retained controls runners now separate
prepared execution, campaign setup, installed-client exercises and verification.
Complete initialization/error/cleanup scopes move together: already-created
servers, adapters, coordinators, stores and receiver processes retain their
original failure cleanup order. Borrowed resources remain in their existing
caller scopes. Nine phase extractions expand to the original four function ASTs;
an additional liveness audit rejects moving assignments observed by an enclosing
error/finally scope. All functions in these four modules are below 200 lines.

This check also found an extraction-order bug: helper definitions appended below
a script entry block were unavailable during direct CLI execution. Definitions
now precede entry blocks, including the previously extracted completion argument
parser. Two maintained regressions scan tool entry ordering and execute the
completion runner's isolated, parse-only `--help` path. All seven tooling-boundary
cases pass. The DEV-08 explicit no-send preflight passes with zero network/model
requests; no execution path or target profile was launched.

Full `tools.check` passes 919 Python cases, strict typing on 107 files,
lint/formatting and script/console checks. Typing debt remains 1,631. Four resolved
runner allowances are removed, leaving 39. Other retained tools, long individual
tests and deployment exercises remain under W6.

### Item 11 follow-up: browser and installed-proof phases

Eight retained browser runners now have named workspace, playback, filtering,
provider setup/approval, report and source-onboarding verification phases. Their
existing server/browser context owners, assertions, screenshots, export checks,
request capture and final cleanup stay in place. The installed-client proof
separates attributed runs and outcome revisions, returning the original actor
callback and values needed by later checks. All functions in these nine modules
are below 200 lines.

Fourteen phase extractions expand to the original nine entry-point ASTs, including
explicitly returned callback bindings and shared mutable capture collections.
The enclosing error/cleanup liveness audit passes, and tool entry declarations
remain ahead of direct CLI execution. Browser and installed HTTP journeys were
not launched here; their real target qualification remains pending.

Full `tools.check` passes 919 Python cases, strict typing on 107 files,
lint/formatting, script/console checks and both ratchets. Typing debt remains
1,631; nine resolved function allowances are removed, leaving 30. Remaining W6
work is retained correction/audit/auth tools, long tests and deployment exercises.


### Item 11 follow-up: retained correction and audit phases

The three correction release scripts retain their command modes and client
contexts, with named seeding phases. Completion/CT02B audits now separate source
custody, installed artifacts, native usage and release-journal lineage. The
retained authorization HTTP runner keeps its complete request/cleanup scope
together; zero-send checks separate rollback observation, revision selection
and immutable-source reporting. No historical runner is removed or executed
against a target.

Twelve copied-body extractions expand back to the original executable AST,
including exception and cleanup scopes. Every function under `tools/` is now at
most 200 lines. Full `tools.check` passes 919 Python cases, strict typing on 107
files, lint/formatting and script/console checks. Library typing debt remains
1,631; eight resolved function allowances are removed, leaving 22. The long
individual test journeys and two deployment exercises remain under W6. Real
listener/browser/profile qualification remains pending.


### Item 11 follow-up: W6 test journeys and deployment exercises

Ten oversized test/fixture journeys now have 36 named phases: signed-plan
mutations, queued authority/no-store behavior, continuation receipts/counters,
guarded-tool evidence, provider configuration and personal campaigns, accounting
eligibility/lineage/snapshots/exports, and credential owner/nonowner boundaries.
Client parity command modes keep their terminal returns inside the same client
context. Public test names, decorators and all assertions remain available.
The six accounting HTTP test files remain below 400 lines.

DEV-09/DEV-10 deployment exercises separate provisioning, installed actors, build
custody and worker verification. DEV-10 retains its complete ownership and
cleanup scope; initial resource flags remain explicit inputs. DEV-07 separates
independent receiver correlation. These six phase extractions preserve the
original executable statements and error scopes. No profile is started, built
or restarted. Fifteen injected success/failure replays match DEV-10 command and
cleanup order exactly, using substitutes without executing external commands.

Expansion proofs cover all 42 extracted phases. All 144 generated native-client
fixtures, including evaluated expected transport calls, are byte-identical
(SHA-256 `1873f92188625ab6a8986137afb70603681053aa35638f7bae1bd1d7b030a979`).
Focused crypto, continuation and provider-plan suites pass eight cases. Full
`tools.check` passes 919 Python cases, strict typing on 107 files, lint/formatting
and script/console checks. Library typing debt remains 1,631; ten resolved test
allowances are removed, leaving 12. Every tooling/test function and the three
affected deployment exercises are at most 200 lines. W6 source decomposition is
implemented; no evidence runner has been deleted or archived. Final installed
wheel verification and checklist reconciliation follow. Real listener/browser/
frozen-profile qualification remains item 1.


### Item 11 follow-up: final source and package validation

All W1–W7 source work is implemented through `f6746d4`. Server files over 1,000
lines fall from three to zero, functions over 150 lines from 16 to zero, and
functions over 100 lines from 38 to nine (all capped). The largest runtime class
is 599 lines; the largest tooling function is 199 and test function 189. The
remaining 12 size allowances are nine server functions, `local_connectors.py`
(847 lines), the Python client's attribution operation (106 lines), and Docker
input preparation (2,302 lines). Their ceilings cannot grow; resolved entries
must be removed. No requested source refactoring remains in this work order.

Full `tools.check` passes 919 Python cases, strict typing on 107 files, the
whole-library typing ratchet (1,631 existing diagnostics), size budgets, lint/
formatting, seven console scripts and maintained JavaScript/contract checks.
Final Python executable-line coverage: 87.46% (18,930/21,645 executable lines;
Python server/client scope only).

Both distributions were rebuilt with the cached pinned `uv_build==0.13.1`,
without dependency acquisition. Complete wheel manifests and bytes match all
161 source namespace files, including every new domain. Extracted wheels pass
472 installed-package tests with network access blocked; imported runtime
modules resolve to the extracted wheels. Server wheel SHA-256:
`4ee9cb493745b4d4a6af6e4d4e774fe29d6602cd1c5b33e9a3ceaa505017045e`.
Python client wheel SHA-256:
`7eb2153a2daa8177d4464130468fcb7cba33a888f2eb6d4d05ab7ce11c7fc772`.
Ignored proof scripts, expansion/differential records, logs, wheels and the
final validation record are under `.artifacts/code-review/god-class/`.

Against `33f7a45`, schema/migration files, adopted contract fixtures and frozen
requirements/wheel inventory bytes remain unchanged. Source proofs and local
checks do not qualify a deployed image or service. Real HTTP/TLS listeners,
browser journeys, frozen worker/image builds and deployment exercises remain
pending under item 1; native target checks remain stated in item 8. Item 9 stays
deferred at the owner's request. The old daemon/profile has not been updated
or restarted, and no provider request has been made.


### CI follow-up: guarded HTTP setup, TypeScript consumers and native exports

GitHub Actions exposed three test-harness defects after `26bbeb8`. Loopback
Python HTTP fixtures bind successfully in CI, then fail when `HTTPServer` names
the bound host using reverse DNS. The shared guard now returns the literal local
name from `getfqdn` in loopback mode without resolving it. Direct reverse DNS,
external names and offline naming remain blocked; the same guard applies to
isolated Python children and the installed JavaScript HTTP fixture. New tests
exercise the real `server_bind` implementation for standard, threaded and bounded
HTTP servers with only the OS bind/address calls substituted, plus allowed and
rejected naming operations. These are listener-free regressions.

The packed TypeScript consumer no longer redeclares `accountingError` and
`accountingStatus`. It still checks both `httpStatus` and `http_status` against
`number | null`. The TypeScript 5.9.3 compiler passes the actual package consumers
in NodeNext and CommonJS modes; package export/declaration checks also pass.

Native report download tests now select the current `Export attempt page ·
CSV/JSON` buttons. They assert visibility before waiting for a download and
check all three seeded attempt IDs, JSON pagination and CSV row count. The test
names describe page-scoped exports. Application export behavior is unchanged.
Browser-suite type checking and discovery of both corrected tests in all three
projects pass. The seeded JSON export also matches the new pagination/attempt
assertions through the real fixture and handler without a listener.

Verification: full `tools.check` passes 921 Python cases, strict typing on 107
files, lint/formatting, unchanged size/type debt ratchets and the maintained
script/console checks. The 21 inventory/network-guard tests and installed
JavaScript offline runtime checks pass separately. Runtime schemas, frozen
inputs and the daemon/profile are unchanged. This executor denies real loopback
binds with `PermissionError: [Errno 1]`; HTTP/native-fetch/browser execution and
confirmation of the replacement GitHub Actions run remain pending. Item 1 stays
open. TypeScript compilation is now verified locally; Rust/.NET target checks
remain pending under item 8, and item 9 remains deferred.


### CI follow-up: JavaScript streamed-limit error assertion

The native JavaScript HTTP job reached its streamed oversized-response check
after the loopback naming fix. Its assertion still expected the byte-limit error
at `error.cause.message`; total-deadline transport handling wraps that failure
in an HTTP exchange error to preserve the observed status. The actual chain is
`TRANSPORT_OUTCOME_UNKNOWN` → `HTTP exchange failed` →
`response exceeds its byte limit`. The HTTP fixture now checks both levels.
No runtime client behavior or public error/retry/status fields change.

An installed-client offline regression exercises a native `Response` and
`ReadableStream`, verifies that exact error chain and HTTP 200/query-first
metadata, and checks one cancellation, one fetch, lock release and stopping at
the first chunk over the 1 MiB cap. The fresh packed JavaScript suite passes all
144 contract cases and 53 safety cases, plus its other installed-consumer checks.
Full `tools.check` passes 921 Python cases, strict typing on 107 files, existing
size/type debt ratchets, lint/formatting and script/console checks. Actual native
fetch over loopback remains unverified here because the executor denies listener
binds; the replacement GitHub Actions HTTP job is still required.


### Further review debt: typing, size allowances and report aggregation

The owner authorized all three remaining cleanup workstreams after completion
of W1–W7. These add finish lines beyond the original work-order allowances.
Contracts, exact decimal/currency/unknown semantics, visibility, cutoff and
cohort attribution remain required behavior. No daemon/profile update, provider
request or dependency acquisition is part of this pass.

| Workstream | Status | Finish line / current evidence |
| --- | --- | --- |
| R1 — complete library typing | In progress | Bring all server/Python-client modules into strict typing; remove the remaining diagnostic budget. Baseline: 1,631 diagnostics in 44 files. Lifecycle/connection/journal, gateway and validation boundaries now leave 1,303 diagnostics; strict coverage includes the entire gateway and successor contract/plan/descriptor modules. |
| R2 — remove size allowances | In progress | Eight of the 12 initial exceptions are resolved; four function allowances remain. Connector and historical Docker-input file splits retain public imports and every historical runner. |
| R3 — scale report aggregation | In progress | Avoid loading every full attempt record into Python for totals/cohorts. Preserve bounded read-only snapshot ownership, exact decimal arithmetic, visibility, revision cutoffs, complete cohort costs and existing response/export pagination. |

The first R1 batch types coroutine/future ownership and bounded connection
lifecycle, plus diagnostic journal records/cache fingerprints. Framework
forwarding arguments remain the standard library's opaque boundary; concrete
streams, threads, callbacks, futures and records are typed. Runtime cleanup and
locking stay in their existing scopes. Full `tools.check` passes 921 Python
cases, strict typing on 110 files, lint/formatting, size budgets and maintained
script/console checks. Whole-library diagnostics fall from 1,631 to 1,599; the
per-file budgets are tightened to the observed counts.


#### R1: owned gateway and successor boundaries

Every gateway module and the successor contract, signer/eligibility and
descriptor modules now pass strict mypy. Send-authority and closable async-body
protocols describe transport capabilities; the local authority has a checked
conformance proof. Callback/deadline/socket/TLS/reader ownership is typed without
changing first-write, revocation, cleanup or error routing. The relay future is
correctly typed as its returned relay record rather than an HTTPX response. The
successor canonical JSON helper's annotation now matches its existing string
return. JSON shape validation and decimal calculations remain unchanged.

After stripping type annotations and identity casts, 118 existing functions
have the same executable AST. Fresh-interpreter import coverage now includes
all gateway modules and successor contract/plan/descriptor modules. Focused
guard, owned sender and compressed-response regressions pass. Full `tools.check`
passes 921 Python cases, strict typing on 123 files, lint/formatting, unchanged
size limits and script/console checks. Whole-library diagnostics fall from 1,599 to 1,319 in 30 files; observed
per-file budgets are tightened. All 12 size exceptions and the report
aggregation follow-up remain active. No live HTTP/provider/profile work runs.


#### R2: validation steps and six resolved function allowances

Python attribution response validation, outcome subject validation, relay
content/credential validation, text/retrieval transport-header checks and
rotation CLI arguments now have named helpers. Six copied-body expansion proofs
preserve executable statements, ordering, admission/authority gates, transactions
and cleanup/error scopes. The relay timeout remains an explicit returned value
so request construction cannot lose it before the later wait-budget assignment.
All new helpers pass the applicable strict typing scope.

Six resolved function allowances are removed, leaving six: local connector and
historical Docker-input files, the connector HTTP reader, two operator route
handlers and operator server composition. Typing outcome identifiers and the
run getter also reduces whole-library diagnostics from 1,319 to 1,305; observed
per-file budgets are tightened. Full `tools.check` passes 921 Python cases, strict
typing on 123 files, lint/formatting, source budgets and script/console checks.
Remaining R1/R2/R3 work continues; no target execution or retained-runner deletion
is performed.


#### R2: connector, campaign-reporting and retained-input domain moves

Thirty-three function/method bodies move unchanged into connector HTTP/policy,
connector inventory, campaign reporting and Docker-input fetch/resolution/
collection modules. Public facade bindings, patched globals, ownership scopes
and the collector's captured fetcher default remain available. A runtime
binding/default regression and fresh-import checks cover the new modules.
The collection domain binds its facade after definitions so either import order
works; no data acquisition, backend, installation or container is invoked.

The connector facade falls below 800 lines (about 600), campaign reporting leaves
room for strict annotations within its class limit, and Docker preparation falls
from 2,302 to about 1,225 lines. Both file allowances resolve. Four function
allowances remain; the connector reader's transferred ceiling includes four
physical lines of facade-qualification formatting, to be removed in cleanup.
All tooling functions remain at most 200 lines. Existing diagnostic debt
transfers without aggregate growth, from 1,305 to 1,303; strict cleanup of these
domains follows separately.

Full `tools.check` passes 922 Python cases, strict typing on 123 files,
lint/formatting, transferred size/type budgets and maintained script/console
checks. Copied-body AST proofs cover all 33 moves. No historical runner, frozen
input, contract fixture or deployed state is removed or modified.
