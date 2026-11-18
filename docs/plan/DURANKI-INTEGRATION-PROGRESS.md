# Duranki Integration Readiness — execution progress

**Independent closeout (2026-10-28 12:11:51 EDT):** [Independent Review 04](../development/integration-readiness/INDEPENDENT-REVIEW-04-2026-10-28.md) accepts `READY_FOR_VEGA_PLATFORM_INTEGRATION` for contract v2 and the exact 0.2.2 local release. IC03-01 and the prior reviewed integration findings are closed for this scope. Vega platform instrumentation and real T0 remain later work; the real feature-retention policy is still `PROPOSED`, and DEV-12 `CT02-02b` remains `OPEN/PARTIAL`.

**Node security correction (2026-10-28):** [Current source pins](../security/NODE-OCTOBER-2026-FIX-2026-10-28.md) select fixed Node 24.22.1 and private JavaScript client 0.2.3. The corrected 0.2.2 accounting service, exact release archive and independent-review status below are unchanged. The next milestone is the separately authorized Vega platform integration.

**Correction 03 start:** 2026-10-28 11:06:36 EDT (`2026-10-28 15:06:36 UTC`), branch `dev12/operation-contract`, actual commit `d3d533a47c3addcc503c2d6b6ba0c06bb0340b9d`. **Current stage:** corrected 0.2.2 local release verified under [Correction 03](DURANKI-INTEGRATION-CORRECTION-03.md). **Current executor disposition:** `READY_FOR_VEGA_PLATFORM_INTEGRATION`; Independent Review 04 has accepted this successor. Independent Review 03 held the preceding 0.2.1 release for IC03-01. Historical executor claims remain preserved separately.

| Finding | Status | Implementation and evidence needed |
| --- | --- | --- |
| IC03-01 mixed-version lineage and continued ingestion | VERIFIED | `integration_accounting.py`, contract clause, 14 focused HTTP tests; installed 0.2.0 accepted history copied to 0.2.2, same-dataset continuation, both mixed orders, pure-v2 control, unchanged old hash, JSON/CSV/export and restart |
| IC02-02–IC02-05 | VERIFIED | Independent Review 03 closes these for the local scope; retain prior evidence and avoid unrelated reruns |

**Correction 03 release:** plan `90136b9`, tested product/client source `6fc9434f7aa0a120b04c94931f28c3112bc333c7`, installed scripts/lock `98009d0`. Private 0.2.2 release ZIP: `/Users/larrymitchell/Mach33/Duranki-artifacts/integration-correction03-20261028-01/candidate1/duranki-integration-service-0.2.2.zip`, 863363 bytes, SHA-256 `2ebfe4a380f43523f604a3233b897fca59cc370c8a4b50597d1ca0a7da12db22`. The [current result](../development/integration-readiness/RESULT.md) and [validation record](../development/integration-readiness/CORRECTION-03-VALIDATION.json) identify the exact installed checks and limits. The real feature-retention policy remains `PROPOSED`; CT02-02b stays `OPEN`.

**Correction 03 next executable action:** separately authorized Vega execution-path inventory, durable exporter and eligibility integration before real T0. Do not replay model calls for telemetry.

**Correction 02 start:** 2026-10-28 09:22:52 EDT (`2026-10-28 13:22:52 UTC`), branch `dev12/operation-contract`, actual commit `79997c469d404f10bc60d8cf28bd48c7447f8db8`. **Stage at 0.2.1 closeout:** local release verified. **Executor disposition at that time:** `READY_FOR_VEGA_PLATFORM_INTEGRATION` under [Correction 02](DURANKI-INTEGRATION-CORRECTION-02.md), subject to the limits in its [preserved result](../development/integration-readiness/RESULT-v3.md). Independent Review 03 later held that readiness claim for IC03-01; the preceding v1/v2 executor results remain historical.

| Finding | Status | Implementation path and required evidence |
| --- | --- | --- |
| IC02-01 lineage arrival orders | VERIFIED | `integration_accounting.py`; both-order HTTP case, installed Python/Node cases, old-mismatch safe projection |
| IC02-02 eligibility ordering | VERIFIED | Service and v2 response contract; immediate/delayed same-second and stale/denied HTTP cases; installed assessment/export |
| IC02-03 snapshot reference binding | VERIFIED | Service/report/export; both-order/wrong-kind/foreign-attempt/old-mismatch HTTP and installed cases |
| IC02-04 native usage projection state | VERIFIED | V2 JSON/CSV, contract and installed client; five knowledge combinations and copied v1/v2 histories |
| IC02-05 exact review manifest | VERIFIED | Review packager checks exact ZIP path set and hashes, including nested `retained/final-release/MANIFEST.sha256` |

**Correction 02 decision:** Preserve closed IR01–IR03, IR05 and IR06 and the substantive IR04 accounting. Restrict new work to the three consistency defects and two projection/packaging cleanups. Retain v1/v2 artifacts and accepted records; publish new versioned local artifacts after installed verification. The real feature-retention policy remains `PROPOSED`; CT02-02b stays `OPEN`.

**Correction 02 release:** plan `3ab88a2`, implementation `e1381f5`, exact tested product/client source `c8433bb9388a9503d814929a780c6840ee63396c`. Private 0.2.1 release ZIP: `/Users/larrymitchell/Mach33/Duranki-artifacts/integration-correction02-20261028-01/candidate2/duranki-integration-service-0.2.1.zip`, 859618 bytes, SHA-256 `cc578074609f4829969ebe5072c44a29f78e8aa6cffc7d8235b6a8487a498c56`. The [validation record](../development/integration-readiness/CORRECTION-02-VALIDATION.json) and [preserved result](../development/integration-readiness/RESULT-v3.md) identify the installed 0.2.1 checks, restart, restore, v1/v2 copies and reconciled amounts. The real retention policy stays `PROPOSED` and CT02-02b stays `OPEN`.

**Next action recorded at the Correction 02 checkpoint:** independent review of its compact bundle and the real-retention policy decision; then separately authorized Vega execution-path inventory, durable exporter and eligibility integration before real T0. Do not replay model calls for telemetry.

**Original start:** 2026-10-27 22:04:47 UTC (18:04:47 America/Toronto), branch `dev12/operation-contract`, commit `f97612944639761d153c77b161c7730e32c71705`. **Correction 01 start:** 2026-10-27 22:28:48 EDT, same branch at `4ffe57e6c257b136ef9267afa9b9334c9023f9de`. **Stage at 0.2.0 closeout:** corrected local release complete. **Executor disposition at that time:** `READY_FOR_VEGA_PLATFORM_INTEGRATION` for the v2 local interface. The earlier v1 claim and Correction 01 result remain preserved in [RESULT-v1.md](../development/integration-readiness/RESULT-v1.md) and [RESULT-v2.md](../development/integration-readiness/RESULT-v2.md). Real feature-policy adoption and cohort activation were pending owner decisions for the following Vega milestone.

The [Correction 01 commission](DURANKI-INTEGRATION-CORRECTION-01.md) governs this successor. The independent review found three reproduced defects and six capture-contract gaps. The original v1 release and its evidence remain intact.

| Correction | Status | Intended implementation and verification evidence |
| --- | --- | --- |
| IR01 Typed timestamps | VERIFIED | `server/src/duranki_server/integration_accounting.py`, both clients; v1/v2 HTTP, installed timestamp-like ID and real-date negative cases |
| IR02 Encoded identifier routes | VERIFIED | API/operator one-time decode; both installed clients, operator smoke and Chrome encoded-account change, malformed separators denied |
| IR03 Outcome projection | VERIFIED | Service v1 fallback and v2 admission; HTTP JSON/CSV and copied v1-to-v2 upgrade |
| IR04 Independent units/cost knowledge | VERIFIED | V2 schema/ledger/clients/report; HTTP revision/zero/gap cases; installed known USD 0.030000000 plus one unknown |
| IR05 Unresolved/ineligible accounts | VERIFIED | V2 unresolved observation/resolution and selection flags; cross-owner HTTP, installed late accounting after disable |
| IR06 Operation identity | VERIFIED | Bounded v2 family/model-state schema; HTTP families and installed model-less search |
| IR07 Retry/fallback lineage | VERIFIED | Distinct logical/attempt links and cycle/cross-dataset guards; HTTP and installed once-only rollup |
| IR08 Eligibility decision evidence | VERIFIED | Persisted answer/revision/digest, selected-action binding and export; HTTP/installed verified versus current disabled state |
| IR09 Durable feature/decision snapshots | VERIFIED | Allowlist, separate content/digest/retrieval/export/expiry; HTTP, installed two snapshots, restore and proposed real-data policy |

**Correction decision:** publish contract v2 and new service/client versions. Keep v1 artifacts and stored records readable. Retention horizons require owner adoption before real collection; synthetic policy machinery can be implemented now. No provider execution or owner-profile change is permitted.

**Correction release:** Plan checkpoint `5e0b125`, implementation `c22a71d`, installed-client fixes/tests `4462269`, release instructions/packager `4f61873`. Exact installed candidate-3 product/client bytes correspond to source through `4462269b190acd3e0deacedfd65eb46aca48058f`; release docs/packager at `4f6187397ae340542248b6931660d42d0dddfe71`. V1 contract and archive bytes remain unchanged. The v2 offline checker passes 5 positive events, 2 snapshots and 6 negatives; the authenticated HTTP suite passes 8 tests. Clean installed 0.2.0 clients and service pass seed, restart, backup restore and copied v1 upgrade, with JSON/CSV/export reconciliation. The operator and actual browser encoded-account checks pass. Evidence paths and results are in [RESULT-v2.md](../development/integration-readiness/RESULT-v2.md).

**Correction artifacts:** Private root `/Users/larrymitchell/Mach33/Duranki-artifacts/integration-correction01-20261027-01/candidate3/`; `duranki-integration-service-0.2.0.zip` SHA-256 `fa861dbf729aafbf84b3e9c0614c384f32859f384929d8bae441eb3cfbd983b2`, 853016 bytes; service wheel `23f10e0da68badc264207a5f609a2d0787ebb956f92b521ebe023a61ed2554ed`, Python wheel `46a2c4c17ed5bbf5d7b51ffa49585320f1e0d8386cd3b6c3ea5100702b64e199`, npm tarball `7d6544a12776f9d04e3c4b736c555757cfdb93e8e118dea62acec6f37b5a5d3a`. Manifest and ZIP passed integrity checks. No real dataset or operational record was changed.

**Next action recorded at the Correction 01 checkpoint:** inspect its compact review bundle and adopt/narrow the proposed real feature-retention policy; then begin the separately authorized Vega execution-path inventory and exporter/eligibility integration before selecting real T0. Do not import pre-T0 activity or replay a model call to recover telemetry.

## Historical v1 release record

Read the [approved plan](DURANKI-INTEGRATION-READINESS.md) and this record before further milestone work. Initial plan checkpoint `35f4369`; Stage 1 contract `5af6e72`; service/clients `a82348f`; scoped reporting correction `545acab`. Exact v1 tested product source: `545acab617145ded973cd59c45775d9d9eed08ba` (tree `a54c2d21a91ca0b46e09742cbff9566b6c23a3a4`). DEV-12 technical qualification remains `PARTIAL` and CT02-02b remains `OPEN`; see its [delivery exception](../development/dev-12/DELIVERY-EXCEPTION-01.md).

| Requirement / criterion | Status | Implementation and verification evidence |
| --- | --- | --- |
| R1.1 Dataset, identity, membership | VERIFIED | [Contract v1](../contracts/integration-readiness-v1/CONTRACT.md), schema, offline checker; HTTP before-activation exclusion and late inclusion |
| R1.2 Separate context, decision, result, usage, outcome | VERIFIED | Eleven versioned examples; durable external events and installed two-agent demo |
| R1.3 IDs, receipts, duplicates, conflicts | VERIFIED | Contract cases, concurrent HTTP duplicate, conflict and installed recovery/no-extra-cost checks |
| R1.4 External credential references, eligibility | VERIFIED | Schema, operator register/disable and installed eligibility reads |
| R1.5 Scope, native accounting, unknowns | VERIFIED | Contract, exact-decimal ledger, scoped denial/read-only HTTP and explicit-zero cases |
| R2.1 Authenticated durable ingestion | VERIFIED | `integration_accounting.py`, `web.py`; five focused HTTP tests and packaged service demo |
| R2.2 Activity history and effective-once rollups | VERIFIED | Immutable events, 33-revision case, distinct retry and inclusive run rollups |
| R2.3 Account management and late accounting | VERIFIED | Registry/operator API/UI; correction accepted after disable |
| R2.4 Reports and exports | VERIFIED | JSON/CSV same three included attempts; independently reconciled known USD 0.055000000 and one unknown |
| R2.5 Scope denial and concurrency | VERIFIED | Admin/ingest/read-only separation, wrong-scope denial, simultaneous duplicate HTTP test |
| R2.6 Build, migration and persistence | VERIFIED | Offline wheel, isolated 0.0.0→0.1.0 migration, ordinary restart, online backup and separate restore |
| R3.1 Installed clients | VERIFIED | Clean Node 24 npm and CPython 3.12 wheel installs; both exercised contract v1 against packaged service |
| R3.2 Combined release and instructions | VERIFIED | Historical [v1 release instructions](../development/integration-readiness/RELEASE-v1.md), [v1 result](../development/integration-readiness/RESULT-v1.md), extracted ZIP installs and demo |
| C1 Contract implemented | VERIFIED | Contract v1; all four schema copies SHA-256 `a2bbb2052f078242a5098a09d1ae4ff46cc2b1554fa1bfa7719a6a7ab00c03b9` |
| C2 Clean packaged service | VERIFIED | Extracted ZIP, clean final service wheel and `package_smoke.py` fresh authenticated event/receipt; no charge |
| C3 Exact installed clients | VERIFIED | Node `v24.22.1` and CPython `3.12.15` release checks; separate clean extracted installs |
| C4 Attribution and reconciliation | VERIFIED | Two agents, delegated run, distinct retry, revisions, unknown and JSON/CSV reconciliation |
| C5 Usability and authorization | VERIFIED | Eligibility changes on disable, late accounting allowed, scoped tests |
| C6 Restart and restore | VERIFIED | Dataset, receipts and amounts retained through both |
| C7 Compatibility and limits | VERIFIED | Versions, hash manifest, local instructions and explicit deployment limits |

**Decisions:** External observations use `/integration/v1/` and additive SQLite tables, separate from controlled wire 0.2/0.3, reservations and sender records. The release runs `integration_only` on loopback without a model worker. Dataset activation is immutable and owner controlled; release tests use a synthetic activation, while actual Vega activation is the next milestone. Out-of-order usage is retained; only the latest contiguous revision contributes. Zero requires evidence; unknown remains unknown. Clients cap JSON responses at 16 MiB and do not automatically retry. Exact frozen Python dependency wheels, including certifi 2026.10.19, are bundled with hashes. No dependency upgrade was needed.

**Artifacts:** Private local directory `/Users/larrymitchell/Mach33/Duranki-artifacts/integration-readiness-20261027-01/final-release/`. ZIP `duranki-integration-service-0.1.0.zip` SHA-256 `7d5c31cbd7d394447076639f7b327b868e4c8e533566c9324881d18fe78d5209`; npm `packages/mach33-duranki-client-0.1.0.tgz` `65512c34f548a19e66e4dfba786dcc01d4836038588970c26b2898b1399f3833`; Python wheel `packages/mach33_duranki_client-0.1.0-py3-none-any.whl` `8753d65387d52840006911d9379ae1d1eee535ff02c46ab8d2a8557e1d8df3ae`; service wheel `packages/mach33_duranki_server-0.1.0-py3-none-any.whl` `7c1a379961d599511e6c02d28fb675da6e9cd3c1a03e3270f4d566948f8eb2a0`. Self-excluding `MANIFEST.sha256` SHA-256 `bb3e3486c7d4c975ce8f6315321f28c8d65f459445a2366ba28adef1847e3e04`; all entries verified. Local/private only; no registry publication or claimed off-machine backup.

**Observed v1 checks:** Offline contract 11 positive/6 negative, USD 0.050000000 example. Five authenticated HTTP tests passed. Installed combined seed, ordinary restart verification and separate backup restoration each passed: three included attempts, one excluded early attempt, one unknown-cost included attempt and known USD 0.055000000. A fresh final-wheel package smoke accepted one non-model event, returned the same duplicate/recovered receipt and reported no charge. Restored demo DB: 16 external events, zero controlled submissions or sender ownership. Operator HTTP registration/disable/report/isolation passed. Headless Chrome 1440×900 and 860×900 passed, with 15 local GETs and one local login POST, no external page request or provider call. Private screenshots: `final-run/browser-evidence/integration-desktop.png` SHA-256 `417a4a8a754146970dd618ba9396e773f01fdb44d7e2bad0f8ef191503bea2fc`; `integration-narrow.png` SHA-256 `b02d82d4eac8f109139f56e222a62e9fe92e4272d161be1a74154f1ceebaea66`. Detailed historical commands and results are in the [v1 result](../development/integration-readiness/RESULT-v1.md).

**Open inputs and limits:** The inspected `mach33-platform` checkout `e69a1fce53917603d110bdd386bde1547a82196d` declares Node `>=24 <25` and `.nvmrc` = `24`; no Python runtime declaration was found in its top three levels. Vega instrumentation, durable exporter/backlog, eligibility enforcement and real cohort activation are deliberately not included. A deployed topology needs separate database, scale, authentication and persistence qualification. No commercial tariff, real provider or production deployment was tested.

**Next executable action:** Start the separately authorized Vega integration: inventory real execution paths and identities, implement durable export, enforce eligibility before new selection, then activate the real fresh dataset at an owner-chosen time. Do not import earlier activity into that cohort or replay model work for telemetry recovery.
