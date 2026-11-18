# WP-B/DKR-01 Docker Preparation Target

**Additive owner amendment:** LM-01 selects the existing local Docker Desktop and Compose as the **preparation target** for Linux ARM64 (`linux/arm64`). The earlier disposable macOS ARM64 guest and single-guest loopback topology are not prerequisites for this kit. This does not change [DEC-13 source selection](../DEC-13-CANDIDATE-SELECTION-01.md), the [adopted A2 contract](../../contracts/WP-A-A2-ADOPTION-01.md), the accepted foundation, or historical `PROPOSED`/`NOT_RUN` labels. It selects neither base-image bytes nor an executable dependency set. WP-B/B1 runtime and WP-C remain unissued.

## Observed local interface

On 17 October 2026 local time, `docker --version` reported CLI **29.6.2**, `docker compose version` **v5.3.1**, and `docker buildx version` **v0.35.0-desktop.2**. `docker context show` returned `desktop-linux`; a narrow `docker context inspect desktop-linux` returned `unix:///Users/larrymitchell/.docker/run/docker.sock`. Docker Desktop is installed locally. These facts establish a local context name and endpoint path, not an accessible engine or target architecture.

With explicit `--context desktop-linux`, both `docker version --format 'client={{.Client.Version}} server={{.Server.Version}}'` and `docker info --format 'os={{.OSType}} arch={{.Architecture}} name={{.Name}}'` exited **1** with `permission denied while trying to connect to the docker API at unix:///Users/larrymitchell/.docker/run/docker.sock`. The executor stopped daemon access; no alternate endpoint, sudo or socket workaround was used. Server OS/architecture, Buildx builder and image availability are **NOT CHECKED**. The exact argv, cwd, stdout/stderr and status are in the review evidence. Image/container creation and network policy were not attempted.

## Actors and owned resources

The authored [Compose file](../../../tests/gateway-proof/docker/compose.yaml) defines three future actors: a stdlib driver, the selected real gateway with its out-of-tree guard, and an independent stdlib receiver. `-p duranki-wpb-<collision-checked-run-id>` namespaces two internal bridges and four labeled volumes. No host port, Docker socket, home/workspace mount, external network or global container name is declared. The gateway writes only intent and gateway-log volumes; the receiver alone writes its traffic volume; the driver writes its observation volume. A host operator exports evidence after shutdown. Labels aid ownership review and are not isolation controls.

| Flow | Intended address | Policy |
|---|---|---|
| Driver → gateway | `gateway:4000` on `ingress` | Admit signed synthetic requests only; established replies allowed. |
| Gateway → receiver | `receiver:8000` on `provider` | The only model-send destination after FDC and durable intent. |
| Driver control/liveness → receiver | No direct bridge membership | Host-controlled evidence or a separately reviewed control path; receiver health traffic must be identified separately. |
| Gateway → driver, other peers, host/VM management, public Internet | Any address | Deny in the future namespace policy; probe both alternate loopback and external targets. |
| Docker embedded DNS | `127.0.0.11:53` if required | Allow only after verifying necessity and bounded behavior; record DNS and resolved receiver IP. |

`internal: true` and bridge memberships express the initial topology. They do **not** prove directional or port-specific filtering, host/VM isolation, IPv4/IPv6 behavior or DNS confinement. The concrete proposed enforcement is a **short-lived, project-scoped network-namespace policy helper**. A future `tests/gateway-proof/net_policy.py` plus reviewed policy image would join only the collision-checked gateway container's network namespace with temporary `NET_ADMIN`, install default-deny `inet` output/input rules permitting the verified driver ingress, established replies, required embedded DNS and the frozen receiver IP:8000, read back the rules, write an authenticated run/namespace/rules receipt, then exit. It must have no host namespace, privileged mode or persistent gateway capability. The gateway wrapper must remain a non-LiteLLM wait process until that receipt is verified; a restarted/recreated namespace requires re-application before import/start. This helper, its image, address-discovery logic and socket-policy proof are **future B1 inputs, not present or run here**. Docker Desktop's actual support remains unchecked because its daemon denied access. No untrusted gateway process may start merely because Compose parses.

The driver/host operator is trusted infrastructure; the independent receiver's log volume is not gateway writable. This is not a kernel-escape or administrator-adversary claim. Network containment supplements, rather than replaces, final-dispatch control at the actual write boundary.

## Next gates

The owner may supply one read-only `docker --context desktop-linux info --format 'os={{.OSType}} arch={{.Architecture}} name={{.Name}}'` result from the normal permitted Terminal, or provide this executor access to that **specific** local daemon query. That is the smallest missing Docker capability observation. Separate authorization is required for exact artifact acquisition/approval and offline builds; B1 runtime additionally requires the implemented policy helper, harness, positive-control receiver proof and explicit issuance. No platform switch follows from this denial.
