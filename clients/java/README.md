# CognitiveDynamics EzLLMRouter Java client

Version **0.3.0** supports Java 17 or newer and has no runtime dependencies.
The package is `com.cognitivedynamics.ezllmrouter`; the Maven coordinates are
`com.cognitivedynamics:ezllmrouter-client:0.3.0`. It has not been published to a
registry.

Build a standalone JAR using only the JDK, without Maven or network access:

```sh
bash clients/java/build.sh
```

The result is `clients/java/build/ezllmrouter-client-0.3.0.jar`. Add it to your
classpath, or install that JAR and `pom.xml` into your own Maven repository.
`mvn -f clients/java/pom.xml package` is also available when the declared Maven
build plugins are installed. The dependency-free JDK build is used in CI.

```java
import com.cognitivedynamics.ezllmrouter.EzLLMRouterClient;

try (var client = new EzLLMRouterClient(
        "http://127.0.0.1:8765", System.getenv("EZLLMROUTER_TOKEN"))) {
    var capabilities = client.getCapabilities();
    System.out.println(capabilities.get("profile"));
}
```

`EzLLMRouterClient` exposes `submit`, `submitInRun`, `getStatus`,
`getCapabilities`, `startRun`, `getRun`, `reportOutcome` and
`getOutcomeReceipt`. Wire 0.3 uses `submitEmbedding`, `submitRerank` and
`getSuccessorStatus`. Submission methods accept an optional `Integer waitMs`;
`null` omits the header and an explicit integer sends a 0–30000 ms wait.

Records are `Map<String, Object>` with `List<?>` arrays. The helper
`Json.parseObject(rawJSON)` loads a record without a cast and preserves safe
integers as `Long`. Application-created records can use `Integer` or `Long`.
`Json.stringify(record)` produces the compact canonical representation.
Decimal amounts, quantities and vector coordinates remain strings; floating
point JSON numbers are rejected. See the [API contracts](../../docs/API.md).

```java
import com.cognitivedynamics.ezllmrouter.IntegrationClient;

try (var client = new IntegrationClient(origin, ingestToken, "3")) {
    var receipt = client.submitObservation(event);
    var recovered = client.recoverReceipt(datasetId, eventId);
}
```

Select accounting version `"1"`, `"2"` or `"3"`; the two-argument constructor
defaults to v1. `IntegrationClient` provides `createDataset`, `registerAccount`,
`setAccountState`, `eligibility`, `report`, `submitObservation` and
`recoverReceipt`. V2/v3 add `submitSnapshot`, `snapshot` and `exportDataset`;
v3 adds `setAccountPermissions` and `operationEligibility`. These methods use
the same records as the [JavaScript client](../js/README.md).

`EzLLMRouterException` provides `getCode`, `getHttpStatus` (zero if unobserved),
`getRetryGuidance`, `getCorrelationId`, `getSelector`, `getHandle`, `getWorkKey`,
`getAttemptId` and `getFailureStage`. After `query_first`, recover the saved
selector or accounting receipt before deciding on redelivery. Missing recovery
fields do not prove that work did not execute.

Both clients are `AutoCloseable`. The default HTTP transport disables redirects
and proxy inheritance, requests identity encoding, and uses a 10-second connect
timeout and a 35-second total exchange deadline, including response-body reads.
The constructor accepting `Duration` overrides that deadline (zero disables it).
Interrupted calls cancel their exchange and retain query-first guidance.
The client never replays an operation; the JDK may retry a connection before
transmission or an idempotent transport request on a stale connection.

Response bodies close on success and rejection. Byte limits are 1 MiB for
wire 0.2/attribution and 16 MiB for wire 0.3/accounting. Strict decoding rejects
duplicate keys, unsafe integers, invalid UTF-8 and malformed Unicode. Result
identities, recovery handles and accounting digests are checked against the
original request.

The constructor accepting `Transport` supports injected test transports. The
client owns each returned response body; the caller owns its transport and must
preserve redirect and write-replay behavior. Only the trusted service origin
receives credentials. No client method calls a provider directly.

Run `bash clients/java/build.sh test` for contract and safety checks against the
packaged JAR. The repository's `tests/client_languages/check.sh --http` adds
explicit loopback transport tests after the native packages have been built.
