DURANKI INTEGRATION READINESS — CORRECTION 02

Complete the narrow residual corrections from Independent Review 02. Preserve the working v2 design and the closures already achieved by Correction 01.

The reviewed final reference is 79997c469d404f10bc60d8cf28bd48c7447f8db8, with product/client source through 4462269b190acd3e0deacedfd65eb46aca48058f. Inspect the actual current approved branch and worktree; do not reset newer work or disturb unrelated owner files.

PLAN CHECKPOINT

Read applicable repository guidance, the existing readiness plan/progress, Correction 01 and the attached Independent Review 02.

Save this commission in docs/plan/DURANKI-INTEGRATION-CORRECTION-02.md. Link it from the existing readiness plan and track IC02-01 through IC02-05 in the progress record. Preserve historical executor claims while distinguishing independent acceptance.

Keep IR01–IR03, IR05 and IR06 closed for the reviewed scope. Preserve the substantive IR04 usage/cost fix; add only its missing projection state. IR07–IR09 remain partial for the specific residuals below.

Commit the plan checkpoint, then continue implementation. Reread plan/progress after session restart or compaction. Routine decisions do not require approval; do not return a documentation-only completion.

IC02-01 — CONSISTENT LINEAGE IN BOTH ARRIVAL ORDERS

Reproduced failure: orphan lineage with logical.original receives 201; later start for the same attempt with logical.conflicting also receives 201; a matching predecessor subsequently receives 409. A separate lineage can overwrite an explicitly initial role with fallback, contrary to the unknown-start enrichment contract.

Validate incoming starts against existing lineage immediately, even without the predecessor. Validate incoming lineage against the existing start. Enforce unknown-only enrichment and immutable task/logical/role bindings. Do not silently rewrite explicit start facts.

Test both delivery orders, valid unknown enrichment, explicit-role and logical conflicts, late predecessors, cycles, scope isolation, duplicates and once-only charges. Existing incompatible records must not be rendered as trustworthy links.

IC02-02 — ELIGIBILITY ORDERING WITHOUT ARRIVAL-TIME BIAS

Reproduced failure: a usable answer and pre-disable decision share the contract's second-resolution timestamp with a later disable. Immediate decision delivery succeeds; the delayed first delivery of equivalent valid evidence fails 400/never because the service chooses the highest revision at the tied timestamp.

Represent enough ordering to support the historical verdict, or retain the observation and referenced answer with an explicit indeterminate assessment when ordering is unavailable. Keep the caller's reported evidence distinct from the service's established assessment.

Do not fix this by fabricating timestamps, changing valid evidence to stale, trusting an unverified claim as proven, or forcing synchronous telemetry. Preserve malformed/foreign-account/model/dataset rejection and actual stale/denied evidence.

Test immediate versus delayed delivery, a later mutation in the same second, unambiguous stale/denied cases and duplicate receipt recovery. Make any necessary compatible schema/response clarification explicit across contract, service, both clients and exports.

IC02-03 — COMPLETE SNAPSHOT REFERENCE BINDING

Reproduced failure: feature.a belongs to attempt.a, but attempt.b can reference it as both context_ref and decision_ref. Both references are accepted and the report calls both captured, despite the snapshot belonging to another attempt and being feature-kind only.

Bind every reference by dataset, attempt, expected kind and snapshot ID. Enforce constraints whether an event or snapshot arrives first, including previously unresolved reference claims. Reject incompatible bindings before committing them. A genuinely absent reference may remain pending/missing; an incompatible one must never project as captured.

Make reporting/export robust to already-accepted mismatches without changing their immutable history or inventing new bindings. Preserve snapshot integrity, authorization, expiry and restoration.

Test foreign-attempt reference, wrong-kind reference, both arrival orders, valid same-attempt snapshots, missing targets, conflicting reuse and expired snapshots. Exercise JSON, CSV where applicable, dataset export and both installed clients.

IC02-04 — EXPLICIT NATIVE-USAGE STATE IN REPORTS

Add a documented usage_state or equivalent field to v2 JSON and CSV. Keep it separate from cost_status and define known, unknown, not-observed and legacy behavior accurately. The state must agree with the effective contiguous usage event in dataset export.

Cover known usage/unknown cost, unknown usage/known cost, both known, both unknown and absent usage. Preserve known units, explicit zero and once-only monetary totals.

IC02-05 — EXACT REVIEW-MANIFEST COVERAGE

Fix the packager to exclude only the root MANIFEST.sha256 path. Include the nested retained/final-release/MANIFEST.sha256. Verify exact equality between manifest payload paths and all other archive files, not just that listed hashes pass. Preserve the original packet as evidence. This packaging cleanup requires no unrelated product rerun.

RELEASE AND EVIDENCE

Use normal authenticated local HTTP and clean consumers installed from the exact newly built service and client artifacts. Preserve v1 compatibility and accepted records. Keep v2 where the correction is compatible; document any required schema addition and package-version change explicitly. Do not silently change released artifact bytes.

Run the existing focused suite as regression coverage and add the bounded cases above. Retain fresh command/runtime records, actual outputs and failures, representative responses, JSON/CSV/export, independent arithmetic, restart/restore results and exact artifact hashes. Verify corrected installed behavior, not only source imports. Test upgrade/readability of retained v1/v2 data and accepted mismatches affected by these changes.

Return a compact self-auditing review bundle containing the focused source delta, updated plan/progress/result, exact release identity and retained evidence. Do not include dependency trees, old DEV-12 packets or regenerate old missing evidence.

Keep the existing feature-retention policy PROPOSED unless Larry separately adopts it. Its approval belongs before real T0 and must not stall these synthetic corrections. No dataset reset, historical backfill, model routing, real provider access, paid execution, owner-profile change, production deployment or new DEV-12 campaign is authorized by this commission. Preserve CT02-02b OPEN.

Declare READY_FOR_VEGA_PLATFORM_INTEGRATION only when IC02-01–IC02-04 are implemented and verified through the corrected installed release, the review manifest is complete, and the existing readiness criteria still hold. Distinguish software readiness from the pending real-retention policy and subsequent Vega instrumentation/exporter/eligibility-enforcement milestone.

Start with the plan checkpoint and continue through the corrected release. Return the scoped commits, exact artifacts, case-to-evidence mapping, any concrete remaining blocker and the next Vega integration action.

