# Integration Readiness correction 01 — local release result

**Disposition: `READY_FOR_VEGA_PLATFORM_INTEGRATION` for the corrected local contract v2 service and clients.** This is readiness to begin Vega instrumentation, not Vega execution coverage, live dataset activation, provider qualification or production deployment. The earlier v1 READY claim is retained in [RESULT-v1.md](RESULT-v1.md) as historical executor evidence; independent review required this correction. DEV-12 `CT02-02b` remains `OPEN` and its technical qualification remains `PARTIAL`.

**Source and branch:** `dev12/operation-contract`; correction start `4ffe57e6c257b136ef9267afa9b9334c9023f9de`; tested product/client source through `4462269b190acd3e0deacedfd65eb46aca48058f` (tree `0d70f3d270a7b2b7652f943eec75e6731afbcb1b`); release instructions/packager commit `4f6187397ae340542248b6931660d42d0dddfe71`. The exact installed candidate-3 package bytes were built from the same product/client sources before the documentation commit. No controlled sender campaign or owner-profile update was performed.

## Corrected scope and evidence

| Finding | Implemented behavior | Focused evidence |
| --- | --- | --- |
| IR01 | Typed calendar timestamps; legal `event.TimeZ` ID retained | v2 checker; authenticated HTTP; installed Node/Python receipt recovery |
| IR02 | One-time decoded identifier route segment; colon IDs; malformed/forbidden separators denied | HTTP, both installed clients, operator smoke and actual browser click at 860 px |
| IR03 | Legacy missing outcome reports `not_observed`; v2 missing outcome rejected | HTTP JSON and CSV regression; installed v1 migration/upgrade |
| IR04 | Independent known/unknown native usage and cost, explicit zero evidence, contiguous revision accounting | v2 checker, HTTP negatives, installed two known amounts and one unknown, JSON/CSV/export |
| IR05 | Authorized unresolved account is retained; same-dataset resolution and reported identity preserved; disabled/denied evidence separate from past execution | HTTP cross-owner tests, installed unresolved/resolved and late accounting after disable |
| IR06 | Bounded operation family and model-less state | HTTP family cases; installed `search` model-less attempt |
| IR07 | Distinct logical/attempt IDs, retry/fallback/fan-out and late predecessor linkage; cycles/cross-dataset denied | HTTP cases; installed fallback, separate attempts and once-only rollup |
| IR08 | Immutable eligibility response/revision/digest linked to selected action; current state not substituted for selection-time evidence | HTTP and installed answer, report/export and disabled-account read |
| IR09 | Allowlisted versioned snapshot contents stored separately with digest, retrieval/export, explicit unavailable/expired and synthetic expiry/purge | HTTP integrity/expiry; installed two snapshots; restore; [proposed policy](../../plan/DURANKI-INTEGRATION-FEATURE-RETENTION-POLICY.md) |

Contract v2 is [here](../../contracts/integration-readiness-v2/CONTRACT.md), with schema, examples and executable checker. V1 routes, schemas and stored rows remain supported. Older records show successor fields as absent; they are not rewritten. The new observation path stores no fictitious controlled submission, reservation or sender evidence.

## Exact private release

Root: `/Users/larrymitchell/Mach33/Duranki-artifacts/integration-correction01-20261027-01/candidate3/`. All named package archives are version 0.2.0; API contract is version 2. The ZIP was assembled from the exact installed candidate-3 archives and web assets; no dependency was acquired for this correction.

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `duranki-integration-service-0.2.0.zip` | 853016 | `fa861dbf729aafbf84b3e9c0614c384f32859f384929d8bae441eb3cfbd983b2` |
| `packages/mach33_duranki_server-0.2.0-py3-none-any.whl` | 144451 | `23f10e0da68badc264207a5f609a2d0787ebb956f92b521ebe023a61ed2554ed` |
| `packages/mach33_duranki_client-0.2.0-py3-none-any.whl` | 31622 | `46a2c4c17ed5bbf5d7b51ffa49585320f1e0d8386cd3b6c3ea5100702b64e199` |
| `packages/mach33-duranki-client-0.2.0.tgz` | 24551 | `7d6544a12776f9d04e3c4b736c555757cfdb93e8e118dea62acec6f37b5a5d3a` |

The ZIP's self-excluding `MANIFEST.sha256` is `f71062bdbf946b3bd132cf13e03b2c7361fd6d2ad63f12e7cc9f41878d53948c`; all 35 payloads passed `shasum -a 256 -c`. `unzip -t` passed. The versioned [release instructions](RELEASE.md) specify clean offline installation, exact package compatibility, additive migration and consistent backup/restoration. The private archives have no claimed hosted registry or off-machine backup.

## Executed checks and observed calculations

Toolchain: CPython 3.12.15, Node 24.22.1, uv 0.13.5. The v1 offline checker passed 11 positives and 6 negatives, USD 0.050000000 example. The v2 offline checker passed 5 positive events, 2 snapshots, 6 negatives and independent USD 0.030000000. The focused authenticated HTTP suite passed **8/8** tests, including retained v1 regressions and v2 negative cases. JavaScript syntax and `git diff --check` passed.

The installed synthetic release used clean Python and Node consumer environments with the exact 0.2.0 archives, the packaged service wheel, frozen dependency wheels and the local loopback HTTP surface. Its seed, ordinary restart verification and independent backup restoration each passed with **three included attempts, 11 events, two snapshots and known USD 0.030000000**. The independent arithmetic is USD 0.020000000 + USD 0.010000000; a third included attempt retains native usage with unknown monetary cost. The same three attempts and known subtotal reconcile in `instance/evidence/final-report.json`, `final-report.csv` and `final-export.json`. The duplicate receipt `event.TimeZ` did not add a charge; fallback is a separate attempt. The installed script asserts the exported effective amounts against its independent Decimal sum and CSV. The unknown attempt is not included in the known subtotal.

The separate v1-to-v2 copied-database upgrade passed: three historical included attempts, known USD 0.055000000 and successor fields explicitly absent. Operator smoke passed encoded account state and two invalid encodings. Headless Chrome passed an actual operator UI state-change click on the encoded account at 860 px, with no clipped controls; it observed **19 local GETs and 3 local POSTs** (login plus two account-state writes), no external page requests. The browser screenshot `evidence/integration-correction-encoded-account.png` is synthetic only, SHA-256 `46c1ced3ba624cd579881d865ceb21ec01dacd08ef803a930d664433ca57c26f`.

Before/after read-only refresh the isolated database counts remained events 11, attempts 3, snapshots 2, eligibility reads 2, controlled submissions 0 and sender ownership 0. The restored instance reproduced the same report/receipt/snapshot result. All disposable services and Chrome were stopped. No provider call, commercial spend, real cohort activation or owner operational write occurred.

**Corrected failures retained:** installed candidate 1 rejected valid second-precision timestamps in Node; installed candidate 2 raised a Python schema-definition lookup error. Both were fixed before candidate 3, which passed. The initial restored verification used the original instance token against the separate restored secrets and failed authentication; it passed with the corresponding restored token. These earlier outcomes are diagnostic evidence, not successor passes.

## Remaining limits and next action

The [feature retention policy](../../plan/DURANKI-INTEGRATION-FEATURE-RETENTION-POLICY.md) remains **PROPOSED** for real data. Larry must adopt or narrow the fields, classifications, source expiry and offline backup/export deletion rules before a real T0. The local default permits only synthetic low-class captured content. Vega must inventory actual operations and execution paths, implement a durable exporter/backlog and enforce eligibility before new selection. These are following-milestone tasks; the local contract records evidence but does not enforce Vega behavior. Pagination, scaled topology, PostgreSQL, deployed authentication and invoice reconciliation remain unqualified. No real provider rate, model, credential or spending authority is implied.
