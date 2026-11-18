# Review tracker — Duranki (LLM routing design), v0.1 → v1.1

## Proposed changes (running list)

| # | Source | Change | Section | Status |
|---|---|---|---|---|
| 1 | Grok | Conservative default for R: learned routing disabled per step type until a minimum number of labeled outcomes exists; rules-only until then | 5.5, 8 | Adopt |
| 2 | Grok | Cascade-with-verifier is the default (not optional) for any step with a cheap checker | 5.5 | Adopt |
| 3 | Grok | New section: agent instrumentation contract (attribution tags, subtask boundaries, outcome signals, ownership) | new §6.x | Adopt |
| 4 | Grok | Jev vs local embedding classifier as explicit shadow experiment with falsification criterion | 5.5, 8 (Ph 3/5) | Adopt |
| 5 | Grok | Stickiness vs step-level routing as an explicit measured experiment | 5.7, 8 | Adopt |
| 6 | Grok | Lab routes under the same quality gate; gate is per model + quantization, not per location | 5.4 | Adopt (refined) |
| 7 | Grok | Specify saturation cost function, wait-time prediction/smoothing, and full overflow chain when all self-hosted pools are saturated | 5.6 | Adopt |
| 8 | Grok | Phase 0/1 exit: baseline cost per completed task by agent type | 8 | Adopt |
| 9 | Grok | Define quality bar + statistical test for "equal quality" exit criteria | 8 | Needs decision |
| 10 | Grok | License/feature-gating review becomes a Phase 1 exit criterion | 8 | Adopt |
| 11 | Grok | Cache-miss rate as an explicit metric in Phase 2 and 5 exit criteria | 8 | Adopt |
| 12 | Grok | Recalibration process on model/prompt version change; affected model falls back to rules-only while pending | 5.9 / new | Adopt |
| 13 | Grok | Nested sub-agent cost/outcome roll-up as named risk + attribution requirement | 6.1, 9 | Adopt |
| 14 | Grok | Presence = office LAN subnets only, explicitly excluding VPN address pools | 5.4 | Adopt (clarification) |
| 15 | Grok | Prompt storage: concrete retention and access controls | 6.3 | Needs decision (now coupled to #21) |
| 16 | Gemini | Split steps: verifiable (cascade, bounded R) vs unverifiable trajectory steps (R as hyperparameter tuned on end-to-end task success; cheap routing only for leaf subtasks) | 5.5 | Adopt — supersedes #1 framing |
| 17 | Gemini | Sticky "main agent spine"; step-level routing for stateless leaf calls; context isolation in agent framework as prerequisite | 5.7, 8 (Ph 2) | Adopt — refines #5 |
| 18 | Gemini | Fix own inconsistency: 150 ms router timeout vs Jev's reported 70–500 ms latency. Jev out of synchronous path unless bake-off justifies it | 5.5, 5.9 | Adopt |
| 19 | Gemini | Three-way bake-off: metadata-only model vs local embedding classifier vs Jev features; Jev may serve offline as a labeler for the local classifier | 8 (Ph 3) | Adopt — extends #4 |
| 20 | Gemini | Demo drain: let short in-flight sessions finish on lab; stagger migrations to avoid a prefill storm on the cloud pool | 5.4 | Adopt |
| 21 | Gemini | Overnight counterfactual replay on idle lab for paired labels (leaf/verifiable steps); uniform 1% exploration slice for positivity; trajectory steps need recorded tool outputs | 5.8, 8 | Adopt (with limits) |
| 22 | Gemini | Size cloud self-hosted pool for base load; bursts go straight to cheaper frontier tier (GPU scale-up takes minutes) | 5.6, 7 | Adopt — changes overflow chain in #7 |
| 23 | Gemini | Gateway HA: multiple stateless LiteLLM replicas, Redis-backed budget checks, telemetry off the critical path | 4, 7 | Adopt |
| 24 | Gemini | Fail-open passthrough gateway on health-check failure — but it must still enforce data classification (fail closed for sensitive traffic) | 5.9, 9 | Adopt (modified) |
| 25 | Gemini | Non-streaming for internal agent steps so cascades can validate and retry transparently | 5.5 | Adopt |
| 26 | Gemini | Canonical tool-schema subset + per-model-family prompt wrappers in gateway plugin | 5.2, 9 | Adopt |
| 27 | Gemini | Session-hash affinity enforced at serving ingress from Phase 4 day one | 5.7, 8 | Adopt |
| 28 | Gemini | Goodhart risk: syntactic signals are guards/features, not the training reward; anchor labels to terminal task success or verified eval | 6.3, 9 | Adopt — reconciles with #3 |
| 29 | Gemini | Note VPN hairpinning for large payloads (images/PDFs) | 7 | Adopt (minor) |
| 30 | Gemini | Drop office-presence requirement for lab (idle nights/weekends) | 5.4 | Needs decision |
| 31 | DeepSeek | Instrument R from Phase 1 with causal lineage (retries, escalations, re-executions linked to originating step); keep R as a distribution; risk-adjusted threshold (tail/CVaR) for verifiable steps | 5.5, 6 | Adopt — fold lineage IDs into instrumentation contract (#3) |
| 32 | DeepSeek | Separate concerns: gateway session stickiness = which tier/model (policy); node placement = prefix-cache-aware scheduler at serving layer (llm-d / GKE Inference Gateway score prefixes themselves). Leaf calls benefit from shared system-prompt/tool prefixes across sessions | 5.7 | Adopt (corrected) — replaces #27. Note (round 3): v0.3 §6.6 implements three things, not one: policy-level model affinity, serving-layer cache placement, and eligibility/failover overrides returning to the orchestrator (R2-31) |
| 33 | DeepSeek | Exploration rate per step type, driven by head uncertainty (Thompson-style); higher rates only on steps with a verifier/cascade behind them | 5.8 | Adopt (modified) — complements #21 |
| 34 | DeepSeek | If residency applies: residency becomes a capability filter; possible split-region pools | 5.2, 7 | Adopt, conditional on residency decision |
| 35 | DeepSeek | Meter routing overhead (Jev cost, classifier compute, added latency) as first-class cost; latency-accumulation risk | 6.2, 9 | Adopt |
| 36 | DeepSeek | Canary eval on model version change before full switch | 5.9 / #12 | Adopt — extends #12 |
| 37 | DeepSeek | Regularly exercise fallback paths (local classifier, rules-only, passthrough) — scheduled failover tests | 9 | Adopt |
| 38 | DeepSeek | Jev for cold-start/rare step types, distilled local classifier for hot paths — add as bake-off arm | 8 (Ph 3) | Adopt — extends #19 |
| 39 | GPT-6.1 | Separate mandatory admission (auth, attribution, classification, capability, budget, lab restrictions) from optional optimization; hard checks apply even with routing disabled; rules short-circuit ranking only. Classification moves to Phase 1 (v0.1 had it in Phase 4 — error) | 3, 5, 8 | Adopt — highest priority |
| 40 | GPT-6.1 | Router returns a bounded execution plan (deployment, permitted fallbacks, policy version, constraints, deadline, retry allowance, budget auth); gateway may not substitute outside it | 4, 5 | Adopt |
| 41 | GPT-6.1 | Rewrite availability promise: optimization failure → deterministic compliant route; if none, queue or fail explicitly; never relax security/budget | 1, 5.9 | Adopt — generalizes #24 |
| 42 | GPT-6.1 | Objective = min expected task cost subject to quality and latency constraints per task class; cost inequality is the heuristic inside an approved quality envelope | 1, 5.5 | Adopt |
| 43 | GPT-6.1 | Three outcome levels: execution success, step correctness, task acceptance; cascade quality depends on detection rate × recovery | 6.3 | Adopt — reconciles #3, #28 |
| 44 | GPT-6.1 | Retry/recovery state model (pre-dispatch, unknown outcome, partial output, uncommitted, committed side effect); gateway owns transport retries, orchestrator owns semantic recovery; logical step ID + attempt ID; single global retry budget; escalate from known-good state | new §5.x | Adopt |
| 45 | GPT-6.1 | Authenticated attribution (validate identity/task ownership, not trust tags); classify the assembled request incl. retrieved docs/tool results; service principals for background work | 6.1 | Adopt |
| 46 | GPT-6.1 | Fix OTel: trace/span context with parent spans and span links, not "parent_trace_id" (v0.1 error) | 6.1 | Adopt |
| 47 | GPT-6.1 | Accounting authority = durable deduplicated per-attempt usage ledger, independent of trace sampling; unknown usage marked unknown/estimated; normalize provider usage into exclusive buckets; keep raw usage | 6.2 | Adopt |
| 48 | GPT-6.1 | Jev and all classifier/verifier/shadow calls go through the gateway and are metered (LiteLLM has a TypeSafe passthrough and /v1/decisions endpoint — verified) | 4, 6.2 | Adopt |
| 49 | GPT-6.1 | Budget admission control with concurrent reservation/settlement; defined behaviour when budget state unavailable | 6, 8 | Adopt |
| 50 | GPT-6.1 | Cost per accepted task computed over full task cohorts, including failed and abandoned tasks | 6.4, 8 | Adopt |
| 51 | GPT-6.1 | Bake-off adds deterministic-rules baseline; fallback classifier needs its own head (not interchangeable with Jev-trained head) | 8 (Ph 3), 5.9 | Adopt — extends #19/#38 |
| 52 | GPT-6.1 | Separate model affinity / replica-cache affinity / recoverable conversation state; pin model per subtask with reconsideration at boundaries; explicit pinned-model mode (evals, reviewer independence) | 5.7 | Adopt — consolidates #17, #32 |
| 53 | GPT-6.1 | Fix lab admission wording (v0.1 "headroom below threshold" — error); define capacity denominator; admission leases to prevent replica races; stale metrics stop admission | 5.4 | Adopt |
| 54 | GPT-6.1 | Drain requests, not just new sessions: stop time, max in-flight, sticky continuations, cancellation, handover condition | 5.4 | Adopt — extends #20 |
| 55 | GPT-6.1 | Cache isolation across tenants/security domains (vLLM cache salting) as risk + policy | 9 | Adopt |
| 56 | GPT-6.1 | Shadow routing ≠ counterfactual outcomes; randomized task/subtask cohorts for early evaluation; record full eligible set + execution chain; doubly robust evaluation later | 5.8, 8 | Adopt — complements #21/#33 |
| 57 | GPT-6.1 | Decision replay requires permitted feature snapshots, extractor/policy versions, candidate sets, scores — hashes alone insufficient | 6.3 | Adopt — couples to #15 |
| 58 | GPT-6.1 | Stage infrastructure: gateway + telemetry with existing endpoints, then one lab pool, then cloud inference when measured demand justifies it | 7, 8 | Adopt |
| 59 | GPT-6.1 | Pick a coherent serving stack (KServe + llm-d complementary; Ray alternative); one logical gateway = replicated; lab and cloud independently operable pools | 4.1, 7 | Adopt |
| 60 | GPT-6.1 | Correct marketplace residency claim (v0.1 overstated): cross-region inference and global endpoints can move data; record permission per endpoint/profile/model/geography | 7.1 | Adopt |
| 61 | GPT-6.1 | Three cost views: avoidable incremental (routing), allocated (reporting), full operating (capacity); new cloud capacity is not near-zero marginal | 5.6, 6.2 | Adopt |
| 62 | GPT-6.1 | Strengthened phase exit criteria + pre-live fault test suite (restricted-request timeout, unauthorized fallback, budget race, partial stream, missing usage, stale lab metrics, long-session drain, classifier version change) | 8 | Adopt — scope Phase 1 carefully |

## Round 2 (v0.2) — proposed changes

| # | Source | Change | Section | Status |
|---|---|---|---|---|
| R2-1 | Grok | Retry/fallback revalidation re-classifies the *current* assembled request, not the admission snapshot | 5.4, 8 | Adopt |
| R2-2 | Grok | Session model pin becoming ineligible mid-task (sensitivity raised by new content) → explicit failure to orchestrator; only the orchestrator may relax a pin | 5.1, 6.6 | Adopt |
| R2-3 | Grok | State explicitly that Jev/classifier calls pass admission themselves and cannot score content above their ceiling | 5.1 | Adopt (clarification) |
| R2-4 | Grok | Add `classification_snapshot` (level, content hash, classifier version) to execution plan | 5.3 | Adopt |
| R2-5 | Grok | Add `verifier_spec` to execution plan — with ownership split: syntactic verifiers in gateway; semantic verifiers (tests, execution) in orchestrator, which then drives escalation | 5.3, 6.2, 8.1 | Adopt (refined) |
| R2-6 | Grok | Retry budget decremented atomically against a single authority shared by gateway and orchestrator | 8.2 | Adopt |
| R2-7 | Grok | "Outcome unknown" gets a bounded timeout and an explicit signal to the orchestrator, reconciled with ledger | 8.3 | Adopt |
| R2-8 | Grok | Replay labels are deployment-specific (model + quantization + serving config); cross-check against randomized cohorts before promotion | 12.1 | Adopt (strengthened) |
| R2-9 | Grok | Low-volume / high-consequence classes stay on baseline policy by explicit rule | 11.3 | Adopt |
| R2-10 | Grok | Instrumentation adoption: compliance gate — but via a migration mode (attribute to agent's authenticated principal, flag non-compliant, ineligible for optimization) rather than rejecting traffic | 9, 15 | Adopt (modified) |
| R2-11 | Grok | New fault tests: reclassification race; outcome-unknown timeout; nested retry budget under concurrency | 16 | Adopt |
| R2-12 | Grok | New risks: reclassification race; outcome-unknown stall; replay label bias; partial instrumentation adoption | 17 | Adopt |
| R2-13 | Gemini | Derivative calls (verifier, judge, distillation, Jev) inherit max(parent sensitivity, own prompt sensitivity) at admission | 5.1 | Adopt — generalizes R2-3 |
| R2-14 | Gemini | Classification responsibility split: orchestrator does monotonic taint-tracking from source-tagged tool results/documents; gateway enforces structural guards (PII/secret scan, rejects untagged tool results). v0.2 overclaimed gateway content classification. Leaf isolation scopes taint to the leaf payload | 5.1, 9 | Adopt — corrects v0.2 |
| R2-15 | Gemini | Execution plan: per-attempt TTFT and total timeouts; prompt_adapter_map per candidate deployment; idempotency_key; lease_token | 5.3 | Adopt |
| R2-16 | Gemini | Two-tier cascades: Tier 1 gateway-owned structural checks; Tier 2 orchestrator-owned semantic checks, re-issued as new attempt with originating_step_id and min_tier constraint | 6.2, 8.1 | Adopt — agrees with R2-5 |
| R2-17 | Gemini | New attempt state SUPERSEDED_BY_ESCALATION; tokens billed and counted toward step cost and realized R | 8.3, 10 | Adopt |
| R2-18 | Gemini | Split leaf-trajectory cell: compressions/transformations (cheap allowed if grounded/citable by spine or errors soft) vs state-altering decisions (filtering, selection, sub-planning: not cheap by default) | 6.1, 6.3 | Adopt |
| R2-19 | Gemini | Replay: k≈4 samples per prompt (shared prefill) for empirical pass rates instead of binary labels | 12.1 | Adopt |
| R2-20 | Gemini | Judge never from same model family as the candidate being judged; blind/normalize formatting; track human-vs-judge kappa | 11.2 | Adopt |
| R2-21 | Gemini | Sequential testing (mSPRT / confidence sequences) for cohorts with early harm stopping; pooled macro-tier gating for low-volume classes, with per-class harm monitoring retained | 11.3 | Adopt (pooling with caveat) |
| R2-22 | Gemini | Lab drain forces mid-spine cross-family migration when no same-family fallback exists: fault test + transcript normalization in adapters; admit spines to lab only if expected to finish before next reservation or a tested cross-family path exists | 7.3, 16, 17 | Adopt (extended) |
| R2-23 | Gemini | Background preemption = gateway cancels in-flight background requests on lease-service signal (frees KV cache) | 7.1, 6.7 | Adopt |
| R2-24 | Gemini | Redis budget reservations carry TTLs; settled spend reconciled from durable ledger | 10.4 | Adopt |
| R2-25 | Gemini | New risks: cross-family transcript translation failure; Redis reservation loss; judge drift/verbosity bias | 17 | Adopt |
| R2-26 | DeepSeek | Pinned mode ⇒ empty permitted_fallbacks; explicit failure on unavailability | 5.1, 5.3 | Adopt — corroborates R2-2 |
| R2-27 | DeepSeek | Marketplace geography binding: region-pinned inference profiles for any sensitivity above public; log provider-reported processing region | 14.4, 10 | Adopt |
| R2-28 | DeepSeek | Remove the "explicitly configured policy" escape clause from budget fail-closed (v0.2 softening) — no exceptions initially | 5.1 | Adopt — corrects v0.2 |
| R2-29 | DeepSeek | Classification is a deterministic, locally evaluable rules engine (label inheritance/taint, patterns, allowlists) so it survives degraded mode; models only auxiliary | 5.1, 5.4 | Adopt — converges with R2-14 |
| R2-30 | DeepSeek | Plan fields: retention_class, prefix/cache hint, per-attempt cost ceiling (enforced as output-token limit, not mid-stream cutoff), cancellation_token; propensity = 1.0 for deterministic decisions | 5.3 | Adopt |
| R2-31 | DeepSeek | Spine fallbacks: same-deployment only at gateway; any model-identity change returns to orchestrator, which restarts the subtask. Eligibility shrink mid-spine ⇒ forced re-route, orchestrator notified, cache loss accepted | 5.3, 6.6 | Adopt — closes #32 reopen |
| R2-32 | DeepSeek | Cancelled attempt state; cascade escalations use a separate bounded escalation allowance (≤1 per step initially), not the failure-retry budget | 8.3, 6.2 | Adopt |
| R2-33 | DeepSeek | Gateway validates leaf claims against evidence (payload excludes spine history, independent parent span, no in-task upstream dependency); spot-audit verifiability labels | 6.1, 9 | Adopt |
| R2-34 | DeepSeek | Phase 0/3 report spend share per taxonomy quadrant to establish the achievable savings ceiling before Phase 5 is scoped | 15 | Adopt |
| R2-35 | DeepSeek | p keyed by deployment, not model name; decision rule states its p_s ≈ 1 assumption | 6.4 | Adopt |
| R2-36 | DeepSeek | Replay: measure coverage per step type vs live share; min-outcome gate applies to replay coverage; costs recomputed from a cache-state model; stale-corpus caveat on absolute rates | 12.1, 6.4 | Adopt |
| R2-37 | DeepSeek | Trajectory cohorts randomized at task level (or cluster-robust SEs); IPW/DR claimed only where positivity exists; trajectory evaluation rests on cohorts | 12.1, 12.3 | Adopt |
| R2-38 | DeepSeek | Non-inferiority: minimum class size (merge below it); baseline deployment frozen per study; latency tested with its own smaller sample size; δ≈0 classes explicitly excluded from cheap routing | 11.3 | Adopt |
| R2-39 | DeepSeek | Presence signal carrier: if orchestrators run in the cloud, source subnet never shows office. Presence must derive from authenticated session context (SSO session origin observed server-side, device posture) | 7.1 | Decided: orchestrators run in cloud and lab. Presence = office origin of the human's interactive client connection, observed at the agent framework's authenticated ingress and carried as a signed attribute; lab-hosted orchestrator addresses never count as presence |
| R2-40 | DeepSeek | Lab: admitted requests run to completion within max duration (lease renewal) except background preemption; drain checks destination capacity at T−15; queued requests rerouted at T−10; emergency "drain now" mode; restore lab-as-production security requirement (v0.2 omission) | 7 | Adopt |
| R2-41 | DeepSeek | Risks/mechanisms: ledger reconciliation tolerance + owner + breach action; usage-semantics version alongside price version; shared-prefix cache-write attribution convention; per-client retention as principal attribute in admission; fallback predictor in version-change triggers; evaluation volume as standing cost | 10, 13, 12.4, 17 | Adopt |
| R2-42 | DeepSeek | Retention horizons: non-content feature snapshots (Jev answers, metadata scores) kept ~13 months with ledger; content-derived features (embeddings) 90 days; state effective retraining window | 13.1 | Adopt (resolution proposed) |
| R2-43 | DeepSeek | Ledger is append-only; settlement/reconciliation appends linked revisions | 10.1 | Adopt |
| R2-44 | DeepSeek | Bake-off arm E charged for offline labelling run, amortized | 6.5 | Adopt |
| R2-45 | DeepSeek | Fix §12.4 sequence: canary → regression ⇒ rules-only; pass ⇒ recalibrate → promote | 12.4 | Adopt |
| R2-46 | DeepSeek | Minimum shippable Phase 1a: gateway + attribution (with migration mode) + ledger + reports + deterministic rules classifier; model-assisted classification deferred | 15 | Adopt |
| R2-47 | DeepSeek | Objective covers (routing, recovery) pair: add recovery_policy_version, jointly versioned | 1, 5.3 | Adopt |
| R2-48 | DeepSeek | Fault suite scoped per phase (1b / 4 / 6) | 16 | Adopt |
| R2-49 | GPT-6.1 | Quality approval is part of admission: a destination is eligible only as an approved configuration (model + quantization + adapter + verifier + recovery) for the task class; rules-only fallback uses approved configs; canaries have separately authorized scope | 5.1, 12.4 | Adopt |
| R2-50 | GPT-6.1 | Single final-dispatch check used by every path (ordinary, deterministic fallback, retry, emergency gateway), including current reservation, admission class and valid lease; a plan means "may attempt if still permitted" | 5, 6.7, 7 | Adopt |
| R2-51 | GPT-6.1 | Emergency gateway preserves all of §5.1; distinguish gateway-process vs shared-dependency (Redis/DB/policy store) outages; disable LiteLLM DB-outage fallback-identity behaviour; network policy so agents cannot reach self-hosted model servers directly | 5.4, 14.5 | Adopt |
| R2-52 | GPT-6.1 | Plan bound to principal, task, step revision and request hash (incl. tools, attachments, settings, adapter transforms); expiry/revocation; quality-approval reference; failure-to-action mapping; financial scope covering the bounded chain or requiring fresh atomic reservation | 5.3 | Adopt |
| R2-53 | GPT-6.1 | Trusted request `purpose` (execution, feature extraction, verification, evaluation, replay) with fixed supporting-call policies; no recursive optimization or cascades on supporting calls | 5.1, 5.3 | Adopt — extends R2-13 |
| R2-54 | GPT-6.1 | Single-winner step completion: only the currently authorized attempt may publish a result; late/superseded results accounted but cannot advance the task. Persist dispatch intent before dispatch. Cancellation: requested / confirmed / unknown | 8, 10 | Adopt — extends R2-32 |
| R2-55 | GPT-6.1 | Redefine "verifiable": registered checker evaluating the substantive acceptance condition, with measured false-accept/false-reject rates. Structural guards do not qualify a step | 6.1, 11.1 | Adopt — corrects v0.2 |
| R2-56 | GPT-6.1 | Leaf trajectory: cheap only with an explicit consumption contract (independent verification / advisory-only / approval before consequential action) and the full parent–leaf policy passing the quality gate; isolation is not semantic safety | 6.3 | Adopt — merges with R2-18 |
| R2-57 | GPT-6.1 | Correct cascade cost: E[C] = c_w + c_v + q·E[C_esc], q = escalation probability (verifier decision), distinct from correctness; tail-adjusted version labelled a decision score | 6.2, 6.4 | Adopt — corrects v0.2 |
| R2-58 | GPT-6.1 | Governing metric = E[C_task] / P(accepted), or state the approximation | 1 | Adopt — corrects v0.2 |
| R2-59 | GPT-6.1 | Replay evidence reported separately from live evidence; counterfactual invalid where candidate chooses different tools/args; sandboxes/simulators; idle-lab latency not production evidence | 12.1 | Adopt |
| R2-60 | GPT-6.1 | Positivity over actions, not just sampled requests: randomize among approved experimental actions | 12.1 | Adopt — refines R2-37 |
| R2-61 | GPT-6.1 | Training / development-selection / confirmation splits, grouped by originating task; Jev outputs never become success labels; terminal acceptance not copied onto steps | 11.4, 12 | Adopt |
| R2-62 | GPT-6.1 | Three capabilities with stated windows: accounting audit, decision reconstruction, model re-execution; embeddings inherit content retention; state coverage gap for non-retained workloads | 13.1, 3 | Adopt — refines R2-42 |
| R2-63 | GPT-6.1 | Non-inferiority via one-sided lower confidence bound on paired risk difference (McNemar tests equality — v0.2 error); state sample-size assumptions; pairing benefit not guaranteed | 11.3 | Adopt — corrects v0.2 |
| R2-64 | GPT-6.1 | 500 outcomes = data-readiness threshold, not approval; absolute quality floor / stable reference baseline to prevent cumulative erosion; latency criterion = P(T ≤ D) | 6.3, 11.3 | Adopt |
| R2-65 | GPT-6.1 | Fix phase contradictions: budget enforcement "every phase" vs 1b; reconciliation in both 1a and 1b; minimal acceptance protocol + baseline cohort moved to Phase 0 (Phase 2 needs it); Phase 3 replay pool evaluation-only | 15 | Adopt |
| R2-66 | GPT-6.1 | Phase 1a guarantees stated explicitly: fixed requested destinations, no substitution, which financial controls are enforced; hard-ceiling workloads wait for 1b | 15 | Adopt (modified: onboard progressively to 100%, not pilot-only) |
| R2-67 | GPT-6.1 | Fault tests: plan reuse after mutation/revocation; schema-valid-but-wrong leaf; duplicate/late completion; delayed cancellation ack; shared-state outage; supporting-call recursion; evaluation-data reuse | 16 | Adopt |

## Round 3 (v0.3) — proposed changes

| # | Source | Change | Section | Status |
|---|---|---|---|---|
| R3-1 | Grok | State explicitly: final-dispatch check evaluates current classification; `classification_snapshot` is audit-only | 5.3, 5.4 | Adopt (clarification) |
| R3-2 | Grok | Define `request_hash` canonicalization: semantic content only; exclude trace IDs, timestamps and other non-semantic metadata | 5.3 | Adopt — amended by R3-9 (hash pre-adapter, not adapter output) |
| R3-3 | Grok | Fault test: forged or unsigned office-origin attribute rejected | 16 | Adopt — gap in v0.3 suite |
| R3-4 | Grok | Contingency if LiteLLM verification fails in Phase 1a: thin custom admission layer in front of LiteLLM, or alternative gateway — decided before Phase 1a starts | 15 | Adopt |
| R3-5 | Grok | Name approved-configuration registry owner and canary→approved promotion process before Phase 3 | 18 | Adopt (already in §18 owners; add process) |
| R3-6 | Grok | Guard: routing code reads only the incremental cost view | 10.5 | Adopt (minor) |
| R3-7 | Grok | Orchestrator restartable step boundary flagged as highest gateway↔agent-team coordination item (Phase 4) | 8, 15 | Adopt (note) |
| R3-8 | Gemini | Gateway response cache (if enabled) runs only after mandatory admission, key salted with security domain, classification level and quality-approval ref; cache hits recorded in ledger | 5, 10 | Adopt — real bypass path |
| R3-9 | Gemini | `request_hash` over canonical pre-adapter payload + adapter-map versions; hashing adapter output contradicts per-candidate adapters (v0.3 internal inconsistency) | 5.3 | Adopt — corrects v0.3 |
| R3-10 | Gemini | Single-winner completion implemented as compare-and-swap in the orchestrator's state store; no separate consensus service | 8.4 | Adopt (implementation note) |
| R3-11 | Gemini | Signed office-origin attribute has 8–12 h TTL bound to session (bounds stickiness); ingress reads client IP only from trusted edge, never client-supplied forwarding headers | 7.1 | Adopt |
| R3-12 | Gemini | Ledger availability: managed HA database primary; replicas may persist dispatch intent to a local durable WAL on persistent volume during brief outages, bounded window, async flush; WAL unavailable ⇒ fail closed | 5.4, 10.1 | Adopt (with constraints) |
| R3-13 | Gemini | Leaf validation via message-block lineage IDs / turn-count bounds, not substring matching; requires block IDs in instrumentation contract | 6.1, 9 | Adopt |
| R3-14 | DeepSeek | Plan signed by the optimization layer (keyed MAC/signature); FDC verifies signature first | 5.3, 5.4 | Adopt — Phase 1a |
| R3-15 | DeepSeek | FDC checks plan's policy_version and recovery_policy_version match current, else replan | 5.4 | Adopt — Phase 1a |
| R3-16 | DeepSeek | FDC explicitly part of the emergency gateway's contract; any gateway incl. future lab replica runs the identical FDC | 5.4, 14.2 | Adopt (clarification) |
| R3-17 | DeepSeek | Plan carries validated task_class and step_class (1a); minimum_tier and originating_step_id for escalation attempts (Phase 4) | 5.3, 6.2 | Adopt |
| R3-18 | DeepSeek | References in request_hash: versioned references hash reference + content version; unversioned references must be materialized and hashed | 5.3 | Adopt |
| R3-19 | DeepSeek | Single-winner store = orchestrator state store (CAS), independent of gateway availability; owned by orchestrator team | 8.4 | Adopt — converges with R3-10 |
| R3-20 | DeepSeek | Escalation allowance exhausted ⇒ return to orchestrator for decision (fail step / abandon task); does not consume failure-retry budget | 6.2 | Adopt |
| R3-21 | DeepSeek | Adding or changing a verifier changes step classification ⇒ policy change subject to §12.4 canary/confirmation gate | 6.1, 12.4 | Adopt |
| R3-22 | DeepSeek | Presence attributed at the first trusted edge facing the human; when a web backend proxies to the agent framework, the web tier's edge observes and signs origin and the attribute propagates; otherwise presence unavailable (stated limitation) | 7.1 | Adopt (refined) |
| R3-23 | DeepSeek | Ingress signing-key management: storage, rotation, who can mint, verifier key distribution | 7.1 | Adopt — Phase 1a |
| R3-24 | DeepSeek | Sample-size arithmetic applies to confirmation set; off-policy target restricted to approved experimental actions (stated limitation); fallback predictor promotion follows same gate | 11.3, 12.1, 12.3, 12.4 | Adopt |
| R3-25 | DeepSeek | Ledger build fallback: simpler append-only log with the same interface acceptable for 1a; reconciliation layer can follow | 15 | Adopt — combines with R3-12 |
| R3-26 | DeepSeek | Classification rules engine: owner, labelled test corpus, minimum bar — set both false-negative (missed sensitive content) and false-positive ceilings | 5.1, 15 | Adopt (refined: FN bar matters most) |
| R3-27 | DeepSeek | Binary exit criteria: 1a = all traffic authenticated and attributed to a principal, non-compliant share reported; full instrumentation-contract compliance = Phase 2 exit (optimization needs it) | 15 | Adopt (modified) |
| R3-28 | DeepSeek | Define the recovery policy artifact (contents, owner, versioning, promotion) — new §6.8 | 1, 6.8 | Adopt |
| R3-29 | DeepSeek | Approved-configuration registry lifecycle: addition, evidence, approver, revocation, coordination with policy_version | 4.1, 5.1.8 | Adopt — merges R3-5 |
| R3-30 | DeepSeek | Reconciliation breach is tracked and adjudicated, not stop-the-world | 10.6 | Adopt |
| R3-31 | DeepSeek | Add `judging` purpose | 5.1.4 | Adopt |
| R3-32 | DeepSeek | Spine sessions: lease renewal per attempt; capacity denominator accounts for long-lived spines | 6.7 | Adopt |
| R3-33 | DeepSeek | Quadrant spend-share threshold with consequence (e.g. trajectory-spine > 50% ⇒ Phase 3–5 targets re-scoped) — consequence gates Phase 3, not Phase 1a | 10.7, 15 | Adopt (modified) |
| R3-34 | DeepSeek | decision_record lives in the ledger | 13.1 | Adopt |
| R3-35 | GPT-6.1 | Reservation-owner leases may expire; financial exposure of dispatched/outcome-unknown attempts persists until settlement, proof of non-execution, or conservative accounting at the authorized maximum. Same for capacity: reclaim only on confirmed completion/cancellation, not on failover. Recovered budget state must include outstanding exposure before admission resumes | 6.7, 8.3, 10.4, 5.3 | Adopt — corrects v0.3 (TTL release contradiction); highest priority runtime fix |
| R3-36 | GPT-6.1 | financial_scope bounds total authorized charge (input + all billable components), not just output tokens; request types without boundable exposure excluded from hard-ceiling workloads | 5.3, 10.4 | Adopt |
| R3-37 | GPT-6.1 | Explicit Phase 1a admission profile: fixed destinations; documented 1a budget controls (not atomic reservation); initial approved-configuration list as a version-controlled file; exit = 100% of the eligible onboarding cohort (workloads needing hard ceilings wait for 1b) | 5.1, 15 | Adopt — resolves v0.3 contradictions (registry in Phase 3; "every phase" budget) |
| R3-38 | GPT-6.1 | Migration mode tolerates only accounting/analytic metadata gaps; never bypasses identity, destination authorization, purpose, source classification or retention | 5.1.2 | Adopt |
| R3-39 | GPT-6.1 | Phase 1a acceptance tests: invalid identity, forbidden destination, missing taint, ledger unavailable, prohibited content in telemetry | 16 | Adopt |
| R3-40 | GPT-6.1 | Derived features inherit source handling and retention unless an approved feature schema permits longer retention (v0.3 blanket "non-content" exemption for Jev answers/scores was wrong) | 13.1 | Adopt — corrects v0.3 / R2-42 |
| R3-41 | GPT-6.1 | Retention enforced at every persistence boundary: traces, exception logs, exporter queues, feature caches, eval stores; allowlisted telemetry schema with redaction from Phase 1a | 13.1, 10 | Adopt |
| R3-42 | GPT-6.1 | Handling policy combines all applicable client-specific restrictions, not just max sensitivity level | 5.1.3, 5.1.11 | Adopt |
| R3-43 | GPT-6.1 | Two-level binding: canonical-work hash (pre-adapter, per R3-9) + candidate prepared request derived deterministically; FDC validates the final prepared request after all callbacks/adapters | 5.3, 5.4 | Adopt — merges R3-9, R3-18 |
| R3-44 | GPT-6.1 | Identity levels: logical step+revision / execution generation (authorized invocation, new on escalation) / provider attempt. Idempotency keyed by execution generation so escalation isn't deduplicated into the rejected result. Candidate delivery ≠ acceptance; acceptance transition owned by orchestrator after verification | 8.2, 8.4 | Adopt — corrects v0.3 (per-step idempotency key would dedupe escalation) |
| R3-45 | GPT-6.1 | Define authorization point and effect of revocation on admitted-but-untransmitted attempts; test it | 5.4 | Adopt |
| R3-46 | GPT-6.1 | Tier 1 wording: gateway may retry same deployment, or use permitted leaf fallbacks; any identity change on spine returns an escalation request to the orchestrator | 6.2 | Adopt — corrects v0.3 inconsistency with §6.6/§8.1 |
| R3-47 | GPT-6.1 | Leaf validation via orchestrator construction manifest (registered step definition, selected inputs/dependencies); gateway validates manifest, labels, binding | 6.1, 9 | Adopt — converges with R3-13 |
| R3-48 | GPT-6.1 | Origin attribute bound to issuer, gateway audience, principal, session, validity; never carried in OTel baggage | 7.1 | Adopt — extends R3-11/R3-23 |
| R3-49 | GPT-6.1 | Remove "p_s ≈ 1 because baseline" justification; simplified rule only where omitted baseline failure/recovery terms are empirically immaterial | 6.4 | Adopt — corrects v0.3 |
| R3-50 | GPT-6.1 | Generalized cascade quality: q = p_w·f + (1−p_w)·d; P(correct) = p_w(1−f) + q·r | 11.1 | Adopt — corrects v0.3 |
| R3-51 | GPT-6.1 | Pooled gating: predeclared grouping; state the class level at which approval is established; underpowered no-harm ≠ per-class qualification | 11.3 | Adopt |
| R3-52 | GPT-6.1 | Analysis matches design: paired for replay, two-arm (cluster-aware) for randomized cohorts | 11.3 | Adopt — corrects v0.3 |
| R3-53 | GPT-6.1 | Common (or balanced) judge per comparison with frozen rubric; judge family differs from all candidates in that comparison | 11.2 | Adopt — reconciles with R2-20 |
| R3-54 | GPT-6.1 | Latency study gets separately justified sample size (not necessarily smaller); δ≈0 exclusion is a risk policy (δ=0 requires superiority), not impossibility | 11.3 | Adopt — corrects v0.3 |
| R3-55 | GPT-6.1 | Change triggers include verifiers, recovery/escalation rules, thresholds, consumption contracts, judge/rubric (measurement review) | 12.4 | Adopt — extends R3-21 |
| R3-56 | GPT-6.1 | Mutating corpus: paired validity requires controlled common environment or recorded responses | 12.1 | Adopt |
| R3-57 | GPT-6.1 | Rule: each fault test is an entry/exit requirement for the first phase relying on its guarantee (move outcome-unknown to 1b, predictor change to 5, confirmation isolation to 3) | 16 | Adopt — corrects v0.3 |

## v1.1 (16 Oct 2026) — internal update from the competitive landscape review

Not externally reviewed. Source: *Duranki — Competitive Landscape* (16 Oct 2026) and Larry's decisions of 16 Oct.

| # | Source | Change | Section | Status |
|---|---|---|---|---|
| V11-1 | Larry | System named Duranki; agents Neti, Ninshubur, Nisaba, Shamash, Nabu added to the design | §0, §4.1, §4.2, Fig. 1 | Done |
| V11-2 | Larry / landscape | Off-the-shelf (COTS) products named per component with status: decided, candidate, open, existing, build | §4.1 | Done |
| V11-3 | Landscape (LiteLLM PyPI compromise, Mar 2026) | Supply-chain controls: pinned hash-verified builds, own images, soak period, egress allowlist, secrets manager and rotation, SBOM, fail closed on suspicion | §4.4, §15 (1a), §16 tests 37–41 | Done |
| V11-4 | Landscape (LiteLLM Auto Router v2, Jul 2026) | LiteLLM built-in routing disabled; only the optimization plugin routes, within the signed plan; FDC rejects unnamed deployments | §4.3, test 40 | Done |
| V11-5 | Landscape (Portkey acquisition, TensorZero shutdown) | New risks: compromised COTS release; vendor acquisition or shutdown; built-in routing overriding the plan | §17 | Done |
| V11-6 | Landscape | LiteLLM contingency widened to cover compromise and acquisition/licence change; supply-chain owner; soak period and ledger database product added as open decisions | §18 items 6, 7, 9, 10 | Done |
| V11-7 | Larry | Phase 3 bake-off kept as is (internal predictor comparison, not outside products) | §6.5 | No change |
| V11-8 | Landscape | Competitor comparison against outside routers proposed, then withdrawn: no bake-off against products until Duranki exists | — | Withdrawn |
| V11-9 | Build | Docx: emblem drawings for each agent and a title banner (Appendix A); photographs of artefacts to follow when supplied | docx only | Done |

Test numbering note: the new Phase 1a tests are numbered 37–41, after the v1.0 list, so existing references to tests 1–36 stay valid.

Build note: v1.0's docx build applied its section page breaks to "Heading 1" while sections are "Heading 2", so the intended breaks never fired. Fixed in the v1.1 build; layout only.

## Pushed back / low value
- Grok: clock skew affecting drain window — NTP plus a generous drain window makes this negligible.
- Grok: cache affinity across lab/cloud boundary — already covered by stickiness; sessions only move on forced re-route.

## Decision status (15 Oct, 14:21)
- Presence (#30): intent = in-office developers get the lab as their natural primary endpoint. Proposed: presence is a priority/preference, not hard eligibility — two admission classes (office interactive = priority; remote/batch/replay = background, admitted only at lower load, preemptible).
- Equal quality (#9): open — proposed non-inferiority framework on task acceptance, margin per task class; Larry to set margins and high-consequence classes.
- Prompt retention (#15): recommendation given (tiered by sensitivity) — awaiting confirmation.
- Residency: no current requirement. Mach33 is US-based; many staff are contractors to it. US regions are eligible (wider GPU/model availability). Keep residency as a capability-filter attribute for future client terms. Flag export-control (ITAR/EAR) check if any work touches controlled technical data.

## Decisions needed from Larry (original list)
- Quality bar and test for "equal quality" (#9)
- Prompt retention period and access (#15)
- Will lab pools run quantized models? (affects #6; Gemini flags the same risk)
- What does the office-presence rule protect? Proposed split: presence gates interactive sessions; batch/eval/replay workloads use the lab freely when not reserved (#30)

## Pushed back (Gemini)
- "Baselines will capture 90%+ of Jev's lift" is a prediction, not evidence — the bake-off decides.
- Fail-open passthrough as proposed would bypass data classification; must fail closed for sensitive traffic.
- Counterfactual replay gives clean paired labels only for leaf/verifiable steps; trajectory steps can't be replayed faithfully without recorded tool outputs (and live tools have side effects).

## Pushed back (DeepSeek)
- vLLM/SGLang affinity claims are muddled: agent spines are append-only, so session and prefix affinity largely coincide there. Real fix is #32, not replacing session stickiness wholesale.
- Full contextual bandit from the start — no (Grok and Gemini agree); replay + uncertainty-driven exploration covers it.
- Calendar/badge presence signals — added complexity; depends on #30 decision.
- Claim that LiteLLM has a plugin pipeline that enriches routing context — unverified; verify hook capabilities during Phase 1 license/feature review (#10).
- Uncited "recent work confirms" statements — treat as unsupported.

## Pushed back (GPT-6.1)
- Mostly none on substance. Caution: its Phase 1 gate (budget concurrency tests, reconciliation, trusted attribution) risks making Phase 1 too heavy to ship fast. Split Phase 1 into 1a (door + attribution + classification + ledger) and 1b (budget reservation, reconciliation, fault tests).

## Pushed back (Gemini, round 2)
- Replay survivorship bias is real but bounded: while the spine stays on the strong model in production, replayed leaf inputs match live leaf inputs. Bias appears when spine policy changes — so re-baseline replay labels whenever spine routing changes.
- Pooling task classes for gating can hide a regression in one class; pooled gate must be paired with per-class harm monitoring.
- "Freeze as v1.0 now": not yet — fold round 2 into v0.3, then baseline. Phase 0 can start immediately regardless.

## Pushed back (DeepSeek, round 3)
- "Budget clause missing from v0.3 error table": it is present (row 2), but cites §5.1.9 — budget is §5.1.10. Fix the reference.
- Web presence gap is narrower than stated: an edge in front of the user's browser does see the client IP. The gap exists only where a web backend proxies to the agent framework. Resolved by R3-22.
- Quadrant threshold should gate Phase 3–5 scoping, not Phase 1a — metering is valuable regardless of the savings ceiling.

## v0.3 errors identified in round 3
- request_hash covered adapter output while fallbacks carry per-candidate adapters (Gemini)
- Gateway response cache not placed after admission (Gemini)
- References treated as content-bound in request_hash (DeepSeek)
- Error table cites §5.1.9 for budget; correct is §5.1.10 (DeepSeek, corrected)
- Budget reservation TTLs release exposure of dispatched/outcome-unknown work; lease "released on failover" contradicts §6.7 (GPT-6.1)
- Mandatory admission "every phase" contradicted by Phase 1a/1b budget split; approved-configuration registry mandatory but scheduled for Phase 3 (GPT-6.1)
- Derived features (Jev answers, scores) treated as non-content despite inheritance rule (GPT-6.1)
- Per-step idempotency key would deduplicate an authorized escalation into the rejected result (GPT-6.1)
- Tier 1 "escalate within the plan" inconsistent with orchestrator ownership of identity changes (GPT-6.1)
- "p_s ≈ 1 because baseline" unjustified (GPT-6.1)
- Cascade quality equation omitted false rejection (GPT-6.1)
- Paired analysis required universally, including two-arm cohorts (GPT-6.1)
- Latency sample size asserted smaller; δ≈0 called mathematically impossible (GPT-6.1)
- Fault tests scheduled after the phase that relies on them (GPT-6.1)

## v0.2 errors identified in round 2
- Gateway claimed to classify assembled-request content it cannot see provenance for (Gemini)
- Budget fail-closed softened by "explicitly configured policy" clause (DeepSeek)
- Lab-as-production security requirement dropped from v0.1 (DeepSeek)
- Schema validity allowed to qualify a step as "verifiable" (GPT-6.1)
- Cascade cost put verifier cost only in the failure branch (GPT-6.1)
- Objective (expected cost) mismatched with metric (cost per accepted task) (GPT-6.1)
- McNemar named as a non-inferiority test; it tests equality (GPT-6.1)
- "Every decision is reconstructable" overclaimed relative to retention (GPT-6.1)
- Phase contradictions: budget reservation in every phase vs 1b; Phase 2 needed an eval set not built until Phase 3 (GPT-6.1)

## v0.1 errors identified across reviews
- Router timeout 150 ms inconsistent with Jev 70–500 ms (Gemini)
- Classification introduced in Phase 4 while gateway live in Phase 1 (GPT-6.1)
- "parent_trace_id" not OTel-correct (GPT-6.1)
- Lab "headroom below admission threshold" wording inverted (GPT-6.1)
- Marketplace residency claim overstated (GPT-6.1)
- Overflow chain assumed fast cloud GPU scale-up (Gemini)
