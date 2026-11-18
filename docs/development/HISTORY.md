# Development history and retired evidence

The active tree keeps the frozen build inputs, catalogue test seed, living
result/review records, and one-use receipt files that guard historical run IDs
for DEV-04–DEV-10. Earlier screenshots, review packets, and other historical
records remain at immutable source commit
[`018df8391c25ce326c017bf84eec634704d59c39`](https://github.com/33fg/duranki/tree/018df8391c25ce326c017bf84eec634704d59c39/docs/development).
The approved `origin` branch `dev11/cache-aware-accounting` was checked at
that commit before this cleanup. The [exact 261-path classification](RETIREMENT-2026-10-25.json)
records the committed blob for every affected path: 49 active inputs (3
content files and 46 one-use collision guards), 15 governing records kept
here, 197 retired historical files, and no unresolved
tracked paths. There were no pending DEV-01–DEV-03 deletions.

| Slice | Living record | Evidence and retrieval |
| --- | --- | --- |
| DEV-04 | [Result](dev-04/RESULT.md); [final handoff](dev-04/DEV-04-CHOICE-B-HELD-TIMEOUT-HANDOFF-14.md); [independent review](dev-04/DEV-04-RUN11-INDEPENDENT-REVIEW-15.md) | [Run-11 validation](https://github.com/33fg/duranki/blob/018df8391c25ce326c017bf84eec634704d59c39/docs/development/dev-04/DEV-04-RUN11-INDEPENDENT-VALIDATION-15.json) |
| DEV-05 | [Result](dev-05/RESULT.md); [handoff](dev-05/REVIEW-HANDOFF.md) | [Run-16 review](https://github.com/33fg/duranki/blob/018df8391c25ce326c017bf84eec634704d59c39/docs/development/dev-05/DURANKI-DEV-05-RUN16-REVIEW-05.md) and [validation](https://github.com/33fg/duranki/blob/018df8391c25ce326c017bf84eec634704d59c39/docs/development/dev-05/DURANKI-DEV-05-RUN16-VALIDATION.json) |
| DEV-06 | [Result](dev-06/RESULT.md); [handoff](dev-06/REVIEW-HANDOFF.md) | [Owner audit](https://github.com/33fg/duranki/blob/018df8391c25ce326c017bf84eec634704d59c39/docs/development/dev-06/evidence/owner-audit-20261021-05/MANIFEST.json), [persistence](https://github.com/33fg/duranki/blob/018df8391c25ce326c017bf84eec634704d59c39/docs/development/dev-06/evidence/owner-persistence-20261021-06/MANIFEST.json), [browser](https://github.com/33fg/duranki/blob/018df8391c25ce326c017bf84eec634704d59c39/docs/development/dev-06/evidence/browser-walkthrough-20261021-07/MANIFEST.json), and the [dated artifact index](https://github.com/33fg/duranki/blob/018df8391c25ce326c017bf84eec634704d59c39/docs/development/dev-06/ARTIFACT-INDEX.json) |
| DEV-07 | [Result](dev-07/RESULT.md); [handoff](dev-07/REVIEW-HANDOFF.md) | [Final local catalogue browser result](dev-07/CRUD-LOCAL-BROWSER-RESULT-03.json) |
| DEV-08 | [Result](dev-08/RESULT.md); [handoff](dev-08/REVIEW-HANDOFF.md) | [Source pages](dev-08/SOURCE-PAGES-BROWSER-RESULT-02.json) and [provider approval](dev-08/PROVIDER-APPROVAL-BROWSER-RESULT-04.json) |
| DEV-09 | [Result](dev-09/RESULT.md); [handoff](dev-09/REVIEW-HANDOFF.md) | [Team demo](dev-09/TEAM-DEMO-BROWSER-RESULT-04.json) and [timeline alignment](dev-09/TEAM-DEMO-ALIGNMENT-RESULT-02.json) |
| DEV-10 | [Result](dev-10/RESULT.md); [handoff](dev-10/REVIEW-HANDOFF.md) | [Target result 08](dev-10/TARGET-RESULT-08.json), [browser generation](dev-10/BROWSER-GENERATION-RESULT-01.json), and [preserving deployment](dev-10/PROFILE-SETTLEMENT-RESULT-01.json) |
| DEV-11 | [Current result](dev-11/RESULT.md); [handoff](dev-11/REVIEW-HANDOFF.md) | Current controlled evidence remains in the active tree. |

Retrieve an exact retired file with `git show 018df8391c25ce326c017bf84eec634704d59c39:<path-from-manifest>`.
The retained [gateway lock](dev-04/requirements.gateway.lock), [wheel inventory](dev-04/WHEEL-INVENTORY.json),
and [catalogue seed](dev-07/DURANKI-REAL-MODEL-CATALOGUE-20261021.json)
remain at their existing paths because preparation and tests read them there.
Relative screenshot paths inside retained one-use JSON receipts describe their
historical run; resolve them against the fixed commit, without editing the
receipts or reusing their run IDs.

This Git history covers committed files only. Ignored frozen wheels, local
archives, generated credentials, operational volumes, and any uncommitted or
excluded evidence require their own custody; the old DEV-06 artifact index is
a dated observation, not proof of a current off-machine backup.
