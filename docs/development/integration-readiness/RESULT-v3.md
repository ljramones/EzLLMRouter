# Integration Readiness correction 02 — local release result

**Disposition: `READY_FOR_VEGA_PLATFORM_INTEGRATION` for the corrected local contract v2 service and installed clients.** This is readiness to begin platform instrumentation, not real dataset activation, live provider qualification or production deployment. The preceding v1 and v2 results remain in [RESULT-v1.md](RESULT-v1.md) and [RESULT-v2.md](RESULT-v2.md). DEV-12 `CT02-02b` remains `OPEN`; its controlled-execution qualification remains `PARTIAL`.

**Identity:** branch `dev12/operation-contract`; reviewed baseline `79997c469d404f10bc60d8cf28bd48c7447f8db8`; plan checkpoint `3ab88a2`; corrected product/contract `e1381f5`; exact tested product and installed-client source `c8433bb9388a9503d814929a780c6840ee63396c`. The release packages were built from these product/client contents and installed from the candidate-2 archives before the final documentation commit. The private release ZIP records the tested source in `SOURCE-IDENTITY.json`. No owner profile or real Vega data changed.

## Finding disposition and evidence

| Finding | Corrected behavior | Evidence |
| --- | --- | --- |
| IC02-01 | Incoming starts and lineage constrain each other in either order; only an unknown start can be enriched. Historical contradictions report `binding_conflict` and retain original bytes. | `test_correction02_lineage_both_orders_and_historical_conflict`; installed Python fallback and Node explicit-role rejection; JSON/export reconciliation |
| IC02-02 | The caller assertion remains immutable; the server separately reports `indeterminate` when second-resolution evidence cannot order a decision and mutation. Unambiguous stale/denied evidence still rejects incompatible assertions. | `test_correction02_eligibility_same_second_and_unambiguous`; installed Node eligibility/decision and Python JSON/CSV/export; restored assessment |
| IC02-03 | Snapshot references bind dataset, attempt, ID and kind in both arrival orders. Old incompatible refs report `binding_conflict` without borrowed content. | `test_correction02_snapshot_binding_both_orders_and_old_mismatches`; installed Node/Python negative and retrieval; JSON/export |
| IC02-04 | `usage_state` is independent from `cost_status` in v2 JSON/CSV, including known, unknown, not observed and legacy absent. | `test_correction02_usage_state_json_csv_and_export`; installed known native/unknown cost and unknown native/known cost; copied v1/v2 history |
| IC02-05 | The review manifest excludes only its root path and covers every other archived path, including the nested release manifest. | `package_correction_review.py` exact-set/hash verification; correction-02 review archive verification |

The contract and four synchronized schema copies retain v2 event shapes and add bounded response states. The v1 contract and historical archives are unchanged. Neither client transports a new request type; both installed clients exercise the compatible response fields. `eligibility_assessment` is a derived server verdict, not an alteration of caller evidence or a proof of Vega enforcement.

## Release and observed checks

Private root: `/Users/larrymitchell/Mach33/Duranki-artifacts/integration-correction02-20261028-01/candidate2/`. API contract remains v2; service, Python client and npm client are **0.2.1**. The release archive contains the same package bytes installed for the isolated run.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `duranki-integration-service-0.2.1.zip` | 859618 | `cc578074609f4829969ebe5072c44a29f78e8aa6cffc7d8235b6a8487a498c56` |
| `packages/mach33_duranki_server-0.2.1-py3-none-any.whl` | 145865 | `7e2d4871eff313825a2c527b5387782b627922a0d24959e3ebd3a7fba3d13e63` |
| `packages/mach33_duranki_client-0.2.1-py3-none-any.whl` | 32017 | `80798e7001a08faa5480377348ad66927512fb2bd750c70c20b5663be5989d11` |
| `packages/mach33-duranki-client-0.2.1.tgz` | 24830 | `5f8dc42eb5cf9926135548231ded9235fe8891baf25e56ec77a364c741038f43` |

The release's self-excluding manifest SHA-256 is `7198b547ca487e4815b0d39ca11cdaafd6eff7c61aa0db4b855e2785a05d85aa`. The packager checked exact ZIP path equality and every payload hash; `unzip -t` and `shasum -a 256 -c MANIFEST.sha256` passed for all 36 payloads. The [release instructions](RELEASE.md) specify the exact clean offline installation, compatibility, backup and limits.

Actual focused toolchain: CPython **3.12.16**, Node **24.22.1**. The v1 checker passed 11 positive and 6 negative cases with exact USD 0.050000000; the v2 checker passed 5 events, 2 snapshots, 6 negatives and 6 response states with independent effective USD 0.030000000. The authenticated HTTP source suite passed **12/12** tests. Node syntax and `git diff --check` passed. The new source cases cover both arrival orders, same-second delayed evidence, foreign/wrong-kind snapshots, old accepted mismatch projections, explicit knowledge states and immutable duplicate/conflict behavior.

Clean installed 0.2.1 Python and Node consumers exercised normal authenticated HTTP against the isolated 0.2.1 service. Seed, restart and separate consistent-backup restoration passed. Each reported **3 included attempts, 9 events, 2 captured snapshots, 1 unknown-cost attempt and known USD 0.030000000**. Independent arithmetic is USD 0.020000000 + USD 0.010000000. JSON, CSV and dataset export agree, and receipt recovery/read-only verification added no attempt or charge. The Node decision retained caller `verified` while the server correctly assessed the tied-second evidence `indeterminate`. The fallback and base attempts remain distinct; a bad snapshot reference and explicit-role lineage rewrite were rejected.

The installed 0.2.1 service opened isolated **copies** of retained v1 and v2 databases. The installed client read three v1 attempts, USD 0.055000000 known and one unknown-cost attempt, with successor fields `legacy_absent`; the v1 endpoint still agreed. It read three retained v2 attempts, USD 0.030000000 known and one unknown-cost attempt with the new projection fields. The focused source tests also inject historical accepted contradictory rows and assert safe report/export projection without rewriting them. These checks did not mutate the original retained databases.

The first local candidate package exposed a stale 0.2.0 startup banner despite 0.2.1 wheel metadata. It was stopped before seeding; `__version__`, the startup banner and local editable locks were corrected, then candidate 2 was built and tested. This diagnostic candidate is not the release. The [validation record](CORRECTION-02-VALIDATION.json) identifies executed commands and retained evidence.

## Limits and next action

The [real feature-retention policy](../../plan/DURANKI-INTEGRATION-FEATURE-RETENTION-POLICY.md) remains **PROPOSED** and must be adopted or narrowed before real T0. Vega must inventory execution paths, add durable export/backlog, enforce eligibility before new selection, and activate the fresh cohort in its separate milestone. The local release remains loopback SQLite with unpaginated reports and a 16 MiB JSON client bound. No deployed topology, invoice reconciliation, real provider, commercial tariff or off-machine artifact backup is claimed. No provider call, commercial spend, owner-profile write, controlled sender campaign or real dataset activation occurred.
