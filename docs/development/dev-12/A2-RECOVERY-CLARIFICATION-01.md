# DEV-12 A2 recovery clarification 01 — expired duplicate POST

**Date:** 26 October 2026
**Standing:** proposed in the independent partial review; adopted when Larry forwards the companion correction/completion instruction.
**Baseline:** accepted candidate 04; implementation reviewed at `f5affea3f36e7a949d570f7bf826a9708e0c1c99`.

## Why this clarification is necessary

The accepted A1 contract forbids recovery from reviving expired result bytes and preserves authorized completed/expired status. Its `SubmitReply.completed` schema requires a result, while its other POST branches mean pending, failed or outcome unknown. No existing POST success branch truthfully represents a known completed submission whose result has expired. This precise HTTP mapping was not previously adjudicated.

This clarification uses the existing `ErrorResponse` and GET status schemas. It introduces no error code, response branch, route, replay permission or change to canonical work. Preserve the eight accepted A1 files and their manifests unchanged; record this explicit A2 clarification in the development result and tests.

## Normative mapping

After authenticating the caller, validating strict request shape, resolving an existing full WorkKey, confirming same version/digest and current read permission, an exact duplicate POST for completed work whose trusted result-retention cutoff has been reached returns:

- HTTP **403**.
- The existing strict wire-0.3 `ErrorResponse`:
  - `contract_version:"0.3"`
  - `code:"POLICY_DENIED"`
  - independently generated `correlation_id`
  - `retry_guidance:"query_first"`
- No expired result, handle, attempt or other added fields in that error body.

The 403 refuses **return of expired content**. It does not change the durable completed state, deny an otherwise authorized historical status read, establish absence of prior work, or authorize new execution.

The caller uses its original selector through the existing authenticated `getStatus` WorkKey route, or its already-known submission ID. Both authorized GET forms return HTTP **200** with the original handle/attempt, `submission_state:"completed"`, `candidate_access:"expired"`, coherent permitted financial state and no result bytes.

Current denial remains non-enumerating under the existing access rules. Changed caller content/digest and cross-version reuse retain their existing conflict distinctions. The expired-result mapping applies only after successful exact-work/current-access resolution.

There is no new admission, reservation, signer call, executor invocation, automatic retry, new WorkKey or sender action. Never relabel the historical submission pending/failed/unknown to fit a POST branch.

## Implementation and focused checks

The current generic `web.py` error helper forces sub-500 errors to `retry_guidance:"never"`. Implement the specific recovery projection intentionally; merely raising an ordinary 403 is insufficient. Preserve unrelated policy-denial mappings.

Preserve immutable caller recovery context in both SDKs and expose query-first guidance. Do not add fields forbidden by the existing error schema or invent a server submission ID when none was previously received.

Verify before/at/after the independent retention cutoff, duplicate POST and both GET selectors, renewed authentication after the old execution deadline, current denied access, exact error body and SDK behavior. Assert unchanged attempt, reservation, send and result-availability origin. These are offline/service HTTP checks and need no provider or synthetic receiver send.
