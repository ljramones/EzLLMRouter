# EzLLMRouter

**LLM access control, routing, and usage accounting by CognitiveDynamics.**

EzLLMRouter connects applications and agents to language models under explicit
permissions. It records who requested work, which agents and models took part,
what was consumed, and what the available evidence says it cost. Unknown usage
or cost stays unknown; retries and delegated work remain attributable.

The goal is the lowest cost of work that meets the required standard.

## Components

| Component | Responsibility |
| --- | --- |
| Access control | Authenticate callers, enforce grants, and recheck permission before sending. |
| Router | Choose among permitted model configurations and follow approved fallback rules. |
| Usage accounting | Record attempts, native usage, revisions, and costs without charging twice for child work. |
| Evaluation | Record authorized outcome evidence and compare results against defined standards. |
| Configuration registry | Preserve versioned model configurations, permissions, and approval changes. |

The Coordinator combines identity, policy, work records, and execution plans.
In the separated execution profile, an isolated model worker prepares requests;
the trusted guard and sender validate and transmit authorized work. The operator
console exposes configuration, connections, activity, and costs.

The external accounting profile also accepts observations from applications that
execute their own model calls. Recording an observation never authorizes or
repeats a model call.

These responsibilities are delivered in stages. Rule-based routing, synthetic
execution, accounting, and evaluation interfaces have different levels of
verification; learned routing and production qualification remain future work.
See the [architecture](docs/architecture/EZLLMROUTER.md) and the existing
[development records](docs/development/HISTORY.md) for implementation evidence.

## Packages

The CognitiveDynamics package line starts at **0.3.0**.

| Package | Distribution name | Public interface |
| --- | --- | --- |
| Python service | `cognitivedynamics-ezllmrouter-server` | `ezllmrouter` command; `ezllmrouter_server` |
| Python client | `cognitivedynamics-ezllmrouter-client` | `ezllmrouter_client` |
| JavaScript client | `@cognitivedynamics/ezllmrouter-client` | CommonJS |

Python packages require Python `>=3.12,<3.13`. The JavaScript client uses Node
`>=24.22.1 <25`. Build locally using the pinned `uv` build backend and Node:

```sh
uv build --offline --no-python-downloads --wheel server --out-dir dist
uv build --offline --no-python-downloads --wheel clients/python --out-dir dist
npm pack ./clients/js --offline --ignore-scripts --pack-destination ./dist
```

These commands build local archives. Packages are private and have not been
published to a registry. Dependencies must already be available locally.

```python
from ezllmrouter_client import EzLLMRouterClient, EzLLMRouterError, IntegrationClient

with EzLLMRouterClient(base_url="http://127.0.0.1:8765", token=token) as client:
    capabilities = client.get_capabilities()
```

```js
const { EzLLMRouterClient, EzLLMRouterError, IntegrationClient } =
  require("@cognitivedynamics/ezllmrouter-client");

const client = new EzLLMRouterClient({ baseUrl: "http://127.0.0.1:8765", token });
const capabilities = await client.getCapabilities();
```

The clients do not automatically replay requests. When a response is lost,
recover the recorded result or receipt before deciding whether to submit again.
See the [Python client](clients/python/README.md) and
[JavaScript client](clients/js/README.md) for attribution and accounting APIs.

## Local service

After installing the service wheel and its pinned dependencies, the external
accounting service can run on loopback with a new private state directory:

```sh
mkdir -m 700 ./local-instance
ezllmrouter \
  --db "$PWD/local-instance/service.sqlite" \
  --secrets-dir "$PWD/local-instance/secrets" \
  --web-root "$PWD/web"
```

The defaults are API port `48760` and operator console port `48761`. The launcher
prints the path to the generated operator credential. Keep that file and the
state directory private. The optional `--demo-scope` flag reads a separately
prepared immutable synthetic demo; opening a console page does not run a model.

The older offline Docker profile is described in
[deploy/local/README.md](deploy/local/README.md). It requires frozen, verified
artifacts in addition to this source checkout. Its existing environment
variables, artifact names, and stored identities remain compatible.

## Language choice

The service remains in Python, with JavaScript for the client and console.
Most work here involves network requests, authorization, database access, and
accounting. There is no measured performance problem that justifies replacing
the implementation. Keeping Python preserves the existing validation and
provider integration work.

Go would be a reasonable candidate for a future standalone proxy if deployment
size or measured concurrent throughput becomes a constraint. TypeScript could
reduce the number of languages for a JavaScript-focused team, but would not by
itself improve this service's correctness or speed. Measure a specific problem
before choosing a rewrite.

## Repository map

| Path | Contents |
| --- | --- |
| `server/` | Coordinator, registry, persistence, operator API, and trusted service. |
| `clients/python/`, `clients/js/` | Installable network clients. |
| `web/` | Operator console HTML, CSS, and JavaScript. |
| `deploy/local/` | Frozen-input Docker profile and lifecycle tools. |
| `tests/` | Contracts, clients, accounting, gateway, sender, and console checks. |
| `docs/` | Current architecture, contracts, plans, and historical evidence. |

## Compatibility and development status

The new names change package and product branding. Existing protocol versions,
wire headers, schema IDs, database records, frozen artifacts, and legacy Python
imports are retained so the rename does not invalidate stored work or installed
integrations. Earlier names in dated contracts and evidence identify those
historical versions. Current component names are the functional names above.

This source contains controlled synthetic checks and later provider/accounting
development. A package build does not establish production readiness or upgrade
an existing running profile. Live provider execution, deployment acceptance, and
learned routing require their own evidence. See the
[rebranding record](docs/development/EZLLMROUTER-REBRANDING.md) for the scope and
validation of this change.
