# Testing roadmap

The browser baseline passed all 381 cases across Chromium, Firefox and WebKit
in the owner Terminal. The subsequent Claude review is being addressed in the
[review follow-up](CODE-REVIEW-FOLLOWUP.md). The longer-term priorities below
still apply. The implementation ledger below records measured coverage and the
remaining deployment qualification separately.

## First gate: browser baseline

Run the complete suite in `tests/playwright` against Chromium, Firefox and WebKit,
with the locked Python environment and pinned npm dependencies. Type checking,
all browser projects and the existing regression gates must pass. CI treats a
test that passes only on retry as a failure. Resolve failures before adding the
later test layers below.

The browser suite uses the real operator HTTP handlers, browser assets, registry,
SQLite database and encrypted credential stores. Each test has its own service
and data. Local model discovery uses loopback HTTP; cloud inventory uses a
deterministic discovery adapter. It checks user-visible behavior and persisted
results without making inference requests. A passing run establishes this
fixture's behavior, not a deployed environment or a live provider connection.

| Browser area | Journeys |
| --- | --- |
| Sign-in and sessions | Bootstrap password change, invalid credentials, exact passwords, reload, expiry, logout and cookies. |
| Accounts and permissions | Create, edit, disable, delete, reset, model grants, last-administrator protection, concurrent edits and cross-session revocation. |
| Navigation | Administrative screens, deep links, history, keyboard focus, narrow viewport, failed requests and late responses. |
| Local connectors | Discovery over HTTP, explicit selections, metadata failures, key handling, disable, delete and restart. |
| Cloud connections | Draft setup, write-only credentials, model choices, replacements, rejected keys, disable and restart. |
| Model catalogue | Search, fixture separation, reference prices, source links, create, edit and archive. |
| Activity and accounting | Identity scoping, filters, unknown costs, corrections, tabs, downloads, empty states and demo separation. |
| Browser security | Role boundaries, CSRF, Origin checks, literal rendering of user input and response headers. |

Coverage is journey-based. It is not an exhaustive browser, accessibility, visual
regression or security audit. The existing component and HTTP tests remain
necessary for combinations that would be slow or awkward to exercise through UI.

## Subsequent work

Implement these in order, keeping each addition independently reviewable.

| Priority | Work | Completion evidence |
| --- | --- | --- |
| 1 | Close CI discovery gaps and establish measured coverage. Inventory maintained tests outside `tools.check` and workflow jobs, especially JavaScript SDK/runtime and installed-consumer scripts. Classify each as offline, loopback or deployment-dependent. Add suitable maintained offline and HTTP tests to CI. Measure Python and Node coverage by subsystem. | An explicit test inventory, no silently omitted maintained suites, reproducible coverage reports and a critical-behavior gap list. Set thresholds after measuring the baseline; avoid a single percentage that hides untested authorization or accounting paths. |
| 2 | Extend transport and API security tests through real sockets. Build on current Python HTTP/TLS and native-client fixtures. Cover framing, truncated and oversized bodies, compression, redirects, deadline expiry, interrupted responses, session revocation and wrong identity/version responses. Include JavaScript actual HTTP behavior alongside its mocked-fetch cases. | Each supported client rejects malformed or mismatched responses with the documented error and retry semantics. Negative requests produce no extra send or credential disclosure. All fixtures run locally in CI. |
| 3 | Test durability at process boundaries. Extend existing startup, accounting-recovery, migration and key-rotation tests with subprocess termination around database commits and dispatch transitions. Exercise concurrent writes, revision conflicts and coherent backup/restore of databases with all required keyrings. | Restart preserves attempts and accounting exactly once, stale writers cannot overwrite current policy, incomplete backups fail safely and a restored disposable installation reads its retained secrets and observations. |
| 4 | Expand installation and platform checks. Keep shared contract cases and packaged-consumer checks for all six client languages. Add a small supported-platform matrix, prioritizing Windows and macOS transport, paths, Unicode, timeouts and package loading. Test documented install commands against built packages. | A fresh consumer can install, import and use each package on its declared supported platforms, with matching contract and transport results. Supported runtimes and platform limits are documented. |
| 5 | Add generated and adversarial inputs. Target parsers, contract versions, Unicode identifiers, numeric boundaries, decimal accounting, duplicate events and correction ordering. Preserve useful failing seeds as small regression cases. | Deterministic seeded runs find no crashes, hangs, accepted invalid authority, duplicate charges or lost corrections. Use independently stated invariants rather than copies of implementation logic. |
| 6 | Establish performance and long-running baselines. Seed realistic disposable ledger sizes and measure report/export latency, memory, SQLite contention and connector polling under repeated navigation. Add bounded concurrency and soak runs with synthetic upstreams. | Measured latency, throughput and resource budgets with repeatable inputs. No unbounded growth, leaked jobs or duplicate execution. Put slow runs on a separate schedule or manual job before making stable budgets blocking. |

Separately, test the packaged local deployment using reviewed frozen inputs:
startup, health, filesystem permissions, network isolation, restart and restore.
This needs its own disposable Docker environment. Keep it distinct from the
browser fixture and do not treat it as permission to restart an existing profile
or contact a paid provider. Any live-provider qualification remains an explicit,
bounded operation with separate credentials and spending authorization.

Continue review work by affected behavior and severity, with a regression test
for each confirmed defect. The implementation ledger below records coverage
measurements, generated inputs and process-boundary tests added after the browser
baseline. Their scoped results do not complete deployment qualification or every
later test layer.

## Testing-review implementation ledger

This ledger tracks the 20 recommendations in the owner's
`EzLLMRouter-testing-review-2026-11-20.md`, reviewed at `1c4a715`.
The report's counts are estimates: the recorded source gate at that commit ran
928 Python cases, with 161 strictly checked files and 518 selected fresh-wheel
cases. Re-measure each tier rather than equating method counts with executed
cases. Some recommendations already have partial implementations; the table
keeps those distinct from new work and from target verification.

| ID | Recommendation | Status and evidence |
| --- | --- | --- |
| T01 | Python/Node coverage and critical-branch ratchets | Implemented for the declared measurement scopes: offline and HTTP Python measurements and lock auditing run in PR CI, with independent exact missing-code budgets and a source-checked combined report. SDK coverage uses a static TypeScript function inventory with V8 hits; all console scripts have static AST counter inventories and measured hits. All 13 selected critical functions, including first-write transports and coordinator outcomes, require complete conditional-exit coverage; no current follow-up selector gaps remain. Nightly repeats retain all outcomes. Exception dispatch, native code and exhaustive JavaScript branch measurement remain outside these metrics. See DEVELOPMENT.md for commands. |
| T02 | Generated authorization matrix | Implemented for current route/action samples: all 66 operator routes have independent policy rows, including browser authority, session states, valid-body denials and both console modes. Another 42 existing-resource/action cases cover all 16 operator family bindings, separate dataset owners, grants, encrypted credential lifecycles and successful writes. The wire policy covers 42 route/version bindings with real bearer credentials and eight active identities. Direct-handler, socket-pair and localhost variants run in CI; sensitivity tests detect role, ownership and mutation bypasses. Source inventories and dispatch hashes require review when routes/actions change. Exhaustive combinations of resource states remain outside this scope. |
| T03 | Docker image builds and deployment checks | Partial: tools.container_tests inventories all tracked Dockerfiles and resolves supported unittest/discovery/pytest/script commands through actual preparation helpers, COPY, WORKDIR, stages and mount scope. Unsupported validation forms and unqualified staging contexts fail; negative regressions cover missing copies and preflights. Image build/structure/compose qualification still awaits the approved frozen bundle and a disposable target. |
| T04 | Supply-chain, secret and static security scans | Partial: Ruff S rules cover server/Python-client, worker, deploy and tools sources with exact finding and source identities. A standard-library secret scanner checks current source and reachable full Git history using redacted output and blob-bound public-fixture exceptions. Input checks validate Python hashes/archive identities, npm integrity/manifest agreement, reviewed local projects and native manifest declarations. OSV pagination and retained page replay fail closed. Bootstrap uv wheel/hash and the remaining action commit are pinned. Native transitive graphs and actual-image scans still need their qualified inputs. |
| T05 | HTTP/JSON/IPC fuzzing | Implemented for the declared generated corpus: authenticated operator/wire framing also traverses the real ingress relay; fragmented IPC boundaries and bounded provider compression cases reject truncation, trailing members and allocation bombs. All six client decoders consume 536 independent fixed-seed cases, including depth, Unicode, duplicate keys and numeric boundaries. These bounded campaigns do not establish exhaustive parser coverage. |
| T06 | Accounting/canonical/registry properties | Implemented for the declared generated models: independent canonical/digest/integer-decimal checks, accounting/campaign and model/principal histories now include grant activation/removal/scope intersections, model state, price publication/replay/stale writes, immutable schedules and historical costs. A bounded reducer simplifies commands, nested JSON, keys, strings and numeric values while preserving the first divergent invariant; invalid candidates cannot replace it. Larger state spaces remain outside this scope. |
| T07 | Forced concurrency and lock-scope detection | Implemented for the declared local synchronized suites: lock auditing adds blocking event/condition/future/join waits with positive controls for nonblocking/completed operations and conditions releasing their own gate. Explicit fixture checkpoints and thread-start infrastructure have narrow exceptions. Three seeded HTTP/TLS stress rounds cover shared revocation/cancellation with exact delivery counts alongside existing races; the nine-suite runner remains scheduled for longer runs. Arbitrary native mutex/file/CPU work and deployment load qualification remain separate. |
| T08 | Process crashes, storage faults and coherent restore | Implemented for the declared local process-crash/fault scope: 49 named SIGKILL checkpoints cover work/usage, encrypted-file publication, migrations, backup/WAL, real signed-plan issuance and durable intent references, first HTTP request bytes, reply publication and integration/connector database-key rotation. Reopen/retry preserves identities, history, unknown outcomes and single-attempt accounting; rotation rolls back atomically and resumes without another key. Coherent restore and SQLite full/busy/I/O faults remain covered. Physical power loss and interruption inside kernel I/O still require target qualification. |
| T09 | Per-schema upgrade fixtures | Implemented for v001–v003 and keyring format v1: WAL fixtures populate all 53 application tables and all JSON expression indexes. Independent migration allowlists protect unrelated data even after golden regeneration. Checksums, exact rows, accounting, content digests and inventory anchors survive upgrade/restart and failed-upgrade retry. Unsupported schemas/key formats and unqualified new resources fail closed. No private or binary databases are tracked. |
| T10 | Provider/client resilience matrix | Implemented for the declared matrix: all six owned HTTP/TLS clients consume the same 28 cases and assert public error/recovery/status policy, exact delivery counts, byte limits, deadlines, no redirect/replay and rejection of untrusted TLS before HTTP credentials arrive. Existing 144 protocol/accounting cases and critical first-write tests remain separate maintained dimensions. Live-provider and exhaustive cross-product qualification remain outside this scope. |
| T11 | Abuse rates and resource limits | Implemented for the documented local limits: an executable inventory links all twelve runtime-resource rows and six additional security/API groups to registered regressions. Real boundaries cover execution/connection admission, login rates and pending work, hashed bucket bounds, session eviction/admin reservation, 4,096 tokens, report readers/SQL deadline, IPC/body/response sizes and diagnostic rollover. Production load and container timing qualification remain separate. |
| T12 | Logs and canary-secret contracts | Implemented for the current logging contract: all 66 operator and 42 wire bindings have route/level/schema/canary checks across nine statuses; 42 family action cases verify literal positions. Dynamic IDs matching route words remain redacted. Tests distinguish INFO rejections from sanitized ERROR stacks and verify the copied worker logger without trusted server imports. Production log collection is outside this source contract. |
| T13 | Front-end payload contracts | Open. Component fixtures need real server payload/schema checks. |
| T14 | Released-client version skew | Awaiting inputs. Identify hash-pinned previous released packages and previous-server vectors; never substitute current packages and call that N-1 testing. |
| T15 | Supported platform matrix | Open. Add macOS service and macOS/Windows packaged-client workflows with accurate supported-platform boundaries. |
| T16 | Performance and soak | Partial. `test_reporting_stream` already asserts bounded Python input memory as ledger size grows; exact 1k/10k comparisons are recorded in the review follow-up. Add reproducible scheduled latency/resource/soak runners. |
| T17 | Accessibility | Open. Keyboard/focus/viewport browser checks exist; add screen-complete automated accessibility, zoom and reduced-motion journeys. |
| T18 | Mutation testing | Implemented for seven declared critical decisions: source-pinned isolated mutations target grant removal, operation replay payloads, published price identity, login backoff, abandoned first writes, queue capacity and route-ID redaction. Passing baselines and imported-copy identities are required. Killed, survived, invalid and timeout outcomes are recorded separately; survivors/invalid/timeouts fail a dedicated CI job. Real subprocess controls verify all four outcomes and cleanup. This finite gate is not an exhaustive mutation score. |
| T19 | Time/locale/timezone boundaries | Partial: before/at/after boundaries cover HTTP and client total deadlines, plan/attempt expiry, trusted-context offset equivalence, wire-token/browser-session expiry and clock rollback, and exact login backoff opening times. Locale, DST and broader scheduling/deployment-clock cases remain. |
| T20 | Executable documentation | Open. Run extracted documented Python/JS examples against controlled service boundaries. |

All-skipped/empty-suite rejection and maintained-test inventories already block
`tools.check`. Existing startup-hook checks use archive inspection without
importing wheel code. These are verified foundations, not new missing tests.
Test-duration/outcome artifacts and repeat-run instability reporting now run to make future slow/flaky-test decisions evidence based. Retrying a failed
test never turns its original failure into a pass.

The implementation uses existing pinned runtimes where possible. This executor
currently cannot resolve package-download hosts. New third-party scanner or
browser dependency pins require their actual reviewed archives/checksums and
lock entries; an unavailable tool or frozen bundle is recorded as unverified,
not as a passing check. No testing change authorizes real-provider traffic,
spending, a persistent-profile restart or reacquisition of frozen gateway inputs.

## Testing follow-up review, 2026-11-21

The owner's `EzLLMRouter-testing-review-followup-2026-11-21.md` reviewed
`bd18676`. Its findings take priority over extending the original roadmap.
For each fix, first run the new bad-code/negative fixture against the old gate
and retain that failing run under ignored `.artifacts/testing-review-followup/`.
Then fix the gate, run the regression and full checks, and update this table.

| Finding | Status |
| --- | --- |
| H1: lost lock violations and missing instrumentation | Core fixes implemented: retained module-wide verdict, worker/caught/loop probes, SQLite on asyncio, TLS data methods, maintenance stores and registry/credential/vault/availability gates. Initial negative run: nine failing assertions and six unguarded TLS errors; all four probe tests now pass. Broader synchronization/file-I/O waits remain outside scope. |
| H2: generated framing never reaches body parsers | Fixed: the old generator fails the new reached-parser assertion with zero calls. Authenticated generation and positive controls now assert every parser/dispatch boundary. New negative cases first produced 21 failures, including empty Transfer-Encoding and non-ASCII length digits, plus a newly found valid-JSON/truncated-body dispatch on both servers. Both parsers now enforce ASCII length digits and complete bodies; wire rejects any Transfer-Encoding header, including empty. |
| H3: authorization role/body/method gaps | Implemented for current operator route samples: read-only/password-change-required sessions, valid-body write denials, wrong methods and integration-only mode. The old gate first failed two sensitivity assertions; three sensitivity tests now pass, together with nine direct-handler, ten socket-pair and ten localhost HTTP tests. That validation passed 1,017 Python cases plus maintained script/JavaScript checks. T02 adds the current wire API and existing-resource family matrices. |
| M1: HTTP tier lacks measurements and lock audit | Implemented: the PR HTTP step enables coverage, its own reviewed budget and retained lock auditing; source/runtime/denominator checks protect the merged offline/HTTP report, and artifact upload follows both tiers. The first audited HTTP run exposed provider I/O under the shared probe bookkeeping lock and a fixture mutation on the asyncio loop. Probes now serialize through completion events outside that lock, with duplicate/retry regressions; the TLS fixture moves its mutation to a thread. |
| M2: Python coverage allowance can be reused | Fixed: hash-bound exact missing-line/exit sets reject equal-count coverage swaps and require tightening after improvements. Changed sources require reviewed identities. The migrated offline baseline removes 222 line and 190 exit allowances without increasing any per-file count. Eight deterministic scheduler tests run in both tiers to cover every scheduler conditional exit, including stopping before the first tick. Linux CI comparisons exposed the scheduling variance; the first HTTP gate correctly demanded a tighter budget when an extra background tick covered five lines and five exits. |
| M3: dynamic JS function denominator | Fixed: the locked TypeScript 5.9.3 parser inventories SDK source functions before V8 hits are mapped by UTF-16 span. Nested and never-loaded functions remain counted; script wrappers are excluded. Real V8 regressions preserve the denominator when outer calls are removed and cover astral text, methods/accessors, constructors, arrows and generators. The installed SDK checks cover 156 of 158 static functions; exact missing identities are budgeted. |
| M4: forbidden version spellings and mutable images | Fixed: release-component normalization rejects abbreviated/zero-padded/local/pre/post spellings; Docker FROM/ARG and compose/workflow fields reject forbidden/mutable/unpinned LiteLLM references. Quoted keys and inline mappings work; unresolved anchors/block scalars fail. Forty negative assertions first failed; syntax probes additionally caught four bypasses and a stage-alias false positive before correction. Standard-library CI preflight precedes project dependency installation. No artifact acquisition or approval. |
| M5: Docker COPY/WORKDIR and unparsed validation commands | Implemented: all 17 tracked Dockerfiles are inventoried; supported validation entry points resolve through preparation's actual staging helpers and a COPY/stage/WORKDIR/PYTHONPATH/mount model. Exec RUN, shell wrappers, pytest and non-test-named preflights are checked; unsupported validation forms and unqualified staging contexts fail. The old checker first failed 11 negative assertions; all 12 focused tests now pass. Image builds remain a separate target qualification. |
| M6: secret scanning, shipped SAST scope and inventory completeness | Implemented for current declared inputs: full-history/current-source secret detection with exact public-fixture exceptions; SAST includes worker/deploy/tools; unreviewed nonregistry Python/native sources, malformed hashes, npm integrity/manifest drift and archive-identity mismatches fail. Native declarations and explicitly incomplete inputs are inventoried with their limits. OSV pages are followed, retained and checked on replay. This source result does not qualify unavailable archive bytes, native transitive graphs or image contents. |
| M7: setup/timeout telemetry, timing overhead and stress/flake semantics | Implemented: sanitized fixture/load/timeout/module outcomes use atomic invocation records; inconsistent module/test outcomes fail the runner. A passing child record cannot hide a later process timeout. Monitoring disables completed entry/line/conditional locations, preserving both branch exits. PR duration budgets run separately without instrumentation. Stress records and passes per-round generator seeds, with their scope stated explicitly. Twelve focused regressions pass, including warmed callback and collector-reuse checks; richer models and acquire-order assertions remain M8. |
| M8: forced interleavings and richer generated models | Implemented: both campaign orders require actual competing authority-gate contention; a delayed-competitor mutation is rejected. Campaign generation renews synthetic allowances and exercises over-bound costs, unknown charges and corrections without early saturation. Registry models cover multiple models/principals, edits/states, conflicting operation IDs and version checks after stale rejection. General JSON includes null/floats/escapes/controls/Unicode keys; canonical bytes come from literal construction and digest expectations use known answers. First-divergence traces undergo bounded command deletion and replay; sensitivity tests verify detection and reduction. |
| M9: WAL goldens, unaffected-table invariants, richer restore/crash cases | Implemented for v001–v003: release-specific WAL fixtures populate all 53 application tables and every JSON expression index. Independent migration allowlists reject regenerated destructive goldens. Twelve migration, two backup and two WAL-boundary SIGKILL cases verify repeated recovery. Restore removes access to the original path and tests missing/older/newer/retired key combinations in all three scopes. Interrupted backup now leaves no published partial destination; publication and sync failures retain their exact state. Kernel checkpoint I/O and physical power-loss qualification remain outside these process-crash tests. |
| L1: non-ASCII Content-Length digits | Fixed with H2; byte 0xB2 is rejected as an input error, with no dispatch, instead of wire returning 503. |
| L2: artifact retention | Implemented: managed default health/coverage/type-audit/stress outputs retain five successful and five failed runs per kind. Leases protect active processes; abandoned runs retain failure evidence. Pins, explicit destinations, unmarked legacy runs and curated review evidence are preserved. Four focused regressions cover repeated invocations, failure/active/pinned evidence, symlinks and abrupt process exit. |
| L3: bootstrap pins and advisory environment | Implemented: advisory lookup stays standard-library-only. All remaining uv bootstrap installs require the reviewed 0.13.9 Linux x86_64 wheel hash; its downloaded archive agrees with PyPI metadata and has no startup hooks. setup-dotnet uses the exact verified upstream commit formerly selected by v5. Provenance is recorded in .github/bootstrap-inputs.json; source regressions reject the old unhashed/mutable forms. Frozen inputs are unchanged. |
| L4: smaller measurement/SAST/decoder gaps | Implemented: SAST exceptions bind source and exact finding identities. JSON differential observations preserve numeric types and signed zero; JS `-0` is normalized to integer zero. IPC nesting is bounded on both paths. All 15 console scripts have static denominators, measured hits and exact missing-counter budgets. Compiler copies of Python `while` predicates share logical exit identities, including compound, async and large-jump cases. UUID VM artifacts preserve same-PID worker measurements. A live tracing-hook regression and its broken-collector probe replace the vacuous assertion. |

M1–M3 local validation uses Python 3.12.15 and Node 24.22.1. The enforced offline
gate passes 1,044 Python cases plus maintained script/JavaScript checks; all 95
HTTP/TLS cases pass with coverage, lock auditing and the 30-second module budget.
Offline line coverage is 88.65%; the combined offline/HTTP report reaches 92.08%
with no initial critical-selector gaps. Installed SDK offline and actual HTTP
checks pass against a fresh locally packed package. Red/green logs, source-bound
reports and the previous Linux CI comparison remain under ignored
`.artifacts/testing-review-followup/` and `.artifacts/coverage/`. Deployment,
frozen-worker and broader T01 follow-up selectors remain separate qualifications.

M5/M7/L2 local validation passes both coverage/lock-audit tiers: 88.65% offline,
69.79% HTTP and 92.08% combined line coverage. The first Linux CI HTTP run
correctly demanded a tighter budget when handler shutdown happened to cover
four additional lines and five exits. Both tiers now run the eight existing
socket-budget regressions, forcing closed-stream, handler-join, thread-start
failure, framing and cancellation outcomes. The HTTP budget removes 38 line
and 22 exit allowances across two unchanged sources; no allowance increases.
A separate uninstrumented offline/HTTP pass meets the
30-second module budget (slowest module 9.10 seconds), with no inconsistent
outcomes. The final 54 focused regressions and a three-round offline stress
smoke run (15 suite invocations) pass, as do 22 further coverage/inventory
regressions. Logs and source-bound summaries remain
under ignored `.artifacts/testing-review-followup/`; no Docker build, frozen
input change or running-profile operation was performed.

M6/L3/L4-SAST validation retains failing negative probes before each gate fix,
then passes 33 focused regressions and the actual guarded secret-scanner suite.
The expanded SAST review binds 1,006 existing findings across 163 file/rule
groups, including owner-run evidence assertions and explicit tool calls. Secret
exceptions bind 278 exact public/synthetic blobs. The dependency inventory records
142 declared candidates from 22 inputs; unavailable archive bytes and native
transitive graphs remain explicit limits. Offline/HTTP coverage and their merged
gate pass without budget changes (88.65%, 69.79% and 92.08%). The separate
uninstrumented pass runs 1,194 Python cases, with a 9.30-second slowest module and
no inconsistent outcomes. Final source-security refinements also pass the focused
and standalone gates. Red/green logs, archive inspection, source identities and
validation records remain under ignored `.artifacts/testing-review-followup/`.
No frozen input, dependency version, running profile or provider execution changed.

L4 measurement validation passes 43 focused Python regressions, three VM
instrumentation cases and all maintained console scripts. All 15 console sources
now retain static denominators: 288 of 1,148 functions and 1,668 of 5,119
statements are covered; the exact remaining counter identities are budgeted.
The Python inventory removes 64 verified compiler-copy exits while preserving
distinct cleanup paths. Offline and HTTP budgets remove 32 and 41 missing-exit
allowances respectively, with no application source or missing-line changes.
Both coverage/lock-audit tiers and their merged gate pass at 88.73%, 70.62% and
92.15% line coverage. Validation also exposed and fixed concurrent collector
initialization that could reset another thread's hits; its negative probe fails
before serialization and passes afterward.

The separate uninstrumented L4 pass runs 1,216 Python cases across 174 module
invocations, with an 8.88-second slowest module and no inconsistent outcomes.
Replaying the retained same-source SDK measurements through the updated reporter
preserves its 156-of-158 function result; this is a reporter check, not a new
package installation. Source/security checks pass, including 1,008 individually
reviewed SAST findings. Logs and source-bound reports remain under ignored
`.artifacts/testing-review-followup/` and `.artifacts/coverage/`. Broader T01
critical selectors and deployment qualification retain their stated limits.

T01 first-write validation closes the ten remaining transport exit gaps. Seven
new socket-pair tests run in both tiers; all 86 logical exits across four
transport selectors are covered and now block regressions. The offline budget
removes five missing-line and 24 missing-exit allowances; HTTP removes 63 and 44,
with unchanged application source hashes and no allowance increases. Both
coverage/lock-audit tiers and their merged gate pass at 88.75%, 70.90% and 92.17%
line coverage. The independent duration pass runs 1,230 Python cases across 176
module invocations; the slowest takes 9.47 seconds, with no inconsistent outcomes.
TLS drain units use opaque MemoryBIO fixtures, alongside the existing real
localhost TLS checks. The 19 coordinator outcome exits remain the next T01 group.
Source-bound reports and reviewed budget changes remain under ignored
`.artifacts/testing-review-followup/` and `.artifacts/coverage/`.

T01 coordinator validation closes the remaining 19 outcome exit gaps. Twelve
new tests use actual temporary SQLite intents, usage revisions and campaign
reservations; all 32 exits across the three outcome functions are covered and
blocking. All 13 selected critical functions now have zero gaps, with no deferred
selectors. The offline budget removes 18 missing-line and 20 missing-exit
allowances; HTTP removes 61 and 59. Application source hashes are unchanged and
no allowances increase. Both coverage/lock-audit tiers and their merged gate pass
at 88.83%, 71.16% and 92.25% line coverage. The separate duration run passes 1,254
Python test executions across 178 module invocations; the slowest takes 9.31
seconds, with no inconsistent outcomes. Provider and deployment qualification,
native/exception-edge coverage and the broader T02 authorization matrix remain
separate work.

T02 wire validation adds 47 test executions across direct handlers, socket pairs,
localhost HTTP and two sensitivity regressions. The independent policy covers
42 route/version bindings and eight active identities, with real registry
credentials and temporary SQLite resources. A negative regression first exposed
work 0.3 reading legacy attribution routes and returning a 0.2 response; both
legacy GET routes now require 0.2, matching their POST boundary. Denials preserve
database/authority/dispatch state, while fresh writes and replay controls pass.
Offline and HTTP budgets remove 246/454 missing-line and 150/241 missing-exit
allowances respectively. The changed handler's remaining identities map to
reviewed prior gaps; all four new version-guard exits are covered. Coverage and
lock-audit gates pass at 89.90%, 73.14% and 92.53% combined line coverage, with all
13 critical selectors still complete. The separate duration run passes 1,301
Python test executions across 182 module invocations; the slowest takes 8.83
seconds, with no inconsistent outcomes. Source/security checks and documentation
links pass. Source-bound reports and red/green evidence remain under ignored
`.artifacts/testing-review-followup/` and `.artifacts/coverage/`. Broader operator
resource-family scenarios remain under T02; no provider, profile or frozen-input
operation was performed.

T02 resource-family validation adds 38 test executions: twelve scenarios through
each of three transports and two sensitivity regressions. The independent policy
has 42 existing-resource/action cases across all 16 operator family bindings.
Separate dataset owners, current grants and sessions, credential lifecycle
actions, successful writes and unchanged-state denials are exercised against
actual services and temporary SQLite records. Two negative subtests first showed
that extra path segments could alias a provider validation or queue a demo job;
both malformed routes now return 404 before accessing the record or dispatching.
All six new guard exits are covered. Remaining changed-source coverage identities
map to reviewed prior gaps; offline/HTTP budgets remove 66/827 missing-line and
59/422 missing-exit allowances, with no increases. Coverage/lock-audit gates pass
at 90.19%, 76.74% and 92.70% combined line coverage, with all 13 critical functions
complete. The separate duration run passes 1,339 Python test executions across
186 module invocations; the slowest takes 11.91 seconds, with no inconsistent
outcomes. Source/security checks, JSON and documentation links pass. Reviewed
source identities and red/green evidence remain under ignored
`.artifacts/testing-review-followup/` and `.artifacts/coverage/`. T02 is implemented
for these current route/action samples. Exhaustive resource-state combinations,
provider and deployment qualification remain outside this scope; no frozen input
or running profile changed.

Transport-batch validation adds the shared decoder/HTTP matrices, ingress and
compression generation, the resource-limit inventory, route logging contracts
and expiry/deadline boundaries. Instrumented local runs passed 1,228 offline and
183 HTTP Python test executions with no lock-audit violations. Offline line
coverage is 90.26% (20,839/23,087), HTTP is 77.23% (17,831/23,087), and the combined
report is 92.76% (21,416/23,087). The 12,000 logical conditional exits have 8,456
offline, 6,381 HTTP and 8,913 combined hits; all 13 critical functions remain
complete. Changed-source budgets preserve only mapped, reviewed old gaps; the
new compression and route-label functions have no missing conditional exits in
either tier. Other budgets only tighten.

The corpus exposed and now covers empty/ambiguous encoding acceptance in Go,
Java and .NET, duplicate version acceptance in Go, and the .NET depth-32
boundary. Source regressions also cover bounded complete decompression, ingress
half-close/early-rejection forwarding, positional route-ID redaction and exact
login-backoff opening times. Installed JavaScript, Go race/vet, Java and packaged
.NET checks passed locally. The owner's Rust executable cannot run on this ARM64
host; native Rust validation belongs to the maintained CI job. Evidence remains
under ignored `.artifacts/testing-review-followup/` and `.artifacts/coverage/`.
T19 retains its locale/DST follow-up. These checks do not send provider requests,
restart the persistent profile or change frozen inputs.

The separate uninstrumented run passed all 1,411 executions across 198 module
invocations. The slowest module took 11.88 seconds, within the 30-second budget;
no unstable outcomes were recorded. The limit inventory also verifies the actual
Coordinator, successor and sender-check pool configuration against its declared
worker/capacity values.

The first CI Rust corpus run also exposed Serde's classification of integer
`-0` as floating point. Rust decoding now normalizes only that complete integer
token outside strings; decimal/exponent forms and malformed adjacency remain
invalid. Dedicated cases preserve quoted bytes and both accepted/refused forms.

State/recovery batch validation passed 1,240 offline and 184 HTTP Python test
executions, with no lock-audit violations. The separate uninstrumented run passed
all 1,424 executions across 205 module invocations; the slowest module took
12.15 seconds, below the 30-second budget. Offline line coverage is 90.28%
(20,843/23,087), HTTP is 77.36% (17,860/23,087), and combined is 92.78%
(21,420/23,087). Of 12,000 logical conditional exits, the tiers cover 8,464,
6,392 and 8,921 respectively; all thirteen critical functions remain complete.
Application source hashes are unchanged and coverage budgets only tighten.

Three synchronized stress rounds passed all 27 suite executions, including
72 concurrent HTTP/TLS exchanges with exact delivery counts. The master seed
20261120 produced round seeds 10789855592110675028, 17704106921817721005 and
6099287097979355139. An initial generated-model assumption about a legacy
unpriced record was corrected without adding a price identity to that record.
The seven critical decision mutations were all killed, with zero survivors,
invalid cases or timeouts. Separate real-process controls exercise all four
outcomes. A dedicated mutation CI job retains reports and logs; temporary
source/runtime copies are excluded. Source-bound results, initial failures and
reviewed budget changes remain under ignored `.artifacts/testing-review-followup/`,
`.artifacts/coverage/`, `.artifacts/concurrency-stress/` and `.artifacts/mutations/`.
These local checks use disposable synthetic data and do not qualify physical
power loss, arbitrary native waits or production throughput.
