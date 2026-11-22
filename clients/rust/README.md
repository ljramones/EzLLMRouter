# CognitiveDynamics EzLLMRouter Rust client

The **0.3.0** crate is `ezllmrouter-client`, imported as `ezllmrouter_client`.
It is a synchronous client using Reqwest with Rustls and Serde JSON. The source
requires Rust 1.85+; the repository declares the 1.90.0 development toolchain.
It has not been published to crates.io.

Use it locally in an application:

```toml
[dependencies]
ezllmrouter-client = { path = "/absolute/path/to/EzLLMRouter/clients/rust" }
```

```rust
use ezllmrouter_client::{Client, IntegrationClient, parse_object};

fn example(origin: &str, token: &str) -> Result<(), Box<dyn std::error::Error>> {
    let client = Client::new(origin, token)?;
    let capabilities = client.get_capabilities()?;
    let request = parse_object(&std::fs::read("request.json")?)?;
    let reply = client.submit(&request, Some(3000))?;
    Ok(())
}
```

`Client` supports `submit`, `submit_in_run`, `get_status`, `get_capabilities`,
`submit_embedding`, `submit_rerank`, `get_successor_status`, `start_run`,
`get_run`, `report_outcome` and `get_outcome_receipt`. Waits use `Option<u32>`:
`None` omits the header, and `Some(0..=30000)` sends an explicit wait.
Wire 0.3 status queries use a submission ID or `{"work_selector": {...}}`.

`IntegrationClient::new(origin, ingest_token, "3")` selects accounting v3;
versions `"1"` and `"2"` are also supported. It exposes `create_dataset`,
`register_account`, `set_account_state`, `submit_observation`, `recover_receipt`,
`eligibility` and `report`. V2/v3 add `submit_snapshot`, `snapshot` and
`export_dataset`; v3 adds `set_account_permissions` and `operation_eligibility`.
All records use `serde_json::Value`. `parse_object` preserves strict JSON
semantics; `canonical` returns the sorted-key representation used for digests.
Decimal quantities, costs and vector coordinates remain strings.

`Error` exposes `code`, optional `http_status`, `retry_guidance`,
`correlation_id`, `selector`, verified `handle`, `work_key`, `attempt_id` and
`failure_stage`. `requires_query()` identifies query-first recovery. Recover
existing work or its accounting receipt before deciding on redelivery. These
clients contact only the selected service origin and never execute provider work.

The default transport disables redirects, proxy inheritance, compression and
automatic retries. It has a 10-second connect timeout and a 35-second total
exchange timeout, including response-body reads. `Options` changes the timeout
or supplies an `Arc<dyn Transport>`; `timeout: None` disables the deadline.
Injected transports must preserve replay and redirect behavior and enforce their
own I/O deadlines. The API is blocking; use a blocking-task executor when calling
it from an async application. Dropping a client releases its transport; `close`
rejects future operations.

Response bodies are bounded to 1 MiB for wire 0.2/attribution and 16 MiB for
wire 0.3/accounting. Strict decoding rejects duplicate keys, unsafe integers,
invalid UTF-8 and malformed Unicode. Response identity, result correspondence
and accounting digests are checked against the original request.
Integer `-0` canonicalizes to `0`; decimal and exponent spellings such as `-0.0`
and `-0e0` remain invalid. Quoted text is preserved during decoding.

Run contract, correctness and package verification with:

```sh
bash tests/client_languages/check_rust.sh
python3 -I -S tests/client_languages/http_fixture.py --client rust
```

The first Cargo build needs the pinned direct dependencies and their resolved
transitive dependencies. This library does not claim a frozen dependency closure;
applications should retain their own reviewed Cargo lockfile. The HTTP fixture
requires permission to bind localhost and makes no model requests. CI contains
both checks; a working Rust compiler is required to establish build results.
