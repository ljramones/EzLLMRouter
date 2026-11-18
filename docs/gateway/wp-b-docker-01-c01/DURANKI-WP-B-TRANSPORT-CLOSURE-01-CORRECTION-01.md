# WP-B/DKR-01 Transport Closure — Correction 01

**Result:** `SOURCE_BOUNDARY_PARTIAL_INPUTS_NOT_ACQUIRED`. The source-based LiteLLM trace in the [original transport assessment](../wp-b-docker-01/DURANKI-WP-B-TRANSPORT-CLOSURE-01.md) remains applicable. The correction changes how the four missing source candidates can be acquired as inert data; it does not manufacture their source review or an FDC proof.

| Candidate | Version | Recorded workspace-lock sdist SHA-256 | Present state |
|---|---:|---|---|
| OpenAI SDK | 2.33.0 | `f850c435e2a4685bba3295bd54912dd26315d9c1b7733068186134d6e0599f9a` | Not acquired/inspected |
| HTTPX | 0.28.1 | `75e98c5f16b0f35b567856f597f06ff2270a374470a5c2392242528e3e3e42fc` | Not acquired/inspected |
| httpcore | 1.0.9 | `6e34463af53fd2ab5d807f399a9b45ea31c3dfa2276f15a2c3f00afff6e176e8` | Not acquired/inspected |
| AnyIO | 4.14.2 | `cfa139f3ed1a23ee8f88a145ddb5ac7605b8bb4313c7f` | Not acquired/inspected |

The corrected queue binds each URL, filename, size bound, expected size and digest. A later owner-side `prepare.py owner` run may transfer them into a fresh scratch run and include receipts in a Downloads packet. The separate online uv resolution consumes **official index metadata**, not these sdists; the four source bytes serve subsequent static transport inspection. Success in one path does not close the other.

LiteLLM's selected adapter injects an `AsyncOpenAI` client and uses `chat.completions.with_raw_response.create`; it has a parameter-dropping 422 branch and an alternate HTTP handler. An out-of-tree `httpx.AsyncBaseTransport` guard remains a hypothesis until exact SDK/HTTPX/httpcore/AnyIO bytes and a live receiver trace establish final request preparation, retry and first-write behavior. A check before delegation may leave a pool-wait/revocation gap. If a supported final-write boundary cannot be shown, DEC-09 returns to the owner. The selected source's signature, enterprise entitlement, current advisory/change review and operational soak remain separate unresolved qualifications. No provider or gateway code ran here.
