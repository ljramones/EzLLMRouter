# DEV-12 A2 authentication projection clarification 01

**Date:** October 26, 2026 — America/Toronto. The reviewed source packet and relevant retained observations are dated October 27 in UTC.
**Owner:** Larry Mitchell.
**Status:** **Adopted for bounded A2 implementation by Larry's CONTINUE-03 forwarding.** The original supplied draft remains intact in the owner review package. This clarification grants no execution authority or independent acceptance.

## 1. Purpose and governing basis

The selected wire-0.3 recovery case returned HTTP401 with `INTENT_PERSIST_FAILED` and `retry_guidance:"never"` for an invalid old credential. Both exact clients correctly reject that combination: their declared persistence-failure mapping is HTTP503 with `query_first`. The retained observation is `case.ct02_recovery.wheel.continuation9.json`, `/payload/outcomes/old_credential_denial`, in the `281bd6f9d6d349b96b817c50f7e53c2db203fc19` review packet.

The contract already requires authentication failure to retain its inherited HTTP401 category. Its strict successor error schema has no `AUTHENTICATION_FAILED` enumerator. This clarification resolves that specific projection using an existing public code and shape.

The normative anchors are:

| Source | Relevant requirement |
| --- | --- |
| `docs/contracts/dev12-successor-01/CONTRACT.md`, “Selected surface and version boundary,” paragraphs at lines 9–11 | Inherits WP-A authentication and pre-admission 4xx categories; explicitly selected wire0.3; recovery does not reserve or send again. |
| `docs/contracts/wp-a-02/DURANKI-WP-A-CONTRACT-v0.2.md`, §6, line 81 | Version selection precedes authentication; authentication precedes body parsing; authentication failure is HTTP401; authenticated lookup outside scope is non-enumerating HTTP404. |
| `docs/contracts/dev12-successor-01/CONTRACT.md`, “Status, errors and storage boundary,” line 63 | Strict error shape; safe correlation and guidance; precise HTTP/SDK projection is A2 work. |
| `docs/contracts/dev12-successor-01/schemas.json`, `$defs.ErrorResponse` | Existing `POLICY_DENIED` code and `never` guidance; exactly four required fields; no additional properties. |
| `docs/development/dev-12/A2-RECOVERY-CLARIFICATION-01.md`, “Normative mapping” | Authenticated expired-content duplicate POST is HTTP403 / `POLICY_DENIED` / `query_first`; authorized historical status remains readable. |

The current generic fallback in `server/src/duranki_server/web.py:30–45` substitutes `INTENT_PERSIST_FAILED` for authentication failure while retaining HTTP401. Correct only the identified authentication projection. Do not hide unrelated errors behind a new generic denial fallback.

## 2. Normative authentication mapping upon adoption

After successful selection of wire **0.3**, a missing, malformed, invalid or revoked credential that fails the supported authentication boundary returns:

- HTTP **401**.
- Response header **`Duranki-Contract-Version: 0.3`**.
- The existing strict `ErrorResponse`, containing exactly `contract_version`, `code`, `correlation_id` and `retry_guidance`:

```json
{
  "contract_version": "0.3",
  "code": "POLICY_DENIED",
  "correlation_id": "error.authentication.synthetic.example",
  "retry_guidance": "never"
}
```

The example correlation value is illustrative. Generate a valid independent correlation ID for the actual response. Do not include a handle, attempt ID, result, principal, credential, safe-message extension or any other field.

This branch executes **before body parsing, WorkKey lookup, admission, reservation, signing or dispatch**. It discloses no fact about whether requested work exists. Preserve `AUTHENTICATION_FAILED` as the internal reason and in any permitted audit record; redact credentials. `POLICY_DENIED` is the bounded public projection of authentication refusal, not evidence that an authenticated policy decision, work lookup or intent-persistence operation occurred.

`never` means the client must not automatically retry the failed operation using the rejected credential. It does not erase previously admitted work. After authorized credential renewal, recovery uses the original submission ID or complete WorkKey under current read permission; it does not replay work or acquire a new WorkKey.

Routing/version errors retain their existing precedence. This clarification does not convert malformed or unsupported version selection into an authentication response.

## 3. Exact SDK acceptance and preserved mappings

Both Python and CommonJS successor validators must accept the additional tuple **HTTP401 / `POLICY_DENIED` / `never`** only when the response header, body version, correlation ID and complete strict shape are valid. This applies to the supported successor submit and status methods. Expose the typed public code, HTTP status, correlation and guidance while preserving the caller's immutable recovery selector. Do not synthesize server handles or attempts absent from the response.

The existing one-status `ERROR_HTTP` entries are insufficient for this precise exception. Implement a bounded tuple check rather than accepting arbitrary HTTP statuses for `POLICY_DENIED`, or arbitrary error codes on HTTP401. Both SDKs must reject HTTP401 with `INTENT_PERSIST_FAILED`, `POLICY_DENIED/query_first`, `POLICY_DENIED/after_replan`, invalid correlation, mismatched version or extra fields through their existing protocol-inconsistency behavior. Rejection retains the original selector and performs no automatic retry.

Preserve all of the following:

| Existing branch | Preserved behavior |
| --- | --- |
| Wire0.2 authentication failure | HTTP401 with its existing strict `AUTHENTICATION_FAILED` error projection. |
| Authenticated current status-access denial | HTTP404 `NOT_FOUND_OR_FORBIDDEN`, without enumerating work. |
| Authenticated expired-content duplicate POST | HTTP403 `POLICY_DENIED/query_first`, no added handle/attempt/result fields; subsequent authorized status remains HTTP200 with expired content and preserved finance. |
| Ordinary authenticated policy refusal | Existing HTTP403 mapping and restrictions. |
| Service/intent failure | Existing HTTP503 `INTENT_PERSIST_FAILED/query_first`; it is not an authentication fallback. |

Keep all eight accepted A1 normative files, historical manifests, schema enumerators, canonical/signing bytes, legacy defaults and existing conflict projections unchanged. Add no public enum, schema field, route or replay permission. Place the adopted clarification under `docs/development/dev-12/` and record the A2 mapping explicitly.

## 4. Focused verification with zero admissions and sends

Use the already permitted disposable authentication/HTTP assembly and retained completed work. No new synthetic attempt is needed.

1. Through actual HTTP, exercise missing/malformed authorization and invalid/revoked synthetic credentials on POST and both status-selector routes. Retain exact status, version header and safe body. Pair malformed JSON with failed authentication to establish rejection before body interpretation. Observe no WorkKey lookup or later admission/send stage for the authentication failure.
2. Renew or use a currently eligible synthetic credential for the same authorized principal. Both existing-work status selectors must recover the original handle, attempt and financial state. Pair current authenticated read denial with the unchanged HTTP404 behavior. Keep owner-profile credentials untouched.
3. Reuse adequate retained evidence for the HTTP403 expired-duplicate and HTTP503 intent branches; use bounded artifact fixtures where appropriate. Do not create a new intent-failure attempt merely to repeat an unchanged control. Logical retention tests must not move the real campaign deadline or machine clock.
4. Run the same valid HTTP401 tuple and discriminating invalid tuples through **both exact rebuilt artifacts**, with both selector forms and preserved selector context through transport. Retain input bytes, HTTP/header context, typed outcomes, request counts and artifact identity. Pair each negative family with a valid response; preserve the existing zero/native-evidence, strict byte and conflict checks.
5. Compare before/after submission, attempt, reservation, ownership, guard, receiver, usage and campaign records. No admission, reservation, signature, sender invocation or receiver arrival may be added. Expected authentication audit entries are distinguishable from financial or work mutations. Preserve existing holds, pauses, counters and expiry.

The current packages remain historical evidence: wheel SHA-256 `d4cdea6ffabd7aa62985040e4a92a4870d73dc8e4240f43d4472d86ce595bb98`; tarball SHA-256 `b871b64c98e299e031e4a6e11766a06e7a494f6e4b8b787fd70bfb8144694a3f`. Preserve those exact bytes. Build genuine corrected successors offline from existing frozen inputs, retain their new hashes and payload-to-source correspondence, and qualify the exact unpacked artifacts without dependency acquisition or publication.

This clarification grants no new campaign, admission allowance, sending permission, deadline extension or authority-pause release. Complete it through offline work and permitted retained-state HTTP checks; report any concrete remaining constraint without substituting a new scope.
