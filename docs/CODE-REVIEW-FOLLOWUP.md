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

The review is not fully resolved. Continue in this order:

1. **Target qualification:** build and exercise the changed service and worker
   images with the reviewed inputs; rerun browser and actual HTTP/TLS fixtures,
   credential initialization, Rust and the frozen worker in their target environments.
2. **Blocking work:** move large reports, sender database work and password
   verification off shared locks/event loops (report 3: 4.1.3, 4.2.2, 4.3.3).
3. **Logging:** treat routine wire rejections and idle closes appropriately and
   derive route labels from the route table (4.3.4–4.3.5).
4. **Dependency and CI coverage:** declare server gateway extras, exercise the
   shipped lock in CI and harden remaining bootstrap/action/toolchain inputs
   (4.4.1–4.4.3). Frozen checks now have runners; they still need target execution.
5. **Clients:** distinguish local JS serialization failures from uncertain sends,
   add a JS total deadline, and address the remaining parity/error-mapping details
   (4.5.1–4.5.3).
6. **Typing and the testing roadmap:** extend the current 51-file strict scope
   and measure subsystem coverage. Complete process-termination recovery,
   backup/restore, platform, generated-input and sustained performance tests.
   Existing synthetic benchmarks do not establish production capacity.

Broader GitHub Actions hardening is deferred to a separate activity at the owner's
request. This includes reviewing and pinning the remaining CI bootstrap artifacts
and action revisions (4.3.3).

Other lower-severity findings and carried-forward structural items remain open
unless explicitly listed as fixed above. Added coverage is not a substitute for
deployment, security or performance qualification.
