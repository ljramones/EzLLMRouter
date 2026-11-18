# DEV-12 focused legacy cross-version conflict clarification 01

**Date:** 26 October 2026
**Adoption:** effective when Larry forwards the companion Completion 02 instruction.

## Decision

Preserve the accepted full authenticated WorkKey across wire versions. Reuse of an owned key under the other version is a conflict and must not create another admission, reservation, attempt or send.

Use the response contract explicitly selected by the caller:

| Selected wire | HTTP status | Error code | Retry guidance |
| --- | --- | --- | --- |
| 0.2 | 409 | WORK_CONFLICT | never |
| 0.3 | 409 | WORK_VERSION_CONFLICT | never |

Retain the more specific cross-version reason in internal/audit records. Keep the existing strict error shape for each wire. No additional fields, wire version, schema enum or SDK relaxation is introduced.

## Reason

The accepted successor text says cross-version reuse yields WORK_VERSION_CONFLICT and also preserves exact wire-0.2 semantics. The preserved legacy error schema and both legacy clients do not admit that newer code. The general successor wording therefore needs this explicit legacy projection.

This is a newly explicit implementation clarification. It is not a claim that A1 independently adjudicated this mapping. Preserve all immutable A1 and legacy schema/vector bytes.

## Verification

Exercise both admission orders, same-version changed-content conflicts and the normal-HTTP concurrent race through both rebuilt installed clients. Exactly one version owns a new key; the losing request receives its own wire’s mapped error. Verify strict shape, HTTP status, guidance and zero extra ownership/reservation/attempt/send. Successful same-version recovery stays unchanged.

Record adoption in docs/development/dev-12/A2-LEGACY-CONFLICT-CLARIFICATION-01.md and the living result.
