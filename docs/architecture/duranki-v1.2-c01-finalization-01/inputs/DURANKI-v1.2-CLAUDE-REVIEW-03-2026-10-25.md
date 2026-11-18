# Duranki v1.2 — Claude review 03: Correction 01

**Date:** 25 October 2026  
**Status:** Reviewer verdict on the Correction 01 package. Not owner adoption.  
**Owner:** Larry Mitchell  
**Reviewed:** `DURANKI-v1.2-CORRECTION-01-REVIEW-PACKAGE.zip`, SHA-256 `de390713f284a9316b55fa1508e491cdc81c1b4e0c85eeb5fcbeace2b65da312`

| Package file | SHA-256 (first 16) |
|---|---|
| `DURANKI-ARCHITECTURE-v1.2-CORRECTION-01.md` | `3cb18d2dae9a2abf` |
| `DURANKI-v1.2-C01-ROADMAP.md` | `99e01a72266f0fce` |
| `DURANKI-v1.2-C01-ASSURANCE-REGISTER.md` / `.json` | `fbf3688e45867b2c` / `288052a5035acb0e` |
| `DURANKI-v1.2-C01-REVIEW-AND-RESEARCH-MAP.md` | `6e109b7b9cd0ccc5` |
| `FICTIONAL-TARIFF-VECTORS.json` | `ce77848ee815ccfa` |
| `MANIFEST.sha256` | `8fa9184d8fc26165` |

## 1. Verdict

**Concur with required corrections.** Correction 01 incorporates the findings from Reviews 01 and 02 at the cited clauses, and the companion register, roadmap and tariff vectors check out. Two material defects remain. Both are small clause-level fixes:

- **G-01:** server-assessed envelope state sits inside canonical work, which breaks idempotent deduplication.
- **G-02:** the plan-signing key custody requirement was lost when the risk table was compressed.

Fix them as a short erratum to Correction 01 and verify by delta. A further full correction cycle is not needed. The next substantive artifact remains the exact successor contract (roadmap §8).

## 2. What was verified

- **Integrity.** All 37 manifest entries verify. The input copies of v1.1, v1.2, Dispositions 01 and 02, Reviews 01 and 02, the handoff and Addendum A match their previously recorded hashes.
- **Prior findings at their clauses.** These were checked in the architecture text, not only in the map:
  - F-01: shared envelope in the DEV-12 successor (§5.3, §9.4, §15.3; roadmap §3).
  - F-02: T-84 aliased to T-49.
  - F-03: authority revision vector over the named existing revisions (§5.4).
  - C-1: spend importer at roadmap position 2.
  - C-2: research departures labelled (§6.3, §12.1).
  - C-3: opaque compaction inherits the union of input taints (§5.1 control 3, §13.5).
  - C-4: tier and rounding fixtures (roadmap §5).
  - C-5: Choice B named as the fence (§5.4); see N-01.
  - C-6: length test, 6.0% shorter by Python split; see N-03.
  - Also corrected: R8 full `WorkKey` (§8.2), R1 privilege separation (§10.1), R5/R6 stream stop and incremental reservations (§8.6), and the stale Ninshubur/Nabu/Redis clauses (§4.2, §14.5).
- **Tariff vectors.** Recomputed independently with exact decimals. Every Tariff A and Tariff B case matches, and the domain bounds (USD 0.009000000 and 0.010000013) are correct.
- **Assurance register.** 87 identifiers: 86 parents plus the T-84 alias. 71 nested subcases, no duplicates, no orphans and no unqualified parent pass. Statuses are consistent between the Markdown and JSON forms.

## 3. Material findings

### G-01 — Server-assessed envelope state must not be part of canonical work

**Where.** §5.3 binding table, rows 3–4; §9.4 table ("value, admission status and reason inside canonical work"; "ordered chain and its admission status/reason inside canonical work").

**Problem.** §8.2, following the adopted contract, deduplicates only when the `WorkKey` matches **and** the canonical-work digest is equal. Several values the correction places inside canonical work are assessed by the server at admission and can legitimately change between two identical submissions:

- `unavailable` means, by its own definition, that the source was unreachable when the row was written (Addendum A §3.2). It is transient.
- `not_yet_issued` changes for every in-flight work key on the day commissions start being issued.
- Commission status moves from `asserted` to `verified` when verification becomes available.
- `caller_omitted` and delegation-chain coverage (partial or complete) are server judgments, not caller content.

When any of these changes, an identical resubmission produces a different digest. It is then rejected as a conflict instead of returning the original result. That breaks T-14 and the query-first recovery path the clients rely on.

**Precedent.** The adopted WP-A v0.3 §2.2 already draws this line:
- The `trusted` block holds only values that stay stable for the lifetime of the authorized work (`context_id` "survives credential refresh/reconnection").
- `classification_snapshot`, which is time-varying server state, is kept out of canonical work as "audit only".
- Correction 01 applies the same reasoning to the activation epoch.

**Required change.**
1. **Canonical work** holds caller-supplied envelope content: the commission reference as asserted, delegation links as asserted, and reasons the caller declares (for example `not_applicable` for direct human use). It may also hold trusted values that stay stable for the work's lifetime, such as the verified first and last delegation links, consistent with the `trusted` block.
2. **The signed admission/plan record** holds server-assessed commission status, chain coverage and server-assigned reasons (`not_yet_issued`, `unavailable`, `caller_omitted`) as an immutable admission snapshot. This is the same treatment as `classification_snapshot` and the activation epoch. Mutation protection is unchanged because the plan is signed.
3. **Tests.** Add a subcase to T-14 or T-77: an identical resubmission across a server-side status or reason change deduplicates to the original. Reword T-46.b and T-79.c to cover mutation of the signed admission snapshot.

### G-02 — Plan-signing key custody was dropped

**Where.** §17. In v1.2, the only statement of how plan-signing keys are protected was the risk row "Signing-key compromise (plans, origin) — Managed keys, rotation, restricted minting". The compressed risk table in Correction 01 omits it. Key management now survives only for office-origin keys (§7.1). This contradicts Correction 01's own §19 condition: shorter "without deleting inherited safety/quality obligations".

The plan signature is what lets the guard and sender trust admitted work, so its custody is a security obligation, not just a risk note.

**Required change.** Restore it as a requirement in §4.4 or §5.3:
- Plan-signing keys live in a managed key service, with key ID and version (the WP-A signature envelope already carries `key_id` and `key_version`).
- Only the trusted plan authority can sign. The guard and sender hold verification keys only.
- Keys rotate on a schedule.
- On compromise, revoke the key version. Unsent plans signed under it then fail FDC check 1 and need fresh authority. A possibly sent attempt is never re-sent because of a re-sign.

Add a T-07 subcase for a revoked signing-key version.

WP-A §3 says plans are signed "by the optimization layer". The successor contract should restate the signer as the trusted plan authority, matching §5.3.

## 4. Notes

**N-01 — Refinement of my C-5 wording.** In Review 02 I asked for the authority-revision change to commit inside the first-write fence. That is stronger than needed, and it would be worse in production. Correction 01 §5.4 now requires authority records to commit inside the fence. That puts durable database I/O (network round trips once on PostgreSQL) under the send lock and creates a lock-ordering hazard.

The DEV-04 Choice B evidence uses a different and sufficient order:
1. Commit the authority change durably.
2. Under the fence, update the sender's authoritative view, including the revision vector.
3. Acknowledge.

Revocation is effective at the fence-protected view update. A restart reloads durable state before any send. The existing rule that a failed view update fails closed covers the gap. Amend §5.4 in the same erratum.

**N-02 — The register cannot yet measure progress.** It is structurally sound. But the only evidence supplied was WP-A, the DEV-04 Run-11 review and DEV-11, so most standalone items read "not evidenced", including identity rejection, plan-signature rejection and the supply-chain tests. That answers nothing about how close the build is to v1.1. Before the DEV-12 brief, map the DEV-05 to DEV-10 result records into the register. This is mechanical. It is also what the brief's "reused evidence with explicit correspondence" depends on.

**N-03 — Length passed on the letter only.** The normative document is 6.0% shorter, but negation density rose from 22.0 to 23.9 per 1,000 words (Python split, the same convention). The aim of moving caveats out was only partly met. I would not spend another cycle on prose; it does not block DEV-12.

**N-04 — One extra Tariff B vector.** Three separate one-document requests settle to USD 0.000900000 in total, while one three-document request settles to 0.000900002. Add this pair to T-48.g. It shows that rounding is applied per attempt, not just the per-request minimum.

## 5. Path forward and owner actions

1. **Erratum.** The author fixes G-01, G-02 and N-01 as a short erratum: §5.3, §9.4, §5.4, §4.4 or §5.3 for key custody, and the T-07, T-14/T-77, T-46.b and T-79.c subcases. Verify by delta only.
2. **Confirm PostgreSQL** directly to the author. The map records that no affirmation was inferred from "next".
3. **Supply the DEV-05 to DEV-10 result records** for the register (N-02).
4. **Adopt.** After the erratum verifies, adopt the Correction 01 delta. Then the exact successor contract and the DEV-12 brief follow.

## 6. Limits

This is a document review. The WP-A contract, DEV-04 and DEV-11 records were read from the package inputs. Valhalla 0.4, the Proto proposal and evidence report, and the DEV-05 to DEV-10 records were not available. No repository, implementation, credential or provider was inspected or changed.
