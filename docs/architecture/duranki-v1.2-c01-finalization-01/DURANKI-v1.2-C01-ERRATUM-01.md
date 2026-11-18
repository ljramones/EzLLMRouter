# Duranki v1.2 Correction 01 — Erratum 01

**Date:** 25 October 2026  
**Owner:** Larry Mitchell  
**Standing:** Authored document delta for independent review. No owner adoption, implementation, runtime test, deployment or integration is implied.  
**Review basis:** [Claude Review 03](inputs/DURANKI-v1.2-CLAUDE-REVIEW-03-2026-10-25.md), SHA-256 `867c1a7635bac5e4cca56a957aebe95f47b31c3936b8664ca61d6001719a550f`.  
**Reviewed predecessor:** Correction 01 package SHA-256 `de390713f284a9316b55fa1508e491cdc81c1b4e0c85eeb5fcbeace2b65da312`. Its 37 manifest payloads verify. The exact predecessor architecture, register, roadmap and incorporation map are preserved under `predecessor/`.

## 1. Disposition and review boundary

Concur with G-01 and G-02. The canonical-binding choice was an author error: signing mutable server assessments is necessary, but making them part of logical-work equality was not. Plan-key custody was an inherited requirement and should not have disappeared during compression. Incorporate the reviewer's N-01 lock-ordering refinement, while distinguishing the proposed sequence from what historical records actually prove.

This is an erratum, not Correction 02 or a new architecture cycle. The active reading copy applies the narrow replacements; [the architecture diff](deltas/ARCHITECTURE-C01-to-E01.diff) shows their exact scope. Existing scope, operation sequencing, source evidence, legacy wire `0.2`, historical canonical bytes, tariffs and test identities remain controlling except for the explicit amendments below. Companion edits only keep the register, roadmap and current map consistent, add the requested rounding pair, and append available evidence.

| Review item | Disposition | Exact target |
|---|---|---|
| G-01 | Corrected in text; exact successor implementation unexecuted | Architecture §§5.3, 9.4; T-14.a, T-46.b, T-79.c |
| G-02 | Restored as a requirement, not just a risk row | Architecture §5.3, §5.4 check 1; T-07.a |
| N-01 | Corrected successor publication order; historical proof claim qualified | Architecture §5.4; existing T-24 boundary |
| N-02 | Partially addressed by available DEV-05/06/07 evidence; still open for missing records | Register and separate evidence supplement |
| N-03 | Acknowledged; no prose-only rewrite | No additional work or new gate |
| N-04 | Added to existing T-48.g and fictional vectors | Roadmap §5.2; `FICTIONAL-TARIFF-VECTORS.json` |

## 2. G-01 — Separate asserted work from assessed authority

The corrected contract distinguishes three things:

| Information | Protected location | Effect on an identical resubmission |
|---|---|---|
| Caller-asserted commission reference, ordered delegation links and caller-declared reasons; mandatory lifetime-stable trusted identity | Canonical work | Unchanged assertions preserve the digest; changed assertions under the same WorkKey conflict |
| Server-assessed commission verification, delegation coverage and server-assigned absence reasons | Immutable signed admission snapshot, linked to the work digest | Later assessment changes do not change logical identity |
| Activation context and current authorization/key/reservation state | Signed execution context and qualified current checks | May block access or sending; never creates another logical effect automatically |

The server does not fill a caller omission with a newly available commission or an inferred reason and then hash that reconstruction as though the caller supplied it. Verification may change `asserted` to `verified`; a source may become available; coverage may improve. Those are appended assessments, not changed submitted work.

An authorized identical resubmission recovers the existing submission/attempt. It does not allocate a new reservation or send. That is **not** permission to bypass current access, handling, commission or revocation controls. A legitimate denial under changed policy is distinct from a false work-conflict error. Possibility of a previous send continues to bar automatic replay. The full authenticated WorkKey and canonical assertion equality remain required; user-supplied identity strings never become authority merely by being hashed.

The ledger schema decision now explicitly separates assertion storage from assessment storage and retains work-digest/signature linkage. This remains part of the same DEV-12 successor delta. No fields are added to strict legacy wire `0.2` by this document edit.

## 3. G-02 — Restore plan-signing key custody

Production signing keys belong in a managed key service with an explicit key ID and version. Neti's trusted plan authority alone can sign validated admitted plans. The guard and sender verify; they do not mint authority. The isolated worker, clients and ranking component have no signing capability.

The requirement includes scheduled rotation and compromise revocation. A signature can remain mathematically valid after its key version is revoked; that plan is nevertheless ineligible for execution. Check key eligibility at FDC and at first-write freshness after waits. Replacement signing requires fresh trusted authority and preserves existing work identity, ownership and financial exposure. It cannot retry a possibly sent attempt.

Isolated synthetic keys can support a named test profile. They do not establish managed production custody. The historical WP-A phrase “optimization layer” is corrected to “trusted plan authority” in the successor; the adopted historical file is not edited.

## 4. N-01 — Commit, publish under the fence, then acknowledge

The amended ordering is:

```text
Durable authority/revision transaction (outside send lock)
    → coherent, non-regressing sender-view publication (under Choice B fence)
    → acknowledgement of effectiveness
```

The sender uses the same fence for the final current in-memory checks and qualified nonblocking first write. Database operations and key-service calls stay outside that critical section. Local revocation takes effect at the fence-protected publication, not when a management request arrives or merely when its database transaction commits. The implementation records the stages separately and must not acknowledge effectiveness early.

Publication failure or uncertainty closes the affected release path. Ordered publication prevents an old update from overwriting a new one. Restart loads and validates durable state before allowing sends. A crash after a possible send preserves uncertainty rather than turning missing diagnostics into permission to replay. These are explicit qualification obligations, not newly observed behavior.

**Historical distinction:** the available DEV-04/05 source supports the in-memory fence mechanism; it does not itself prove the full durable publication sequence. The supplied DEV-07 living result expressly describes its transaction committing while holding the gate. That record remains unchanged. Review 03's proposed ordering is accepted as the successor requirement without recasting DEV-07 as evidence that it already uses that ordering.

## 5. Test delta and fictional arithmetic

The four core subcase changes are two additions and two amendments. All remain unexecuted requirements in this packet.

| Subcase | Change | Required discriminator |
|---|---|---|
| T-07.a | Added | Revoke a signing-key version after preparing a valid plan; block its unsent first write, including after a lower wait. An eligible-key positive succeeds; re-signing cannot replay a possibly sent attempt. |
| T-14.a | Added | Same WorkKey and caller assertions, changed server status/coverage/reasons: recover the original; no added attempt, reservation or send. Current access controls still apply. |
| T-46.b | Amended | Detect tampering with the signed admission assessment and work linkage; distinguish it from legitimate later appended assessments and changed caller work. |
| T-79.c | Amended | Bind caller commission assertions and separately protect signed admission status/reasons; later verification leaves original work identity unchanged. |

N-04 expands **existing T-48.g** rather than adding an ID. For Tariff B, `3 × round_half_even(0.0003000005)` is USD **0.000900000**, while `round_half_even(3 × 0.0003000005)` is USD **0.000900002**. The same raw aggregate produces different totals because the financial unit is the attempt. The new vector also preserves separate upward reservation rounding. Earlier Tariff A/B vectors and bounds remain byte-for-byte equivalent as JSON data.

There are still **87 parent/alias identifiers: 86 canonical parents and the T-84 alias**. Subcases rise from **71 to 73**. No new parent PASS is recorded. Document calculations do not pass a product test. Existing T-24 covers the changed publication ordering and requires matching failure/restart proof before reliance; historical queue evidence is not promoted to that broader claim.

## 6. N-02 — Evidence mapping is separate work, and partly complete

[Evidence supplement 01](DURANKI-v1.2-C01-EVIDENCE-SUPPLEMENT-01.md) adds bounded observations to 17 parent rows using the supplied final DEV-05 review, dated DEV-06/07 results and selected Run-16 source/record correspondence. The register preserves its previous assessment history rather than rewriting earlier uncertainty.

Final DEV-08–DEV-10 result and receipt files, and later DEV-07 closure, were not located in the searched conversation/Library files. Later executor messages and the history index are not silently substituted for the missing primary bytes. [The capture prompt](DURANKI-DEV05-10-EVIDENCE-CAPTURE-PROMPT.md) requests the exact committed records without running tests or altering a profile. N-02 therefore remains open for completion. No whole-v1.1 or standalone-completion percentage is claimed.

## 7. Owner decision and next artifact

**PostgreSQL remains the recorded production ledger engine**, from the quoted 23 October owner decision already incorporated in Correction 01. This erratum does not reopen that choice or authorize migration of the standalone SQLite store. A forwarded reviewer request to affirm it is not represented as a new direct owner affirmation or adoption of the architecture.

The next independent review is delta-only: G-01, G-02, N-01, the four core subcases, the N-04 pair and the separately bounded evidence-map additions. Architecture adoption remains an owner act. After adoption, the next substantive design artifact is the exact successor schema/serialization and canonical-vector contract delta, followed by the DEV-12 brief with an honest reused-evidence map. Vega integration remains deferred.

## 8. Validation and limits

[Document validation](DURANKI-v1.2-C01-E01-DOCUMENT-VALIDATION.json) records checked input hashes, unchanged sections, exact replacements, register structure, preserved tariff data, new arithmetic and package checks. [Delta index](REVIEW-DELTA-INDEX.json) records before/after hashes and diffs.

No product code, database, running profile, credentials, provider account, allowance, Git branch or external integration was changed. No service, Docker container or provider was invoked. This packet does not independently close its own findings or claim runtime implementation of the successor requirements.
