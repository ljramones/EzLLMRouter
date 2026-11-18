# WP-FND Foundation Receipt 01

**Disposition:** `BLOCKED_WITH_EVIDENCE` on 16 October 2026 (America/Toronto). WP-FND was issued for one bounded offline run; foundation implementation and independent acceptance were not completed. No follow-on work package is issued by this receipt.

## Authority and entry gate

LM-01's operative issuance is `/Users/larrymitchell/Downloads/DURANKI-WP-FND-ISSUANCE-01.md`, SHA-256 `787f4720b438b96a1cbb8739766a958346994ed922573fb2f95c73eb3b515387`. It incorporates `docs/implementation/foundation-entry-02/DURANKI-WP-FND-COMMISSION-DRAFT-01.md`, SHA-256 `d20564b0a9162c74a4d2d336bfacff0362a1b24d2f6d30fb29e209e69ed797c5`, with the explicit Node-path amendment. This external issuance was not copied into the repository.

For this run LM-01 adopted Implementation Plan v0.2 and the E02-01 overlay, DEC-01's macOS arm64 Python `>=3.12,<3.13` and Node `>=24,<25` foundation targets, DEC-02's three independent private package roots, DEC-15's independent root and conditional unborn-main Git initialization, and internal metadata version `0.0.0`. Original plan, register and erratum bytes remain unchanged. Other architecture, capability and operational decisions remain open.

`FND-EX01` is the owner-accepted exception for this one offline packaging/import workload: the unresolved Python native-signature/resource-layout failures, native-signature failure on authenticated Node archive bytes, and residual announced Node 24.x security-update risk. These failures remain **`KNOWN_FAILURE — OWNER_EXCEPTION_ACCEPTED_FOR_FND`**, not technical passes. No vulnerability-free or independent security-review claim is made. The issuer's 16 October refresh of the Node October 2026 notice reports a planned release on or shortly after 21 October, with HIGH the highest announced severity for 24.x; no shipped fix or offline non-impact is inferred.

The final read-only entry gate was `SATISFIED` for root, custody, collision, selected input, license, offline-effect and source identity checks, and `SATISFIED_BY_RECORDED_OWNER_EXCEPTION` for the known native-signature/security conditions. The physical root is `/Users/larrymitchell/Mach33/Duranki`, outside Mach-Platform and without root or enclosing Git metadata. All 19 authorized file paths were absent before mutation. The approved `/private/tmp/duranki-fnd-01/` parent was absent before creating fresh child `run-20261016-01`.

The initial inventory contained **25 files**. All **26** historical closure-return source receipts matched current bytes; four obsolete Downloads paths were reconciled by their byte-identical restored copies in the prior provenance run. Architecture v1.1 (`8f3ab5b86a8533687da6cb0e80e16b8d7586fc7392c02a646b8c08025aee7e9c`), tracker (`36be1ae781fb6645fa186881eb967e7118f24dbf585913f2f8e0da9b1e1260ac`), plan v0.2 (`852d58be6087c1952f8349b429029f23c9235c86236b26dcf3ed69d3758aebab`), register v0.2 (`ea4657b342be60e5bb785d9093130aa980503221d9e3c75ee603adaef8eb4e92`), E02-01 (`b94d1ef9d534aac33b8b702f808963ba4e3be5d7152a9f8c5a96f5662122ea7e`) and closure return (`bb57b8dc946ae3887324e78f6a8eecfe79dbe2fee98e13f1d86431f26885e91a`) matched. Full initial paths, sizes and hashes: `/private/tmp/duranki-fnd-01/run-20261016-01/logs/preflight-root.json`, SHA-256 `b580609322158dab265e4d46dd795fad8147cc17e67f87f9d982bb37f9227a89`.

## Selected inputs and effect boundary

| Selected input | Observed version or role | SHA-256 |
|---|---|---|
| `/opt/homebrew/Cellar/python@3.12/3.12.15/bin/python3.12` | Python 3.12.15; resolves into the versioned framework | `c4e9f06cb179ae4b3728c748990fbbef7f30580ea42c0eb9c702ebc7c7861c89` |
| `/private/tmp/duranki-provenance-01/run-20261016-02/node-reference-tree/node-v24.19.0-darwin-arm64/bin/node` | Node v24.19.0 | `27db838bb204ef7c21df2931f5656e4c8fb32e6e947f363a402b49714d32b5b1` |
| `/private/tmp/duranki-provenance-01/run-20261016-02/node-reference-tree/node-v24.19.0-darwin-arm64/lib/node_modules/npm/bin/npm-cli.js` | npm 11.17.0 from bundled `package.json`; script was not invoked | `8e5f6f3429f8cdbe693cdc29904e9d5a7b127a494bd15c804bd54c7403bfcbe7` |
| `/opt/homebrew/Cellar/uv/0.13.1/bin/uv` | uv 0.13.1; proposed bundled `uv_build==0.13.1` route not executed | `cfe5e5695316639f9820e8e57d0732e8a361311c03f1ea1786f4fc879cebf4c5` |
| `/opt/homebrew/Cellar/git/2.56.0_1/bin/git` | Git 2.56.0 | `92229f2456a49561ac5d614bbed775224e2fc32a8eca22ac41aeb3ce47d7899c` |

The signed Node archive input still matched SHA-256 `3f1cf157479c1480352083105e13faf9d008ede98e7e157746b6df940d197b94`. The pristine tree still matched all 5,779 manifest entries (4,708 files, 1,068 directories, three symlinks), with no missing or extra paths. Its manifest (`ebf1198a622916fec0c30a2a6dd3be1194076dd3a7123876669c4ae544cc791f`), scoped Homebrew comparison (`815160667fa1bef25dc6bf5f9914b9e1781f75354fd3d09411753f82f6fe768f`) and provenance audit (`647abd32df908e8ee58926c6f13b293ce7338355211e78fda29727493f4575e8`) rehashed as issued. The 90 Mach-O and two SBOM installed inputs showed no drift from those records. The Node release-key fingerprint is `5BE8A3F6C8A5C01D106C0AD820B1A390B168D356`; the locally recorded Homebrew trust basis and their stated provenance limits were accepted only for this run.

Local license receipts existed and were hashed: Node `LICENSE` `148eacf7863ef4329224a29398623077200a27194aa075569faf4a0a85566ca5`; npm `LICENSE` `7610d223851f421d315df5e77974f1c68a04b97e02060e5bbbcf13d95e3ca257`; Python `LICENSE` `3b2f81fe21d181c499c59a256c8e1968455d6689d269aa85373bfb6af41da3bf`; uv `LICENSE-MIT` `860e3d7a86b84e6a7012c7a635fc64df475cebc6cce34dfeb73a5982ec58176c` and `LICENSE-APACHE` `c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4`; Git `COPYING` `5b2198d1645f767585e8a88ac0499b04472164c0d2da22e75ecf97ef443ab32e`.

The intended build requirement was `requires = ["uv_build==0.13.1"]`, `build-backend = "uv_build"`, with offline uv and no external backend. It was **not executed or proven**. The intended effects were limited to the 19 source paths, conditional `.git/`, and the fresh run tree for caches, builds, consumers, logs and evidence. No download, package resolution, service, gateway, Vega or network action occurred.

## Blocking Git attempt

After the gate, before substantive source creation, the selected Git was invoked with an empty approved template directory, clean environment, disabled system/global configuration and unborn `main` requested:

```text
/opt/homebrew/Cellar/git/2.56.0_1/bin/git -C /Users/larrymitchell/Mach33/Duranki init --initial-branch=main --template=/private/tmp/duranki-fnd-01/run-20261016-01/git-template-empty
exit 1
stderr: /Users/larrymitchell/Mach33/Duranki/.git: Operation not permitted
```

The current workspace permits reading `.git` but denied its creation. `.git/` remains absent. No alternate Git layout, privilege escalation or bypass was attempted. Exact command, environment and result: `/private/tmp/duranki-fnd-01/run-20261016-01/logs/git-init-attempt.json`, SHA-256 `4ecd91ff28314a4264c73f41debeca85163a7bf4d775635d4c56ddb6af906ea1`. The immediate post-attempt audit found the same 25 initial files, no additions, deletions or changed hashes, and no `.git/`: `/private/tmp/duranki-fnd-01/run-20261016-01/logs/post-git-block-audit.json`, SHA-256 `fba4ada460815dfb6628287267368b9346ce80976b72d01ff99f9315aaeb314b`.

This is a new execution-environment blocker outside `FND-EX01`. The run stopped before package metadata, lock generation, builds or consumers. The smallest environmental change for a later attempt is permission to create and write the repository `.git/` path. Because this issued run stopped as blocked, any restart also requires renewed owner authority under issuance §2.

## FND case results

| Case | Result | Evidence and limit |
|---|---|---|
| FND-01 custody | `BLOCKED_NOT_COMPLETED` | Initial root/source custody passed; architecture and tracker copies were not made. Protected initial bytes remained unchanged. |
| FND-02 toolchain | `BLOCKED_NOT_COMPLETED` | Selected paths, versions, hashes and provenance records matched; known native failures retain `KNOWN_FAILURE — OWNER_EXCEPTION_ACCEPTED_FOR_FND`. No npm child, build backend or installed consumer executed. |
| FND-03 archives | `NOT_RUN` | No sdist, wheel or npm tarball was built. |
| FND-04 reproducibility | `NOT_RUN` | No A/B build occurred. |
| FND-05 consumers | `NOT_RUN` | No package installation or import occurred. |
| FND-06 boundary | `BLOCKED_NOT_COMPLETED` | No out-of-scope write or network action observed; `.git/` creation was denied and the run stopped. No stage, commit, remote or push exists. |

## Exact repository output manifest

Only the receipt below was created. `NOT_CREATED` means no source output or package artifact exists at that authorized path.

| Authorized path | Result |
|---|---|
| `.gitignore` | `NOT_CREATED` |
| `.python-version` | `NOT_CREATED` |
| `.nvmrc` | `NOT_CREATED` |
| `docs/architecture/llm-routing-infra-design-v1.1.md` | `NOT_CREATED` |
| `docs/architecture/review-tracker.md` | `NOT_CREATED` |
| `docs/foundation/WP-FND-RECEIPT-01.md` | `CREATED_BLOCKED_RECEIPT` |
| `server/pyproject.toml` | `NOT_CREATED` |
| `server/uv.lock` | `NOT_CREATED` |
| `server/src/duranki_server/__init__.py` | `NOT_CREATED` |
| `clients/python/pyproject.toml` | `NOT_CREATED` |
| `clients/python/uv.lock` | `NOT_CREATED` |
| `clients/python/src/duranki_client/__init__.py` | `NOT_CREATED` |
| `clients/js/package.json` | `NOT_CREATED` |
| `clients/js/package-lock.json` | `NOT_CREATED` |
| `clients/js/index.cjs` | `NOT_CREATED` |
| `tests/foundation/README.md` | `NOT_CREATED` |
| `tests/foundation/js-consumer/package.json` | `NOT_CREATED` |
| `tests/foundation/js-consumer/require.cjs` | `NOT_CREATED` |
| `tests/foundation/python-consumer/import_client.py` | `NOT_CREATED` |

The final inventory is the same 25 protected files plus this receipt; `.git/` is absent. There are no package artifacts or installed-consumer observations. The receipt's own SHA-256 and the review-evidence archive SHA-256 are returned separately to avoid self-reference.
