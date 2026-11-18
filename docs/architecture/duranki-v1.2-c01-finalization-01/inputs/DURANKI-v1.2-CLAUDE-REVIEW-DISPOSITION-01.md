# Duranki architecture v1.2 — Claude review disposition 01

**Date:** 25 October 2026  
**Status:** Author assessment and proposed correction direction; not owner adoption, independent closure or an implementation commission  
**Review:** Owner-supplied Claude 5.5 Opus review, `Pasted text(20261025-234956).txt`  
**Candidate reviewed:** `DURANKI-ARCHITECTURE-v1.2-REVIEW-DRAFT-2026-10-25.md` and its change note

## 1. Overall disposition

Concur with the review's overall finding: retain the separated worker/guard/sender architecture, typed operations, native-unit accounting, permission hierarchy and task-quality objective, but correct v1.2 before adoption and before issuing DEV-12. The missing research disposition, unclear standalone completion boundary and incomplete successor-contract decision are substantive authoring gaps.

Accept the problems identified in all seven material findings, with qualifications to M-01, M-03, M-04, M-05 and M-06 below. The proposed solutions must not accidentally reintroduce premature Vega integration, probabilistic spending bounds, unfenced authority checks or changes to the legacy wire contract.

The review explicitly covered only the architecture and change note, not the reconnaissance, implementation evidence, comparison diff or document-validation record. Its architectural agreement is not a new acceptance of DEV-11 or a verification of deployed state. This assessment compares the review with the supplied architecture, adopted contract excerpts, reconnaissance, DEV-11 records and the 22 October research report. Two narrowly scoped external checks concern RFC 8693 and byte-level BPE, not current commercial prices or provider qualification.

**Preserved owner decision:** develop Duranki independently while Larry completes the prerequisite Vega work. Neither this review nor an optional spending-export importer authorizes Vega instrumentation, integration or provider access. External response caching remains deferred.

## 2. Material findings

### M-01 — Measurement and development sequencing

**Disposition: accept the measurement gap; qualify the proposed remedy.**

The current sequence does not yet produce representative task acceptance or production spending evidence. That is a limitation of the agreed standalone development stage, not a reason to reverse the owner's integration hold. The architecture should distinguish three deliverables:

- **Engineering assurance:** whether the controlled system preserves identity, authorization, accounting, duplicate suppression and exposure under its admitted contracts.
- **Observed spending baseline:** what available account/project/key/model/operation observations actually report, with unknown attribution and coverage visible.
- **Accepted-task efficiency:** cost, outcomes and latency for complete comparable task cohorts. This remains the governing optimization metric and requires suitable task evidence.

An offline importer for owner-supplied provider usage/cost exports is a useful early, independent development item. It must preserve source identity, account/currency/period, observation and import times, granularity, overlap, corrections and linkage to controlled attempts. An imported aggregate is not a newly created provider attempt. Importing a second overlapping report cannot add the same spending twice.

Do not promise that provider exports identify all fifteen operation families or individual agents. Map only what the supplied export supports; keep unresolved operation, agent, task and charging-owner fields unknown. Account spending cannot, without further evidence, establish task acceptance, delegation, agent efficiency or the spine/leaf taxonomy. The Phase 0 spend-share trigger is **not yet evaluable**, rather than waived or satisfied.

State the engineering reason for the proposed embedding/reranking pair: these exercise synchronous typed non-text results, independent operation permissions, vector/index compatibility and shared-ingestion accounting without requiring media/session machinery. Their selection is not a claim that retrieval is the largest cost centre. Available spend observations should inform later prioritization without becoming a prerequisite to every correctness test.

**Correction locations:** §§0.1, 1, 9.2, 10.6–10.7, 15 and the separate roadmap.

### M-02 — Measurable progress and a standalone exit

**Disposition: accept.**

Create a separate T-01–T-76 assurance register. Each entry needs requirement text/reference, applicable profile, scoped result, evidence/build reference, observation date, limits and remaining proof. Compound tests need stable sub-identifiers. Use “not evidenced in the reviewed records” where appropriate; absence of evidence is not proof that nobody implemented or tested something.

A bounded synthetic pass must not turn the whole target requirement green. For example, one process's allowance concurrency test does not establish multi-replica financial consistency. Register source implementation, controlled-target evidence, deployment observation and commercial/integration evidence separately.

Define a **standalone assurance profile** with an explicit supported-operation and threat boundary. Its exit should cover the installed clients, authenticated service, isolated worker, final binding and sender freshness, durable accounting, bounded allowances where claimed, unknown exposure, no-repeat behavior, preserved restart state and relevant operator journeys. It excludes production HA, real office-presence claims, representative Vega telemetry and invoice accuracy until those are separately introduced.

Keep the production phase gates intact. State where office-origin assertions, replication and commercial reconciliation first become applicable. Standalone progress should be measurable without falsely declaring the entire production phase complete or adding cloud deployment as a prerequisite to a synthetic extension.

**Correction locations:** §§5.1, 7.1, 15–16; new assurance register.

### M-03 — Token-efficiency research integration

**Disposition: accept; correct the finding's overstatement about complete absence.**

The 22 October report was omitted from the v1.2 source basis and was not systematically dispositioned. Add it and a numbered 22-item incorporation/deferment map. The proposed map is in §4 of this note.

The draft already says in §6.4 that incremental costs include cache state and switching cost. Section 6.7 already names uncached input work and KV occupancy. The deficiency is not total absence: the prediction inputs, explicit decision treatment, uncertainty and contract ownership are insufficiently specified.

Add reasoning effort/thinking mode and service tier to the qualified configuration where applicable. Resolve defaults explicitly and distinguish requested from effective settings. A changed model/effort/adapter/compaction combination cannot inherit quality evidence merely because the displayed model name is unchanged. Service tiers may also change lifecycle and latency, so tier selection is more than a price label.

Carry forward the report's compaction classes: deterministic masking with retrievable lineage, spine-history summary, inter-agent handoff summary and provider context management. Deterministic masking is still subject to handling, retrievability and task-quality requirements; it is not automatically harmless. A summary that replaces spine state is not an ordinary cheap transformation.

Distinguish **predicted cost for ranking**, **proven maximum exposure for admission**, and **observed cost for settlement**. Cache-state estimates and switching/re-warming effects belong in predictions and evaluation, not in an unproved reduction of financial reservations. Avoid double-counting switching effects already represented by candidate cache-state quantities.

The paper's measured magnitudes and proposed mechanisms remain hypotheses for Duranki, as its own threats-to-validity section emphasizes. Do not assert that cache events dominate Duranki's actual spending before relevant traffic is measured.

**Correction locations:** §§5.3, 5.5, 6.3–6.7, 9–12, 17, 20; research disposition companion.

### M-04 — Authority freshness and credential rotation

**Disposition: accept the distinction; qualify the epoch mechanism before implementation.**

A scoped authority epoch/vector is a useful proposed invalidation mechanism. It is not, by itself, a final-send synchronization mechanism. A sender can read a matching epoch, another actor can revoke, and the sender can then write. The required relation between effective revocation and first application-request write must still be enforced by a qualified lock/fence/ownership protocol.

Any authority-changing transaction must update the relevant authority records and their version/epoch consistently. The sender must use a coherent authority view, reject stale ownership and fail closed when required authority cannot be established. Rollback must not move authority generations backward or revive revoked grants. Unknown outcomes must preserve exposure.

Epoch equality also does not establish an unexpired deadline, an unconsumed attempt, an adequate current reservation or available capacity. Those checks remain. The review's suggestion that the epoch store is the *only* strongly consistent state is too broad: reservation, duplicate-send ownership and authority-update consistency still need their own guarantees.

Separate the **logical credential binding**, its **authorization/account-scope revision**, and the **secret-material revision actually used**. An explicitly qualified same-scope routine rotation may resolve the new secret at send time without invalidating every queued plan. It must establish equivalent endpoint/account/project/permission and applicable handling scope, and record the actual secret version safely. Unknown equivalence, disabled access, changed account scope, suspected compromise or revocation blocks/revalidates affected queued work.

Keep the more conservative existing behavior until that successor rotation contract is tested. This is not permission to bypass DEV-10/11 revision checks today. Split T-39 and T-45 into rotation, revocation, compromise/scope-change and stale queued-send cases. Upstream key revocation and local binding changes remain separate facts.

**Correction locations:** §§4.4–4.5, 5.3–5.5, 10.4, tests 24/39/45/75.

### M-05 — Reservation efficiency and long-running work

**Disposition: accept the performance concern; require a proof-qualified alternative.**

DEV-11's provider-context-ceiling bound is intentionally conservative. The review's illustrative input-only ratio is approximately `400,000 / (60,000 × (0.10 + 0.90 × 0.10)) = 35.09`. This is an illustration under those assumptions, not measured Duranki utilization, and it excludes output and any additional fees.

The current wording is “A byte cap is a handling restriction, not by itself a token bound.” It is not a categorical ban on qualified byte-based bounds. Preserve that distinction and add an explicit qualification path.

Byte-level BPE can establish an upper bound for the exact byte sequence it tokenizes when its transformations and special-token treatment are known. That does not automatically bound the provider's complete billable input. A qualifying contract must account for actual final preparation, normalization, framing, separators/special tokens, repeated inputs, tool rendering, provider additions and any enabled modality. An empirical average bytes-per-token ratio, an arbitrary hidden-token margin or an untrusted worker estimate is not a hard bound.

Where both are independently valid, a successor may use the smaller of the provider's enforced input ceiling and a request-specific proven bound. Every billable component still needs coverage, and unknown cache residency must not be priced as a guaranteed hit. Preserve the DEV-11 contract until a replacement is explicitly qualified.

Add reservation/settlement ratio, held exposure, reservation-caused admission rejection, release latency and unknown-exposure age as diagnostics. Release only the excess established by sufficient usage/settlement evidence, through one atomic, revision-safe adjustment. Partial usage does not prove the remaining liability is zero.

For future streaming/realtime work, rolling reservations are an option, not an automatic solution. Each increment must cover a proven maximum of further billable work, including processing already committed, reporting delay and cancellation/stop uncertainty. Closing the local connection does not prove remote execution or billing stopped. A fully bounded session reservation is also valid. Without either a finite full-session bound or a qualified incremental bound, hard-ceiling admission remains unavailable.

**Correction locations:** §§8.6, 10.4, 10.7–10.8 and tests 48/50/72/75. No realtime implementation is added to DEV-12.

### M-06 — Successor operation contract

**Disposition: accept the proposed structural direction; preserve the full legacy boundary.**

Before DEV-12 implementation, settle a common versioned envelope, `operation {type, version}`, an operation-specific request/response schema, trusted identity and compatibility references, and operation-domain-separated canonical binding. Separate operation type, versioned contract, unique execution attempt and administrative command/idempotency identity. Inspect the actual existing registry field before choosing an additive replacement name or migration.

Retain the existing wire `0.2` parser, canonical digests, profile semantics and historical vectors. Do not simply relabel every legacy request `text.generate@1`: the supplied development history includes caller-owned tool cycles as well as plain text. Any legacy display mapping must identify its qualified semantics and remain distinct from rewriting signed work or admitting new operations. No legacy request obtains new capabilities through a compatibility wrapper.

Represent usage components by attempt **and usage revision**, with component identity, native unit, exact quantity where known, field-evidence state, normalization semantics and immutable price reference. Keep chargeable components distinct from overlapping totals and diagnostic subsets. Persisted absence/null/invalid/zero meanings must survive. One effective revision per attempt is used at a report cutoff; revisions are not added as charges.

The generic component representation does not permit arbitrary units or unknown commercial fees to become billable schedules. Operation schemas and qualified price functions remain the allowlist. Logical architecture decisions precede code; exact successor schema/profile identifiers and serialization vectors belong in the bounded contract delta.

**Correction locations:** §§5.3, 5.7, 8.2, 10.2, 14.6, 18 and test 47.

### M-07 — Demonstrate a genuinely non-token price

**Disposition: accept.**

Require a non-token synthetic tariff in DEV-12. One example is a fictional rerank request containing one query and 1–25 documents, with a search unit of up to 10 documents:

```text
units = ceil(document_count / 10)
cost = max(USD 0.005 per request, USD 0.003 × units)
```

The independently calculated boundary examples are:

| Documents | Units | Fictional USD |
|---|---:|---:|
| 1 or 10 | 1 | 0.005 |
| 11 or 20 | 2 | 0.006 |
| 21 or 25 | 3 | 0.009 |

The maximum for that admitted domain is USD 0.009. Reject zero or more than 25 documents before sending. Test missing/null/invalid/explicit-zero billed-unit evidence against the contract; do not default a missing provider observation to the locally expected count. If contractual derivation is permitted, record it as such rather than mislabelling it provider-reported. Repeated queries, new attempts and split batches must obey the per-request minimum independently. These are test-fixture values, not commercial rates or authorized spending.

**Correction locations:** §15.2 and T-48 subcases.

## 3. Notes N-01–N-07

| Note | Proposed disposition |
|---|---|
| **N-01 — Document structure** | Separate normative architecture, dated assurance/evidence register, and development roadmap. Keep stable section/test references and the normative phase gates. Use orthogonal state dimensions with defined events/transitions; readiness, cost evidence and coverage are not one linear state machine. Preserve corrections as appended evidence. |
| **N-02 — PostgreSQL** | Prior adoption is not established by the reviewed material. Both supplied architectural versions leave the production ledger database open; a separate context check did not recover an owner adoption. Record an existing authoritative decision if one is found, otherwise retain an explicit decision item. Do not silently treat the reviewer's recollection as owner authority, and do not make a production database decision a blocker to the existing standalone SQLite extension. |
| **N-03 — Stale clauses** | Correct Ninshubur to rank admitted candidates before trusted plan issuance; repair Nabu's limit sentence; replace the removed cache-miss exit-metric reference with cost/quality/latency evaluation and cache diagnostics; label Redis/replicated operational notes as target rather than current deployment. |
| **N-04 — Service tier** | Include applicable tier in configuration, price, lifecycle and latency evidence. Preserve requested/effective tier distinction. Treat batch/flex/priority choice as a later eligible routing dimension; no claim that it offers the largest saving without measured demand, latency tolerance and actual rates. |
| **N-05 — Compound tests** | Add stable sub-IDs, initially for T-39, T-45, T-48, T-50 and T-62 and wherever partial evidence otherwise becomes ambiguous. Preserve parent IDs and require all applicable subcases for an unqualified parent pass. |
| **N-06 — Trusted agent identity** | Prefer a distinct authenticated service principal or an explicitly trusted agent-to-principal binding. RFC 8693 is a useful delegation representation candidate, not an instruction to add OAuth infrastructure to DEV-12. Validate issuer/audience/expiry/current actor and scope through the chosen trusted profile. Nested `act` history is informational, not authority for previous actors; charging ownership and workflow lineage still need their own validation. |
| **N-07 — Product boundary** | Name exclusions: no arbitrary enterprise API proxy, provider marketplace/reselling, general identity-provider administration, agent planner/tool orchestrator, model training/hosting control product or replacement for provider invoicing. Qualified AI-service operations, account credentials, permissions and reporting are legitimate Duranki responsibilities, not scope creep merely because they need a usable console. |

## 4. Proposed disposition of the research report's 22 items

This is a proposal for the correction, not a claim that the changes are already incorporated or implemented. Numbering follows the 22 October report §7.2. Its empirical magnitudes and unvalidated mechanisms are not automatically adopted.

| # | Report item | Correction / deferral direction |
|---|---|---|
| 1 | Billed-rate segment telemetry | Add the measurement contract. Distinguish exact provider quantities from estimated segment allocation; never invent per-block cache billing unavailable from the provider. Real producer instrumentation remains later. |
| 2 | Replace the cache-miss gate | Already incorporated in §15; repair the stale §17 reference and retain invalidation diagnostics without claiming savings. |
| 3 | Cache-domain identity and affinity | Specify domain identity and supported affinity constraints; qualify provider-specific keys/rate behavior later. No physical-residency guarantee. |
| 4 | Security-domain cache isolation | Retain the isolation requirement. Defer specific lab hash algorithms and response-cache implementation to the selected serving contract; public side-channel resistance does not suppress authorized operator accounting. |
| 5 | Signed cache controls | Require binding when explicit controls are enabled. DEV-11 remains implicit-only; additional TTL/key/reference controls require a separate qualified contract. |
| 6 | Prompt layout / prefix-churn lint | Add future caller/preparation ownership and a metadata-only lint boundary; do not silently rewrite admitted prompts or instrument Vega now. |
| 7 | Cache-state estimator | Specify evidence, freshness and uncertainty inputs to ranking/capacity models. Defer implementation until data or a selected serving stack exists. Predictions cannot replace exposure bounds. |
| 8 | Effort / thinking mode | Add to configuration and change-control identity now; actual sweeps remain gated. |
| 9 | Switching and whole-leaf cost | Make the existing cost obligation explicit, with multi-call and re-warming effects counted once and prediction uncertainty visible. |
| 10 | Compaction classes and accounting | Incorporate the four classes and provenance. Avoid recursively summarizing lossy summaries by default; any exception needs its own contract and quality evidence. A new purpose value requires a versioned change, not silent wire-0.2 expansion. |
| 11 | Replay validity | Retain valid single-step replay/repricing and explicitly qualify branched trajectories with controlled environments. Defer unsupported counterfactual claims rather than prohibit every properly controlled whole-task experiment. |
| 12 | Cascade / verifier refinement | Clarify that the existing aggregate `r` is conditional on escalation. Its equation is not wrong if `r` is the correct mixture. Separately record false-rejection and detected-failure strata, independent audits and generator-dependent verifier qualification in later evaluation. |
| 13 | Sticky replans | Preserve current eligible deployment when possible; distinguish non-security publication from effective revocation. No stale-authority exception and no automatic change to current version checks. |
| 14 | Retained segment feature schema | Require a separately approved schema and handling review; a hash or aggregate is not automatically declassified or permanently retainable. |
| 15 | Token estimation | Separate predictive estimators from proof-qualified reservation bounds. Defer unqualified tokenizer/byte-ratio mechanisms. |
| 16 | kNN baseline and bake-off criterion | Add as a later comparison candidate with quality eligibility first, then cost, latency and stability. No new dependency now. |
| 17 | Lab CPU-KV/preemption design | Defer concrete mechanism and T-33 changes until a serving stack and cancellation/demotion/capacity evidence are available. Retain physical-capacity proof requirements. |
| 18 | Effort sweeps and cascades | Defer experimental execution; include in evaluation roadmap, with separately approved configurations and paid scope. |
| 19 | Prefix fork / home-cache experiments | Defer execution pending valid fixtures/cohorts and demonstrated handling compatibility. No isolation relaxation to obtain cache hits. |
| 20 | TTL / keep-alive prediction | Defer pending supported controls, billed rates and gap data. Keep-alives are provider work, not passive observation or page-refresh behavior. |
| 21 | Masking versus summarization | Defer experiments but establish compaction classes and outcome criteria now. Preserve the admitted work and version transformations. |
| 22 | Single-agent versus fan-out | Defer experiments pending comparable task/outcome evidence. Keep distinct attempts, authorized fan-out limits and outstanding exposure; task completion alone cannot release unknown liability. |

## 5. Bounded correction and re-review

Produce **v1.2 Correction 01**, not a fresh architecture redesign. Preserve v1.1, the submitted v1.2 and the original review. The correction should deliver the normative architecture, separate assurance register and separate roadmap, with explicit cross-references and a finding-to-clause map.

Before issuing DEV-12, settle the operation-envelope and legacy-compatibility direction, the standalone profile, non-token fixture requirements and the research dispositions relevant to that slice. Treat authority-epoch implementation, optimized input bounds, realtime credit windows, provider importers and production topology as separately scoped work unless a bounded implementation brief explicitly includes them. Do not overload the retrieval slice with every future capability.

A re-review should distinguish: correction authored; correction independently checked; owner adoption; implementation; controlled proof; deployment; commercial qualification. This assessment closes none of those stages by declaration.

**No source, schema, dependency, credential, owner profile, provider account or Vega application was changed by this assessment. The existing architecture files remain unchanged.**

## 6. Source basis

- **R1:** Owner-supplied Claude review, `Pasted text(20261025-234956).txt`, material findings M-01–M-07 and notes N-01–N-07.
- **A1:** `DURANKI-ARCHITECTURE-v1.2-REVIEW-DRAFT-2026-10-25.md`, especially §§0–1, 4–6, 8–10 and 15–20.
- **A2:** `DURANKI-ARCHITECTURE-v1.2-CHANGE-NOTE-2026-10-25.md`.
- **P1:** *Token Efficiency in Agentic LLM Systems: Gauging, Measuring and Managing Cost, with Application to Duranki*, 22 October 2026, particularly compaction classification, cost-model calibration, §7.2's 22 ranked items and §8's limitations. Read as supplied research, not independently reverified empirical literature.
- **S1:** Supplied DEV-11 `CACHE-ACCOUNTING-CONTRACT.md`, result, review handoff and controlled target/browser records.
- **S2:** WP-A/A2 adoption and *Duranki WP-A Contract Candidate v0.3 — Correction 01*; supplied tool-cycle development history. Legacy semantics and usage-replacement revisions remain controlling until expressly changed.
- **S3:** `MODEL-SERVICE-COVERAGE-REPORT.md`, 25 October 2026: static operation coverage, not traffic or spending measurement.
- **X1 — narrowly checked external standard:** RFC 8693, §4.1, OAuth 2.0 Token Exchange, https://www.rfc-editor.org/rfc/rfc8693.html#section-4.1 . Current actor versus informational prior-actor history; not a Duranki implementation decision.
- **X2 — narrowly checked primary algorithm example:** OpenAI tiktoken, `_educational.py`, https://github.com/openai/tiktoken/blob/main/tiktoken/_educational.py . Byte-level BPE starts with bytes and merges them; this does not establish any commercial model's complete input billing bound or a frozen dependency selection.
