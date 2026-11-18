# Duranki v1.2 — Claude review 04: Correction 01, Erratum 01 (delta verification)

**Date:** 25 October 2026  
**Status:** Delta verification of Erratum 01 against Review 03. Not owner adoption.  
**Owner:** Larry Mitchell  
**Reviewed:** `DURANKI-v1.2-C01-ERRATUM-01-REVIEW-PACKAGE.zip`, SHA-256 `7ef3584b2b2d56490ad1d08eb3ae0b2d03d0f05c72a312e98ee544ac55db33a4`

## 1. Verdict

**Concur with one required correction, R04-01.** G-01 and G-02 are closed. However, the lock ordering adopted from my Review 03 N-01 is wrong for the standalone profile. The DEV-07 evidence in this package shows why, and I did not have that evidence when I wrote N-01. The fix is one paragraph in §5.4.

With R04-01 applied, Correction 01 + Erratum 01 is ready for owner adoption. No further correction cycle is needed.

## 2. Verified

- **Integrity.** All 83 manifest entries verify. The `predecessor/` architecture, register and roadmap match the Correction 01 identities reviewed in Review 03 (`3cb18d2d…`, `288052a5…`, `99e01a72…`). The Review 03 input copy matches `867c1a76…`.
- **Delta scope.** I diffed the predecessor against the current architecture myself. The result has the same nine hunks as the supplied `deltas/ARCHITECTURE-C01-to-E01.diff`; the only difference is how the diff tool aligned the lines. No unannounced edits.
- **G-01, closed.** §5.3 and §9.4 now split caller assertions (canonical work) from server assessments (a signed admission snapshot tied to the work digest). Activation stays in the signed execution context. Duplicates that differ only in server assessment resolve to the original submission. Current authority still governs access, and a newly required commission cannot be bypassed by recovering an old work key. T-14.a, T-46.b and T-79.c state the right discriminators.
- **G-02, closed.** The managed signing-key requirement is restored in §5.3. FDC check 1 now rejects revoked key versions, as does the first-write freshness check. Only the trusted plan authority signs. T-07.a adds a revoked-version case after a lower wait, with a positive control and a no-replay rule on re-signing. The signer wording that conflicts with WP-A is restated.
- **N-04.** Recomputed: three one-document attempts settle to USD 0.000900000 and one three-document attempt to 0.000900002. Their upward bounds are 0.000900003 and 0.000900002. All match.
- **Register.** 87 identifiers, 86 parents plus the T-84 alias, 73 subcases, no duplicates and no PASS status anywhere. The 17 new historical mappings are labelled partial and carry their limits.
- **Evidence supplement and capture prompt.** The supplement is candid about what DEV-05 to DEV-07 do and do not show. The prompt is read-only: it anchors to a commit, uses `git show`, excludes secrets and live databases, and requires HEAD, index and status to be unchanged. It is fit to run.

## 3. Required correction

### R04-01 — Make the authority-update ordering an invariant and keep DEV-07's ordering for the standalone profile

**Correction to my own N-01.** Review 03 N-01 asked for the durable commit to happen outside the first-write gate. Erratum 01 adopted that and made it normative: "No database I/O … runs under the first-write lock" (§5.4).

The supplied DEV-07 result (§ "Implemented source checkpoint") shows the qualified implementation does the opposite. Registry writes "commit data, audit and authority revision atomically while holding the owned sender's existing first-write gate". The epoch changes before success is acknowledged, and a failed transaction leaves the prior record and epoch in place. The register already maps that behavior to T-24 through E-11.

For a single-process standalone profile on SQLite, the DEV-07 ordering is better than the one I proposed:

- **No gap between commit and view.** The durable state and the sender's view change together. The commit-to-publication window, out-of-order publication and partial-publication failure that §5.4 now has to qualify do not exist.
- **It fails safe.** A stalled commit blocks sends rather than allowing them.
- **It is already qualified.** It passed the DEV-07 target, with queued revocation and restart persistence.

My production concern, network-bound PostgreSQL commits held under the send lock, belongs to the replicated fence. Correction 01 already says that fence needs its own qualification, because a process-local gate cannot serialize across replicas anyway.

**Required change to §5.4:**

1. **Invariant for every profile.** Effectiveness is acknowledged only after the authority change is durable **and** the sender's authoritative view reflecting it has been published under the fence. A failure leaves the prior durable state and view in force. Restart reloads durable authority before any send. These rules exist in the current text; keep them.
2. **Standalone single-process profile.** An atomic durable commit together with the view update inside the gate conforms. That is the DEV-07 ordering, with E-11 as evidence.
3. **PostgreSQL or replicated profiles**, where commits involve network or unbounded I/O. Use the Erratum 01 sequence, and qualify the commit-to-publication interval, failure, ordering and restart as part of that profile's fence.

Scope the "no database I/O under the lock" sentence to item 3. Without this change, DEV-12 would have to rework a qualified mechanism and requalify T-24 against new failure modes, for no benefit in the profile DEV-12 targets.

## 4. Notes

**R04-N1 — Define "execution-eligible" so that rotation does not invalidate queued plans.** FDC check 1 now requires an "execution-eligible key ID/version", but the term is undefined. Scheduled rotation should stop new signing under the old version while keeping it eligible for verification until the plans already signed under it expire. Only revocation ends eligibility. Otherwise every scheduled rotation invalidates queued plans, which is the same replan storm M-04 removed for provider credentials. Add a rotated-but-not-revoked positive control to T-07.a.

**R04-N2 — Name signing-key status in the authority revision vector.** The §5.4 fence checks the "authority/key-status view", but the revision-vector list two paragraphs later omits signing-key status. Add it to keep the two consistent.

**R04-N3 — N-02 remains open, appropriately.** The capture prompt is the right next step. It can run in parallel with adoption and the successor-contract work; it does not gate either.

## 5. Owner actions

1. Have the author apply R04-01, and optionally R04-N1 and R04-N2. They are three short paragraph edits; a quick delta check is enough.
2. Adopt Correction 01 + Erratum 01 with those edits.
3. Run the read-only evidence capture prompt against the Duranki repository.
4. PostgreSQL is still recorded from the 23 October quotation. A one-line direct confirmation to the author closes that provenance note whenever convenient; it blocks nothing.

The next design artifact after adoption is the exact successor contract, as the author proposes.

## 6. Limits

This is a document review. The package script `verify_document_delta.py` was not executed; checks were made independently. The DEV-05 to DEV-07 records were read as supplied copies. DEV-08 to DEV-10, Valhalla 0.4 and the Proto documents were not available. No repository, implementation, credential or provider was inspected or changed.
