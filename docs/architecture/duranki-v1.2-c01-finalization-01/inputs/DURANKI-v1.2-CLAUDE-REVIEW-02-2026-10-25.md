# Duranki v1.2 — Claude review 02: Disposition 02 and open items from the Disposition 01 review

**Date:** 25 October 2026  
**Status:** Reviewer verdict and required corrections for Correction 01. Not owner adoption of v1.2, Addendum A, Disposition 01 or Disposition 02.  
**Owner:** Larry Mitchell  
**Reviewed:**

| Input | Bytes | SHA-256 |
|---|---:|---|
| `DURANKI-v1.2-ADDENDUM-A-DISPOSITION-02.md` | 24,723 | `64a37dfe7d0f2a43fd0dba2698b12d19e1a48193292b3ff8349b5610bbd14537` |
| `DURANKI-ADDENDUM-A-PACKET-VERIFICATION-01.json` | 9,045 | `b0bc82a9a94d303fc4457ddc26683a20147a499a2c258ed8b237c0e78e26c0f7` |

Read against the handoff and Addendum A (identities in their `MANIFEST.sha256`), the v1.2 draft (`99bf11df…`) and Disposition 01 (`63750092…`). The Disposition 02 hash matches the `output_note` in the verification JSON, and the v1.2 and Disposition 01 hashes match the JSON's input records.

## 1. Verdict

**Concur with required corrections.** Disposition 02 dispositions all eighteen handoff rows, resolves the test-number collision, settles terminology and records the ledger decision with the right scope. Several of its corrections improve on the handoff (§2).

Two corrections are required before Correction 01 is authored:

- **F-01:** the shared metadata envelope must be part of the successor-contract decision that DEV-12 depends on.
- **§4:** six items from my review of Disposition 01 have no disposition. That review was given in conversation, not as a file, and Disposition 02 carries Disposition 01 forward "unchanged".

The remaining findings are notes.

## 2. Where Disposition 02 improves on the handoff

The handoff called several rows compatible that are not quite compatible. Disposition 02 is right on each of these:

- **R1.** An insert-only gateway role contradicts the state transitions that reservations and registry records need. Immutable financial events and mutable operational state need separate privileges.
- **R8.** Addendum A's step + revision + generation tuple is not globally unique. The adopted `WorkKey` includes `principal_id` and `task_id`, and deduplication also requires canonical-work equality. Modality also must not decide identity ownership: a speech or search call can belong to a step, contrary to Addendum A §4.3.
- **§6.2.** There is a third axis, commission status (absent, asserted, verified), beside absence reasons and provider field evidence. The handoff named only two.
- **§6.3.** Addendum A §7.2 schedules step identity in Phase 1b and taint instrumentation in Phase 2, which would weaken checks the adopted contract already requires. The handoff did not flag this.
- **§6.4.** Moving budget authority to a future service is a cutover with its own correctness conditions, not a change of connection. Two services must never authorize against the same balance.

## 3. Findings

### F-01 (material) — Put the shared metadata envelope in the successor contract DEV-12 needs

Disposition 02 §8 says to "define any shared metadata envelope within the reviewed successor contract", but it does not say which successor. T-77 and T-79 are scoped to an unscheduled "new shared-metadata profile". As written, the envelope could arrive in a later contract version.

That would cost a second versioned change. Disposition 01 M-06 already requires a successor wire contract before DEV-12, with its own canonical binding, parity tests and legacy compatibility work. Adding commission, delegation, activation and absence-reason fields afterwards means repeating that work. Owner decision 1 ("agreed": record the delegation chain from day one; commission reference empty with a reason until it exists) and Addendum A's time-sensitivity argument both point to doing it once.

**Required for Correction 01:**

1. Make the envelope part of the M-06 successor-contract decision: commission reference and status, delegation chain and status, activation epoch and absence reasons. In the standalone profile the fields stay empty with reasons, or carry synthetic fixture values. No Proto or Vega work is implied.
2. Decide which envelope fields sit **inside** the canonical-work binding. The commission reference and the delegation chain become authority-bearing from Valhalla step 3. If they are outside the binding now, step 3 forces another binding version. Including them while they are record-only costs little: a mutation after admission is simply detected.
3. Add T-77 and T-79 to the DEV-12 test map. Add the parts of T-78 that synthetic direct-human, delegated-agent and autonomous principals can exercise.
4. Add the matching columns to the standalone ledger schema in the same change. This is a schema decision, not integration.

### F-02 (note) — T-84 duplicates T-49

T-84, "missing native-operation usage" scoped to a qualified native-unit accounting contract, states the same requirement as T-49 for the same scope, and T-18 for text. With two IDs for one assertion, the assurance register can show one passed and the other "not assessed".

Record A-49 as a provenance alias of T-49, carrying the corrected outcome, instead of giving it a new number. T-85 (commission revocation before first write) is a similar case. A commission is one more revocation source for the T-24 boundary, so T-85 could be a T-24 sub-ID. That one is a judgment call; keeping T-85 separate is defensible because the commission authority arrives later.

### F-03 (note) — Define "authority revision" over the existing revisions

v1.2 already versions each authority input: policy, recovery policy, registry, source permission, grant and delegation, credential binding and price. Define the authority revision vector as the vector of those named revisions, not as a new counter. Otherwise the design gains another number to keep consistent with the ones it summarizes. "Revision" is already qualified everywhere it appears (step revision, usage revision and so on), so the name itself is fine.

### F-04 (note, reviewer error) — Word count convention

The handoff reported 5,811 words without naming the counting convention. GNU `wc` 9.4 gives 5,811 in the C locale and 5,825 in a UTF-8 locale. Python's `str.split()` also gives 5,825. The difference is exactly fourteen tokens made only of non-ASCII characters: three standalone "—" and eleven "→". The verification JSON is right that the number was not reproduced under its convention.

A word count was never identity evidence. Byte identity with the 23 October delivery can be established only by hashing the owner's copy of that file, if it still exists.

### F-05 (note) — Owner affirmation closes the decision-evidence question

The verification JSON records the Postgres decision as "decision evidence recovered", based on the handoff's quotation rather than an independently read transcript. That is the correct posture for the author. The owner can close it directly by affirming the decision to the Correction 01 author. It is his decision, and an affirmation needs no transcript.

## 4. Open items carried forward from the Disposition 01 review

These six points were raised in conversation after Disposition 01 and are not dispositioned anywhere yet:

| # | Item | Required for Correction 01 |
|---|---|---|
| C-1 | **The M-01 remedy is unscheduled.** Disposition 01 accepts the spend-export importer as a useful early item, then lists "provider importers" under separately scoped work (§5). The measurement gap is acknowledged but nothing is scheduled to close it. | Give the importer a position in the roadmap. It needs no Vega change and is the only near-term source of real spend data. |
| C-2 | **Departures from the research report are not labelled.** Item 10 said never compact a compaction; Disposition 01 makes it a default with exceptions. Item 11 limited replay to single-step leaves; Disposition 01 allows qualified whole-task experiments. | Label both as deliberate departures from the report, with reasons, in the 22-item map. |
| C-3 | **A handling rule from report item 10 is missing.** Opaque provider-side compaction inherits the union of its inputs' taints. | Carry it as a handling requirement in §5.1/§13, not as a deferred experiment. |
| C-4 | **The M-07 fixture does not test tiers or currency rounding**, although T-48 claims both. Its boundary table (checked: correct) covers the minimum charge and unit ceilings only. | Add a tier boundary, and one case whose amount is not representable at ledger precision so the declared rounding rule is exercised (DEV-11 rounds half-even at the nano unit). |
| C-5 | **The first-write fence is unnamed.** Disposition 01 M-04 calls for "a qualified lock/fence/ownership protocol". Disposition 02 R7 restates that a revision comparison does not serialize revocation with first write, but neither names the mechanism. | Name the Choice B first-write fence as the serialization point. A revocation is effective when it passes through that fence, and the authority-revision change commits inside it. |
| C-6 | **No length test for N-01.** Correction 01 now absorbs v1.2, two dispositions and the addendum reconciliation. | At re-review the normative architecture should be shorter than v1.2, with evidence caveats moved to the assurance register and sequencing to the roadmap. |

## 5. Owner actions

1. Affirm to the Correction 01 author that PostgreSQL is the production ledger engine (F-05).
2. Accept or amend the T-77–T-87 crosswalk, including the F-02 aliasing.
3. If the 23 October copy of `duranki-addendum-a.md` still exists, hash it and compare against `88c02e50…f45575ba` (F-04).
4. If R15 and R16 correspondence is to be checked, supply Valhalla 0.4 and the Proto Runtime Proposal with its evidence report.

## 6. Limits

This is a document review. No implementation, repository, credential or provider was inspected or changed. Valhalla 0.4, the Proto proposal and evidence report, the WP-A contract documents and the DEV-11 records were not available in this session; statements about them rely on v1.2, Disposition 01 and Disposition 02.
