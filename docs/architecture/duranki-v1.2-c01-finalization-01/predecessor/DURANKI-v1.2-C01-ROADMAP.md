# Duranki v1.2 Correction 01 — development roadmap

**Date:** 25 October 2026  
**Status:** Proposed sequencing and bounded implementation scope; not a commission or paid-work authorization  
**Owner:** Larry Mitchell  
**Governing draft:** [DURANKI-ARCHITECTURE-v1.2-CORRECTION-01.md](DURANKI-ARCHITECTURE-v1.2-CORRECTION-01.md)  
**Evidence:** [DURANKI-v1.2-C01-ASSURANCE-REGISTER.md](DURANKI-v1.2-C01-ASSURANCE-REGISTER.md)

## 1. Direction and completion boundaries

Build Duranki independently while the prerequisite Vega work finishes. Preserve the separated worker/guard/sender, adopted legacy wire semantics and local operational history. Develop usable provider/account setup, operation coverage, accounting, rules and evaluation tooling against controlled producers before platform integration. External response caching remains deferred.

Keep three deliverables separate: engineering assurance, observed account spending, and accepted-task efficiency. Account exports can improve spend visibility without Vega, but may not identify an agent, task class or outcome. The Phase 0 taxonomy/spend-share trigger remains not evaluable until its actual inputs exist. No inference from a scripted cost chart closes that gate.

The architecture defines production phase guarantees in §15.1 and the standalone exit in §15.2. The evidence register is the progress measure; a development commit is not a production phase completion.

## 2. Ordered standalone work

| Position | Work | Completion boundary | Exclusions / dependency |
|---|---|---|---|
| 0 | Review/adopt the applicable Correction 01 delta and exact successor contract | Architecture direction, shared-envelope binding, schemas and vectors reviewed for the selected scope | No product changes or real calls by document adoption alone |
| 1 | **DEV-12: operation-aware accounting and retrieval proof** | §3–§5 below | No Vega, real providers, deployment or new infrastructure |
| 2 | **WP-SPEND-IMPORT: offline usage/cost-export importer** | §6; positioned immediately after DEV-12, before further policy/adaptor expansion | Separate brief; no live provider polling or Vega dependency |
| 3 | Provider/account setup completion, allowance clarity and useful alerts | Clear setup/authentication/inventory/permission/rate/health states; current access and no hidden work | No implicit grants, discovery, paid test or commercial pricing edits |
| 4 | Named deterministic policy drafts, preview/audit/rollback and health/cooldown scaffolding | Read-only explainability and synthetic rule tests | No live model substitution from publishing an unqualified policy |
| 5 | Selected additional text/tool/stream contracts; then bounded transcription and vision | Each contract/lifecycle independently qualified | Provider/library advertised support is not blanket approval |
| 6 | Hosted-search fee contracts and selected adjacent-service observations | Complete native billing domain and explicit coverage | Fee gaps remain unknown; observation is not enforcement |
| 7 | Qualified alternative/recovery behavior, image/TTS artifact handling and private/lab controls | No-repeat/exposure, generation-versus-retrieval and physical capacity/handling tests | No unsafe download retries, arbitrary URLs or index-incompatible substitution |
| 8 | Realtime/long-running lifecycle and opaque-execution observation | Finite session or proved incremental bound, stop uncertainty and attribution | No unbounded hard-ceiling claim |
| Later | Standalone evaluation workbench, then explicitly approved Vega cohort and representative rules | Comparable complete outcomes and coverage before any learned promotion | Owner releases integration hold; no date inferred |

Position 2 is a committed **proposal of order**, not an unspecified “useful later item”: it is the next standalone work package after the bounded retrieval proof. Its format-design and synthetic fixtures can be prepared independently under a separate brief; there is no technical dependency on live Vega. Real owner-supplied exports, when available and authorized, inform later priorities without changing DEV-12's engineering rationale or becoming a prerequisite to correctness testing.

## 3. DEV-12 entry and contract delta

**Title:** Operation-aware accounting foundation and synthetic retrieval-operation proof.

The reason embeddings/reranking go first is architectural: synchronous non-text outputs exercise operation permissions, typed results, vector/index compatibility, native charging and shared ingestion without audio/session/media transport. No measured claim says they are the largest cost centre.

The entry delta must be frozen and independently reviewed before product changes:

| Decision | Required result |
|---|---|
| Versioning | A separate common successor envelope with `operation {type, version}`, bounded typed request/response union and explicit capability profile; exact names/identifiers selected in the delta |
| Legacy | Strict wire `0.2`, existing projection/digests/vectors, legacy tool-cycle semantics and installed-client behavior remain; no general relabelling as plain text |
| Canonical binding | Full trusted WorkKey and canonical-work equality; operation-domain-separated serialization with unambiguous encoding; approved input ordering and defaults |
| Shared metadata **in this same successor** | Commission reference/status/reason, delegation chain/status/reason, activation epoch/reason and event applicability per architecture §9.4 |
| Binding placement | Canonical commission/delegation admission snapshots; activation in signed execution context, outside the logical-work key; trace/time and later verification outside immutable work |
| Identity | Distinct authenticated principal, agent binding, initiating person, charging owner and delegation lineage; synthetic direct-human, delegated-agent and autonomous cases |
| Ledger | Add lossless typed envelope storage and linked later verification; usage components keyed by attempt **and revision**; old rows preserved without fabricated backfill |
| Registry naming | Inspect the actual administrative `operation_id` surface before choosing an additive rename; separate command, operation type/contract and attempt identity |
| Financial contracts | Closed fictional tariff domain, exact native units/evidence, full conservative bound, rounding and per-attempt minima/tier conditions |

The common envelope is now part of the required decision, not optional scope for another future version. Exact wire/schema/projection constants and executable goldens are not supplied or adopted by this architectural packet. That bounded contract artifact remains the concrete pre-code entry requirement.

## 4. DEV-12 implementation and proof surface

Use the existing clients, Coordinator, isolated worker, guard, trusted sender, registry/ledger and operator UI. Add only the code/schema/tests necessary for the reviewed successor and two synthetic retrieval operations. Use an independent controlled receiver, fictional models/rates and a versioned fake corpus/index; the corpus owner performs index side effects, not the sender.

Embedding proof binds ordered bounded batches, document/query role, exact vector-space profile and index reference; validates count, dimensions and finite values; and rejects silent drop/truncation/reordering. Equal dimensions alone do not establish compatibility. Reranking binds query and ordered candidates; validates returned IDs/indices/order and records malformed/partial/unknown output independently of cost. Any permitted local baseline ranking is labelled degradation and never creates an unrecorded paid replacement.

Accounting records ingestion once, query embedding separately, and reranking separately. Direct and inclusive user/agent/provider views reconcile to unique attempts; allocation is an explicit reporting view. The UI shows operation, native quantities, calculated subtotal/unknown components and outstanding exposure, with one synthetic retrieval timeline and accessible drill-down. No separate UI framework or broad setup redesign is introduced.

**Required test map:** retain the proposed T-42, T-45–T-55, T-61, T-65 and T-66; add **T-77, T-79 and the standalone synthetic T-78 subcases**. Include relevant T-01–T-03/T-07–T-09/T-14/T-18/T-24 regressions and selected T-60/T-62/T-64 usability/identity checks. The implementation brief names exact applicable subcases and reused evidence, rather than declaring every broad parent passed.

Installed Python and CommonJS clients must exercise successor semantic parity through the actual composed Coordinator → worker → final guard → trusted sender → independent receiver path. Correlate attempts, bound request hashes and receiver arrivals. Prove duplicate/status/refresh no-extra-send, admission and final-mutation negatives, queued revocation using Choice B, unknown exposure across restart, usage corrections once, and preserving schema migration. Reuse unaffected evidence only with source/profile correspondence; never repeat historical one-use run IDs.

**Explicitly excluded:** Vega/Proto changes; production PostgreSQL/Redis rollout; Valhalla/Norns/Trimorphus services; real keys or providers; commercial rate/model selection; paid allowance activation; owner-profile update; new dependency acquisition; external caching; realtime or image/audio implementation; live retry/fallback/model substitution; learned routing. A separate brief may authorize exact disposable builds/tests, not this document itself.

## 5. Fictional non-token tariff requirements (M-07 / C-4)

These are author-calculated **test vectors**, not execution results, vendor prices or authorized spending. Each admitted request contains exactly one query and `n` documents, integer `1 ≤ n ≤ 25`. Reject zero, 26+, negatives, booleans, fractions and strings. Return and preserve the required native billed-unit observation; missing/null/invalid/contradictory evidence remains unknown under the selected contract rather than being replaced by locally expected usage.

### 5.1 Tariff A — retain the reviewed minimum and unit-ceiling example

```text
units = ceil(n / 10)
raw_USD = max(0.005 per request, 0.003 × units)
```

| Documents | Search units | Calculated USD |
|---|---:|---:|
| 1 | 1 | 0.005000000 |
| 10 | 1 | 0.005000000 |
| 11 | 2 | 0.006000000 |
| 20 | 2 | 0.006000000 |
| 21 | 3 | 0.009000000 |
| 25 | 3 | 0.009000000 |

The full-domain bound is **USD 0.009000000**. Test all 25 admitted cardinalities plus the boundaries. A retry/new request or a split batch independently incurs its own minimum; grouping for display does not merge provider attempts.

### 5.2 Tariff B — whole-request tier plus currency rounding

```text
per_document_USD = 0.0003000005 when n ≤ 10
                   0.0004000005 when 11 ≤ n ≤ 25
raw_USD = n × per_document_USD
settled_USD = round_half_even(raw_USD, quantum = 0.000000001)
reserved_USD ≥ ceil(raw maximum exposure, quantum = 0.000000001)
```

The tier applies to **all documents in the request**, not just those above ten. There is no minimum or extra fee in Tariff B; it is a distinct immutable schedule, not a silent replacement of A.

| Documents | Raw USD | Half-even settled USD | Upward-rounded request bound |
|---|---:|---:|---:|
| 1 | 0.0003000005 | 0.000300000 | 0.000300001 |
| 3 | 0.0009000015 | 0.000900002 | 0.000900002 |
| 10 | 0.0030000050 | 0.003000005 | 0.003000005 |
| 11 | 0.0044000055 | 0.004400006 | 0.004400006 |
| 25 | 0.0100000125 | 0.010000012 | 0.010000013 |

The full-domain reservation is **USD 0.010000013**. The `n=10/11` pair exercises the tier switch. `n=1` rounds an exact half-nano tie down to an even nano; `n=3` rounds a half-nano tie up. The `n=25` case proves settlement and conservative reservation use different rounding directions. Test complete-domain bounds independently from the implementation's own evaluator. Preserve DEV-11's separate positive-raw-rounded-to-zero guard; do not label such amounts free.

Tariff A expects a search-unit observation and Tariff B expects document-unit observation, under their respective declared semantics. Explicit zero remains explicit reported evidence, but contradicts a successfully billed nonempty request in these fixtures and cannot yield a complete free cost. Any separately permitted contractual derivation must be labelled derived and independently qualified, never mislabelled provider-reported.

Subcases T-48.a–T-48.g cover native units, minimum/unit ceilings, tier boundary, half-even currency precision, upward reservation over all 25 inputs, usage-evidence/domain negatives and separate-request/split-batch treatment. `FICTIONAL-TARIFF-VECTORS.json` supplies the exact expected values. Computing these vectors in this packet is not passing any product subcase.

## 6. WP-SPEND-IMPORT — the next standalone work package

**Position:** immediately after DEV-12 and before further routing/policy or provider-family expansion. Scope is an offline importer for explicitly supplied account exports; no account login, automatic download, key or model call is required.

Start with one declared export format chosen from actual owner-supplied material, plus synthetic fixtures. Preserve source file identity and ownership, provider/account scope, currency, period/timezone, observation/import timestamps, granularity, units/cost basis, credits/adjustments, schema version and corrections. Map only supported dimensions. Keep unknown agent/task/operation/owner fields honest. Allow an unchanged import to return its original receipt.

The decisive acceptance cases are duplicate import; differently named identical content; different files covering the same period; partial overlaps; correction/replacement reports; multiple currencies; mismatched timezones; invalid values; unresolved attribution; linkage to a controlled attempt without duplicate spending; and authorized filtered/exported readback. Ambiguous overlap must be flagged and excluded from additive totals, not silently estimated away. Use T-73/T-62 subcases and their existing accounting relationships rather than inventing a second provider-attempt ledger.

A valid aggregate can show real spend at its actual resolution. It cannot by itself prove invoice reconciliation, task acceptance, delegation or agent efficiency. Missing exports are a data-coverage limit; implementation can be proven synthetically and real-data acceptance recorded later without Vega integration. A format/model choice is made in its brief, not guessed now.

## 7. Research and future-integration work

The 22-item map distinguishes current contract requirements from future experiments. Later work includes effort sweeps/cascades, cache-state calibration, prefix-fork and home-cache comparisons, TTL/keep-alive experiments, masking/summarization comparison, and single-agent versus fan-out cohorts. Every provider action remains separately authorized and metered; keep-alive is work, not observation. No empirical magnitude from the research paper is a Duranki saving claim.

Valhalla/Proto integration later qualifies commission revocation, common labels, policy consultation, budget-authority cutover, activation fencing and field mapping. Obtain Valhalla 0.4 and the Proto proposal/evidence report before declaring citation correspondence. Keep the library of existing call-site evidence distinct from runtime traffic; migrate a selected cohort, establish correct identity/handling/accounting, then enforce egress and revoke keys only after their actual consumers are accounted for. A base-URL edit alone is not integration qualification.

## 8. Handoff and re-review

Correction authored → independent document review → owner adoption of applicable delta → exact successor-contract review → bounded implementation → controlled qualification → separately authorized deployment/commercial qualification. These are distinct events, not automatic promotions.

The next authoring deliverable after this packet is the **exact bounded successor contract**, not another architecture redesign. No further review-of-review note is needed merely to acknowledge the incorporated findings; genuine new contradictions should be stated as specific clauses and resolved in the corrected candidate.
