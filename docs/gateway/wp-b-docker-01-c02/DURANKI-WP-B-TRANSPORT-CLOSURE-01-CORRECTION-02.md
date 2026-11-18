# WP-B/DKR-01 Transport Closure — Correction 02

**Result:** `SOURCE_BOUNDARY_PARTIAL_INPUTS_NOT_ACQUIRED`. The selected LiteLLM source trace and unresolved final-write gap in the [original assessment](../wp-b-docker-01/DURANKI-WP-B-TRANSPORT-CLOSURE-01.md) remain. C02 fixes preparation boundaries and the C01 AnyIO checksum transcription. It neither acquires nor inspects the four transport archives.

| Inspection candidate | Proposed version | Recorded workspace-lock sdist SHA-256 | Actual state |
|---|---:|---|---|
| OpenAI SDK | 2.33.0 | `f850c435e2a4685bba3295bd54912dd26315d9c1b7733068186134d6e0599f9a` | Not acquired/inspected |
| HTTPX | 0.28.1 | `75e98c5f16b0f35b567856f597f06ff2270a374470a5c2392242528e3e3e42fc` | Not acquired/inspected |
| httpcore | 1.0.9 | `6e34463af53fd2ab5d807f399a9b45ea31c3dfa2276f15a2c3f00afff6e176e8` | Not acquired/inspected |
| AnyIO | 4.14.2 | `cfa139f3ed1a23ee8f88a145ddb5ac7605b8bbfd8592baacd7ce3d8bb4313c7f` | Not acquired/inspected |

The AnyIO value above is the 64-character digest in the controlling C02 input JSON, copied from the earlier correct input record. The shortened C01 table value was a transcription error; no dependency selection, artifact pin or provenance finding changes.

A later owner-side helper run may fetch the four source candidates as bounded inert bytes with size/hash receipts. Its separate online, no-build uv route consumes official PyPI index metadata for a **proposal**; the four sdists do not populate its cache or close the Linux graph. The composed C02 test used scripted HTTP bytes and a mocked uv child only.

The selected LiteLLM adapter injects an `AsyncOpenAI` client and invokes `chat.completions.with_raw_response.create`; a parameter-dropping 422 branch and alternate HTTP handler remain relevant. An out-of-tree HTTPX transport guard is a hypothesis until exact SDK/HTTPX/httpcore/AnyIO source and a live independent receiver trace establish final request preparation, retry and first-write behavior. A pre-delegation guard may leave a pool-wait/revocation gap. If no supported final-write boundary can be shown, DEC-09 returns to the owner. Publisher signature, enterprise entitlement, current advisory/change review and operational soak remain separate qualifications. No gateway, SDK or provider code ran here.
