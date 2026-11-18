# WP-B/DKR-01 Compose Proof Delta — Correction 01

The adopted A2 wire `0.2`, projection `duranki-work-v0.2` and `initial_1a@1` remain unchanged. The nine B groups in the [original delta](../wp-b-docker-01/DURANKI-WP-B-COMPOSE-PROOF-DELTA-01.md) remain **NOT_RUN**; no shape or mock preparation test here is a gateway qualification. The independent receiver target is `http://receiver:8000/v1/chat/completions` and the driver target is `http://gateway:4000/v1/chat/completions`. The future signed route fixture must be regenerated for those exact controls.

| Group | Retained future proof obligation | Correction effect |
|---|---|---|
| B-01 | Valid signed text and exactly one receiver arrival after durable intent | Trusted fixed `/app/trusted` loader is defined; future wrapper still absent. |
| B-02 | Ordered tools, taint and capability exclusions | No contract change. |
| B-03 | Final prepared body/control mutation rejection | No guard or final-write proof yet. |
| B-04 | Host/port/path/model/timeout and alternate-route rejection | Compose `pull_policy: never` prevents implicit runtime image acquisition. |
| B-05 | Signature, expiry and version checks | Signing keys are not generated. |
| B-06 | Persistence, cancellation and queued-send revocation | No service or intent recorder ran. |
| B-07 | Known/uncertain response and unknown usage | A2 live-only no-store consequence stays in adopted contract. |
| B-08 | SDK retries, 422 parameter drop and alternate handlers | Exact transport sources still not inspected. |
| B-09 | Egress/privacy/package and same-allowed-receiver bypass | Namespace policy, independent receiver and runtime observation remain pending. |

## Recipe and proof boundary

All three services have `pull_policy: never`; absence of an approved local image must fail rather than pull. Build/runtime dependency installs are wheel-only, hash-locked and offline; staging checks Python 3.12/Linux ARM64 wheel tags, while the selected root wheel is separately built from its pinned source with Maturin/Cargo after future authorization. The local wheel is hash checked, installed without dependency resolution and followed by `pip check`. Future harness files are copied into `/app/trusted`; `python -I -B -c` inserts only that fixed directory before importing each fixed entry module. Synthetic local tests confirm that explicit loading works under `-I` while an ordinary sibling import from a script path fails. These static tests do not prove future wrapper correctness.

Every negative B case still requires valid receiver controls before and after, reached-stage evidence, receiver/socket observation through task drain plus five seconds, and a same-allowed-receiver bypass probe. The guard-to-first-write, total deadline through response consumption, retry allowance, cancellation and context isolation requirements remain. The gateway wrapper must refuse untrusted import/start until the future project-scoped namespace policy and authenticated run receipt are verified. `internal: true` bridges and separate volumes are no substitute for that proof.

A separately issued B1 instruction must freeze actual image digests, run environment, route fixture, harness, policy helper, exact argv and cleanup identities before using Compose. No `up`, build, listener or provider action is authorized by this correction. WP-B/B1 and WP-C remain `NOT_ISSUED`.
