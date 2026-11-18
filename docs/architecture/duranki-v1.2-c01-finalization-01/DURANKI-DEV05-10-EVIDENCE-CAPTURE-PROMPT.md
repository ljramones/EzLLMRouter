# Duranki — Read-only DEV-05–DEV-10 evidence capture

## Objective

Complete the C01 assurance register's historical evidence inputs, especially final DEV-07 and DEV-08–DEV-10. This is **record retrieval**, not implementation, testing, deployment, a new architecture cycle or permission to alter the repository.

Work from `/Users/larrymitchell/Mach33/Duranki`. Read existing instructions. Preserve HEAD, index, working-tree status and all one-use run records. Do not reset, clean, stage, commit, push, merge, build, install, start Docker, query the running application, register a key, make a provider call or instrument Vega.

## Source anchor

Use immutable commit `018df8391c25ce326c017bf84eec634704d59c39`, named by the supplied `docs/development/RETIREMENT-2026-10-25.json` and history index. Verify the commit exists locally and inspect its recorded relationship to DEV-11. Do not assume the current checkout is that version. No checkout change is needed: read committed bytes with `git show <commit>:<path>` or equivalent read-only Git plumbing.

`EVIDENCE-CAPTURE-PATHS.json` is the exact 22-path request and records the expected Git blob IDs from the retirement manifest. A Git blob ID is not a SHA-256 digest. Verify each object ID and separately calculate each exported file's SHA-256 and length. If an object is absent or differs, report the exact discrepancy; do not reconstruct it from conversation or mark it absent at all other locations. If newer result records exist, include them separately with their own commit/blob identities rather than overwriting the anchored copies.

## Requested record set

Capture RESULT.md and REVIEW-HANDOFF.md for DEV-05 through DEV-10, plus the listed final browser/installed-client/target/deployment receipts. The DEV-05 final independent review/source/runtime packets are already available to the author; do not rerun them. The final records needed beyond those living documents are:

- `docs/development/dev-07/CRUD-LOCAL-BROWSER-RESULT-03.json`
- `docs/development/dev-08/PROVIDER-APPROVAL-BROWSER-RESULT-04.json`
- `docs/development/dev-08/SOURCE-PAGES-BROWSER-RESULT-02.json`
- `docs/development/dev-09/INSTALLED-CLIENT-RESULT-01.json`
- `docs/development/dev-09/REPORT-BROWSER-RESULT-03.json`
- `docs/development/dev-09/TEAM-DEMO-ALIGNMENT-RESULT-02.json`
- `docs/development/dev-09/TEAM-DEMO-BROWSER-RESULT-04.json`
- `docs/development/dev-10/BROWSER-GENERATION-RESULT-01.json`
- `docs/development/dev-10/PROFILE-SETTLEMENT-RESULT-01.json`
- `docs/development/dev-10/TARGET-RESULT-08.json`

Read each result/receipt for the exact product-source commit, build fingerprint, observation date, controlled versus operational scope, explicit no-send evidence, and remaining limits. Preserve original failed runs and “not run” statements. An original result that predates a later receipt is historical, not proof the later work failed.

## Output and safeguards

Create one fresh collision-checked directory outside the repository and one portable ZIP. Include only these safe committed documents/receipts and any essential small linked validation or independent-review record needed to interpret them. Preserve exact original paths under an `anchored/` prefix. Do not copy credential files, environment dumps, session cookies, live SQLite databases, provider responses, arbitrary logs, frozen wheels or signing keys. If a requested record unexpectedly includes a secret, do not distribute the original: record the reason and provide a clearly identified redacted derivative with restricted original custody, never falsely label it byte-identical.

Include a self-excluding SHA-256 manifest, a JSON capture receipt (anchor commit, original path, Git blob ID, SHA-256, length, role and correspondence result) and a short availability table. Verify ZIP paths/types, CRC and exact manifest coverage. Record repository HEAD/index/status before and after; require no change caused by this capture. Do not use `git add` to save the output.

Return the bundle's actual absolute path, byte length and SHA-256, available/missing counts and any mismatch. No test pass is earned by retrieval. The architecture author will map the checked records to specific requirement/subcase scopes without inferring current deployment or complete v1.1 acceptance.
