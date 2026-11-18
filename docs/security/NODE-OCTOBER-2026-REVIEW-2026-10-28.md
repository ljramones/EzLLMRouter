# Node.js October 2026 security review

**Review date:** 2026-10-28
**Source checkout at final inspection:** `e1381f564709731cc314b1455ba1ed5a322a5a83`
**Scope:** Duranki JavaScript client, browser console, Node test/runtime inputs, and related repository records. This is a read-only source and configuration review; it is not a deployed-environment or exploit test.

## Decision for the fix owner

Duranki still pins vulnerable Node `v24.19.0`. Two integration release scripts select `v24.22.1`, which **meets** the supplied Node 24 fix threshold for CVE-2026-111497. The client engine range `>=24 <25` permits vulnerable releases. The installed CommonJS client uses Node's built-in `fetch` by default, so a Brotli-compressed response from an attacker-controlled endpoint can reach Node's decoder when the client runs on a vulnerable Node release. The documented Duranki endpoints are local/trusted; this review did not establish an attacker-controlled response path in the recorded topology.

The same Node upgrade is the indicated fix for the other October 2026 Node CVEs listed below, using the version and affected-line information supplied for this review. Their upstream advisory details were **not independently fetched or verified** here. Confirm the official Node advisory and exact replacement artifact provenance before approving a frozen-input or operational-profile change.

## Version and image inventory

| Version or constraint | Evidence | Disposition |
| --- | --- | --- |
| `v24.19.0` | [`.nvmrc`](../../.nvmrc) line 1; [`README.md`](../../README.md) line 119; [`tests/development_slice/run.sh`](../../tests/development_slice/run.sh) line 12 pins `node:24.19.0-bookworm-slim`; [`tests/gateway_integration/run.sh`](../../tests/gateway_integration/run.sh) line 29 and [`tests/operator_console/dev09_installed_proof.py`](../../tests/operator_console/dev09_installed_proof.py) line 95 name the host executable | Vulnerable under the supplied Node 24 threshold. |
| `v24.19.0` installed client image | [`docs/development/dev-12/A2-A4-VALIDATION.json`](../development/dev-12/A2-A4-VALIDATION.json) line 230 records image ID `sha256:517e1b65b0e7e17377720978f1e7756318d17f57df8dce51d79e717c10cbf1cf` and Node `v24.19.0`; [`tests/gateway_integration/dev12_ct02b_host.py`](../../tests/gateway_integration/dev12_ct02b_host.py) line 28 and `dev12_ct02b_host02.py` line 28 pin that ID | Historical frozen test/target input; vulnerable if reused. |
| `v24.22.1` | [`tests/integration_readiness/combined_release.py`](../../tests/integration_readiness/combined_release.py) line 27 and [`correction_release.py`](../../tests/integration_readiness/correction_release.py) line 43 name its executable; [integration readiness result](../development/integration-readiness/RESULT.md) line 38 records it | Meets the supplied Node 24 fixed threshold. It was also the shell's `node --version` during the earlier review turn. |
| `>=24 <25` | [`clients/js/package.json`](../../clients/js/package.json) lines 11-13 and [`package-lock.json`](../../clients/js/package-lock.json) lines 10-12; [client README](../../clients/js/README.md) line 5 | Supported range allows all vulnerable Node 24 patches below `24.22.1`. |
| `24.22.0` | [foundation commission draft](../implementation/foundation-entry-02/DURANKI-WP-FND-COMMISSION-DRAFT-01.md) line 19 explicitly says this candidate was not adopted | Historical candidate only; vulnerable if used. |
| `20.20.2` | [foundation entry report](../implementation/foundation-entry-01/DURANKI-FOUNDATION-ENTRY-DECISIONS-01.md) line 7 reports a former shell default | Historical EOL host observation, not a selected project runtime. |
| `v26.12.1` | [DEV-12 result](../development/dev-12/RESULT.md) line 109 records a host tool; `node --version` at this report's final inspection also returned `v26.12.1` | Meets the supplied Node 26 fixed threshold. A shell default does not replace repository or image pins. |

Additional pinned Node image references use `docker.io/library/node@sha256:be8929e08ae137e81b5e1edba02259e6c4cb2f5ad655092bb9f56b97e41c4536` in [`deploy/local/profile.py`](../../deploy/local/profile.py) line 25, [`tests/client_parity/run.sh`](../../tests/client_parity/run.sh) line 11, [`tests/tool_cycle/run.sh`](../../tests/tool_cycle/run.sh) line 12, and [`tests/gateway_integration/run.sh`](../../tests/gateway_integration/run.sh) line 32. The digest alone does not encode a Node version. Inspect the actual selected image before attributing a version or replacing it. The JavaScript Dockerfiles use `ARG NODE_IMAGE` / `FROM ${NODE_IMAGE}`; the calling profile or runner supplies that image.

No `.node-version`, `.tool-versions`, CI configuration, Bun runtime declaration, Bun lockfile, or other JavaScript dependency lockfile was found in this checkout. No Node 22, 23, or 25 runtime pin was found. Under the supplied thresholds, fixed alternatives are Node `22.23.4+`, `24.22.1+`, or `26.12.1+`; Node 20 and earlier, 23, and 25 are EOL lines to migrate away from.

## Reachability of the listed issues

| Issue | Repository evidence | Assessment |
| --- | --- | --- |
| **CVE-2026-111497**, Brotli decoder | [`clients/js/index.cjs`](../../clients/js/index.cjs) lines 197-215, 281-289, and 381-395 and [`clients/js/integration.cjs`](../../clients/js/integration.cjs) lines 85-102 use `globalThis.fetch` by default and consume responses from caller-supplied `baseUrl` values. Node may decode `Content-Encoding: br` before `response.json()` or `response.arrayBuffer()` and before schema checks. | Reachable if a configured server or intermediary supplies attacker-controlled Brotli bytes. The [client README](../../clients/js/README.md) lines 11-15 shows a loopback service, and lines 36-38 say the client calls the Duranki service rather than a provider. No public inbound Node Brotli route was found. |
| **CVE-2026-105482**, NUL-truncated DNS names | No `node:dns`, `dns.resolve*()`, or `dns.reverse()` call was found in product JavaScript. | No demonstrated application path that validates one hostname and passes it to the affected DNS APIs. |
| **CVE-2026-105483**, **CVE-2026-106069**, **CVE-2026-106072**, TLS hostname/IP handling | The two client constructors above accept HTTP(S) `baseUrl` values and use Node `fetch` for HTTPS. No `tls.connect`, `https.request`, `checkServerIdentity`, or custom certificate verifier was found in product JavaScript. | Relevant to a deployment that allows untrusted data to select a client endpoint. The documented endpoints are local/trusted; this review does not prove an exploitable hostname-verification bypass through these particular `fetch` calls. |
| **CVE-2026-105481**, early response on a keep-alive socket | No explicit `http.Agent`, shared agent, keep-alive setting, or Undici dispatcher was found. The clients perform repeated `fetch` requests. | Built-in connection reuse may still matter. No shared-agent path across attacker-controlled requests was demonstrated. |
| **CVE-2026-106074**, snapshot/SEA UUID or integer reuse | No Node `--build-snapshot`, snapshot blob, SEA build, or product Node `crypto.randomInt()` / `crypto.randomUUID()` use was found. [`web/app.js`](../../web/app.js) line 31 and other console files call **browser** `crypto.randomUUID()`; [`tests/operator_console/dev12_completion_browser.cjs`](../../tests/operator_console/dev12_completion_browser.cjs) line 225 uses Node UUID in a test. | No demonstrated affected production snapshot or SEA path. |

The source search found no direct `node:zlib` Brotli decoder, Express/body-parser installation or route, or third-party JavaScript decompression package. The browser console's same-origin [`fetch`](../../web/app.js) line 14 runs in the browser, outside Node's decoder. The Python gateway dependency research mentions optional `brotli` / `brotlicffi` extras, but neither package was found pinned in the inspected runtime locks; this Node CVE does not establish a Python package vulnerability.

## Broader JavaScript observations

The current [`clients/js/package-lock.json`](../../clients/js/package-lock.json) contains only `@mach33/duranki-client` itself. `npm ls --all --package-lock-only --json` listed no transitive packages. `npm audit --offline --json` exited 0 with zero reported vulnerabilities and zero auditable dependencies. That result does **not** audit the Node runtime or prove that offline advisory data is complete.

A targeted product-JavaScript search found no `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `eval`, `new Function`, shell execution, or dynamic redirect sink. The console's [`node()` helper](../../web/app.js) line 5 inserts string values using `textContent`; its API helper uses same-origin credentials and `redirect: "error"` at line 14. This is not a complete authorization, path-traversal, or server-side security audit; those controls primarily live in the Python service.

## Fix handoff

1. Confirm the official October 2026 Node advisory and the exact fixed patch and artifact provenance. Keep the intended Node 24 support line unless an approved release decision changes it.
2. Raise [`.nvmrc`](../../.nvmrc) and `clients/js` `engines.node` in both `package.json` and `package-lock.json` to require at least `24.22.1` on Node 24. The integration release scripts already select fixed `24.22.1`; update the older `24.19.0` host executable pins in runner/proof scripts that must continue to run.
3. Replace each selected Node image tag/digest with an explicit reviewed fixed image. Verify `node --version` inside the actual image, and preserve the repository's frozen-input/hash-checked release process. Do not infer a version from a digest string alone or silently change an existing one-use historical result.
4. Rebuild and run the focused offline JavaScript package, installed-client, and relevant local gateway checks with the replacement runtime. Record the source commit, image identity, observed version, and result. The current review performed no Docker or deployed-profile restart.
5. While patching, restrict client `baseUrl` values to trusted services and disable Brotli responses at those services. For a server whose response is untrusted, a proxy or transport layer must reject `Content-Encoding: br` **before** Node's `fetch` decoder; checking response headers after `fetch` is too late. An `Accept-Encoding: identity` request alone is not a control against a malicious server. The listed TLS issues also favor keeping untrusted input out of endpoint selection.

## Review limits

The CVE descriptions, severity, affected lines, and fixed-version thresholds in this report came from the review request; no live upstream advisory fetch was performed. The repo was being changed by another actor during review. At final inspection, `clients/js/package.json` and its lockfile both reported package version `0.2.1` with engine range `>=24 <25`; earlier in the review they reported `0.2.0` with the same engine range. This report adds no runtime fix, release authorization, or production acceptance claim.
