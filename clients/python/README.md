# CognitiveDynamics EzLLMRouter Python Client

Package version **0.3.0** uses the CognitiveDynamics name. Existing wire and
accounting contracts remain compatible. Historical release numbers below
describe when each capability was introduced.

## External accounting integration (0.2.2)

Python `>=3.12,<3.13` is supported. The [v2 contract](../../docs/contracts/integration-readiness-v2/CONTRACT.md)
and [examples](../../docs/contracts/integration-readiness-v2/examples.json)
define complete successor event records. Install the private `0.3.0` wheel with
its frozen HTTPX dependencies.

```python
from ezllmrouter_client import IntegrationClient, IntegrationClientError

with IntegrationClient("http://127.0.0.1:48760", ingest_token, version="2") as client:
    eligibility = client.eligibility(dataset_id, account_id, model_id)
    receipt = client.submit_observation(event)  # one HTTP delivery, no model call
    recovered = client.recover_receipt(dataset_id, event["event_id"])
    stored = client.submit_snapshot(feature_snapshot)
    snapshot = client.snapshot(dataset_id, feature_snapshot["snapshot_id"])
```

Owner administrators may also use `create_dataset`, `register_account`,
`set_account_state` and `report` with an authorized credential. The client
does not retry automatically. For an unknown transport outcome, recover the
receipt before redelivering the identical event. A new model retry uses a new
attempt ID; neither this client nor the accounting service executes it.
V2 owner/report principals can call `export_dataset(dataset_id)` for included
events and selected-action evidence. Omit `version="2"` or pass `version="1"`
to use the preserved v1 route/schema. Default captured features are limited
to synthetic low-class fixtures until the owner adopts a real retention policy.

The corrected v2 `report` returns `usage_state` independently of `cost_status`,
and a server `eligibility_assessment` independently of the caller's reported
`eligibility_evidence_status`. Same-second ordering ambiguity is
`indeterminate`, not a verified selection. `binding_conflict` marks older
inconsistent snapshot or lineage references without attributing their content
to the wrong attempt. `export_dataset` includes eligibility and snapshot
reference assessments next to the immutable event records. The client returns
these fields without changing or repeating the underlying work.

`ezllmrouter_client.EzLLMRouterClient` is a synchronous wire-0.2 client for the
currently enabled text `submit`, `getStatus` and `getCapabilities` operations.
It connects only to a EzLLMRouter service. It does not call a model provider.

```python
from ezllmrouter_client import EzLLMRouterClient, EzLLMRouterError

with EzLLMRouterClient(base_url="http://service:8765", token="local-token") as client:
    reply = client.submit(request, {"wait_ms": 3000})
    status = client.getStatus({"submission_id": reply["handle"]["submission_id"]})
```

The default HTTPX transport disables redirects, proxy inheritance and retries.
Default connect/read/write/pool timeouts are 10/35/30/10 seconds, allowing the
server's maximum 30-second response wait. `timeout=` can override these HTTPX
settings; explicitly passing `None` disables them. Call `close()` or use a context
manager. `get_status` and `get_capabilities` are aliases; `get_status` also accepts
`contract_version="0.3"`.

HTTPX responses are streamed into a bounded buffer with `Accept-Encoding:
identity`; compressed responses are rejected before decoding. Wire 0.2 and
attribution responses are capped at 1 MiB; wire 0.3 and integration responses at
16 MiB. The wire 0.3 bound accommodates the supported embedding dimensions and
batch size. Result profiles are checked against the request, allowing new
server configuration references without a client-side fixture allowlist.

For tests, `transport=` accepts an object with `request` and optional `close`
methods. A transport providing the HTTPX `stream` interface uses bounded reads;
a request-only transport is responsible for its own buffering. Responses close
on success, malformed data, size rejection and interrupted reads.

A lost or unparseable response raises `EzLLMRouterError` with
`code="TRANSPORT_OUTCOME_UNKNOWN"`, `retry_guidance="query_first"` and the
original work selector. No operation is automatically replayed. Other errors
expose `http_status`, `correlation_id`, `handle`, `attempt_id`, and
`failure_stage` where valid evidence provides them. `None` for an unavailable
field does not imply that work did not execute.
Recovery errors attach a handle only when it matches the original request or
status selector. The original selector remains available when a response's handle
is malformed or belongs to another submission.

## Trusted attribution and outcomes (client 0.0.4)

The service keeps the strict submission body at wire 0.2. A versioned run is
created first; `submit_in_run` adds only the paired attribution headers. The
service resolves the authenticated caller, user delegation and charging owner
from its registry and checks current permissions again before dispatch.

```python
run = client.start_run({
    "version": "1", "run_id": "run.example.1", "task_id": request["task_id"],
    "task_class": request["task_class"], "evaluation_ref": "rubric.example.v1",
    "mode": "user_delegated_agent", "agent_id": "agent.registered",
    "agent_version": "v1", "initiating_user_id": "user.authorized",
})
reply = client.submit_in_run(request, run["run_id"], {"wait_ms": 3000})

# A separately permitted child run has one authoritative parent.
child = client.start_run({
    "version": "1", "run_id": "run.example.child", "task_id": request["task_id"],
    "task_class": request["task_class"], "evaluation_ref": "rubric.example.v1",
    "mode": "nested_agent", "agent_id": "agent.child", "agent_version": "v1",
    "parent_run_id": run["run_id"],
})
```

For a direct human run use `mode="direct_human"` with a human credential and
omit agent and user fields. For an autonomous service run use
`mode="autonomous_agent"` with registered agent ID/version and omit user and
parent fields. An authenticated caller cannot claim another user or owner by
editing these fields. Reusing an existing work key with another run conflicts.

An explicitly authorized evaluator records substantive task acceptance or a
step verdict with `report_outcome(event)`. The event uses version `1`, a stable
`event_id`, `run_id`, `kind`, `subject_revision`, `verdict`,
`evaluator_version` and `evidence_ref`. `get_outcome_receipt(event_id)` is the
read-only lost-ACK recovery path. Delivery alone never records acceptance.

## Speech-operation eligibility (integration v3)

Release `0.2.4` adds `version="3"` for the [v3 speech contract](../../docs/contracts/integration-readiness-v3/CONTRACT.md). `operation_eligibility(dataset_id, account_id, {"operation_family": ..., "capability": ..., "selection_kind": ..., "model_id": ...})` reads the digest-bound decision. Include `model_id` exactly for `known_model`; an omitted provider selector is `provider_selected`, not automatically `not_applicable`. Owner/admin `set_account_permissions(account_id, {"dataset_id": ..., "expected_revision": ..., "allowed_models": [...], "allowed_operations": [...]})` replaces explicit permissions. Empty lists deny new selection. Existing v1/v2 methods remain version-specific. Observation retry never repeats model work.
