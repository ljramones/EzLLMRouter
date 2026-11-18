# DEV-11 result — cache-aware accounting for bounded Responses text

**Status:** source implementation and isolated controlled target/browser checks
passed. **Paid provider execution remains off.** The tested clean product
source is `86d1c8cb0d99c31660f8ef7ad7464e1b40e670f4`, tree
`2d951bacbf938bec2127d4b1b902426ca3d4bffb`, frozen build fingerprint
`e3157e9e235d8980d00ba6d264cca528e5beac5d09f981839221f9259b84e981`.
The implementation branch is `dev11/cache-aware-accounting`, descended from
DEV-10 `882e9c1` through the evidence-only assessment commit `7e66207`.
The frozen input custody is
`/Users/larrymitchell/Mach33/Duranki-artifacts/dev09-certifi-20261022-01`.
Its gateway lock still pins LiteLLM 1.105.1 (SHA-256
`beb5044645144308b39560049c0f68875ad7de07e681ad0b73e2bc6c3705ba61`),
OpenAI SDK 2.54.0 and certifi 2026.10.19. No dependency was upgraded.

## What changed

The [versioned contract](CACHE-ACCOUNTING-CONTRACT.md) binds an exact
Responses model, supported implicit 30-minute cache behavior, reviewed
context/output limits, four immutable USD token rates and their source/date.
Existing provider two-rate records remain historical and cannot activate a
new paid personal campaign. The same exact-decimal evaluator bounds exposure
for Coordinator policy and atomic campaign reservation. It charges all
possible input at the highest disjoint input-category rate and bounded total
output. Model, price, credential and grant revisions still gate first send.

The frozen worker now serializes only fields actually set in its parsed
response. The sender allowlists and preserves reported `total_tokens`, input
and output totals, cached reads, aggregate writes, write-lifetime details and
reasoning details. The ledger retains only bounded accounting metadata,
presence states and the raw usage digest. The v0.2 installed-client wire is
projected to its existing strict categories; the authenticated operator
projection displays the richer persisted breakdown. Prompt, response and
secret retention rules were not broadened.

The normal provider result and activity detail now show total input first,
ordinary input, cached reads, 30-minute priced writes, total output and its
reasoning subset, calculated cost, contract/price versions, reserved exposure
and remaining allowance. Missing or contradictory evidence is visibly
unknown rather than zero. The registry form requires an operator's explicit
review of the exact model's rate, context, temperature and cache conditions;
publishing a schedule alone does not activate generation.

## Controlled observations

- [Final target matrix](TARGET-RESULT-02.json): the **clean** frozen
  service/worker images ran five installed Python-client requests through
  Coordinator, signed plan, isolated worker, final guard, trusted sender,
  independent local TLS receiver, usage revision and campaign settlement.
  Each separate one-use namespace had exactly one intended arrival, guard
  commit and first-byte send; duplicate submission and status read added zero
  sends. The mixed response had 120 total input = **20 ordinary + 70 reads +
  30 writes**, 20 total output including two reasoning tokens. At fictional
  rates of USD 1, 0.1, 1.25 and 2 per million, independent arithmetic gives
  **USD 0.000104500**. Read-only and explicit-zero cases calculated
  **USD 0.000097000** and **USD 0.000160000**. Missing and explicit-null write
  counters stayed distinct, yielded unknown cost, paused the campaign and
  retained the full **USD 0.001314000** exposure. A reviewed fictional
  1,000-token input ceiling and 32-token output limit yielded that same
  reserved bound. There were no real provider calls. The earlier
  [single-case target receipt](TARGET-RESULT-01.json) remains historical.
- [Final browser result](BROWSER-RESULT-02.json) and [safe result screenshot](browser-20261025-03/dev11-cache-controlled-generation-result.png): the normal authenticated **Run one live test** button on the final clean disposable service displayed `Hello.`, the full token breakdown, calculated cost, price/contract, reservation, **1 / 1** request count, zero outstanding exposure and **USD 0.019895500** available from a fictional USD 0.02 allowance. A same-form double click was disabled. Refresh and status made authenticated local read-only GETs; the independent receiver still had one arrival. The post-click SQLite/guard/sender/receiver audit found one submission, intent, attempt, usage revision, guard commit, first-byte send and arrival. This screenshot contains synthetic identifiers and no credential. The [earlier browser receipt](BROWSER-RESULT-01.json) remains historical.
- Focused frozen-image regressions: **6** cache arithmetic/validation cases,
  **8** campaign cases (race, unknown restart, historical price refusal,
  over-bound persistence and once-only correction), **2** registry/Coordinator
  cases, and **1** frozen LiteLLM parser → sender presence case passed.
  The parser case checked absent, explicit null, zero and write-bearing fields
  with the installed frozen type. `node tests/operator_console/test_activity_usage_view.cjs`
  passed; modified UI scripts passed `node --check`. Source syntax and
  `git diff --check` passed. The earlier DEV-10 installed-client matrix,
  worker-isolation and no-retry evidence was reused, not rerun wholesale.
- Initial prepare with the old DEV-06 artifact custody correctly rejected its
  certifi 2026.10.18 wheel. The subsequent prepare/build used the existing
  certifi 2026.10.19 custody and succeeded. The disposable diagnostic target
  namespaces `01`–`03` exposed and corrected a missing trusted test template,
  strict client-wire extension and status selector in the new harness. The
  later missing-counter client-wire correction is in source `86d1c8c`; the
  final five-case target `01` matrix and browser `03` ran its clean images.
  Disposable containers and link volumes were removed; no operational
  profile was restarted.

## Assessment finding disposition

| Finding | DEV-11 disposition |
| --- | --- |
| F1 reservation may omit expensive cold writes | Closed for the new eligible contract by a reviewed context ceiling and maximum disjoint input rate. The old provider price remains ineligible for a new campaign. No observed prior overspend is claimed. |
| F2 cache usage unknown and mixed categories wrong | Closed for complete 30-minute observations; reads/writes are disjoint and costed. Other cache modes remain unknown. |
| F3 absent write becomes zero | Closed for the new contract across frozen parsing, sender and ledger. Absent/null/invalid required counters retain exposure. Historical rows are unchanged. |
| F4 explicit controls absent | Deferred by design: only implicit/default behavior is admitted. No 12-hour TTL, key or breakpoint controls were added. |
| F5 incomplete provider price schema/history | Four-category immutable contract and bounded allowlisted observations added. Storage, other providers, complex tiers and invoice ingestion remain deferred. Existing revision reconciliation still applies a linked correction once; no backfill or invoice claim was made. |
| F6 documentation mismatch | Contract and UI now describe this tool-free text route and fictional controlled evidence accurately. |
| F7 external caching hypothesis | Deferred; no external cache or efficiency claim was added. |

## Source versus running profile and remaining limits

At final read-only Docker inspection, the owner service and worker still used
`duranki-dev06-*:525e11d9ba47d453`, the previously recorded DEV-10 source
`2bb04ff7dd4c584d09bcbcce3fe3e4c0ce0d1ef9`. DEV-11 images are staged
only. No owner database, vault, grants, permissions, prices, campaign or
operational history were read or changed for this run; the running profile's
current campaign/data state was **not queried**. The prior DEV-10 receipt's
unconfigured campaign is historical, not a fresh current-state assertion.

No exact commercial model, rate, context limit, currency choice, personal
key, request count or spending amount was selected for Larry. The synthetic
receiver proves software-path behavior, not provider acceptance, actual cache
residency, latency savings, tax/account-wide spend or invoice accuracy. A
model that cannot support `temperature:0`, report the required counters or
fit one reviewed price tier is ineligible under this version. The frozen
types and guard still do not authorize explicit 12-hour controls. No
commercial-provider cache test, owner deployment or paid activation occurred.
An owner deployment later requires the existing preserving backup and
build-before-stop workflow, a reviewed exact contract/rate and deliberate
finite local activation and invocation; this DEV-11 checkpoint is not that
authorization.
