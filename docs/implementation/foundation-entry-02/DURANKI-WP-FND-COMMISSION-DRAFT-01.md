# Duranki WP-FND Commission Draft 01

**Status:** `DRAFT_NOT_ISSUED` · **Date:** 16 October 2026 · **Root:** `/Users/larrymitchell/Mach33/Duranki`

This is a proposed, gated execution instrument for the narrow foundation work in Implementation Plan v0.2 §8. It grants no execution authority. Architecture v1.1 and `review-tracker.md` remain controlling; planning-01, planning-02, foundation-entry-01, `AGENTS.md`, the readout and `mach-recce/` remain unchanged. The owner must adopt the choices below and issue a separate commission before anyone runs WP-FND. No gate below is recorded as passed merely because this draft exists.

## 1. Owner adoption and issuance record

| Item | Proposed direction for owner decision | Actual adoption / authority |
|---|---|---|
| Implementation Plan v0.2 | Adopt its bounded FND sequence with the separately receipted E02-01 overlay. | **UNRECORDED** |
| `E02-01` | Adopt only the proposed T-29 `required_observation` replacement; leave the v0.2 register file unchanged until a later versioned consolidation. | **PROPOSED_NOT_APPLIED** |
| `DEC-01` | Initial macOS arm64 foundation support: CPython `>=3.12,<3.13`, Node `>=24,<25`; candidate local Python 3.12.15, Node 24.19.0/npm 11.17.0, uv 0.13.1 with its compatible bundled `uv_build==0.13.1`. | **UNRECORDED**; exact artifacts and security disposition still gated |
| `DEC-02` | Three independent package roots: Python server, Python client, plain JavaScript CommonJS client. Internal names below remain provisional. | **UNRECORDED** |
| `DEC-15` | Confirm independent root; permit local `git init -b main` with unborn branch only if expressly issued; byte-identical architecture/tracker copies. No stage, commit, remote or push. | **UNRECORDED**; Git authority absent |
| Node security disposition | Owner and security reviewer decide whether a verified exact Node 24 artifact may be used for this isolated offline pack/import workload in light of the announced October 2026 security update. | **UNRECORDED**; no safe-current claim |
| Publication policy | Approve unpublished/internal metadata, provisional names and no publication. | **UNRECORDED**; no project license inferred |

The initial Python minor is a foundation test target, not a permanent Python client constraint. A newer Node patch, alternate Python, external backend, added dependency, public publication, or changed scope requires an explicit amended decision; this draft does not select one. The Node project announced security updates for 24.x on or shortly after 21 October 2026, with HIGH as the highest announced severity [W3]. Refresh the advisory at issuance. Node 24.22.0/npm 11.19.1 is documented as released on 14 October [W2], but neither it nor a future patch is adopted here. **FE01-01** is reflected in the narrowed entry gates in §2; **FE01-02** in §§3–5; **FE01-03** in the evidence and provenance gate below.

## 2. Read-only preflight gate — before Git or source writes

The future executor evaluates and reports a dated PASS/BLOCKED result for every item **before** creating `docs/foundation/WP-FND-RECEIPT-01.md` or making any other repository write. After all items pass and the issued commission authorizes execution, transcribe the preflight evidence into that receipt. If any item is BLOCKED, stop before `.git/`, package metadata, copied documents, or other source writes. Read-only checks may inspect paths, bytes, metadata, versions and publisher advisories; they must not install, resolve, build or import an application.

1. **Authority:** obtain signed/recorded LM-01 adoption of `DEC-01`, `DEC-02`, `DEC-15`, plan v0.2 plus E02-01, the unpublished/internal metadata policy, the exact artifact allowlist, and the workload-specific Node security disposition. Obtain a separately issued WP-FND instrument naming Git, source, temporary and network authority. An unfilled field is a block.
2. **Root and collisions:** resolve the physical root to the path above; confirm it is outside Mach-Platform and not in an enclosing Git worktree. Inventory all existing files and hashes. Check all 19 paths in §4, conditional `.git/`, and the selected temporary run area for collisions or symlink escapes. If a Git repository already exists, report changed starting state and stop for revised authority; do not reinitialize or change branches.
3. **Custody:** rehash architecture v1.1 (`8f3ab5b86a8533687da6cb0e80e16b8d7586fc7392c02a646b8c08025aee7e9c`) and tracker (`36be1ae781fb6645fa186881eb967e7118f24dbf585913f2f8e0da9b1e1260ac`) at their controlling source paths. Verify planning-02 and E02-01 receipts, and preserve existing planning, readout and reconnaissance bytes. Any mismatch stops copying and requires review.
4. **Selected executables:** resolve every selected Python, Node, npm, uv and conditional Git path, symlink target, version and SHA-256. Tie the *actual bytes to be executed* to accepted upstream or distributor metadata/signature/attestation and record the verification method, result and license evidence. A version string, local file hash, Homebrew install receipt, nvm directory or publisher webpage alone is insufficient. Validate npm's script runs under the selected Node, not the shell default.
5. **Security and dependencies:** refresh primary publisher releases/advisories and record the disposition for the exact Node artifact and offline FND workload. Confirm the uv bundled backend route and pin, no unexpected build/runtime dependencies, approved private metadata and artifact-only local installs. Do not certify Linux or selected LiteLLM compatibility here.
6. **Effect boundary:** approve the 19 repository paths, conditional `.git/`, per-run temporary/cache/log/environment paths, and any network retrieval by exact host, artifact and digest. The default execution route after verified artifacts are present is offline. Unknown download, lifecycle script, toolchain switch or write location is a block.

### Toolchain candidate ledger (evidence as of 16 October 2026)

These are candidates and local observations, not an adopted or provenance-verified execution set. The paths and SHA-256 values were read locally for this draft; the public facts are separately attributed to the foundation-entry review [W1–W12]. The executor must repeat the checks at issuance.

| Tool / proposed range | Selected local path and observed version | Local evidence and provenance limit | Advisory / owner action |
|---|---|---|---|
| Python `>=3.12,<3.13` | `/opt/homebrew/bin/python3.12` → Homebrew Cellar 3.12.15; binary SHA-256 `c4e9f06cb179ae4b3728c748990fbbef7f30580ea42c0eb9c702ebc7c7861c89` | Local version, symlink, binary fingerprint and Homebrew bottle install receipt observed. Python 3.12.15 is a PSF security, source-only release with support through October 2028 [W1,W12]; source checksum does not authenticate the Homebrew bottle. | Approve distributor/bottle or build chain and exact interpreter; refresh patch/security status. |
| Node `>=24,<25` | `/Users/larrymitchell/.nvm/versions/node/v24.19.0/bin/node`; `v24.19.0`; binary SHA-256 `27db838bb204ef7c21df2931f5656e4c8fb32e6e947f363a402b49714d32b5b1` | Local version and fingerprint only; no matching signed release archive/installed-binary attestation. | Resolve exact-artifact provenance and [W3] offline-scope security disposition; do not silently substitute 24.22.0 or guess the pending patch. |
| npm bundled with selected Node | `/Users/larrymitchell/.nvm/versions/node/v24.19.0/bin/npm` → `../lib/node_modules/npm/bin/npm-cli.js`; `11.17.0`; script SHA-256 `8e5f6f3429f8cdbe693cdc29904e9d5a7b127a494bd15c804bd54c7403bfcbe7` | Local version, shebang and script fingerprint; npm uses `/usr/bin/env node`, so selected PATH and actual child version need proof. | Verify npm closure within accepted Node distribution and license; refresh if Node tuple changes. |
| uv frontend and bundled backend | `/opt/homebrew/bin/uv` → Homebrew Cellar 0.13.1; `uv 0.13.1`; binary SHA-256 `cfe5e5695316639f9820e8e57d0732e8a361311c03f1ea1786f4fc879cebf4c5` | Local version, fingerprint and Homebrew bottle receipt; Astral publishes uv 0.13.1 [W4]. Its compatible backend is documented as bundled [W6]. | Verify distributor chain and actual bundled-backend selection; no separate wheel install is presumed. |
| `uv_build==0.13.1` build-system requirement | Bundled through approved uv if compatible; no separate executable selected | PyPI advertises macOS arm64 wheel `uv_build-0.13.1-py3-none-macosx_11_0_arm64.whl`, SHA-256 `bcdd9a7368832aee61e4e3e515be0ada57393ace59c86803c1726e275c006e72`, `MIT OR Apache-2.0` [W5]. No wheel bytes were obtained or verified. | Keep bundled route or seek separate approval for external wheel hash, retrieval and backend execution. |
| Git, conditional | `/opt/homebrew/bin/git` → Cellar 2.56.0_1; `2.56.0`; binary SHA-256 `92229f2456a49561ac5d614bbed775224e2fc32a8eca22ac41aeb3ce47d7899c` | Local version and fingerprint only. | Verify accepted tool provenance if Git init is issued; no Git action before preflight. |

The shell defaults reported in foundation-entry-01 are Python 3.15.0 and Node 20.20.2; they are not the proposed tools. For **FE01-N1**, the `npm-ci.md` E-04 SHA-256 was truncated to 63 characters in the recommendation. The locally rehashed file and foundation-entry-01 return both give **`f42590051fadb44830b2607266d67a844c6d92b8b1735479ffba8d0cc21e728e`**. This corrects the documentation receipt only; it does not authenticate the npm installation.

## 3. Proposed package and build contract

| Root | Proposed internal metadata and contents | Artifact boundary |
|---|---|---|
| `server/` | Distribution `mach33-duranki-server`; import `duranki_server`; `pyproject.toml` with `[build-system] requires = ["uv_build==0.13.1"]`, `build-backend = "uv_build"`, and `[tool.uv.build-backend] module-name = "duranki_server"`. `Private :: Do Not Upload` classifier; no invented license or LiteLLM dependency. | Build sdist, then wheel from that sdist. Include only package module and required metadata; stub has no service startup. |
| `clients/python/` | Separate distribution `mach33-duranki-client`; import `duranki_client`; same pinned build system and explicit `module-name = "duranki_client"`. `Private :: Do Not Upload` classifier; no server, gateway or training dependency. | Build sdist, then wheel from that sdist; install wheel by verified local path into a clean consumer. |
| `clients/js/` | Scoped provisional `@mach33/duranki-client`; plain `.cjs` source, `type: "commonjs"`, `main`/`exports` targeting `./index.cjs`, `engines.node: ">=24 <25"`, `private: true`, and `files: ["index.cjs"]`; no dependency or lifecycle scripts. | `npm pack` tarball must contain `package.json` and `index.cjs` only, apart from unavoidable npm metadata. Install by verified local tarball path; no ESM/transpiler. |

These private metadata guards prevent accidental upload but do not confer confidentiality, registry ownership or license rights [W7,W8]. The owner must approve minimal unpublished/internal metadata before writing it. No public index name resolution, package publication, license invention or workspace link is part of FND. Provisional names can change only by amendment before package writes. Full API/export and capability choices remain later work.

**Proposed execution sequence after the gate passes and a commission is issued:** create metadata and stubs directly at the allowed paths; keep three independent roots and no root workspace. Use the explicit approved Python/uv and `uv_build==0.13.1`, record frontend/backend/isolation mode, set offline/no-index and disable Python downloads. Build each sdist into a fresh temp output directory, then build its wheel *from that sdist*; use `--no-create-gitignore` so uv does not add an unlisted file. If bundled backend selection fails or tries external retrieval, stop. `uv.lock` files are allowed source outputs but their existence is not backend-execution proof. Any third-party requirement discovered in a lock or archive needs a revised allowlist and approval before resolution.

Pack JS with selected Node/npm, `--ignore-scripts`, `--offline`, a controlled cache and `--pack-destination` inside the temp run area. Inspect manifest and archive entries before installing. Repeat independent clean builds from the same recorded source bytes and selected toolchain in distinct temp directories/caches; compare sdist, wheel and tarball hashes. If hashes differ, investigate timestamps/metadata and record exact discrepancy and corrected repeat proof, or fail reproducibility. A single successful import cannot satisfy this check.

Install **only** the built client wheel and tarball by their verified absolute artifact paths into separate fresh consumers outside the checkout. Use offline, no-index/no-dependency behavior for Python and offline, no-script behavior for npm; confirm the dependency closure from installed metadata/lock records. Execute `require('@mach33/duranki-client')` under selected Node and `import duranki_client` under selected Python with working directories outside all source roots, no `PYTHONPATH`, editable install, workspace link or globally installed Duranki package. Record resolved module paths under each consumer's environment. Do not import the server application, call a network API or infer functional compatibility from package imports.

## 4. Exact proposed repository write surface

The following **19 file paths** are the complete proposed repository-file manifest for a later issued WP-FND. Check each path for collision immediately before any future write; no path is created by this draft. Any change requires an explicit delta and approval.

1. `.gitignore`
2. `.python-version`
3. `.nvmrc`
4. `docs/architecture/llm-routing-infra-design-v1.1.md` — byte-identical source copy
5. `docs/architecture/review-tracker.md` — byte-identical source copy
6. `docs/foundation/WP-FND-RECEIPT-01.md`
7. `server/pyproject.toml`
8. `server/uv.lock`
9. `server/src/duranki_server/__init__.py`
10. `clients/python/pyproject.toml`
11. `clients/python/uv.lock`
12. `clients/python/src/duranki_client/__init__.py`
13. `clients/js/package.json`
14. `clients/js/package-lock.json`
15. `clients/js/index.cjs`
16. `tests/foundation/README.md`
17. `tests/foundation/js-consumer/package.json`
18. `tests/foundation/js-consumer/require.cjs`
19. `tests/foundation/python-consumer/import_client.py`

The two source copies use `/Users/larrymitchell/Mach33/LLM_Routing/` as the current controlling location. Record source and copied SHA-256; reject a mismatch. If expressly issued, `git init -b main` may create local `.git/` **after** the read-only gate and before substantive source files, with an unborn `main` branch. Git staging, commit, remote configuration and push are **excluded**. Do not use `uv init` defaults that create Git state. Generated lockfiles are included above; no other repository artifacts, `.venv`, `dist`, `node_modules`, logs or caches are authorized.

### Permitted auxiliary effects for a future issued run

Propose one fresh, collision-checked run tree **under** `/private/tmp/duranki-fnd-01/`, with separate `build-a/` and `build-b/` directories (each with its own cache), `consumers/python/`, `consumers/js/`, `tmp/`, `logs/` and `evidence/` areas. Do not reuse or delete an existing tree. Copy the test-consumer files listed above into that tree before running them; installations and generated consumer lockfiles stay there. Point `TMPDIR`, `UV_CACHE_DIR`, npm cache/log configuration and build output there; prevent checkout bytecode with `PYTHONDONTWRITEBYTECODE=1` and place any required environment/bytecode inside the run tree. Use explicit selected tool paths; prefix PATH for npm's env-node shebang and record the resulting process versions. Disable npm lifecycle scripts, npm audit/update network behavior, uv Python downloads and unapproved configuration or shared-cache discovery. Verify all effective settings in the receipt before invoking tools. No shared cache deletion, global toolchain switch or write outside the approved repository manifest and fresh run tree is implied.

Any future metadata/artifact retrieval is a separate, narrow preflight grant naming host, exact artifact, expected digest, license, destination and TLS/signature verification. No artifact download is authorized by this draft. Once approved artifacts exist, the build/install/import sequence is offline and fail-closed; unexpected backend, package or runtime retrieval stops the work.

## 5. Acceptance evidence and stop conditions

| Case | Required foundation observation |
|---|---|
| FND-01 custody | Physical root, initial inventory, original/copy architecture and tracker hashes, planning/E02-01 preservation, and unchanged protected file receipts. |
| FND-02 toolchain | Actual executable/child paths, versions, binary hashes, provenance verification chain, npm closure, backend route and Node security disposition; no fallback to defaults. |
| FND-03 archives | Two Python sdists and wheels built from sdists, JS tarball, archive manifests, private metadata, exact contents and artifact hashes; no server/architecture/test/credential material in clients. |
| FND-04 reproducibility | Independent clean builds from identical source/tool inputs; matching artifact hashes or a documented, resolved discrepancy with repeat proof. |
| FND-05 consumers | Clean installed CommonJS and Python clients import by package name from their temp consumer environments; resolved module paths and dependency closure show no checkout/global/workspace/editable source. JS has no Python/server dependency; Python client has no server/training/gateway dependency. |
| FND-06 boundary | Only the 19 repository files, conditional authorized `.git/` and approved temp effects exist; no stage/commit/remote/push, publication, service, provider, gateway or Vega action. |

Any missing authority, unresolved exact-artifact provenance or security disposition, source mismatch, collision, unapproved dependency/retrieval, package coupling, out-of-scope write, failed clean import or unresolved reproducibility discrepancy is a stop. Record BLOCKED with evidence; do not repair by silently changing versions or widening scope. Documentary readiness, verified local artifact selection and actual build/import evidence are three different states. C3 request-to-outcome proof, B pinned gateway qualification and D operational acceptance cannot be credited by WP-FND.

## 6. Review handoff and evidence attribution

The next owner action is explicit adoption of the decision block and issuance of a bounded WP-FND instrument after the unresolved preflight conditions are settled. Even after issuance, completion ends at the foundation receipt; later work needs its own authority. This draft uses foundation-entry-01 recommendations as local executor reports and Foundation Entry Review 01 §§4–8 as a **separately attributed public-source supplement**. The review checked W1–W12 on 16 October 2026; this draft did not independently fetch those pages or verify downloaded binaries. Local version reports, file hashes and Homebrew receipts are observations, not publisher artifact attestation.

**Public-source locators from the review:** [W1] `https://www.python.org/downloads/release/python-31215/`; [W2] `https://nodejs.org/en/blog/release/v24.22.0`; [W3] `https://nodejs.org/en/blog/vulnerability/october-2026-security-releases`; [W4] `https://github.com/astral-sh/uv/releases/tag/0.13.1`; [W5] `https://pypi.org/project/uv-build/0.13.1/`; [W6] `https://docs.astral.sh/uv/concepts/build-backend/`; [W7] `https://docs.astral.sh/uv/concepts/projects/build/`; [W8] `https://docs.npmjs.com/cli/v11/configuring-npm/package-json/`; [W9] `https://docs.astral.sh/uv/reference/environment/`; [W10] `https://docs.npmjs.com/cli/v11/commands/npm-cache/`; [W11] `https://docs.npmjs.com/cli/v11/commands/npm-pack/`; [W12] `https://discuss.python.org/t/python-3-10-22-3-11-17-3-12-15-3-13-16-and-3-14-8-are-now-available/109296`.
