# Duranki v1.2 Correction 01 — dated assurance register

**As of:** 25 October 2026. **Status:** draft evidence map, not fresh execution or owner acceptance.  
**Normative requirements:** [DURANKI-ARCHITECTURE-v1.2-CORRECTION-01.md](DURANKI-ARCHITECTURE-v1.2-CORRECTION-01.md)  
**Machine-readable complete register:** [DURANKI-v1.2-C01-ASSURANCE-REGISTER.json](DURANKI-v1.2-C01-ASSURANCE-REGISTER.json)

## 1. Interpretation and evidence limits

This register resolves all 87 IDs: **86 canonical parent requirements and one retired alias (T-84 → T-49)**. It records 73 stable subcases. No parent has an unqualified PASS. A blank evidence cell means **not evidenced in the reviewed records**, not “not implemented”. Current repository, host, containers, credentials, provider accounts and owner-profile state were not inspected. Focused historical source/record checks are identified in the separate evidence supplement.

Use independent evidence dimensions: source implementation, controlled target, deployment observation, commercial qualification and integration. A prior component/controlled result can support a bounded part of a requirement, not the entire production obligation or new successor behavior. The JSON records full requirement text, profile, build/evidence, date, limits and remaining proof for every canonical parent and subcase.

**Source and deployment are distinct:** the DEV-11 record identifies tested source `86d1c8cb0d99c31660f8ef7ad7464e1b40e670f4` and fingerprint `e3157e9e235d8980d00ba6d264cca528e5beac5d09f981839221f9259b84e981`; its last reported running owner image was the earlier DEV-10 build. That historical statement does not establish today's runtime or allowance state. The final matrix used installed Python; earlier CommonJS/worker evidence was reused, not rerun wholesale. No real-provider call or invoice qualification is established by these receipts.

**Decision provenance:** PostgreSQL is carried from the owner's quoted 23 October decision (E-08), not a newly inspected transcript or fresh affirmation. The reconstructed Addendum A hash identifies received bytes, not its unavailable original. Valhalla 0.4 and the Proto proposal/evidence report remain absent; all R15/R16 correspondences remain attributed, not independently closed. None of these gaps justifies inventing a replacement or reversing the standalone-first direction.

## 2. Profiles

| ID | Scope |
|---|---|
| `S-LEGACY` | Qualified standalone legacy wire 0.2 operations, including separately evidenced caller-owned tools |
| `S-TEXT-CACHE` | Exact DEV-11 bounded cache-aware text contract; fictional controlled evidence distinct from paid activation |
| `S-RETRIEVAL` | Proposed DEV-12 typed embedding/rerank and shared metadata successor; not implemented by this packet |
| `S-ADMIN` | Local operator/API management and reporting within supported operations |
| `S-IMPORT` | Proposed offline spending-observation importer |
| `P-PRODUCTION` | Replicated/shared-state production gateway, HA, operational conformance |
| `P-EVALUATION` | Qualified cohorts, evaluation and eventual policy promotion |
| `P-LAB` | Office-origin/serving/capacity/drain profile |
| `P-LIFECYCLE` | Future qualified media/stream/session/adjacent-service lifecycles |
| `P-VALHALLA` | Future real verified commission/activation/federated budget integration |

## 3. Evidence catalogue

| ID | Date / subject | Scope |
|---|---|---|
| E-01 | 2026-10-17 — `wire 0.2 / duranki-work-v0.2 / initial_1a@1` | [WP-A-A2-ADOPTION-01.md](inputs/WP-A-A2-ADOPTION-01.md); Specification adoption only; no runtime result |
| E-02 | 2026-10-20 — `Run-11 source packet SHA256 9a3a3bda199b5fad6d63ccac6abd7837d534ed0c45cefb496645d89f56834a64` | [DEV-04-RUN11-INDEPENDENT-REVIEW-15.md](inputs/DEV-04-RUN11-INDEPENDENT-REVIEW-15.md); Prior independent review of bounded Choice B plaintext HTTP/1.1 separation and queued revocation; not a rerun here |
| E-03 | 2026-10-25 — `86d1c8cb0d99c31660f8ef7ad7464e1b40e670f4 / e3157e9e235d8980d00ba6d264cca528e5beac5d09f981839221f9259b84e981` | [RESULT(20261025-200121).md](inputs/RESULT%2820261025-200121%29.md); Executor-reported source/focused regressions and controlled observations, not product-source inspection here |
| E-04 | 2026-10-25 — `86d1c8cb0d99c31660f8ef7ad7464e1b40e670f4 / e3157e9e235d8980d00ba6d264cca528e5beac5d09f981839221f9259b84e981` | [TARGET-RESULT-02.json](inputs/TARGET-RESULT-02.json); Supplied final five-case controlled TLS receipt; installed Python path; arithmetic checked as data, not receiver logs/rerun |
| E-05 | 2026-10-25 — `86d1c8cb0d99c31660f8ef7ad7464e1b40e670f4 / e3157e9e235d8980d00ba6d264cca528e5beac5d09f981839221f9259b84e981` | [BROWSER-RESULT-02.json](inputs/BROWSER-RESULT-02.json); Supplied normal authenticated browser receipt, fictional mixed cache case; no browser rerun here |
| E-06 | 2026-10-25 — `platform e69a1fce53917603d110bdd386bde1547a82196d; Duranki d990b78ca48b8e673c0cbd0260d3e141e45c7e48` | [MODEL-SERVICE-COVERAGE-REPORT.md](inputs/MODEL-SERVICE-COVERAGE-REPORT.md); Static source reconnaissance report; no current source/runtime inspected here |
| E-07 | 2026-10-25 — `openai.responses.implicit-cache.v1 / openai.responses.text.cache.v2` | [CACHE-ACCOUNTING-CONTRACT.md](inputs/CACHE-ACCOUNTING-CONTRACT.md); Exact DEV-11 contract text; not a selected commercial model |
| E-08 | 2026-10-23 decision quoted in 2026-10-25 handoff — `document SHA256 e0c0394f862fd42ceba8726e19327a1429cb7caee16478c1df94a6419ca09fa2` | [DURANKI-ADDENDUM-A-RECONCILIATION-HANDOFF-2026-10-25.md](inputs/DURANKI-ADDENDUM-A-RECONCILIATION-HANDOFF-2026-10-25.md); Recovered owner decisions via quotation, not independently read original transcript |

| E-09 | 2026-10-21 — `Run-16 source a711e6e30a3bf950abd3ab3b873eaa8069ce9b93d7934dd47be72bbc772f535c; runtime adf88631c2026ae1e0648dcb9e141e5887580ece5a8a294c3ad3d7088ccfc341` | [DEV-05-RUN16-REVIEW-05.md](inputs/DEV-05-RUN16-REVIEW-05.md); Independent historical review of Run-16; bounded installed clients/tools/no-store and error cases; not re-executed here. |
| E-10 | 2026-10-21 — `Running source then 150127a37e953ee255d0dcd8b831f6c72e18c2f7; fingerprint 80ee4223546ccd93c6843b3efe9e33737ca34b0599d0673c2abeb460c185a9ee` | [DEV-06-RESULT-SUPPLIED-20261021-195653.md](inputs/DEV-06-RESULT-SUPPLIED-20261021-195653.md); Supplied living result: local console, independent receiver audit, ordinary restart and browser observations; author-reported records, no current runtime read. |
| E-11 | 2026-10-21 — `Owner target 7ead951b47c0bcebd0b25f174e0de685851ec5e2; fingerprint 53702db06f40a3c3c51b742818ae27e5018c50a526be70b22ee2abcf1dea2040` | [DEV-07-RESULT-SUPPLIED-20261021-232233.md](inputs/DEV-07-RESULT-SUPPLIED-20261021-232233.md); Supplied living result: registry, grants, prices, queued revocations, restart and catalogue component checks. This copy predates later catalogue/CRUD browser closure. |
| E-12 | 2026-10-21 recorded execution; 2026-10-25 mapping — `a711e6e30a3bf950abd3ab3b873eaa8069ce9b93d7934dd47be72bbc772f535c` | [DEV-05-EVIDENCE-CORRESPONDENCE.json](DEV-05-EVIDENCE-CORRESPONDENCE.json); Hash-verified Run-16 source/runtime manifests; inspected named test definitions and matching recorded suite exits. Inert correspondence only, no rerun. |

## 4. Canonical parent map

“Prior bounded” means only the stated partial source/receipt mapping. “Not evidenced” carries no assertion that nobody tested it elsewhere. New successor and future-integration obligations remain open. Requirement text and all proof fields are in the JSON; the clause column below is stable within this candidate.

| ID | Governing clause | Applicable profiles | Evidence / scoped status |
|---|---|---|---|
| T-01 | §5.1 | S-LEGACY, S-TEXT-CACHE, S-RETRIEVAL | E-12; partial historical map (supplement) |
| T-02 | §5.1 | S-LEGACY, S-TEXT-CACHE, S-RETRIEVAL | E-12; partial historical map (supplement) |
| T-03 | §5.1 | S-LEGACY, S-TEXT-CACHE, S-RETRIEVAL | None mapped; not evidenced |
| T-04 | §10.1 | P-PRODUCTION | None mapped; not evidenced |
| T-05 | §13.2 | S-LEGACY, S-TEXT-CACHE | E-09, E-10; partial historical map (supplement) |
| T-06 | §7.1 | P-LAB | None mapped; not evidenced |
| T-07 | §5.4 | S-LEGACY, S-TEXT-CACHE, S-RETRIEVAL | None mapped; not evidenced |
| T-08 | §5.3 | S-LEGACY, S-TEXT-CACHE, S-RETRIEVAL | E-09, E-11; partial historical map (supplement) |
| T-09 | §5.4 | S-LEGACY, S-TEXT-CACHE, S-RETRIEVAL | E-02, E-09, E-12; partial historical map (supplement) |
| T-10 | §10.4 | S-LEGACY, S-TEXT-CACHE | None mapped; not evidenced |
| T-11 | §10.4 | S-LEGACY, S-TEXT-CACHE | E-03; prior bounded only |
| T-12 | §10.4 | S-LEGACY, S-TEXT-CACHE | E-03; prior bounded only |
| T-13 | §8.5 | P-PRODUCTION | None mapped; not evidenced |
| T-14 | §8.2 | S-LEGACY, S-TEXT-CACHE, S-RETRIEVAL | E-04, E-09, E-12; partial historical map (supplement) |
| T-15 | §8.4 | P-PRODUCTION | None mapped; not evidenced |
| T-16 | §8.4 | S-LEGACY, S-TEXT-CACHE | E-09; partial historical map (supplement) |
| T-17 | §8.6 | P-PRODUCTION | None mapped; not evidenced |
| T-18 | §10.2 | S-LEGACY, S-TEXT-CACHE, S-RETRIEVAL | E-04, E-09; partial historical map (supplement) |
| T-19 | §5.4 | S-LEGACY, S-TEXT-CACHE | None mapped; not evidenced |
| T-20 | §5.4 | P-PRODUCTION | None mapped; not evidenced |
| T-21 | §5.1 | S-LEGACY, S-TEXT-CACHE | None mapped; not evidenced |
| T-22 | §10.8 | P-PRODUCTION | None mapped; not evidenced |
| T-23 | §6.6 | S-LEGACY, S-TEXT-CACHE | None mapped; not evidenced |
| T-24 | §5.4 | S-LEGACY, S-TEXT-CACHE, S-RETRIEVAL | E-02, E-11; partial historical map (supplement) |
| T-25 | §5.6 | P-EVALUATION | None mapped; not evidenced |
| T-26 | §11.4 | P-EVALUATION | None mapped; not evidenced |
| T-27 | §12.4 | P-EVALUATION | None mapped; not evidenced |
| T-28 | §6.7 | P-LAB | None mapped; not evidenced |
| T-29 | §7.3 | P-LAB | None mapped; not evidenced |
| T-30 | §6.6 | P-LAB | None mapped; not evidenced |
| T-31 | §11.1 | P-EVALUATION | None mapped; not evidenced |
| T-32 | §6.1 | P-EVALUATION | None mapped; not evidenced |
| T-33 | §7.3 | P-LAB | None mapped; not evidenced |
| T-34 | §6.7 | P-LAB | None mapped; not evidenced |
| T-35 | §12.4 | P-EVALUATION | None mapped; not evidenced |
| T-36 | §6.5 | P-EVALUATION | None mapped; not evidenced |
| T-37 | §4.4 | S-LEGACY, S-TEXT-CACHE | E-10, E-11; partial historical map (supplement) |
| T-38 | §4.4 | S-LEGACY, S-TEXT-CACHE | E-02, E-09, E-10; partial historical map (supplement) |
| T-39 | §4.4 | S-LEGACY, S-TEXT-CACHE | None mapped; not evidenced |
| T-40 | §4.3 | S-LEGACY, S-TEXT-CACHE | E-12; partial historical map (supplement) |
| T-41 | §4.4 | S-LEGACY, S-TEXT-CACHE | None mapped; not evidenced |
| T-42 | §5.7 | S-RETRIEVAL | None mapped; not evidenced |
| T-43 | §4.6 | S-LEGACY, S-TEXT-CACHE, S-ADMIN | E-05, E-10, E-11; partial historical map (supplement) |
| T-44 | §4.5 | S-LEGACY, S-TEXT-CACHE, S-ADMIN | None mapped; not evidenced |
| T-45 | §5.4 | S-RETRIEVAL | E-11; partial historical map (supplement) |
| T-46 | §5.3 | S-RETRIEVAL | None mapped; not evidenced |
| T-47 | §5.7 | S-RETRIEVAL | E-03, E-09; partial historical map (supplement) |
| T-48 | §10.8 | S-RETRIEVAL | E-04; prior bounded only |
| T-49 | §10.2 | S-RETRIEVAL | E-04; prior bounded only |
| T-50 | §10.4 | S-RETRIEVAL | E-03; prior bounded only |
| T-51 | §5.9 | S-RETRIEVAL | None mapped; not evidenced |
| T-52 | §5.9 | S-RETRIEVAL | None mapped; not evidenced |
| T-53 | §5.9 | S-RETRIEVAL | None mapped; not evidenced |
| T-54 | §5.9 | S-RETRIEVAL | None mapped; not evidenced |
| T-55 | §10.8 | S-RETRIEVAL | None mapped; not evidenced |
| T-56 | §4.6 | S-LEGACY, S-TEXT-CACHE, S-ADMIN | E-03, E-11; partial historical map (supplement) |
| T-57 | §4.6 | S-LEGACY, S-TEXT-CACHE, S-ADMIN | E-11; partial historical map (supplement) |
| T-58 | §6.9 | S-ADMIN, P-EVALUATION | None mapped; not evidenced |
| T-59 | §6.10 | S-ADMIN | None mapped; not evidenced |
| T-60 | §9.1 | S-LEGACY, S-TEXT-CACHE, S-RETRIEVAL, S-ADMIN | None mapped; not evidenced |
| T-61 | §10.8 | S-LEGACY, S-TEXT-CACHE, S-RETRIEVAL, S-ADMIN | None mapped; not evidenced |
| T-62 | §10.7 | S-LEGACY, S-TEXT-CACHE, S-RETRIEVAL, S-ADMIN | None mapped; not evidenced |
| T-63 | §11.5 | S-ADMIN, P-EVALUATION | None mapped; not evidenced |
| T-64 | §4.6 | S-LEGACY, S-TEXT-CACHE, S-RETRIEVAL, S-ADMIN | E-05; prior bounded only |
| T-65 | §4.6 | S-RETRIEVAL, S-ADMIN | None mapped; not evidenced |
| T-66 | §14.6 | S-LEGACY, S-TEXT-CACHE, S-RETRIEVAL, S-ADMIN | E-03; prior bounded only |
| T-67 | §8.6 | P-LIFECYCLE | None mapped; not evidenced |
| T-68 | §13.5 | P-LIFECYCLE | None mapped; not evidenced |
| T-69 | §5.9 | P-LIFECYCLE | None mapped; not evidenced |
| T-70 | §13.5 | P-LIFECYCLE | None mapped; not evidenced |
| T-71 | §13.5 | P-LIFECYCLE | None mapped; not evidenced |
| T-72 | §8.6 | P-LIFECYCLE | None mapped; not evidenced |
| T-73 | §10.6 | S-IMPORT, P-LIFECYCLE | None mapped; not evidenced |
| T-74 | §6.10 | P-LIFECYCLE | None mapped; not evidenced |
| T-75 | §10.8 | S-LEGACY, S-TEXT-CACHE | None mapped; not evidenced |
| T-76 | §9.3 | S-LEGACY, S-TEXT-CACHE | None mapped; not evidenced |
| T-77 | §9.4 | S-RETRIEVAL | None mapped; not evidenced |
| T-78 | §9.1 | S-RETRIEVAL | None mapped; not evidenced |
| T-79 | §9.4 | S-RETRIEVAL | None mapped; not evidenced |
| T-80 | §4.4 | P-LIFECYCLE | None mapped; not evidenced |
| T-81 | §5.9 | P-LIFECYCLE | None mapped; not evidenced |
| T-82 | §8.6 | P-LIFECYCLE | None mapped; not evidenced |
| T-83 | §13.2 | P-LIFECYCLE | None mapped; not evidenced |
| T-84 | §16.4 → T-49 | Non-scored alias | No independent result permitted; A-49 provenance retained |
| T-85 | §5.4 | P-VALHALLA | None mapped; not evidenced |
| T-86 | §8.6 | P-VALHALLA | None mapped; not evidenced |
| T-87 | §8.2 | P-VALHALLA | None mapped; not evidenced |

## 5. Bounded prior results and remaining proof

**T-09 — E-02.** Retained final-request/forged-attempt controls reported in the bounded Run-11 scope; successor mutation variants untested. Remaining: Produce or map exact subject/profile evidence for every applicable assertion, preserving historical limits; no new execution result is supplied here. Successor schema, installed-client and composed retrieval proof remain required.

**T-11 — E-03.** Eight campaign regressions reportedly include a local race; no replicated financial consistency result. Remaining: Produce or map exact subject/profile evidence for every applicable assertion, preserving historical limits; no new execution result is supplied here.

**T-12 — E-03.** Local unknown-exposure reopen/recovery regression reported; no Redis or production recovery proof. Remaining: Produce or map exact subject/profile evidence for every applicable assertion, preserving historical limits; no new execution result is supplied here.

**T-14 — E-04.** Duplicate submissions added no sends in all five controlled text cases; authorized escalation/successor behavior not covered. Remaining: Produce or map exact subject/profile evidence for every applicable assertion, preserving historical limits; no new execution result is supplied here. Successor schema, installed-client and composed retrieval proof remain required.

**T-18 — E-04.** Missing/null required write counters produced unknown cost, pause and held exposure; the full later-reconciliation parent is not qualified by this matrix. Remaining: Produce or map exact subject/profile evidence for every applicable assertion, preserving historical limits; no new execution result is supplied here. Successor schema, installed-client and composed retrieval proof remain required.

**T-24 — E-02.** Run-11 held positive and queued post-revocation rejection observed for the selected local plaintext sender; not all transports or authority sources. Remaining: Produce or map exact subject/profile evidence for every applicable assertion, preserving historical limits; no new execution result is supplied here. Successor schema, installed-client and composed retrieval proof remain required.

**T-38 — E-02.** Bounded raw-worker and forged-attempt controls observed; production telemetry/all-provider egress not qualified. Remaining: Produce or map exact subject/profile evidence for every applicable assertion, preserving historical limits; no new execution result is supplied here.

**T-43 — E-05.** Post-generation refresh/status produced read-only local GETs and no added receiver arrival; all setup/preview/save cases not established by this receipt. Remaining: Produce or map exact subject/profile evidence for every applicable assertion, preserving historical limits; no new execution result is supplied here.

**T-47 — E-03.** DEV-11 reports preserved strict legacy wire with earlier installed-client evidence reused; no successor parity has run. Remaining: Produce or map exact subject/profile evidence for every applicable assertion, preserving historical limits; no new execution result is supplied here. Successor schema, installed-client and composed retrieval proof remain required.

**T-48 — E-04.** Exact fictional token/cache arithmetic and conservative bound in five controlled cases; non-token, tier and rounding successor fixtures not product-tested. Remaining: Produce or map exact subject/profile evidence for every applicable assertion, preserving historical limits; no new execution result is supplied here. Successor schema, installed-client and composed retrieval proof remain required.

**T-49 — E-04.** Controlled missing/null/explicit-zero write distinctions; invalid/over-bound focused cases reported separately in E-03; native operations not tested. Remaining: Produce or map exact subject/profile evidence for every applicable assertion, preserving historical limits; no new execution result is supplied here. Successor schema, installed-client and composed retrieval proof remain required.

**T-50 — E-03.** Local race/restart/over-bound/once-only-correction regressions reported; E-04 documents no-extra-send. Complete successor/distributed parent remains open. Remaining: Produce or map exact subject/profile evidence for every applicable assertion, preserving historical limits; no new execution result is supplied here. Successor schema, installed-client and composed retrieval proof remain required.

**T-56 — E-03.** Exact-model/cache/rate review and normal result controls reported; complete provider readiness/setup journey not evidenced. Remaining: Produce or map exact subject/profile evidence for every applicable assertion, preserving historical limits; no new execution result is supplied here.

**T-64 — E-05.** One normal authenticated generation result and double-click disable observed in supplied receipt; full responsive/accessibility/edit matrix not evidenced. Remaining: Produce or map exact subject/profile evidence for every applicable assertion, preserving historical limits; no new execution result is supplied here. Successor schema, installed-client and composed retrieval proof remain required.

**T-66 — E-03.** Historical rows/wire preserved by reported DEV-11 scope; no successor migration, deployment or full rollback proof. Remaining: Produce or map exact subject/profile evidence for every applicable assertion, preserving historical limits; no new execution result is supplied here. Successor schema, installed-client and composed retrieval proof remain required.

## 6. Stable subcases

Each subcase inherits its normative clause but not a parent pass. Detailed profile, date, evidence and remaining-proof fields are in the JSON.

| Subcase | Assertion | Evidence status |
|---|---|---|
| T-07.a | A correctly signed plan under a revoked signing-key version is rejected before first write, including after a lower wait. Positive controls include an eligible current key and a rotated-but-not-revoked old key verifying an already-issued unexpired plan; rotation alone causes no re-signing, new attempt or additional send. Re-signing preserves the work key and no-repeat ownership and never replays a possibly sent attempt. Production custody/rotation evidence is separately scoped. | Not executed; erratum requirement |
| T-14.a | Unchanged WorkKey and canonical caller assertions resubmitted across server-assessed commission asserted-to-verified, unavailable-to-available, not_yet_issued or caller_omitted reason changes, and delegation coverage changes resolve to the original submission/attempt with no extra reservation or send. Current read/dispatch authority still applies; changed caller assertions under the same key conflict. | Not executed; erratum requirement |
| T-24.a | Effective local revocation while queued below the guard blocks first write; positive controls work. | E-02 — bounded legacy only |
| T-24.b | First-write/revocation order, would-block and partial-write paths preserve consumption/uncertainty. | Not evidenced for successor |
| T-24.c | Crash/owner recovery never repeats a possibly sent attempt. | Not evidenced for successor |
| T-24.d | Replicated/protocol-specific release fencing qualified before reliance. | Not evidenced for successor |
| T-39.a | Unauthorized worker/client/log/export cannot read secret. | Not evidenced for successor |
| T-39.b | Qualified same-scope rotation records actual secret revision without widening authority; current strict behavior remains until qualified. | Not evidenced for successor |
| T-39.c | Local revocation disables queued unsent work and separately records upstream revocation confirmation. | Not evidenced for successor |
| T-39.d | Compromise or account/permission-scope change blocks/revalidates affected queued work. | Not evidenced for successor |
| T-45.a | Source/account/operation isolation. | Not evidenced for successor |
| T-45.b | Source disallow blocks queued unsent work. | Not evidenced for successor |
| T-45.c | Grant/delegation revoke blocks queued unsent work. | Not evidenced for successor |
| T-45.d | Credential scope change/compromise/revocation blocks queued work. | Not evidenced for successor |
| T-45.e | Routine rotation follows exactly the qualified revision contract; no inferred exemption. | Not evidenced for successor |
| T-46.a | Operation/payload/order/compatibility mutation rejected. | Not evidenced for successor |
| T-46.b | Tampering with the signed commission/delegation admission assessment (status, coverage, server-assigned reason or work-digest linkage) is rejected; changed canonical caller assertions conflict under the same WorkKey. Legitimately appended later assessments do not mutate the original snapshot or identity. | Not evidenced for successor |
| T-46.c | Signed activation-context mutation rejected; activation change is not a new work key. | Not evidenced for successor |
| T-46.d | Price/financial-owner mutation rejected. | Not evidenced for successor |
| T-47.a | Installed Python/CommonJS successor schemas and defaults agree. | Not evidenced for successor |
| T-47.b | Domain-separated canonical goldens and order sensitivity agree. | Not evidenced for successor |
| T-47.c | Legacy strict parser/digests/tool-cycle semantics preserved. | Not evidenced for successor |
| T-47.d | Unknown versions/fields reject; no permissive compatibility grants. | Not evidenced for successor |
| T-48.a | Native non-token quantity/price semantics. | Not evidenced for successor |
| T-48.b | Tariff A unit ceiling and per-request minimum at all 25 inputs. | Not evidenced for successor |
| T-48.c | Tariff B whole-request tier boundary n=10/11. | Not evidenced for successor |
| T-48.d | Half-even nano currency rounding including opposite tie directions. | Not evidenced for successor |
| T-48.e | Upward reservation covers every admitted raw/settled amount. | Not evidenced for successor |
| T-48.f | Domain and missing/null/invalid/zero/contradictory usage cases preserve evidence and unknown liability. | Not evidenced for successor |
| T-48.g | Separate requests, repeat attempts and split batches apply their own minima/rates and per-attempt rounding; no double-counted components. Tariff B: three distinct n=1 attempts total USD 0.000900000, while one n=3 attempt settles USD 0.000900002; equal raw aggregate does not imply equal rounded total. | Not evidenced for successor |
| T-49.a | Absent required native counter retained, cost unknown. | E-04 — bounded legacy only |
| T-49.b | Explicit null distinct from absence, cost unknown. | E-04 — bounded legacy only |
| T-49.c | Explicit zero retained; accepted as zero only when consistent with the contract. | E-04 — bounded legacy only |
| T-49.d | Invalid/contradictory/out-of-domain counter retained with invalidity/unknown cost. | Not evidenced for successor |
| T-49.e | Later sufficient evidence appends a revision and adjusts financial state once; no resend. | Not evidenced for successor |
| T-50.a | Atomic concurrent reservations respect every supported scope. | Not evidenced for successor |
| T-50.b | Duplicate/competing submissions cause no extra send. | E-04 — bounded legacy only |
| T-50.c | Restart retains unknown exposure before new admissions. | Not evidenced for successor |
| T-50.d | Linked usage correction applies a delta once. | Not evidenced for successor |
| T-50.e | Above-bound result recorded and affected scope paused, not clamped. | Not evidenced for successor |
| T-50.f | Distributed recovery qualified separately; no single-process extrapolation. | Not evidenced for successor |
| T-60.a | Direct human has no invented agent. | Not evidenced for successor |
| T-60.b | Delegated agent identity and initiating human remain distinct. | Not evidenced for successor |
| T-60.c | Autonomous work has service principal/charging owner, no invented initiating human. | Not evidenced for successor |
| T-60.d | Forged/cyclic authority-bearing attribution rejected. | Not evidenced for successor |
| T-62.a | Time period/timezone boundaries align. | Not evidenced for successor |
| T-62.b | Revision cutoff picks one effective usage revision. | Not evidenced for successor |
| T-62.c | Provider/actor/task/environment filters select the same authorized attempt set. | Not evidenced for successor |
| T-62.d | Timeline and CSV/JSON totals reconcile. | Not evidenced for successor |
| T-62.e | Cross-principal report/export access denied. | Not evidenced for successor |
| T-73.a | External observations retain source/period/granularity and do not invent sends. | Not evidenced for successor |
| T-73.b | Identical re-import is idempotent. | Not evidenced for successor |
| T-73.c | Overlapping/replacement/corrected exports do not add duplicate spend; ambiguous overlap flagged. | Not evidenced for successor |
| T-73.d | Controlled-attempt linkage reconciles rather than adds the observation. | Not evidenced for successor |
| T-73.e | Currencies/unknown attribution remain distinct. | Not evidenced for successor |
| T-77.a | All required shared fields/reasons exist on applicable successor events. | Not evidenced for successor |
| T-77.b | Invalid reason or inconsistent field/status combination rejected. | Not evidenced for successor |
| T-77.c | Pre-admission/legacy events follow explicit applicability without invented backfill. | Not evidenced for successor |
| T-77.d | Absence reason never waives mandatory authority. | Not evidenced for successor |
| T-78.a | Synthetic direct-human binding and appropriate chain representation. | Not evidenced for successor |
| T-78.b | Synthetic delegated-agent binding, ordered chain and asserted intermediate links. | Not evidenced for successor |
| T-78.c | Synthetic autonomous service/owner with no fictitious person. | Not evidenced for successor |
| T-78.d | Forged endpoints, cycles and excess bounds rejected; asserted history not authority. | Not evidenced for successor |
| T-78.e | Future real issuer/Proto chain qualification is separate from synthetic cases. | Not evidenced for successor |
| T-79.a | Absent commission with allowed reason and asserted record-only fixture. | Not evidenced for successor |
| T-79.b | Record-only reference supplies no commission execution authority. | Not evidenced for successor |
| T-79.c | Mutation of canonical caller commission assertions is detected; tampering with the signed admission status/reason or its work-digest linkage is rejected. Later linked verification leaves the original snapshot and deduplication identity unchanged. | Not evidenced for successor |
| T-79.d | Later verification appends evidence/time without retroactive authority upgrade. | Not evidenced for successor |
| T-85.a | Verified commission revocation serialized with the same T-24 first-write fence. | Not evidenced for successor |
| T-85.b | Stale commission/gate evidence fails closed before reliance. | Not evidenced for successor |
| T-87.a | Activation current at admission and first write. | Not evidenced for successor |
| T-87.b | Orchestrator rejects stale acceptance; late usage preserved. | Not evidenced for successor |
| T-87.c | Epoch change alone adds no effect, attempt or budget. | Not evidenced for successor |

## 7. Updating this register

Append scoped evidence with immutable requirement/profile/build identities, observation date and limits. Preserve earlier failures and evidence from superseded builds. A reused receipt must identify source correspondence; a later document commit does not imply new runtime. No blanket inheritance from SDK feature lists, another provider, another transport or a simulated tariff is allowed.

Rollups count canonical requirements only and state their profile denominator. T-84 always resolves to T-49; T-85 is separately applicable only to verified-commission integration and links the general T-24 fence. Do not aggregate synthetic and commercial evidence into one readiness score. Owner adoption, implementation, controlled execution, deployment and commercial/integration acceptance remain separate milestones.

## 8. DEV-05–DEV-10 evidence supplement 01

[Read the evidence supplement](DURANKI-v1.2-C01-EVIDENCE-SUPPLEMENT-01.md). Seventeen parent rows now carry additional bounded historical observations, including related positive-only provenance where stated. This does not mark all their subcases passed. Earlier C01 assertions in §5 remain dated history; the JSON preserves those assessments explicitly and appends the supplement. DEV-08–DEV-10 primary results and later DEV-07 closure remain unmapped. T-07’s signature/key-revocation negatives, T-41’s adoption-refusal path and production key custody remain unevidenced by the selected added records.

All 87 parent/alias identifiers are unchanged; there are now 73 subcases. T-07.a and T-14.a are new unexecuted requirements. T-46.b and T-79.c are amended, and T-48.g has an additional fictional rounding vector. No runtime status is inherited from a document calculation.

## 9. Review 04 finalization

[Closeout](DURANKI-v1.2-C01-REVIEW04-CLOSEOUT-01.md) applies R04-01: E-11's bounded DEV-07 commit-inside-gate ordering is compatible with the single-process SQLite profile. The commit-outside-lock publication sequence and its additional failure cases belong to the PostgreSQL/replicated profile; they are not a reason to rewrite DEV-12's standalone gate. Current build correspondence and all remaining crash/transport/successor proof remain explicit. No evidence status, test ID or count changes.

Existing T-07.a now includes the rotated-but-not-revoked positive control. Two mechanical JSON parent-text errors, T-07 and T-14, are repaired by copying their already-correct §16 test statements; their subcases and evidence statuses are not promoted. N-02 receipt capture and mapping continue in parallel with adoption and successor-contract drafting.
