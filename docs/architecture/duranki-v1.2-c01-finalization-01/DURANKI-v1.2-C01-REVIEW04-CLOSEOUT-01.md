# Duranki v1.2 — Review 04 closeout 01

**Date:** 25 October 2026  
**Standing:** R04-01 applied; bounded author document verification complete; ready for owner adoption. Not owner adoption, new independent review, implementation acceptance or execution authority.  
**Applies to:** Correction 01 + Erratum 01. This finalization supersedes only the affected ordering/key-lifecycle text and the listed companion mappings; earlier inputs and execution records remain preserved.

## 1. Stop the architecture review cycle

Review 04 §1 states that G-01 and G-02 are closed and that, after R04-01, no further correction cycle is needed. Its §4 explicitly allows N-02 evidence capture to run in parallel with adoption and successor-contract work. The remaining author correction is now applied and checked by delta. Recommend owner adoption, not a fifth broad architecture review. A newly demonstrated material defect would still receive a targeted correction; this is not a claim of permanent defect-freedom.

The next design artifact is the exact successor contract; its own schema, canonicalization and implementation checks remain necessary. That work does not reopen this baseline by default. Evidence mapping is a record-reconciliation task, not a new execution commission.

## 2. R04-01 — invariant, then profile-specific mechanism

Every profile acknowledges effectiveness only after the authority change is durable and the matching sender view has been published under its applicable first-write fence. First write cannot interleave with a partially applied authority/view update.

For the single-process SQLite standalone profile, retain the DEV-07 sequence: hold the existing gate, atomically commit authority data/audit/revisions, publish the matching sender view, release the gate and acknowledge. A definitively rolled-back transaction retains the coherent prior state and view. A stalled commit blocks sends. The supplied DEV-07 result describes this ordering and its bounded queued-revocation and ordinary-restart observations. No rewrite of that mechanism is required merely to enter DEV-12.

For PostgreSQL or replicated profiles with network-bound or unbounded persistence, commit outside the local first-write lock, publish a coherent non-regressing view through the separately qualified end-to-end fence, then acknowledge. The commit-to-publication interval, failure, competing updates and restart belong to that profile's qualification, not to an invented standalone requirement. A per-process lock is not distributed qualification.

A committed-but-unpublished or uncertain update fails closed until consistency is recovered; it cannot be described as a rolled-back update. Restart reloads durable authority before sending. Possible-send uncertainty, exposure and no-repeat ownership remain unchanged.

This corrects the author's earlier blanket adoption of Review 03 N-01. It does not rewrite the DEV-07 historical record to make it match a different sequence.

## 3. Two small key-lifecycle clarifications

**R04-N1:** scheduled rotation stops new signing under the old key but preserves verification of its already-issued unexpired plans unless revoked. Rotation is not revocation. Other plan, permission, expiry and financial checks continue. Existing T-07.a now includes the rotated-but-not-revoked positive control; no new ID or claimed pass is added.

**R04-N2:** the authority revision vector explicitly includes the bound signing-key version's verification/revocation eligibility. This is not the active minting-key selector; ordinary rotation alone does not invalidate queued plans.

G-01's stable assertion/signed assessment separation and G-02's managed custody, restricted signer, revoked-key rejection and no-replay requirements remain intact.

## 4. Mechanical companion repairs and preservation

The current architecture changes only its identity/reading note and §§5.3–5.4. The research map, assurance register and evidence supplement are synchronized to those changes. Existing historical disposition entries remain history, with this closeout taking precedence.

During register synchronization, two JSON parent requirement strings (T-07 and T-14) were found to contain unrelated earlier numbered design principles rather than their §16 test statements. They are copied verbatim from the already-correct, unchanged §16 entries. This repairs the map, not the architecture or its tests. All 86 canonical parent strings now match §16. No evidence status is promoted; all 87 parent/alias IDs and 73 subcase IDs are unchanged.

The roadmap, tariff vectors, source inputs, predecessor files, evidence-capture prompt and its 22-path inventory are byte-identical to the reviewed Erratum 01 package. Diffs and file identities expose every modified file. The original package is preserved as `history/ERRATUM-01-REVIEW-PACKAGE.zip` (SHA-256 `7ef3584b2b2d56490ad1d08eb3ae0b2d03d0f05c72a312e98ee544ac55db33a4`). Review 04 and its supplied manifest are copied under `inputs/`.

Old Erratum 01 replacement instructions, checks, delta index and `verify_document_delta.py` are historical records for their original bytes, not checks of this finalization. Use `verify_finalization.py` for this package. This closeout overrides their blanket commit-outside-lock recommendation for standalone only.

## 5. Adoption and remaining work

**Recommended next decision:** adopt the architecture direction in Correction 01 + Erratum 01 as finalized here. This message and packet do not record that the owner has already done so.

Proceed with the exact successor contract and then the bounded DEV-12 brief. Run the unchanged read-only evidence capture in the repository in parallel, and map final DEV-08–DEV-10 and later DEV-07 records before claiming an accurate implementation-completeness measure. N-02 remains open and non-gating for architecture adoption or contract drafting. No percentage complete is claimed.

PostgreSQL remains the recorded production engine; standalone SQLite remains supported within its scope. The quotation-based provenance note is not a design blocker. Vega/Proto integration stays deferred. No code change, Git action, repository capture, Docker work, paid provider call, credential operation or owner-profile update was performed by this finalization.

## 6. Evidence and verification

- [Review 04](inputs/DURANKI-v1.2-CLAUDE-REVIEW-04-2026-10-25.md), §§1, 3–5: required correction, optional notes and stopping condition; full SHA-256 `15f3adb8a8063ae0d181aa4046b44b2cd06ce9440e37f8a41470c3e3dfb78cdd`.
- [DEV-07 supplied result](inputs/DEV-07-RESULT-SUPPLIED-20261021-232233.md), “Implemented source checkpoint” and “Observed owner target”: dated standalone ordering and bounded historical result, not a new source inspection.
- [Finalization validation](FINALIZATION-VALIDATION.json): current document-only checks and their limits.
- [Delta index](FINALIZATION-DELTA-INDEX.json): exact before/after hashes and diffs, including mechanical register repairs.

The verification is an author-side integrity/scope/consistency check. It does not claim that Claude reviewed the final bytes or that a product test ran.
