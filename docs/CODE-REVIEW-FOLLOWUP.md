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
| 4.1.3: Rejected database changed to WAL | Validate ownership/schema before setting journal mode. Rejection preserves the database bytes and creates no WAL/SHM sidecars. Other findings in this subsection remain open. |
| 4.1.3: Dataset purge races | Account, event, snapshot, recorded eligibility and credential mutations recheck dataset existence inside their publishing transaction. Purge also removes encrypted credential versions, bindings and operation records atomically. Deterministic thread regressions cover eleven delayed writer paths and discovery returning after purge; no orphan rows or credentials reappear. Other persistence findings remain open. |
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

The .NET package test also now uses a fresh package cache for each restore.
Previously, an existing package with the same version could hide SDK changes
from the tests despite a successful local pack.

## Validation and outstanding gates

The expanded offline Python/component runner passes: 582 unittest cases plus
the console component checks, Ruff and the existing strict mypy scope.
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

The gateway follow-up adds 14 focused runtime/logging checks, including exact
bound requests with every former fixture switch enabled, fixed startup
destination/timeout, probe rejection, coroutine cancellation, secret canaries
and reply failures without retry. Packaging tests verify that the minimal worker
needs only its runtime, wire codec and standalone logger; fixture scripts
require an explicit harness source map. The frozen Docker/worker and real HTTP
checks still require their target environment.

The database batch adds 14 focused tests. Migration checks verify upgrade and
rollback against a version 1 database; concurrency checks use held provider
fixtures and explicit thread barriers without real sockets or provider calls.
The server wheel includes both numbered migration resources.

The session/probe batch adds 23 offline tests: 14 exercise real operator handlers
with memory streams and explicit thread barriers; nine exercise the real HTTP
response parser over synthetic socket/TLS objects. The probe checks verify IPv6
sockaddrs, SNI, address rejection, invalid trust material, connection/handshake/send
failures and declared/streamed response limits. Four selected regressions also
reject the pre-fix implementations from `ed48930`. Actual IPv6/TLS networking and
the browser suite have not been rerun for this batch.

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

1. Widen lint/type coverage incrementally; the current strict mypy gate still
   covers only its explicit file list (4.3.2).
2. Address full scans, N+1 queries, executor shutdown and remaining token/future
   lifecycle issues. Other persistence details remain open; the single
   SQLite connection still serializes database access.
3. Refactor routes, repeated CSV/money/timestamp logic, repository ownership and
   large functions with focused behavior tests. Continue the platform, process
   recovery, generated-input and performance work in the testing roadmap.

GitHub Actions hardening is deferred to a separate activity at the owner's
request. This includes reviewing and pinning the remaining CI bootstrap artifacts
and action revisions (4.3.3).

Other lower-severity findings and carried-forward structural items remain open
unless explicitly listed as fixed above. Added coverage is not a substitute for
deployment, security or performance qualification.
