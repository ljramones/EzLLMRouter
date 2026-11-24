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
| T03 | Docker image builds and deployment checks | Implemented for the pinned local Linux ARM64 Debian 13 profile: all six runtime-Python/receiver/worker/service/Python/JavaScript images build offline; a disposable target checks startup, actual isolation and credential permissions, installed-client readback, four exact synthetic arrivals, ordinary restart, and restoration into separate volumes with encrypted canary recovery. Missing keys fail closed. Another 99 TLS/database/recovery cases ran in the actual service image in the November 23 qualification. The auxiliary JavaScript actor also builds offline. All seven images pass the subsequent filesystem component scan. Existing Dockerfile/staging inventories and negative controls remain blocking. Other architectures, physical power loss and production acceptance are separate. See the qualification and remediation records below. |
| T04 | Supply-chain, secret and static security scans | Audit tooling and exact target capture implemented; current release acceptance remains blocked by one newly published Zstandard finding. All 33 original blockers are resolved for the qualified Linux ARM64 profile. The fresh 343-entry inventory has 73 raw matches and 28 raw blockers: ten component dispositions, nine native backport fixes and eight expiring profile decisions leave CVE-2026-124851 open. The minimal PostgreSQL bundle removes unused Kerberos/LDAP and extra OpenSSL copies while retaining the worker proxy interface and all 117 hash-pinned wheels. All seven images pass native dependency inspection; six pass full disposable qualification and the seventh its SDK/policy smoke. Raw findings and rating vectors remain visible. Profile-specific decisions do not claim upstream fixes or qualify other deployments. See the November 24 record below. Persistent profile and production acceptance are unchanged. |
| T05 | HTTP/JSON/IPC fuzzing | Implemented for the declared generated corpus: authenticated operator/wire framing also traverses the real ingress relay; fragmented IPC boundaries and bounded provider compression cases reject truncation, trailing members and allocation bombs. All six client decoders consume 536 independent fixed-seed cases, including depth, Unicode, duplicate keys and numeric boundaries. These bounded campaigns do not establish exhaustive parser coverage. |
| T06 | Accounting/canonical/registry properties | Implemented for the declared generated models: independent canonical/digest/integer-decimal checks, accounting/campaign and model/principal histories now include grant activation/removal/scope intersections, model state, price publication/replay/stale writes, immutable schedules and historical costs. A bounded reducer simplifies commands, nested JSON, keys, strings and numeric values while preserving the first divergent invariant; invalid candidates cannot replace it. Larger state spaces remain outside this scope. |
| T07 | Forced concurrency and lock-scope detection | Implemented for the declared local synchronized suites: lock auditing adds blocking event/condition/future/join waits with positive controls for nonblocking/completed operations and conditions releasing their own gate. Explicit fixture checkpoints and thread-start infrastructure have narrow exceptions. Three seeded HTTP/TLS stress rounds cover shared revocation/cancellation with exact delivery counts alongside existing races; the nine-suite runner remains scheduled for longer runs. Arbitrary native mutex/file/CPU work and deployment load qualification remain separate. |
| T08 | Process crashes, storage faults and coherent restore | Implemented for the declared local process-crash/fault scope: 49 named SIGKILL checkpoints cover work/usage, encrypted-file publication, migrations, backup/WAL, real signed-plan issuance and durable intent references, first HTTP request bytes, reply publication and integration/connector database-key rotation. Reopen/retry preserves identities, history, unknown outcomes and single-attempt accounting; rotation rolls back atomically and resumes without another key. Coherent restore and SQLite full/busy/I/O faults remain covered. Physical power loss and interruption inside kernel I/O still require target qualification. |
| T09 | Per-schema upgrade fixtures | Implemented for v001–v003 and keyring format v1: WAL fixtures populate all 53 application tables and all JSON expression indexes. Independent migration allowlists protect unrelated data even after golden regeneration. Checksums, exact rows, accounting, content digests and inventory anchors survive upgrade/restart and failed-upgrade retry. Unsupported schemas/key formats and unqualified new resources fail closed. No private or binary databases are tracked. |
| T10 | Provider/client resilience matrix | Implemented for the declared matrix: all six owned HTTP/TLS clients consume the same 28 cases and assert public error/recovery/status policy, exact delivery counts, byte limits, deadlines, no redirect/replay and rejection of untrusted TLS before HTTP credentials arrive. Existing 144 protocol/accounting cases and critical first-write tests remain separate maintained dimensions. Live-provider and exhaustive cross-product qualification remain outside this scope. |
| T11 | Abuse rates and resource limits | Implemented for the documented local limits: an executable inventory links all twelve runtime-resource rows and six additional security/API groups to registered regressions. Real boundaries cover execution/connection admission, login rates and pending work, hashed bucket bounds, session eviction/admin reservation, 4,096 tokens, report readers/SQL deadline, IPC/body/response sizes and diagnostic rollover. Production load and container timing qualification remain separate. |
| T12 | Logs and canary-secret contracts | Implemented for the current logging contract: all 66 operator and 42 wire bindings have route/level/schema/canary checks across nine statuses; 42 family action cases verify literal positions. Dynamic IDs matching route words remain redacted. Tests distinguish INFO rejections from sanitized ERROR stacks and verify the copied worker logger without trusted server imports. Production log collection is outside this source contract. |
| T13 | Front-end payload contracts | Implemented for the declared main-screen consumer fields: a navigation census covers all 13 administrative screens and 15 real response families. Independently stated nested field/type contracts preserve nullable destinations, explicit unknown costs and decimal strings. Required-field removal, type changes and decimal coercion have negative controls; unknown response families fail the census. Additional resource states and every optional field remain outside this finite contract. |
| T14 | Released-client version skew | Awaiting inputs. Identify hash-pinned previous released packages and previous-server vectors; never substitute current packages and call that N-1 testing. |
| T15 | Supported platform matrix | Implemented in CI: macOS service regressions and macOS/Windows current-client consumers join existing Linux jobs. The portable runner builds wheels, npm/JAR/NuGet/crate packages and a fresh Go module, checks Unicode/space paths, shared contracts/decoders and owned HTTP/TLS behavior. Python dependencies come from the locked development environment; Go uses an explicit local module replacement. Windows service support, released-package skew and deployment qualification are not claimed. |
| T16 | Performance and soak | Implemented for the synthetic operator baseline/soak scope. The manual/nightly runner measures fixed 1k/10k additional-attempt ledgers and a five-minute, two-client HTTP soak with report/export parity, exact decimal totals, concurrent WAL writes and metadata-only connector polling. Fresh subprocesses retain source/input hashes, nearest-rank latency percentiles, CPU, RSS high-water marks, sampled heap, threads/descriptors and writer progress. Correctness, timeout and cleanup failures block; initial timing and resource-growth results are observational. Existing bounded report-memory regressions remain. Production SLOs, calibrated long-term growth budgets and deployed/provider load qualification remain separate. |
| T17 | Accessibility | Implemented for the declared browser journeys: pinned axe 4.11.0 audits all 13 main screens, six accounting sections, sign-in/password/error states, ordinary/read-only navigation and the user form. A 200% CSS-zoom/reduced-motion keyboard journey checks form entry and cancellation; an unlabeled-input canary proves the auditor detects defects. Automated checks do not establish full WCAG conformance or replace assistive-technology review. |
| T18 | Mutation testing | Implemented for seven declared critical decisions: source-pinned isolated mutations target grant removal, operation replay payloads, published price identity, login backoff, abandoned first writes, queue capacity and route-ID redaction. Passing baselines and imported-copy identities are required. Killed, survived, invalid and timeout outcomes are recorded separately; survivors/invalid/timeouts fail a dedicated CI job. Real subprocess controls verify all four outcomes and cleanup. This finite gate is not an exhaustive mutation score. |
| T19 | Time/locale/timezone boundaries | Implemented for the declared source boundaries: existing expiry/deadline/backoff cases now join six browser locale/timezone cases, UTC date filters across DST, exact cost display, local expiry conversion and rejection of nonexistent/ambiguous times (including half-hour changes and a skipped day). Scheduler ticks reject wall-clock dependencies and missed-interval replay after suspension. Deployment clock behavior remains a target qualification task. |
| T20 | Executable documentation | Implemented for the two marked Python/JS accounting-v2 README examples. CI extracts their actual code fences verbatim, supplies synthetic inputs and exercises real authenticated HTTP handlers, SQLite event/receipt recovery and snapshots. Missing, duplicate, empty or retagged examples fail; one observation remains one unknown-cost attempt with no controlled execution. Other documentation examples and deployment/install commands retain their own checks. |

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

## Deployment qualification and package audit, 2026-11-22

Runtime source `cafe28971f6d5472488b1d2ee3f9ae83d21de2d2` passed on Docker
29.9.2 / Linux ARM64, using the existing digest-pinned Python 3.12.15 and Node
24.22.1 images. All 117 frozen worker wheels matched their recorded bytes and
SHA-256 values and passed archive startup-hook inspection. That run used LiteLLM
1.105.1 with its existing reviewed hash; no frozen dependency was reacquired or
updated. The runtime fingerprint is
`7bd382b57bad85e8dd14d380d015bf37dcf0a934fc1af5dc1b69bc63a2094118`.

Actual builds exposed and fixed a missing staged `tools.gateway.paths` module,
an obsolete worker IPC probe import, and the frozen SDK's
`x-stainless-raw-response` metadata field. The trusted sender accepts that known
metadata and strips it before forwarding, with a regression checking the final
request. Unreviewed headers and replayed attempts remain rejected.

The disposable runner builds five images without build-network access and uses
fresh generated credentials, project names and volumes. It checks read-only
roots, UID/GID 10001, dropped capabilities, no-new-privileges, network-disabled
workers, read-only sender sockets, console-only ingress and credential modes.
Four synthetic submissions, including a tool continuation and no-store work,
match four independent receiver arrivals. Ordinary restart adds no requests.
Cold copies of the service, credentials and receiver volumes restore into a
separate project, preserving those records and decrypting a provider-vault
canary. A missing provider key fails closed without creating a replacement.
Python/JavaScript packages also perform authenticated metadata readbacks with no
additional provider requests. Temporary secrets and backup bytes stay outside
the evidence export; cleanup removes only the runner's own resources.

Private evidence is under ignored `.artifacts/release-qualification/`:
`target-cafe289-final/qualification.json` records the final harness and target;
`target-cafe289/qualification.json` and `image-audit-final/images.json` bind the
five initially qualified images to their immutable IDs. The latter audit retains
`inventory.json`, `sbom.cdx.json`, complete `osv.json` pages and `findings.json`.
Its 521 package/version entries combine declared inputs, the resolved Rust graph,
and actual installed Debian/Python/npm packages. This inventory does not inspect
the internals of bundled Python/Node runtime binaries or establish exhaustive
vulnerability detection. Go, Java and .NET runtime manifests declare no external
package closure; their existing installed-consumer checks remain separate.

The advisory check at `2026-11-22T22:55:14.209032+00:00` failed its release gate.
Named findings in that combined inventory include certifi `2026.7.22`
(`GHSA-6q48-6c7w-9gw2`, compromised intermediate CA trust), dnspython `2.9.0`
(`GHSA-vvf4-9x63-8xvv`), filelock `3.32.7` (`GHSA-v4x8-3wr5-3wq8`), oauthlib
`4.0.0` (`GHSA-3jp2-3mrg-2vxc`), and unmaintained chrono `0.4.42`
(`RUSTSEC-2026-0543`). Correction: certifi `2026.7.22` was confined to the older
client-parity lock/consumer recipes; the qualified images already contained fixed
`2026.10.19`. The original 226 matches/194 blockers describe the combined declared
and installed inventory, not runtime-only findings. Installed OS packages and
build/package tooling add other matches. The synthetic profile uses a local HTTP receiver and its worker has no
network; that does not waive these findings for release or other deployments.
Review affected interfaces and distribution backports, then prepare reviewed
replacement inputs under the repository's release authorization rule. No
advisory exception or production approval was added.

T14 still needs genuine hash-pinned previous releases and previous-server
vectors. GitHub has no tags or releases, and retained development SDK archives
are not released-version evidence. T16 performance/soak remains the next separate
implementation batch after the release-input findings are addressed.

## Release-input remediation, 2026-11-22

Runtime source `4933eea5b59d33a858930725be462b7198330ff0` passed actual offline
Linux ARM64 qualification with Python 3.12.16 and Node 24.22.3, both pinned by
immutable image digest. All six images built, including the Python helper base
without pip/ensurepip. The runtime fingerprint is
`a1aca10adf937e124d723d91c13db80266b794feb8739ab7c64ceb23fc519139`.
The same startup, isolation, credential-mode, installed-client, four-arrival,
restart and separate-volume encrypted-restore checks described above passed.
Every Python runtime lacks pip/ensurepip; the JavaScript consumer lacks global
npm/corepack/yarn. The disposable projects and volumes were cleaned up.

The 117-wheel closure now selects eight reviewed replacements: dnspython 2.9.2,
filelock 4.2.1, oauthlib 4.0.1, LiteLLM 1.106.12, boto3/botocore 1.43.117,
litellm-enterprise 0.1.76.post1 and litellm-proxy-extras 0.4.108. The selected
`litellm-1.106.12-cp310-abi3-manylinux_2_28_aarch64.whl` SHA-256 is
`3baf90eecb4bd63a23eecc474c3ebb7dbcbe4243d459480d96d47805a46cdbda`.
A separate custody-verified store preserves the old inputs. The first candidate
failed actual installation because LiteLLM 1.105.1 requires filelock `<4`; its
failure remains retained. Complete METADATA dependency/extras/Python checks now
reject that incompatible closure before building. No requirement was overridden.

Review on 2026-11-22 (America/Toronto) covered the publisher's
[current incident notice](https://docs.litellm.ai/blog/security-incident-oct-21-2026),
[canonical investigation](https://docs.litellm.ai/blog/security-incident-oct-21-2026-attack-chain),
[1.106.12 release notes](https://github.com/BerriAI/litellm/releases/tag/v1.106.12),
[GitHub advisories](https://github.com/BerriAI/litellm/security/advisories), PyPI
metadata/yanked status and exact published artifacts. The selected maintenance
branch includes the backports for GHSA-2rwg-2wh4-7c4f (1.106.9),
GHSA-w4c7-34wj-hqm8 (1.106.5) and GHSA-4xm2-x5g5-wc8q (1.106.12).
These concern Azure credential overrides, an enterprise file route and key-info
metadata respectively; the synthetic OpenAI receiver profile does not expose
those interfaces. Broader production/provider qualification is not established.
The forbidden 1.107.0 artifact was never acquired, installed or executed.

The selected LiteLLM PyPI attestation subject matches its filename/hash and the
expected `BerriAI/project-releaser` publisher workflow. Independent Sigstore
transparency-log verification was not performed. The four necessary companion
updates have no published PyPI attestations; their exact PyPI archive hashes,
metadata, dependency relationships and contents were inspected. All 117 selected
wheels passed byte/hash and startup-hook inspection before installation; absence
of startup hooks alone does not establish that an artifact is clean. These
provenance limits remain open, with no production approval implied.

The exact-image audit at `2026-11-23T00:33:55.495382+00:00` retains 359 combined
package/version entries, 164 advisory matches and 163 blockers. All blockers are
unrated Debian advisories; the remaining application match is moderate
`GHSA-mf5v-w3w3-f6cg` in opentelemetry-api 1.45.1. Per-image attribution retains
110 matches for JavaScript, 163 each for the Python consumer, receiver, helper
base and service, and 164 for the worker. Those overlapping counts must not be
summed. Declared-only inputs have no matches in this snapshot. Node's embedded
undici 7.30.2 is included. Other bundled binary internals are not exhaustively
audited. Upstream build/helper base images retain installer findings in their
separate pre-stripping inventory. Advisory counts changed with inventory scope
and package removal; the difference is not a count of proven fixed exploits.
Debian urgency is not a severity waiver. Distribution backport/applicability
review and any required patches remain release-blocking.

Private evidence is under ignored `.artifacts/release-remediation/`:
`target-compatible/qualification.json`, `image-audit/{images,inventory,sbom.cdx,osv,findings,attribution}.json`,
the upstream review snapshots and `frozen-store-final/ARTIFACT-CUSTODY.json`.
Runtime source CI run `45088613239` passed all 14 jobs, including Linux, macOS and
Windows packaged consumers. The uninstrumented local pass ran 1,446 Python test
executions across 207 modules, with no skips or unstable results and an
11.79-second slowest module against the 30-second budget. Both legacy Python
consumer images also built offline and passed their installed-client regressions
with certifi 2026.10.19 and no pip/ensurepip; their complete historical runner
wrappers were not qualified. Offline and HTTP quality/coverage gates passed:
90.28% offline, 78.37% HTTP, 92.78% combined, with no coverage-budget increase.
The source Docker inventory covers 18 Dockerfiles. Removing chrono preserves the
wire timestamp rules with explicit Gregorian boundary checks and leaves 148
external Rust packages in the tracked locked graph. T14 still needs genuine
previous releases and vectors; T16 remains a separate batch. The persistent
profile, original artifact store and production acceptance were not changed.

## Synthetic operator performance runner, 2026-11-23

`tools.performance_suite` adds separate scale and soak subprocesses around real
reporting and authenticated operator HTTP paths. Fixed seeds generate public
synthetic attempt/model/cost distributions; an independent integer-cent oracle
checks exact decimal conservation against the ten-case accounting fixture.
HTTP JSON/CSV exports preserve the selected page, repeated navigation makes no
model work, and a real loopback metadata endpoint observes only availability
GETs. A bounded writer appends usage revisions without changing known costs.
Final table counts must account for every acknowledged write and retain attempt,
intent and guard-dispatch counts.

Scale latency samples run without coverage, lock auditing or tracemalloc; report
allocation peak is measured in a separate call. Soak latency explicitly includes
tracemalloc overhead, with periodic heap/thread/descriptor/CPU/RSS samples and
bounded percentile buffers. RSS is a process high-water mark, not current memory.
Zero leaked threads/descriptors, export/accounting mismatches, duplicate probes,
unexpected requests, stopped writers, failed children and timeouts fail the run.
Initial timing and long-term heap/RSS growth budgets remain observational.

The parent owns temporary SQLite/key/credential storage and removes it even when
a worker times out. Evidence exports counters, measurements and public source
identities; no database or generated secret is exported. Source hashes and
commit/dirty state must remain unchanged between phases. An early supervised
attempt failed at the network-guard adapter; a regression now exercises that
adapter. Another preliminary run changed source while executing and is explicitly
invalidated, with its original output preserved. Default output retention bounds
successful and failed runs; explicit output paths must be fresh.

The separate scheduled/manual workflow uses existing reviewed action/bootstrap
pins, Python 3.12.15, 1,000/10,000 added attempts, seven samples, two clients and a
300-second soak. These are synthetic local HTTP observations, with fresh
connections per request, rather than browser-rendering, live-provider, production
capacity or physical-storage qualification. Application code, frozen runtime
inputs, the persistent profile and production acceptance are unchanged.

The real HTTP smoke additionally covers 72 previously allowed lines and 41
conditional exits across five unchanged application modules. Only the HTTP
allowances shrink; its measured coverage is 78.85%, with 92.81% combined coverage.
The first CI pass also exposed a socket-pair ingress fixture that closed unread
request data without the server's normal write shutdown. The fixture now mirrors
`TCPServer.shutdown_request` before closing both peers. The old fixture fails the
new shutdown assertion; the corrected four-case suite passes 20 fresh-process
runs. Malformed requests still reject and cannot dispatch a following request.
The performance measurements remain bound to `b3888fc`; this follow-up changes
fixture teardown and coverage metadata, with performance source/input hashes
unchanged.

## Final seven profile findings and fresh advisories, 2026-11-24

All **33 original blockers are resolved for the exact qualified Linux ARM64
profile**. The remaining seven glibc/tar cases have expiring, executable
`not_affected` decisions tied to that profile; their upstream packages are not
claimed fixed. The fresh November 24 scan also adds two findings. The new QUIC
case, CVE-2026-84785, requires acceptance of incoming QUIC streams, absent from
the reviewed application dependency closure and interfaces. The new Zstandard
case, **CVE-2026-124851, remains blocking**. Release acceptance therefore still
has **one effective blocker**. The persistent profile and production acceptance
remain unchanged.

The current 343-entry inventory has 73 raw matches and 28 raw blockers. Ten exact
component dispositions, nine native backport fixes and eight qualified-profile
decisions leave that one blocker. Raw severity and source attribution remain in
the complete advisory report. Three util-linux advisory timestamps changed;
their complete content excluding `modified` was identical. Two OpenSSL records
changed only modification time and other Debian suites: their full Debian:13
records and all other fields were identical. Explicit, patch-bound revalidation
accepts those exact updates without changing native artifacts or weakening
checks for changed target exposure. The new findings remain separately recorded.

The native inspection found bundled Kerberos glob/regex callers and additional
OpenSSL libraries inside psycopg-binary, missed by the prior three-copy review.
The [minimal driver bundle](../deploy/local/inputs/native/README.md#minimal-postgresql-native-bundle)
relinks the published extension objects to exact-version libpq 18.6 without
GSSAPI/LDAP, using the already patched shared OpenSSL. All 210 libpq exports
remain. Sixteen old bundled libraries are removed and one minimal libpq is
provided. The worker retains its LiteLLM proxy ASGI interface; all 117 frozen
wheel selections remain dependency-compatible, with 116 exact wheel files
unchanged from the preceding batch, including LiteLLM 1.106.12.

Across all seven new images, **3,800 ELF objects** are parsed without execution.
Application dependency closures have no affected glob/regex or incoming-QUIC
callers; optional tkinter extensions with unavailable Tcl/Tk dependencies remain
explicitly recorded as unloadable. Ambiguous dependencies and malformed or
unordered load segments fail. Native diagnostics verify the AArch64 global
read-only guard outside thread stacks, C.UTF-8 and non-root/no-new-privileges
execution. Complete owned-source and qualification identities bind these checks;
changed callers, code, images, advisories, runtime controls or expired reviews
retain blocking status. A bounded setuid diagnostic elevates only in its isolated
unprotected control; the required kernel flag prevents elevation. The canary
image is removed. The archive helper separately rejects privileged modes and
links before restoration.

All six offline builds and disposable isolation/client/restart/restore checks
pass, plus the auxiliary JavaScript SDK/policy smoke. The source gate passes
1,337 cases across 182 modules without skips; subsequent native/advisory gate
regressions also pass. All 99 native TLS/database/recovery cases pass in the
exact new service image. Private source caches, complete fresh advisory response,
initial failed attempts, current decisions and validation records remain under
ignored `.artifacts/final-seven/`.

The qualified runtime source is `fc522afe280fc2df5c64709fffc71ecb65765abf`,
fingerprint `97ad943182638a62f848d0131d00fa46b60f293fbe255c5e9bd9b2cf3a1962b4`.
The source packet SHA-256 is
`1d18eb8853e60c285999a0c02a6a70a07d82ed5a5ff7b48b2c77713deb8c0185`.
Subsequent advisory/tooling records preserve those runtime source/input bytes.

The next dependency work is the new Zstandard disclosure, including both the
retained system library and Node's embedded copy. No reviewed replacement or
backport is selected by this record. This open case prevents a claim of zero
current blockers.

## OpenSSL native backports, 2026-11-23

Before the final-seven review, the audit had **7 effective blockers, down from the original 33**.
This batch fixes all nine retained OpenSSL cases across the system library,
Node and cryptography copies. The earlier seven published archive fixes and
ten verified component dispositions remain in effect. The six glibc cases and
one tar case still block release acceptance; the persistent profile and
production acceptance are unchanged.

The [native input guide](../deploy/local/inputs/native/README.md) describes the
v4 source/output custody record. OpenSSL 3.5.9-1~deb13u1+ezllmrouter1 backports
eight merged maintenance fixes and the complete locally reviewed DANE fix/test
from still-open upstream PR 33634. Node remains 24.22.3, rebuilt from its
signature-verified source with shared SSL. Cryptography 50.0.2+ezllmrouter1 also
links the patched shared library. Its honest Linux ARM64 wheel replaces one of
117 frozen inputs; the other 116 wheel files, including LiteLLM 1.106.12, retain
their exact hashes. Neither local version labels nor the Node rebuild conceal
the upstream advisory ranges.

The complete raw advisory report retains 26 blockers. Ten exact component
dispositions and nine artifact-bound native fixes leave seven effective blockers.
The native review validates all seven images, the thirteen selected archives,
every applicable code hash and actual runtime versions. Standard-library Python
images additionally prove that both the cryptography module and its native object
are absent. Changed advisories, copies, source identities or incomplete proof
retain blocking status. An initial audit stopped at that absence distinction;
completion reused its complete fresh advisory response only after verifying that
all source input hashes remained identical.

The qualified runtime source is
`780538e296a1b5014990f226de0cecd5567cff15`, fingerprint
`1c969776d3da71047df0c6caaea9ef5d85954dc1c5765213a3513b97f78cfd23`.
Its source packet SHA-256 is
`65f1f2edabacdf6151ff56f8b6a5243e6a8e2259e1aecb5ab4a0440378d36dc3`.
Later inventory/review tooling commits preserve those runtime source bytes.

Validation includes 13 OpenSSL regression recipes/601 tests; all six offline
image builds and disposable startup/isolation/installed-client/restart/restore
checks; the seventh JavaScript image's SDK/policy smoke; and 99 native
TLS/database/recovery tests in the exact new service image, without skips.
Both shared libraries retain all 6,477 public exports and symbol versions.
Node and cryptography declare shared SSL/crypto dependencies without builder
search paths. Both Node images preserve the exact prior bundled CA trust set
and pass authenticated-encryption and signature smoke checks. Before/after SIV
controls reproduce invalid-nonce acceptance and empty-AAD loss in the previous
library and reject those behaviors in the patched build. The source gate passed
1,324 cases across 179 modules with no skips; the subsequent image-absence case
and its related regression suite also pass. Evidence, initial failed attempts and
the final validation manifest remain under ignored `.artifacts/openssl-remediation/`.

## Library upgrades and component closure, 2026-11-23

Before the native backport batch, the audit had **16 effective blockers, down from 33**. The complete
342-entry inventory produces 71 raw matches: 23 high, one critical, two unrated,
38 moderate and seven low. Of the 26 raw blockers, ten have exact component
dispositions. The raw report, rating vectors and severity classifications remain
unchanged by those dispositions. Release acceptance remains blocked.

| Resolution | Original blockers resolved |
| --- | ---: |
| Published SQLite, ACL and GCC archive fixes | 7 |
| Verified absent components in exact retained archives/images | 10 |
| Still open: OpenSSL (9), glibc (6), tar (1) | 16 |

The v3 OS lock retains the pinned Debian 13 bases and seven stable archives,
adding six authenticated Forky ARM64 archives. SQLite 3.54.1-2 fixes the three
FTS5/session cases; ACL 2.4.0-1 fixes both library and utility cases; GCC 14 base
14.4.0-4 and the GCC 16 base/libgcc/libstdc++ closure at 16.2.0-4 fix the two GCC
source-package cases. Dependencies fit the retained glibc 2.41. Exact reviewed
Forky binary/source versions use Debian:14 advisory attribution; all other
installed packages retain Debian:13. Source mismatches, unknown suites and
missing authenticated origin metadata fail. One earlier ACL component
disposition is now covered by an archive fix and is counted only once.

Ten active component dispositions cover four util-linux paths, attr utilities,
infocmp, two Perl modules, the SQLite shell and its ZIP extension. The review
catalog retains the historical ACL case for exact older images. SQLite's
`.recover` command and ZIP virtual-table implementation are outside the retained
libsqlite3-0 archive. All seven images pass exact library/alias code checks and
the stronger file census. Non-executable ZIP shared objects and aliases are
checked as code. Declared OS-lock sources additionally require the complete
archive set, verified against the audited inventory and lock hash with
`--os-store`; image proofs alone leave those sources blocked. Other bundled
copies and unreviewed native interfaces receive no exemption.

Runtime source `e234d982efab23e5e3b7a7705e6509a99c2766d4`, fingerprint
`713414a94de45362f0a406f4721c8ba1777b6444720da9bdd19c81e274a38eab`,
passes clean, offline, disposable qualification across six images: startup,
worker isolation, synthetic final requests, installed clients, restart,
backup/restore and cleanup. A seventh auxiliary JavaScript image passes its
installed-SDK and runtime-policy smoke checks. The final service image also
passes all 99 selected database/recovery/encryption/TLS tests, with no skips,
using a test archive from that exact source commit.

ELF inspection preserves every old libacl, libgcc and libstdc++ export and symbol
version. SQLite preserves its public `sqlite3_` API; seven removed internal
implementation symbols remain recorded as an explicit limit. A bounded GCC
allocation smoke passes on both old and new libraries and is not used as proof
of patch sensitivity. Three harmless disposable image canaries reintroduce the
SQLite shell, a non-executable ZIP module or a module symlink: the previous gate
accepts all three, and the new gate rejects all three. Only those fresh labelled
canary images are removed.

The maintained local quality runner passes 1,312 Python executions across 177
modules with no skips, alongside its JavaScript/contract and source checks.
Regressions cover declared-archive inventory binding, changed hashes,
unreviewed extra binaries, incomplete image/extension coverage and component
reintroduction. Source-security checks retain 1,019 exact reviewed SAST
identities. A secret-scan exception binds only the unchanged public artifact
directory token in the updated OS guide. Complete raw/reviewed audits, signed
indexes, archive inspection, source packets, native/ABI/canary results,
test-health data and CI results belong under ignored
`.artifacts/dependency-resolution/`; `VALIDATION.json` binds the final evidence.
The 117 frozen wheels, persistent profile and production acceptance are
unchanged. No custom SQLite build or OpenSSL backport is adopted.

OpenSSL still needs maintained-branch fixes or reviewed published replacements,
including a separate assessment of cryptography's embedded OpenSSL 4.0.3.
Eight system-OpenSSL fixes are available on maintained upstream branches; the
DANE fix is still under review. The six glibc cases and tar case remain visible;
current stable/backports metadata provides no replacement that clears them.
No no-DSA label, disputed CVE status or locale setting is treated as a waiver.

## Dependency-resolution review, 2026-11-23

A fresh complete OSV query reproduces 341 inventory entries, 86 matches and
33 raw blockers. Artifact-bound component reviews now resolve nine of those
matches across all seven immutable images, leaving **24 effective blockers**.
Raw ratings and findings remain intact. This supersedes the earlier named-file
observations below; it adds binary artifact/code verification and explicit
per-advisory dispositions rather than changing that historical evidence.

APT-authenticated stable indexes select seven retained component archives.
All seven archive hashes/sizes are verified; the catalog binds 92 code paths,
including library/executable aliases, to their actual image bytes. Every image
also passes the complete regular-file/symlink census. The nine cases concern
four util-linux mount/nsenter paths, ACL and attr utilities, infocmp, Pod::Text
and Archive::Tar. The distinct libacl pathname API finding stays blocked.
Changed advisory contents, binary/source versions, code hashes, architecture,
component coverage or image attribution invalidate a disposition. Every source
must pass, and reviews expire after at most seven days. Other bundled copies
and unreviewed native interfaces receive no exemption.

The remaining 24 matches cover OpenSSL (nine), glibc (six), SQLite (five), GCC
(two), libacl (one) and tar (one). Signed stable and backports metadata offer no
newer versions for these packages. Maintained OpenSSL branches contain fixes
for eight of the nine cases; the DANE fix is still under upstream review.
The embedded OpenSSL 4.0.3 in cryptography remains a separate native copy
and cannot be repaired by replacing the system OpenSSL alone.

An offline ARM64 SQLite 3.54.1 source-build prototype uses the publisher's
archive SHA-256 and amalgamation SHA3-256. A derived service image passes all
99 selected database, recovery, encryption and TLS cases with no skips. This
prototype is not adopted into the OS lock or counted as a resolved finding.
Signed Debian testing metadata also identifies published SQLite, ACL and GCC
candidates; their compatibility and exact source attribution require separate
qualification before adoption.

Six new regression cases exercise partial-image review, changed advisory/code,
extra binaries, component reintroduction, source/architecture/version changes,
unsafe paths and review expiry. The maintained offline quality runner passes 1,305 Python executions across
177 modules with no skips;
SAST reviews two fixed, network-disabled Docker inspection calls, retaining
1,019 exact source/finding identities. Evidence is under ignored
`.artifacts/dependency-resolution/`, including signed indexes and metadata,
archive/code manifests, complete raw and reviewed audits, per-image proofs,
native candidate build/test logs and test-health results. Runtime source remains
`cbbc5a9`; the persistent profile, 117 frozen wheels and production acceptance
are unchanged.

## Runtime component inventory, 2026-11-23

The qualification footprint check previously searched only `/usr/bin` and
`/usr/sbin`. It now inventories every regular file and symbolic link on the image
filesystem, including copied tools outside those directories. NUL-delimited
records include type, octal mode and absolute path. Empty, missing-control,
unterminated, duplicate, malformed, noncanonical and oversized censuses fail.
The report binds a canonical metadata hash and the exact executable/module
selectors to each immutable image identity.

The guard rejects the removed executable names plus getfacl/setfacl/chacl,
getfattr/setfattr and unpacked Pod::Text/Archive::Tar source or compiled modules.
It also rejects symlink aliases for the reviewed Perl module directories.
An initial basename-only scan rejected account data and unrelated Debconf
Text.pm files; mode and module-path checks preserve those legitimate files.
Regressions cover alternate directories, file and symlink canaries, non-executable
modules, malformed metadata and stable order-independent evidence hashes.
Three new regression cases failed against the original gate.

Three actual disposable images separately add a harmless copied nsenter, a
symlink to an existing harmless executable, or an unpacked Pod::Text module.
The previous committed gate accepts all three; the new gate rejects all three.
Canary contents are never executed, and the check removes only its freshly
created, owner-labelled images. All seven existing audited runtime images pass
the stronger gate, covering 3,400 to 25,732 regular files/links per image.
Their runtime source remains `cbbc5a9`; no image, base, OS archive, frozen wheel,
application source or runtime configuration changes in this batch.

Review replays the complete, image/inventory-bound OSV snapshot from
`2026-11-23T15:52:51.454906+00:00`; it does not claim a new feed query.
Nine cases have absent named components across all seven images: four util-linux
mount/nsenter cases, the ACL command-line case, the attr command-line case,
infocmp and the two Perl modules. These 63 observations do not establish absence
of renamed, archived or statically embedded code. Retained libacl pathname APIs
still require separate investigation; removing getfacl/setfacl/chacl does not
resolve CVE-2026-54369. All nine reviewed cases retain their blocking status.
The raw gate remains failed with 86 matches and 33 blockers across ten source
packages. No advisory waiver or library version change is added.

Local regression, source-security, typing and duration checks pass 1,481 Python
executions across 212 modules with no skips or unstable outcomes. The slowest
module takes 11.81 seconds against the 30-second budget. SAST retains the existing
1,014 reviewed identities, secret scanning needs no new exceptions, and all 22
local links in the three edited guides resolve.

Ignored `.artifacts/component-review/` retains the original negative run,
the initial/refined scan results, per-image file metadata and command exits,
`component-scan.json`, actual canary build/check logs, `canary-results.json`,
`component-interface-review.json` and the validation manifest. The earlier
startup/isolation, synthetic-request, restart/restore and native-library results
remain bound to their original runtime source and image IDs; those suites were
not repeated for this qualification-tool change. The persistent profile,
production acceptance and other deployment limits are unchanged.

## Runtime tool removal and locale policy, 2026-11-23

Runtime source `cbbc5a9afa04c451c2ed5105bfcdda1ab2185074` passed disposable Linux
ARM64 qualification with fingerprint
`d0e9df949f473ff1bdb1f501cae30c8809145b211809d43d474b56c1368a6b0a`;
its source packet SHA-256 is
`0847aef9ad6793b1be5ac66c62bd80f1d43b6ad0333f53c6c38516b796a66201`.
The immutable bases, seven Debian archive identities and 117 frozen worker wheels
are unchanged. The OS lock becomes v2 to seal the package-removal policy and the
updated installer; its SHA-256 is
`b751cf4c68add8b37a046f0eff4da09c0229375fd00e9db938bcac004e8a3552`.

The runtime removes 19 additional unused login/password, PAM, mount/namespace and
terminal packages. The complete removal closure is 22 packages including the
previous APT tools. Dependency simulation first rejected removing tar because
dpkg requires it; both remain. The reviewed closure preserves every other installed
package, with before/after checks rejecting extra removals or added packages.
Python images now contain 65 installed OS packages; JavaScript images contain 57,
down from 84/76. The staged `REMOVE-PACKAGES` bytes and checksum are bound to the
lock and source packet. Protected libraries, duplicate/unsafe package arguments
and rehashed manifest tampering fail before Docker executes. The original
validator first failed five new policy-negative assertions.

Existing service/JavaScript images each contained 11 setuid/setgid files. All six
new qualified images and the separately built auxiliary JavaScript image have
none, and no selected removed command remains. Read-only inspection helpers use
directory-read authority solely in their disposable containers; application roles
retain their non-root, zero-capability and no-new-privileges configuration.
All image defaults and five live profile services enforce `LANG=LC_ALL=C.UTF-8`
and `LANGUAGE=C`. This constrains gettext's locale inputs for the declared profile;
it does not patch glibc or qualify arbitrary operator overrides.

ELF metadata inspection confirms Node requires libstdc++ and libgcc. Aligned-new
exports remain present in libstdc++; glob, regex and gettext symbols remain in
libc. Node, libstdc++ and libc bytes exactly match the previous qualified objects.
The inspection never executes the inspected ELF files or ldd, and removes its
temporary containers. Current Debian tracker evidence still records the selected
Trixie glibc/GCC findings as vulnerable; testing/unstable GCC fixes do not approve
replacement stable inputs. All eight reviewed glibc/GCC cases remain blocking.
Absence of compiler headers does not establish safety of prebuilt native callers
or inlined templates.

Default certificate bytes and all 148 trust anchors are unchanged. Native Python
imports and the Toronto timezone pass in the final service image. The reviewed
Pod::Text/Archive::Tar files are absent from perl-base's owned-file list; this
limited observation does not waive the retained Perl findings.

Local regression/security/duration gates pass 1,478 Python executions in 212 modules,
with no skips or unstable outcomes and an 11.68-second slowest module against the
30-second limit. Strict typing and the whole-library audit report zero debt;
1,014 source/finding-pinned SAST findings remain reviewed. Secret scanning required
one exact source-blob/finding exception for the public OS artifact-directory path
in the updated guide; detector rules are unchanged. Source validation resolves
all 18 Dockerfiles. Application source and coverage allowances are unchanged.
Six images pass offline builds, startup/isolation, installed-client readback,
four exact synthetic arrivals, restart and separate-volume encrypted restore.
Cleanup removes both owned projects/volumes. The auxiliary JavaScript actor passes
its offline build, installed-SDK identity and runtime-policy checks; its broader
actor flows remain separate. The actual service image passes 99 TLS, schema, WAL,
SIGKILL, backup, key-rotation, coherent-restore and SQLite-capability cases without
skips.

The seven-image audit at `2026-11-23T15:52:51.454906+00:00` retains 341 combined
package/version entries and 86 matches: 30 high, one critical, two unrated,
46 moderate and seven low. There are 33 blockers across ten source packages.
Each non-worker image has 85 OS matches and 33 blockers; the worker adds the
moderate application finding. Declared-only inputs have no matches. Four previous
PAM/shadow matches disappear, including three blockers. The fresh OSV snapshot
also adds high OpenSSL QUIC finding CVE-2026-107494, published by its CNA on
November 18. It remains blocking. No advisory was waived and no library version
changed; the package gate still fails.

Private evidence under ignored `.artifacts/runtime-tooling-review/` includes
the original/corrected dependency simulations, `trial-policy-validation.json`,
`baseline-setid.json`, retained policy failures, `health-final-fixed/summary.json`,
`target/qualification.json`, `auxiliary-js.json`, `native-libraries.log`,
`elf-metadata-qualified.json`, `retained-runtime-facts.json`,
`library-interface-review.json`, `advisory-difference.json`,
`remaining-review-queue.json` and `image-audit/`. The persistent profile, production
acceptance, physical-power-loss qualification, released-client N-1 availability
and T16 scope are unchanged.

## CVSS v4 and SQLite capability hardening, 2026-11-22

Runtime source `19528481bbdcffe7bb5dade155f07b9358f0e55e` adds defensive SQLite
connections and CVSS v4 base-score support. Its qualified fingerprint is
`b3674b754c53da9312f2229f609fa8fabe6d5a4a912d987df983a168b3b74e53`;
the source packet SHA-256 is
`ef3ecb3c1493a261be20b344a95ca5ac0ce9bf2320d25aca3ef8575a6368aca1`.
The worker's 117 frozen wheels and Debian OS inputs are unchanged.

The v4 scorer adapts FIRST's BSD-licensed reference implementation at commit
`c5b0d409ae9f57c44264c6ce5f27d89298e1d32a`. Reviewed normative tables retain their
source hashes and have an enforced byte hash. All 104,976 base-metric combinations
match FIRST's reference calculator, alongside published example goldens. The first
comparison retained 522 rounding differences from exact-rational arithmetic;
the corrected implementation preserves FIRST's floating operation order and
rounding. Full vectors enforce metric order, values, completeness and type/version
agreement. Optional metrics cannot reduce the base-score gate; malformed vectors,
unsupported versions and changed tables fail closed. Advisory lookup still uses
only the standard library, without new development or runtime dependencies.

The actual SQLite 3.46.1 image originally left defensive mode off and native
extension loading enabled. All five service-owned connection sites now enable
defensive mode and disable extension loading before SQL: normal/open-existing
stores, independent report snapshots and both backup connections. Failed settings
close connections and release ownership. The old implementation first failed
three negative assertions, including writable-schema tampering. A target gate
now rejects images with weakened settings; the actual service reports defensive
mode enabled and extension loading disabled. The installed helper hash matches
the committed source. The fresh schema has 53 application tables and no virtual
tables, plus SQLite/schema metadata entries.

Full local validation passes 1,476 Python executions in 212 modules with no skips
or unstable results and an 11.97-second slowest module against the 30-second limit.
Ruff, strict typing, zero whole-library typing debt, 1,014 reviewed SAST findings,
secret scanning and dependency preflight pass. Offline/HTTP/combined coverage is
90.32%/78.54%/92.81%, with all selected critical exits covered. Reviewed budgets
tighten by 42 line and 12 branch allowances across the two tiers; the new helper
has no missing lines. Existing SAST statements retain their reviewed identities.

Disposable Linux ARM64 qualification passes all six offline builds, installed
SQLite capability checks, isolation, installed-client reads, four exact synthetic
arrivals, restart and encrypted restore into separate volumes. Both owned projects
and volumes were removed. The actual service image additionally passes 99 TLS,
schema, WAL, SIGKILL, backup, key-rotation, coherent-restore and SQLite capability
cases with no skips, using read-only public source fixtures and disposable data.

The fresh exact-image audit at `2026-11-23T03:48:07.889337+00:00` retains all 89
matches: 31 high, one critical, three unrated, 46 moderate and eight low. There are
35 blocking Debian matches across 12 source packages. Each image has 88 OS matches
and 35 blockers; the worker also has the moderate application finding. Declared-only
inputs have no matches. Nine previously unrated matches become nonblocking with
v4 scoring; no advisory is waived and no library version changed. The gate fails.

All eight OpenSSL and five SQLite blocking cases retain individual prerequisite
notes. The service lacks the SQLite CLI and zipfile function/module, while FTS5
and session support are compiled in. Python's missing session API does not prove
native callers absent. Selected source uses ordinary TLS/HTTP and AESGCM, but the
cryptography wheel also exposes AESGCMSIV. OpenSSL's November 10/17 notices report
source fixes and schedule containing releases for December 1; no unpublished
replacement artifact is selected. These observations support further review,
without approving other providers or arbitrary externally supplied databases.

Private evidence is under ignored `.artifacts/cvss4-review/`: retained old-gate
and initial rounding failures, `comparison-final.json`,
`coverage-identity-review.json`, `health-final/summary.json`,
`target/qualification.json`, `runtime-validation-manifest-final.json`,
`native-libraries.log`, `runtime-interface-facts.json`, `interface-review.json`
and `image-audit/{images,inventory,sbom.cdx,osv,findings,attribution}.json`.
The persistent profile, production acceptance, physical-power-loss qualification,
released-client N-1 availability and T16 scope are unchanged.

## Advisory classification and disposable restore, 2026-11-22

Review found that the advisory gate retained CVSS vectors but ignored them when
the database supplied no named severity. The corrected standard-library scorer
validates CVSS v3.0/v3.1 metrics and computes the base score with exact arithmetic.
It retains raw vectors and database severity, adds effective severity and score
provenance, and chooses the highest usable rating. Temporal/environmental metrics
cannot lower the base score. Unsupported versions, malformed ratings and absent
ratings remain blocking. No dependency or frozen input changed.

Replaying the unchanged exact-image snapshot from `2026-11-23T01:46:52.923221+00:00`
keeps all 89 matches visible: 21 unrated, 22 high, one critical, 38 moderate and
seven low. All 44 blocking matches are Debian entries across 14 source packages.
The 21 unrated entries include 18 CVSS v4 ratings and three without a usable rating.
Of the 45 nonblocking entries, 44 are Debian and one is the previously recorded
moderate opentelemetry-api finding. Each image still has 88 OS matches; the worker
also has the application match. This corrects classification, without closing or
waiving any advisory or changing the selected package versions. The gate fails.
CVSS v4 support and the remaining package/interface reviews are subsequent work.

The qualification's cold-copy path also validated with Python and extracted with
GNU tar. It now uses one physical USTAR parser for validation and restore, with
bounded private spooling, complete hash verification before writes, explicit
directory ancestry and exclusive no-follow file creation. Links, special files,
PAX/GNU extensions, altered/truncated/trailing payloads and nonempty destinations
fail. Source traversal rejects links, special files and mutation during copying.
The helper resolves the already patched runtime image to its immutable ID; it no
longer uses the raw build base. Scope is the three disposable qualification volumes,
with a 128 MiB/16,384-member limit. Runtime application sources remain `64dd620`.

The old archive gate first failed two new negative assertions; the old advisory
gate separately failed the vector-classification regression. All 46 focused cases
pass after correction. All 2,592 CVSS v3 base-metric combinations agree with FIRST's
published v3.1 reference calculator, alongside published example goldens. The full
local offline gate passes 1,274 Python executions in 174 modules, no skips or
unstable outcomes, and an 11.40-second slowest module against the 30-second limit.
Ruff, mypy, type audit, 1,014 reviewed SAST findings, secret scanning, dependency
preflight and maintained JavaScript/script checks pass. Existing SAST statements
retain their identities except the two reviewed archive subprocess replacements.

Disposable Linux ARM64 qualification passes with the sealed `64dd620` source
packet and the updated, hash-recorded host harness. All six images pass offline
build/runtime checks; four exact synthetic requests, restart and separate-volume
encrypted restore/readback pass. Three restored archives contain 14, three and two
members respectively; no private archive is exported. Cleanup removes both owned
projects and volumes. The persistent profile and production acceptance are unchanged.
Private evidence under ignored `.artifacts/advisory-review/` includes
`classification-summary.json`, `findings.json`, `attribution.json`,
`cvss-exhaustive.json`, the retained old-gate failures, `full-check-fixed.log`,
`test-health-fixed/summary.json` and `target/qualification.json`. The earlier
[Debian record](#debian-os-remediation-2026-11-22) preserves the original audit's
unrated classification and the independent native-library qualification.

## Debian OS remediation, 2026-11-22

Runtime source `64dd620f361e6f0d2993b30bf9209ce0566bcf8a` passed disposable Linux
ARM64 qualification with digest-pinned Debian 13 (Trixie) bases and the existing
Python 3.12.16 and Node 24.22.3 runtimes. Its fingerprint is
`5bc89e3495ac43c83cc7a02526c49db048df22e25cc658296b5b16bedeec4e7e`;
the source packet SHA-256 is
`9b5fc455e1b841177007e586bd0ba1f5b76570cb37b7f78e2dfe84f813fe9b3f`.
All six images built offline and passed exact installed-OS-version and
APT/pip/npm-tooling checks, startup, isolation, credential permissions,
installed-client readback, four exact synthetic arrivals, restart and
separate-volume encrypted restore. Cleanup removed the disposable projects and
volumes. The auxiliary JavaScript actor independently built offline and passed
installed-client/version and tooling-absence checks.

The current Debian tracker showed the old Bookworm packages already at their
published versions, with no recorded fix for the matched entries. Review therefore
selected immutable official Trixie images, checked their published source
Dockerfiles, inspected stopped-container filesystems and audited their packages.
Those images still needed current glibc, OpenSSL and zlib updates. APT verified
Debian's signed InRelease and package indexes before downloading seven exact
archives; sizes, SHA-256 values, binary/source metadata, startup-hook names and
maintainer scripts were inspected before installation. The
[OS lock](../deploy/local/inputs/os/README.md) records this provenance and selects
base-files 13.8+deb13u8, glibc 2.41-12+deb13u5, OpenSSL 3.5.9-1~deb13u1 and
zlib 1:1.3.dfsg+really1.3.1-1+deb13u1. The Python closure uses seven archives;
Node uses six. The 117 worker wheels, their bytes and selected LiteLLM 1.106.12
input are unchanged by this transition.

Preparation verifies complete archive sets, sizes, hashes, links and installer
identity. Each build context records only its role's selected archives; builders
compare those bytes and metadata with the source packet before building an image.
The build-only script verifies the OS/architecture and archive hashes, installs
offline, checks package consistency and removes exactly apt, libapt-pkg7.0 and
sqv. Debian's essential-package protection first rejected that removal; the
retained corrected build explicitly permits the three named packages and uses a
before/after installed-package census to reject any additional removal. Dpkg
remains available for inventories. Existing cached older images can still be
reused; rebuilding requires preparing the reviewed OS inputs.

The actual service image also passed 95 TLS, compression, schema-upgrade, WAL,
SIGKILL recovery, backup, key-rotation and coherent-restore cases, with no skips.
They used read-only public source fixtures from the qualified commit and disposable
data. The first validation bundle omitted a deployment source file needed by one
source-inventory assertion; both that failed run and the complete corrected run
are retained. Observed libraries are system OpenSSL 3.5.9, SQLite 3.46.1 and the
frozen cryptography wheel's separate OpenSSL 4.0.3. Host quality gates passed
1,451 Python test executions across 208 modules, with no skips/unstable results
and an 11.78-second slowest module against the 30-second budget. Offline/HTTP/
combined coverage remains 90.28%/78.37%/92.78%, without increasing budgets.
The sparse source-identity unit fixture correction in `2cb0750` changes tests
only; the qualified runtime files remain those in `64dd620`.

The exact-image audit at `2026-11-23T01:46:52.923221+00:00` retained 345 combined
package/version entries and 89 matches. All 88 unrated Debian matches remain
blocking across 18 source packages; opentelemetry-api 1.45.1 retains one moderate
application finding. Each non-worker image has the same 88 OS matches; the worker
has those plus the moderate finding. Overlapping image counts must not be summed.
Declared-only inputs have no matches in this snapshot. The earlier Bookworm
snapshot had 163 OS matches, but the difference includes distribution/package
scope changes and is not a count of independently proven fixed exploits.

Current tracker reconciliation retains 85 open, two undetermined and one
source-disputed Debian match. For CVE-2026-39113, Debian marks the selected SQLite
release not affected (`fixed_version: 0`) while OSV still returns the match; the
actual runtime exposes no `sqlar_uncompress` function. Selected source uses
ordinary TLS/HTTP and AESGCM, without QUIC, DTLS, DANE, Suite-B flag or
AES-GCM-SIV interfaces. These observations narrow subsequent interface review;
they are not blanket advisory waivers or approval of other providers/configurations.
The raw gate remains failed. Upstream build images retain separate OS/tooling
findings, and bundled binary internals are not exhaustively audited. Physical
power loss, other deployment architectures and production acceptance remain open.

Private evidence is under ignored `.artifacts/debian-remediation/`:
`target-64dd620/qualification.json`, the signed metadata/archive review,
`image-audit/{images,inventory,sbom.cdx,osv,findings,attribution}.json`,
`native-libraries-final.log`, `runtime-validation-manifest-final.json`,
`auxiliary-js.json` and `interface-review.json`. Original failures remain beside
the corrected runs. `debian-review-queue-current.json` groups all 88 remaining
matches for the next review. The persistent profile, original input stores,
production acceptance, released-client N-1 availability and T16 scope are unchanged.

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

Browser/platform batch validation runs 1,433 Python executions across 207 module
invocations with no failures or unstable outcomes. The slowest uninstrumented
module takes 11.76 seconds, within the 30-second budget. Measurements contain
1,245 offline and 188 HTTP executions with no lock-audit violations. Offline
coverage remains 90.28% (20,843/23,087); HTTP rises to 78.37%
(18,094/23,087), covering 6,550 of 12,000 conditional exits. Combined coverage
remains 92.78% (21,420/23,087) and 8,921 conditional exits, with all thirteen
critical functions complete. HTTP budgets only tighten: 234 lines and 158 exits.

Local browser validation combines all 381 existing journeys in the broad run
with all 120 added cases in the final three-browser run. CI runs the complete
501-case suite. The payload census waits for the final build response and checks
the selected heading; the keyboard journey accepts and counts the single discard
dialog. The expiry helper's twelve new statement/function counters are all hit;
399 existing missing identities map exactly through the insertion and reviewed
call replacement, without increasing coverage debt.

Five available local client toolchains pass the portable package/consumer,
contract, decoder and 28-case HTTP/TLS checks. The local Rust executable cannot
run on this ARM64 host; the macOS/Windows matrix supplies separate Rust and
Windows qualification. Platform reports identify current source/package inputs,
not released N-1 packages. The two axe archives were inspected and their bytes
match registry SHA-512 integrity; npm lifecycle scripts remain disabled. Source,
hashes, focused corrections and raw results remain under ignored
`.artifacts/testing-review-followup/`, `.artifacts/platform-clients/` and
`.artifacts/coverage/`. Frozen deployment inputs, released-package skew and
performance/soak qualification remain separate work.
