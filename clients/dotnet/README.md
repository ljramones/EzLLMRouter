# CognitiveDynamics EzLLMRouter .NET client

The **0.3.0** C# client targets **.NET 10 LTS** and uses only the .NET base class
libraries. Package ID: `CognitiveDynamics.EzLLMRouter.Client`. Namespace:
`CognitiveDynamics.EzLLMRouter`. The package has not been published to NuGet.

Build and test with a .NET 10 SDK:

```sh
bash clients/dotnet/build.sh test
```

The script creates a NuGet package in `clients/dotnet/build/packages`, installs
that local package into the test consumer, and runs the shared contract cases.
The checked-in NuGet configuration disables external package sources. Applications
can reference `EzLLMRouter.Client.csproj` directly or use the local package source.

```csharp
using CognitiveDynamics.EzLLMRouter;

using var client = new EzLLMRouterClient(origin, serviceToken);
var capabilities = await client.GetCapabilitiesAsync(cancellationToken);
var request = ProtocolJson.ParseObject(await File.ReadAllBytesAsync("request.json"));
var reply = await client.SubmitAsync(request, waitMs: 3000,
    cancellationToken: cancellationToken);
```

`EzLLMRouterClient` supports `SubmitAsync`, `SubmitInRunAsync`, `GetStatusAsync`,
`GetCapabilitiesAsync`, `SubmitEmbeddingAsync`, `SubmitRerankAsync`,
`GetSuccessorStatusAsync`, `StartRunAsync`, `GetRunAsync`, `ReportOutcomeAsync`
and `GetOutcomeReceiptAsync`. A null wait omits the header; an explicit integer
must be between 0 and 30000 ms. Wire 0.3 status queries use a submission ID or
`{"work_selector": {...}}`. See the [API guide](../../docs/API.md).

```csharp
using var accounting = new IntegrationClient(origin, ingestToken, version: "3");
var receipt = await accounting.SubmitObservationAsync(eventRecord, cancellationToken);
var recovered = await accounting.RecoverReceiptAsync(datasetId, eventId, cancellationToken);
```

Accounting defaults to v1 and supports v1/v2/v3 explicitly. The methods are
`CreateDatasetAsync`, `RegisterAccountAsync`, `SetAccountStateAsync`,
`SubmitObservationAsync`, `RecoverReceiptAsync`, `EligibilityAsync` and
`ReportAsync`. V2/v3 add `SubmitSnapshotAsync`, `SnapshotAsync` and
`ExportDatasetAsync`. V3 adds `SetAccountPermissionsAsync` and
`OperationEligibilityAsync`. Records are `System.Text.Json.Nodes.JsonObject`;
all JSON numbers must be safe integers, and decimal quantities remain strings.

`EzLLMRouterException` carries `Code`, nullable `HttpStatus`, `RetryGuidance`,
`CorrelationId`, `Selector`, verified `Handle`, `WorkKey`, `AttemptId` and
`FailureStage`. After `query_first`, recover existing work or its receipt before
considering redelivery. Missing evidence does not prove that work was unsent.

The default handler disables redirects, proxy inheritance and decompression,
uses a 10-second connect timeout and a 35-second exchange deadline, and avoids
connection reuse. Every async method accepts a cancellation token. A constructor
timeout of zero or `Timeout.InfiniteTimeSpan` disables the exchange deadline.
No operation is replayed by the client; the .NET transport may retry a connection
before transmission. Injected `HttpMessageHandler` instances remain caller owned.
Clients are `IDisposable`, and response bodies are disposed on all paths.

Response limits are 1 MiB for wire 0.2/attribution and 16 MiB for wire
0.3/accounting. Decoding rejects duplicate keys, unsafe numbers and invalid
Unicode. Result identities, recovery selectors and accounting digests are
checked against the issued request. No client method calls a provider directly.

The localhost transport fixture is a separate check after building:

```sh
python3 -I -S tests/client_languages/http_fixture.py --client dotnet
```

These checks require a working .NET SDK, and the HTTP fixture also requires
permission to bind localhost. CI includes both checks; local toolchain or socket
restrictions do not establish that they passed.
