# WP-B/DKR-01 Docker Target — Correction 02

**Status:** the selected LiteLLM v1.105.1 commit `d665dc1a6315847fcad6cc2c1264ceb47c06abce` and Docker Desktop Linux ARM64 preparation target are retained. DEC-13 source selection, adopted A2 and accepted foundation are unchanged. This correction does not issue a build or WP-B/B1 runtime proof.

## Observed interface and proposed identities

LM-01 supplied `docker --context desktop-linux info --format 'os={{.OSType}} arch={{.Architecture}} name={{.Name}}'` with output `os=linux arch=aarch64 name=docker-desktop`: `OWNER_OBSERVED_ENGINE_AVAILABLE_LINUX_ARM64`. The excerpt has no separate exit-status field or exact timestamp. The earlier sandboxed executor socket result remains `EXECUTOR_ACCESS_DENIED`; it was not repeated. Neither observation establishes available images, Buildx behavior or permission for a mutating Docker operation.

| Exact metadata role | Proposed repository/tag | Query platform | Current state |
|---|---|---|---|
| `python_builder` | `library/python:3.12.15-bookworm` | `linux/arm64/v8` | Metadata and layers not acquired |
| `python_runtime_and_tools` | `library/python:3.12.15-slim-bookworm` | `linux/arm64/v8` | Metadata and layers not acquired |
| `rust_toolchain` | `library/rust:1.88.0-bookworm` | `linux/arm64/v8` | Metadata and layers not acquired |

The helper now rejects any role/query mismatch before requesting data and writes only fixed role-based index, child-manifest and config filenames beneath its selected run. Mocked complete and partial owner workflows verify receipts and a Downloads-style handoff. They do not establish publisher availability or approve these image tags. Proposed Python patch **3.12.15** is used consistently for resolution markers; proposed glibc **2.36** is the numeric wheel compatibility ceiling. Both remain input proposals pending exact image and artifact verification.

## Recipe boundary

Compose retains three actors, two internal bridges, four separate volumes, no published ports, non-root UID 10001, read-only roots and `pull_policy: never`. The two Dockerfiles now copy trusted harness inputs as root-owned files and set 0444 file and 0555 directory modes before changing to UID 10001. Synthetic staged tools and runtime contexts verify the 0600 source → readable, non-writable image-mode relationship. No image was built or run. Labels, `internal: true` and static permissions do not prove namespace containment or final-send control.

The [C02 inputs](DURANKI-WP-B-BUILD-INPUTS-01-CORRECTION-02.json) remain `ready_for_build: false` and `owner_build_approval: false`. Python graph/wheel hashes, OCI layers, Cargo/native closure, enterprise entitlement, security/change review and actual local image identity require separate evidence and owner disposition. Runtime proof further requires the B1 harness, policy helper and independent receiver. WP-B/B1 and WP-C remain `NOT_ISSUED`.
