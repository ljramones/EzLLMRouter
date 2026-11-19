# CognitiveDynamics EzLLMRouter Go client

Version **0.3.0** is a standalone Go module with no third-party dependencies.
Source requires Go 1.22 or newer; CI uses the version in `.go-version`.

The module is `github.com/ljramones/EzLLMRouter/clients/go`, imported as
`ezllmrouter`. Until a Go module release is tagged, use the checkout locally:

```sh
go mod edit -replace=github.com/ljramones/EzLLMRouter/clients/go=/absolute/path/to/EzLLMRouter/clients/go
go get github.com/ljramones/EzLLMRouter/clients/go
```

```go
package main

import (
    "context"
    "log"
    "os"

    ezllmrouter "github.com/ljramones/EzLLMRouter/clients/go"
)

func main() {
    client, err := ezllmrouter.NewClient("http://127.0.0.1:8765", os.Getenv("EZLLMROUTER_TOKEN"))
    if err != nil { log.Fatal(err) }
    defer client.Close()
    capabilities, err := client.GetCapabilities(context.Background())
    if err != nil { log.Fatal(err) }
    log.Print(capabilities["profile"])
}
```

`Client` exposes `Submit`, `SubmitInRun`, `GetStatus`, `GetCapabilities`,
`StartRun`, `GetRun`, `ReportOutcome` and `GetOutcomeReceipt`. Wire 0.3 uses
`SubmitEmbedding`, `SubmitRerank` and `GetSuccessorStatus`. All operations take
a `context.Context`. Submission methods take `*SubmitOptions`; `nil` omits the
wait header, and `SubmitOptions{WaitMS: &wait}` sends an explicit 0–30000 ms wait.

Records use `Object` (`map[string]any`), matching the field names in the
[API contracts](../../docs/API.md). Load a request or event with
`ezllmrouter.ParseObject(rawJSON)` to retain integer types and strict JSON
validation. Native Go integers and `json.Number` integers are also accepted.
Decimal prices, quantities and embedding coordinates stay strings. Floating
point JSON numbers are rejected.

For external accounting:

```go
client, err := ezllmrouter.NewIntegrationClient(origin, ingestToken, "3")
if err != nil { return err }
defer client.Close()
receipt, err := client.SubmitObservation(ctx, event)
// If delivery has an unknown outcome, recover the same event before redelivery:
recovered, err := client.RecoverReceipt(ctx, datasetID, eventID)
```

Select accounting version `"1"`, `"2"` or `"3"`. `IntegrationClient` also
provides `CreateDataset`, `RegisterAccount`, `SetAccountState`, `Eligibility`
and `Report`; v2/v3 add `SubmitSnapshot`, `Snapshot` and `ExportDataset`; v3 adds
`SetAccountPermissions` and `OperationEligibility`. Method names correspond to
the [Python client](../python/README.md) and use the same record schemas.

An `*ezllmrouter.Error` exposes `Code`, `HTTPStatus` (zero if unobserved),
`RetryGuidance`, `CorrelationID`, `Selector`, `Handle`, `WorkKey`, `AttemptID`
and `FailureStage`. Use `errors.As` to inspect it. After `query_first`, query
the saved selector or receipt before deciding whether to redeliver. An absent
handle or HTTP status does not prove that work was not sent.

The default transport uses a 10-second connect/TLS timeout and a 35-second total
exchange deadline, including response reads. `WithTimeout` overrides the total
deadline (zero disables it). Caller context deadlines remain effective. The
client disables proxy inheritance, compression and connection reuse, does not
follow redirects, and never retries an operation. Responses close on every
outcome and are bounded to 1 MiB for wire 0.2/attribution and 16 MiB for wire
0.3/accounting. Duplicate keys, unsafe integers, invalid UTF-8 and malformed
Unicode are rejected. Handles, result identities and accounting digests are
checked against the original request.

`WithTransport(http.RoundTripper)` supports testing or a custom transport;
the caller owns that transport and must preserve its redirect and replay
behavior. `Close` closes owned idle connections and rejects subsequent calls.
These clients contact only the configured EzLLMRouter service.

From this checkout, run `bash tests/client_languages/check.sh` for native tests
and packaging, then `bash tests/client_languages/check.sh --http` for separate
loopback transport tests. No provider calls or service restart are involved.
