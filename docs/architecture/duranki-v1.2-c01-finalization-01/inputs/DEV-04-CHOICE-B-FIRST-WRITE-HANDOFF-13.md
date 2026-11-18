# DEV-04 Choice B first-write handoff — local checkpoint

## Authority and scope

LM-01 adopted `DURANKI-DEV-04-FIRST-WRITE-OWNER-ADDENDUM-13.txt` on 2026-10-20. Observed SHA-256: `a55d97f799947163abedab33468223b1aedf50997ac5d099d640723d681c7470`. This is a bounded synthetic plaintext HTTP/1.1 experiment for one fixed provider route. The historical Run-07 stale arrival and Run-09 separation evidence remain intact. No Docker target result for this implementation exists yet.

## Implementation and discriminator

`owned_sender_transport.py` owns a public nonblocking TCP socket behind documented frozen httpcore 1.0.9 backend/stream interfaces. Frozen httpcore/h11 continue to manage HTTP/1.1 and the one-connection pool. After resource waits, the stream performs a full fresh check, then serializes current local revocation, epoch and deadline checks with one `socket.send` through the same trusted lock. A would-block return waits outside the lock and rechecks; positive partial writes only advance the same attempt's suffix. Cancellation closes the stream. The first-byte event means a positive local OS send return, with no claim about physical wire timing or provider receipt. The sender uses no TLS, HTTP/2, proxy, redirect, retry or connection reuse in this route.

The trusted service owns the revocation control socket and acknowledges commands after applying them. The LiteLLM worker retains `network_mode: none`, no trusted code/data mount or provider key, and no provider route. The sender still requires a registered, single-use attempt, independently checks the exact final request, commits the guard receipt, and preserves the prior public failure/unknown distinctions.

The new target sequence runs after the existing two-positive separation verifier. It occupies the selected sender's actual httpcore pool with a receiver hold, observes a second committed request queued there, revokes local authority, releases the hold, and checks that the queued attempt had no first socket acceptance, headers/body or receiver arrival. It then checks a 5.2-second quiet interval and restores authority for a final positive. The verifier joins the real pool observation, control acknowledgment, guard events, statuses, receipts, send diagnostics and independent receiver rows by attempt ID. A separate socketpair test covers the post-check backpressure gap and cancellation semantics locally.

## Local evidence

- Frozen-version owned-sender controls: 10 tests passed, including GuardTransport→httpcore/h11→socketpair positive, real httpcore queue/revocation, backpressure, partial writes, cancellation before/after first acceptance, failure and consumed-attempt reuse.
- Existing Choice B component tests: 11 passed. Python compilation and `bash -n` for the runner and Choice B steps passed.
- Unique source preflight: 57 source files, 117 unchanged frozen wheels. All 58 source-packet entries matched the SHA-256 manifest. The staged worker has only `choice_b_worker.py` and `choice_b_wire.py` as Python sources. Source packet: [DEV-04-SOURCE-source-preflight-20261020-13.zip](DEV-04-SOURCE-source-preflight-20261020-13.zip), SHA-256 `5b2cb79226ba5136a217937176ed2f9c5a8e9d5a1055d826f346de9cad0d9455`.
- The compact [local validation record](DEV-04-CHOICE-B-FIRST-WRITE-LOCAL-VALIDATION-13.json) lists the exact commands, counts and pending target verdict.
- The executor has the previously documented Docker denial. No new Docker build, image, container or owner evidence was created for this implementation.

## One owner Terminal invocation

Run from the owner Terminal with the existing Docker Desktop Linux context and frozen local inputs:

```sh
cd /Users/larrymitchell/Mach33/Duranki && ./tests/gateway_integration/run.sh run-20261020-10 choice_b
```

The runner creates a new `/private/tmp/duranki-dev-04/run-20261020-10` directory and its normal source/runtime packets under `docs/development/dev-04/`; it rejects collisions. Preserve the entire run directory and packets, including any failing step's `.stdout`, `.stderr` and `.exit`, for independent review. A passing target verifier prints `CHOICE_B_LOCAL_FIRST_WRITE_QUEUE_REVOCATION_OBSERVED`. A local test pass alone is not that verdict.

## Review focus and open claims

Check the new `choice-b-freshness-*` evidence with `verify_choice_b_freshness.py`, including queue time before revocation acknowledgment, five unique guard receipts/send records for the five selected attempts, four matching positive receiver arrivals, a queued `failed_before_transmit` status, zero queued first-byte acceptance and zero queued receiver arrivals. The control socket is only a local authority source; remote propagation and physical network timestamps remain unqualified. The Run-09 egress checkpoint remains bounded to its tested worker probes. Production, TLS and whole-gateway acceptance remain open.
