# Node.js October 2026 security correction

**Date:** 2026-10-28. **Tested source commit:** `63e784a41dcff42f7c44e86a1e4495cfe172ba82`. **Scope:** current source/runtime selection and the private JavaScript client. This correction does not update the owner profile or rewrite historical run evidence. It follows the [read-only review](NODE-OCTOBER-2026-REVIEW-2026-10-28.md).

## Decision and provenance

The [official Node.js October 21 security release advisory](https://nodejs.org/en/blog/vulnerability/october-2026-security-releases) lists **v24.22.1** as the fixed Node 24 release. Current Duranki support remains on Node 24. The old pinned `v24.19.0` image was executed in an isolated, network-disabled version check and returned `v24.19.0`.

The replacement is the official `docker.io/library/node:24.22.1-bookworm-slim` Linux ARM64 image, selected by immutable multi-platform index digest `sha256:be8204d4bd327363357f532187b752ff62759c31bedf98e9e18fc08c9cbd605c`. Docker's published index identified ARM64 child manifest `sha256:932a44adcdb8f5dfbf00f00eb38da8d22b450b2ad258b6d1b2319beca823bfbd`, source `nodejs/docker-node` revision `80f02a542da739e6a662451d1db66456a0dea253`, and Debian bookworm-slim base. After pulling the explicit tag, `docker image inspect` reported the same index digest, Linux ARM64; `docker run --rm --network none --platform linux/arm64 --entrypoint node` against the digest returned **v24.22.1**. This is the selected frozen image input for current source. The host `/Users/larrymitchell/.nvm/versions/node/v24.22.1/bin/node` also returned v24.22.1.

The active profile and reusable client/gateway/development runners now select that digest. `.nvmrc`, the active host-executable pins, the JavaScript package engine range and its lockfile require 24.22.1 on the supported Node 24 line. The private npm client is **0.2.3**; HTTP contracts and server version remain unchanged at v2 and 0.2.2. Exact client tarball: `/Users/larrymitchell/Mach33/Duranki-artifacts/node-security-20261028-01/packages/mach33-duranki-client-0.2.3.tgz`, **25,189 bytes**, SHA-256 `c4438dcccb8d4541372e313e29d0105682159d81ce0fe59aca69909b5c0ce01b`. It was built with `npm pack . --offline --ignore-scripts --no-audit --no-fund`; all nine tar members match the tested source commit byte for byte. It was installed from that archive with `--offline --ignore-scripts --engine-strict --no-package-lock`. The first install diagnostic used the host shell's Node 26 despite an absolute npm executable; the successful install invoked npm's CLI through the explicit Node 24.22.1 binary. No dependency was acquired or changed.

## Client boundary and checks

Both client constructors require a configured HTTP(S) **origin**, with no embedded credentials, path, query or fragment; the parsed origin is canonicalized before requests. Operators must supply a trusted service origin from configuration, never from a model result or other untrusted data. All Node client transport paths request `Accept-Encoding: identity`. The Duranki service has no compression implementation in current source. Trusted proxies must also leave Brotli disabled. Node `fetch` can decode before application inspection; an identity request header is a service convention, not a protection against a malicious server. The fixed runtime is the security boundary for that case.

Focused checks on actual Node **v24.22.1**:

| Check | Result |
| --- | --- |
| Source transport origin/encoding check | PASS; four transport paths, no network |
| Existing source CommonJS response test | PASS; 4 positive, 19 malformed response, 2 selector, 4 mutation, 3 option/unknown-outcome cases; 0 provider calls |
| Existing DEV-12 SDK source test | PASS; 6 positive, 19 negative |
| `node --check` on both changed client modules | PASS |
| Exact 0.2.3 tarball installed under Node 24.22.1 with strict engine check | PASS |
| Installed tarball transport check in fixed ARM64 Docker image, `--network none` | PASS; four transport paths |
| Existing installed CommonJS response test in the same fixed image, `--network none` | PASS; same counts and 0 provider calls |
| Isolated rebuild of the current frozen profile's JavaScript actor context with the fixed Node digest | PASS; local image `duranki-node-security-smoke:20261028`, config ID `sha256:299450d3009421c1d8d37a6e0e3357f3181bdab57b467653ec9feb361e308ffc`; network-disabled runtime returned `v24.22.1` and the frozen client's public `DurankiClient` export |
| `git diff --check` | PASS |

An initial attempt to run the older tool-cycle unit test directly from source failed because it expects a staged `vectors.json` and an installed package. The relevant installed response test above supplied the package and used its repository fallback vectors. The actor smoke used the already frozen profile context and its historical client package, under a separate image tag; it did not substitute the new 0.2.3 client into that historical build. A first runtime probe tried to import the package's private `package.json` subpath and failed as expected under its exports map; the corrected public-export probe passed. No gateway sender or model call was run. The owner profile was not rebuilt or restarted.

## Retained limits

The exact 0.2.2 integration release ZIP remains historical and unchanged. Its JavaScript engine declaration permitted vulnerable Node 24 patches; use the 0.2.3 client on a verified fixed runtime for new local installations. Old DEV-12 CT02b one-use scripts and validation records retain their exact `v24.19.0` image identity as historical evidence. Do not reuse those frozen scripts/images for new runs; a future campaign needs a newly qualified image and authorization. Earlier DEV-01/04/05 run receipts likewise remain unchanged. A read-only `docker ps` showed the owner profile's ingress, service, receiver, netns and worker containers running; none was a Node container. Existing built actor images were not rebuilt. This correction did not run a new gateway matrix, publish to a registry, activate Vega, select a provider, or alter operational credentials, history or permissions.
