DURANKI INTEGRATION READINESS — CORRECTION 01

Implement one focused successor release that closes the findings below and completes the existing Integration Readiness plan. This is implementation work, not a request for another design-only return.

STARTING POINT AND REPOSITORY RECORD

Read repository guidance, docs/plan/DURANKI-INTEGRATION-READINESS.md, docs/plan/DURANKI-INTEGRATION-PROGRESS.md, the attached Independent Review 01, and the current source. The reviewed final reference is 4ffe57e6c257b136ef9267afa9b9334c9023f9de; use the actual approved current baseline without resetting newer work.

Save this commission at docs/plan/DURANKI-INTEGRATION-CORRECTION-01.md. Add a scoped correction reference to the existing readiness plan and map IR01–IR09 into the progress record with source paths, tests, evidence and next action. Preserve the original acceptance criteria and historical release findings. Record the current disposition as correction required; preserve the earlier executor READY claim as history.

Commit the plan checkpoint and continue implementation. Reread plan/progress at session start, after compaction and before declaring readiness. Resolve routine engineering choices autonomously; do not insert approval gates between stages.

SCOPE AND VERSIONING

Publish an explicit contract v2 and compatible new service/JavaScript/Python package versions. Preserve v1 artifacts and historical data; document migration, v1 compatibility and legacy-field absence. Do not overwrite released package bytes or silently pretend old observations contain new fields.

Use the existing @mach33/duranki-client and mach33-duranki-client packages. Private tarballs/wheels suffice. Keep the accounting-only boundary, authenticated dataset/owner scope, once-per-attempt effective accounting, explicit unknowns, fresh activation membership, and separation of pre-call facts from later observations.

No real provider calls, commercial spend, owner-profile changes, production deployment, hosted-registry provisioning or repeated DEV-12 sender campaign is part of this commission. CT02-02b remains OPEN. Use disposable synthetic fixtures. Preserve unrelated owner files and existing branch/push rules.

REQUIRED CORRECTIONS

IR01 — Typed timestamp validation
Stop treating arbitrary strings containing uppercase T and ending in Z as timestamps. Accept contract-valid IDs such as event.TimeZ. Validate actual timestamp fields for valid calendar/time values. Demonstrate parity across HTTP and both clients.

IR02 — Encoded identifier routes
Make colon-containing IDs work through both clients and the operator UI for account eligibility, receipt recovery and account-state change. Decode the intended path segment exactly once, then validate the ID. Test malformed encoding and forbidden separators. Do not narrow the published identifier grammar to hide the bug.

IR03 — Outcome projection robustness
The current service accepts an outcome activity without an outcome value, then its report returns 503/KeyError. Align successor admission rules and projection, and safely report already-accepted legacy missing-outcome records as explicitly absent/unknown. Do not invent outcomes or make a whole dataset unreportable. Exercise JSON and CSV.

IR04 — Independent usage and cost knowledge
Retain known native units when monetary cost is unknown. Define the converse when cost is known but native details are unavailable. Keep explicit missing/unknown/zero semantics, provenance and append-only revisions. A later cost revision must count once and preserve known usage. Apply the representation consistently to schemas, service, clients and exports.

IR05 — Accounting coverage for unresolved or ineligible accounts
An authorized platform observation must remain recordable when its reported account reference has not been registered. Store it as unresolved in the authenticated dataset/owner; flag it in reports. Do not auto-create a usable account, manufacture credentials, resolve another owner's account, or relax authorization.

Retain observations of already-executed disallowed/disabled-model work with appropriate selection-time evidence or an explicit unknown status. Current account state is not proof of past policy violation. Later account resolution must preserve the original reported identity.

IR06 — Operation identity
Add a bounded, versioned operation family that can represent the platform's relevant generation, embedding, speech, search, realtime and other used operations. Include explicit unknown/other handling. Represent a genuinely model-less operation without a fictitious model ID. Consult the actual local platform inventory if available; do not claim the quoted Proto counts as verified without inspecting it.

IR07 — Retry and fallback lineage
Represent logical operation and causal retry/fallback relationships separately from distinct attempt IDs and parallel fan-out. Preserve each attempt's charge. Define late predecessor handling; reject self-links, cycles and cross-dataset links. Leave missing legacy lineage explicit rather than guessing.

IR08 — Eligibility decision evidence
Bind decisions to the actual immutable eligibility response/revision used, with account/model, returned decision, policy and relevant times. Make the binding verifiable; distinguish missing, stale or bypassed evidence. Export it with the selected action. This records evidence; Vega's actual enforcement is qualified during integration.

IR09 — Durable feature and decision snapshots
Replace identifier-only promises with a bounded, versioned, retrievable/exportable feature-and-decision record. Preserve identity, schema/producer version, provenance, source/availability time and integrity where policy permits.

Keep pre-call features, selected action and post-call observations separate. Include selected action/eligibility evidence in the dataset export. Define explicit unavailable/expired/not-collected states. Do not disguise later outcomes as pre-call features.

Implement a concrete field allowlist rather than arbitrary metadata. Initial candidates are application-defined task/operation categories, modalities, measured or estimated input-size features with provenance, requested output/latency/capability constraints, and versioned agent/policy/configuration identity. Raw prompts/responses, audio/media, free-form payloads, content embeddings, credentials and secret-bearing URLs are outside this initial accounting store.

RETENTION POLICY

Read the applicable adopted architecture and current owner decisions. Its retained-feature rule requires approval for longer retention than inherited source policy; numeric defaults in the inspected architecture still require confirmation.

Produce docs/plan/DURANKI-INTEGRATION-FEATURE-RETENTION-POLICY.md with exact fields, purposes, classification, retention duration/expiry, permitted readers/exporters and restoration/deletion behavior. Mark any unapproved choices as proposed.

Implement the policy-bound machinery and qualify it with synthetic fixtures now. Proposed accounting/approved-feature horizon is approximately 13 months, subject to actual adopted policy and client/classification limits; this proposal is not live-data approval. Keep raw-content ingestion off. Hashes are not automatically exempt from source policy.

Do not stop the correction implementation waiting for live-data approval. Return the concrete policy for Larry to adopt before real T0 activation. Treat that activation decision separately from readiness of the tested software interface.

Append-only history permits later versioned enrichment of included attempts when source facts are available. Preserve the no-pre-activation-backfill rule and the future dataset across deployments; do not reset or fabricate historical features.

IMPLEMENTATION AND VERIFICATION

Fix the reproduced correctness failures and establish the successor contract, then implement service and clients in parallel where useful. Keep all schema copies and response validation aligned. Test meaningful behavior through normal authenticated HTTP and the exact installed new packages, not just source imports.

Required focused cases:
- Legal timestamp-like and colon-containing IDs through both clients and operator routes.
- Invalid real timestamps and invalid path encodings.
- Missing-outcome legacy records cannot break reports.
- Known units/unknown cost, explicit zero, later cost evidence, duplicates and revision gaps.
- Unregistered accounts, disallowed models, late accounting after disable and cross-owner reference isolation.
- Different operation families and model-less operations.
- Retry/fallback versus fan-out, late links, invalid cycles and once-only rollups.
- Selection-time eligibility evidence differing from current account state.
- Feature snapshot integrity, pre/post separation, authenticated export and policy expiry.
- Existing authorization, out-of-order, restart, upgrade and backup-restoration behavior.

Retain fresh compact evidence from the exact successor artifacts: command/runtime identity, actual outputs and failures, case/result correspondence, representative HTTP responses, JSON/CSV, independent arithmetic, restart/restore outputs, and artifact hashes. Retain evidence as each case runs. Label these as new successor checks; do not recreate missing v1 historical outputs.

Provide a small self-auditing review bundle without dependency trees or old campaign packets. Update the plan/progress and final disposition. READY_FOR_VEGA_PLATFORM_INTEGRATION requires implemented IR01–IR09, passing relevant installed-release cases, a usable local release and accurate remaining limitations. The real retained-feature policy and dataset activation may remain explicitly pending owner adoption for the following integration milestone.

Return the scoped commits, exact artifact identities, plan-to-evidence correspondence, remaining decisions and the next concrete Vega integration step. Start with the repository plan checkpoint and continue through the corrected release.

