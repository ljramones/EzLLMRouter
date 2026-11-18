# Duranki external accounting integration contract v1

**Status:** implementation contract for the isolated Integration Readiness release. **Version:** `1`, selected by `/integration/v1/` paths and `Duranki-Integration-Version: 1`. This contract is separate from controlled-execution wire 0.2 and 0.3. All endpoints require a bearer credential authenticated by the Duranki registry. JSON uses UTF-8, unique object keys, safe integers, no floating-point numbers and at most 65,536 request bytes. IDs use `[A-Za-z0-9][A-Za-z0-9._:-]{0,159}`; timestamps are UTC seconds `YYYY-MM-DDTHH:MM:SSZ`. Decimal quantities and amounts are strings, up to nine fractional places, nonnegative and finite.

## Scope, dataset and authority

An owner registry administrator creates one immutable dataset with `dataset_id`, `platform_id`, `environment_id`, `owner_id`, `ingest_principal_id` and `activated_at`. This command is used only for an isolated synthetic release in this milestone; actual Vega activation follows later. The dataset is never silently replaced on deployment. An attempt belongs to the dataset iff its asserted `started_at >= activated_at`. Earlier attempts may receive receipts and be retained as `excluded_before_activation`, but their usage never enters the new cohort. Delayed results and corrections for included attempts remain eligible regardless of receipt time or later account state. The service binds dataset owner and ingest principal to authenticated registry principals; event payloads cannot choose a different platform, environment or owner.

An active owner `registry_admin` may create datasets and register/change accounts. Only the dataset's active `ingest_principal_id` may submit and recover its observations. The owner administrator and read-only operators under that owner may read reports; ordinary ingest principals may read only their dataset's eligibility and own receipts. Do not conflate this authority with model-use permission in Vega. The server does not create a Duranki submission, reservation, send ownership or provider request.

## HTTP operations

| Method and path | Actor | Meaning |
| --- | --- | --- |
| `POST /integration/v1/datasets` | Owner admin | Create immutable dataset; exact duplicate returns original record, conflicting ID returns 409 |
| `POST /integration/v1/accounts` | Owner admin | Register account with Vega credential reference, provider ID, allowed models and usable/disabled state |
| `POST /integration/v1/accounts/{id}/state` | Owner admin | Compare-and-set state with expected revision; retain history |
| `GET /integration/v1/accounts/{id}/eligibility?dataset_id=...&model_id=...` | Dataset ingest principal or owner admin | Versioned current usability decision; no connection-health or demonstrated-capability assertion |
| `POST /integration/v1/events` | Dataset ingest principal | Append one external observation and return durable receipt |
| `GET /integration/v1/events/{event_id}/receipt?dataset_id=...` | Dataset ingest principal or owner admin | Recover receipt before any telemetry retry |
| `GET /integration/v1/reports/usage?dataset_id=...` | Authorized owner/report principal | Effective-once JSON report; `&export=csv` gives the same selected attempt set |

Successful new events return 201; identical delivery of the same event ID and canonical body returns 200 with the **same receipt**. Conflicting reuse of an ID, attempt start, usage ordinal or immutable run binding returns 409 without changing accepted state. A transport or 503 outcome is unknown to the caller: query the receipt, then redeliver the **same** event body and ID if absent. Telemetry retry is never model-call permission. A new actual model retry has a new attempt ID and start event. The response envelope contains `integration_version: "1"`; errors contain `code` and `retry_guidance` (`never` or `query_first`). No automatic HTTP-client resend occurs.

## Account and event records

An account is scoped to one dataset and contains `account_id`, `provider_id`, `credential_ref` (a Vega manager reference, **not a secret**), `allowed_models`, `state`, `revision` and owner. The reference is opaque and must not be dereferenced by Duranki. Eligibility returns the current revision, `usable` and a reason; a disabled account denies new Vega selection when Vega later enforces this response. Historical/in-flight observations remain recordable after disable.

Every event has `integration_version`, stable `event_id`, `dataset_id`, `kind` and `occurred_at`, plus kind-specific fields. The canonical body digest covers all fields. Events are append-only; a corrected fact is a new event/revision.

| Kind | Required payload | Meaning |
| --- | --- | --- |
| `activity` | `activity_kind` (task/step/tool/delegation/outcome), `task_id`, `run_id`, `root_run_id`, `actor_kind`, `actor_id`; optional `parent_run_id`, `step_id`, `outcome` | Non-model context. Never creates a charge. Parent/root bindings for a run are immutable. |
| `attempt_started` | `attempt_id`, `started_at`, `task_id`, `step_id`, `run_id`, `root_run_id`, optional `parent_run_id`, `actor_kind`, `actor_id`, `provider_account_id`, `model_id`, `context_ref`, optional `initiating_user_id` | Immutable before-call context and execution attribution. `actor_kind` is agent/service/human. No cost. |
| `decision` | `attempt_id`, `decision_ref`, `selected_account_id`, `selected_model_id`, `policy_version` | What was selected before execution, independently of later result/usage. `occurred_at` must not be after `started_at` once start is known. |
| `result` | `attempt_id`, `result_state` (completed/failed/unknown), optional `result_ref` | Delivery/result observation. Unknown remains explicit. No automatic charge. |
| `usage` | `attempt_id`, `usage_revision`, `usage_state` (known/unknown), optional known fields below | Native financial observation/correction. Exact ordinal is immutable; latest contiguous revision is effective. |

A known usage revision requires `currency`, `amount_decimal`, `cost_basis` (provider_reported/derived/estimated/reconciled), `price_ref`, `price_version`, and `native_units` (distinct `unit` plus `quantity_decimal` entries). An unknown revision has none of those fields. A true zero amount is valid only with a nonempty `zero_basis`; missing or contradictory zero remains unknown. No currency conversion, price guess or manufactured usage occurs.

Activity and attempt run bindings form a forest within a dataset: root equals run when parent is absent; child names an existing or eventually delivered parent and carries its root. Cycles and conflicting parent/root assertions are rejected. An attempt can be received before its decision, result or usage, and the latter can arrive before its start. Such orphan events retain receipts but contribute no cost until a valid included start arrives. Usage revision 2 can arrive before revision 1; it is pending and does not replace the effective amount until the contiguous chain exists. Each attempt contributes at most its single latest contiguous known amount. Unknown effective cost is counted as unknown, never zero. Direct agent/actor, provider/account and root-workflow reports regroup that same attempt set. Inclusive run cost traverses distinct descendant attempts once.

Reports expose each attempt's dataset/platform/environment/owner/account, task/run/actor, start time, result, effective usage revision, native quantities, currency, amount or explicit unknown, cost basis and price identity. CSV and JSON use the same authorization and filters. Neither report merges unlike currencies. A report may show an unknown-cost count alongside known totals, without presenting the known subtotal as a complete account bill.

## Conformance and limits

The [schema](schema.json), [examples](examples.json) and [offline cases](check.py) are normative examples of this contract. The service, both installed clients and clean release must pass their corresponding HTTP and installed-artifact cases. The contract defines a supported local accounting interface; it does not instrument Vega, authorize a model request, establish account invoice accuracy, or close DEV-12 CT02-02b.
