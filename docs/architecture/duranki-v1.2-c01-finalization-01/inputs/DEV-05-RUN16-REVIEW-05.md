# Duranki DEV-05 — Run-16 independent review 05

**Date:** 21 October 2026  
**Disposition:** `DEV05_SEPARATED_CLIENT_TOOL_CHECKPOINT_OBSERVED`  
**Scope:** the defined D05-01–05 standalone synthetic client/tool integration on the separated Choice B path. This is not production, real-provider, TLS/HTTP2, all-profile, complete B-series or Phase 1a operational acceptance.

The supplied owner run demonstrates the bounded matrix: both installed clients complete text and caller-owned retained/no-store tool workflows through real LiteLLM and the trusted sender; cross-reads add no sends; the selected provider failures retain their known/unknown outcomes; the reached-guard mutation and worker/sender probes add no receiver arrival. No corrective product patch or unchanged Docker rerun is requested. Preserve Run-11 and the historical failed runs.

## 1. Evidence and independent work

| Supplied archive | Bytes | SHA-256 | Payloads verified |
|---|---:|---|---:|
| DEV-05-RUNTIME-run-20261021-16.zip | 155,266 | `adf88631c2026ae1e0648dcb9e141e5887580ece5a8a294c3ad3d7088ccfc341` | 431/431 |
| DEV-05-SOURCE-run-20261021-16.zip | 222,010 | `a711e6e30a3bf950abd3ab3b873eaa8069ce9b93d7934dd47be72bbc772f535c` | 76/76 |

CRC, safe paths, duplicate names, ordinary member types, prefix collisions, encryption, size budgets, exact manifest coverage, byte lengths and hashes pass. The source ZIP has 77 members and the runtime ZIP has 432, including each self-excluded manifest. The runtime source-build manifest and source manifest contain identical parsed JSON. The runtime export adds one trailing newline: they are not byte-identical serialized files.

Seven changed-file identities recorded in the latest local preflight validation match the executed snapshot. The preflight archive itself was not supplied anew as a separate input; its reported archive hash is not conflated with the run-specific source hash.

The independent data-only verifier checks attempt/submission/receipt/receiver/usage associations, guard and send events, actor inventories, finite horizons, no-store metadata, identity records, cleanup and the one nonfatal housekeeping exit. Eight deliberate in-memory corruptions are rejected. These are verifier tests, not additional product tests.

The inspected supplied `harness/verify_dev05.py` was separately replayed, unchanged, in both `checkpoint` and `full` modes against reviewer copies of the original records. Both returned zero and produced stdout byte-identical to the corresponding captured outputs. No application code, Docker, LiteLLM, SDK provider call or package installer was run in this review. The replay used reviewer Python 3.13.5. The owner’s target behavior is evidence from the supplied records, not a new execution by the reviewer.

## 2. D05-01/02 — Installed clients and retained tool checkpoint

The installed identities are Python client 0.0.3 from `/usr/local/lib/python3.12/site-packages/duranki_client/__init__.py` and CommonJS client 0.0.2 from `/app/consumer/node_modules/@mach33/duranki-client/index.cjs`. The source manifest preserves these package artifact receipts:

- Python wheel: `efabf2ee4832b627b104845b79bf0302f1b7448f17c2c4ef8c35b8287d8fac57`.
- CommonJS tarball: `5672be3e0c5ed7e847e508f22ef269d83c04bb65c830dba47e923055ec93ec82`.

Both clients target the trusted separated service on port 8773. The real LiteLLM ASGI proxy operates inside the isolated worker, with `RelayTransport` as its selected transport and the trusted sender owning provider access. This is not a separately deployed public LiteLLM HTTP proxy. Worker module identities for LiteLLM and its proxy match the captured selected source/wheel correspondence record. External wheel bytes and built image filesystems were not newly inspected by this review.

The first checkpoint accounts for six intentional receiver requests and two caller lookup executions: one retained text submission per client and two model rounds per retained lookup cycle. Python uses `result_value`; CommonJS uses `result_text`. Retained result/candidate/attempt identities agree across cross-language by-ID and by-work status reads. Reads add no model send or tool execution. New generations and distinct attempts are preserved in each tool cycle; the receiver’s ordered roles and tool-call IDs agree with the actors and receipts. Only the caller actors implement and invoke `lookup`; the selected sender/worker route carries requests and responses rather than executing it.

## 3. D05-03 — Live no-store cycles and forged-source controls

Each installed client completes two live model rounds and executes its lookup once. Both actors check the returned `no.content.store` restriction and verify that both candidates remain unavailable through status (`not_retained`, without a candidate). Before legitimate follow-up, each alters the complete source call’s arguments and verifies `422 / SOURCE_INVALID` with no additional send.

The source-negative quiet intervals are 5,219 ms for Python and 5,210 ms for CommonJS. Receiver/service reads remain responsive; the legitimate follow-up succeeds afterward. Four no-store submissions have `content_store_allowed: false`, no stored candidate and available attempt usage. Their expected generation and submission/attempt associations reconcile with four receiver arrivals and four receipts.

The storage scan examines the four selected submissions and their related intent, guard-receipt and usage rows: four rows in each table. The serving-log scan covers `service_choice_b` and `worker_choice_b`, 17,712 bytes / 178 lines, and reports no matches for its three selected prompt/output/argument literals. The final scan has the same size, hash and result. The independent receiver exports only restricted request metadata, lengths and digests, not captured message contents. The no-store actors export IDs/counts/destinations/status rather than the delivered tool/text content.

**Scope limit:** the actual database and serving-log bytes are not included in the review packet. The observations are the recorded scans plus inspected scan/source logic, not a reviewer re-scan of an exported database. The literal searches are not comprehensive semantic secret detection, whole-memory/WAL erasure, universal vendor-cache inspection or durable no-store provenance across restart. Process-local source verification and this fixed synthetic no-store flow are the demonstrated behavior.

## 4. D05-04 — Known failure and unknown outcome stay distinct

| Receiver case | Installed Python result | Cross-client read | Arrivals | Extra observed replay |
|---|---|---|---:|---:|
| Controlled 503 | `502 / REMOTE_EXECUTION_FAILED`; `failed_after_transmit` | CommonJS observes same submission/attempt/state, usage `not_recorded` | 1 | 0 |
| Ambiguous close | `outcome_unknown`; usage `not_recorded` | CommonJS preserves unknown state and absence of terminal known-failure claim | 1 | 0 |

The quiet intervals are 5,205 ms and 5,203 ms. Before/after receiver exports are identical. The worker records one relay invocation for each attempt, with no second invocation hidden behind a rejected sender replay. The close has `RemoteProtocolError` in the lower/send diagnostics and one recorded first socket-byte acceptance; it is not a failed-before-transmit case. Missing usage does not become zero cost.

The commands labelled `*-drain` establish terminal submission state only. Their `selected_pool_requests` is explicitly null. Complete pool/task drain is **not** established; the no-replay conclusion is the observed finite interval and unchanged final captures, not indefinite exclusion of every retry path.

All twelve transmitted attempts’ final request receipts contain 1.0-second connect/read/write/pool values. This is actual selected-path timeout propagation, not merely configuration text, and not a complete end-to-end deadline guarantee. The private recipe remains v4; the independently prepared final-provider expectation remains `recipe.dev04.openai-sdk.v2`—different role/version namespaces, not a regression. The source binds private `max_retries=0`; the actual cached SDK scalar is not exported in this run. One relay invocation per exercised attempt establishes no observed re-entry, not new introspection of every SDK cache instance.

## 5. D05-05 — Reached-guard mutation and separation controls

Mutation attempt `attempt.9a6e3072a28045ecbfad3668f7bbaf1d` changes `tools[0].function.description` after binding, retaining byte length while changing the body digest. The source confines this injection to the explicit DEV-05 test flag and step. Its guard sequence is exactly `entered → blocked(FDC_REJECTED)`. The attempt has one preparatory intent but no final guard receipt, no first socket-byte acceptance and no receiver arrival. Its installed actor records no caller tool execution and a 5,222-ms stable interval. This is a reached-guard negative, not an earlier shape rejection.

The raw worker probe reports `ConnectError`. An unregistered attempt through the reachable sender socket is rejected with `ValueError`. Their combined 5,205-ms interval adds no arrival, and the final service/receiver health control returns 200. Startup also records the network-disabled worker, no default route, failed direct receiver connection, and no trusted code/credentials in the checked worker surface.

These are the selected probes, not exhaustive arbitrary-code, IPC-abuse or cross-tenant qualification. Positive workflows precede the final mutation/probe group; a health check, not another model completion, follows it. The defined DEV-05 finite inventory is preserved without inventing a thirteenth provider request.

## 6. Full accounting and ordering

| Quantity | Observed |
|---|---:|
| Retained text receiver requests | 2 |
| Retained tool model rounds | 4 |
| Live no-store tool model rounds | 4 |
| Provider-failure/close requests | 2 |
| **Total independent receiver arrivals** | **12** |
| **Caller lookup executions** | **4** |
| Submissions / preparatory intents | 13 / 13 |
| Final guard dispatch receipts | 12 |
| Usage revisions | 10 |
| Pre-transmit blocked mutation | 1 |
| Worker relay invocations | 13; one per registered attempt |

Every receiver arrival matches a distinct trusted receipt by attempt ID, submission, request method, destination, body length and body hash. Signed-plan IDs and work digests join the preparatory intent and receipt exports. The original signed plan bytes are not exported for an independent signature replay; target authority code/components exercise their verification, while this review checks the captured binding chain.

Each transmitted attempt has one `entered → commit_acknowledged → released_to_lower_transport` progression and one recorded local first-byte acceptance. The ambiguous close adds its lower error. The blocked mutation has none of the release/acceptance events. Raw send-summary timestamps are completion-time diagnostics, not first-write kernel timestamps. Ten successful responses yield ten usage revisions; the known failure, uncertain outcome and blocked mutation do not manufacture usage. Visible public retained-response usage preserves partial knowledge and unknown cost. No-store public status is observed as usage available; detailed raw no-store usage is not exported.

Final receiver/guard/send snapshots are byte-identical to the matrix snapshots. Cross-language reads add no sends. No price, actual bill or real workload saving is established by synthetic usage.

## 7. Recorded commands, cleanup and a nonfatal export

There are **99 complete argv/stdout/stderr/exit sets** and **110 recorded exits**. All required matrix, component, work, run and cleanup exits are zero. One finalizer-only export exits 1:

`final-receiver-controls`: `cat: /data/controls.jsonl: No such file or directory`.

The receiver creates that file for hold/release controls. This DEV-05 matrix does not execute a hold/release case; its required `d05-controls` command handles absence and successfully exports an empty stream. The subsequent generic finalizer uses unconditional `cat`. This is a nonblocking housekeeping/capture discrepancy, not a failed no-send test or grounds to rerun the successful matrix. Retain the exact exit; do not claim all 110 exits were zero. Any later incidental collector cleanup can mark that absence explicitly, without changing historical records.

`capture.exit` itself is not in the ZIP: the runner writes it after capture returns. The emitted packet announcement and verified artifact establish completed export; this review does not invent that missing exit record.

The recorded Python suites total 173 test executions (140 pre-Docker plus 33 target guard/retry/work-identity/client tests); these are not 173 distinct reviewer reruns. Node actor/client controls also pass in their recorded stages. The evidence identifies Linux ARM64 images and separate installed client imports.

Cleanup records removal of six project containers (`netns`, receiver, worker, service, Python consumer, JavaScript consumer), three scoped volumes and five newly built image tags. Deleted image IDs match the build inspection. No check of current Docker state, BuildKit cache or unrelated host resources was performed.

## 8. Preservation and limits

Against preserved Run-15, six existing source members change and one work-identity regression is added (the manifest is separately changed). The actual sender WorkKey check and both fixtures implement the reviewed integer repair. All six core/server modules, owned-socket transport, final guard, private v4 recipe and worker code are unchanged from Run-15. The owned-socket transport, guard, private recipe and six core modules are also byte-identical to Run-11.

Run-11's selected pool-revocation discriminator is cited, not rerun or extended. The current test/source composition preserves its mechanism while separately evidencing the DEV-05 client/tool workflows. Current observations do not prove TLS, HTTP2, streaming, distributed authority propagation, full task/transport drain, crash consistency, recovery after ambiguous send, every adopted operation, multitenant security or production/operational acceptance. Earlier unexercised DEV-03 variants remain separate coverage, not hidden prerequisites for this defined matrix.

The supplied living RESULT and handoff still use pre-run/pending language. Update them with the observed disposition and these precise limits; keep the historical failed runs and local observations separately attributed. Their pre-run language is stale after this execution, not contrary runtime evidence.

## 9. Next action

Record `DEV05_SEPARATED_CLIENT_TOOL_CHECKPOINT_OBSERVED` in the existing living RESULT.md, preserve this review/validation and the original packets, and stop the DEV-05 correction loop. A local data-only replay is sufficient for an executor wanting to confirm the handoff. No code change, dependency acquisition, package rebuild or unchanged owner run is requested. Do not silently spend the remainder of this batch on TLS or production features. The next separately scoped product increment remains an owner decision.
