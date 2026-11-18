# Mach33 activity demo load — local result, 2026-11-04

## Installed identity and scope

The installed integration-only operator is Duranki **0.2.16** at `http://127.0.0.1:48885/integration` (API 48884). Its offline wheel is `server/dist/mach33_duranki_server-0.2.16-py3-none-any.whl`, SHA-256 `4eef68797998e54dbeb02ebc5bdf92072c936462f78ada13c611f854476f8701`. Duranki source remains at `b84c5b1037b2fdc02a8547c73af499e4a63ea53e` on `dev12/operation-contract`, with uncommitted changes. The companion platform worktree remains at `a9b48b05274e41db1b2aeb161109bf81d3ca3dcd` on `platform/feat/duranki-integration`, also uncommitted. No branch was reset, merged, pushed or deployed.

The input archive is `/Users/larrymitchell/Downloads/DURANKI-MACH33-DEMO-DATA-2026-11-04.zip`, SHA-256 `b0e4ae848f9a77dae57e97305084a3f8d72d4ac43e91ec1224b71dc2004e740f`. Its `validate_demo.py` passed **32,404 checks**. Every manifest-listed file matched its declared length and SHA-256 before loading. The selected dataset is `demo.dataset.mach33.activity.20261104.v1`, displayed as **Mach 33 activity demo — 14 days**. Its fixed range is **2026-10-22 through 2026-11-04** in `America/Toronto`; the report cutoff is **2026-11-04T17:00:00Z**. These are scripted demonstrations, not measured Vega activity or real expenditure.

The imported scope is `/Users/larrymitchell/Mach33/mach33-platform-duranki-integration/.mach33-local/duranki-instance/mach33-activity-demo-20261104-01/`. Its directory is mode `0700`; `fixture.json` and `scope.json` are mode `0600`. The fixture SHA-256 is `ea1f5cb1574544c73010175b49aa2dd8e189eeb5b36a1237a19963e7539c91d8`; the package manifest SHA-256 is `ea5412c02bb9c3fbb102043a21eb9fc45ef96d7d146fa25efb545d26bc830fc8`.

## Adapter and application paths

`deploy/local/load_mach33_demo.py` validates the package hashes, synthetic execution policy, `demo.*` IDs and disabled provider accounts, then copies the exact fixture into that private scope. `scope.json` is `duranki.mach33_demo_scope.v1`. An unchanged second import returned `unchanged`; a changed fixture under the same dataset ID produced a conflict in a separate temporary scope and left the original intact. Source IDs are retained as service IDs, so no source-to-target remap is needed. The complete source records, including timestamps, parent runs, outcomes, duplicate-delivery cases and replacement revisions, remain in `fixture.json`; no fixture fields were silently rewritten into another schema.

`duranki_server.mach33_demo.Mach33Demo` reads the immutable scope at service startup, checks its digest and projects one set of effective attempts at the fixed cutoff using decimal USD and Toronto date buckets. Later revisions replace earlier values. Direct, delegated and inclusive run totals are distinct; inclusive totals are not summed across parents. The installed operator exposes authenticated read-only `/operator/v1/mach33-demo/report` and `/operator/v1/mach33-demo/workflow` endpoints. The report provides six groupings, effective attempts, observation steps, filters, JSON and CSV export. The CSV marks every row as demo provenance. The workflow endpoint retains exact runs, tasks, attempts, revisions, events, outcomes and lineage. No demo write or provider execution endpoint was added.

The existing **Connections** landing view is unchanged. In **Accounting**, **Open demo workspace** selects `source=demo` and the featured workflow `demo.workflow.0105`. The same installed application presents Overview, Providers, Models, Agents, People & teams, and Tasks & workflows, with bars, exact tables, workflow lanes, an observation-time cost curve, seek/play/replay, selected event and linked attempt/revision details. The earlier DEV-09 replay remains selectable as **Original DEV-09 replay** (`source=classic`). External observations and native Duranki accounting remain separate sources; changing sources or returning to Connections does not import demo rows into either.

## Exact reconciliation and interaction evidence

The installed authenticated report matched `expected_totals.json` for every shared headline measure and every row and field of all six groupings: initiating user, executing actor direct, provider, model, Toronto local date and workflow. All **378 run rollups** matched direct, delegated and inclusive values. The 112 workflow endpoints yielded **3,112 events** and **592 usage revisions**, including **18 replacements**, with no duplicated charge. The 574-row CSV export carried demo provenance. A Larry Mitchell person filter returned **95 attempts**; clearing it restored **574**.

| Measure | Installed result |
| --- | ---: |
| Synthetic users / agents / providers / model profiles | 6 / 11 / 3 / 6 |
| Workflows / runs / attempts | 112 / 378 / 574 |
| Usage revisions / replacement revisions / timeline events | 592 / 18 / 3,112 |
| Duplicate-delivery cases retained in fixture | 5 |
| Known / unknown / explicit-zero cost attempts | 543 / 31 / 13 |
| Unknown usage attempts | 16 |
| Known simulated USD subtotal | 16.070757200 |
| Known input / output tokens | 5,476,356 / 1,068,473 |
| Provider results | 547 completed; 13 failed; 13 blocked; 1 pending |
| Workflow outcomes | 90 accepted; 9 rejected; 10 unreported; 2 cancelled; 1 pending |

The featured `demo.workflow.0105` is **Prepare a mission briefing**, initiated by synthetic Larry Mitchell at 09:00 Toronto on November 4. It has 8 attempts, 43 timeline events and final known simulated USD **0.225829600**; all 8 observation cost steps matched the oracle. The selected usage event links its run, actor, provider/model, tokens, cost state and amount. `demo.workflow.0005` demonstrates a corrected attempt: the inspector shows original revision `demo.usage.0005.02.v1` at USD **0.007328400**, replacement `v2` at USD **0.007596400**, and parent run `demo.run.0005.00`.

Headless Chrome exercised the six Accounting tabs, charts, featured trace, selected usage event, seek/play, correction trace, person filter, clear filter and return to Connections. The final browser pass showed one demo filter panel and no stale external report content after navigation; reopening Accounting restored the normal external source. Representative private screenshots:

- [Connections preserved](/Users/larrymitchell/Mach33/mach33-platform-duranki-integration/.mach33-local/duranki-instance/real-credentials-20261103-01/mach33-demo-review-verified/01-connections-preserved.png)
- [Overview with daily chart](/Users/larrymitchell/Mach33/mach33-platform-duranki-integration/.mach33-local/duranki-instance/real-credentials-20261103-01/mach33-demo-review-verified/02-mach33-overview-chart-and-trace.png)
- [Workflow selected usage event and cost curve](/Users/larrymitchell/Mach33/mach33-platform-duranki-integration/.mach33-local/duranki-instance/real-credentials-20261103-01/mach33-demo-review-verified/04-selected-event.png)
- [Replacement revision and parent run](/Users/larrymitchell/Mach33/mach33-platform-duranki-integration/.mach33-local/duranki-instance/real-credentials-20261103-01/mach33-demo-review-verified/06-corrected-usage-trace.png)

## Owner-state preservation and limits

The ordinary owner Connections remained connected: Anthropic with **11 selected models**, xAI with **7**. The credential profile's existing controlled fixture accounts also remained in the database. Hashes of all **six** credential binding records matched the consistent pre-demo backup exactly. After import, UI refresh, replay and an ordinary local restart, the owner database still had **0** `integration_attempts` and **0** `integration_events`. Its existing `service.sqlite`, encryption secrets, operator password and ports were reused; the backup is `service-before-demo-015.sqlite` in that private directory. No credential value was printed, copied into the demo scope or placed in this result. No provider inference, external request or real accounting activation was run.

The supplied schema is portable, so the demo uses a versioned file-backed server scope and projection rather than native production accounting tables. Native Usage & Costs does not show these scripted charges. The JSON report exports effective attempt rows and observation steps; full original event and revision records are available through the workflow endpoint and retained fixture. The fixture contains no real prompts or model responses to display. These are the remaining representation limits of this local demonstration.
