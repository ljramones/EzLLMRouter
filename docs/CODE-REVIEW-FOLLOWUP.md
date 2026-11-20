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
| 4.6 / 4.10 / 4.3.5: Login and operator transport policy | Bound failed and pending named logins by canonical username across peers, clear failures after success, and cap concurrent work and retained identities. Expected credential rejection has no ERROR stack trace; unexpected faults return a sanitized 503. TCP is loopback-only; an explicit HTTPS origin over a private Unix socket enables Secure session and clearing cookies. Owned socket directories and mode `0600` are checked before listening. Product-specific integration forwarding remains outside this security batch. |
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

The .NET package test also now uses a fresh package cache for each restore.
Previously, an existing package with the same version could hide SDK changes
from the tests despite a successful local pack.

## Validation and outstanding gates

The expanded offline Python/component runner passes: 795 unittest cases plus
seven console component scripts, Ruff and strict mypy across 38 modules.
Installed JavaScript runtime checks and packaged TypeScript consumer checks
pass. JavaScript, Go, Java and .NET pass all 125 shared cases against their built clients.

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

## Remaining review work

The review is not fully resolved. Continue in this order:

1. **Python client consistency and API polish:** unify the remaining request
   pipelines, header/error handling, exception root and schema-validator policies.
   Add public typing and `py.typed`, address the Python naming convention, tighten
   base-URL validation, review credential exposure and remove unused resources
   (5.4 / report-1 6.6–6.7).
2. **Remaining runtime coupling, naming and packaging:** remove fixed consumer,
   purpose, identity/class and integration-forwarding assumptions; replace
   milestone names and hidden aliases; derive release metadata from one source.
   Consolidate remaining descriptor, demo and gateway duplication, narrow expected
   parser-error handling, and separate fixture-only successor code from the
   production wheel (4.2.7 / 4.3.5 / 5.1 / 5.3).
3. **Deployment hygiene:** consolidate command runners and filesystem helpers,
   resolve the `profile` module name collision, finish timeout/error/connection
   cleanup, remove dated run IDs and make Docker context selection explicit.
   Review restart's automatic source preparation, correct stale client-version
   evidence labels and remove unnecessary image layers/test-source staging
   (4.3.5 / 5.5).
4. **Broader typing:** extend strict checks into remaining services and clients.
   The current 38-module scope is not full coverage (4.3.2).
5. **Test/tooling hygiene:** separate evidence drivers from tests, simplify import
   strategies and compatibility shims, remove duplicated harnesses and improve
   naming. Finish port-allocation race, sleep, missing-tool and assertion cleanup;
   standardize JavaScript test entry points and reduce production dependence on
   test fixtures (5.6).
6. **Validation and the testing roadmap:** rerun browsers and actual HTTP/TLS
   fixtures after the fixes, confirm credential initialization on the corrected
   ARM64 CI runner, qualify Rust and the isolated frozen worker in their target
   environments, and measure subsystem coverage. Complete process-termination
   recovery, backup/restore, supported-platform, generated-input and sustained
   performance testing. Existing synthetic database benchmarks cover only part
   of that roadmap; they do not establish production capacity.

Broader GitHub Actions hardening is deferred to a separate activity at the owner's
request. This includes reviewing and pinning the remaining CI bootstrap artifacts
and action revisions (4.3.3).

Other lower-severity findings and carried-forward structural items remain open
unless explicitly listed as fixed above. Added coverage is not a substitute for
deployment, security or performance qualification.
