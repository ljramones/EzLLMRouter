# WP-FND Receipt 03

**Result:** `READY_FOR_INDEPENDENT_FOUNDATION_REVIEW` · **Run:** 16 October 2026 · **Root:** `/Users/larrymitchell/Mach33/Duranki` · **Temporary run:** `/private/tmp/duranki-fnd-01/run-20261016-03/`. This records one executed, bounded, offline foundation run. It does not grant or claim independent acceptance, application functionality, gateway qualification, Vega connection, or a later work package.

## Operative authority and entry gate

LM-01’s in-session **WP-FND Resumption 03** is the operative renewal and starting-state amendment to `DURANKI-WP-FND-ISSUANCE-01.md` (SHA-256 `787f4720b438b96a1cbb8739766a958346994ed922573fb2f95c73eb3b515387`) and incorporated commission draft (SHA-256 `d20564b0a9162c74a4d2d336bfacff0362a1b24d2f6d30fb29e209e69ed797c5`). The issuance adopted Plan v0.2 plus the separate E02-01 overlay, DEC-01/02/15, the private unpublished package metadata, selected artifacts, and scoped exception `FND-EX01`; the historical documents retain their original status text. Resumption 03 replaces the no-Git starting-state and Codex-init requirements with the owner-created local `.git/`, and replaces receipt 01/02 with this new receipt path. The exception was renewed only for this run and expires at its completion. No new toolchain or risk decision was made here.

| Final read-only gate | Result and evidence |
|---|---|
| Authority and boundary | `SATISFIED`: issuance and LM-01 Resumption 03 authorize only this offline run, eighteen non-receipt files, receipt 03, and one fresh temporary child. No Git writes. |
| Root and Git | `SATISFIED`: physical root and local Git dir are the path above and its `.git/`; symbolic HEAD `refs/heads/main`; unborn HEAD (verify exits 128); no staged entries or remotes. `GIT_OPTIONAL_LOCKS=0`; see `logs/git-state-final.json`. |
| Source custody and collisions | `SATISFIED`: 27 protected files matched their previous receipts, all 19 current write paths were clear, and the fresh child run did not exist. Architecture, tracker, plan, register, erratum, draft, issuance and prior receipts matched recorded hashes. Node tree 5,779/5,779 entries and the 92 scoped Homebrew installed inputs matched their accepted records. |
| Selected tools and local evidence | `SATISFIED`: selected binary/script and provenance-record hashes matched §2. Versions were Python 3.12.15, Node 24.19.0, npm 11.17.0, uv 0.13.1, Git 2.56.0. `uv` build logs prove bundled `uv_build` execution. |
| Native signatures and Node security | `SATISFIED_BY_RECORDED_OWNER_EXCEPTION`: prior Python native signature/resource-layout failures, authenticated Node archive member signature failure, and announced Node 24.x security risk remain **KNOWN_FAILURE — OWNER_EXCEPTION_ACCEPTED_FOR_FND** under `FND-EX01`; none is relabeled PASS or assessed as generally safe. The issuer’s 16 October primary-source advisory refresh is incorporated; no new local publisher query or network access occurred. |
| New material blocker | `SATISFIED`: none found in the scoped entry checks or foundation execution. |

The prior `WP-FND-RECEIPT-01.md`, `WP-FND-RECEIPT-02.md`, their archives and previous scratch runs remain unchanged. The preceding 27-file inventory includes both receipts; the final audit must still confirm it after this receipt is written.

## Selected execution inputs and controls

| Input | Selected path | SHA-256 |
|---|---|---|
| Python 3.12.15 | `/opt/homebrew/Cellar/python@3.12/3.12.15/bin/python3.12` | `c4e9f06cb179ae4b3728c748990fbbef7f30580ea42c0eb9c702ebc7c7861c89` |
| Node 24.19.0 | `/private/tmp/duranki-provenance-01/run-20261016-02/node-reference-tree/node-v24.19.0-darwin-arm64/bin/node` | `27db838bb204ef7c21df2931f5656e4c8fb32e6e947f363a402b49714d32b5b1` |
| npm 11.17.0 script | `/private/tmp/duranki-provenance-01/run-20261016-02/node-reference-tree/node-v24.19.0-darwin-arm64/lib/node_modules/npm/bin/npm-cli.js` | `8e5f6f3429f8cdbe693cdc29904e9d5a7b127a494bd15c804bd54c7403bfcbe7` |
| uv 0.13.1 | `/opt/homebrew/Cellar/uv/0.13.1/bin/uv` | `cfe5e5695316639f9820e8e57d0732e8a361311c03f1ea1786f4fc879cebf4c5` |
| Git 2.56.0 (read only) | `/opt/homebrew/Cellar/git/2.56.0_1/bin/git` | `92229f2456a49561ac5d614bbed775224e2fc32a8eca22ac41aeb3ce47d7899c` |

Selected pristine Node reference manifest: `ebf1198a622916fec0c30a2a6dd3be1194076dd3a7123876669c4ae544cc791f`; scoped Homebrew comparison: `815160667fa1bef25dc6bf5f9914b9e1781f75354fd3d09411753f82f6fe768f`; verification audit: `647abd32df908e8ee58926c6f13b293ce7338355211e78fda29727493f4575e8`. Their previous signature/trust evidence and limitations remain attributed to those records. Local license receipts include Node `LICENSE` `148eacf7863ef4329224a29398623077200a27194aa075569faf4a0a85566ca5`, npm `LICENSE` `7610d223851f421d315df5e77974f1c68a04b97e02060e5bbbcf13d95e3ca257`, Python `LICENSE` `3b2f81fe21d181c499c59a256c8e1968455d6689d269aa85373bfb6af41da3bf`, uv MIT/Apache license receipts `860e3d7a86b84e6a7012c7a635fc64df475cebc6cce34dfeb73a5982ec58176c` / `c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4`, and Git `COPYING` `5b2198d1645f767585e8a88ac0499b04472164c0d2da22e75ecf97ef443ab32e`. These license receipts do not resolve the accepted native-signature findings.

All package operations used explicit selected executable paths, sanitized environment, a temp `HOME`/`TMPDIR`, isolated uv/npm caches and config, `UV_OFFLINE=1`, `UV_PYTHON_DOWNLOADS=never`, `--no-index`, npm `offline`, `ignore-scripts`, disabled audit/update requests, and `PYTHONDONTWRITEBYTECODE=1`. npm was launched as selected Node plus its authenticated `npm-cli.js`; `logs/tool-process-identity.json` records actual Node `process.execPath` and npm version. No selected tree, shared cache, installed tool or `.git/` was written.

## Package build and archive evidence

`server/` builds distribution `mach33-duranki-server` / import `duranki_server`; `clients/python/` builds independent `mach33-duranki-client` / import `duranki_client`; `clients/js/` packs private CommonJS `@mach33/duranki-client`. Python projects declare `uv_build==0.13.1`, explicit `module-name`, no runtime dependencies, and private metadata. JS has no dependencies or lifecycle scripts. Both Python sdists were built from source. Wheels were built from safe-extracted, member-checked copies of those exact sdists in the temporary tree using uv’s logged bundled backend. No copied source or wheel build output was placed in the repository.

| Artifact | Build A SHA-256 | Build B SHA-256 | Repeated match |
|---|---|---|---|
| `server_sdist` | `f1045d5296a103b16845e24338fd7fe3109f6b996bd9e796b3ff8edeb1de7642` | `f1045d5296a103b16845e24338fd7fe3109f6b996bd9e796b3ff8edeb1de7642` | YES |
| `server_wheel` | `d74ec0941174f000820cf9330a2faa63038bd70e268f257860bf40d3b0c9a1d3` | `d74ec0941174f000820cf9330a2faa63038bd70e268f257860bf40d3b0c9a1d3` | YES |
| `client_sdist` | `16e2abf65f820f8d499538ceb86ec82952a7303bdd553267b7160b008d96589c` | `16e2abf65f820f8d499538ceb86ec82952a7303bdd553267b7160b008d96589c` | YES |
| `client_wheel` | `e162a706d889cf41d96cdb9e77ebc1a0351d049b4df47e464f1b1c747c7e6f04` | `e162a706d889cf41d96cdb9e77ebc1a0351d049b4df47e464f1b1c747c7e6f04` | YES |
| `js_tarball` | `231fb69d51b95241558d512ac17a439bdef2cf0bb0488f94236da05ee8e9bb11` | `231fb69d51b95241558d512ac17a439bdef2cf0bb0488f94236da05ee8e9bb11` | YES |

Build A artifacts are under `run-20261016-03/build-a/{server,client,js}/`; Build B counterparts under `build-b/`. Exact paths, sizes, per-member names/hashes and comparisons are in `logs/artifact-audit.json`. The Python sdists each contain `PKG-INFO`, generated `pyproject.toml`, an exact-byte `pyproject.toml.orig` copy of the source metadata, and one inert module. Wheels contain that module and standard dist-info only. The JS tarball contains only `package/index.cjs` and `package/package.json`. No server, architecture, test, credential, gateway or training file is in a client archive. Both uv locks name only their local root package; JS source lock names only itself.

A direct `uv build <server-sdist.tar.gz> --wheel --no-index --offline` attempt exited 2 because isolated PEP 517 resolution could not find `uv-build==0.13.1` in the empty offline cache. It made no extra repository file. The authorized resolution was to validate and unpack the sdist in the fresh temporary run, then `uv build <unpacked-sdist-root> --wheel --no-index --offline` using the bundled backend; the log states `Using bundled uv_build backend`. The same safe sdist-derived method was used for both packages in both build runs. No backend wheel was fetched or installed.

## Installed consumers and FND outcomes

The Python client wheel was installed from its verified absolute Build A path into `consumers/python/venv/` with `uv pip install --no-deps --no-index --no-build --offline`; `direct_url.json` identifies that wheel. Executing the copied consumer script under the venv interpreter with `-I -B` resolved `duranki_client` at `consumers/python/venv/lib/python3.12/site-packages/duranki_client/__init__.py`, version `0.0.0`, with no `Requires-Dist`. The JS tarball was installed from its verified absolute Build A path in `consumers/js/` with offline npm and scripts disabled. Its lock resolves a relative `file:` reference to that tarball with no transitive entries. Selected Node resolved `@mach33/duranki-client` at `consumers/js/node_modules/@mach33/duranki-client/index.cjs`, version `0.0.0`. See `logs/consumer-*.json` and the copied test drivers. Neither consumer used a checkout, editable, workspace or global Duranki package.

| Case | Result |
|---|---|
| FND-01 custody | **PASS** — physical root, protected 27-file inventory, architecture/tracker byte-identical copies and controlling-source hashes; prior receipts/runs preserved. |
| FND-02 toolchain | **PASS with recorded owner exception** — selected versions, paths, hashes, pristine Node tree, scoped Homebrew inputs and bundled backend verified; native-signature and Node-security findings remain `KNOWN_FAILURE — OWNER_EXCEPTION_ACCEPTED_FOR_FND`. |
| FND-03 archives | **PASS** — two Python sdists, wheels from sdists and JS tarball with inspected private metadata and bounded contents. |
| FND-04 reproducibility | **PASS** — independent A/B caches and output trees produced identical hashes and member manifests for all five artifacts. |
| FND-05 consumers | **PASS** — both local-artifact, fresh installed consumers import by package name from their temp environments; no cross-package or third-party dependency. |
| FND-06 boundary | **PASS** — exactly the authorized 18 non-receipt source files plus this receipt, no unexpected repository file, and one fresh temp run; Git remains read-only unborn `main` with no staged path, commit or remote. |

## Exact new repository-file manifest

The 18 hashed paths below were the complete new non-receipt write set in `logs/boundary-audit-pre-receipt.json`. This receipt is the nineteenth path. Its own SHA-256 is intentionally outside its contents and is reported in the return.

| Path | SHA-256 |
|---|---|
| `.gitignore` | `187458c55d5114a45bf2a0b645c23d0728e6ef35952739a1df535c054ca181ef` |
| `.nvmrc` | `b7677d3ec37ee1897ba07dc2cfe8292fe421c9ac93396cca5bbece486d1a2a41` |
| `.python-version` | `7b55f8e67b5623c4bef3fa691288da9437d79d3aba156de48d481db32ac7d16d` |
| `clients/js/index.cjs` | `f26b8b24cad41704e977974f0b4ab6339da3e557c157ce613901f7125969fcfb` |
| `clients/js/package-lock.json` | `15fc2da74ff8a53583d3cd180437d2c0de6988feb75da4ab8c4de022051bb9ea` |
| `clients/js/package.json` | `6091bdaebd326710742640885e54e0a0d33fd394874c087fe9a8037b9fdb10f2` |
| `clients/python/pyproject.toml` | `b2d519336421b7e240a2b18c945825071656f6380df6551b74c1f5cbf3f97ceb` |
| `clients/python/src/duranki_client/__init__.py` | `64a5e3ea85d8e0e666edcbbdd0b2ca73c78b7d283faef5090e7110ab2290cbf8` |
| `clients/python/uv.lock` | `1d9c2f0a446a5262d7186a23b7527a39431f81a945e351985330b8ddb34d921b` |
| `docs/architecture/llm-routing-infra-design-v1.1.md` | `8f3ab5b86a8533687da6cb0e80e16b8d7586fc7392c02a646b8c08025aee7e9c` |
| `docs/architecture/review-tracker.md` | `36be1ae781fb6645fa186881eb967e7118f24dbf585913f2f8e0da9b1e1260ac` |
| `server/pyproject.toml` | `dfd232b2294773ce9f908352fe4d386d40723aec6f18aa8eb485388ca6d4680f` |
| `server/src/duranki_server/__init__.py` | `79806e8cfdb91e7911997a3a7a46f1c35020f3f5bc52e0f0ce737b198fa3f6aa` |
| `server/uv.lock` | `81103f69b2446fcc0b5bb51a976b75da2d4a8c16534b1e839424e68368f72f15` |
| `tests/foundation/README.md` | `d7257851c96d65326a046b07357349306a2e40d34e57394420fbf4e1505a913c` |
| `tests/foundation/js-consumer/package.json` | `e95eecf8300839a5579601d612bcfbaee3959e8ddbdcdd12c53b8989f6569637` |
| `tests/foundation/js-consumer/require.cjs` | `fd4389a64b6a54137f63da57d1d614dec14d08c2ca542166174fe46bfe5e5294` |
| `tests/foundation/python-consumer/import_client.py` | `89987156a53faed75e3b35242fdf76c20af8d86a7fc0fbb072dbf933d5960f11` |
| `docs/foundation/WP-FND-RECEIPT-03.md` | Reported in return; excluded from self-hash. |

The controlling architecture source/copy SHA-256 is `8f3ab5b86a8533687da6cb0e80e16b8d7586fc7392c02a646b8c08025aee7e9c`; tracker source/copy is `36be1ae781fb6645fa186881eb967e7118f24dbf585913f2f8e0da9b1e1260ac`. Final Git state is recorded in `logs/git-state-final.json`. Previous evidence archives 01/02 retained their recorded hashes. Review archive: `/private/tmp/duranki-fnd-01/run-20261016-03/evidence/WP-FND-REVIEW-EVIDENCE-03.tar.gz`; its manifest and final hash are reported separately to avoid self-reference.

**Stop:** WP-FND ends with this return. No Git stage/commit/remote/push, publication, service, provider call, gateway experiment or Vega connection occurred. Later implementation requires separate authority.
