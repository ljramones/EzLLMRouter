# Duranki DEV-04 — Run-11 independent review 15

**Disposition: `CHOICE_B_LOCAL_FIRST_WRITE_QUEUE_REVOCATION_OBSERVED`.** The selected plaintext HTTP/1.1 Choice B queue-revocation discriminator passes in the supplied owner execution. The held positive completes after controlled release; the queued authorized attempt is rejected after local revocation and before any recorded local socket-byte acceptance or receiver arrival. The worker-egress/forged-attempt controls also pass in this run. No corrective product patch or unchanged target rerun is requested by this review.

This is a **bounded development observation**, not production, whole-gateway, full initial-profile, complete B-series or universal final-send acceptance. It does not retrospectively convert Run-07 or Run-10 into successful runs. The older pre-pool implementation remains disproved by its preserved counterexample.

## 1. What closes now

The two issues identified in Run-10 are resolved for the exercised target path:

1. Actual final-request timeout extensions are **30.0 seconds for both held and queued work**, and **1.0 second for each of the three ordinary positives**. The private per-request timeout now propagates through the executing LiteLLM/SDK/relay path into the trusted guard's receipt. This is not merely a private JSON field or an offline resolver-helper result.
2. The held attempt is `completed / present / response_observed`, not `outcome_unknown`. The queued attempt is `failed_before_transmit / unavailable_due_failure / failed_before_dispatch` with public terminal error `FDC_REJECTED` and matching terminal attempt identity. Its lower exception is `ContractError`, consistent with the actual Coordinator freshness callback. The verifier retains the held-positive requirement; it has not accepted a timed-out hold to obtain a pass.

The owned-socket implementation itself, the trusted sender/service, the guard, worker code, Compose isolation and all six supplied Duranki server modules are byte-identical to the verified Run-10 source snapshot. This iteration changes the private recipe, status export, runner/staging and verification/regression support. It adds two harness files. No new enforcement implementation was needed for this correction.

## 2. Input integrity and source correspondence

| Input | Bytes | SHA-256 | Verified payloads |
|---|---:|---|---:|
| `DEV-04-RUNTIME-run-20261020-11.zip` | 119,640 | `b825d38e300a7f971db827a12696eae7d3c582d4c21dc374cc96983ae24045bb` | 325 |
| `DEV-04-SOURCE-run-20261020-11.zip` | 126,523 | `9a3a3bda199b5fad6d63ccac6abd7837d534ed0c45cefb496645d89f56834a64` | 59 |
| `DEV-04-SOURCE-source-preflight-20261020-14-timeout-final.zip` | 126,523 | `22ea6f05bba75b94fc65b76ae2e5d61993c08838301e06bdf0329b26780afb3d` | 59 |
| `DEV-04-SOURCE-source-preflight-20261020-14-timeout.zip` | 126,455 | `cf6034b50b6fff20a74d0f243ef1329657da9d19a12c9b7c2c72a830f588297e` | 59 |

CRC, duplicate names, path escapes, member types, file-prefix collisions, encryption and inspection-size checks pass. Every payload size/hash matches its self-excluding manifest. The runtime's source-build manifest equals the executed source manifest as JSON.

The **final** preflight and executed source contain byte-identical uncompressed members, including their manifest; the ZIP container hashes differ. The earlier non-final preflight differs in `harness/verify_choice_b_freshness.py`, `harness/test_run10_held_timeout.py` and the manifest. It is not represented as the executed source. This is an identified candidate succession, not a discrepancy in the controlling final snapshot.

The source manifest retains the same 117-wheel inventory and the Python 0.0.3/CommonJS 0.0.2 package references. This review did not newly inspect the external distribution bytes. The worker's observed LiteLLM and proxy module hashes match the supplied selected wheel/sdist correspondence records. Native-binary source correspondence and current advisory clearance are not supplied by this record check.

There are **72 complete argv/stdout/stderr/exit command sets** and **84 recorded exit files, all zero**. Bootstrap and some final exports/cleanup do not each have all four capture files; they are not counted as complete command sets.

## 3. The decisive target sequence

Held attempt:

`attempt.c5785cb9a4694e26a8861851dd0173c4`

Queued attempt:

`attempt.35fb5933afcc4d62a392e4dd14486a5e`

The inspected driver, authority control, selected real-pool observation and independent receiver records support this ordering:

1. The held request reaches the receiver and enters its response hold, occupying the selected sender resource.
2. The second request passes the guard and has a durable guard receipt before being released into the selected httpcore pool.
3. Its actual queued state is observed at sender monotonic ns `766785848317511`. The observation reads selected private pool state for evidence only; it is not the enforcement mechanism.
4. The trusted local authority reports revocation applied at epoch 1, monotonic ns `766786145762677`, approximately **297.445 ms after the queue observation**.
5. The driver waits for that successful acknowledgment before issuing the receiver release command. The independent receiver records `hold_entered_after_receiver_arrival → hold_released → hold_response_released`, in order, without `hold_timed_out`.
6. The held positive completes normally. Its response hold lasted approximately **995.912 ms** before controlled release.
7. The queued request records a `ContractError` at monotonic ns `766786348354094`, approximately **202.591 ms after revocation acknowledgment**. Its completed send diagnostic records `first_bytes_accepted_by_local_socket: false` and zero first-acceptance events. The receiver never records that attempt.
8. Receiver output is unchanged through the **5,205 ms** freshness observation interval. After local authority is restored at epoch 2, a new positive completes and adds exactly one arrival. The rejected old attempt is not revived in the final exports.

**Chronology limits:** the authority and queue/error records use the sender's monotonic clock. Receiver controls use its own wall-clock records. Ordering of revoke-before-release is additionally supported by the inspected sequential `logrun` calls, successful command exits and the authority command's acknowledgment after applying the gate change. This review does not infer kernel-write chronology by comparing unrelated clocks.

`FIRST_BYTES_ACCEPTED_BY_LOCAL_SOCKET` is set in source only after a positive nonblocking `socket.send` return. The exported `send-events` row is emitted when the send operation finishes; its timestamp is **not** the timestamp of first-byte acceptance. There is no independent packet capture or kernel trace here. Absence of an application-request arrival is joined with the actual source-level first-acceptance flag and terminal before-send state, rather than treated as sufficient by itself. TCP connection establishment is not counted as a provider-request header/body transmission.

## 4. Timeout correction and semantic result

| Attempt class | Actual receipt extensions: connect/read/write/pool | Outcome |
|---|---|---|
| Ordinary before/after separation positives | 1.0 / 1.0 / 1.0 / 1.0 | Both delivered |
| Held positive | 30.0 / 30.0 / 30.0 / 30.0 | Completed; candidate present |
| Queued revoked work | 30.0 / 30.0 / 30.0 / 30.0 | FDC rejection before first acceptance; no arrival |
| Ordinary positive after authority restoration | 1.0 / 1.0 / 1.0 / 1.0 | Delivered |

The private proxy recipe v4 and the independent provider receipt recipe v2 describe different transformations. Their different identifiers are intentional: private SDK controls changed; the final provider expectation remained the same.

Thirty-second per-operation extensions are not a proof of an end-to-end thirty-second deadline through queueing, response consumption and recovery. The unchanged owned transport additionally checks the signed deadline at its local first-send gate, but that is not a complete deadline qualification.

The original Run-10 failure remains truthful and immutable. This review supplies a successful new target observation; it does not weaken the earlier test or relabel an unknown response as success.

## 5. Separation and accounting still reconcile

The actual executing Python client records three ordinary delivered positives. The held request is the fourth successful model response. All four receiver rows match four distinct trusted receipt rows by attempt, method, destination, body length and body hash. Three bodies are 144 bytes; the held request is 155 bytes. Their successful send summaries each record exactly one first-acceptance event and no lower error.

The queued rejected attempt has the fifth preparatory intent and guard receipt, but no socket acceptance, receiver arrival or reported usage. Final aggregate:

```text
5 submissions
5 preparatory intents
5 guard dispatch receipts
4 receiver arrivals
4 usage revisions
```

A guard receipt records authorization/intent, not proof of a network send. Thus five receipts and four arrivals are expected here. The internal worker/sender exchange is not counted as a separate model attempt. The aggregate usage count is not a full per-row accounting or real-provider billing audit; missing usage is not silently assigned zero cost.

The worker checks report no default route, absent selected trusted-code paths and credential environment variables, and a failed direct loopback receiver connection (`errno 111`). The labelled in-worker raw HTTPX probe returns `ConnectError`; the forged sender attempt returns `ValueError`. Receiver records remain byte-identical through their negative capture and a **5,204 ms** observation interval; a positive succeeds afterward.

The `network_mode: none` string in the probe output is a reported label supported by the submitted Compose configuration, not a separate live Docker-inspect field. Actual route/path/environment/connect assertions are visible in the executed probe command. This remains a bounded separation observation, not exhaustive arbitrary-code, endpoint impersonation, tenant-isolation or host-compromise proof. The worker and sender share the specifically declared Unix communication volume, while the trusted state/control volume is not mounted into the worker.

The preliminary separation verifier still prints `FRESHNESS_OPEN` / `NOT_TESTED` because it runs **before** the new freshness sequence. The later dedicated verifier prints `CHOICE_B_LOCAL_FIRST_WRITE_QUEUE_REVOCATION_OBSERVED`. The first output is a sub-checkpoint, not a contradiction in the completed run.

## 6. Build, tests and cleanup attribution

The owner invocation records **97 Python test executions across eight suites**, including 15 timeout/verifier regressions, 10 owned-sender controls and 11 Choice B controls. Those component invocations run on the recorded host interpreter; they are not all container runs. The subsequent live installed-client/worker/sender experiment is the Linux ARM64 target observation.

The Choice B component stderr contains an `unclosed event loop` ResourceWarning, followed by all 11 tests passing. This is preserved as a component-test warning, not described as a warning-free run or a new observed target-service failure. Full background-task drain remains unproved.

The five built-image records identify Linux ARM64 and non-root runtime users. No source-manifest labels are present in these records; correspondence is based on source snapshots, stage manifest and logged build contexts. Image filesystems were not independently inspected.

Cleanup records show successful removal of **five scoped containers, three volumes and five built image tags**. Removed image identities match all five build-inspection identities. The selected topology does not record removal of a separately created project network. End-of-run receiver, control, guard, pool and send exports are byte-identical to the earlier final-check captures: no additional recorded arrival or send event appears before cleanup.

These are checked historical records. No claim is made about the current state of the Mac, Docker daemon, BuildKit cache or external services.

## 7. Reviewer work and reproducibility

The reviewer independently checked archive structure, hashes, source correspondence, recorded exits, identities, timeout values, per-attempt joins, queue/control/error ordering, positive/negative observations and cleanup. The included `DURANKI-DEV-04-RUN11-VERIFY.py` uses the standard library and treats all archived content as data. It refuses to overwrite its requested output and has **eight in-memory corrupted-evidence rejection controls**, all passing. Those controls are verifier tests, not additional product tests.

After inspecting their source, the reviewer also replayed the supplied `verify_choice_b.py` and `verify_choice_b_freshness.py` against copied original records. Both returned zero, and both stdout results matched the original recorded bytes exactly. Replay commands and outputs are separately attributed in `supplied-data-verifier-replays.json`.

Reviewer environment: Linux/Python 3.13.5. **No Docker execution, application/transport test replay, package installation, LiteLLM execution, external request, new socket or Mac repository mutation occurred in this review.** The supplied owner evidence, rather than reviewer execution, establishes target behavior.

## 8. Disposition and next action

Preserve this as the successful **selected synthetic Choice B separation and local queue-revocation checkpoint**. The Run-10 timeout mismatch and rejection-verifier mismatch are closed for the reviewed target cases. The Run-07 stale-queue counterexample is now answered by a different implementation in this bounded local-authority, plaintext HTTP/1.1 scenario; the historical failing result remains unchanged.

There is no new corrective patch and no reason to repeat unchanged Run-11, rebuild unchanged client packages or reacquire dependencies. Record the observed milestone in the existing living RESULT.md, keeping the preliminary sub-verifier and historical failures accurately attributed. Do not erase the distinction between this feasibility result and production adoption.

The next substantive work, when selected, should be a separate, finite increment based on the product's requirements—not another attempt to obtain the same queued-revocation result. TLS/HTTP2, broader providers, real-provider credentials, remote/distributed authority propagation, crash/restart continuity, end-to-end deadlines, complete drain, all adversarial sender-interface cases, tool/client parity on the separated path and complete B-series/production acceptance remain unqualified by this run. They are not retroactive reasons to withhold the demonstrated checkpoint, and this review does not automatically authorize them or reset the cumulative effort caps.
