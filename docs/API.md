# API and clients

EzLLMRouter provides controlled execution and external accounting interfaces.
The accounting-only launcher exposes the API at `http://127.0.0.1:48760` and the
operator console at `http://127.0.0.1:48761/integration`. Model execution is disabled
in that launcher.

## Client packages

| Language | Distribution | Import |
| --- | --- | --- |
| Python | `cognitivedynamics-ezllmrouter-client` | `ezllmrouter_client` |
| JavaScript / TypeScript | `@cognitivedynamics/ezllmrouter-client` | CommonJS / ESM with declarations |
| Go | `github.com/ljramones/EzLLMRouter/clients/go` | `ezllmrouter` |
| Java | `com.cognitivedynamics:ezllmrouter-client` | `com.cognitivedynamics.ezllmrouter` |
| C# / .NET | `CognitiveDynamics.EzLLMRouter.Client` | `CognitiveDynamics.EzLLMRouter` |
| Rust | `ezllmrouter-client` | `ezllmrouter_client` |

Use Python 3.12 and the Node version declared in `.nvmrc`. See the
[Python](../clients/python/README.md), [JavaScript](../clients/js/README.md),
[Go](../clients/go/README.md), [Java](../clients/java/README.md),
[C#/.NET](../clients/dotnet/README.md) and [Rust](../clients/rust/README.md)
guides for method examples, language requirements and local installation.
Go, Java, .NET and Rust cover wire 0.2 execution, wire 0.3 embedding/rerank, attribution v1
and accounting v1/v2/v3, using the same contract resources and recovery rules.
Client origins and credentials come from
trusted application configuration.

Server and client packages use `EzLLMRouter-Contract-Version` for controlled
execution and `EzLLMRouter-Integration-Version` for accounting. The operator
console uses `X-EzLLMRouter-CSRF`. Python implementations live directly in
`ezllmrouter_client` and `ezllmrouter_server`; package exports contain only the
current names. Upgrade the server, worker and consumers together when protocol
headers or canonical digest domains change.

## External accounting v2

Use `IntegrationClient(..., version="2")` in Python or `{version: "2"}` in
JavaScript for the v2 accounting interface under `/integration/v2/`.
Applications submit observations describing activity, attempts, decisions,
results, usage and lineage. The application performs its own model calls;
submitting accounting data never executes a model.

```python
from ezllmrouter_client import IntegrationClient

with IntegrationClient(origin, ingest_token, version="2") as client:
    receipt = client.submit_observation(event)
    recovered = client.recover_receipt(dataset_id, event["event_id"])
```

An event binds its dataset, attempt and provenance to the authenticated caller's
scope. Reusing an event ID with identical content is idempotent; conflicting
content is rejected. Unknown usage and unknown cost remain explicit. Usage
corrections add revisions instead of replacing history.

The [v2 examples](../tests/fixtures/contracts/integration-readiness-v2/examples.json)
and [schema](../tests/fixtures/contracts/integration-readiness-v2/schema.json)
define complete records. The v1 interface remains available through `version="1"`.

## External accounting v3

The `/integration/v3/` interface adds operation families and model-identity states
for generation and speech operations. Select `version="3"` when constructing the
client. Read operation eligibility before selecting an account or capability.
Account permissions explicitly control allowed models and operations.

Model identities distinguish a known model, provider selection and a model that
does not apply to the operation. Missing evidence must not be replaced with an
assumed identity. See the [v3 examples](../tests/fixtures/contracts/integration-readiness-v3/examples.json)
and [schema](../tests/fixtures/contracts/integration-readiness-v3/schema.json).

## Controlled execution and recovery

Controlled execution admits work under explicit identity, grants and finite
limits. The isolated worker prepares a request; the trusted service validates
the final request and owns transmission. A client response does not itself prove
task acceptance.

Text execution accepts `generation_settings.max_output_tokens` from 1 through
32,768 and `generation_settings.total_timeout_ms` from 1 through 300,000
milliseconds. A larger value is rejected with HTTP 422 and `LIMIT_EXCEEDED`
before admission. Personal campaign and provider/model policies can impose lower
limits; the existing personal campaign ceiling is 4,096 output tokens. The trusted sender uses one attempt deadline
bounded by that timeout and the signed plan's expiry; worker preparation and
provider response reading share that budget.

After a transport timeout or uncertain response, query existing work using its
submission handle or work identity. Do not repeat a model call to repair telemetry
delivery. A post-send persistence failure can return `202 pending` while durable
status records an unknown outcome and preserves any observed usage. Repeating
the same work identity does not dispatch another request.

The clients validate response shape, correspondence and byte limits. They do not
follow redirects or replay an operation automatically. The Java guide describes
the JDK's connection and idempotent transport retry behavior. See the client guides for
supported execution profiles and response-recovery methods.

Both Python clients accept `total_timeout=` in seconds, defaulting to a 60-second
budget for each HTTP exchange. It is independent of the connect/read/write/pool
phase limits; deadline failures preserve query-first recovery and do not replay
the request. See the [Python guide](../clients/python/README.md) for disabling the
budget explicitly and the OS DNS/custom-transport limits.

JavaScript clients accept `timeoutMs`, defaulting to 35,000 ms across fetch and
body reading; `null` explicitly disables the total budget. Both Python clients
accept `verify=` for a private CA with their built-in deadline transport. Across
clients, decoded response schema/correspondence violations use `PROTOCOL_INVALID`,
while unreadable/malformed replies retain `TRANSPORT_OUTCOME_UNKNOWN`. A valid
server error keeps its public code. Missing/invalid accounting retry
guidance on 5xx responses defaults to `query_first`; requests are never replayed
automatically.

Wire 0.2 free text in model results and tool arguments preserves escaped newlines, tabs
and other valid Unicode content. NUL and lone surrogate code points are rejected.
Wire 0.3 strings reject C0 and DEL controls. Identifiers, timestamps and fields
with explicit text restrictions still use their schema rules.

## Identity and identifier rules

Internal IDs are case-sensitive ASCII strings of 1–160 characters. The first
character is a letter or digit; subsequent characters can also contain `.`, `_`,
`:` and `-`. Admission, registry, catalogue, operator projections and ID report
filters share this rule, matching the clients. Prefixes such as `catalogue.` and
`operator.source.` count toward the limit. Display text and external provider
model names use their own field rules.

Report-only buckets such as `__direct_human__` remain valid selectors in their
specific fields. Missing values are excluded from literal filters, including the
string `"None"`; a recorded literal `"None"` still matches exactly.

Registry-backed Coordinator authentication uses a credential's explicit context
first. Other registry credentials use the configured `authentication_context`,
or a common scope when every mapped identity has identical non-identity context.
Different scopes require an explicit fallback. Empty or ambiguous context maps
return HTTP 401; an empty map with an explicit registry authentication context is
supported. Missing, invalid and expired context expiries also return HTTP 401.
Credential selection is independent of map insertion order. Direct Coordinator
callers must pass `credential=` when more than one credential shares the same
context object.

The isolated embedding/rerank profiles calculate fictional native prices from
the packaged `dev12/tariffs.json`. Rate strings, minimum charges, quantum and
cardinality domains come from that resource; registered arithmetic and rounding
remain code-owned. Calculations check price identity, currency, native units,
domain and maximum bound against registration. The existing resource and golden
prices are unchanged.

## Operator API

The operator API is under `/operator/v1/`. Named sign-in creates a browser session;
mutations require its CSRF token and an allowed Origin. Accounts that require a
password change have limited access until that change is complete.

See [users and permissions](USER-MANAGEMENT.md) for account endpoints and
[local connectors](LOCAL-CONNECTORS.md) for connection endpoints.

Scripted-demo projections use `/operator/v1/scripted-demo/`; synthetic retrieval
usage uses `/operator/v1/retrieval-usage`. These replace the former product and
milestone route names; bundled browser consumers use the descriptive paths.
Stored records, schema IDs, digest domains and historical evidence IDs retain
their adopted values. The supported scripted-demo CLI option is `--demo-scope`.

`/operator/v1/integration/identity` returns no external user by default. An
administrator may explicitly configure an identity lookup as described in the
[security guide](SECURITY.md#instance-identity-and-optional-display-lookup).

Provider probes return a safe failed observation with reason `invalid_settings`
for invalid adapter/settings input, before network access. Unsupported operations
return `unsupported` / `operation_not_implemented`; malformed replies remain
`malformed_response` failures. Neither settings nor credentials enter the result.

Probe operation IDs deduplicate while the observation is retained: the newest 20
per connection plus up to three inventory anchors. Retrying a pruned ID can run a
new metadata probe. Use a new ID for a deliberate new probe; the observation
window is not a permanent operation ledger. Execution and credential-operation
receipts retain their separate durability rules.

The immutable demo projection represents an existing attempt with no qualifying
usage revision at its report cutoff as unknown usage and cost. Future attempts
and revisions are excluded, and replacement counts stay non-negative. Workflow
traversal rejects cycles and missing parents with a controlled validation error.

## Personal campaign exposure recovery

The execution console's owner can acknowledge an `unknown` or `over_bound`
attempt on a paused or closed campaign. The API is
`POST /operator/v1/personal-campaign`, with the normal authenticated owner
session, allowed Origin and CSRF token:

```json
{
  "action": "acknowledge_exposure",
  "campaign_id": "personal.local.1",
  "attempt_id": "attempt.example",
  "expected_revision": 3,
  "reason": "Owner accepts the unresolved possible charge"
}
```

This records an audited reason and counts the full reservation, or a higher
known cost, against that allowance. The state becomes `acknowledged`; no provider
usage is fabricated and no provider request is sent. Request counts and attempt
history remain intact. Live `reserved` attempts cannot be acknowledged. Repeating
the same acknowledgement is idempotent. New recorded usage can later replace
the conservative budget charge through the existing reconcile action.

Activation remains a separate owner action. Closing an old campaign and explicitly
authorizing a new allowance retains the old exposure without blocking the new
campaign. The summary and console show `unresolved_prior_attempts`, including
the campaign revision needed to acknowledge them. The accounting-only console
does not expose personal execution campaign actions.
