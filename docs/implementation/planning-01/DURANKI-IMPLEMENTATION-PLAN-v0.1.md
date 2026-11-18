# Duranki Implementation Plan v0.1

**Status:** Draft for review; no implementation commission is issued. **Date:** 16 October 2026. **Repository:** `/Users/larrymitchell/Mach33/Duranki` (directory without Git metadata; branch, HEAD, and tracked status unavailable). **Evidence:** `mach-recce/` is `COMPLETE_WITH_EXPLICIT_GAPS`; it is static consumer-source reconnaissance, not runtime certification. This checkout contains documents only; no Duranki service, SDK, harness, deployment, or tests have been inspected or built.

## 1. Authority and reading key

**Baseline requirement (B)** means `llm-routing-infra-design-v1.1.md` (SHA-256 `8f3ab5b86a8533687da6cb0e80e16b8d7586fc7392c02a646b8c08025aee7e9c`, outside this checkout at `/Users/larrymitchell/Mach33/LLM_Routing/`). `review-tracker.md` records decisions and regression history; superseded entries do not override v1.1. **Agreed direction (A)** means the eight implementation decisions in `DURANKI-IMPLEMENTATION-PLAN-AUTHORING-COMMISSION-01.md` §2. **Proposal (P)** means this plan or `inputs/DURANKI-RECCE-TO-IMPLEMENTATION-READOUT-01.md`; it requires review before implementation. The five unchanged `mach-recce/` artifacts support source-shape claims and synthetic cases; they do not establish live traffic or compliance. The optional `Duranki-Competitive-Landscape.docx` is context only. Exact source paths and hashes appear in the planning return.

**B:** one logical gateway, mandatory admission, signed work-bound plans, final-dispatch check (FDC), durable dispatch intent, append-only accounting, and orchestrator-owned substantive acceptance (§§3–5, 8–10). **A:** Python core and LiteLLM integration; separate importable JavaScript and Python network clients in this fresh Duranki repository; JavaScript is the production-intended Vega client; domain policy and accounting stay separate from gateway integration; no Vega connection yet. LiteLLM is extended, not forked. **P:** start standalone conformance with non-streaming, fixed-approved-destination structured requests. This is a useful first slice, not approval to omit any Phase 1a gate.

## 2. Contract and responsibility map

Draft a versioned network contract for ordered system/conversation/content blocks, tool schemas, explicit tool choice, tool-call/result IDs, source lineage and combined restrictions, resolved prompt/model inputs or controlled versioned references, request settings, cancellation, and capability negotiation. Responses need content blocks, structural status, actual served configuration, usage with raw and normalized categories and explicit unknown/estimated status, `attempt_id`, provider ID where present, error/retryability, and candidate-delivery status. Separate execution-status queries and outcome events distinguish transport completion from substantive step correctness and task acceptance. Source: baseline §§5.1–5.4, 8.1–8.5, 9–11; recce report §§3–5; readout §§3–4.

The trusted caller/orchestrator resolves prompts and models, labels every block and derived call, creates `step_id` + revision and `execution_generation`, owns tools and other effects, verifies substance, authorizes semantic recovery, and performs single-winner acceptance in its state store. The SDK transports and validates inputs for developer feedback; it cannot mint trusted identity, taint, authority, or acceptance. The server derives or validates authenticated principal and charging owner, performs admission, signs plans, prepares candidates with versioned adapters, and applies FDC after all callbacks. The gateway creates `attempt_id`, records intent before transmission, and keeps provider ID for reconciliation. The Phase 1a surface exposes identity levels without claiming Phase 1b deduplication, crash recovery, or compare-and-swap are already proven. Source: baseline §§5.1, 5.3–5.4, 8.2, 8.5; readout §§3.5, 5A.

Canonical-work binding covers principal, purpose, task/step/revision/generation and the assembled pre-adapter request. Candidate preparation binds each authorized deployment and adapter version; unversioned references are materialized or rejected. FDC checks the final prepared request, current classification and permission, signature, versions, financial authorization, and durable intent on every enabled path. Observed adapter changes, including cache-hint removal or forced-tool-choice weakening, are not approved behavior: preserve the semantic contract with a proven adapter or reject the combination. Phase 1a requests name an approved fixed destination, have no model substitution, and enforce spend limits and alerts without a hard concurrent ceiling (§§5.1, 5.3–5.5, 10.4). Supporting calls inherit policy and must be accounted for separately.

**P capability disposition:** include ordered text, structured tool/result exchange, explicit supported tool-choice subset, caller-side JSON salvage, materialized synthetic document text, service-principal/background and nested calls, and unknown usage. Propose explicit pre-dispatch rejection for streaming, realtime voice, audio/image generation, binary multimodal transport, direct Responses/web-search semantics, and uncontrolled provider-managed state until separately approved. A non-streaming synthetic analogue of a streamed source workflow is a new variant; it does not prove the source's streaming consumer. Capability exclusions are open decisions, not permanent baseline exclusions. The full Phase 1a test set still applies to enabled paths; first-relying-phase rules apply if a deferred capability is enabled earlier (baseline §16).

## 3. Evidence levels and phase roadmap

Evidence is labelled **specified**, **locally observed**, **standalone conformance**, **operational acceptance**, or **representative workload**. A synthetic cost ledger proves arithmetic and attribution under test inputs, not real cost per accepted task, task quality, traffic share, production latency, or savings. A local gateway experiment proves only the selected release and exercised paths; it is not the complete Phase 1a exit. Representative Phase 0 cohorts require later authorized observation of real tasks and acceptance; no Vega access is required to author this plan or develop the standalone harness. Sources: baseline §§1, 11, 15–16; readout §§2, 6.

| Baseline phase | Planned work and gate (baseline §15 unless stated) |
|---|---|
| **0 — Instrument and baseline** | Define minimal acceptance protocol, cohort/taxonomy and measurement schema; later collect representative complete cohorts. Exit: cost per accepted task by class and savings ceiling; if trajectory-spine spend exceeds about 50%, re-scope Phase 3–5 before Phase 3. Synthetic readiness is not this exit. |
| **1a — Door and ledger** | A–D below: fixed-destination admission, replicated gateway, signed plans/FDC, classification, approved-configuration file, origin keys, ledger/WAL, supply chain and telemetry. Exit: 100% of eligible onboarding cohort authenticated and principal-attributed, non-compliant share reported, basic reconciliation, and tests 1–9 plus 37–41. Standalone tests are preparatory; operational evidence is separate. |
| **1b — Budgets, recovery, faults** | Full admission, atomic exposure reservation, recovered-state safety, generation deduplication, crash recovery and single-winner acceptance. Exit: hard-ceiling workloads onboarded and tests 10–24 (subject to first-relying-phase rule). |
| **2 — Quick wins** | Context discipline, leaf isolation, response cache after admission, loop guards; full instrumentation contract. Exit: reduced cost per accepted task, non-inferiority, cache-miss rate not worse, test 25. |
| **3 — Evaluation and bake-off** | Split eval sets, registry service, evaluation-only overnight replay; unchanged internal five-way predictor comparison. Exit: development comparison and confirmation-set selection; tests 26–27. |
| **4 — Rules, cascades and lab live** | Rules, two-tier cascades, leaf manifests, lab presence/admission/leases/drain. Exit: quality floor and non-inferiority, drain/cross-family migration, measured lab savings; tests 28–34. |
| **5 — Learned routing** | Gradual selected-predictor rollout. Exit: better cost per accepted task than rules/simpler predictors after overhead and recovery, rollback proven; test 35. |
| **6 — Closed loop** | Approved exploration, propensities, delayed outcomes, drift and gated promotion. Exit: quality stable or improving across changes. Test 36 is ongoing scheduled fallback exercise. |

Test IDs 1–41 retain their canonical meanings and phases in baseline §16. The register maps each once and adds non-numbered obligations. If an earlier approved feature relies on a later guarantee, its test moves to that first relying phase; a rejection test for a disabled feature does not prove enabled behavior.

## 4. Near-term work packages and ordering

The register carries stable IDs `WP-*`, `OB-*`, and `T-01`–`T-41`. Each location below is a **proposed future write surface**, not permission to create code now. Owner roles are responsibilities, not named assignees. A and B can proceed in parallel after separate commissions and their blocking decisions. C depends on the relevant A contract and B's proven gateway boundary. D extends C to the entire Phase 1a profile. Foundation and Phase 0 measurement preparation can proceed independently of Vega integration. No effort or dates are assumed.

### WP-FND — Repository and toolchain foundation (Phase 1a preparation)

- **Objective/owner:** define package boundaries and reproducible toolchain; repository maintainer with SDK and security reviewers.
- **Inputs/dependencies:** baseline §§3–4.4, 14; agreed Python/SDK direction; decisions `DEC-01`, `DEC-02`. No application dependency is selected by this plan.
- **Proposed locations/boundary:** future `server/`, `clients/js/`, `clients/python/`, `tests/`, `docs/contracts/`, and build metadata only after commission. Separate distributable clients from server/training packages. No Vega edits.
- **Completion/evidence/handoff:** reviewed package/import boundaries, exact version/hash/license inventory and release verification, isolated clean CommonJS and Python consumer setup, reproducible build evidence. Hand off selected pins and provenance to B and C; no product version or license is verified here.

### WP-P0 — Measurement and representative baseline (Phase 0)

- **Objective/owner:** measurement schema, acceptance protocol and later representative cohorts; measurement lead with orchestrator owner.
- **Inputs/dependencies:** baseline §§1, 10–11, 15; owner decisions `DEC-03`, `DEC-12`; independent of B/C.
- **Proposed locations/boundary:** future `docs/measurement/` and later approved measurement tooling. Current work may specify synthetic examples; real collection requires its own authorization and source access.
- **Completion/evidence/handoff:** cohort definitions include failed/abandoned tasks, token and spend taxonomy, acceptance, quality floors and cost per accepted task; representative Phase 0 exit is separately evidenced. Hand off baseline and savings-ceiling consequence before Phase 3 scoping.

### WP-A — Source-informed contract and capability profile (Phase 1a preparation)

- **Objective/owner:** versioned schemas and executable-independent vectors; API owner with policy, gateway, SDK and orchestrator reviewers.
- **Inputs/dependencies:** baseline §§5, 8–10, 13; recce report/mapping; readout §§3–5; `DEC-04`–`DEC-08`.
- **Proposed locations/boundary:** future `docs/contracts/` and inert vectors. Specify request/block/source/trust context, canonical work and candidate preparation, status, errors, usage, cancellation/outcomes, capability exclusions and client package compatibility. No Mach-Platform prompt database or application repair logic.
- **Completion/evidence/handoff:** each field has authority, validation and versioning; cross-client examples yield equivalent server-interpreted requests; invalid inputs and explicit unsupported outcomes are specified; reviewer signs off unresolved choices or keeps them blocked. Hand contract to C and B.

### WP-B — Pinned gateway integration proof (Phase 1a preparation)

- **Objective/owner:** prove actual enabled LiteLLM transmission paths on a chosen pinned release; gateway integration owner with security/accounting reviewers.
- **Inputs/dependencies:** baseline §§4.3–4.4, 5.3–5.4, 10; relevant A binding draft, FND pins, `DEC-01`, `DEC-09`; independently commissioned experiment.
- **Proposed locations/boundary:** future isolated `tests/gateway-proof/` and evidence under `docs/evidence/`; controlled local receiver and synthetic content only. No live Jev, production provider, Vega, cloud or traffic action is authorized by this plan.
- **Completion/evidence/handoff:** enumerate enabled endpoints, retries and all downstream transformations; demonstrate post-callback FDC, named deployment, intent-before-transmit, failure propagation and independent receiver observation; disable built-in routing/fallback identity; verify hooks, budget behavior, TypeSafe passthrough attribution, feature/license gating and supply-chain provenance against the pinned release. A forbidden dispatch must leave the independent receiver empty. Record unproven paths and contingency trigger; hand a go/no-go boundary to C/D. A top-level hook invocation alone is insufficient.

### WP-C — Production-intended clients and synthetic orchestrator (Phase 1a path)

- **Objective/owner:** actual Python service exercised by installed JavaScript and Python network distributions; SDK/service owners with a simulated orchestrator owner.
- **Inputs/dependencies:** approved A surface, B boundary, FND foundation; `DEC-04`–`DEC-08`. Provisional SDK exercises before B are labelled provisional, never accepted conformance.
- **Proposed locations/boundary:** future `server/`, `clients/js/`, `clients/python/`, `tests/standalone/`; synthetic identity/origin issuers, tools, documents, provider receivers. SDK imports need no server, LiteLLM, training packages or Mach-Platform source on the host.
- **Completion/evidence/handoff:** clean CommonJS Node consumer per recce snapshot `>=24 <25` (exact support pin still open), clean Python consumer, matching semantic vectors, ordered tool IDs, unknown usage, nested attribution, request-to-outcome workflow and raw-protocol negative cases. Server enforcement and FDC are observed independently at receiver; orchestrator owns verification/effects. Hand gaps to D.

### WP-D — Phase 1a hardening and acceptance (Phase 1a gate)

- **Objective/owner:** complete operational Phase 1a; gateway, policy, accounting, deployment, security and operations owners.
- **Inputs/dependencies:** A–C, FND, approved onboarding cohort and `DEC-09`–`DEC-11`; Phase 0 representative exit remains separate.
- **Proposed locations/boundary:** future policy/ledger/deployment/operations modules and evidence, no Vega connection by default. Supply-chain controls apply to LiteLLM, Redis, Langfuse and collector from Phase 1a.
- **Completion/evidence/handoff:** replicated gateway and network policy; authenticated identity/charging owner; bounded migration mode; deterministic classification with corpus/bars; signed fixed-destination plans and current-version FDC; approved-configuration file; durable intent plus ledger/replica-local WAL fail-closed path; spend limits/alerts; origin-key controls; retention at every persistence boundary and allowlisted telemetry; pinned/hash-verified builds, egress, secrets, SBOM, advisory/soak/rollback process; basic reconciliation. Demonstrate tests 1–9, 37–41 and complete §15 exit in the relevant environment. Distinguish local simulation, staging, operations and real cohort evidence. Hand Phase 1b exposure/recovery gaps explicitly to the next gate.

## 5. Test and proof design

Use separate evidence classes: component policy/adapter/ledger tests; cross-language canonical-request vectors; installed-package consumer tests; actual pinned gateway and independent provider receiver; fault/concurrency tests; later explicitly authorized provider/staging and representative-workload evidence. Drive complete request → admission → signed plan → FDC → persisted intent → receiver → usage/candidate → orchestrator outcome workflows. Send raw protocol negatives around SDK validation; absence of a provider request is observed at the independent receiver. For test 9, inject mutation **after binding** through a controlled server test adapter/callback; an early client-signature failure does not prove FDC. Test controls confer no production authority. Record enabled-path coverage, hidden retries, pre-transmission revocation, unknown outcome and WAL failure separately. Sources: baseline §§4.3, 5.4, 8, 10, 16; readout §5.

The fixture overlay covers all 19 synthetic source scenarios and splits assertion phase from scenario phase. It corrects `raw_reused_generation` to return/refer to the existing execution for identical bound work with **no additional** provider attempt; changed work must not inherit authority; a new authorized generation is distinct. It separates Phase 1a spend-limit behavior from Phase 1b atomic maximum exposure, and streaming rejection from later partial-stream safety. Server-side canonical binding remains authoritative; client hashes are developer aids. The original catalogue remains unchanged. Test coverage is mapped in the register independently of fixture count.

**Planning-data schema:** the register has `work_packages`, `obligations`, and `baseline_tests` arrays, keyed by unique `WP-*`, `OB-*`, and `T-01`–`T-41` IDs. Dependencies and test references point to these IDs; `earliest_baseline_phase` retains v1.1's test placement. The overlay's `fixture_records` array is keyed by `original_fixture_id`; each `assertion_groups` entry records profile, earliest phase, enforcing component, harness prerequisites and observable result. `proposed_variants` link back to their original fixture. These JSON files are planning data, not executable tests or adopted schemas.

## 6. Decisions and deferred integration

| ID / needed before | Owner role | Open decision and recommendation (proposal only) | Blocks |
|---|---|---|---|
| `DEC-01` / FND, B | repository/toolchain and gateway owners | Exact Python, Node, LiteLLM and dependency pins, package/export formats, license and release verification. Choose only after compatibility/provenance review; ensure CommonJS consumption. | FND, B, C |
| `DEC-02` / FND | repository maintainer | Packaging/build/release layout and independent client installation proof; select through review. | FND, C |
| `DEC-03` / P0 exit | measurement and quality owners | Cohorts, acceptance protocol, class margins/floors and grouping; use representative complete tasks. | Phase 0 exit, Phase 2+ |
| `DEC-04` / A approval | API and policy owners | Canonical block/lineage schema, trust context, reference binding and semantic hash rules. Recommend shared server vectors. | A, C |
| `DEC-05` / A approval | API and orchestrator owners | Exact status, cancellation, candidate/outcome and idempotency responses; preserve distinct identities. | A, C, 1b |
| `DEC-06` / A approval | capability owner | Initial enabled families, structured tool-choice subset, streaming and binary/stateful exclusions. Recommend readout's non-streaming slice subject to approval; reject unsupported pre-dispatch. | A, C, test applicability |
| `DEC-07` / A approval | accounting owner | Usage-unknown/estimated envelope, price and usage semantics, billable categories. Never map missing to zero. | A, C, D |
| `DEC-08` / A approval | adapter and SDK owners | Allowed candidate transformations and JS export/runtime support. Demonstrate semantic preservation or reject. | A, B, C |
| `DEC-09` / before Phase 1a start | gateway/security owners | Pinned-release contingency if hooks, license, compromise or vendor change prevent enforcement: thin admission layer or alternative gateway, preserving §5. | B, D gate |
| `DEC-10` / D | platform/accounting owners | Managed append-only ledger product, WAL bounds, cloud/region and operational topology; preserve baseline responsibilities, choose no product here. | D |
| `DEC-11` / D | policy/security/operations owners | Named role holders, classification bars, approved cohort/configurations, keys, supply-chain soak period and exception process, numeric defaults. | D gate |
| `DEC-12` / later phases | architecture/quality owners | Export-control applicability, serving stack, lab hardware/models, predictor selection and Phase 3–5 scope after Phase 0 ceiling. No lab choice blocks fixed-destination standalone work. | Later gates |

Deferred Vega cohort-specific integration traces: effective route/worker registration, authenticated principal and charging-owner provenance, source-label creation and prompt/model resolution, queue redelivery/cancellation, acceptance/side-effect recovery, provider SDK configuration, retention boundaries, and measured traffic/cost. Refresh the source snapshot before such work. Source: recce report §§6–8; readout §7. No current package connects Vega. Provider behavior, license rights, actual traffic, cost savings and task quality remain unverified.

## 7. Proposed next executable commission — **NOT ISSUED**

**Objective:** WP-FND only: establish the agreed Python service boundary and two separately installable network-client package boundaries, with a reproducible toolchain and clean import/consumer proof. **Prerequisites:** approve `DEC-01` and `DEC-02`, identify an implementation reviewer, and issue a separate bounded commission. **Proposed write surface:** new package/build metadata and minimal boundary files under `server/`, `clients/js/`, `clients/python/`, plus a small isolated consumer proof under `tests/`; exact paths reviewed before execution. **Permitted scope if separately issued:** local source and package/build work using selected pinned dependencies and only the network access explicitly approved in that later commission. **Expected proof:** independent JS CommonJS and Python installation/import, no Python/server packages required by the JS consumer, no server packages required by Python client, recorded hashes and licenses, no routing or provider calls. **Stop conditions:** unresolved pins/licensing, dependency provenance failure, package coupling, or a write outside the new commission. This proposal does not authorize scaffolding, installs, tests or gateway experiments now.
