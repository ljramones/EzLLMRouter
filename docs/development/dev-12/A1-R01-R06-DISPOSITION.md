# DEV-12/A1 candidate-04 focused dispositions

Candidates 01 (`0ee1d9086c2dc1f1ec00c5390020f34103d49235`), 02 (`74205342077b0e72ffe28a8d58b0983cc41956cd`) and 03 (`15cfeaa21e711c2247492711b1aca16d62f29531`) remain immutable in Git and their exact exports. This record identifies candidate-04 **offline contract** corrections for focused delta review; it does not claim A2 runtime acceptance. The [contract](../../contracts/dev12-successor-01/CONTRACT.md), [schemas](../../contracts/dev12-successor-01/schemas.json), [vectors](../../contracts/dev12-successor-01/vectors.json), [reference checker](../../contracts/dev12-successor-01/conformance/reference.cjs) and [tests](../../contracts/dev12-successor-01/conformance/check.cjs) are the operative bytes.

## Original A1-R01–R06

| Group | Candidate-04 disposition |
| --- | --- |
| R01 — caller omission and assessment | Preserved candidate-02 correction: absent commission remains absent in work, explicit declaration changes work, server assessment remains separate. Four canonical examples and the independent Python projection remain passing. |
| R02 — strict decoding and shape | Preserved candidate-02 correction: byte-oriented decoder, own-property-safe schema walker, bounded JSON/Unicode/calendar cases. The unchanged negative corpus remains passing. |
| R03 — result correlation and compatibility | Complete at this offline scope: full registered embedding tuple and ordered result checks remain; `replyValid` and `statusValid` now require an independently supplied expected submission ID as well as WorkKey and attempt. Wrong-submission positives/negatives appear in the JS checker. |
| R04 — signed plan and preparation | Complete at this offline scope: full signing-message bytes remain; synthetic `ExecutionEligibilityContext` independently supplies key tuple/material/eligibility, current revisions, activation, reservation/owner, expected IDs and time. Fixed 5000 ms timeout is enforced in schema and semantics. The checker covers tampering, correctly signed wrong context, rotation/revocation, tagged activation and expiry boundaries. Runtime sender/key custody remain A3. |
| R05 — native usage, tariffs and revisions | Complete at this offline scope: original four fictional price contracts and all tariff rows unchanged. Usage revisions use the actual accepted same-attempt history, immutable stored-plan/reservation context and effective-row reduction. The prospective accepted history must also validate, including at the 32-row offline capacity. Unknown and over-bound remain distinct. The JS checker covers replacement, duplicate/conflict, foreign/fabricated/stale/forked history, capacity and two-attempt totals; Python independently checks price and historical bytes. |
| R06 — public lifecycle and handling | Complete at this offline scope: fixed-public restriction and status/recovery surface remain; completed expired content is representable without result bytes while retaining handle/usage/amount. Independent retention origin/cutoff/time governs expiry. Outer settlement exactly tracks the accepted effective usage state; pending means no effective row. Runtime retention/storage/read controls remain A2–A4. |

## Candidate-02 review-local C02-01–C02-06

| Finding | Changed clause, data and decisive cases |
| --- | --- |
| C02-01 | Contract “Correlated results”; `replyValid` and `statusValid` in `reference.cjs`; complete `COMPLETED` and `STATUS_VALID_UNKNOWN_COST` positives plus single-field wrong-submission negatives in `check.cjs`. Expected ID comes from plan/stored history, never response. |
| C02-02 | Contract “Signed plan”; `ExecutionEligibilityContext`/`SyntheticVerificationKey` schemas, `execution_eligibility_context` and `activation_tagged_fixture` vectors, `signatureValid` + `executionEligible`. Signed-binding matrix, independently mismatched context, wrong key, unknown/revoked key, plan revocation, ordinary minting rotation, all named revision mismatches and before/at/after expiry cases. |
| C02-03 | Contract fixed timeout; `ExecutionDescriptor.timeout_ms:const 5000`; static `nonconforming_timeout_fixture` with matching recipe and valid signature. Its complete plan fails fixed-profile shape/semantics/eligibility while the original 5000 ms plan passes. |
| C02-04 | Contract “Historical usage”; `HistoricalUsageContext`, `historical_contexts` and `historical_underbound` vectors; `acceptedHistoryValid`, `usageValid`, `acceptUsage`, `effectiveTotals` and history-backed `statusValid`. Actual same-attempt predecessor, no-op duplicate, conflict and two distinct latest attempts are checked. Candidate 04 also closes the C03-01 successor-capacity defect below. |
| C02-05 | Contract “Status”; `RetentionContext`, `retention_context` and `STATUS_EXPIRED_*` fixtures. Valid calculated, unknown and over-bound expired statuses retain finance; missing/early/false cutoff and content-presence contradictions reject. |
| C02-06 | Contract settlement mapping; `statusValid` requires `pending` only before an effective row and exact later `calculated`/`unknown`/`over_bound` equality. The checker rejects unknown-as-over-bound and over-bound-as-unknown, including after content expiry. |

## Candidate-03 review-local C03-01

| Finding | Changed clause, reference and decisive cases |
| --- | --- |
| C03-01 / C02-04 / A1-R05–R06 | Contract “Historical usage” now identifies 32 as an offline reference-context capacity and requires the prospective accepted history to remain valid. `usageValid` in `reference.cjs` checks that prospective context; `acceptUsage` retains duplicate-before-append behavior. The 19 new `check.cjs` assertions cover the final permitted append, known effective amount, expiry-preserved financial status, overflow rejection with byte-identical prior history, readable latest row and once-only totals, identical duplicate no-op and conflicting duplicate rejection. Capacity rejection is not a zero-cost or resend decision; actual late observations require later qualified storage. |

Candidate-02 and candidate-03 reviewer defect-characterization scripts/results remain in their supplied immutable review packages as historical evidence, not candidate-04 acceptance tests. The existing 22-path historical capture and its limits are unchanged. No product execution, database migration, provider use, credential handling or owner-profile update occurred in A1.
