# Duranki Addendum A: Valhalla Alignment and Providers Beyond Language Models

**Changes to the Duranki v1.1 baseline, phase by phase**

| | |
|---|---|
| **Status** | Proposed addendum to Duranki v1.1. Nothing here changes Phase 0. The Phase 1a additions are small and are listed in Section 3. |
| **Version** | 0.1 |
| **Author** | Larry Mitchell, Chief Architect and Duranki owner |
| **Decisions** | Duranki changes: Duranki owner. Proto changes (P-02, P-15, P-17): Proto owner (CTO). Network egress and the migration of applications outside Proto: VP of Technology. |
| **Intended readers** | Duranki implementers; the Proto owner; VP of Technology; LLM engineering |
| **Date** | 23 October 2026 |
| **Amends** | Duranki — LLM Routing & Metering Infrastructure, v1.1 (16 October 2026) |
| **Companion documents** | Valhalla: Conceptual Architecture, version 0.4; Proto Runtime Proposal (23 October 2026) and its evidence report; Protecting Agency concept overview, draft 0.2 |

## How to read this addendum

- **Section 1** summarizes what changes and when. **Section 3** is the only part that touches Phase 1a, and it is time-sensitive.
- **Sections 4 to 7** align Duranki with Valhalla and with Proto: identities, budgets, what changes when Valhalla's core arrives, and the Proto boundary.
- **Section 8** extends Duranki beyond language models to speech, search and realtime voice. **Section 9** covers the direct provider calls outside Proto. **Section 10** closes the open ledger-database decision.
- **Sections 11 and 12** list every change to v1.1 by section, and the new acceptance tests. **Section 13** lists what is still open.
- Section references such as "§5.4" are to Duranki v1.1. References such as "Valhalla 7.6" are to the Valhalla document, version 0.4. "P-15" and similar are proposals in the Proto Runtime Proposal.
- Status labels follow Valhalla: **Built**, **Being built**, **Proposed**, **Planned**, **Concept**, **Candidate**.

---

## 1. Summary

Duranki v1.1 was designed before Valhalla existed. Valhalla now treats Duranki as its model plane: Neti's admission and final-dispatch check are the first of Ladon's enforcement points, Nisaba is the model plane's ledger, and Duranki's reservation and exposure model is the first implementation of Valhalla's budget authority (Valhalla 7.3 to 7.5). This addendum makes that relationship explicit without changing any Duranki contract, invariant or phase gate, except where stated.

It also widens Duranki's scope. v1.1 covers language-model calls. Of the fourteen direct provider call sites in Proto, only four are plain language-model calls. Two are model calls that search the web, and eight are speech-to-text, text-to-speech or realtime voice (Section 8.1). A door that only language models must pass through leaves most of Proto's provider traffic unmetered and ungoverned.

**What changes, and when:**

| When | Change | Section |
|---|---|---|
| **Phase 1a (time-sensitive)** | Commission and delegation references, and Valhalla's other shared fields, added to the instrumentation contract and ledger rows, each with a reason code when empty | 3 |
| Phase 1a | Ledger on managed Postgres, closing §18 item 10 | 10 |
| Phase 1b | Reservations made against a *budget account*, so the same logic later runs against Valhalla's budget authority | 5 |
| New Phase 1c | Speech, search and realtime voice through the gateway: same admission, authorization point, ledger, key custody and egress rules; no routing | 8 |
| Alongside 1a to 2 | Migration of the direct provider calls outside Proto, ending in egress denial | 9 |
| Valhalla step 3 | Commission revocation joins the final-dispatch check; Duranki's taint vocabulary becomes Valhalla's label vocabulary; Neti consults Trimorphus; budget authority moves to the Norns | 6 |
| Valhalla step 4 | The caller's activation epoch is checked at admission and at the final-dispatch check | 4 |

**The time-sensitive item.** Nisaba is append-only. Fields added before its schema is fixed cost almost nothing. Fields added later leave the earlier history without them, and who delegated to whom cannot be reconstructed with contemporaneous authority after the fact (Valhalla 12).

---

## 2. Duranki's place in Valhalla

**In plain terms:** Duranki keeps doing exactly what it was designed to do. Valhalla gives it neighbours: other enforcement points for tools, agents and storage, and a common set of record fields so that one question, such as "what did this piece of work cost?", can be answered across all of them.

| Duranki component | Its role in Valhalla | Valhalla reference |
|---|---|---|
| Neti: admission and final-dispatch check | The model plane's Ladon enforcement point | 7.5 |
| Nisaba: append-only ledger with dispatch intent | The model plane's ledger, one of Valhalla's federated ledgers | 7.3 |
| Duranki's reservation and exposure model (Phase 1b) | The first implementation of Valhalla's budget authority, scoped to the model plane | 7.4 |
| Authorization point and re-check before transmission | The pattern Valhalla adopts for every boundary: stopping happens at release | 7.6 |
| Monotonic taint on model-call content | The pattern for Valhalla's context labels | 4.6 |
| Shamash, Nabu | Precedents for Valhalla's evaluation and promotion loop | 8.5 |

What does not change:

- **Duranki routes models, not agents.** Valhalla's agent router is a separate service, because Duranki is deliberately kept out of agents' side effects (§8.1; Valhalla 8.3).
- **The orchestrator keeps its responsibilities**: substantive verification, acceptance, checkpoints, escalation, model-identity changes and side effects (§8.1). In Mach33 the orchestrator is Proto.
- **Duranki ships on its own schedule.** Nothing in this addendum makes a Duranki phase wait for Valhalla. Fields that Valhalla will fill later are present and empty, with a reason code, until then.

---

## 3. Phase 1a: shared fields in the instrumentation contract and ledger

### 3.1 The fields

Valhalla requires every ledger to carry the same minimum fields, so that records from different boundaries can be joined (Valhalla 7.3). Duranki already carries most of them. The table lists each shared field, its Duranki source, and what it holds in Phase 1a.

| Shared field | Duranki source | Phase 1a value | Filled from |
|---|---|---|---|
| Commission reference | **New** | Empty, reason `not_yet_issued` | Proto P-16 record-only commissions; enforced from Valhalla step 3 |
| Commission reference status | **New** | `absent` | `asserted` once Proto supplies commissions; `verified` once the Norns can validate them |
| Delegation chain | **New** | The authenticated principal and the calling agent | Extended link by link as Proto's invoke door (P-08) records each invocation |
| Delegation chain status | **New** | `partial` | `complete` once every invocation path records its links |
| Trace ID | §9 trace context | Present | Already required |
| Logical effect ID | **New**, derived from `step_id` + revision + `execution_generation` (§8.2) | Present where the orchestrator supplies step identity; otherwise the Proto call identifier (P-02) | See Section 4 |
| Attempt ID | `attempt_id` (§8.2) | Present | Already required |
| Activation epoch | **New** | Empty, reason `not_yet_issued` | Valhalla step 4 (Valhalla 8.1) |
| Actor | §9 identity | The agent's current identity | The Proto Entity UUID once birth records exist (P-07) |
| Effect | Request type and destination | Present | Extended with modality in Phase 1c (Section 8) |
| Cost | §10.2 usage capture | Present | Already required |
| Outcome | §8.4 attempt states | Present | Already required |
| Policy versions | `policy_version`, `recovery_policy_version`, `registry_version` (§5.3) | Present | Already required |

**The delegation chain.** It is an ordered list of links from the original request to the agent making the call. Each link records a principal or agent, the invocation identifier that created the link (P-02), and that link's commission reference once commissions exist. Its length is bounded by Valhalla's recursion controls (Valhalla 8.3). The gateway can verify the first link (the authenticated principal) and the last (the authenticated caller). Links in between are reported by the orchestrator and recorded as reported, because caller-supplied values are validated, never trusted (§5.1 control 1). They become verifiable when invocations carry authenticated records (P-08).

**Commission references before commissions exist.** Nothing issues commissions in Phase 1a. When Proto begins issuing commissions under P-16, which changes no enforcement behaviour until the enforcement cores exist, the field fills with status `asserted`: recorded, attributed and queryable, but never relied on for enforcement. From Valhalla step 3 the Norns validate it, the status becomes `verified`, and enforcement may rely on it.

### 3.2 The absence rule

Every shared field is present on every ledger row. A field may be empty only with a reason code from a closed list:

| Reason code | Meaning |
|---|---|
| `not_yet_issued` | The platform does not yet issue this identifier (commissions, activation epochs, birth records) |
| `not_applicable` | The field does not apply to this kind of row |
| `caller_omitted` | The caller should have supplied it and did not. The row is flagged non-compliant, as in migration mode (§5.1 control 2). |
| `unavailable` | The source was unreachable when the row was written; it is filled by an appended revision when the source returns |

The rule exists so that the ledger can tell "this did not exist yet" apart from "a caller dropped it". A conformance test enforces it and blocks deployment of any plane that fails it (Valhalla 7.3).

### 3.3 What it costs Phase 1a

- **Schema:** the new columns, the reason codes, and an index on commission reference and delegation-chain root.
- **Gateway:** recording the fields; verifying the first and last links of the delegation chain against the authenticated context it already checks.
- **Proto:** populating fields it already plans to carry. P-02 reserves slots, empty by default, for a commission reference, a delegation chain and an execution generation.
- **Not required for Phase 1a:** any enforcement based on these fields, or any change to admission. The Phase 1a exit criteria are unchanged except for the new tests (Section 12).

---

## 4. Identities

### 4.1 The mapping

Valhalla gives every effect three identities: a logical effect ID that recognises duplicates, an attempt ID for each try, and the activation epoch of the worker that proposed it, which fences stale workers (Valhalla 7.5). Duranki v1.1 has its own three levels (§8.2). They map as follows.

| Valhalla | Duranki | Meaning |
|---|---|---|
| Logical effect ID | `step_id` + revision + `execution_generation` | One model completion for one authorized invocation of a step. Duranki's deduplication key. |
| Attempt ID | `attempt_id` | One provider dispatch within a generation, including transport retries and permitted fallbacks |
| Activation epoch | **New:** the calling orchestrator's activation epoch | Lets Duranki refuse a request from a stale Proto activation |
| Not an effect identity | `step_id` + revision | The unit of single-winner acceptance, in the orchestrator state store (§8.5) |
| Not an effect identity | Provider request ID | Reconciliation only |

Two consequences:

- **An authorized escalation is a new effect.** It is a new execution generation, so it has a new logical effect ID and is never deduplicated into the result it replaces. This is the v1.0 correction to v0.3 (§0, v0.3 errors), preserved.
- **Acceptance stays at the step.** Several generations of one step are several effects, each billed; only one result per step is accepted, by compare-and-swap in the orchestrator's store.

Valhalla version 0.3 stated this mapping incorrectly, and used Duranki's term *execution generation* for its own worker fence. Version 0.4 corrects both: the worker fence is the *activation epoch*, and *execution generation* keeps Duranki's meaning (Valhalla, Appendix F).

### 4.2 Activation epochs at the gateway

From Valhalla step 4, every request carries the activation epoch of the Proto instance making it. Neti refuses a request whose epoch is older than the instance's current epoch, at admission and again at the final-dispatch check. The single-winner acceptance in the orchestrator state store also refuses a result submitted under an older epoch.

This closes a gap that v1.1 did not have to consider: a Proto instance that was paused or cut off, while its agent moved to another executor, waking and spending or accepting results in the agent's name (Valhalla 8.1).

### 4.3 Identities for calls that are not steps

Speech, search and realtime calls (Section 8) do not belong to orchestrator steps. Their logical effect ID is Proto's call identifier (P-02), kept across retries. A realtime session is one logical effect for its whole duration (Section 8.4).

---

## 5. Budgets: Phase 1b against a budget account

### 5.1 The change

Phase 1b's reservation model is unchanged: atomic reservation against the authorized total charge, exposure held until settled, owner expiry not releasing exposure, recovered state counting outstanding exposure before admission resumes, and failing closed when budget state is unavailable (§10.4). Valhalla adopted these rules as written (Valhalla 4.4 rule 3, 7.4).

What changes is *what* a reservation is made against. Instead of a principal's or task's balance directly, Phase 1b reserves against a **budget account**, named in the plan's `financial_scope`:

| Period | Budget account | Authority |
|---|---|---|
| Phase 1b, before Valhalla step 3 | The principal's or task's account, as v1.1 intends | Duranki: Redis for shared state, reconciled from the ledger |
| From Valhalla step 3 | The governing commission's account | The Norns' budget ledger for that commission tree; Duranki reserves through it |

The reservation interface is the same in both periods: reserve a maximum exposure for a logical effect against an account; settle actual cost; release proven-unused exposure. Only the implementation behind it changes, so Duranki's reservation logic is written once.

### 5.2 Rules that carry over

- **Sub-envelopes.** From step 3, a delegation carves a child commission's budget once from its parent's; Duranki's reservations touch only the governing commission's own account (Valhalla 7.4).
- **Partition.** If the budget authority for an account is unreachable, admission for that account fails closed. This is v1.1's rule (§5.4 failure table) and Valhalla's (7.4).
- **Retry and escalation allowances** (§8.3) stay per task and stay in Duranki. Each consumption records the commission reference, so they roll up by commission.
- **Exposure that outlives its owner** is held exactly as v1.1 requires; settlement or expiry of a child returns only the proven unused, unencumbered balance (Valhalla 7.4).

---

## 6. From Valhalla step 3: revocation, labels and decisions

None of these changes applies before Valhalla step 3, and none changes a Duranki contract before then.

### 6.1 Commission revocation at the final-dispatch check

- **Plans carry the governing commission's reference.** A plan authorizes work under one commission; revoking that commission revokes the plan, as a policy or registry change does today (§5.3).
- **A new final-dispatch check**, inserted after check 1 (§5.4): the governing commission is live, and no revocation fence covers it.
- **The authorization point is unchanged.** An attempt authorized but not yet transmitted when a revocation arrives is re-checked before transmission, as v1.1 already requires (§5.4; test 24). Valhalla adopted the same boundary: stopping happens at release, with the fence re-checked atomically with the release decision (Valhalla 7.6).
- **Gate freshness.** A gateway replica that loses contact with the commission state stops admitting when its short gate lease lapses (Valhalla 7.2), in the same way that it fails closed today when Redis or the policy store is unavailable.

### 6.2 One label vocabulary

Duranki's orchestrator taint (§5.1 control 3) and Valhalla's context labels (Valhalla 4.6) are the same mechanism: every source carries its restrictions, a context's labels only accumulate, and the handling policy is the combination of all of them. From step 3 they use **one vocabulary**, owned by the owner of Duranki's classification rules engine (§18 item 6), so that a label means the same thing at the model gateway, the tool dispatch point and the store.

Duranki's gateway-side structural guards (PII and secret scanning, rejection of untagged content) are unchanged. They remain model-plane checks.

### 6.3 Neti and Trimorphus

Neti keeps every model-specific check: capability, quality approval, the classification rules engine, lab policy, leases. For the questions Trimorphus answers for every boundary (who is acting, what permission authorizes this act, and what may reach this destination), Neti consults Trimorphus once it exists. Trimorphus's fail-closed rule applies: an error in a required policy, or a missing required input, is a refusal (Valhalla 7.5). This matches v1.1's principle that availability never trumps policy (§3 principle 4).

### 6.4 The budget authority moves

Once Duranki's Phase 1b exposure model is proven, step 3 moves budget authority into the Norns, generalized to compute, storage and agent invocations, and Duranki reserves through it (Section 5; Valhalla 7.4). Proving Duranki's model is one of Valhalla's step 3 gates (Valhalla 12).

---

## 7. The Proto boundary

### 7.1 The provider seam (P-15)

P-15 gives Proto one provider client layer, with typed interfaces for language models, search, speech-to-text, text-to-speech and realtime voice. v1.1 assumed the gateway would replace only the language-model interface. Under this addendum:

- **Phase 1a:** the language-model interface is implemented by the Duranki gateway.
- **Phase 1c:** the search, speech and realtime interfaces are implemented by the gateway too (Section 8).
- Every call carries P-02 identifiers and the shared fields of Section 3.

### 7.2 Orchestrator obligations (P-17), by phase

| Duranki phase | What Proto supplies |
|---|---|
| 1a | Authentication, attribution and purpose (§5.1); P-02 trace context; the shared fields of Section 3, empty with reason codes where Proto does not have them yet |
| 1b | Step identity, execution generations and single-winner acceptance (§8.2, §8.5); handling of outcome-unknown attempts (§8.4) |
| 1c | Call identifiers and modality for speech, search and realtime calls (Section 8) |
| 2 | The full instrumentation contract (§9): monotonic taint labels on every tool result, document and attachment; lineage IDs on message blocks; construction manifests for leaf steps; known-good checkpoints |
| Valhalla step 3 | Governing commission on every call; activation epoch from Valhalla step 4 |

### 7.3 One contract for Duranki and ADR 0051

P-17 proposes mapping Duranki's instrumentation fields onto ADR 0051's observable tuple, so that one contract serves both. This addendum maps the fields to the four regions whose content P-03 specifies (s: versions and hashes; e: spans; t: timestamps, trace links and the hybrid logical clock; p: agent and activity identity, with observer attribution). ADR 0051's other regions (u, i, h, n) are not described in the documents this addendum draws on, so fields that may belong there are left for the joint Proto–Duranki review.

| Duranki §9 field | Proto source | Proposed ADR 0051 region |
|---|---|---|
| Trace and span context, span links | P-02 | t |
| Principal, service principal, charging owner | Authenticated context | p |
| `task_id`, `subtask_id`, `session_id` | P-02 identifiers | p |
| `step_id` + revision, `execution_generation` | P-02 reserved slots | p |
| Commission reference, delegation chain, activation epoch | P-02 reserved slots; P-08; Valhalla 8.1 | p |
| `purpose`, `step_type`, `step_class`, pinned-model flag | Proto call site | e (attributes of the model-call span) |
| Construction manifest (leaf steps) | Proto, versioned | s (manifest hash), referenced from e |
| Lineage IDs on message blocks | Proto | Joint review |
| Taint labels | Proto | Not a telemetry coordinate: an enforcement input recorded in the ledger. Joint review for any projection. |
| Outcome signals (§11.1) | Proto | Joint review |
| `task_class` | Proto | Joint review |

**Two streams.** ADR 0051 separates the agent's own account from evidence observed at its boundaries, with PROV-O attribution in **p** (P-03). Nisaba's rows are boundary observations: the gateway saw the request and the provider's usage. Proto's spans are the agent's own account. The ledger therefore supplies the boundary stream for model, speech and search calls, and the two can be compared, which is what ADR 0051's third-party verifier needs.

---

## 8. Providers beyond language models

### 8.1 What Proto calls today

The Proto evidence report lists fourteen direct provider call sites inside Proto and the Agency (F-12):

| Kind of call | Providers | Call sites |
|---|---|---|
| Language model | Anthropic | 4 (chat stream, decomposition, tension detection, Agency member chat) |
| Model call that searches the web | xAI, through its Responses API | 2 (horizon search, Vega web search) |
| Speech-to-text | Deepgram, xAI | 2 |
| Text-to-speech | ElevenLabs, xAI | 5 (speech synthesis twice; voice fillers, yields and backchannels) |
| Realtime voice | xAI | 1 (WebSocket) |

Ten of the fourteen are not plain language-model calls. Outside Proto, the static search found more than a hundred further direct calls, including OpenAI transcription (Section 9).

### 8.2 How these calls differ

| Kind | Billed by | Can exposure be bounded before the call? | What is sensitive | Latency |
|---|---|---|---|---|
| Speech-to-text, recorded | Audio duration | Yes, from the input's duration | The audio itself, which may be personal data, and its transcript | Moderate |
| Speech-to-text, live | Audio duration | Only by a session maximum | As above, continuously | High |
| Text-to-speech | Characters | Yes, from the input text | The text sent; the voice choice | High for fillers and backchannels |
| Realtime voice | As the provider bills (tokens or time) | Only by a session maximum | Everything said in both directions | Very high |
| Web search | Model tokens, plus searches or sources retrieved | Yes, per request, with a cap on searches | **The query**: a search for a confidential acquisition target tells the search provider about the deal. The results are external content of unknown trustworthiness. | Moderate |

Three things follow:

- **Classification works from labels, not scanning.** v1.1's structural guards scan text for PII and secrets (§5.1 control 3). Audio cannot be pattern-scanned cheaply, so speech calls are classified from their source labels (who is speaking, in which session, under which client terms), and destination permission does the rest.
- **Search queries are content.** They are classified and checked against the destination's permission exactly as prompts are. Search results enter the context carrying their provenance and an *external, untrusted* label: they are data, never instructions (Valhalla 7.7).
- **Streams need session-level budgets.** v1.1 excludes from hard-ceiling workloads any request whose maximum exposure cannot be bounded (§10.4). Live speech and realtime voice are bounded by giving each session a maximum, reserving for an increment of it, and topping the reservation up as the session continues (Section 8.4).

### 8.3 What the gateway product supports

Checked against LiteLLM's documentation on 23 October 2026. Every entry still needs verification against the pinned release, as §4.3 requires for every feature Duranki relies on.

| Kind | Documented in LiteLLM | Not documented |
|---|---|---|
| Speech-to-text | `/audio/transcriptions` through the proxy, with cost tracking marked as supported, for providers including OpenAI and Deepgram [1][2]; ElevenLabs Scribe [3] | xAI speech-to-text; Deepgram live streaming |
| Text-to-speech | `/audio/speech` through the proxy for ElevenLabs [3] | xAI text-to-speech |
| Realtime voice | `/v1/realtime` over WebSocket through the proxy, including xAI's Grok Voice Agent [4][5]; guardrails can run before a session starts [4]; realtime cost tracking with token usage, documented for OpenAI and Azure [6] | Cost tracking for xAI realtime |
| Web search | Not established | xAI's search through the Responses API, and how its cost is tracked |

One documented behaviour conflicts with Duranki's data handling: LiteLLM logs complete realtime responses to its logging integrations [4][6]. Duranki's allowlisted telemetry schema (§13.2) requires this to be restricted before any realtime traffic passes through the gateway.

### 8.4 The design: one door, two lanes

Every provider call passes through the same door: the same admission (identity, attribution, purpose, classification, destination permission, retention), the same authorization point, the same ledger, provider keys held only by the gateway, and egress denied to everything else (§3 principle 1; §4.4).

Behind the door there are two lanes:

- **Lane 1: LiteLLM**, for every provider endpoint that the pinned release verifiably supports, meters correctly and lets Duranki's hooks govern.
- **Lane 2: a thin Duranki-owned proxy** for the endpoints LiteLLM does not support or cannot meter correctly. It implements the same hook contract: admission, the authorization point, ledger rows, key custody. It is the contingency layer v1.1 already requires to be decided before Phase 1a (§4.3, §18 item 7), built once and used for both purposes.

For these kinds of call, at first:

- **No routing or optimization.** Destinations are fixed, as in Phase 1a. Choosing cheaper speech or search providers by quality is a later decision, with its own evaluation.
- **Streaming effects.** A live transcription or realtime session is admitted once, at its start, and is one logical effect. Its release is continuous, so stopping works chunk by chunk: a revocation, a failed reservation top-up or an expired gate lease closes the session at the next chunk boundary, within the revocation-latency bound (Valhalla 7.2). What has already streamed is settled. Admission happens per session, never per audio frame.
- **Usage capture.** §10.2's normalized billable categories gain modality-specific units under a new usage-semantics version: audio seconds, characters, realtime tokens or minutes as each provider bills, and search requests or sources. Missing usage is estimated, never zero.
- **Retention.** Raw audio is not stored unless a retention class allows it. Transcripts inherit the handling of the audio they came from (§13.2, derived data).
- **Latency.** The extra hop matters most for voice. The gateway serving voice runs in the same region as the voice bodies, admission is per session, and the added latency is measured for each kind of call. The acceptable figure is a planning parameter for the voice product's owner; none is set here.
- **Repeated synthesis.** Fillers, yields and backchannels are short phrases synthesized on each use. If they come from a fixed set, caching their audio would remove most of those calls. Any such cache sits after admission and follows §5.6.

### 8.5 Phase 1c

| | |
|---|---|
| **Scope** | Speech-to-text, text-to-speech, realtime voice and web search through the gateway, in the two lanes of Section 8.4; Proto's P-15 interfaces for them implemented by the gateway; modality-specific usage capture; realtime logging restricted to the allowlisted schema; session-level reservations for streams |
| **Admission profile** | As Phase 1a (§5.1): identity, purpose, destination permission, classification and retention enforced; per-principal spend limits and alerts; no hard concurrent-ceiling guarantee. Hard ceilings for streams follow Phase 1b's reservation model once it is proven. |
| **Ordering** | After Phase 1a; can run alongside Phase 1b |
| **Exit criteria** | All of Proto's speech, search and realtime traffic is authenticated, attributed and recorded in the ledger; their provider keys are held only by the gateway; Phase 1c tests pass (Section 12) |

---

## 9. Direct provider calls outside Proto

The Proto evidence report's static search found more than a hundred further direct provider calls in the wider repository: `messages.create` and `messages.stream`, and HTTP and WebSocket calls to xAI, OpenAI, Deepgram and ElevenLabs, in applications, libraries and diagnostic scripts. The list is not provably exhaustive; dynamic call sites need call-graph analysis.

Because no inventory can be shown to be complete, the backstop is **egress denial**: once provider keys exist only in the gateway and network policy blocks provider endpoints for everything else, any call that was missed fails loudly instead of leaking. The migration ends there.

1. **Inventory and owners.** Each call site is assigned to the owner of its application. Owner of the inventory: Chief Architect.
2. **Migrate application by application.** Where an application's client library can be pointed at the gateway, migration changes only the base URL and the credential; elsewhere it needs code changes, and the inventory records which is which. Speech, search and realtime calls migrate once Phase 1c serves them.
3. **Revoke keys as applications move.** When an application is migrated, its provider keys are revoked. Developers and diagnostic scripts use the gateway under a developer principal, so their usage is metered too.
4. **Deny egress.** Once every known caller is migrated, network policy denies provider endpoints from everything except the gateway, in every environment. For Proto, this is a Valhalla step 3 gate (Valhalla 12). For the wider repository, the date is set by the VP of Technology, who owns egress policy and production applications.
5. **Watch for failures.** Denied connections are logged and alerted, so a missed caller is found when it first fails, not when an invoice arrives.

---

## 10. The ledger on Postgres

Nisaba's database product was open (§18 item 10). It is **managed Postgres**: Cloud SQL while Mach33 runs on GCP, and RDS when the move to AWS happens (Valhalla 10.1).

- **Append-only by privilege.** The gateway's database role may insert and read, never update or delete. Settlement and reconciliation append linked revisions, as v1.1 requires (§10.1).
- **Partitioned by time**, so that retention is applied by dropping whole partitions once their window has passed (about 13 months for accounting rows, §13.1). Partitioning by commission tree can be added when Valhalla's sharding needs it (Valhalla 7.3).
- **Hash chaining.** Each row carries a hash of the previous row in its partition, and partition heads are written periodically to a shared anchor (Valhalla 7.3). It is cheapest to add with the schema, but unlike the commission fields it can start later without losing anything except tamper evidence for earlier rows. It is recommended for Phase 1a, not required.
- **The write-ahead log for brief outages** stays as §10.1 specifies: replica-local, on a persistent volume, for a bounded window, failing closed when unavailable.
- **One engine for all of Valhalla's ledgers**, so that the conformance tests, the operational skills and the cross-plane joins are the same everywhere.

---

## 11. Changes to Duranki v1.1, by section

| v1.1 section | Change | Phase |
|---|---|---|
| §1 Purpose | Metering and governance cover speech, search and realtime voice as well as language models; routing remains for language models | 1c |
| §3 principle 1 | "The gateway is the only door" covers every external AI provider call, not only model calls | 1c |
| §4.1 Components | Ledger: managed Postgres (decided). New component: Lane 2 proxy (build), merged with the §4.3 contingency | 1a, 1c |
| §4.3 Verification | Extended to every provider endpoint Duranki serves, including speech, search and realtime, and to LiteLLM's realtime logging default | 1c |
| §5.1 Admission | Phase 1c admission profile; search queries classified as content; speech classified from source labels | 1c |
| §5.3 Plan | Plans carry the governing commission's reference and the budget account in `financial_scope` | 1b; step 3 |
| §5.4 Final-dispatch check | New check after check 1: governing commission live and not fenced; activation epoch current | Step 3; step 4 |
| §8.2 Identity levels | Logical effect ID defined as step + revision + execution generation; activation epoch added | 1a; step 4 |
| §8.5 Single-winner acceptance | Acceptance refuses results submitted under an older activation epoch | Step 4 |
| §9 Instrumentation contract | Shared fields of Section 3, with reason codes; field-to-region mapping of Section 7.3 | 1a |
| §10.1 Ledger | Shared fields and the absence rule; Postgres; hash chaining recommended | 1a |
| §10.2 Usage capture | Modality-specific billable categories under a new usage-semantics version | 1c |
| §10.4 Budgets and exposure | Reservations against a budget account; session-level reservations for streams | 1b; 1c |
| §13 Retention | Raw audio not stored by default; transcripts inherit the audio's handling | 1c |
| §15 Phased plan | New Phase 1c (Section 8.5) | — |
| §16 Tests | Tests 42 to 52 (Section 12) | 1a, 1c, step 3, step 4 |
| §18 Open decisions | Item 10 closed (Postgres); new items in Section 13 | — |

---

## 12. New acceptance tests

Numbered after v1.1's test 41, so existing references stay valid. As in v1.1, each test is a requirement of the first phase that relies on its guarantee.

**Phase 1a**

42. A ledger row with an empty shared field and no reason code, or with a reason code outside the closed list → conformance check fails and deployment is refused
43. A delegation chain whose first link does not match the authenticated principal, or whose last link does not match the authenticated caller → rejected
44. A caller-supplied commission reference before commissions are validated → recorded with status `asserted`; no admission decision depends on it

**Phase 1c**

45. A speech, search or realtime call from any identity other than the gateway reaching a provider endpoint → blocked by egress policy and alerted
46. A search query carrying a label that the search destination does not permit → rejected before transmission
47. A realtime session whose reservation top-up fails → session closed at the next chunk boundary; usage to that point settled
48. Complete realtime responses presented to a logging integration → blocked by the allowlisted schema
49. Missing usage for a speech or search call → recorded as estimated, never zero; reconciled later by appended revision

**Valhalla step 3**

50. Governing commission revoked between the final-dispatch check and transmission → attempt not transmitted (extends test 24)
51. A realtime session whose governing commission is revoked → session closed at the next chunk boundary, within the revocation-latency bound

**Valhalla step 4**

52. A request, or a result submitted for acceptance, carrying an activation epoch older than the instance's current epoch → refused

---

## 13. Still open

1. **Label vocabulary owner.** Section 6.2 assigns it to the owner of the classification rules engine, who is not yet named (§18 item 6).
2. **Which speech and search providers remain.** Phase 1c serves the current ones. Whether to keep separate providers for speech-to-text, text-to-speech and realtime voice is a product decision, best made with the metering Phase 1c provides.
3. **Voice latency budget** through the gateway, per kind of call. Owner: the voice product's owner.
4. **Lane 2 scope.** Which endpoints it serves depends on verification against the pinned LiteLLM release (Section 8.3).
5. **Date for egress denial** across the wider repository. Owner: VP of Technology.
6. **Hash chaining in Phase 1a**, or later (Section 10).

---

## Appendix: References

1. LiteLLM, *Audio transcription* (`/audio/transcriptions`). https://docs.litellm.ai/docs/audio_transcription
2. LiteLLM, *Deepgram*. https://docs.litellm.ai/docs/providers/deepgram
3. LiteLLM, *ElevenLabs*. https://docs.litellm.ai/docs/providers/elevenlabs
4. LiteLLM, *Realtime API*. https://docs.litellm.ai/docs/realtime
5. LiteLLM, *xAI Voice Agent (Realtime API)*. https://docs.litellm.ai/docs/providers/xai_realtime
6. LiteLLM, *Release notes v1.66.0-stable* (realtime cost tracking and logging). https://docs.litellm.ai/release_notes/v1.66.0-stable/v1.66.0-stable

Internal documents: Duranki v1.1 (16 October 2026); Valhalla: Conceptual Architecture, version 0.4; Proto Runtime Proposal and its evidence report (23 October 2026); Protecting Agency concept overview, draft 0.2.
