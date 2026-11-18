# DEV-07 review handoff — observed synthetic target

**Source:** `dev07/model-access-registries-20261021`, based on DEV-06 `17ba43aaeb28f5a40d48080f93d2553f1882e930`. First code checkpoint: `b2acc8f54d4db956f315ea3dee5c0ae6fd31f70c`. The owner target ran commit `7ead951b47c0bcebd0b25f174e0de685851ec5e2`, fingerprint `53702db06f40a3c3c51b742818ae27e5018c50a526be70b22ee2abcf1dea2040`. Review-documentation commits after that build do not change its running-source identity. No protected branch merge is requested.

## Changed implementation

- `server/src/duranki_server/registry.py`, `core.py`, `plans.py`, `operator_web.py`, `operator_projection.py`: additive trusted SQLite registry, strict management actions, private credential binding, signed decision link, live admission and first-write revision checks, synthetic price snapshots and safe usage projection.
- `web/index.html`, `app.js`, `app.css`: Models & Pricing and Users & Access list/detail/history/form views in the existing console. UI reads cannot send model work. Mutations require a current admin session, Origin and CSRF.
- `tests/gateway_integration/{proxy_recipe,choice_b_worker,guard,receiver}.py`: fixed second synthetic model selection through the actual LiteLLM worker and receiver. The worker remains network isolated; no arbitrary destination was added.
- `deploy/local/{prepare,profile,compose,dev07_run,provision}.py` and scoped Dockerfiles: checked offline staging, online pre-migration backup, pre-upgrade image builds, one-use finite target driver and private one-time provisioning.

## Local and target evidence

The operator suite passed 46 tests with Python 3.12 and local loopback permission; the existing core suite passed 22. Node 24.19 syntax checks and Python compilation passed. The owner target then ran the frozen signed-plan build and installed-client matrix. The private `deploy/local/.state/dev07-runs/dev07-20261021-01/result.json` reports `PASS`: 7 existing submissions preserved, 13 new receiver-correlated synthetic requests, one caller lookup, three actual-pool revocations with zero queued first acceptance, and a successful ordinary restart with revoked grant retained. `failure.json` is absent; upgrade and persistence restart exits are 0. A subsequent loopback GET returned HTTP 200, confirming the console was reachable when the owner reported a possible crash. This does not complete the browser walkthrough. The executor's recorded Docker denial remains; no Docker rerun was made for the diagnosis.

## Completed owner-Terminal invocation

The owner ran the one-use namespace with the existing artifact root:

```sh
DURANKI_ARTIFACT_ROOT=/Users/larrymitchell/Mach33/Duranki-artifacts/dev06-20261021-01 python3.12 /Users/larrymitchell/Mach33/Duranki/deploy/local/dev07_run.py dev07-20261021-01
```

The namespace is one-use and must not be repeated. The driver checked quiescence, stored an online SQLite backup, built scoped images and installed-client actors offline before replacing the running profile, and passed the frozen signed-plan preflight. It exercised the fixed 13-request inventory and zero-send negatives. Each revocation used a held control request, an observed queued attempt in the real owned pool, an acknowledged management mutation and independent receiver/send-event observations. Ordinary restart readback exited 0 and left the console running. There was no `down -v`, package reacquisition or real-provider route.

Raw run evidence stays private in `deploy/local/.state/dev07-runs/dev07-20261021-01/`, and the consistent backup stays in `.state/backups/`. The driver's safe `result.json`, `receiver-correlation.json`, mutation metadata, bounded stdout/stderr/exit records, receiver control log and pool/send observations are the normal target review inputs. The backup hash is `01c29584b035030005d1ee86425dca7854af7df318b3e198360d8147836890ea`. The script reported `PASS` after all assertions and restart readback passed.

## Bounded browser observation after a passing target

The owner captured the seven top-level page screenshots listed below. After the scoped service update, use `http://127.0.0.1:8780/` and the existing private `.state/operator-password` value for only the unobserved interactions: open existing Activity and no-store detail, open a real catalogue model detail and its source links, turn both fixture toggles on and off, use Tab and Enter through navigation, inspect read-only Explain access, and sign out. Do not click demos or submit management forms. Component tests already cover management writes; the current instruction preserves live grants and prices. Record safe counts or screenshots, never the credential, cookie, raw payload or database. This browser step is separate from the thirteen-request target inventory.

## Remaining boundaries

The living [RESULT.md](RESULT.md) tracks the actual pass/fail state. The target covers only local synthetic HTTP/1.1, single-process authority and the selected owned first-write mechanism. It does not qualify real providers, production budgets, distributed revocation, crash recovery, complete no-store erasure or the whole gateway. Git remote source backup and the frozen-input/recovery bundle are distinct; no off-machine artifact copy is claimed.

## Real catalogue and owner-name continuation

The scoped continuation adds the hash-checked twelve-entry research seed, strict reference-only registry import, authenticated importer, name-first catalogue and identity views, and a one-use target runner. The real entries have no provider destination or credential and remain `not_connected`. The existing owner is displayed as Larry Mitchell through an `edit_principal` operation; no other person is inferred from unapproved source material. Existing synthetic fixtures remain under visible test toggles, and historic activity is unchanged.

Local import/display/permission checks passed: 52 operator HTTP and registry tests with loopback access, 22 Coordinator core tests, and a Node display regression for all twelve entries and the rate boundaries. The owner ran the catalogue upgrade in the one-use namespace `catalogue-20261021-01`.

The namespace is one-use and completed with `PASS`. Private `deploy/local/.state/catalogue-runs/catalogue-20261021-01/result.json` records running source `0150b67e45d9af4e257fd9cd532f87b405158818`, fingerprint `1ca236ce6e50a5dfd7b89c4569d5b15d00db172e8b760e42e2cbf7d8dbc5e62b`, twelve imported disconnected entries, unchanged grants/prices, 20 receiver arrivals before and after, and successful ordinary restart readback. There is no failure record. A later retry collided with the existing run directory before any stage; do not repeat the upgrade. The runner now gives a clear no-overwrite message and the result location.

Authenticated read-only checks found 23 preserved submissions, twelve real entries plus three test configurations, the renamed owner, Activity/detail, Usage, Configuration and Build data, and Haiku's two bands with three source links. Live HTML and catalogue JavaScript loaded; sign-out invalidated the temporary session with a 401. The remaining browser step is a bounded visual and keyboard walkthrough of populated Models & Pricing and Users & Access list/detail, test toggles, conditional prices and source links, Activity/detail, Usage, Configuration, Build and sign-out. Capture safe screenshots without clicking demos. The running image remains at `0150b67`; this documentation and collision-message commit will be newer. The previous DEV-07 target `PASS` remains separately preserved.

## Activity and Usage follow-up

The owner supplied seven screenshots from catalogue commit `0150b67e`: [Overview](https://github.com/33fg/duranki/blob/018df8391c25ce326c017bf84eec634704d59c39/docs/development/dev-07/screenshots/overview-0150b67e.png), [Activity](https://github.com/33fg/duranki/blob/018df8391c25ce326c017bf84eec634704d59c39/docs/development/dev-07/screenshots/activity-0150b67e.png), [Usage](https://github.com/33fg/duranki/blob/018df8391c25ce326c017bf84eec634704d59c39/docs/development/dev-07/screenshots/usage-0150b67e.png), [Configuration](https://github.com/33fg/duranki/blob/018df8391c25ce326c017bf84eec634704d59c39/docs/development/dev-07/screenshots/configuration-0150b67e.png), [Models & Pricing](https://github.com/33fg/duranki/blob/018df8391c25ce326c017bf84eec634704d59c39/docs/development/dev-07/screenshots/models-pricing-0150b67e.png), [Users & Access](https://github.com/33fg/duranki/blob/018df8391c25ce326c017bf84eec634704d59c39/docs/development/dev-07/screenshots/users-access-0150b67e.png), and [Build](https://github.com/33fg/duranki/blob/018df8391c25ce326c017bf84eec634704d59c39/docs/development/dev-07/screenshots/build-0150b67e.png). These establish rendered top-level pages only. The Activity screenshot shows long technical IDs dominating rows. The Usage screenshot shows `Dispatched: 23`, while the completed DEV-07 target independently recorded three queued revocations with no first socket write and 20 receiver arrivals.

Source review found that `dispatched` counts persisted `guard_dispatches` receipts. A receipt commits before the owned lower pool, so it is not a transmission observation. The compatibility field remains a receipt count. The new Usage screen calls it **Final requests committed**, adds **Intents persisted**, **First write observed**, **No first write observed** and **Write observation unknown**, and explains receiver arrivals as separate evidence. The same definitions apply in per-step rows. First-write counts come only from attempt-linked trusted-sender events. Missing or conflicting events stay unknown. A regression exercises a committed lower-pool attempt revoked before first write and checks it contributes one receipt, zero first writes and one explicit no-first-write observation. No historical accounting row was rewritten.

Activity and Usage now show readable synthetic operation names, principal and configuration display names, state and time ahead of compact exact IDs. Detail retains exact task, step, generation, attempt and submission IDs. Technical IDs remain accessible by hovering or opening detail. The seven captured screenshots are historical source-build observations. The owner completed the scoped `usage_update.py usage-20261021-01` update with `PASS`: source `f02bb25a`, 23 submissions, 23 final-request receipts, 20 observed first writes, three observed no-first-write attempts and 20 receiver arrivals, unchanged before/after. It did not reimport the catalogue or rerun the thirteen-request matrix. The original source commits, catalogue PASS and collision records remain intact.

Run once in owner Terminal with Docker Desktop running; this creates a new one-use `usage-runs` namespace and preserves the completed catalogue namespace:

```sh
DURANKI_ARTIFACT_ROOT=/Users/larrymitchell/Mach33/Duranki-artifacts/dev06-20261021-01 python3.12 /Users/larrymitchell/Mach33/Duranki/deploy/local/usage_update.py usage-20261021-01
```

That command completed with the separate PASS receipt described above. Its namespace is one-use and must not be invoked again.

## Administrator CRUD continuation

Changed source: `server/src/duranki_server/catalogue.py` and `registry.py` add strictly validated operator-entered disconnected catalogue registration, versioned reference price snapshots, descriptive edit and explicit archive. `web/crud_view.js` supplies normal-screen Add/View/Edit/Delete, Update prices, Manage model access, history, archived filters, safe forms, focus and confirmation. `operator_web.py`, `prepare.py` and `index.html` serve and stage the new module. Historical imported records, executable synthetic routes and public clients retain their existing identities. New human/service identities begin inactive, unbound and ungranted; exact grant management cannot activate a reference-only model. Sender authority, session status checks, revision conflicts, idempotency, audit and last-admin protection remain in the existing registry path. No dependency or gateway change was made.

The [living result](RESULT.md) distinguishes local proof from the pending persistent-profile target. A disposable SQLite-backed operator service and actual headless Chrome completed the model and user create/edit/delete forms, two price snapshots, grant and removal, read-only Explain, unsaved Cancel, confirmation dialogs, archived filters, keyboard Tab and sign-out. Reopened SQLite retained both tombstones, the removed grant and the earlier price. Independent submissions, intents, final-request receipts and caller lookups stayed at zero. The first browser proof exposed cramped row actions; the second corrected the grid; the final [third result](CRUD-LOCAL-BROWSER-RESULT-03.json) and six linked screenshots checked the final layout and last-admin control. All three proof records remain preserved. These records use test-only model names and source placeholders; no publisher verification or real-provider route is claimed.

Local regression results: 60 operator Python tests passed with loopback permission, 46 existing core tests, 10 owned-sender transport tests, three Node screen regressions, Python compilation and `git diff --check`. The scoped browser runner uses a fresh private Chrome profile, keeps the existing operator credential out of logs, and removes the profile after sign-out. It writes target screenshots and safe result metadata into a one-use private `crud-runs` directory. The Docker executor denial still prevents a target build here.

### Fresh owner invocation

Run this **once** in the owner Terminal with Docker Desktop available. The `crud-20261021-01` path was checked absent; the runner refuses any collision without overwriting evidence:

```sh
DURANKI_ARTIFACT_ROOT=/Users/larrymitchell/Mach33/Duranki-artifacts/dev06-20261021-01 python3.12 /Users/larrymitchell/Mach33/Duranki/deploy/local/crud_target.py crud-20261021-01
```

It first backs up the live SQLite store and performs a service-only offline source update with byte-identical worker/receiver images. It then drives the **persistent profile** through the real browser controls using uniquely named disposable records, compares database/usage counters and independent receiver arrivals before and after, and restarts without clearing volumes. `deploy/local/.state/crud-runs/crud-20261021-01/result.json` records the service update; `browser-result.json` records the browser/restart result and screenshot hashes. Any failure has a separately named failure record. The 23 existing submissions and completed Run-11/DEV-05/DEV-07 evidence remain intact. Until the owner run returns `PASS`, the running image remains `f02bb25a` and target browser CRUD is open; the local Chrome proof does not substitute for that target observation.

The implementation and local browser evidence commit is `ef78763b5de9c7a420b44a16a40004e6cfdf1aa2`. It was pushed normally to `origin/dev07/model-access-registries-20261021`; an independent remote-ref read returned the same exact hash. The owner target records the later checkout tip that it stages, keeping running-source identity independently checkable.
