# EzLLMRouter architecture

EzLLMRouter is CognitiveDynamics' LLM access, routing, and accounting service.
It supports applications and agents with explicit caller identity, versioned
permissions, attributable attempts, and recorded usage and costs.

## Responsibilities

| Role | Responsibility | Boundary |
| --- | --- | --- |
| Access control | Authenticate callers and enforce grants, restrictions, and current permissions. | Admission does not grant permanent permission to send. |
| Router | Select from permitted configurations and approved recovery paths. | Route selection cannot grant access to another destination. |
| Usage accounting | Record usage revisions, native units, cost provenance, and work attribution. | Missing evidence remains unknown; inclusive parent totals are not additional charges. |
| Evaluation | Record authorized task and step outcomes and compare policies. | A successful API response does not prove task acceptance. |
| Configuration registry | Preserve configurations, grants, versions, and approval state. | Discovery and evaluation do not approve a configuration for use. |

These are responsibilities rather than five independently running agents.
Their implemented interfaces and validation scopes are recorded in the
[current status](TESTING-ROADMAP.md#current-status). Learned routing is future work.

## Controlled execution

```text
Python / JS / TS / Go / Java / C# / Rust client
          |
          v
Coordinator + registry + persistent work records
          |
          v
Isolated request-preparation worker
          |
          v
Trusted final guard + sender ---> authorized model destination

Operator console ---> authenticated metadata and management API
```

The worker prepares a request without receiving provider credentials or network
authority. The trusted service checks the final request against its execution
plan and current permissions, records send intent, and owns transmission.
An unresolved response is queried by work identity before another attempt is
considered. Existing fixed synthetic execution evidence does not establish that
all provider transports or failure modes are qualified.

## External accounting

Applications that make their own provider calls can submit observations through
the versioned integration API. Events bind attempts to an authorized dataset,
provider account, operation, workflow, and executing actor. Receipts support
recovery after an uncertain telemetry delivery. Repeating an observation must
not repeat a provider call or add another charge.

External observations and controlled execution use distinct records. Reports
preserve revisions, provenance, native units, currencies, and explicit unknowns.
Dataset activation and account permissions are owner controlled.

## Implementation

The server uses Python 3.12 and a single SQLite persistence boundary. The browser
console uses JavaScript, HTML and CSS. Python, JavaScript/TypeScript, Go, Java,
C# and Rust clients expose service
and accounting interfaces without calling a provider directly.

All tables use the [versioned database schema](DATABASE.md). Repository
modules own SQL queries; shared transactions keep accounting, credentials,
permissions and audit entries consistent. The operator server separates transport,
authentication, route dispatch and per-server application state.
Shared [formatting, JSON policies, authority bookkeeping and state types](DATABASE.md#shared-server-logic)
preserve the adopted wire contracts and keep transaction ownership explicit.

See [resource ownership and shutdown](RESOURCES.md), the [API guide](API.md),
[security policy](SECURITY.md), and
[development checks](DEVELOPMENT.md). Disposable Linux ARM64 qualification has
passed for the recorded inputs. Real-load acceptance and production deployment
remain deferred; learned routing is future work.
