# Duranki architecture v1.2 — Addendum A reconciliation disposition 02

**Date:** 25 October 2026  
**Status:** Author assessment and proposed correction direction. Supplements Disposition 01; not adoption of Addendum A, v1.2, or the proposed reconciliation. No implementation commission.  
**Owner:** Larry Mitchell  
**Subject:** Recovered Addendum A, draft 0.1, and its reconciliation handoff  
**Result:** Packet identities verified; PostgreSQL decision evidence recovered; all R1–R18 dispositioned below; test crosswalk and terminology proposed. The corrected architecture itself has not been authored by this note.

## 1. What changes in the assessment

The supplied handoff resolves Disposition 01 N-02's missing-decision issue: **PostgreSQL is the owner-selected production-ledger database engine.** Its source is the owner's 23 October reply, quoted in the handoff, not a new recommendation to choose a database. Preserve Disposition 01 as history and append this correction. Document incorporation remains pending; database deployment or migration is not established.

The addendum contributes an important missing architectural relationship: Duranki's model/AI-service boundary should be able to participate in a wider system of commissions, delegation, activation fencing and budget authority. This can be described and prepared in standalone contracts without bringing Vega or Valhalla integration forward.

Do not append Addendum A unchanged to v1.2. Reconcile its clauses explicitly, retain their source references, and produce one coherent normative successor. The four recovered owner decisions are distinct from the rest of the addendum's proposed mechanisms.

## 2. Packet identity and evidence limits

| Input | Bytes | SHA-256 |
|---|---:|---|
| `duranki-addendum-a.md` | 37,071 | `88c02e50b29be9363e02014c65a00abe6333d79ff1f0b52e2d57e694f45575ba` |
| `DURANKI-ADDENDUM-A-RECONCILIATION-HANDOFF-2026-10-25.md` | 15,483 | `e0c0394f862fd42ceba8726e19327a1429cb7caee16478c1df94a6419ca09fa2` |
| Supplied `MANIFEST.sha256` | 210 | `8be73df3bc5c1936ad9701552361ef78e36a884b9d7c91bbd62570b4a4cd13ee` |

Both payload hashes match the supplied manifest. These checks identify the received bytes, not the inaccessible 23 October delivery or the underlying Claude transcript. The eight reconstruction edits were not independently replayed because their original transcript was not supplied. The handoff's reported word count is 5,811; both `wc -w` and whitespace splitting produce 5,825 for the received file. A different counting convention may explain that difference. It does not invalidate the matching manifest, but the word count was not reproduced and is not an identity proof.

No separate original Addendum A was located in the mounted files or the relevant file searches. Valhalla 0.4 and the Proto Runtime Proposal/evidence report were not located in the searched conversation/Library material. Their cited contents, including F-12, P-02/P-15/P-17 and ADR 0051, therefore remain **reported by Addendum A, not independently checked here**. The search result is not a claim that the owner lacks those files. No public-web source is substituted for these private documents.

The v1.2 draft, its change note and Disposition 01 were also read/compared. Their exact local identities are in the companion verification JSON. No supplied source document was edited.

## 3. Four owner decisions: their actual scope

The reconciliation handoff §4 quotes:

> For 2, please fix Valhalla 0.4. For 4, use Postgres. For 3. I originally had it for LLM models, but we need to consider the others.  For 1, agreed

| Decision | Carry forward | Do not infer |
|---|---|---|
| 1 — commission/delegation fields | Empty commission reference with a reason before commissions exist; preserve available delegation evidence from the beginning | Invented agents or links; unverified lineage as authority; historical backfilling as contemporaneous evidence; immediate Proto edits |
| 2 — identity terminology | **Activation epoch** denotes the Valhalla worker/activation fence; **execution generation** retains Duranki's invocation meaning | That Valhalla 0.4's actual text was checked or its fencing implementation exists |
| 3 — broader scope | Consider model and AI-service operations beyond LLM text | Blanket support, a universal tariff, all-provider activation or an adopted Phase 1c schedule |
| 4 — database | **PostgreSQL: decided by owner, 23 October 2026** | Cloud SQL/RDS selection, a cloud move, same physical database for every ledger, deployment, HA proof, or immediate replacement of SQLite |

Recommended replacement for the database-open item: “Production ledger engine: PostgreSQL, selected by Larry Mitchell on 23 October 2026. Managed hosting, topology, access roles, retention/partition design, optional tamper evidence, migration and production qualification remain separately scoped. The standalone SQLite profile remains supported within its recorded scope.”

## 4. R1–R18 finding-to-clause map

The disposition verbs below are **recommendations for Correction 01**, not declarations of owner adoption. Section targets refer to the existing v1.2 organization; separate roadmap/register material may link back to those clauses.

| Row | Topic | Disposition and correction | Clause target / timing |
|---|---|---|---|
| **R1** | Production ledger database | **Incorporate recovered decision; qualify implementation.** Replace “database product open” with PostgreSQL. Keep Cloud SQL/RDS, insert-only roles, partitions and hash chaining as proposals. Immutable financial events and mutable operational reservation/registry state need explicitly separate privileges; “the gateway can only INSERT” must not accidentally contradict supported state transitions. | §§4.1, 10.1, 14.6, 18.10; D01 N-02. Engine decision now; migration later. |
| **R2** | Non-LLM scope / Phase 1c | **Incorporate scope; supersede the bundled phase as the next-work dependency.** Map transcription → MS-05, synthesis → MS-06, realtime → MS-07, hosted search → MS-09; keep adjacent search MS-10 distinct. Qualify each operation/lifecycle under the standalone profile. Retain “Addendum A Phase 1c” as a historical roadmap label, not a requirement to implement all voice/search before retrieval. Source-site counts are not traffic share. | §§5.7–5.9, 8.6, 15 and roadmap. |
| **R3** | Two lanes / hooks | **Supersede hook-based enforcement.** Treat the lanes as adapter choices: qualified frozen SDK/LiteLLM preparation or a Duranki-owned preparation adapter. Both pass through trusted plan, independent final guard and qualified sender controls. A different protocol may need a separately qualified sender implementation; it does not gain a second weaker governance route. | §§4, 4.3, 5.4. Architecture correction now. |
| **R4** | Missing usage | **Supersede with unknown-preserving accounting.** Keep required missing usage/cost unknown, retain relevant exposure and pause/block according to the active profile. Record estimates separately. Sufficient later evidence appends a revision; an estimate alone does not settle unknown liability. Rewrite A-49. | §§10.2, 10.4, 10.8; T-84 proposal. |
| **R5** | Stream stopping and settlement | **Supersede the implied equivalence.** Local close, provider stop, known usage and financial settlement are independent facts. Preserve known incurred charges and uncertain committed/in-flight exposure. Rewrite A-47/A-51 to forbid release merely from local close. | §§8.4, 8.6, 10.4; proposed T-82/T-86. |
| **R6** | Incremental session reservations | **Incorporate with qualification.** Permit either a finite whole-session reservation or proof-qualified increments covering committed work, reporting delay and stop uncertainty. A local duration/chunk cap is not automatically a provider billable cap. Failure to extend prevents further unauthorized release; it does not erase already incurred or uncertain liability. | §§8.6, 10.8. Design now; lifecycle implementation later. |
| **R7** | Epoch/generation collision | **Incorporate distinction; rename only successor terminology.** Keep activation epoch and execution generation. Use **authority revision** (a scoped revision vector where needed) and **connection sequence**. Neither an epoch nor a revision comparison alone serializes revocation with first write. Existing wire names/digests are preserved until an explicit versioned change. | §§5.3–5.4, 8.2, 8.6; terminology §5 below. |
| **R8** | Logical-effect identity | **Incorporate with correction.** A shorthand step/revision/generation tuple is not globally unique: retain the authenticated principal/task namespace and canonical-work equality. Non-step identifiers need issuer/scope and conflict rules. Speech/search can belong to steps; modality must not determine identity ownership. A realtime session may group multiple billable attempts, turns and connections without collapsing them. | §§5.3, 8.2, 9; identity safeguards §6 below. |
| **R9** | Shared fields / absence rule | **Incorporate logical contract now; implement additively in the reviewed successor.** Distinguish metadata absence reasons from provider-field evidence and authority-verification status. New profile records must satisfy their schema; historical records keep legacy coverage, not invented values. Valid absence reasons never waive required authentication, handling or financial authority. No need to instrument Vega to test this envelope. | §§9, 10.1–10.2, 14.6 and successor contract; T-77/T-79. |
| **R10** | Delegation chain | **Incorporate with trust qualification.** Verify each authority-bearing identity through the selected trusted profile. The originating human, authenticated service principal and current agent are not automatically the same entity. Record intermediate links as attributed assertions until verified; do not infer “complete” merely from a complete-looking list. No trust upgrade from display names. | §§5.1, 9.1; T-78 and T-60. |
| **R11** | Budget account | **Incorporate abstraction; defer authority transfer.** Name the governing budget account in validated financial scope. Preserve all applicable caps and authenticated charging scope. A delegated sub-envelope is not a second charge or a second allocation of the parent's money. A future Norns cutover must preserve outstanding reservations/corrections and prevent dual spend authority. Redis remains a target, not a deployed fact. | §§5.3, 10.4, 10.8; future integration roadmap. |
| **R12** | Non-text classification | **Incorporate with operation-specific rules.** Queries disclose content and intent; search outputs remain external evidence. Audio and derived transcripts inherit source restrictions. Lack of a cheap text scanner does not waive required classification; an unsupported handling obligation rejects rather than silently bypassing it. Treat the billing-unit table as illustrative, not commercial qualification. | §§5.1, 5.9, 13.5; T-81. |
| **R13** | Realtime telemetry | **Retain prohibition; defer feature claim verification.** Prohibited audio/response content must be excluded before callbacks, logging, buffers and exports. The addendum's documentation table does not establish behavior of the frozen release or enable realtime. Inspect the exact selected implementation before relying on it. | §§4.3–4.4, 13; T-83 at first reliance. |
| **R14** | Direct-call migration and egress | **Defer execution to integration.** Retain an owner-assigned inventory and eventual egress backstop for the expressly onboarded cohort. SDK base-URL redirection alone does not prove identity, semantics, handling or accounting conformance. Revoke shared provider credentials only after their consumers are identified and replacement paths qualified. Preserve the Vega hold. | §§3, 14–15; integration roadmap; T-80. |
| **R15** | Valhalla step 3/4 | **Carry as attributed future requirements; defer activation.** Record planned commission freshness, common label vocabulary, Trimorphus consultation, Norns budget authority and activation fencing. Inspect Valhalla 0.4 before declaring clause correspondence. Existing deterministic checks remain controlling; a gate lease cannot quietly weaken the effective-revocation boundary. | §§4, 5.4, 9, 10.4, 18 and integration roadmap. |
| **R16** | Proto / ADR 0051 | **Defer integration; retain mapping as proposed.** Cite P-15/P-17 and ADR regions only as reported by Addendum A until primary documents are inspected. Correct any phase table that appears to postpone currently mandatory identity, source handling or work-binding checks. Full later instrumentation is different from admission prerequisites today. | §§8–9, 13, 15; joint contract review. |
| **R17** | Cached synthesized phrases | **Defer.** It is an optional content cache with quality, handling, freshness, storage and cost evidence requirements, not part of the first retrieval slice. No saving magnitude is established for Duranki. | §5.6; deferred roadmap. |
| **R18** | Cloud hosting | **Retain attributed planning context; defer selection.** Addendum A describes GCP and a planned AWS move. No direct infrastructure evidence was provided here. PostgreSQL selection does not by itself adopt Cloud SQL, RDS, a migration date or common physical storage. | §§14.3, 18; planning context only. |

## 5. Terminology for the corrected draft

| Concept | Recommended term | Meaning and boundary |
|---|---|---|
| Stale-worker fence | **Activation epoch** | Valhalla's authoritative activation identity for a scoped actor/instance. When qualified, it participates in admission and first-write freshness; the orchestrator fences acceptance. It does not create a new effect or clear exposure. |
| Authorized invocation | **Execution generation** | Duranki's existing invocation identity inside its authenticated WorkKey. Authorized escalation is a new generation; a transport reconnect is not. |
| Authority invalidation | **Authority revision** | Monotonic scoped revision, or an authority revision vector, identifying changes to relevant authority. Comparison is not a replacement for synchronized first-write control, deadlines, reservation state or single-send ownership. |
| Realtime transport incarnation | **Connection sequence** | Session-scoped identifier/counter distinguishing connections. It confers no authority, creates no automatic retry permission and does not prove a previous connection's work stopped. |

These names are an authoring recommendation, not four new public fields approved for wire 0.2. The exact schema and versioned migration remain explicit contract work. Do not change original artifacts to erase historical terminology.

## 6. Important clarifications beyond a mechanical merge

### 6.1 A logical effect must retain the full work namespace

The adopted contract defines `WorkKey = (principal_id, task_id, step_id, step_revision, execution_generation)` in its authenticated namespace, with canonical-work digest equality additionally required for deduplication. Addendum A's shortened mapping is descriptive only; it must not replace that identity. A conflict under the same work key remains a conflict, not an opportunity to send another operation.

An activation change or connection change does not authorize another provider attempt for the same effect. New attempts and semantic escalations still follow the admitted lifecycle and financial authority. Non-step external call IDs need an explicit trusted namespace and mapping; importing such IDs must not fabricate a controlled Duranki send.

### 6.2 Absence, assertion and verification are separate axes

The addendum's reasons (`not_yet_issued`, `not_applicable`, `caller_omitted`, `unavailable`) explain why a shared metadata field has no value. Provider counter evidence (`absent`, `null`, `known`, `invalid`) describes observed usage. Commission status (`absent`, `asserted`, `verified`) describes reference evidence. None replaces either of the others.

Before commission enforcement exists, an asserted commission is recorded and queryable but supplies no execution authority. Once an enabled profile requires a verified commission, an “unavailable” reason does not permit work anyway. Likewise, a missing authenticated principal cannot be admitted merely by adding `caller_omitted`.

Later verification is appended with its own evidence/time; it must not rewrite an old assertion as though it was verified before the original dispatch. Legacy rows should not be assigned a reason or relationship that their original evidence cannot support. Shared-field coverage applies to applicable event types: rejection and pre-admission observations must remain recordable even when no attempt, cost or complete identity was created.

### 6.3 Preserve existing handling and identity prerequisites

Addendum A §7.2 places some step identity in Phase 1b and full taint instrumentation in Phase 2. That schedule must not weaken the adopted request contract, which already requires authenticated work identity and verified source restrictions for supported content. Migration mode tolerates only expressly approved analytical gaps, not missing access, handling or budget authority. A future Proto-wide rollout remains separate from correctness of today's standalone admission.

### 6.4 Do not create two financial authorities during federation

A budget-account interface is useful now. Transferring that authority to a future service is not just exchanging a connection URL. The cutover contract must identify who owns outstanding reservations and delayed settlements, prevent both services authorizing against the same unencumbered balance, preserve parent/child envelopes without double allocation, and recover unknown exposure before admission resumes. This is a future qualification requirement, not new DEV-12 implementation scope.

## 7. Proposed acceptance-test crosswalk

Preserve v1.2 **T-01–T-76**. Retain the eleven Addendum A subjects, corrected and scoped, as **T-77–T-87**. Keep the original A-42–A-52 source numbers as provenance aliases. This one-to-one crosswalk favors traceability over silently merging away requirements; related existing tests are linked rather than counted as new observed passes.

All new rows are **requirements proposed; execution not assessed here**. Split compound expectations into stable sub-IDs when creating the assurance register. “Not evidenced here” must not be rewritten as “not implemented.” The crosswalk is proposed for the corrected draft, not claimed as already adopted.

| Original | Proposed | Requirement / corrected outcome | First applicable scope | Related tests |
|---|---|---|---|---|
| A-42 | **T-77** | **Shared-field presence and absence reasons.** Reject invalid new-profile record shapes; do not reinterpret or invalidate legacy rows. A reason code does not waive required authority. | New shared-metadata profile | T-49, T-66 |
| A-43 | **T-78** | **Trusted delegation endpoints and reported intermediate links.** Reject forged authority-bearing endpoints; retain unverified intermediate links only as attributed assertions; test direct-human and autonomous cases. | Trusted identity/delegation profile | T-60 |
| A-44 | **T-79** | **Record-only commission references.** An asserted reference neither grants nor denies execution by commission authority before that authority is enabled; syntax/size/handling checks still apply. | Record-only metadata profile | T-45, T-60 |
| A-45 | **T-80** | **Integrated non-text provider-egress containment.** A working authorized path succeeds; direct forbidden application/worker paths to that endpoint fail and alert. No whole-platform claim from a local probe. | Explicitly onboarded integration cohort | T-38, T-71 |
| A-46 | **T-81** | **Search-query handling and destination permission.** Disallowed query handling rejects before send; provenance and restrictions survive returned search data. | Qualified search contract | T-45, T-68, T-69 |
| A-47 | **T-82** | **Session reservation-extension failure.** Prevent further unauthorized release under the proved bound, request/observe stop, and retain uncertain exposure; local closure does not settle the session. | Qualified incremental-reservation lifecycle | T-50, T-72, T-75 |
| A-48 | **T-83** | **Realtime content exclusion from telemetry.** Prohibited complete response content reaches no diagnostic callback, exception log, export buffer or sink; permitted accounting metadata remains available. | Qualified realtime adapter/telemetry profile | T-5, T-76 |
| A-49 | **T-84** | **Missing native-operation usage.** Missing/null/invalid required usage leaves cost unknown and relevant exposure held; separate estimates do not settle it; later evidence appends once. | Qualified native-unit accounting contract | T-18, T-49, T-50 |
| A-50 | **T-85** | **Commission revocation after commitment before first write.** Effective scoped revocation blocks queued unsent work at the qualified first-write boundary; a check before a lower wait is insufficient. | Future verified-commission integration | T-24, T-45 |
| A-51 | **T-86** | **Commission revocation during a session.** Stop further unauthorized release within a qualified bound; preserve committed/in-flight exposure and distinguish local close from provider-confirmed stop and settlement. | Future verified-commission session integration | T-72, T-85 |
| A-52 | **T-87** | **Stale activation fencing at request and acceptance.** Reject unauthorized activation at admission and first-write freshness; orchestrator rejects stale acceptance. Retain late usage/liability evidence. No new effect or budget merely from activation change. | Future activation-fencing integration | T-24, T-60, T-66 |

No prior receipt is renumbered or retrospectively relabelled. A former test number without a source-document namespace is ambiguous. Register entries must carry requirement version, profile, build/evidence scope and observation status. Passing a synthetic test qualifies only the exercised profile; it does not close integrated egress, commercial billing or Valhalla acceptance.

## 8. Correction 01 entry direction

The architecture correction should incorporate the recovered owner decisions, the R1–R18 dispositions, terminology, and test crosswalk alongside the unchanged applicable M-01–M-07/N-01–N-07 dispositions and the 22-item research map from Disposition 01. Separate normative requirements, dated assurance evidence and roadmap sequencing.

The first standalone implementation remains the proposed operation-aware foundation and synthetic embedding/reranking proof, including a genuinely non-token tariff. Define any shared metadata envelope within the reviewed successor contract without changing legacy canonical bytes. Do not add mandatory production PostgreSQL deployment, Proto edits, Norns/Trimorphus services, realtime transport, external caching or a Vega cohort merely to complete that slice.

The missing Valhalla/Proto originals limit independent citation confirmation, not our ability to preserve the recovered decisions and identify the corrections above. Keep those citation checks explicit; do not mark integration correspondence verified by reviewing this derivative addendum alone.

**No architecture adoption, product change, schema migration, credential action, provider request, paid test, Git commit/merge, owner-profile update or Vega/Valhalla integration was performed or commissioned by this note.**

## 9. Source basis

- **A:** `duranki-addendum-a.md`, draft 0.1, all sections; received identity in §2.
- **H:** `DURANKI-ADDENDUM-A-RECONCILIATION-HANDOFF-2026-10-25.md`, especially §§3–6; recovered decisions and proposed reconciliation, not the original chat transcript.
- **V:** `DURANKI-ARCHITECTURE-v1.2-REVIEW-DRAFT-2026-10-25.md`, especially §§4–5, 8–10 and 15–18. Review draft, not adoption.
- **D:** `DURANKI-v1.2-CLAUDE-REVIEW-DISPOSITION-01.md`, especially M-04–M-06 and N-02/N-06. Preserved; N-02's uncertainty is resolved only as specified here.
- **C:** `DURANKI-WP-A-CONTRACT-v0.3-CORRECTION-01.md`, §§2.1–2.2, 4–5 and 9, read with `WP-A-A2-ADOPTION-01.md`: source handling, authenticated WorkKey, separate outcomes and replacement usage revisions.
- **E:** Supplied DEV-11 contract/result/receipts establish bounded cache-accounting evidence, not commercial audio/search behavior.
- **Unverified primary dependencies:** Valhalla 0.4; Proto Runtime Proposal and evidence report dated 23 October 2026; referenced ADR 0051 regions. Their claims are attributed to A/H, not silently promoted to independently inspected sources.
