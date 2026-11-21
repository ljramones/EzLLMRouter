# Development and verification

Run commands from the repository root: the directory containing `pyproject.toml`,
`uv.lock` and `.nvmrc`.

```sh
nvm use
uv sync --locked --all-groups --python 3.12.15
uv run --locked python -m tools.check
uv run --locked python -m tools.check --http-only
```

The first check runs Ruff, formatting, mypy, JavaScript syntax checks and the
maintained offline regressions. Offline tests reject network connections and
listener binds; local IPC pairs support framing checks. The second check runs
HTTP and TLS fixtures against localhost and requires permission to bind sockets.
These commands use temporary stores and controlled fixtures, with no model calls.

Ruff checks `E9`, all Pyflakes (`F`) and all Bugbear (`B`) rules and `RUF100` across `server/`,
`clients/`, `deploy/`, `worker/`, `tools/` and `tests/`. Formatting is enforced
across those same trees. Local runtime state under
`deploy/local/.state/` is explicitly excluded, including when passed directly to
Ruff. Existing dependency/build exclusions also apply. Dead lint suppressions are rejected; the unused `E402` suppressions were removed.
No new blanket rule ignores hide adopted findings.

Strict mypy checks every server and Python-client module, plus the selected
verification/deployment tools in `TYPED_PATHS` in `tools/check.py`. The library
directories are checked as a whole, including new modules. The blocking
`tools.type_audit` also inventories both libraries with zero remaining error
budgets in `tools/type_audit_budget.json`; new or increased debt fails. Reports
under `.artifacts/type-audit/` retain diagnostics and counts. Test and deployment
modules outside the selected strict scope still receive Ruff and formatting.

Apply the maintained formatter before committing Python changes:

```sh
uv run --locked ruff format server clients deploy worker tools tests
```

Disposable-project regressions invoke the real quality commands and verify that
unused imports, blind exception assertions, unformatted tests and incorrect uses
of imported types block the runner. They also verify runtime-state exclusion.

`tools.check` inventories Git-tracked and non-ignored `test_*.py` files under
`tests/` and `deploy/local/` before running. Every file must have an offline,
loopback or standalone-script registration, or an explicit reason in
`EXCLUDED_TESTS`. Missing classifications fail the check. Class-level
registrations must cover every local test class, including inherited classes; method-only selectors cannot
stand in for a whole class. Empty and entirely skipped suites fail. Module,
standalone-script and JavaScript failures are collected before the runner exits.
`tests/javascript_inventory.json` assigns every test JS/TS source to console,
installed-client, offline, target or helper execution, with reasons for target
and helper files. An added unclassified file fails the audit.
The current exclusions need the frozen gateway runtime or retained run evidence; they are not passing
development tests. In particular, the AnyIO counterexamples require the frozen
4.15.1 wheels, while the development lock uses 4.16.0.

Loopback modules allow localhost and local IPC only. Per-module interpreters
isolate loaded fixtures and environment changes. Ordinary tests import the
installed development packages and package-qualified fixtures. Standalone
source-copy checks retain their explicit source/dependency roots. The accidental
network guard covers Python socket/DNS/UDP operations and wraps
Python child commands before their target code, preserving `-I`/`-S`. Children
and grandchildren inherit the guard even with a replaced environment. Node
children receive a preload guarding sockets, DNS, UDP and native fetch. Native
subprocesses are limited to audited local Git/OpenSSL operations, offline npm
with scripts disabled, and the existing shell syntax/exit-code fixtures. New
commands require an explicit runner decision. These language hooks prevent
accidental test network use; they are not an OS sandbox for hostile code or
native extensions. Target containers and native-language harnesses retain their
own fixture/isolation checks.

In loopback mode, HTTP server naming uses the literal local address or
`localhost`, avoiding the standard library's reverse-DNS lookup during binding.
External names, direct reverse-DNS calls and all offline naming remain blocked.

Coverage and test health use the pinned Python 3.12 and Node runtimes. Console
coverage also needs the already-locked TypeScript parser:

```sh
npm --prefix tests/playwright ci --ignore-scripts --no-audit --no-fund
uv run --locked python -m tools.check --coverage --coverage-gate --health-budget 30
```

Each run creates a fresh directory under `.artifacts/coverage/`. `summary.json`
records Python source hashes, executable/missing lines, and both exits of each
conditional bytecode instruction, including loops and worker threads. Exception
dispatch edges and native code are outside this metric. `subsystems.json` and
`index.html` show subsystem totals and the explicit critical-exit gap list.
`tools/coverage_budget.json` caps missing lines/exits per source file; new files
have zero allowance. Critical selectors in `coverage_policy.json` must exist and
have no uncovered conditional exits. Baseline increases require explicit review;
`tools.coverage_reports --write-baseline` is a maintenance operation, never a CI
step. Add `--loopback` for a separate HTTP-inclusive measurement.

Installed SDK coverage uses native V8 counters. Console VM coverage uses statement
and function counters inserted by the locked TypeScript 5.9.3 parser: Node
24.22.1 precise coverage mis-resolves an early `typeof` after a later lexical
binding. Instrumentation regressions preserve that binding, strict directives,
arrow `this`, loops and exceptions. The JS summary labels the two methods and
unmeasured files explicitly; it does not claim an exhaustive JS branch percentage.
`tools/javascript_coverage_budget.json` ratchets missing console statements/functions
and installed-SDK functions. V8 block ranges remain diagnostic because their
denominator changes when outer functions execute. Installed source aliases are
recorded before temporary packages are removed and must match canonical hashes.

Every normal check also writes sanitized per-test outcomes and durations under
`.artifacts/test-health/`, including failed subtests and skips. `--health-dir`
selects a collection directory, `--health-budget 30` caps Python module durations,
and `--repeat 5` repeats module suites while retaining all failures. The nightly
workflow repeats offline and loopback modules five times and reports inconsistent
outcomes. A passing retry never erases the original failure. Telemetry contains
test identifiers and timings, without exception messages, locals or subtest values.

`python -m tools.container_tests` checks every Docker unittest/discovery/script
selector against the sources staged by preparation, including instruction-local
bind mounts. It cannot establish that images build or run; those checks still
require the approved frozen input bundle and a disposable Docker target.

The independent operator policy table is
`tests/fixtures/operator_authorization.json`. Adding a route without a policy row
fails the offline gate. Matrix variants exercise the real handlers directly,
real HTTP parsing over socket pairs, and localhost listeners in the HTTP tier.
Expected statuses come from the checked-in table and documented roles, never
from the implementation's route-role metadata. Empty mutation bodies cannot
initiate sends; cross-user cases additionally assert unchanged authority state.

Generated parser/property tests use deterministic standard-library generators
without another package install. The normal gate fixes the seed and keeps small
example budgets; scheduled tests record the run number as their seed and use
512 examples. Replay a reported seed/index with:

```sh
EZLLMROUTER_TEST_SEED=0xdeadbeef EZLLMROUTER_TEST_EXAMPLES=512 uv run --locked python -m tools.check --test-module tests.unit.test_generated_parsers.GeneratedParserTests
```

`tests.unit.test_generated_http_framing.AuthenticatedFramingTests` separately
targets authenticated operator and wire routes over real socket pairs. Every
generated framing case must enter the body parser, reject without dispatch,
close the connection and leave a following request unexecuted. Positive controls
must dispatch once with the exact declared JSON body. The hazard alphabet includes
duplicate/conflicting/signed lengths, whitespace, folded/malformed field names,
NUL/bare CR, non-ASCII digits, empty/mixed-case transfer encodings and size limits.
A separate EOF case rejects valid JSON shorter than its declared body. Application
write/send entry points are controlled probes; no users or provider attempts are
created. Early 401/404 cases remain distinct and assert that parsers are bypassed.

Failures print the seed and index, with synthetic JSON bytes encoded as base64.
The JSON comparison distinguishes free response text from the server's stricter
request-text policy. Accounting expectations use integer nanodollars rather
than the implementation's Decimal accumulator. The campaign model preserves
late recorded charges, checks exact incurred/held/available exposure, and refuses
new reservations that exceed current authority. These generators do not yet
provide Hypothesis-style shrinking or cover all native decoder implementations.

`tools.check --lock-audit` wraps the shared store/authority gates, registry probe
and token locks, credential/vault gates, availability lock and password hash
semaphore in each module interpreter, including stores opened for maintenance.
It rejects socket connect/read/write, TLS data I/O and handshake, `time.sleep`,
password hashing and hash-slot waits while a shared gate is held. SQLite
connections/cursors and store entry points additionally reject synchronous
database work on a running asyncio loop, even without a held gate. Ordinary
synchronous SQLite transactions remain supported; this is not a general SQLite
busy-wait detector. Explicit call-site exceptions preserve initial account hashing
before the service binds, the sender's atomic nonblocking first write, and
asyncio's nonblocking event-loop wake-up socket. Routine login and password
changes have no exception. Every violation is retained in the active module's
process-wide audit scope before raising. The module/script fails even if the
exception was caught or occurred on a worker/loop thread; module health artifacts
retain operation/lock labels and thread IDs without SQL text or arguments. Nested
audit probes in the instrument's own tests use isolated scopes. This is test
instrumentation, not an OS sandbox or a detector for arbitrary CPU work/file I/O,
every synchronization wait, or nested isolated source-copy children.

The forced-order race cases include sender revocation/cancellation,
credential rotation/release, purge versus delayed writers, session revocation
during lookups, and both orders of campaign close/admission. Run a short local
stress pass, or omit the small round count and offline restriction for the
nightly 200-round HTTP/TLS pass:

```sh
uv run --locked python -m tools.concurrency_stress --rounds 3 --offline-only
```

The runner shuffles suite order with a recorded seed; the individual races use
events/barriers, rather than sleeps to hope for an ordering. A failure or timeout
stops the run and remains failed in `summary.json`.

`test_process_durability` kills real child processes after a handshake at named
fixture-only checkpoints. It covers before-BEGIN, before-COMMIT and after-COMMIT
for work creation, intent, guard receipt and usage, plus encrypted-file
publication and provider-key rotation. These are process-crash tests, not a
power-loss or physical-disk qualification. Storage tests exercise real SQLite
page-limit/busy failures and an injected I/O failure after a work claim.
`test_coherent_restore` uses the real offline database-backup command, copies the
documented private keyring/vault set, restores credentials in all three scopes
and compares retained accounting. All data and secrets are synthetic and
temporary; the tests never open a running profile or contact a provider.

`tools.security_sast` runs the locked Ruff 0.14.0 `S` rules on every server and
Python-client module, ignoring inline suppression directives. Its five SQL-file
exceptions record the 14 reviewed findings, exact whole-file hashes and reasons
for the allowlisted identifiers/constant clauses. Changed source, new findings,
or stale exceptions fail. This separate security scope does not silently ignore
findings in deployment, evidence or test tools; those remain outside this gate.

`tools.security_dependencies` inventories exact Python/npm candidates from the
development, shipped service/worker, browser/client and build-backend locks.
The PR run validates these inputs and writes `inventory.json` plus a CycloneDX
candidate SBOM without reaching the network. It rejects the forbidden LiteLLM
release component after normalizing abbreviated/zero-padded spellings and local,
pre/post suffixes. Dockerfile FROM/ARG defaults and compose/workflow image fields
reject mutable LiteLLM references, the forbidden release family and missing
digests. Quoted keys and inline container mappings are supported; unresolved
image anchors and block scalars fail. Arbitrary external image-variable values
and digest provenance are not qualified by this source check. CI runs the
standard-library preflight before installing project dependencies. The SBOM describes lock candidates,
not installed container contents or native-language transitive dependencies.

The nightly `--audit` mode sends only package names/versions to the public OSV
API, records the complete response snapshot and its inventory identity, and
fails on high, critical or unrated active advisories. Low/moderate findings stay
visible. Withdrawn entries must have a valid withdrawal time. Metadata outages,
incomplete batches and identity mismatches fail; they never establish a clean
audit. No scan automatically upgrades dependencies or changes frozen inputs.
`--snapshot PATH` rechecks a matching, complete snapshot offline; snapshots older
than seven days fail. Network advisory qualification remains separate from the
offline scanner regressions, which use explicitly synthetic advisory responses.
That job uses the runner's standard library without installing the project's
development or gateway dependencies.

JavaScript runtime checks install a fresh local npm package and exercise the
installed consumer. The HTTP variant uses actual Node fetch against a disposable
localhost fixture:

```sh
npm --prefix clients/js test
npm --prefix clients/js run test:http
npm --prefix clients/js run test:types
```

The JavaScript checks run the 144 shared contract cases against Python's expected
errors, handles and exact outgoing requests. Additional cases cover streamed byte
limits, cleanup, strict decoding, new configuration profiles and large embeddings.
The HTTP fixture also sends an oversized chunked body to exercise native fetch
cancellation. Installed-client checks also exercise total fetch/body deadlines,
reader cleanup and local serialization failures. Real listener-based HTTP checks
remain a separate target check. See the
[review follow-up](CODE-REVIEW-FOLLOWUP.md) for remaining work.

Go and Java clients are independent packages with no external runtime dependencies.
Use the Go version in `clients/go/.go-version` and JDK 17+:

```sh
bash tests/client_languages/check.sh
bash tests/client_languages/check.sh --http
```

The first command runs Go formatting, vet and race checks, then compiles a Java
17 JAR with all compiler warnings treated as errors and tests that packaged JAR.
Both languages run the shared contract cases in `tests/client_languages/cases.json`.
The Python suite checks those cases against the existing Python client and verifies
that embedded schemas match their adopted sources. The second command uses a
disposable localhost fixture to test the native transports. It requires loopback
permission and sends no model requests. Native checks run in a separate CI job.

Additional client checks need TypeScript 5.9.3, a .NET 10 SDK and the Rust
toolchain declared in `clients/rust/rust-toolchain.toml`:

```sh
bash tests/client_languages/check_typescript.sh
bash clients/dotnet/build.sh test
bash tests/client_languages/check_rust.sh
```

TypeScript consumer fixtures compile against the packed npm package in CommonJS
and NodeNext modes. `--package-only` checks exports and declaration syntax but
omits the compiler type check. .NET tests consume the locally packed NuGet
package without external package sources. Rust runs the shared contract cases,
Clippy correctness checks and Cargo package verification. Rust dependency
acquisition is separate from the service's frozen gateway inputs.

After building the native packages, run their explicit HTTP fixtures with
`python3 -I -S tests/client_languages/http_fixture.py --client dotnet` or
`--client rust`. CI has separate jobs for .NET, Rust and TypeScript. A missing
SDK, incompatible compiler or denied localhost bind must be reported as an
unverified check rather than a passing result.

Credential initialization has a separate Linux capability check:

```sh
python3 -I -S tests/security/check_credential_init.py
```

It uses the real Compose configuration in a uniquely named temporary project.
Two separate initializer containers create and replace credentials on the same
named volume, retaining Compose's `CAP_CHOWN`, root identity, read-only root
filesystem, no-new-privileges and disabled network. A third container uses the
service's UID and read-only credential mount: it reads the replacement and fails
both writing and changing its mode. Initializer checks retain ownership and mode
`0400`. Cleanup removes only that isolated project's volumes. No deployment is
started or restarted.

This requires Docker with ARM64 execution support: the digest-pinned local-profile
base is ARM64, and the fixture explicitly requests `linux/arm64`. The
`credential-init` CI job uses `ubuntu-24.04-arm`; other jobs retain their own
platforms. Setting `--platform` alone does not enable emulation on AMD64. A
source/configuration unit check is not a passing Docker capability check.

## Browser journeys

The Playwright suite exercises the real operator HTTP application, browser assets
and SQLite store in Chromium, Firefox and WebKit. Each test starts a disposable
service with synthetic accounts, catalogue data, execution metadata and external
accounting observations. Local server discovery uses a fixed loopback HTTP
metadata fixture. Cloud model discovery uses a deterministic adapter injected at
the external provider boundary, with real encrypted credential storage and
policy updates. The harness rejects external connections and model execution.

After installing the root locked Python environment, run:

```sh
cd tests/playwright
npm ci --ignore-scripts
npx playwright install chromium firefox webkit
npm run typecheck
npm test
```

Use `npm run test:chromium` for a focused local run or `npm run test:headed` to
watch a Chromium session. `npm run test:list` lists cases without replacing the
last HTML or JSON report. `EZLLMROUTER_TEST_PYTHON` can select an existing locked
Python executable; otherwise the harness uses the repository's `.venv`.
Browser runs require permission to bind localhost and start browser processes.

The suite covers first sign-in, password changes, accounts, role boundaries,
navigation, stale and failed requests, provider credential setup, local connector
discovery and model selection, catalogue CRUD, activity, accounting corrections
and report downloads. Service controls use a private stdin protocol; no test
control endpoints are added to the application. Existing service instances,
credentials, model servers and deployment volumes are not test inputs.

CI runs all three browser projects separately. Failed runs retain screenshots,
traces, a JSON result file and an HTML report under ignored
`.artifacts/playwright/`. Fixtures use synthetic credentials because traces can
include entered values and HTTP bodies.
Run `npm run report` to inspect the local HTML report.

## Fixture and evidence organization

One-off gateway qualification and forensic commands live under
`tools/gateway/evidence/`; historical Docker-input tooling lives under
`tools/gateway/docker/`. Accounting evidence actors live under
`tools/accounting/evidence/`, and operator browser proofs under `tools/operator/`. Runtime compatibility shims are removed. Historical proof IDs,
recorded source commits and contract fixtures preserve their original identities;
new source packets record the relocated paths. Synthetic successor authority,
allowance, execution and receipt helpers live in `tools/synthetic/`, outside the
production wheel. Staging includes them only in explicit fixture mode.

Repeatable HTTP tests bind the server directly to port zero and use its actual
bound port, including the operator Host/Origin policy. Observable-state waits
have bounded shared helpers, and synchronization uses events where the test needs
a held execution. Intentional timeout, delayed-start and slow-response faults
retain their explicit timing. Tool-dependent unit fixtures explain missing
Git/Node/OpenSSL skips; those skips do not establish target qualification.
Assertions in repeatable tests stay active under optimized Python. Named client
and retrieval tests use descriptive filenames instead of development milestones.

## Gateway negative controls

Runtime adapters use fixed request checks and destinations. Mutation, bypass,
context-swap, trace-file and private-pool inspection controls live in explicit
fixtures under `tools/gateway/fixture_adapters.py` and `worker_fixture.py`.
The disposable gateway harness requests these with the staging command's
`--fixtures` flag. Normal local-profile staging omits the fixture adapters and
entry points, and the worker's normal command interface rejects raw egress probes.

The isolated `ezllmrouter_worker` package receives its worker entry points and a
small explicit list of dependency-free helpers from `tools/gateway/worker_package.py`.
Those helpers are byte-identical copies of the canonical service sources. The
worker imports package-relative modules and runs with `python -m ezllmrouter_worker`;
the trusted server package remains unavailable in its runtime. The in-process
LiteLLM experiment lives in `tools/gateway/asgi_adapter.py` and is absent from the
server wheel. Frozen alternate-handler validation mounts only the required tool
and server sources in the worker's network-disabled build check.

Both processes log exception types and stack locations without messages, source
text, credentials or payloads. Offline regressions use mock vendor modules, socket
pairs and disposable stores. They do not qualify the actual frozen worker or
Docker signal/mount behavior; those remain target checks.

## Test and build inputs

| Location | Purpose |
| --- | --- |
| `tests/fixtures/contracts/` | Schemas, examples, vectors and standalone conformance checks. |
| `deploy/local/inputs/catalogue.json` | Model catalogue seed used by import and display checks. |
| `deploy/local/inputs/fixtures/` | Runtime execution/request/tool-cycle fixture copies; parity checks preserve adopted test-golden bytes. |
| `deploy/local/inputs/gateway/` | Frozen gateway lock, wheel inventory and advisory metadata. |
| `server/` and client package resources | Runtime copies of supported schemas. |

Data fixtures retain their exact IDs, rates, protocol fields and hashes. Moving
a fixture does not change its contract. Keep runtime schema copies consistent
with their source fixtures when making an authorized contract change.

Generated run evidence belongs in ignored `.artifacts/` or a configured private
artifact store. Keep databases, credentials, keyrings, build archives and run
logs out of the documentation tree and Git. Use fresh namespaces for controlled
test runs; never overwrite a retained run.

## Validation boundaries

Passing local checks does not establish Docker deployment, provider execution
or production readiness. The optional execution profile requires verified frozen
inputs and its own deployment checks. Preparing documentation or building a
package does not authorize a model call, spending or an instance restart.


The registered `tests.unit.test_source_size` gate enforces source-size budgets in
`tools/source_size_budget.json`. Runtime Python files/functions/classes have
800/100/600-line limits; tools/tests have 1,500/200/1,500-line limits. Source files
in other languages receive the file limit. Explicit existing allowances can
only shrink: reduce their ceilings with the code, and remove resolved entries.
Code relocations must transfer an existing allowance explicitly in review,
without increasing its ceiling. New non-ignored source files are checked too.
