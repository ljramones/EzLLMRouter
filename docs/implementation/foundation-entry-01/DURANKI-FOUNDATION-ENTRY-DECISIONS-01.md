# Duranki Foundation Entry Recommendations 01

**Status:** `PROPOSED_FOR_LM01_ADOPTION` for DEC-01, DEC-02 and DEC-15; `WP-FND` is **NOT_ISSUED**. **Date:** 16 October 2026. This document recommends a bounded foundation entry. It does not adopt Implementation Plan v0.2, authorize Git or software work, or qualify a gateway. Architecture v1.1 controls; `docs/implementation/planning-02/` remains unchanged. Review 02's T-29 correction is separately receipted in `DURANKI-PLANNING-02-ERRATUM-01.json`.

## Evidence scope and current local state

The confirmed root is `/Users/larrymitchell/Mach33/Duranki` (`pwd -P`). `.git` is absent as either a file or directory; `git rev-parse --show-toplevel` fails here and in its parent directories. Git branch, HEAD and tracked/untracked status therefore do not exist. The current host is macOS 26.6 arm64. Read-only version reports found CPython 3.12.15, Node 24.19.0 with npm 11.17.0, uv 0.13.1 and Git 2.56.0. Python 3.13.6 and Node 20.20.2 are also installed; the shell's default `python3` is 3.15.0 and default `node` is 20.20.2, so future commands must select the proposed toolchain explicitly.

These are **local upstream-bundled primary documents and tool reports**, read on 16 October 2026. Public DNS failed for a read-only request to `www.python.org`; no publisher site or registry was fetched. Publisher URLs below identify where later live verification belongs. Local files prove what the installed bundles say, not release-signature custody, current security patch status, gateway compatibility, registry ownership, or a production Linux build.

| ID | Publisher-owned evidence read locally; SHA-256 where a file | Publisher URL (locator, not fetched) | Supports / limit |
|---|---|---|---|
| E-01 | `llm-routing-infra-design-v1.1.md` (`8f3ab5b86a8533687da6cb0e80e16b8d7586fc7392c02a646b8c08025aee7e9c`), §§3–4, 15; `mach-recce/DURANKI-MACH-PLATFORM-RECONNAISSANCE.md` (`0836150411fda1b3f3fa3f1c0f5b01d7b0ab76e37d1f7010702f34af115bce80`), §4 | Local controlling sources | Python core/LiteLLM direction and observed CommonJS Node `>=24 <25` consumer snapshot; snapshot does not prove full SDK compatibility. |
| E-02 | `python3.12 --version` = 3.12.15; `/opt/homebrew/Cellar/python@3.12/3.12.15/LICENSE` (`3b2f81fe21d181c499c59a256c8e1968455d6689d269aa85373bfb6af41da3bf`) | `https://www.python.org/downloads/` | Local interpreter and bundled PSF license; upstream release signature and current patch status not checked. |
| E-03 | Node 24.19.0 `README.md` (`47bdbbc1c1ddef217772bf72aec8e93ffe295e72228b63b988dd1035f1a68626`) and `LICENSE` (`148eacf7863ef4329224a29398623077200a27194aa075569faf4a0a85566ca5`) under `~/.nvm/versions/node/v24.19.0/`; `node --version` via that explicit path | `https://nodejs.org/en/download/` | Node's bundled README describes release signatures in `SHASUMS256.txt.asc` and its MIT license. The installed binary's signature was not rechecked. |
| E-04 | Bundled npm 11.17.0 `package.json` (`a4f04ad50219f82e0e8f262d3e1acbdbd678040198ea36fca10fe7bbb38da726`, `license: Artistic-2.0`); bundled `package-json.md` (`797dbeb530b7fe4192cf5d97d0b31cd3f8fcd1aae3c871539ddfd09db017ad47`), `npm-pack.md` (`8e9ea80fbc2efc6631bb4290e44aa9b84e1ba56fc38abdc236f498a791568e92`), `npm-ci.md` (`f42590051fadb44830b2607266d67a844c6d92b8b1735479ffba8d0cc21e728`) | `https://docs.npmjs.com/cli/v11/` | `main`, `exports`, `type`, `files`, packing and clean lockfile install behavior; no package was packed or installed. |
| E-05 | `uv --version` = 0.13.1; `/opt/homebrew/Cellar/uv/0.13.1/README.md` (`57a84a5a635f30e3a26541ebc16ca690944a7750f05713b1af92d3170b58f704`), `LICENSE-APACHE` (`c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4`), `LICENSE-MIT` (`860e3d7a86b84e6a7012c7a635fc64df475cebc6cce34dfeb73a5982ec58176c`), and local `uv help init/build/lock` | `https://docs.astral.sh/uv/` | uv's dual Apache-2.0/MIT license and package/lock/build commands. `uv init` defaults to Git initialization; do not use it without explicit Git authority. Separate `uv_build` distribution metadata is not locally verified. |
| E-06 | `git version 2.56.0`; `git init -h` exposes `--initial-branch`; `git rev-parse` found no enclosing repository | `https://git-scm.com/docs/git-init` | An explicit local `main` branch is possible if separately authorized; no Git action occurred. |

## DEC-01 — Runtime and foundation tooling

**Recommend:** target **CPython `>=3.12,<3.13`** for the first Python service and Python client packages and **Node `>=24,<25`** for the JavaScript client. Use the locally present **Python 3.12.15** and **Node 24.19.0/npm 11.17.0** as the first macOS arm64 foundation host pins, subject to fresh upstream patch/security and provenance checks before a build commission. Use **uv 0.13.1** as the Python project/build frontend and its uv build backend; use bundled **npm** to pack the JavaScript source as a CommonJS tarball. No transpiler, framework, provider SDK, LiteLLM package, server runtime dependency or JS runtime dependency is introduced in WP-FND. The sole proposed new Python build dependency is the matching `uv_build` backend; its exact published version, wheel hash, license and source provenance must be checked from publisher/package metadata before FND installation. `uv` and npm tool binaries are already present locally, but their installed provenance has not been attested.

**Why:** Node 24 matches the inspected Vega CommonJS major range (E-01); Node 20 is the current shell default but outside that range. Python 3.12 is locally available and a conservative candidate for a later LiteLLM integration, while actual pinned LiteLLM compatibility belongs to DEC-13/WP-B. uv can build independent wheel/sdist packages and maintain locks (E-05); npm's bundled docs describe the CommonJS entry and package tarball surface (E-04). The supported ranges are a **proposal**, not evidence that an unselected gateway release or Linux deployment works.

**Material alternatives:** Python 3.13 would extend the support horizon but needs gateway/dependency compatibility evidence; Node 22 would miss the recorded consumer major; `pip` plus another build backend adds a second backend/provenance decision. A dual ESM/CJS build adds tooling and belongs to DEC-08 if needed. **Remaining verification:** live publisher release/security notices, Python and Node artifact signatures or trusted distributor attestations, `uv_build` primary package metadata and license, later selected LiteLLM Python support, and the eventual Linux target. No exact production patch or gateway release is adopted here.

## DEC-02 — Package and distribution boundaries

**Recommend:** three independent package roots, with **no root workspace dependency coupling**:

| Root | Proposed internal distribution / import | First format and boundary |
|---|---|---|
| `server/` | `mach33-duranki-server` / `duranki_server` | Python wheel and sdist via `pyproject.toml`; no LiteLLM dependency in FND. |
| `clients/python/` | `mach33-duranki-client` / `duranki_client` | Separate Python wheel and sdist; no server, training or gateway dependency. |
| `clients/js/` | `@mach33/duranki-client` / `require('@mach33/duranki-client')` | Plain JavaScript CommonJS `.cjs` npm tarball, explicit `main`/`exports` and `engines: >=24 <25`; no Python, server or bundler dependency. |

The distribution names are provisional internal names. Registry ownership/availability, package license text and publication policy are unverified; **no publishing is proposed for FND**. A future ESM export is an A/DEC-08 contract choice. Preserve JavaScript as the source language. The test harness installs the built client artifacts into clean, separate consumers and checks imports and dependency trees only; actual service request-to-outcome behavior is C3 after C1 and B. The server package is a boundary stub in FND, not a functioning gateway.

**Material alternatives:** a single Python workspace is convenient but risks accidentally importing server modules into the client; dual JS outputs may serve more consumers but add a build chain before the contract is settled. Separate package roots and a single CommonJS artifact make the first isolation proof small and directly relevant to Vega. npm's bundled `files`, `main`, `exports`, `type` and `npm pack` documentation (E-04) support the proposed tarball; uv's installed help (E-05) supports independent Python packages. Names, metadata and dependency closure must be reviewed when the future package files are actually written.

## DEC-15 — Independent repository entry and source custody

**Recommend:** confirm this same absolute root in the future commission, then **explicitly authorize local `git init -b main` before substantive source files are created**. Do not authorize a remote, staging, commit or push by implication; recommend **none of those four actions in WP-FND**. Record the unborn branch state and full starting inventory/hashes in the foundation receipt. Preserve `AGENTS.md`, `planning/`, both planning packages, `mach-recce/` and unrelated files. After collision checks, copy architecture v1.1 and `review-tracker.md` byte-identically to `docs/architecture/` and record both source and copy SHA-256. This gives portable baseline custody without altering the controlling originals.

**Material alternatives:** continue without Git and use hash receipts only, or reference the sibling architecture path by digest. Both permit local work but make later custody and independent checkout review harder. An initial baseline commit would improve Git custody but requires a separate staging/commit authorization. The current root and its ancestors are not a Git worktree (E-06); the Mach-Platform path in `mach-recce/` is historical evidence, not the target repo.

## Proposed WP-FND write and execution boundary — **NOT_ISSUED**

If LM-01 adopts the choices and issues a separate commission, propose **exactly** these repository file writes, after individual collision checks:

1. `.gitignore`, `.python-version`, `.nvmrc`.
2. `docs/architecture/llm-routing-infra-design-v1.1.md`, `docs/architecture/review-tracker.md` (byte-identical copies only).
3. `docs/foundation/WP-FND-RECEIPT-01.md` (starting inventory, source receipts, selected artifact hashes/licenses, actual commands/results and limits).
4. `server/pyproject.toml`, `server/uv.lock`, `server/src/duranki_server/__init__.py`.
5. `clients/python/pyproject.toml`, `clients/python/uv.lock`, `clients/python/src/duranki_client/__init__.py`.
6. `clients/js/package.json`, `clients/js/package-lock.json`, `clients/js/index.cjs`.
7. `tests/foundation/README.md`, `tests/foundation/js-consumer/package.json`, `tests/foundation/js-consumer/require.cjs`, `tests/foundation/python-consumer/import_client.py`.

Only if expressly authorized, Git would create local `.git/` with unborn `main`. Generated build artifacts and clean virtual environments belong only under a future collision-checked `/private/tmp/duranki-fnd-01/` and are not repository files. Do not run `uv init` with its default VCS behavior; author the listed files directly or require `--vcs none` if that command is separately approved. No other paths are implied. This list is a **future proposed write manifest**, not permission to create it now.

**Proposed future execution:** select exact approved interpreter/tool/backend artifacts with primary release hashes and license receipts first; permit only their narrowly specified local installation or public-package retrieval if needed in the later commission. Build the two Python distributions and JS tarball, install each client in an isolated clean consumer, check `require()` and Python import plus dependency closure, and record artifact hashes. Do not import or start the server application, call a gateway/provider, or connect Vega under FND. No network access is authorized by this document; a future commission must name any allowed package hosts/artifacts. **Acceptance proof:** reproducible package/import evidence, no server/Python runtime in JS consumer, no server/training dependency in Python client, source custody receipts, and no unlisted writes. **Stop:** unsupported version/license/provenance, missing `uv_build` evidence, source hash mismatch, Git authority not explicit, collision, package coupling, or attempted service behavior. WP-FND remains **NOT_ISSUED**.

## E02-01 and review handoff

`DURANKI-PLANNING-02-ERRATUM-01.json` proposes replacing only T-29 `required_observation` in the unchanged v0.2 register, using architecture §§7.3 and 16. It changes no canonical test, phase, owner or evidence state and has not been applied to planning-02. LM-01 may review the v0.2 plan with this explicit erratum separately from adopting DEC-01/02/15 or issuing WP-FND.
