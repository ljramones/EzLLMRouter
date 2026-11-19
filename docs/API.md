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

After a transport timeout or uncertain response, query existing work using its
submission handle or work identity. Do not repeat a model call to repair telemetry
delivery. A post-send persistence failure can return `202 pending` while durable
status records an unknown outcome and preserves any observed usage. Repeating
the same work identity does not dispatch another request.

The clients validate response shape, correspondence and byte limits. They do not
follow redirects or replay an operation automatically. The Java guide describes
the JDK's connection and idempotent transport retry behavior. See the client guides for
supported execution profiles and response-recovery methods.

## Operator API

The operator API is under `/operator/v1/`. Named sign-in creates a browser session;
mutations require its CSRF token and an allowed Origin. Accounts that require a
password change have limited access until that change is complete.

See [users and permissions](USER-MANAGEMENT.md) for account endpoints and
[local connectors](LOCAL-CONNECTORS.md) for connection endpoints.
