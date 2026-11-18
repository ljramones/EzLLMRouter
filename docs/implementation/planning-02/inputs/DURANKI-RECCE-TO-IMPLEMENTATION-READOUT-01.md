# Duranki — Reconnaissance-to-Implementation Readout 01

**Date:** 16 October 2026  
**Status:** Planning assessment and proposed implementation decisions. Not a code commission, runtime certification, Phase 0/1a acceptance, or Vega integration authorization.  
**Controlling architecture:** `llm-routing-infra-design-v1.1.md`  
**Evidence packet:** the five Codex reconnaissance artifacts supplied in this conversation.

## 1. Planning disposition

Use the reconnaissance as source-informed planning input, preserving its `COMPLETE_WITH_EXPLICIT_GAPS` disposition. It provides enough information to draft the standalone request/response contract, define the first client compatibility profile, and design realistic synthetic integration scenarios. Do not treat the fixture catalogue as an adopted executable acceptance specification without the bounded corrections in section 5.

No further broad Mach-Platform scan is needed before that planning work. Registration, authentication provenance, cancellation propagation, and individual response-consumer gaps remain tracked dependencies of later cohort-specific integration. The separate pinned-release LiteLLM proof remains necessary.

The finalized architecture is not reopened. Preserve the subsequently agreed Python core, Python LiteLLM integration, separately distributable JavaScript and Python network clients in the new Duranki repository, client-driven standalone testing, and deferred Vega connection.

## 2. Evidence and consistency checks

### Recorded source snapshot

Codex reports inspecting `/Users/larrymitchell/Mach33/mach33-platform`, branch `vega/feat/numerics-tier2`, HEAD `e69a1fce53917603d110bdd386bde1547a82196d`. Its return records unchanged beginning/end HEAD and status, pre-existing untracked `artifacts/`, and no inspected-source hash drift. These are executor-reported observations, not independently repeated checkout checks. This snapshot is evidence about the future consumer; it is not the location or branch for the new Duranki repository.

The referenced baseline SHA-256 is `8f3ab5b86a8533687da6cb0e80e16b8d7586fc7392c02a646b8c08025aee7e9c`. It matches the uploaded v1.1 bytes checked during this assessment.

### Checks performed on the uploaded artifacts

- All three JSON artifacts parsed successfully as data.
- The inventory has 26 uniquely identified family records.
- Counting entries explicitly identified as `messages.create` or `messages.stream` reproduces 98 expressions in 79 distinct files, without duplicate path/line/expression entries.
- The inventory and return report identical aggregate counts.
- All listed call-site snapshot hashes agree with their corresponding entries in the inventory's hash table. The actual Mach-Platform source files were not supplied, so their hashes were not independently recalculated.
- The catalogue contains 19 uniquely identified scenario specifications, matching its declaration and the return. Seventeen are currently labelled `1a`; two are labelled `later`; eight are raw-protocol negative scenarios.

These checks establish internal artifact consistency, not completeness of the source search, operational reachability, provider behavior, performance, spend, or task quality. The direct-HTTP and voice entries include representative source landmarks; they must not be added to the SDK-expression count as though all were independently established dispatch expressions.

### Source authority

1. Architecture v1.1 controls requirements, responsibility boundaries, and phase gates.
2. Larry's subsequent language, repository, packaging, and deferred-integration decisions control the implementation direction.
3. The reconnaissance describes observed source shapes and explicitly unresolved edges.
4. The mapping and fixture catalogue propose implementation interpretations. Where those conflict with v1.1, record the correction; do not silently reinterpret the original artifact.

## 3. Findings that materially shape implementation

### 3.1 There is no universal existing dispatch wrapper

The report identifies separate Vega non-streaming, SSE, surface-policy, autonomous, Proto, packaged-assistant, decomposition, composition, coding, background, direct-HTTP, and realtime families. The inventory does not establish live traffic share or complete registration for every family.

**Planning consequence:** build an explicit network client, not a presumed drop-in replacement for one platform function. Later integration must be cohort-based and account for direct/bypass paths. The first standalone release does not need to support all 26 families.

**Sources:** reconnaissance sections 1–3; inventory `inventory_totals` and family records.

### 3.2 The unit of work is a structured request, not a prompt string

Observed callers depend on ordered messages, system blocks, tool schemas, forced tool choice, assistant `tool_use` blocks, and matching `tool_result` identifiers. They also consume content blocks, stop reasons, served model and usage. Application code performs JSON salvage, output validation, and tool execution.

**Planning consequence:** define a provider-independent request/response contract that preserves those semantics, with explicit capability profiles and versioned preparation. Do not flatten everything into text, blindly expose every provider parameter, or copy application repair/tool execution into the network SDK.

**Sources:** reconnaissance sections 1, 3, 4 and 5; mapping rows for ordered messages, tool identity, decomposer and response accounting; baseline sections 5.3, 8 and 10.

### 3.3 Prompt and model state must be captured at invocation time

The report describes editable/versioned prompt blocks, per-turn model configuration, runtime prompt augmentation, differing history windows, and a note appended to an outgoing user message. Reading a template version alone is not equivalent to capturing the assembled request.

**Planning consequence:** the trusted caller submits resolved assembled content or controlled versioned references. Duranki binds that work and its prepared candidate request. The synthetic harness supplies changing prompt/model configurations; Duranki does not import Mach-Platform's prompt database or reproduce its prompt-authoring system.

**Sources:** reconnaissance sections 1.4 and 4; mapping prompt/model rows; baseline section 5.3.

### 3.4 Existing adaptation can change semantics

The report says the compatibility adapter strips cache hints, normalizes tool schemas, and changes forced tool selection to `auto` for some destinations.

**Planning consequence:** observed adaptation is not automatically an approved behavior to reproduce. Preserve required semantics through a tested capability/adapter configuration or reject that unsupported combination. Phase 1a must not weaken tool-choice requirements or silently substitute models for compatibility. Candidate preparation and final-dispatch validation need tests using these exact classes of transformation.

**Sources:** reconnaissance sections 1.3 and 4; mapping adapter row; baseline sections 5.1, 5.3–5.4 and 5.5.

### 3.5 Identity and provenance are caller/server responsibilities

The report finds an optional principal string used for telemetry, application session/by fields, and no universal source-lineage representation established in the inspected builders. It does not prove the platform has no authentication or lineage anywhere.

**Planning consequence:** the harness needs an isolated trusted identity issuer and a simulated orchestrator that supplies labelled blocks and ownership. The SDK carries this information; it does not invent source classifications, authenticate arbitrary identity strings, authorize models, or accept steps. The real identity and lineage mapping remains deferred Vega work.

**Sources:** reconnaissance section 4; mapping trust boundary; baseline sections 5.1 and 9.

### 3.6 Existing accounting is not the future accounting authority

The report describes instrumentation limited to calls in an active usage context, a mixed-model aggregate attributed to the first model, last-response usage in a chat path, and missing usage represented as zeros in a direct wrapper.

**Planning consequence:** preserve per-attempt records, actual served configuration, raw usage and explicit uncertainty. Report execution, step correctness and task acceptance separately. A test with two model rounds must count both; mixed explicit configurations in distinct child calls must remain distinguishable. This is not permission for automatic model substitution within a Phase 1a request.

**Sources:** reconnaissance sections 1.5 and 4; mapping accounting rows; baseline sections 10–11.

### 3.7 JavaScript consumer compatibility is now source-informed

The report identifies a CommonJS root, a declared Node `>=24 <25` range, workspaces, and different SDK dependency declarations in separate packages. This is a snapshot finding, not a recommendation to reuse the provider SDK or its defaults.

**Planning consequence:** require a clean CommonJS consumer test using the built JavaScript package. Also test ordinary ES-module consumption if included in the chosen export contract. The SDK must not need Python or Mach-Platform on its host. Select exact supported runtimes during foundation planning; do not inherit old Numerics pins or impose an unplanned Vega upgrade.

**Sources:** reconnaissance sections 4 and 5; mapping JavaScript compatibility row.

## 4. Proposed first standalone capability profile

This profile is a planning recommendation for the initial end-to-end milestone, not a claim that all Phase 1a obligations are thereby covered.

### Initially implement and exercise

- Non-streaming, fixed-approved-destination requests.
- Ordered text/system/conversation blocks with source handling metadata.
- Tool definitions and a supported explicit tool-choice subset.
- Tool-call/result identifier round trips, with tool execution in the simulated orchestrator.
- Structured-result delivery, explicit malformed-result handling, and caller-owned interpretation.
- Materialized synthetic document text and controlled versioned reference behavior, without assuming image/PDF transport support.
- Service-principal/background calls and nested synthetic calls with separate attribution.
- Rich response and usage envelopes, including missing usage and explicit errors.
- Outcome reporting separate from candidate delivery.
- Direct raw requests that test independent server enforcement.

### Keep as named, initially unsupported capabilities

User-facing event streaming, internal streaming, realtime voice, audio/image generation, binary multimodal input, direct Responses/web-search semantics, and uncontrolled provider-managed mutable state require separate capability decisions and proofs. Unsupported requests must fail explicitly before provider dispatch; they must not be downgraded silently.

A non-streaming synthetic variant inspired by a streamed platform workflow is a new test variant. It does not prove compatibility with the existing stream consumer. Retain the original source-linked scenario and its limitation.

## 5. Bounded fixture corrections before executable adoption

Preserve the supplied catalogue as evidence. Create a versioned implementation catalogue or disposition overlay rather than changing its historical meaning.

### A. Assign phases to assertions, not just entire scenarios

`timeout_unknown_usage` combines Phase 1a usage representation with full-profile exposure, execution-generation deduplication and late-winner behavior. `outline_and_draft` similarly mixes an early candidate/acceptance distinction with a durable single-winner requirement. The mapping also attaches generation deduplication to an early identity row.

Retain request/response shapes and unknown-versus-zero checks in the early profile. Full-profile budget, crash, deduplication and single-winner proofs belong at Phase 1b under baseline sections 15–16, or earlier only when an explicitly approved earlier capability actually relies on them. Do not silently enlarge Phase 1a.

Record for each assertion: baseline clause/test, enforcing owner, active profile, required harness state, and observable pass/fail condition. A scenario can have multiple assertion groups.

### B. Correct `raw_reused_generation`

The supplied scenario describes submitting the same generation twice but expects blanket server rejection and no provider dispatch. Baseline section 8.2 and test 14 require deduplication.

For the same authorized generation and identical bound work, the second submission should refer to the existing execution/result according to the adopted API, without another provider attempt. The first valid submission may already have dispatched. Do not assert zero total dispatches across the pair.

Add a separate proposed conflict case: reuse of that generation with materially different bound work. It must not inherit the original work's authority. Also retain a distinct authorized-new-generation case so legitimate escalation is not deduplicated into a rejected result. Detailed response codes remain contract decisions.

### C. Correct the injection location for `raw_mutated_candidate`

A raw client request does not by itself mutate a server-generated candidate after plan signing. An early signature or input-validation rejection would not prove the final-dispatch check.

Use a controlled server-side test adapter/callback to change a prepared request after its authorization binding. Observe the actual FDC and independent provider receiver. Keep raw-client forgery/mutation tests separately. Test-only injection controls must not be exposed as a production bypass.

### D. Split streaming and financial-profile expectations

`partial_stream_cancel` is labelled Phase 1a despite unresolved streaming eligibility. For a non-streaming initial profile, test explicit streaming rejection. Keep the partial-stream/cancellation lifecycle test for the first approved streaming capability; baseline test 17 is in Phase 1b and the first-relying-phase rule remains controlling.

`raw_no_financial_authorization` must distinguish Phase 1a spend-limit/admission behavior from Phase 1b maximum-exposure reservation. Its current generic label cannot establish a hard concurrent ceiling in Phase 1a.

### E. Clarify canonicalization ownership

The `chat_text` phrase “JS and Python serialize same canonical hash” should become an explicit cross-client semantic-equivalence test: equivalent requests result in the same server canonical-request representation/hash under shared vectors, excluding the non-semantic differences the baseline permits. Authoritative work binding and plan signing remain server-side. Optional SDK hash helpers do not become trusted admission evidence.

### F. Do not equate 19 scenarios with acceptance coverage

The catalogue explicitly contains specifications, not executable tests. It is a seed corpus, not the complete baseline suite. Trace Phase 1a tests 1–9 and 37–41 separately, including ledger/WAL failure, sensitive telemetry, origin claims, signatures and policy changes, and supply-chain enforcement. A scenario may exercise several obligations; an obligation may require several tests.

## 6. Delivery packages informed by the reconnaissance

### Package A — Source-informed contract and capability profile

Draft the request/block/source schemas, model and prompt binding rules, candidate response and usage envelopes, identity roles, outcome event interface, capability exclusions, and JavaScript/Python packaging contract. Produce executable-independent examples and invalid-input cases. Preserve baseline terminology and identifier ownership.

**Completion evidence:** every included behavior traces to v1.1 or a clearly labelled implementation choice; every observed but deferred protocol has an explicit disposition; both client APIs have equivalent semantics.

### Package B — Pinned gateway integration proof

Independently test the selected LiteLLM release's enabled paths against admission, prepared-request binding, dispatch-intent durability and final-dispatch enforcement. Inventory actual transmission and retry mechanisms; do not infer them from the application SDK inventory. Keep provider receivers independent of the gateway's own assertions.

**Completion evidence:** bounded positive and negative dispatch evidence for the selected paths, dependency/configuration inventory, known limitations, and the required contingency decision. A successful local experiment alone is not all Phase 1a acceptance.

### Package C — Production-intended clients and synthetic orchestrator

Develop both SDKs in the fresh repository. Drive the actual running Python service using an installed JavaScript distribution from a clean CommonJS consumer and an installed Python distribution. Use synthetic identity, prompts, documents and tool state. The simulated orchestrator owns verification, effects and, as required by later profiles, durable execution-generation and acceptance state.

**Completion evidence:** standalone round trips, structured/tool fidelity, source-policy inheritance, correctly attributed attempts and outcomes, and deliberate raw requests bypassing SDK validation.

### Package D — Phase 1a hardening and acceptance

Extend the first end-to-end path to the complete Phase 1a deployment, ledger, origin, telemetry, supply-chain and acceptance obligations. Keep simulation evidence, staging evidence, operational qualification and actual Vega integration as distinct statuses.

**Completion evidence:** a requirement-to-test/evidence matrix, named limits and owners, approved profile, and the applicable phase exit evidence. Synthetic tasks do not establish real Vega cost savings or representative Phase 0 completion.

Packages A and B can proceed in parallel as planning/proof work once commissioned. Package C depends on the relevant contract decisions and verified gateway integration boundary. No package in this readout authorizes modifying Mach-Platform.

## 7. Deferred integration register

Before connecting a chosen Vega cohort, complete only the missing traces relevant to that cohort: registration and effective callers; trusted identity and charging ownership; block/source label creation; prompt/model resolution; cancellation and queue redelivery; substantive acceptance and side-effect recovery; provider SDK configuration; persistence/retention boundaries; and actual traffic/cost measurement.

Refresh the snapshot before integration. The reconnaissance is about the recorded source snapshot, not a permanent statement about every future Mach-Platform release.

## 8. Source receipt

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| DURANKI-CALL-PATH-INVENTORY.json | 80,201 | f103ee1d153e2af2538d1e7dfe5b5ef0c65e6192bf219607babdbcff414f33cb |
| DURANKI-FIXTURE-CATALOGUE.json | 18,747 | f487c3de15fd8dd7ee301da5b501308321d771e657ecf356c6c10c4522512ce3 |
| DURANKI-RECONNAISSANCE-RETURN.json | 3,028 | 3da889f7d838130a7d74bf9d071a973254b7964a23df6b76fc501ba0eb6e4804 |
| DURANKI-CLIENT-CONTRACT-MAPPING.md | 7,172 | 3fc7f87bf63ec1293a0895086c1d4608ea1e4bc7466595b2996d19b1ea59c2a5 |
| DURANKI-MACH-PLATFORM-RECONNAISSANCE.md | 19,510 | 0836150411fda1b3f3fa3f1c0f5b01d7b0ab76e37d1f7010702f34af115bce80 |
| llm-routing-infra-design-v1.1.md | 71,744 | 8f3ab5b86a8533687da6cb0e80e16b8d7586fc7392c02a646b8c08025aee7e9c |

The hashes identify uploaded inputs, not externally attested source custody. This assessment did not access the Mach-Platform checkout, run application tests, or verify provider/LiteLLM behavior.
