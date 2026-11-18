# WP-B/DKR-01 Docker Target — Correction 01

**Status:** Linux ARM64 Docker Desktop/Compose preparation target retained. LiteLLM v1.105.1 at commit `d665dc1a6315847fcad6cc2c1264ceb47c06abce` remains the selected experimental source. This correction does not issue WP-B/B1, authorize a build, or change DEC-13, A2 or foundation adoption.

## Interface observations

LM-01 supplied the normal Terminal command `docker --context desktop-linux info --format 'os={{.OSType}} arch={{.Architecture}} name={{.Name}}'` and output `os=linux arch=aarch64 name=docker-desktop`. Record `OWNER_OBSERVED_ENGINE_AVAILABLE_LINUX_ARM64`. The supplied excerpt has no separate exit-status field or exact observation timestamp. This is the owner interface, not executor access or a Buildx/build test. The original executor commands to that context's socket ended in `permission denied`; `EXECUTOR_ACCESS_DENIED` remains unchanged. No daemon command was repeated here.

## Corrected preparation boundary

The [input record](DURANKI-WP-B-BUILD-INPUTS-01-CORRECTION-01.json) names the selected source, 54 proxy requirements, separate proxy-extras/enterprise metadata, Maturin, four critical transport sdists, three proposed OCI tags and Rust/Cargo/native unknowns. Its `ready_for_build` and `owner_build_approval` remain false. The [helper](../../../tests/gateway-proof/docker/prepare.py) offers a fresh-run owner command that acquires bounded official metadata and feeds the selected roots to an online, no-build, wheel-only uv resolution against official PyPI. It records unresolved edges and produces a verified packet in Downloads. The command has **not** been run against the network in this correction; no fetched artifact, completed graph or Docker image is claimed.

The three future actors stay driver → guarded gateway → independent receiver. Compose retains two internal networks, four separate evidence/intent volumes, non-root read-only services, no published ports, and now `pull_policy: never` on all services. These are recipe properties only. Exact local image identities, layer custody, a short-lived namespace policy helper and independent receiver observations are future gates; `internal: true` and labels alone do not establish containment.

## Later gates

A future reviewed build needs complete and independently checked Python wheel hashes/tags, Maturin and Cargo/native closure, selected Linux ARM64 OCI child digests/layers, entitlement/license and security/change disposition, then explicit owner approval. A staged context remains data-only. B1 additionally requires an issued runtime proof, guarded final dispatch and observed containment. WP-C is separate. The accepted foundation and adopted A2 contract are preserved.
