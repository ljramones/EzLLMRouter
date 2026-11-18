# DEV-11 review handoff

**Branch:** `dev11/cache-aware-accounting` (normal push requested by adopted
brief). **Tested source:** `86d1c8cb0d99c31660f8ef7ad7464e1b40e670f4`,
tree `2d951bacbf938bec2127d4b1b902426ca3d4bffb`, frozen build
`e3157e9e235d8980d00ba6d264cca528e5beac5d09f981839221f9259b84e981`.
The documentation/screenshot commit is a later branch descendant and does
not change the tested service/worker product code.

Review [RESULT.md](RESULT.md), the [contract](CACHE-ACCOUNTING-CONTRACT.md),
[final target matrix](TARGET-RESULT-02.json), [final browser receipt](BROWSER-RESULT-02.json)
and [safe result screenshot](browser-20261025-03/dev11-cache-controlled-generation-result.png).
The prior [target](TARGET-RESULT-01.json) and [browser](BROWSER-RESULT-01.json)
receipts remain historical checkpoints.
The assessment and original defect-characterizing probe remain preserved in
their separate evidence-only commit `7e66207`; the new regression suite uses
corrected expectations.

Each of the five clean target cases had one controlled TLS arrival, one guard
commit and one first-byte send. Mixed/read/zero calculated USD 0.000104500,
0.000097000 and 0.000160000 respectively against USD 0.001314000 reserved.
Missing and null write counters kept cost unknown and the full reservation.
The normal browser showed the same split and USD 0.019895500 remaining after
one fictional request; authenticated refresh/status GETs added no send.
Focused frozen-image regressions passed (6 cache, 8 campaign, 2 registry,
1 parser/sender) plus the affected Node usage view check. All Docker test
resources were disposable and removed. No real provider call or operational
profile update occurred.

The running owner profile still uses the prior DEV-10 image tag
`525e11d9ba47d453`. DEV-11 requires a later separately reviewed preserving
deployment before it can run there. No key/model/rate/allowance was chosen.
Explicit cache controls, non-premium/other provider variants, complex pricing,
invoice reconciliation and real cache-performance claims remain outside this
contract. A successful synthetic proof is not paid-provider acceptance.
