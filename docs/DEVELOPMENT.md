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
uv run --locked python -m tools.check --coverage --coverage-gate
```

The PR gate measures and audits both tiers independently, then merges their
Python hits into one combined report. Use fresh output directories for each run:

```sh
uv run --locked python -m tools.check --coverage --coverage-gate --lock-audit --coverage-dir .artifacts/coverage/offline
uv run --locked python -m tools.check --http-only --coverage --coverage-gate --lock-audit --coverage-dir .artifacts/coverage/http --coverage-merge .artifacts/coverage/offline
uv run --locked python -m tools.check --tests-only --loopback --health-budget 30
```

The second and third commands require permission to bind localhost fixtures. The HTTP
directory retains its own summary and a `combined/` report containing the union
of offline and HTTP hits. Merge inputs must have identical Python versions,
measurement scopes, source inventories, source hashes and static denominators.
The PR artifact upload follows both tiers and runs even after a failure.
Both tiers include deterministic scheduler and connection-shutdown outcomes so
incidental background ticks or handler completion cannot change their reviewed
coverage sets.

Each run creates a fresh directory under `.artifacts/coverage/`. `summary.json`
records Python source hashes, executable/missing lines, and both logical exits of each
conditional bytecode instruction, including loops and worker threads. Compiler
copies of a `while` predicate share the original exit identities; compound
conditions retain each decision. Raw branch files use
`ezllmrouter-logical-branches-v2`; earlier physical-exit files must be replaced by
fresh measurements before reporting or merging. Exception
dispatch edges and native code are outside this metric. `subsystems.json` and
`index.html` show subsystem totals and the explicit critical-exit gap list.
`tools/coverage_budget.json` and `tools/coverage_budget_http.json` retain the exact
missing line and conditional-exit identities for their respective tiers. An
unchanged source must match its reviewed sets: newly missing code fails even
when another gap was covered, and improvements require tightening the baseline.
Changed source hashes require reviewing and updating the identities. New files
have zero allowance. Critical selectors in `coverage_policy.json` must exist and
have no uncovered conditional exits in the offline or combined report. Standalone
HTTP runs apply any `critical_http` selectors and their independent budget.
The plaintext and TLS first-write selectors are blocking. Their socket-pair
regressions run in both tiers and reject missing authority, stale epochs,
revocation, abandonment, expired plans and exhausted write timeouts without
accepting request bytes. Real backpressure exercises finite and absent timeouts,
then rechecks authority before retrying. TLS drain tests use a real MemoryBIO
with opaque fixture bytes: handshake output does not count as request acceptance,
and an already accepted request can finish its suffix after revocation. The
separate loopback TLS fixture covers actual handshake, encryption and hostname
verification.
Coordinator failure and uncertain-outcome selectors are also blocking. Their
temporary SQLite fixtures verify that recovery retains reported usage once,
preserves completed candidates, binds provider prices to the planned and reported
model, and leaves missing evidence or unusable pricing unknown. Real campaign
reservations settle once when cost is known and retain their exposure when it is
unknown; unrelated attempts cannot settle a configured campaign. A post-send
response-processing fault additionally checks query-first recovery without
another send. All 13 current critical functions have complete conditional-exit
coverage; exception dispatch and native code remain outside that denominator.
Baseline increases require explicit review;
`tools.coverage_reports --write-baseline` is a maintenance operation, never a CI
step. Select the HTTP budget with `--baseline tools/coverage_budget_http.json`
when reviewing an HTTP baseline. `--loopback` measures both tiers together and
checks against the intersection of the independently reviewed missing-code sets.

Python monitoring disables each code-entry and line callback after its first hit,
and each conditional callback once both exits have been observed. A loop whose
second exit has not yet run still incurs branch callbacks. Concurrent first calls
share serialized initialization so hashing or disassembly cannot reset another
thread's hits. Coverage and lock
auditing therefore have separate timing observations from the uninstrumented
duration gate; their timings are not application performance measurements.

Installed SDK coverage maps native V8 function hits onto a static function
inventory from TypeScript 5.9.3. Nested functions remain in the denominator even
when their outer function is never called; never-loaded SDK files retain their
uncovered functions. Script wrappers and generated implicit constructors are not
source functions. Function offsets use UTF-16 units, including sources containing
astral characters. The installed-SDK job installs the same locked parser used by
console coverage and retains source hashes, static totals and missing-function
identities in its reviewed budget. Console VM coverage uses statement
and function counters inserted by the locked TypeScript 5.9.3 parser: Node
24.22.1 precise coverage mis-resolves an early `typeof` after a later lexical
binding. Instrumentation regressions preserve that binding, strict directives,
arrow `this`, loops and exceptions. The JS summary labels the two methods and
unmeasured files explicitly; it does not claim an exhaustive JS branch percentage.
Every `web/*.js` file has a static counter inventory, including scripts that were
never loaded; inventory generation parses source without executing it. All 15
console scripts must be measured. The console harness loads the current HTML
script list and separately exercises the older workspace script. VM artifacts
use exclusive UUID filenames so workers sharing a process ID retain separate hits.
`tools/javascript_coverage_budget.json` ratchets source hashes, static totals and
exact missing console counter and installed-SDK function identities. A regression
installs a real tracing hook and verifies events during and after a failed
collection; a deliberately broken collector proves the assertion detects hook loss.
V8 block ranges remain diagnostic
because their denominator changes when outer functions execute. Installed source aliases are
recorded before temporary packages are removed and must match canonical hashes.

Every normal check also writes sanitized per-test outcomes and durations under
`.artifacts/test-health/`, including failed subtests, skips and class/module
fixture failures. Parent processes retain module timeouts and unexpected exits
even when the child cannot write a result. Atomic records carry an invocation
identity and instrumentation labels. `--health-dir` selects a collection
directory, and `--repeat 5` repeats module suites while retaining all failures.
Inconsistent test or module outcomes fail the runner, including the nightly
five-repeat run. A passing retry never erases the original failure. Telemetry
contains test identifiers and timings, without exception messages, locals or
subtest values.

`--health-budget 30` caps uninstrumented Python module durations. Combining it
with coverage or lock auditing is rejected; instrumented observations are also
excluded when checking an existing collection. The PR workflow runs the separate
uninstrumented offline/HTTP command above after collecting coverage.

Default health, coverage, type-audit and concurrency-stress outputs use managed
run directories. Each kind retains its newest five successful and five failed
runs; a crashed run joins the failed group once its process lease is released.
Active leases and a `.keep` entry protect evidence from pruning. Explicit output
directories, legacy directories without ownership markers, and curated evidence
under `.artifacts/testing-review-followup/` are outside automatic retention.

`python -m tools.container_tests` inventories all tracked Dockerfiles and models
the service/worker validation contexts through preparation's pure staging helpers.
It follows COPY, stage inheritance, WORKDIR, PYTHONPATH, removal and temporary
bind mounts, checking unittest, discovery, pytest and standalone Python scripts
(including preflights without test-like filenames). Exec-form RUN and supported
shell wrappers are parsed; unsupported validation forms and recipes without a
qualified staging context fail. It cannot establish that images build or run;
those checks still require the approved frozen input bundle and a disposable
Docker target.

The independent operator policy table is
`tests/fixtures/operator_authorization.json`. Adding a route without a policy row
fails the offline gate. Matrix variants exercise the real handlers directly,
real HTTP parsing over socket pairs, and localhost listeners in the HTTP tier.
Expected statuses come from the checked-in table and documented roles, never
from the implementation's route-role metadata. The matrix covers administrator,
ordinary, read-only and password-change-required sessions in both full-console
and integration-only modes. Empty-body expectations and valid-body mutation
denials are separate; wrong-method requests must also fail. Positive controls
exercise user/connector creation and login, logout and own-password changes.
Sensitivity regressions verify that permitting a read-only user mutation, including
one conditional on a valid body, fails the matrix. Cross-user and rejected-write
cases additionally assert unchanged registry authority version. Broader operator
resource-family scenarios remain follow-up work.

The independent wire policy in `tests/fixtures/wire_authorization.json` covers
42 route/version bindings across work 0.2/0.3 and accounting 1/2/3. Source hashes,
work-route literals and the accounting read-route inventory require explicit
review when dispatch changes. The same matrix runs directly, over socket pairs
and on localhost. It uses actual registry credentials, temporary SQLite records
and controlled executors without provider traffic. Eight active identities cover
execution grants, dataset ownership, ingest, report access and the designated
credential consumer. Missing, invalid, duplicate, revoked, suspended and expired
credentials, version headers, wrong methods, integration-only mode, task and
dataset boundaries, and current historical-read grants have negative controls.
Denied requests must leave database changes, registry versions and dispatch
counts unchanged and disclose no result or credential canary. Fresh writes and
idempotent replays provide positive controls. Sensitivity regressions require
the matrix to fail after deliberate authentication and result-ownership bypasses.
Work 0.3 cannot fall back to legacy attribution routes or reuse a 0.2 work identity.

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

Parser failures print the seed and index, with synthetic JSON bytes encoded as
base64. Typed observations distinguish booleans, integers, floating-point values
and signed zero before transport serialization; request text still has a stricter
control-character policy than response text. The JavaScript integer decoder
normalizes `-0` to zero, matching Python. General inputs include null, floats,
escaped/control text and Unicode keys. Separate canonical cases start from literal
tokens in known UTF-16 order, then decode and shuffle insertion order; fixed
SHA-256 known answers check digest formatting.

Campaign and registry models stop at the first divergent invariant. A bounded
48-replay command-deletion reducer preserves that invariant and saves the failing
prefix plus minimized trace under the health directory's `generated-failures/`.
Without an explicit health directory, managed outputs retain five failures under
`.artifacts/test-health/`. These traces contain synthetic commands only; ordinary
health summaries remain value-free. Replay a saved minimized campaign trace with
`tests.generated_campaign.execute(trace["minimized"])`, or use
`tests.generated_registry.execute` for registry traces, after loading its JSON.
This is bounded command deletion, with no claim of globally minimal inputs or
general scalar/JSON shrinking.

Campaign expectations use integer nanodollars, renew allowances by explicitly
closing and configuring new synthetic campaigns, and include unknown and
over-bound settlements, late corrections, duplicate settlement/reconciliation,
and rejected admissions. Registry generation covers two models and two principals,
edits and state changes, exact operation replay, conflicting operation-ID reuse,
stale revisions, unchanged rejected-write versions and unaffected subjects.
Grant/price models and the other native decoders remain follow-up work.

Both campaign close/admission orders observe an actual failed nonblocking
authority-gate acquire by the competitor while the first transaction is held.
Only that checkpoint releases the transaction; an event before calling the
operation does not satisfy the test. A sensitivity probe delays the competitor
until after commit and verifies that this test fails.

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

The runner records the master seed and each round's seed, which controls both
suite order and the generated campaign-model inputs. Replaying those seeds does
not replay OS thread scheduling: the individual races use explicit events and
barriers. A failure or timeout stops the run and remains failed in `summary.json`
and the health records. The scheduled run uses 200 rounds and 512 generated
examples per round. Richer models and additional forced interleavings remain
separate follow-up work.

`test_process_durability` kills real child processes after a handshake at named
fixture-only checkpoints. It covers before-BEGIN, before-COMMIT and after-COMMIT
for work creation, intent, guard receipt and usage, plus encrypted-file
publication and provider-key rotation. These are process-crash tests, not a
power-loss or physical-disk qualification. Storage tests exercise real SQLite
page-limit/busy failures and an injected I/O failure after a work claim.
`test_coherent_restore` uses the real offline database-backup command, copies the
documented private keyring/vault set, restores credentials in all three scopes
and compares retained accounting after moving the original source path away.
It checks missing/older keyrings, newer rings retaining the needed key, and newer
rings after its retirement, in all three scopes. `test_maintenance_crashes`
adds 12 real kills inside migration statements/commit boundaries, two during
backup copy/publication and two at WAL checkpoint boundaries. Migration fixtures
populate all 53 application tables and all JSON expression indexes in WAL mode;
unaffected-table checks are independent of regenerated goldens. Kernel-I/O and
power-loss qualification remain separate. All data and secrets are synthetic and
temporary; the tests never open a running profile or contact a provider.

`tools.security_sast` runs the locked Ruff 0.14.0 `S` rules over server,
Python-client, worker, deployment and tools Python sources, ignoring inline
suppression directives. Git's source inventory excludes ignored runtime state.
Exceptions bind the file hash and each finding's rule, line/column, enclosing
symbol, statement hash and enclosing-code hash. Rehashing a changed file cannot
silently approve a different finding at the same count or a disabled guard
around an unchanged SQL expression. New, changed and resolved findings require
review. Existing tool assertions, explicit subprocess calls, synthetic credentials
and local SQL census expressions retain individual reviewed identities; the
scanner does not disable those rule families for future code.

`tools.security_secrets` scans tracked and nonignored untracked files plus all
reachable Git blobs for known credential prefixes, private-key headers and
high-entropy tokens. CI checks out full history and runs the standard-library
scanner before dependency installation. Credential-assignment context
distinguishes high-entropy hex secrets from public checksums. Git transports are
disabled for these reads, so missing objects fail instead of triggering a lazy
fetch. A shallow checkout or an unreadable,
oversized or linked source fails. Reports contain source identities, locations
and fingerprints, without matching values. Public fixture tokens, alphabets,
signatures and package digests have reviewed exceptions tied to exact blob
hashes and finding sets. These heuristic checks do not inspect ignored private
runtime files, unfetched references or unreachable Git objects. The explicit
limits are 16 MiB per blob and 256 MiB per scan; exceeding them fails rather than
claiming a complete scan.

`tools.security_dependencies` inventories Python/npm lock candidates, reviewed
local Python projects, build backends, bootstrap inputs and native manifests.
It validates Python archive names and SHA-256 fields, npm integrity encodings and
manifest/lock agreement, and exact native dependency declarations. Unreviewed
Git/path sources, missing hashes and unresolved versions fail. Go and .NET
currently declare no external runtime packages; Maven's build plugin and Rust's
direct runtime/development crates are included. Without a reviewed native lock,
transitive native dependencies remain explicitly unqualified. Incomplete gateway
drafts retain their not-installable status.
The PR run validates these inputs and writes `inventory.json` plus a CycloneDX
candidate SBOM without reaching the network. It rejects the forbidden LiteLLM
release component after normalizing abbreviated/zero-padded spellings and local,
pre/post suffixes. Dockerfile FROM/ARG defaults and compose/workflow image fields
reject mutable LiteLLM references, the forbidden release family and missing
digests. Quoted keys and inline container mappings are supported; unresolved
image anchors and block scalars fail. Arbitrary external image-variable values
and digest provenance are not qualified by this source check. CI runs the
standard-library preflight before installing project dependencies. The SBOM
describes declared candidates, not installed container contents. Digest fields
and source identities can be checked offline; unavailable archives are not
claimed byte-verified. Package managers still enforce archive hashes/integrity
during the corresponding qualified installations.

CI installs uv through [.github/requirements-bootstrap.lock](../.github/requirements-bootstrap.lock)
with `--force-reinstall --only-binary=:all: --no-deps --require-hashes`.
Reinstallation prevents an existing same-version package from bypassing archive
verification. Its reviewed Linux x86_64
wheel and the exact setup-dotnet action commit are recorded in
[bootstrap-inputs.json](../.github/bootstrap-inputs.json). Source checks reject
the former unhashed installs and mutable action reference. This bootstrap review
does not change or reacquire the frozen worker inputs.

The nightly `--audit` mode sends only package names/versions to the public OSV
API, follows and retains every advisory page, records the response snapshot and its inventory identity, and
fails on high, critical or unrated active advisories. Low/moderate findings stay
visible. Withdrawn entries must have a valid withdrawal time. Metadata outages,
incomplete batches, repeated/unconsumed page tokens and identity mismatches fail;
saved page evidence must reproduce the retained aggregate. These failures never establish a clean
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
