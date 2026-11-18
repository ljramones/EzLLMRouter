# WP-A/A2 Contract Adoption 01

**Owner decision — LM-01, 17 October 2026:** `WP_A_A2_CONTRACT_ADOPTED_FOR_INITIAL_PROFILE`.

LM-01 adopts DEC-04 through DEC-08 as written in the five-file WP-A/A1 v0.3 Correction 01 candidate. This adoption governs the bounded initial interface and capability profile. The candidate's historical `PROPOSED` and `NOT_RUN` labels remain unchanged; this additive record is the adoption authority. A03-01 and A03-02 are **closed at the specification and inert-data level** on [Independent Review 04](/Users/larrymitchell/Downloads/DURANKI-WP-A-v0.3-C01-INDEPENDENT-REVIEW-04.md), not as runtime acceptance.

## Adopted decisions

- **DEC-04 — Work identity and source authority:** adopt the server-authoritative `duranki-work-v0.2` projection, restricted canonical serialization, source/effective prompt digest distinction, resolved references, stable semantic context identity and current handling checks.
- **DEC-05 — Results and outcomes:** adopt live candidate delivery, pending/status recovery, separate attempt/cancellation/outcome states, caller-owned substantive acceptance, and the documented known-failure mappings before and after transmission.
- **DEC-06 — Initial authorization and capabilities:** adopt `initial_1a@1` fixed approved destination, content-derived feature checks, signed plan, current final-dispatch check and durable intent; retain the candidate's disabled-capability and no-fallback boundaries.
- **DEC-07 — Accounting:** adopt partial known/unknown usage, independent cost status, latest-replacement revisions, protected raw-report references and the specified public usage view. A failure does not imply zero usage or charge.
- **DEC-08 — Client and adapter contract:** adopt wire `0.2`, the independent Python/JavaScript network-client method meanings, version/error handling, bounded wait, and preserve-or-reject final-request binding. The document correction label does not change the wire, projection or profile identifiers.

**Explicit no-store approval:** no-store work may use live-only candidate delivery. On ordinary response-wait expiry, the service may return `202` with `pending_result_policy:metadata_only_no_store`. A later model result may incur a charge yet be unavailable to the caller: prohibited content is not stored, polling cannot retrieve the candidate, and the SDK does not replay automatically. This consequence is accepted for this initial profile. The adopted response-wait default is **1000 ms**; explicit `wait_ms` accepts integers **0–30000 ms** inclusive, under the candidate's header, deadline, timeout and disconnect rules. Known post-transmission remote or unusable-output failures use the candidate's attempt-bound live `502` and stored-status mapping; unknown remote outcomes remain distinct.

## Exact adopted artifact receipts

These local files were rehashed and byte-counted against Independent Review 04 §6 before this record was written.

| Candidate artifact | Bytes | SHA-256 |
|---|---:|---|
| [Contract](wp-a-03-c01/DURANKI-WP-A-CONTRACT-v0.3-CORRECTION-01.md) | 44,461 | `f43c79f8d8bd65085f886fe1bf4b6851192ca241780b0b00d574c088da6f99c1` |
| [Schemas](wp-a-03-c01/DURANKI-WP-A-SCHEMAS-v0.3-CORRECTION-01.json) | 69,500 | `f8d753aa4e11998c483da5dc6dfea6afbf7d482dad34973904e936dcb3b3068b` |
| [Vectors](wp-a-03-c01/DURANKI-WP-A-VECTORS-v0.3-CORRECTION-01.json) | 237,703 | `ea51d2d207d97ace357186ff762c09917c29674666c4307b6fe77ecf65993b38` |
| [Decisions](wp-a-03-c01/DURANKI-WP-A-DECISIONS-v0.3-CORRECTION-01.md) | 9,320 | `701ccc48a9ea3338a0f5e71c9ff9d1ab728d1fda1c67c1f4b34318e6b0a39b60` |
| [Return](wp-a-03-c01/DURANKI-WP-A-RETURN-03-CORRECTION-01.json) | 11,809 | `9613750b778538af3bf2d889dcd4888af9be9cce11016df6a5ba65694bd0f37a` |

**Review receipt:** `/Users/larrymitchell/Downloads/DURANKI-WP-A-v0.3-C01-INDEPENDENT-REVIEW-04.md`, SHA-256 `330dda3e8ba4a092518c625436b48b6ed95528d7862f4ae2729b6f3c5624ec4c`. **Independent validation receipt:** `/Users/larrymitchell/Downloads/DURANKI-WP-A-v0.3-C01-REVIEW-VALIDATION-04.json`, SHA-256 `72630b26a8080ee0a091efed357fb0a5e90ab42e06c1fdb1e77dd162bca684ac`.

## Scope and remaining proof

This is an **initial contract adoption**, not selection or approval of an actual provider configuration, price/usage partition, issuer/key, gateway release, deployment or real-data cohort. Real authentication and source resolution, classification and retention enforcement, cryptographic signing, adapter binding, final transmission interception, durable intent/no-send proof, status/accounting durability, installed-client parity, concurrency/recovery/hard exposure and representative workload/operational acceptance remain for separately issued work. No runtime, signature, gateway or operational test is marked `PASS` by this decision.

WP-FND remains closed with its accepted evidence and historical variances preserved. This record does not renew its execution exception, authorize Git writes or issue WP-B, WP-C, services, provider calls or Vega integration.
