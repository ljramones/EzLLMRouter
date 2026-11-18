# DEV-05 independent review handoff

**Scope:** bounded installed-client/tool integration on the Run-11 separated sender. Run-15's signed WorkKey integer mismatch was corrected and locally tested. Owner Run-16 then completed the defined D05-01–05 synthetic matrix. Disposition: `DEV05_SEPARATED_CLIENT_TOOL_CHECKPOINT_OBSERVED`. The detailed independent Run-16 review and validation are preserved as separate files beside this handoff.

## Identities and comparison

| Item | SHA-256 |
| --- | --- |
| Operative owner-supplied DEV-05 brief | `19858c7fdfef9dffe306eb7ad361097da2cf1403f76eafbba8b2633f7807c3c0` |
| Preserved Run-11 executed source | `9a3a3bda199b5fad6d63ccac6abd7837d534ed0c45cefb496645d89f56834a64` |
| Preserved Run-11 runtime | `b825d38e300a7f971db827a12696eae7d3c582d4c21dc374cc96983ae24045bb` |
| Historical Run-12 source packet | `95fa019fcebe5bc0508fae5d8ef532c837e75c992047bb8c1ddfa5b45ad345f3` |
| Corrected Run-96 source packet | `62c6401858a070aefabf9f22dad47b3775ef1c2f0e15fb22f2240e0da647176e` |
| Run-96 pre-Docker runtime packet | `e690952626cfec5dcc5095237986f4f0dd4126188cd24bdab770d912aa4fc9ef` |
| Separately exported Run-12 redacted records | `f8ef80839ec10343845a6665e6e273df0865ec67a90207f120da0a911c0a36c2` |
| Preserved Run-13 executed source | `f263606d5e79a53daf8c74dfc189c8d87f807a88bdcd28b216f7647e8fa82fd1` |
| Preserved Run-13 runtime | `2bf1105f514b02efdf64f3511a32a0ba016cb9659ee6faa2725da066695b03ab` |
| Corrected Run-93 source | `a1176e189311a93b4fe8ddd86cfb62910cb763abab92fd8595f1b3df1d04cf75` |
| Run-93 pre-Docker runtime | `157d4f10d7129fa0dbec73bd08fda7e41143bc231b083b10bf5ab1f9e6c535f3` |
| Preserved Run-14 executed source | `f06bc975c29157015c8068f6fb776bd15d68b0795c231bbc77f81760067845ca` |
| Preserved Run-14 runtime | `e1d751cb4f854fefd5ecfa78311a7714bff79a7c690b8d8b135bee8b97c5b793` |
| Corrected Run-91 source | `89e916eb28e84924268d7fd1b6275641f2c310144c27954d84809bf479acfa8e` |
| Run-91 pre-Docker runtime | `ab4a02827879c2094d9e636bd9b282ac1947a26f9574a91b8561d1a6d65e62d3` |
| Preserved Run-15 executed source | `f7a600aa747bbacf172f277a66ae75ef0aee7419dc259a873c62efbb48619bc2` |
| Preserved Run-15 runtime | `6008e5e105b65d041653dd91da67f5147b11a748b34ba7131757c13e7e585dff` |
| Corrected Run-90 source | `9e91d6254f709dcc079212d0659186d56113fade0948e7e8442f22908561f1c0` |
| Run-90 pre-Docker runtime | `5159c8062633f70e42463b6767bb5b4ed7ee367aab7179b76a9b4ab881bc5715` |
| Run-16 executed source, 76 verified payloads | `a711e6e30a3bf950abd3ab3b873eaa8069ce9b93d7934dd47be72bbc772f535c` |
| Run-16 runtime, 431 verified payloads | `adf88631c2026ae1e0648dcb9e141e5887580ece5a8a294c3ad3d7088ccfc341` |

`BASELINE-CORRESPONDENCE.json` maps initial DEV-05 executed source changes against Run-11. `PREFLIGHT-CONTINUE-01-VALIDATION.json` records the corrected source identities and every Run-96 command/exit. The source packet contains 73 staged files and its manifest. Client wheel/tarball and 117 gateway wheel identities are in that manifest; frozen dependency bytes remain in the existing checked input directory. The original Run-12 source and logs were not changed.

`WORKER-READINESS-CONTINUE-02-VALIDATION.json` records Run-13's exact identity command, saved failure, exits, packet verification and every Run-93 pre-Docker command. Run-93's source packet has 75 staged files. Run-12 and Run-13 artifacts remain historical and unchanged.

`RETRY-CONTINUE-03-VALIDATION.json` records Run-14’s 75-source/196-runtime manifest check, failed retry stage and cleanup exits; the 24/24 Run-91 pre-Docker command records; and local staged service/client mock checks. Run-14 artifacts and failed exits are unchanged. The host source-copy retry suite uses staged frozen pure-Python wheels plus already installed macOS cryptography 45.0.6; the target container gate for pinned ARM64 cryptography 50.0.2 remains.

`WORK-IDENTITY-CONTINUE-04-VALIDATION.json` records Run-15's 75-source/220-runtime manifest checks and original failed exits, then all 25 passing Run-90 pre-Docker stages, 140 Python tests and source/runtime identities. `WORK-IDENTITY-CONTINUE-04-OBSERVATION.json` records a controlled real-Coordinator → signed-plan → sender path with integer revision, one intent, guard receipt and lower call. It is a source-copy regression, not a target LiteLLM/receiver result. Run-15 packets and logs remain historical and unchanged.

`DURANKI-DEV-05-RUN16-REVIEW-05.md` and `DURANKI-DEV-05-RUN16-VALIDATION.json` record the independent data-only review of the 76-source/431-runtime payloads and owner target behavior. Both packets already resided in this result directory and match the handoff bytes. The supplied verifier replay, key evidence and checkpoint note are preserved separately. The review's replay of captured verifier inputs is not a new application or Docker execution.

## Review focus

1. Confirm `dev05_steps.sh` targets `service_choice_b` for both installed clients and uses neither the old in-process service nor direct receiver submission for model requests. The receiver is queried only for independent metadata counts and health.
2. Confirm D05-02 and D05-03 execute `lookup` only in the caller actors; each follow-up has a new generation, a preserved call block and result linkage. Check the DEV-05-only trusted no-store label and the storage/log scans before accepting no-store claims.
3. Confirm `choice_b_sender.py` changes only the test-named tool field after binding, logs its digest-only mutation, and the final guard blocks it with no receipt or socket acceptance. Check `choice_b_worker.py` attempt counters for hidden local retry. The raw-worker and forged-attempt probes should add no receiver arrival over a measured five-second quiet interval.
4. Confirm the independent verifier rejects mismatched receipts, unknown usage filled as zero, missing actor results, extra arrivals, candidate retention in no-store records, and a negative that did not reach the trusted guard. Distinguish local verifier rehearsal from owner target evidence.
5. Confirm Run-16's executed source packet, `run.exit=0`, `cleanup.exit=0`, full verifier, worker modules, per-attempt intent/receipt chain, receiver records and selected log scan using the independent review and preserved packets. Retain the one nonfatal finalizer-only controls export exit of 1; the required D05 controls export succeeded empty. Do not reinterpret Run-11's historical failures as DEV-05 failures.
6. Inspect the new sender work-identity check, complete component fixture and explicit tool mutation test. Missing/malformed identity must fail before a send; the mutation must reach the independent guard and add no arrival or receipt. Check the deterministic test thread/event-loop close and absence of `ResourceWarning` in Run-96.
7. Inspect `capture_runtime.py` and `dev05_steps.sh` together. The credential lifecycle marker is written before each synthetic credential, known values are redacted, missing values before generation are permissible, and a missing expected value withholds export. A failed export records `capture.exit` and preserves a nonzero primary `run.exit`. Run-12's separate replay packet must not be read as a rerun or a target result.
8. Inspect Run-13's `d05-worker-identities.argv` and stderr: the single Unix connect to `/link/worker.sock` failed with `FileNotFoundError`. The HTTP readiness stage did not check that interface. Compose reported worker Up for about one second and the captured startup scan had zero bytes; no later worker initialization outcome was observed. Check `worker_ready.py` for retrying only absent/refused sockets within 50 seconds, a successful `module_identity` exchange, exact identity validation and immediate protocol/permission failure. The service image stages the probe through its existing gateway COPY with non-root read permissions. If a future run fails at this stage, examine its focused worker-startup log before considering another correction.
9. Inspect Run-14’s retry stderr and the two-file correction. `RetryASGIDouble` consumes v4’s private `max_retries` and signed `timeout`, sends neither in provider JSON, and uses the signed timeout as HTTPX control. Confirm the field-leak and over-budget negatives still reach `GuardRejected`; the persistence, reentry, one-send and uncertainty tests retain their original assertions. `run.sh` executes the staged suite before Docker and retains the target-container run. Run-91’s staged guard 8/8, retry 12/12, installed Python and JavaScript client controls, actor output 9/9 and strict consumer are source-copy/fake-reply checks only.
10. Inspect Run-15's saved first JavaScript 409 and public WorkKey. The Coordinator signs integer `step_revision: 1`, but sender relay admission previously demanded strings for all fields. `choice_b_sender.py` now requires four nonempty string IDs and a true integer revision in `1..9007199254740991`; it does not coerce, default or make identity optional. Both component positive fixtures use integer `1`. `test_work_identity.py` exercises the real Coordinator, signed plan, sender relay, final guard and result mapping across positive, malformed, forged/reused, timeout, reached-guard mutation and commit-failure cases. It is staged before Docker and retained as a target component. Confirm the new source's 25/25 pre-Docker stage exits, the separate guard 8/8, and that the owner target run retains strict client/receiver assertions.

## Current observations and next evidence

Run-90 passed 25 runner-selected pre-Docker stages, including 140 Python tests, and the separate staged guard suite 8/8. Its runtime packet carries `PRE_DOCKER_COMPONENTS_ONLY`; no Docker ran. Run-15’s 220-payload runtime passed manifest verification and credential-file exclusion; `work.exit=1`, `run.exit=1`, `capture.exit=0` and cleanup exits 0 remain authoritative. Run-16 independently records the target inventory: 12 provider arrivals, four caller lookups, 13 intents, 12 receipts, 10 usage revisions and one reached-guard mutation blocked before sending. Both installed clients completed retained and live no-store cycles and cross-reads. The selected no-store scans and finite quiet intervals do not establish complete task drain or whole-process erasure. The actual cached SDK retry scalar was not exported. Run-11's queue-revocation discriminator was cited, not rerun. No product patch or repeated owner run follows this checkpoint.
