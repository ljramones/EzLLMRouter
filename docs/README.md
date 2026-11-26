# EzLLMRouter documentation

Current guides for operating and developing CognitiveDynamics EzLLMRouter:

Start with the [current validation and remaining work](TESTING-ROADMAP.md#current-status)
for completed checks, the unresolved glibc report, provenance limits and deferred
load/deployment work. The [review checklist](CODE-REVIEW-FOLLOWUP.md#remaining-review-work)
keeps the original workstream IDs; dated records preserve earlier results.

| Guide | Contents |
| --- | --- |
| [Architecture](ARCHITECTURE.md) | Responsibilities, execution boundaries and external accounting. |
| [API and clients](API.md) | Client interfaces, versioned accounting and recovery behavior. |
| [Users and permissions](USER-MANAGEMENT.md) | First sign-in, roles and account management. |
| [Local connectors](LOCAL-CONNECTORS.md) | Model-server inventory, availability and model selection. |
| [Runtime resources](RESOURCES.md) | Connection/queue limits, shutdown order and gateway cleanup. |
| [Database](DATABASE.md) | Schema upgrades, retention, transactions, shared server logic and HTTP structure. |
| [Encryption](ENCRYPTION.md) | Independent keyrings, offline rotation/retirement, filesystem requirements and backups. |
| [Security](SECURITY.md) | Credentials, transport boundaries and frozen runtime inputs. |
| [Development](DEVELOPMENT.md) | Environment setup, checks and test inputs. |
| [Testing roadmap](TESTING-ROADMAP.md) | Current validation, remaining/deferred work, testing scopes and dated evidence. |
| [Code review follow-up](CODE-REVIEW-FOLLOWUP.md) | Current workstream checklist and historical fix/verification records. |

Start the local accounting console using the [project README](../README.md).
The optional isolated execution profile is described in the
[deployment guide](../deploy/local/README.md).
