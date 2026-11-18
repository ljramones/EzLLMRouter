# Duranki architecture v1.2 — change note and review handoff

**Date:** 25 October 2026  
**Status:** architecture review draft; no implementation or deployment commissioned  
**Owner:** Larry Mitchell  
**Candidate:** [DURANKI-ARCHITECTURE-v1.2-REVIEW-DRAFT-2026-10-25.md](DURANKI-ARCHITECTURE-v1.2-REVIEW-DRAFT-2026-10-25.md)

## 1. What this delivers

A complete integrated successor to the supplied v1.1 architecture, not a replacement summary or a separate addendum that leaves contradictory old clauses in force. The original top-level section numbers **0–20**, all original numbered subsections, the five Mesopotamian architectural roles and the original acceptance-test identifiers **1–41** remain. New subsections integrate the operation/service coverage, current trusted execution boundary, provider administration, native accounting and standalone development direction.

The candidate is deliberately labelled **not yet adopted**. Earlier external reviews do not cover it. The source v1.1 file was not overwritten, and no repository, product code, running profile, credential, provider, allowance or Vega application was modified. Local helper scripts were used only to author and check documents.

## 2. Basis and evidence boundaries

The source architecture is **71,744 bytes**, SHA-256 `8f3ab5b86a8533687da6cb0e80e16b8d7586fc7392c02a646b8c08025aee7e9c`. It matches the predecessor identity recorded in the supplied historical documentation. The 25 October coverage report/inventory/matrix and DEV-11 contract/result/receipts supply scoped updates. The owner's discussion supplies UI priorities, cost-attribution goals, standalone-first sequencing and the hold on Vega instrumentation. Official publisher documentation supplies the short commercial-feature patterns in §20.3, not Duranki implementation evidence.

The text differentiates target requirements, static source observations, controlled execution, last recorded owner deployment and actual provider/invoice evidence. In particular, DEV-11's tested product source, its later review commit and the recce snapshot are not collapsed into one claimed current running HEAD. The owner profile's current credentials or campaign state were not independently inspected.

## 3. Section-level change map

| Sections | Change | Review significance |
|---|---|---|
| Header, §0 | Broader model/AI-service title; v1.2 draft status; source/profile distinctions; explicit integration deferral | Adoption of a document must not imply phase completion, wire migration, live spending or integration authority |
| §§1–3 | Broaden purpose to typed operations and honest cost/coverage; preserve cost per accepted task and mandatory admission | Ordinary local processing and externally observed work are not invented model routes |
| §4, §§4.1–4.4 | Replace replicated-LiteLLM-as-authority description with trusted Coordinator/plan/guard/sender and isolated worker; distinguish target stack from local proof | This is a substantive trust-boundary reconciliation, not a cosmetic rename. Credentials and signing authority stay outside the worker |
| §§4.5–4.7 | Provider/account/API setup/deployment/operation model; source permission then principal grant; guided setup, readable states, price provenance, usable actions; selected commercial patterns | Discovery, credential validity, operation support, quality, pricing and health cannot be collapsed into a single connected flag |
| §§5.1–5.5 | Operation-specific admission, successor binding and final-write checks after lower waits; persistent-registry evolution | Existing strict wire `0.2` and `duranki-work-v0.2` remain unchanged until a separately reviewed extension |
| §5.6 | External response cache explicitly deferred; native provider caching, serving KV reuse and response reuse separated | No cache product/dependency is selected; billed read evidence is not a physical-reuse or savings claim |
| §§5.7–5.9 | Versioned operation contract, all fifteen recce families, embedding/index and rerank semantics | Native units and compatibility precede execution; source vendor defaults are not commercial activation choices |
| §§6.9–6.10 | Named policy drafts/publication/rollback/preview and scoped health/cooldowns | Deterministic preview may be built now; live model substitution still needs the inherited quality/promotion gates |
| §§7–9 | Lab registration separated from readiness; lifecycle extensions; person/agent/principal/delegation/charging identity and coverage | Vega instrumentation is a later integration, not a dependency of the next standalone tranche |
| §§10.1–10.8 | Native quantities, price functions, finite exposure bounds, DEV-11 preservation, direct/inclusive roll-ups, allocations and coverage | Unknown is not zero; one charge cannot be multiplied through agent/user/provider or corpus views |
| §§11.5, 12.4–12.5 | Operation-specific quality and agent-efficiency comparisons; observations-to-policy progression | Source counts and scripted demos are not representative performance evidence; observational logs are not counterfactual outcomes |
| §§13–14 | Media/artifact custody, private endpoints, no-store continuity, explicit planning assumptions and additive deployment/migration | Failed artifact retrieval must not silently repeat paid generation; rollback must not discard liabilities |
| §15 | Retain assurance phases, add standalone sequence and proposed DEV-12 scope | Development slices are not architecture phases; first addition is synthetic embeddings/reranking, not a provider rollout |
| §16 | Original IDs retained; five original tests clarified; tests 42–76 added and scoped by first reliance | A requirements list is not a claimed pass or a mandate to run future realtime tests during DEV-12 |
| §§17–18 | Broader operation risks and open decisions; distinguish resolved bounded sender choice from open production qualification | No cloud procurement or broad research gate is imposed on the first synthetic extension |
| §§19–20 | Focused architecture review questions; explicit evidence hierarchy; checked official patterns and historical bibliography | Old market assertions are not silently treated as current facts |

## 4. Material amendments requiring explicit review

**Trust and signing boundary.** The old summary and diagram concentrated gateway behaviour around LiteLLM. The candidate treats Duranki as the logical gateway and LiteLLM as replaceable isolated preparation. The trusted plan authority validates/signs an admitted selection; the optimization role does not obtain secret/signing authority inside the worker. This aligns the architecture with the supplied Choice B development evidence without claiming universal protocol qualification.

**Scope expansion.** Operation type/version becomes part of the proposed permission/binding/accounting extension. It is distinct from the attempt ID. The architecture states requirements; exact wire/profile/projection version and field names remain for the contract delta. No new fields can simply be smuggled through wire `0.2`.

**Supply-chain wording.** v1.1's all-source-rebuilt wording is reconciled with the existing frozen-distribution build practice. New wording requires explicit source/distribution provenance and build correspondence rather than falsely claiming every vendor wheel was rebuilt from source. A pinned hash alone does not prove safety. The provider-side revocation effect of a rotated credential must be confirmed when required; local replacement is not assumed to do it.

**Phase 2 cache criterion.** The inherited requirement that cache-miss rate must not worsen is changed to reporting cache diagnostics while evaluating complete cost, quality and latency. External response caching is optional and currently deferred. This is an intentional proposed gate amendment, not a claim that all phase wording is unchanged.

**Financial and physical release.** Financial settlement and physical capacity release remain separate: conservative accounting at an authorized maximum does not demonstrate provider stop or free capacity. Partial-output restart is a newly authorized generation, never an automatic replay. A local WAL does not create independent concurrent-budget authority during a shared-state outage.

**Planning assumptions.** The earlier no-general-residency position is retained as a dated planning assumption, not a new compliance determination. An unsupported comparative cloud advantage and dated vendor business/incident assertions are removed from operative requirements, with the original bibliography preserved as historical context.

## 5. Preserved requirements

The text keeps mandatory admission, combined handling restrictions, current-authority final sending, signed work/candidate binding, durable intent, append-only correction history, unknown exposure, no silent retries or parameter dropping, caller-owned substantive acceptance, and the no-store delivery consequence.

The original §§6.1–6.8 routing taxonomy/cascade rules, §§7.1–7.6 lab policy, §8.5 single-winner acceptance, §§11.1–11.4 quality protocol and §§13.1–13.2 retention rules are retained as exact text blocks. Their presence is checked in the validation record; preservation does not mean those target capabilities are implemented.

DEV-11's exact four-rate/single-tier text contract remains narrow: explicit absent/null/known-zero/invalid evidence, bounded input/output domain, disjoint reads/writes, reasoning as an output subset, unknown exposure and over-bound handling. It is not silently broadened to new cache modes, modalities or provider billing assumptions.

## 6. Acceptance-test traceability

The original **41** test identifiers remain, and **35** new identifiers (**42–76**) are added. No original test is removed or assigned a different subject. Original IDs with wording changes are **18, 24, 37, 38 and 39**:

| ID | Clarification |
|---|---|
| 18 | Missing required usage remains unknown; a separately labelled estimate is not settlement; corrections apply once |
| 24 | Explicit below-guard queue/commit-to-first-write revocation discriminator |
| 37 | Reviewed source/frozen-distribution provenance and actual build correspondence |
| 38 | Worker must also be unable to bypass the sender to an otherwise allowed provider |
| 39 | Trusted secret-runtime scope, no leakage, scheduled rotation/local binding revocation and required upstream confirmation |

Tests 42–55 cover operation foundation/retrieval; 56–66 cover operator/attribution/policy/migration; 67–76 cover later lifecycle and cross-cutting properties. The proposed DEV-12 map is a scoped subset, not all future tests. Existing evidence may be reused only with explicit correspondence; no application test was run while authoring this document.

## 7. Recommended next review and submission

Review the candidate as a successor architecture document. Focus on its evidence/status boundaries, typed operation contract, source/user authorization intersection, finite native-unit exposure, retrieval compatibility, financial-versus-capacity release and no-double-count attribution. Resolve only the contract/version choices actually needed for the first addition; preserve later cloud, realtime and integration decisions as open.

Following owner adoption of the relevant delta, prepare a separate bounded implementation brief for **proposed DEV-12 — Operation-aware accounting foundation and retrieval-operation proof**. Its scope is in §15.2. This handoff neither commissions it nor supplies a real provider, API key, commercial rate or spending amount.

For repository submission, add a successor architecture file and this change note without overwriting the historical v1.1 file. Update the architecture index/review tracker only in the separately authorized documentation change. The supplied `.diff` is a **comparison aid**, not an instruction to patch a running checkout or merge product branches.

## 8. Document checks and limits

The accompanying validation record checks predecessor byte/hash identity, top-level numbering 0–20, all predecessor numbered subsections retained, original tests 1–41 retained, new tests 42–76 unique, fenced blocks/Markdown parsing, numbered cross-references, navigation targets, fifteen-family coverage and exact preservation of the core passages named above. The review bundle also contains the original v1.1 input and the full comparison diff.

These are document checks. They are not an independent architectural acceptance, an application regression, a gateway run, a security scan, a repository/remote check, a provider request or a billing verification. The Mermaid source is included for Markdown renderers; no rendered diagram or browser layout check is claimed for this document.
