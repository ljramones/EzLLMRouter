# Integration Readiness correction 03 — local release result

**Independent Review 04 closeout (2026-10-28 12:11:51 EDT):** [The retained independent review](INDEPENDENT-REVIEW-04-2026-10-28.md) accepts `READY_FOR_VEGA_PLATFORM_INTEGRATION` for contract v2 and the exact local 0.2.2 service/clients. IC03-01 and the earlier reviewed integration findings are closed for that local scope. This acceptance does not activate Vega collection or adopt the proposed real feature-retention policy. DEV-12 `CT02-02b` remains `OPEN/PARTIAL` in its separate controlled-execution record.

**Node security addendum (2026-10-28):** The [focused Node correction](../../security/NODE-OCTOBER-2026-FIX-2026-10-28.md) selects fixed Node 24.22.1 and issues a private JavaScript client 0.2.3. This does not change the tested 0.2.2 service, the exact Correction 03 release ZIP, its historical installed results, or the independent-review status below.

**Executor disposition: `READY_FOR_VEGA_PLATFORM_INTEGRATION` for the corrected 0.2.2 local service and clients.** Independent Review 04 accepted this exact local release. The reviewed 0.2.1 result had one partial lineage finding, IC03-01; that result is preserved in [RESULT-v3.md](RESULT-v3.md), with earlier results in [RESULT-v1.md](RESULT-v1.md) and [RESULT-v2.md](RESULT-v2.md). DEV-12 `CT02-02b` remains `OPEN` and its controlled-execution qualification `PARTIAL`.

**Identity:** branch `dev12/operation-contract`; Independent Review 03 baseline `d3d533a47c3addcc503c2d6b6ba0c06bb0340b9d`; plan checkpoint `90136b9`; exact tested product/client source `6fc9434f7aa0a120b04c94931f28c3112bc333c7`; installed-check sources and lock `98009d0` plus the final scoped evidence refinement. The new package bytes were built from the tested product/client source. No old release archive or accepted record was rewritten.

## IC03-01 closure

`append_event` now checks a v1 start against already accepted v2 lineage. A v1 start has no logical-operation or attempt-role assertion, so it cannot satisfy a pending v2 lineage; the reverse order also rejects new v2 lineage for an existing v1 start. The validator checks the proposed event's connected lineage component, including late predecessors, descendants and cycles. An unrelated old contradiction no longer blocks new capture in the same dataset. A new event that touches an inconsistent component still conflicts. A previously accepted v1-start/v2-lineage pair reports `binding_conflict` without fabricating v1 role or predecessor fields. Existing receipts, event bodies and monetary revisions remain immutable.

The [v2 contract](../../contracts/integration-readiness-v2/CONTRACT.md) now states this compatible admission and projection rule. The request schema and client methods are unchanged. Independent Review 03 closed IC02-02 through IC02-05, IR08 and IR09 for their local scope; this release preserves those behaviors. The focused authenticated HTTP suite passed **14/14** cases, including both mixed-version orders, valid v1 and pure-v2 control, late predecessors, explicit-role and logical/task conflicts, cycles, duplicate receipts, and historical-conflict continued ingestion. Both offline contract checkers passed unchanged: v1 11 positive/6 negative and v2 5 events/2 snapshots/6 negative/6 response states.

## Installed historical continuation

A clean installed **0.2.0 service wheel** accepted a synthetic v2 orphan lineage, a contradictory v2 start, a USD 0.010000000 usage revision and an unrelated start through normal authenticated HTTP. Its four event records and two attempt records hash to `0447936f45c8698c21e18bd9e9fe7d041ad074dd9f44fd57d577d17ad095b82b`. The stopped database and synthetic credentials were copied into a separate 0.2.2 instance; the original fixture remains untouched.

The clean installed **0.2.2 service**, Python client and Node 24 client passed normal authenticated HTTP checks. Before and after new work, the old-record hash stayed identical. The new service reported the old attempt as `binding_conflict`, rejected a new child touching it with **409 `EVENT_CONFLICT` / `never`**, and accepted an unrelated new attempt in that **same historical dataset**. The corrected historical dataset has **3 attempts, 5 events, known USD 0.010000000 and 2 unknown-cost attempts**. An independent Decimal sum over the CSV matches the JSON subtotal; the export contains all five unique event IDs and three attempts. Duplicates and receipt recovery did not add an attempt or charge. Read-only verification after a service restart returned the same census, hash, receipts and subtotal.

The installed Node client tested v2-lineage-first then v1-start conflict, followed by accepted unrelated work. The installed Python client tested v1-start-first then v2-lineage conflict, followed by accepted unrelated work. Each conflict returned **409 `EVENT_CONFLICT` / `never`**. A separate pure-v2 dataset linked a child to its late predecessor. The respective attempt counts were **1, 2 and 2**, with no cost-bearing usage in these control datasets. A later rejected-event probe added zero accepted events. The [validation record](CORRECTION-03-VALIDATION.json) names the executed commands, actual runtimes and retained response files. The 0.2.1 restart/backup-restoration evidence remains applicable to the unchanged persistence path; the 0.2.2 historical-copy and restart checks cover the changed admission path.

## Exact private release

Private root: `/Users/larrymitchell/Mach33/Duranki-artifacts/integration-correction03-20261028-01/candidate1/`. API contract remains v2; service, Python client and npm client are **0.2.2**. The ZIP contains the exact installed package bytes and frozen dependency wheels.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `duranki-integration-service-0.2.2.zip` | 863363 | `2ebfe4a380f43523f604a3233b897fca59cc370c8a4b50597d1ca0a7da12db22` |
| `packages/mach33_duranki_server-0.2.2-py3-none-any.whl` | 146200 | `070b0f536f3e59f647f88bba04bd820febb5424adffcd8ef4e75b611f58c237e` |
| `packages/mach33_duranki_client-0.2.2-py3-none-any.whl` | 32017 | `eddff93e8f17bd6b472293774898c40f0cec20062050b26856d045a6ca11d600` |
| `packages/mach33-duranki-client-0.2.2.tgz` | 24933 | `8a3329e1017bca2c976b3fba0bfa21b8006f8199927134a9b005026b95222665` |

The release manifest SHA-256 is `a6b42c9852346e8f4b3bc561030a7171052d1431978df5d39063247538264009`; all **37** payload paths/hashes and ZIP integrity passed. Actual toolchain: CPython **3.12.16**, Node **24.22.1**, uv **0.13.6**. The [release instructions](RELEASE.md) give exact local installation, migration, backup and compatibility steps. No package registry or off-machine artifact backup is claimed.

## Limits and next action

The [real feature-retention policy](../../plan/DURANKI-INTEGRATION-FEATURE-RETENTION-POLICY.md) remains **PROPOSED** and needs an owner decision before real T0. Vega execution-path inventory, durable export/backlog, selection-time eligibility enforcement and actual cohort activation are the following milestone. This release remains loopback SQLite with unpaginated reports and a 16 MiB client response bound. No real provider call, commercial spend, owner-profile change, production deployment, public publication or DEV-12 sender campaign occurred.
