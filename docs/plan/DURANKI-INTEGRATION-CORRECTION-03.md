DURANKI INTEGRATION READINESS — CORRECTION 03

Close the single residual IC03-01 from Independent Review 03: an accepted conflicting lineage can prevent unrelated new attempts from being recorded. Preserve the working 0.2.1 design and all other independent closures.

Reviewed final reference: d3d533a47c3addcc503c2d6b6ba0c06bb0340b9d.
Tested product/client source: c8433bb9388a9503d814929a780c6840ee63396c.

Inspect the actual approved branch and worktree. Do not reset newer work or disturb unrelated owner files.

PLAN CHECKPOINT

Read applicable repository guidance, the current readiness plan/progress, Correction 02 and the attached Independent Review 03. Save this commission as docs/plan/DURANKI-INTEGRATION-CORRECTION-03.md, link it from the existing plan and track IC03-01 against the still-partial IC02-01 / IR07.

Keep IC02-02 through IC02-05 closed. Preserve IR01–IR06 and the now-reviewed IR08/IR09 closures for their stated local scope. Preserve the direct v2 lineage repairs and safe historical projections already achieved. Keep earlier executor claims as history, clearly separate from independent acceptance.

Commit the plan checkpoint, then continue implementation and release. Reread the plan/progress after restart or compaction. Routine implementation decisions do not require another approval. Do not return a documentation-only completion.

THE ONE REMAINING DEFECT

A. A contradictory orphan lineage and start accepted through normal HTTP by 0.2.0 remain readable under 0.2.1 and are correctly marked binding_conflict. However, a new unrelated task/run/logical operation in that dataset returns 409 EVENT_CONFLICT with retry_guidance=never.

B. The condition is also reachable in a fresh 0.2.1 dataset: v2 orphan lineage returns 201; v1 start for the same attempt returns 201; an unrelated v2 start then returns 409. Reversing the first two requests correctly rejects the lineage with 409. A separate clean v2-only dataset still accepts work.

Cause: append_event invokes lineage validation only for v2 starts/lineage, so a v1 start bypasses pending v2 constraints. The lineage validator subsequently revalidates every retained component and lets an unrelated old conflict veto capture.

REPAIR BOUNDARY

1. Enforce relevant existing/pending lineage constraints consistently for compatible event versions, in both arrival orders. Reject incompatible bindings before committing them. Preserve valid v1 behavior and the immutable meaning of its absent logical/role fields; do not invent those facts.

2. Keep accepted historical conflicts explicit and unchanged, while permitting unrelated valid new observations in the same dataset. Validate the proposed event and its affected relationships, or use an equivalent rule that rejects new violations without re-rejecting unrelated historical ones.

3. Preserve current identity, task, cross-dataset, cycle, self-link, unknown-only-enrichment, duplicate and once-only accounting protections. An event touching an inconsistent component must not be silently accepted as a trustworthy link.

Do not delete accepted rows, reset the dataset, rewrite event bodies/digests, relabel explicit roles, weaken authorization or remove v1 compatibility to make the tests pass.

FOCUSED PASS CONDITIONS

- The exact fresh mixed-version lineage-first sequence cannot commit an incompatible binding. The reverse order has consistent semantics. Following each rejected conflict, a valid unrelated v2 start is accepted.
- A copied fixture of contradictory history genuinely accepted by 0.2.0 remains readable, unchanged and marked binding_conflict; the corrected installed service can ingest unrelated new work into that SAME dataset.
- Valid v1 ingestion without conflicting lineage still works. Valid pure-v2 lineage works in both orders. Late predecessors, logical/task conflicts, unknown enrichment, explicit-role rejection and cycle/scope protections retain their behavior.
- Duplicate submissions and receipt recovery preserve accepted identities; retries do not add attempts or cost. Reports/exports distinguish old conflicts from valid new work and reconcile the expected census and effective costs.
- A separate clean v2-only dataset remains a positive control. Do not use moving to a new dataset as the repair for continued ingestion in an affected one.

Use the supplied reproduction scripts/results as failing evidence, not as successor pass assertions. Run the existing focused 12-test suite as regression coverage and add only tests needed for these cases. Root review runtime differed from the executor; record the actual corrected release toolchain.

RELEASE AND HANDOFF

Issue a new patch release without changing previously released bytes. Keep API contract v2 where the repair is compatible and document any needed clarification. Use normal authenticated local HTTP against the exact newly installed service and clean JavaScript/Python clients. Exercise the relevant compatibility calls and historical-copy continuation through the installed service, not only imported source.

Retain exact artifact identities, commands/results, the focused regression outputs, representative HTTP responses, before/after historical record hashes, and reconciled reports/export. Existing restart/restore checks may be reused where unaffected; rerun only checks needed to establish behavior changed by this repair or required by the existing release criteria. Do not add a new broad qualification campaign.

Return a compact review ZIP with the focused delta, plan/progress/result, case-to-evidence map and exact self-excluding manifest coverage. Keep the previous failure evidence intact. Commit scoped changes and push normally to the already-approved feature branch; verify its remote ref. Preserve unrelated owner work.

The feature-retention policy remains PROPOSED unless Larry separately adopts it. Real T0, Vega instrumentation, provider calls, commercial spend, owner-profile changes, production deployment, public publication and new DEV-12 sender campaigns are outside this commission. Do not import pre-T0 activity or reset a real dataset. Preserve CT02-02b OPEN.

Declare READY_FOR_VEGA_PLATFORM_INTEGRATION only after IC03-01 is verified through the corrected release and the existing readiness criteria still hold. Keep software readiness separate from policy adoption and actual Vega dataset activation.

Start with the plan checkpoint and continue through the narrow correction, focused verification and versioned release.
