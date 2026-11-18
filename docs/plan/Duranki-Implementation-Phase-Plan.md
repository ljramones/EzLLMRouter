# Duranki v1.2 — implementation delivery plan

**Date:** 25 October 2026  
**Owner:** Larry Mitchell  
**Standing:** Proposed delivery grouping of the finalized v1.2 architecture and roadmap, prepared in response to the owner's direction to begin implementation updates. This plan does not itself execute repository changes, deploy a profile, select commercial terms, authorize spending or release the Vega integration hold.

## 1. Basis and intended outcome

Use v1.2 Correction 01 + Erratum 01, Review 04 finalization 01, as the design basis for the next implementation instructions. Do not reopen the full architecture review. Record the owner's implementation direction and the exact baseline identity in the repository without rewriting the historical review documents' status labels.

The owner reports the extracted package at `docs/architecutre/duranki-v1.2-c01-finalization-01`. Resolve the actual directory in the checkout before referencing it in scripts. Do not silently assume a differently spelled path, rename it or create a duplicate architecture tree.

Checked source documents in the supplied package:

| Document | SHA-256 | Relevant sections |
|---|---|---|
| `DURANKI-ARCHITECTURE-v1.2-CORRECTION-01.md` | `fa0229f2e61dce103557b6f51fa63f1a521cd7261799166225a56e5b99da883c` | §§0, 4–10, 11–15, 18 |
| `DURANKI-v1.2-C01-ROADMAP.md` | `afdc60ceb649a9cf73cc0710fc8dd6713574c958d240ceaaafe88f314d2c2c07` | §§2–8 |
| `DURANKI-v1.2-C01-REVIEW04-CLOSEOUT-01.md` | See finalization manifest | §§1–5 |

These documents were read from the supplied files/package, not from the owner's current repository. Current HEAD, index, merge state, deployed image and allowances must be checked by the repository executor rather than inferred from dated development reports.

**First destination:** a usable standalone Duranki with a declared supported-operation profile, clear provider/account setup, permissions, accurate native-unit accounting, understandable user/agent reporting and tested execution controls.

**Later destination:** qualified production operation and a deliberately selected Vega/Proto cohort, followed by measured routing improvements and eventually learned-policy promotion. Valhalla integration is qualified separately when its actual authority services and primary contracts are available.

Delivery stages A–H below do not renumber architecture assurance Phases 0–6 or imply that shipping a feature completes a production phase. They are a practical grouping of the existing roadmap, with production engineering made explicit as a parallel workstream.

## 2. Bounded startup work — not another design phase

The first assignment should establish the exact current checkout and finalized architecture identity, preserve unrelated work, and record the relevant scope. It should inspect the working source before treating a blank assurance cell as missing implementation.

Run the existing DEV-05–DEV-10 read-only evidence-capture instruction in parallel with successor-contract work. Map applicable historical records; retain source/build/profile limits. Missing historical receipts do not prevent contract drafting or unrelated implementation, but they do prevent an unsupported completeness claim.

Inspect the DEV-11 correction's actual source/deployment standing. Reuse its arithmetic and enforcement where applicable. Do not rerun historical one-use IDs, reset the application or assume an old image is current. An owner-profile update, paid test or merge follows its separately scoped instruction, not this plan alone.

## 3. Delivery stages

### A — DEV-12: operation-aware foundation and retrieval

**Purpose:** make embeddings and reranking first-class operations without weakening or silently replacing the existing text/tool contract.

Within this single tranche, use four delivery checkpoints:

| Checkpoint | Deliverable | Exit |
|---|---|---|
| A1 — Exact successor contract | Explicit wire/profile/projection identifiers; bounded request/result schemas; canonical bytes and independent golden vectors; compatibility/migration rules | Focused contract review complete before product changes; no full architecture re-review |
| A2 — Shared implementation | Registry permissions, signed plans/admission snapshots, additive SQLite storage, native usage components keyed by attempt and revision, installed Python/CommonJS support | Component and cross-language equivalence/negative tests pass; historical wire and digests preserved |
| A3 — Retrieval execution | Synthetic embedding and reranking adapters through the actual isolated worker, guard and trusted sender; immutable fictional tariffs | Independent receiver correlation and financial/authority tests pass |
| A4 — Usable composed result | Operation-specific reporting, retrieval timeline and drill-down; composed failure/restart/migration cases | Supported-profile requirements met through both installed clients and the normal operator journey |

The shared metadata envelope is part of A1/A2, not postponed until Vega. Caller assertions and caller-declared reasons belong to canonical work; changing server assessments belong to the signed admission snapshot. Activation information is signed execution context, not a new deduplication identity. Preserve full authenticated work-key scope, exact legacy wire `0.2` semantics and existing caller-owned tool behavior.

Retain the qualified single-process SQLite first-write gate ordering. Do not replace it with the replicated-profile ordering merely to enter DEV-12. Implement the successor's relevant signing-key eligibility checks and tests, without representing a synthetic key as production managed-key custody.

Embeddings bind ordered batches, document/query role and vector-space/index compatibility. Reranking binds ordered candidate identities and validates the returned ranking. The corpus owner retains indexing side effects; Duranki does not become a vector database.

Prove the supplied non-token tariff cases, including minima, document/search units, whole-request tiers, per-attempt half-even settlement and upward-rounded exposure. Keep missing, null, explicit zero, invalid, reported and derived evidence distinguishable. Preserve unknown exposure, duplicate suppression, current-authority rejection and replacement usage revisions applied once.

**Visible demonstration:** index a fictional corpus once, embed a query and rerank its results. Show the separate attempts and their costs, without charging corpus ingestion again to each reader or double-counting parent/child views.

**Excluded:** real provider calls/keys/prices, owner-profile migration, PostgreSQL deployment, new infrastructure or dependency acquisition, live fallback, external caching, audio/media/realtime, Vega/Proto/Valhalla execution and learned routing. The detailed brief selects the exact applicable test subcases.

*Source basis: architecture §§5.3–5.4, 5.7–5.9, 9.4, 10, 15.3–15.4; final roadmap §§3–5; Review 04 closeout §§2–3.*

### B — WP-SPEND-IMPORT: useful spending visibility without Vega

This is the next standalone work package after DEV-12, before further policy or provider-family expansion.

Build an offline importer for owner-supplied usage/cost exports. Select an actual supported format from available supplied material; use synthetic fixtures for engineering tests. Preserve account, currency, period/timezone, native quantities, credits/adjustments, source identity, granularity and correction provenance.

An identical import recovers its original receipt. Overlapping or replacement exports cannot silently inflate totals. Linking an imported amount to a controlled attempt must not charge it a second time. Unresolved user, agent, task or operation remains unknown. Multiple currencies remain distinguishable; no invented conversion is required.

**Exit:** reconciled supported-format imports, honest uncertainty, duplicate/overlap/correction controls, and usable authorized reports/exports. Real-data acceptance waits for actual exports; that need not block synthetic implementation. Account spending alone does not establish task acceptance, invoice accuracy or agent efficiency.

*Source basis: final roadmap §6; architecture §§1, 9.5, 10 and T-73.*

### C — Complete the operator experience and deterministic policy controls

Extend existing screens and APIs rather than rebuilding them. Finish the provider/account journey: save credentials, explicitly check access, discover inventory, permit selected operations, grant scoped access, publish an eligible rate contract and configure allowances. Keep those states separate from endpoint health and provider-advertised capabilities.

Add the scoped budget/alert behavior selected for this increment. Make predicted cost, reserved exposure, calculated settlement and unresolved amounts understandable. Complete supported credential lifecycle actions without disclosing keys or weakening queued authority checks.

Add named policy drafts, published versions, read-only route explanation/preview, audit history and rollback. Health/cooldown scaffolding must not bypass permissions, output compatibility, financial bounds or quality approval. Policy publication alone does not authorize live model substitution.

**Exit:** an operator can configure supported operations, understand why work is blocked or routed, inspect activity and costs, and change/revert policy through tested controls. Ordinary navigation, preview and refresh make no provider call.

*Source basis: final roadmap §2 positions 3–4; architecture §§4.5–4.7, 6.9 and 10.8.*

### D — Expand operations in independently qualified increments

Follow the roadmap's order, not a single large multimodal implementation:

| Order | Family or lifecycle | Required distinction |
|---|---|---|
| D1 | Additional selected text, caller-owned tool and streaming contracts; then bounded transcription and vision | Preserve parameters, content order and caller-owned effects; qualify each transport and usage mapping |
| D2 | Model-hosted search and selected adjacent-service observations | Model tokens, hosted-tool fees and separate service charges remain distinct; observed work is not automatically controlled |
| D3 | Qualified alternatives/recovery, image generation, TTS and artifact handling; private/lab controls | Generation versus retrieval, controlled artifact destinations, no-repeat/exposure, compatible substitution and capacity/handling controls |
| D4 | Realtime voice, long-running jobs and opaque external-execution observation | Session/connection/attempt identity, finite or proved rolling exposure, stop uncertainty and external trust limits |

Each increment supplies an operation contract, accounting rules, relevant controls, installed-client support, UI projection and independent positive/negative tests. Define scope by the declared supported-operation manifest; do not claim every provider or every source-listed operation is qualified.

Some reconnaissance families are ordinary local processing and require no inference adapter. Opaque backends remain observations until their sending authority and accounting boundary are actually established. Do not force every family into a model endpoint.

**Exit:** each enabled family has a documented, tested support boundary; unsupported cases reject clearly. Failure to retrieve a generated artifact does not erase generation cost; local stream closure does not prove provider stop or settlement.

*Source basis: final roadmap §2 positions 5–8; architecture §§5.7–5.9, 7, 8.6 and 10; model/service reconnaissance.*

### E — Production engineering and release qualification

This is a distinct workstream that can begin once the successor storage/authority contracts are stable, in parallel with later standalone operation increments. It is not a prerequisite to A or B.

Implement the selected PostgreSQL production ledger profile and reviewed migration/restore path, without declaring SQLite obsolete. Qualify multi-worker/replica reservation and ownership, authority publication and the first-write fence, failure recovery, stale state, cancellation uncertainty and duplicate prevention. A local mutex is not distributed proof.

Add managed plan-signing and credential custody, role separation, qualified rotation/revocation, supply-chain gates, safe telemetry, operational monitoring, backup/restore and bounded failure/rollback procedures. Introduce shared-state and observability services only within their reviewed dependency and deployment scope. Cloud/hosting/topology choices remain explicit decisions rather than assumptions.

Maintain per-operation commercial qualification as a separate release lane: controlled proof, preserving owner update where authorized, exact account/model/price qualification, deliberate finite paid test, and later reconciliation. It can proceed for an already-qualified operation without waiting for every future operation to exist. This plan selects no key, price, provider, amount or paid invocation.

**Exit:** production infrastructure and release procedures are ready for a declared deployment/cohort. Full operational phase acceptance still requires its actual eligible-cohort, coverage and reconciliation evidence; infrastructure tests alone do not establish it.

*Source basis: architecture §§4.4, 5.4, 10, 13–15 and 18; final roadmap's standalone exclusions and separate deployment/commercial gates.*

### F — Standalone evaluation workbench

Build dataset and outcome ingestion, cohort definitions, development/confirmation splits, configuration-version comparisons, checker evaluation, cost/latency/quality reports, and shadow decision records. Preserve caller-owned substantive acceptance and the costs of evaluation itself.

Test orchestration and reporting with standalone producers before involving Vega. Label synthetic outcome demonstrations as such. Recorded transcripts do not automatically establish counterfactual results for a different model.

**Exit:** reproducible evaluation tooling with correct accounting and promotion/rollback controls, ready for suitable real cohorts. No learned policy or savings claim is justified solely by a synthetic fixture or a larger token/cache-hit graph.

*Source basis: final roadmap §§2, 7; architecture §§6, 11–12 and 15.1.*

### G — Owner-released Vega/Proto and later Valhalla integration

Remain deferred until Larry explicitly releases the hold after the prerequisite Vega work. Do not change call sites merely because the standalone client is ready.

Select a bounded cohort. Map trusted identities, delegation, operation semantics, source handling, task outcomes and cost linkage. Begin with the explicitly approved observation scope, then move selected execution paths under control after their contracts and rollback paths are demonstrated. Observation must not introduce duplicate paid calls. Retire direct keys only after the affected consumers and recovery paths are accounted for.

Valhalla integration is a separate part of this stage when its actual services/contracts are available: verified commissions, activation fencing, policy consultation and controlled budget-authority handover preserving outstanding reservations. Metadata compatibility does not establish live authority integration.

**Exit:** the selected cohort is attributable and covered to the declared level, existing behavior remains valid, rollback is demonstrated and representative task evidence can be collected. No full-platform coverage claim is inferred from one integrated agent.

*Source basis: architecture §§9.4–9.5 and 15; final roadmap §7.*

### H — Measured optimization and closed-loop improvement

Use representative complete cohorts and the architecture's assurance gates. Establish the baseline first, then measure context/loop improvements, evaluate candidate configurations, qualify deterministic rules/cascades and lab scheduling, and only then promote learned ranking. Preserve the quality floor, non-inferiority margin, latency limits, full recovery/evaluation costs and permission boundaries.

Prepare features earlier where useful, but do not promote them on evidence from a different profile or task class. Learned-policy rollback, delayed outcomes, drift detection and approved exploration remain separate qualifications.

**Exit:** demonstrate improvements in cost per accepted task within the required quality/latency envelope, not merely lower token counts or a functioning router. Ongoing monitoring continues after this baseline is complete.

*Source basis: architecture §§1, 6–7, 11–12 and assurance Phases 0–6 in §15.1.*

## 4. What can proceed together

The critical initial order is:

**Baseline record and exact successor contract → DEV-12 → WP-SPEND-IMPORT → operator/policy completion → selected further operation contracts.**

Historical evidence mapping can proceed alongside contract/DEV-12 work; no unchanged runtime rerun is requested simply to fill a register cell. Import-format fixtures may be prepared under their own scope before the importer implementation starts. After shared interfaces stabilize, client/UI work can proceed alongside server adapters using frozen fixtures, while shared schema, signing and accounting edits retain coordinated ownership.

Production engineering can proceed alongside later operation work; commercial qualification can proceed per eligible operation under explicit owner authorization. Evaluation tooling can be prepared before Vega. Actual Vega integration, company credentials, paid activation and learned-policy promotion remain separate decisions.

## 5. Practical definition of done

Use one living implementation tracker and one result record per tranche. Preserve existing requirement IDs. For every enabled slice, record the exact contract/source/build, implemented surface, focused regressions, composed receiver proof where needed, usable operator journey, installation/migration behavior, and remaining limits.

Keep the dimensions separate: source implemented; controlled target qualified; deployed; commercially qualified; integrated; optimization benefit demonstrated. Missing evidence is not automatically missing code, and a green component suite is not a provider-billing or distributed-safety guarantee.

Three useful completion milestones:

1. **Standalone product release:** its explicit supported-operation manifest meets architecture §15.2, with functional clients, UI, accounting and preservation. This can be reached before all future operation families or Vega exist.
2. **Production/integration readiness:** deployment, custody, recovery and the selected provider paths are qualified for the declared production scope. Complete operational acceptance follows the actual cohort evidence.
3. **Optimization baseline completed:** integrated representative cohorts support the measured promotion decisions in assurance Phases 2–6.

Review the exact changed contracts and implementations. Reopen the architecture only for a newly demonstrated material contradiction, not because another DEV tranche is beginning. Correct ordinary bugs within the same assignment. Preserve failed historical evidence, avoid needless reruns and do not substitute documentation growth for product delivery.

## 6. Immediate assignment

Start with baseline/current-source reconciliation and the exact DEV-12 successor contract. Its reviewed schemas and vectors are the entry checkpoint for the implementation, not another general architecture design. Then deliver A2–A4 through the existing application and both installed clients.

Prepare a focused executable brief selecting actual changed paths, disposable test scope, acceptance subcases and repository publication permissions. Retain explicit boundaries for owner-profile deployment, external calls and Vega. No additional commercial-router survey, full architecture review or universal cache project is needed to begin.
