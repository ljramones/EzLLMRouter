# Duranki Addendum A — reconciliation handoff for v1.2 Correction 01

**Date:** 25 October 2026  
**Status:** Reviewer handoff (Claude), following *Claude review disposition 01*. Not owner adoption of Addendum A, of v1.2, or of any reconciliation choice proposed here.  
**Owner:** Larry Mitchell  
**Subject:** `duranki-addendum-a.md`, *Duranki Addendum A: Valhalla Alignment and Providers Beyond Language Models*, draft 0.1, 23 October 2026  
**For:** the author of v1.2 Correction 01

## 1. Purpose

Two proposed successors to Duranki v1.1 exist, and neither cites the other:

- **Addendum A** (23 October 2026) aligns Duranki with Valhalla and Proto, adds a Phase 1c for speech, search and realtime voice, closes the ledger-database decision as Postgres, and adds acceptance tests **42–52**.
- **v1.2** (`DURANKI-ARCHITECTURE-v1.2-REVIEW-DRAFT-2026-10-25.md`, 25 October 2026) generalizes Duranki to typed operations and adds acceptance tests **42–76** with different subjects.

`DURANKI-v1.2-CLAUDE-REVIEW-DISPOSITION-01.md` (N-02) kept the ledger database open because no owner decision was found in its sources. The decision exists in the conversation that produced Addendum A (§4 below).

This handoff supplies Addendum A, records the owner decisions made with it, and maps every point where it overlaps or conflicts with v1.2 and Disposition 01, so Correction 01 can reconcile them.

## 2. Packet contents

| File | Role |
|---|---|
| `duranki-addendum-a.md` | Addendum A, draft 0.1, reconstructed as delivered on 23 October 2026 (§3) |
| `DURANKI-ADDENDUM-A-RECONCILIATION-HANDOFF-2026-10-25.md` | This note |
| `MANIFEST.sha256` | SHA-256 of both files above |

Not included, though Addendum A cites them: Valhalla: Conceptual Architecture 0.4; the Proto Runtime Proposal and its evidence report (23 October 2026); Protecting Agency concept overview 0.2. The owner holds these.

## 3. Provenance and reconstruction

- **Source:** Claude conversation *Cloud compute and agentic infrastructure*, https://claude.ai/chat/ebfba483-95dd-4cd9-9672-f59f68e57547, turns 105–107, 23 October 2026 (about 22:14–22:50 Toronto time).
- **Method:** the file delivered that night is not reachable from this session. It was rebuilt from the transcript of the write that created it, followed by the eight scripted wording corrections applied before delivery. Those corrections cover the provider call-site counts, web-search billing, the LiteLLM text-to-speech row, the realtime-logging wording, the P-16 commission wording and the migration wording. HTML escaping in the transcript (`&amp;`) was reversed.
- **Fidelity checks:** each of the eight corrections matched exactly one passage in the rebuilt text. The rebuilt file has 5,811 words; the delivery message on 23 October reported "about 5,800". No hash was recorded on 23 October, so byte identity with the delivered file cannot be proven here. If the owner still has that file, compare its SHA-256 with `MANIFEST.sha256`; if they differ, the owner's copy governs.
- **Later changes:** none found. The conversation shows no revision of Addendum A after delivery.

## 4. Owner decisions recorded on 23 October 2026

Before Addendum A was drafted, four questions were put to the owner (turn 105). His reply at 22:46 Toronto time (turn 106), verbatim:

> For 2, please fix Valhalla 0.4. For 4, use Postgres. For 3. I originally had it for LLM models, but we need to consider the others.  For 1, agreed

| # | Question | Owner decision |
|---|---|---|
| 1 | What fills the commission field before commissions exist? Proposed: empty with a reason code, with the delegation chain recorded from day one using Proto's caller chain | Agreed |
| 2 | Fix Valhalla as 0.4: rename its worker fence "activation epoch"; *execution generation* keeps Duranki's meaning | Approved; Valhalla 0.4 was produced in the same turn |
| 3 | Does "the gateway is the only door" cover speech, search and realtime voice, or only language models? | Consider the others too, not only language models |
| 4 | Ledger database (§18 item 10) | **Postgres** |

These are answers to those four questions. They do not adopt Addendum A as a whole; it remains a proposed draft 0.1. Decision 4 supersedes the conclusion of Disposition 01 N-02, while its point stands that a production database choice must not block the standalone SQLite profile.

## 5. Reconciliation map

"A" means Addendum A, "v1.2" the review draft and "D01" Disposition 01.

| # | Topic | Addendum A | v1.2 / D01 | Reconciliation needed |
|---|---|---|---|---|
| R1 | Ledger database | §10, §11: managed Postgres (Cloud SQL now, RDS after the AWS move); insert-only role; time partitions; hash chaining recommended for 1a | v1.2 §4.1 and §18 item 10: open. D01 N-02: keep open unless a decision is found | Record decision 4 (§4). A's sub-points (privileges, partitioning, hash chaining, hosting) remain proposals |
| R2 | Scope beyond language models | §8 and §8.5: new Phase 1c for speech-to-text, text-to-speech, realtime voice and model-hosted web search; fixed destinations, no routing | v1.2 §5.7–§5.9 typed operations (MS-05 to MS-07 and MS-09), §8.6 lifecycle profiles, §15.3 rows C, D, F | Decide whether Phase 1c survives as an assurance phase or is replaced by per-operation contracts plus the standalone profile (D01 M-02). Map A's four kinds onto MS families. The evidence bases differ: A cites the Proto evidence report F-12 (14 call sites); v1.2 cites the 25 October recce |
| R3 | Lanes versus the trust boundary | §8.4: Lane 1 is LiteLLM where it "lets Duranki's hooks govern"; Lane 2 is a Duranki-owned proxy implementing "the same hook contract" | v1.2 §4, §4.3: LiteLLM is an untrusted preparation worker; every path sends through the trusted guard and sender; hooks are not a substitute | A's governance-by-hooks premise is superseded. Restate the lanes as a choice of preparation adapter behind the same trusted sender, not two governance paths |
| R4 | Missing usage | §8.4: "Missing usage is estimated, never zero"; test A-49 | v1.2 §10.2 and test 18 as clarified: missing required usage stays unknown and exposure stays held; an estimate is recorded separately and is not settlement | **Conflict.** v1.2 is stricter and should govern. Amend A's wording and A-49 |
| R5 | Stopping and settling streams | §8.4: a failed top-up or revocation closes the session at the next chunk boundary, and "what has already streamed is settled"; tests A-47, A-51 | v1.2 §8.6; D01 M-05: closing the local connection does not prove remote execution or billing stopped | **Conflict.** Closing is a local action. Exposure for committed and in-flight work stays held until provider evidence settles it. Amend the expected outcomes of A-47 and A-51 |
| R6 | Session reservations | §8.2, §8.4, §8.5: a session maximum, reserved in increments topped up as the session runs | v1.2 §8.6, §10.8: no hard-ceiling eligibility without a finite bound. D01 M-05: rolling reservations allowed only with proof conditions | Compatible in direction. Adopt D01's proof conditions as the qualification of A's top-up model |
| R7 | Epoch and generation terms | §4.2: *activation epoch* (Valhalla 0.4) fences a stale Proto activation; checked at admission, final dispatch and acceptance from Valhalla step 4 | Review M-04 and D01 M-04: an authority invalidation counter, called "authority epoch/vector" and "authority generations". v1.2 §8.2: *execution generation*. v1.2 §8.6: "connection epochs" for realtime | Four distinct concepts share two words. Keep *activation epoch* for Valhalla's meaning and *execution generation* for Duranki's. Name the authority counter and the realtime connection counter without "epoch" or "generation". From Valhalla step 4, the activation-epoch check joins the M-04 first-write freshness inputs |
| R8 | Identity mapping | §4.1, §4.3: logical effect ID = step + revision + execution generation; non-step calls use the Proto call ID; a realtime session is one logical effect | v1.2 §8.2: operation type is not an execution identity; session and chunk IDs come with lifecycle contracts. D01 M-06 separates operation type, contract, attempt and administrative command identity | Compatible. Adopt A's mapping in §8.2 or defer it explicitly. Reconcile "a session is one logical effect" with v1.2 §8.6's session, turn and connection identities |
| R9 | Shared fields and the absence rule | §3: commission reference and status, delegation chain and status, logical effect ID, activation epoch, actor and others; empty only with a closed reason code (`not_yet_issued`, `not_applicable`, `caller_omitted`, `unavailable`); marked time-sensitive for 1a | v1.2 §9.1–§9.2: identity relationships and coverage states. v1.2 §10.2: usage field evidence (absent, null, known, invalid). Vega integration on hold | Different axes: A's codes say why a ledger field is empty; v1.2's states say what a provider reported. Define how they combine. Owner decision: whether A's columns enter the standalone ledger schema now. Empty columns with reason codes are a schema decision, not Vega instrumentation; A's time-sensitivity applies from the first real traffic, not to synthetic fixtures |
| R10 | Delegation chain | §3.1, test A-43: gateway verifies the first link (authenticated principal) and the last (authenticated caller); middle links recorded as reported | v1.2 §9.1. D01 N-06: RFC 8693 current actor is authority; nested `act` history is informational | Compatible. A's last-link check is the current-actor check; align vocabulary |
| R11 | Budget account | §5: reservations against a budget account named in `financial_scope`; the principal's or task's account now, the commission's from Valhalla step 3 | v1.2 §5.3 `financial_scope`; §10.8 scoped budgets | Compatible. Name the budget-account abstraction in v1.2 so a later change of authority does not change reservation logic. A's §5.1 table names Redis, which v1.2 §4.1 marks target-only |
| R12 | Classifying non-text content | §8.2: search queries are content; speech classified from source labels; results labelled external and untrusted. §8.4 and §11: transcripts inherit the audio's handling | v1.2 §5.1 control 3, §5.9, §13.5 | Largely compatible. Carry A's two reasons into §5.1 control 3: a search query discloses intent, and audio cannot be scanned cheaply |
| R13 | LiteLLM realtime logging | §8.3, test A-48: LiteLLM logs complete realtime responses to its logging integrations; restrict before realtime traffic | v1.2 §4.3–§4.4: frozen worker without direct egress; §13.2 allowlisted telemetry | Keep the requirement. A's support table reflects LiteLLM documentation on 23 October, not the frozen release v1.2 records (1.105.1); re-verify against that release |
| R14 | Direct calls and egress denial | §9, test A-45: over 100 direct calls outside Proto; inventory, migrate, revoke keys, deny egress; owners named | v1.2 §0.1 integration hold; §3 principle 1: full-platform coverage not claimed before integration | Integration work, consistent with the hold if placed in the later-integration roadmap |
| R15 | Valhalla step 3 and 4 items | §5, §6, tests A-50 to A-52: commission revocation at final dispatch, gate freshness, one label vocabulary, Neti consulting Trimorphus, budget authority moving to the Norns, activation epoch at final dispatch and acceptance | Not covered | Future integration requirements. Reference A as their source, or list them in §18 as open dependencies. No effect before Valhalla step 3 |
| R16 | Proto boundary and ADR 0051 | §7: P-15 provider seam, P-17 obligations by phase, field-to-region mapping | Not covered | Integration-side; defer explicitly |
| R17 | Cached synthesized phrases | §8.4: cache audio for a fixed set of fillers, after admission, under §5.6 | v1.2 §5.6: response caching deferred | Defer, consistent with v1.2 |
| R18 | Hosting context | §10: Cloud SQL while Mach33 runs on GCP; RDS after a planned move to AWS | v1.2 §14.3: cloud selection open; no comparative advantage asserted | A describes current hosting and a planned move, not a comparison. Record as planning context |

## 6. Acceptance-test identifier collision

Both documents number new tests from 42, with different subjects.

| ID | Addendum A subject | v1.2 subject |
|---|---|---|
| 42 | Empty shared field without a valid reason code refuses deployment | Unsupported or mismatched operation rejected before transmission |
| 43 | Delegation chain first or last link mismatch rejected | Saving a credential, browsing, refresh or preview makes no provider call |
| 44 | Commission reference recorded as `asserted`; no admission decision depends on it | Partial or failed discovery keeps an honest completeness state |
| 45 | Non-gateway speech, search or realtime traffic blocked by egress policy | Permission for one source, account or operation does not authorize another |
| 46 | Search query with a label the destination does not permit rejected | Mutation after admission detected |
| 47 | Failed realtime top-up closes the session (outcome conflicts, R5) | Python and JavaScript successor-contract parity |
| 48 | Complete realtime responses blocked from logging integrations | Native-unit pricing |
| 49 | Missing speech or search usage estimated, never zero (conflicts, R4) | Missing, null, zero and invalid quantities kept distinct |
| 50 | Commission revoked between final dispatch and transmission | Concurrent reservations, duplicates, restart and corrections |
| 51 | Realtime session closed on commission revocation (outcome conflicts, R5) | Embedding batch correspondence and bounds |
| 52 | Stale activation epoch refused | Same-dimension vector-space incompatibility |

v1.2's numbers are already cited by v1.2 §15.2 (proposed DEV-12 map: T-42, T-45–T-55, T-61, T-65, T-66) and by D01 N-05 (sub-IDs for T-45, T-48 and T-50 within this range). Addendum A's numbers are cited only inside Addendum A. Neither set is adopted.

**Suggested resolution, for owner decision:** keep v1.2's 42–76. Any Addendum A tests that survive reconciliation take new numbers from 77, keeping a crosswalk to their A-42 to A-52 origins. Settle this before the assurance register (D01 M-02) is created, because the register is keyed on test IDs.

## 7. Requested of the Correction 01 author

1. Add Addendum A draft 0.1 to the source basis, using the identity in `MANIFEST.sha256`.
2. Record decision 4 (Postgres, 23 October 2026) as an owner decision, and update §4.1, §18 item 10 and the D01 N-02 disposition accordingly.
3. Give every row R1–R18 a disposition (adopt, adopt with change, supersede, or defer) with a reason, inside the finding-to-clause map D01 §5 requires.
4. Resolve the conflicts in R4 and R5 in whichever text survives.
5. Choose names for the authority counter and the realtime connection counter (R7).
6. Resolve the test-number collision (§6) before creating the assurance register.
7. Do not treat Addendum A as adopted. Only the four decisions in §4 carry owner authority.

## 8. Limits

This is a comparison of documents. The reviewer did not have Valhalla 0.4, the Proto proposal and evidence report, Protecting Agency 0.2, the DEV-11 records or the 22 October research paper in this session. Addendum A's LiteLLM claims were not re-verified. No repository, implementation, credential or provider was inspected or changed. The reconstruction limits in §3 apply to `duranki-addendum-a.md`.
