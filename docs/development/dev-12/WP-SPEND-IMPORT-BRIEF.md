# WP-SPEND-IMPORT — scoped preparation brief

**Status:** prepared after [DEV-12 delivery exception 01](DELIVERY-EXCEPTION-01.md). This is a separate work-package brief, not implementation, format adoption, real-data acceptance or target authority. Its basis is [Implementation Phase Plan §B](../../plan/Duranki-Implementation-Phase-Plan.md) and the adopted [roadmap §6](../../architecture/duranki-v1.2-c01-finalization-01/DURANKI-v1.2-C01-ROADMAP.md).

## Input and first-format decision

No owner-supplied provider account usage/cost export format or sanitized representative sample was found among the supplied disposition/Continue05 materials or the repository/Downloads filenames inspected for this preparation. **The single missing input is an actual owner-supplied export format and representative sample, with its source documentation if needed.** Select and declare one supported format from that material in the separate implementation package. Do not infer a provider schema, seek account access, download automatically or request credentials. Synthetic fixtures can establish engineering behavior before real-data acceptance.

## Bounded implementation scope to commission separately

Build an **offline** importer for explicitly supplied account exports. Preserve original file content identity and file owner, provider/account scope, currency, period and timezone, observation/import timestamps, source schema/version, row granularity, native units and cost basis, credits/adjustments, and correction/replacement provenance. Keep raw source identity distinct from normalized observations and from existing controlled-attempt charges. Map only fields the selected format actually supports. Unknown user, agent, task, operation and financial owner stay unknown; no inferred delegation or task acceptance. No currency conversion without an independently adopted rate and scope.

Use an idempotent receipt for identical content, including differently named copies. Detect period and row overlap across files; do not add ambiguous overlaps to totals. A correction or replacement must identify the superseded contribution and produce one effective amount without erasing provenance. Link a supported imported observation to a controlled attempt by reconciliation rather than adding a second charge. Preserve original native values and show reporting totals at the actual source granularity. Use existing accounting and authorized report/export surfaces where suitable; no second provider-attempt ledger or live polling route is implied.

## Focused acceptance inventory

| Case | Required observation |
| --- | --- |
| Identical file and renamed identical content | Original receipt recovered; no added amount |
| Distinct files with same period, partial overlaps | Supported disjoint rows counted once; ambiguous overlap flagged and excluded from additive totals |
| Correction and replacement | Effective amount changes once; original and superseding provenance remain inspectable |
| Multiple currencies and mismatched timezones | No silent conversion or period merging; boundaries and source timezone visible |
| Invalid values or unsupported schema | Fail or quarantine without changing accepted totals |
| Unresolved attribution | Unknown dimensions stay unknown in details and exports |
| Controlled-attempt linkage | One expenditure after reconciliation, with both source identities visible |
| Authorized readback | Filtered JSON/CSV and UI totals reconcile; cross-principal denial holds |

Use architecture assurance subcases **T-73.a–e** for external observations and **T-62.a–e** for time, latest-effective revision, common filter set, export reconciliation and access control. Include synthetic duplicate/overlap/correction fixtures and an independent total check. Real-data acceptance waits for the actual export; account-level spend alone does not prove invoice accuracy, accepted-task cost or agent efficiency.

**Out of scope for this preparation:** implementation, migrations, owner-profile deployment, provider login, automatic downloads, model calls, real spend, Vega, PostgreSQL qualification and promotion of DEV-12 CT02-02b. A later implementation instruction must set its own precise scope and authority.
