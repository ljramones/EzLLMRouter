# Testing roadmap

The browser baseline passed all 381 cases across Chromium, Firefox and WebKit
in the owner Terminal. The subsequent Claude review is being addressed in the
[review follow-up](CODE-REVIEW-FOLLOWUP.md). The longer-term priorities below
still apply; measured coverage and deployment qualification remain outstanding.

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
for each confirmed defect. The explicit inventory and JavaScript CI jobs address
the discovery portion of priority 1; they do not establish coverage percentages
or complete the later test layers.
