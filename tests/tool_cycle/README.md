# DEV-03 caller-owned lookup cycle

This retained runner describes the historical DEV-03 fixture and its exact
input/evidence requirements. Its complete wrapper is not part of the current
baseline qualification. Use the [local profile](../../deploy/local/README.md)
and [current validation summary](../../docs/TESTING-ROADMAP.md#current-status)
for maintained preparation and qualification; no historical replay is required
by the current completion list.

Run from the repository root in normal Mac Terminal with a fresh ID:

```sh
./tests/tool_cycle/run.sh run-20261019-04
```

The script stages checked local wheels and the three DEV-03 package artifacts, builds four private Linux ARM64 images from pinned local Python and Node bases, and starts only its `ezllmrouter-dev03-<run>` Compose project. Python and CommonJS are installed into separate consumer images. Each actor completes two retained `auto` lookup cycles under one step using generations 1–4; the receiver checks eight ordered call/result POSTs, and cross-language status reads add none. A Python text request adds one POST. Python and CommonJS then each complete a live no-store cycle, including a forged-source rejection and a measured no-send interval. An installed Python wait-expiry case checks `metadata_only_no_store`, no later candidate access and zero caller tool executions. A malformed provider response and an ordered two-call cycle complete the 17 expected model POSTs. The runner starts a separate mutation-injected service in the same project for a final zero-send negative, then checks the service and receiver counts.

`scenarios.json` is the shared inert fixture. The lookup table exists only in the actor files. The service and SDKs do not execute tools. The receiver checks actual incoming request content and derives the final answer from the received result. This recipe handles one tool and the exact schema in the corpus; `required` choice and other schemas are unsupported.

The runner writes raw argv/stdout/stderr/exit records and a redacted, manifest-checked runtime ZIP to `.artifacts/tool-cycle/`. It captures failure evidence before project-only cleanup. Run `run-20261019-03` observed the retained and Python no-store cycles; its packet remains unchanged. Use a new run ID for any retry; a run or output collision stops before work. The run needs local Docker Desktop context `desktop-linux`, the pinned base images and the checked predecessor wheel set. It performs no pull or real-provider call.
