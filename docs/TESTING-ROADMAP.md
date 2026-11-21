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
| T01 | Python/Node coverage and critical-branch ratchets | Partial: Python line/conditional-exit and JS console/installed-SDK reports and per-file budgets now run in PR CI. Six initial critical selectors have zero gaps; first-byte/coordinator follow-up selectors remain explicitly listed and ratcheted. Nightly repeats retain all outcomes. See DEVELOPMENT.md for commands and metric scope. |
| T02 | Generated authorization matrix | Partial: all 66 operator routes have independent checked-in policy rows, with anonymous/expired/ordinary/admin, missing/wrong CSRF, Origin/Host and cross-user checks. The direct-handler and socket-pair versions pass offline; a localhost version is registered in the HTTP tier. Wire API matrix and broader family-resource scenarios remain. |
| T03 | Docker image builds and deployment checks | Partial: tools.container_tests resolves every Docker unittest/discovery/script command against actual preparation staging, with mount scope and negative regressions. Image build/structure/compose qualification still awaits the approved frozen bundle and a disposable target. |
| T04 | Supply-chain, secret and static security scans | Partial: the PR gate runs all Ruff S rules over server/Python-client sources, with 14 reviewed SQL findings pinned to entire source hashes. Bad-source regressions exercise the real scanner. Offline Python/npm inventory covers the shipped frozen locks and development/build/browser inputs; nightly OSV queries retain a snapshot and fail on high/critical/unrated advisories. Existing archive startup-hook checks remain. Full-history secret scanning, native-language audits and actual-image scans still need their qualified tool inputs. |
| T05 | HTTP/JSON/IPC fuzzing | Partial: fixed-seed request-stream mutations, fragmented/bounded IPC frames, and Python/JS response-decoder differential cases run offline. Server request-control restrictions are checked separately. Nightly runs use a recorded changing seed and larger budget. Ingress, compression and the four other native decoders remain. |
| T06 | Accounting/canonical/registry properties | Partial: canonical round trips, integer-based decimal conservation, identifier boundaries, model revision/idempotency/stale writes, shuffled/duplicate/late accounting events and a campaign exposure state model pass. Registry principal/grant/price models and automated shrinking remain. |
| T07 | Forced concurrency and lock-scope detection | Partial: the audit now retains cross-thread/caught violations and fails the module, watches TLS data I/O and the documented shared gates, and rejects raw/repository/store SQL on asyncio loops. Red/green bad-code probes cover these gaps. Explicit exceptions cover pre-listener bootstrap, the nonblocking atomic first write and asyncio wake-up. Broader wait detection, stronger campaign acquire-order assertions and stress-seed semantics remain follow-up work. Full HTTP/TLS stress qualification remains to be observed. |
| T08 | Process crashes, storage faults and coherent restore | Partial: real child kills cover 12 database and six encrypted-publication checkpoints; two-process exclusion, real SQLite full/busy errors, injected I/O rollback and a database/all-three-keyring restore pass offline. Missing rings fail closed. Actual first-provider-byte/plan/reply-publication kill points and interrupted database-credential rotation remain. |
| T09 | Per-schema upgrade fixtures | Implemented for current schema v001–v003 and keyring format v1: checked-in synthetic seed/checksum/table/report manifests rebuild temporary release databases. Upgrades and restarts preserve exact historical rows, corrected controlled/external cost totals, pruned content digests and inventory anchors. Every pending migration has a byte-preserving failure/retry case; future database/keyring formats fail closed. New SQL resources or a newly minted keyring format without a fixture fail the inventory gate. No private or binary databases are tracked. |
| T10 | Provider/client resilience matrix | Open. Compression, TLS, byte-limit, first-write and deadline examples exist; combine the declared transport behaviours in a shared matrix. |
| T11 | Abuse rates and resource limits | Open. Existing throttle/session/connection/diagnostic regressions need a documented limit/limit-plus-one inventory. |
| T12 | Logs and canary-secret contracts | Open. Exception redaction and named-route checks exist; add a complete route/level/schema/canary matrix. |
| T13 | Front-end payload contracts | Open. Component fixtures need real server payload/schema checks. |
| T14 | Released-client version skew | Awaiting inputs. Identify hash-pinned previous released packages and previous-server vectors; never substitute current packages and call that N-1 testing. |
| T15 | Supported platform matrix | Open. Add macOS service and macOS/Windows packaged-client workflows with accurate supported-platform boundaries. |
| T16 | Performance and soak | Partial. `test_reporting_stream` already asserts bounded Python input memory as ledger size grows; exact 1k/10k comparisons are recorded in the review follow-up. Add reproducible scheduled latency/resource/soak runners. |
| T17 | Accessibility | Open. Keyboard/focus/viewport browser checks exist; add screen-complete automated accessibility, zoom and reduced-motion journeys. |
| T18 | Mutation testing | Open. Add bounded, isolated mutations of critical decisions and report killed/survived/invalid/timeout outcomes separately. |
| T19 | Time/locale/timezone boundaries | Open. Existing injected clocks and timestamp comparisons need a complete expiry/locale/DST matrix. |
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
| H2: generated framing never reaches body parsers | Open; add authenticated targets and parser/dispatch assertions before changing parser behavior. |
| H3: authorization role/body/method gaps | Open; read-only/password-change sessions, valid mutation bodies, wrong methods and integration-only mode. |
| M1: HTTP tier lacks measurements and lock audit | Open. |
| M2: Python coverage allowance can be reused | Open; baseline tightening and missing-exit identities. |
| M3: dynamic JS function denominator | Open; static function inventory. |
| M4: forbidden version spellings and mutable images | Open; parse normalized releases and image declarations without acquiring artifacts. |
| M5: Docker COPY/WORKDIR and unparsed validation commands | Open. |
| M6: secret scanning, shipped SAST scope and inventory completeness | Open. |
| M7: setup/timeout telemetry, timing overhead and stress/flake semantics | Open. |
| M8: forced interleavings and richer generated models | Open. |
| M9: WAL goldens, unaffected-table invariants, richer restore/crash cases | Open. |
| L1: non-ASCII Content-Length digits | Open; address with H2. |
| L2: artifact retention | Open. |
| L3: bootstrap pins and advisory environment | Open; exact tool archives/action commits need qualification. |
| L4: smaller measurement/SAST/decoder gaps | Open; retain individual subitems from the source report. |
