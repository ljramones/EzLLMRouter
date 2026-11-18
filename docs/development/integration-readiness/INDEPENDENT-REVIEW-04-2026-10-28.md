# Duranki Integration Correction 03 Independent Review 04

Date: October 28, 2026, America/Toronto.
Independent acceptance recorded: 12:11:51 p.m. EDT (16:11:51 UTC).

## Acceptance decision

**READY_FOR_VEGA_PLATFORM_INTEGRATION — independently accepted for the agreed local accounting interface, contract v2 and service/clients 0.2.2.**

IC03-01 closes. The incompatible v1/v2 binding is rejected in either arrival order. An existing historical conflict remains visible and immutable while unrelated work is accepted into the same dataset. An event touching the conflicting component still rejects. The exact attached service and client artifacts reproduce the corrected behavior.

Preserve the prior IC02-02–IC02-05 and IR01–IR06/IR08/IR09 closures. Closing this final lineage residual also closes IC02-01 and IR07 for the reviewed local scope. No additional Duranki correction is requested by this review.

This completes the Duranki Integration Readiness milestone. Vega-wide instrumentation, its durable exporter, selection-time eligibility enforcement and real cohort activation remain the next milestone. The proposed real feature-retention policy still requires owner adoption before real T0. DEV-12 CT02-02b remains OPEN with its separate historical technical qualification PARTIAL.

## Accepted release identity

| Reference | Identity |
| --- | --- |
| Previously reviewed baseline | `d3d533a47c3addcc503c2d6b6ba0c06bb0340b9d` |
| Tested product/client source | `6fc9434f7aa0a120b04c94931f28c3112bc333c7` |
| Final record, executor-reported remote head | `d25cc576816e5748bac55b012b435d914929198e` |
| Contract | v2; v1 compatibility retained |
| Service / JavaScript client / Python client | 0.2.2 |

| Attached artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| duranki-integration-service-0.2.2.zip | 863363 | `2ebfe4a380f43523f604a3233b897fca59cc370c8a4b50597d1ca0a7da12db22` |
| duranki-integration-correction03-review.zip | 96131 | `381bce7347a55ec970c13b49c804ee216976fabcbff7e45e7915efe0f52fd349` |
| mach33_duranki_server-0.2.2-py3-none-any.whl | 146200 | `070b0f536f3e59f647f88bba04bd820febb5424adffcd8ef4e75b611f58c237e` |
| mach33_duranki_client-0.2.2-py3-none-any.whl | 32017 | `eddff93e8f17bd6b472293774898c40f0cec20062050b26856d045a6ca11d600` |
| mach33-duranki-client-0.2.2.tgz | 24933 | `8a3329e1017bca2c976b3fba0bfa21b8006f8199927134a9b005026b95222665` |

Both ZIPs pass integrity, safe-path, duplicate-entry and exact manifest path/hash checks. The release manifest covers all 37 other payloads; the review manifest covers all 35. The review packet's nested release manifest and SOURCE-IDENTITY are byte-identical to the full release copies. All six separately attached documents match the manifested review files.

The full release manifest SHA-256 is `a6b42c9852346e8f4b3bc561030a7171052d1431978df5d39063247538264009`; the review manifest SHA-256 is `a07674abf69b50c91d50f54e1c1ef1ce6bde49a430d2a9e88b21e6ef688784b9`.

## Source and package correspondence

Both supplied diffs replay against the previously reviewed source. All old/new Git blob identities match: 16 old and 17 new blobs in baseline-to-product, and four old and 12 new blobs in product-to-final. All 17 directly included repository documents match the reconstructed final source. The final delta changes records, release locks, packaging and qualification scripts; it does not introduce later product/client behavior changes.

All nine supplied wheel archives have valid RECORD entries and safe paths. No .pth, sitecustomize.py or usercustomize.py startup hooks were present. The 34 packaged server module files, eight Python-client module files and nine npm payload files match the reconstructed source byte-for-byte. The npm package declares version 0.2.2, Node >=24 <25, no dependencies and no lifecycle scripts.

The v1 schema remains unchanged across its four copies at SHA-256 `a2bbb2052f078242a5098a09d1ae4ff46cc2b1554fa1bfa7719a6a7ab00c03b9`. V2 remains unchanged across its four copies at `ea2c4b2babd95237478ecbcc619a4dbbe8b23a49722a8a6e0c2f6886e537e3cd`. The contract adds a compatible explanation of mixed-version admission and historical projection.

Acceptance is anchored to the attached bytes and this source correspondence. The Git commit objects and live origin ref were not independently queried here; remote publication remains executor-reported.

## Checks performed

| Check | Independent result |
| --- | --- |
| V1 offline contract | PASS: 11 positive, six negative shapes |
| V2 offline contract | PASS: five events, two snapshots, six negative cases, six response states |
| Submitted authenticated HTTP suite | PASS: 14/14 tests |
| Additional connected-lineage check | PASS: 11 HTTP steps |
| Exact service/Python/npm artifact install | PASS: clean isolated consumers, supplied archives only |
| Installed mixed-version and historical continuation | PASS |
| Installed duplicates, receipt recovery and restart | PASS |
| Independent retained accounting and historical-row hash | PASS |

Review runtime was Python 3.12.14 and Node 24.22.1; executor qualification recorded Python 3.12.16. The service and Python client ran from separate clean virtual environments. The Python client dependency lock was enforced using no-index/hash-checked installation. npm installed the exact tarball offline with lifecycle scripts disabled. No dependency acquisition, real provider, paid operation, Docker operation, owner-profile change or deployment occurred. All disposable service processes were stopped.

One reviewer setup failure, npm trying to use an unavailable default cache, was retained and resolved by using a private workspace cache. It required no product change and is not a finding.

## IC03-01 closure evidence

### Both mixed-version arrival orders

The exact installed Node client submitted a v2 orphan lineage followed by an incompatible v1 start. The new event rejected with 409 EVENT_CONFLICT and retry_guidance=never. The installed Python client exercised v1-start-first followed by v2-lineage, producing the same rejection. Valid unrelated work was accepted after each conflict.

### Continued ingestion in the same historical dataset

The original 0.2.0 wheel was not attached. For independent execution, the previously reviewed 0.2.0 source service created the historical fixture through ordinary authenticated HTTP. Its stopped database was copied into the exact installed 0.2.2 service. The executor's retained evidence separately records creating its fixture using an installed 0.2.0 wheel.

The installed successor:

- Keeps the accepted historical contradiction visible as binding_conflict.
- Accepts an unrelated new attempt in that same dataset.
- Rejects a new child touching the inconsistent component.
- Preserves accepted event bodies, receipts and monetary history.
- Preserves the result through ordinary restart and read-only receipt/report/export verification.

The historical dataset reconciles to three attempts, five events, known simulated USD 0.010000000 and two attempts without observed usage/cost. The priced old attempt still has unknown native usage with known cost. Neither unobserved attempt is represented as a zero-cost observation.

Across four synthetic installed-test datasets, the census is 12 events and eight attempts. Rejected probes and read-only restart verification leave that census unchanged. A pure-v2 child links to its valid late predecessor.

### Connected-component protections

The code now validates all starts against retained lineage and checks the proposed event's bidirectionally connected component. Unrelated inconsistent components cannot veto new capture. The independent 11-step check exercises a three-attempt chain, a late ancestor, incompatible v1 ancestor, wrong logical/task identities, a three-node cycle, duplicate receipt equality and unrelated work after rejection. All pass. Existing identity, task, scope, cycle and unknown-only-enrichment protections remain in place.

## Independent accounting and preservation audit

The retained corrected JSON, CSV and export agree on every CSV field, all included attempt/event identities, effective cost and account/actor/workflow rollups. Exactly one new event/attempt was added to the old historical cohort: event.attempt.after / attempt.after. The old unrelated attempt's existing report fields are unchanged. The contradictory attempt changes only the intended projection: fallback to unknown, predecessor cleared and pending_predecessor to binding_conflict. Its usage and cost are unchanged.

The old-record hash independently recomputes from the corrected export:

`0447936f45c8698c21e18bd9e9fe7d041ad074dd9f44fd57d577d17ad095b82b`

It matches the old-seed, successor-seed, restart, conflict-probe and validation records, and the independent installed replay. Its scope is exactly four event_id/digest/record rows and two attempt_id/record rows in the documented order. It is not a whole-database hash and does not cover receipts, accounts or dataset metadata; those claims are supported by their separate checks. This audit does not independently observe the original Mac database transition.

## Readiness criteria and remaining work

The accepted local product provides the documented observation/account contract, exact installable clients and service, scoped ingestion, stable receipts, effective-once accounting, explicit unknowns, reports/export and compatible persistence behavior. Prior backup-restoration evidence remains applicable to the unchanged persistence path; this successor adds installed historical continuation and restart verification for the changed admission path.

The following work belongs to the next milestone:

1. Inventory and instrument the whole Vega platform, including agents, services, delegation, background jobs and every provider execution path.
2. Implement a durable exporter with visible backlog/errors and stable delivery identities; telemetry recovery must never replay model work.
3. Enforce account/model eligibility before new selection while retaining valid accounting for earlier, in-flight or out-of-policy observed work.
4. Adopt the exact real feature-retention policy and activate a fresh cohort at a recorded T0 after synthetic integration acceptance.
5. Demonstrate complete local platform coverage before qualifying separate deployed services and the chosen production persistence topology.

The current local release uses loopback SQLite, unpaginated reports and a 16 MiB client response bound. The Vega integration must account for these limits without silently dropping or truncating observations. A hosted private registry is optional for local work; consume immutable private release archives and keep versions/hashes pinned. Classifier training/routing begins later at Larry's direction. Pre-T0 historical import remains deferred.

## Timing record

The progress record gives the Integration Readiness implementation start as October 27 at 18:04:47 Toronto. Independent acceptance is recorded October 28 at 12:11:51 Toronto: **18 hours, seven minutes, four seconds of calendar elapsed time**.

Correction 03 itself began October 28 at 11:06:36 EDT according to progress. Larry supplied the executor's **57 minutes, 49 seconds** worked-time report and 12:04 p.m. return. Preserve that as reported execution time rather than infer hours worked for the entire milestone. This is Day 2 of the original October 26 tracking baseline. The original forecasts and the separate DEV-12 exception remain unchanged.

## Evidence map

- input-integrity.json and source-reconstruction.json: exact archive/source checks.
- contract-results.json and http-suite.log: reproduced contract and 14-test results.
- lineage/component_probe.py and .json: connected-component closure.
- evidence/audit_retained.py and audit.json: independent financial and historical-row audit.
- installed/archive-audit.json and installed-result.json: exact package correspondence and installed execution.
- installed/install-commands.json, execution-commands.json, scripts/logs and evidence/: retained replay.
- installed/safe-artifacts.json: deliverable whitelist; runtime directories, credentials, databases, caches and environments are excluded from the review handoff.
