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
See the [architecture](docs/ARCHITECTURE.md) and [documentation index](docs/README.md)
for the current design and operating guides.

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

From the project folder, start the console with:

```sh
./start.sh
```

Open **http://127.0.0.1:48761/integration**. On first sign-in use **`admin`** and
the random temporary password in `local-instance/secrets/admin.password`, then
change the password. Startup prints the private file's path. Stop with **Ctrl+C**.
The launcher uses Python 3.12 through `uv`, keeps data in the ignored
`local-instance/` directory, and installs the exact dependencies in
`server/uv.lock`, downloading any that are missing. Install `uv` and Python 3.12
before starting; initial dependency setup needs internet access. Once the
dependencies are cached, use `UV_OFFLINE=1 ./start.sh` to require offline startup.
Run `./start.sh --help` for options, or choose another console port with
`./start.sh --operator-port 8780`.

After installing the service wheel and its pinned dependencies, the external
accounting service can run on loopback with a new private state directory:

```sh
mkdir -m 700 ./local-instance
ezllmrouter \
  --db "$PWD/local-instance/service.sqlite" \
  --secrets-dir "$PWD/local-instance/secrets" \
  --web-root "$PWD/web"
```

The defaults are API port `48760` and operator console port `48761`. In a fresh
installation, sign in as **`admin`** using the generated `admin.password` file in
your secrets directory and choose a new password before continuing.
Server version **0.3.1** adds **Users & Permissions** for
account CRUD, role assignment, password resets, and model grants. See the
[user management guide](docs/USER-MANAGEMENT.md) for roles, setup overrides,
and compatibility with existing operator tooling. Keep the state and generated
credential files private. The optional `--demo-scope` flag reads a separately
prepared immutable synthetic demo; opening a console page does not run a model.

Startup resumes interrupted creation of the integration sender and credential
consumer using their saved private token files. A normal restart preserves their
tokens and account states, including suspension and revocation. If a registered
account's `ingest.token` or `consumer.token` is missing or does not match the
database, restore its original private file from the same instance. Startup
reports the affected filename and leaves the registered credential unchanged.
Keep the database, its adjacent `service.sqlite.secrets` directory and the
configured secrets directory together when backing up or restoring an instance.
New private token files are saved before their database binding. Integration
credentials, local connectors and the execution vault have independent keyrings;
see [encryption and rotation](docs/ENCRYPTION.md) for the initial storage format,
offline maintenance commands and backup requirements.

Accounting and snapshot reads enforce retention deadlines without deleting data
during the request. The operator service runs physical cleanup once a minute.
Missing or inconsistent retention metadata withholds the affected real dataset
and leaves it for repair; unrelated datasets remain available. Recovery preserves
possible-send exposure, never replays an interrupted request, and keeps historical
charges attached to their original campaign.

Server **0.3.3** separates **External Providers** from **Local Connectors**.
Use Local Connectors for Ollama, LM Studio, vLLM, llama.cpp, LocalAI, or another
OpenAI-compatible server. Availability indicators refresh every 15 seconds while
the page is visible. Choose **Find local servers** to check common localhost
ports, including LocalAI on `8081`, or add a published URL directly. Choose
**Models** to refresh a server's inventory, then select which models to enable.
See the [local connector guide](docs/LOCAL-CONNECTORS.md)
for container addresses, inventory details, and execution boundaries.

The optional isolated Docker execution profile is described in
[deploy/local/README.md](deploy/local/README.md). It requires frozen, verified
artifacts in addition to this source checkout and initializes a fresh database.

## Development checks

Use Python 3.12.15 and the Node version in `.nvmrc`. From the repository root:

```sh
uv sync --locked --all-groups --python 3.12.15
uv run --locked python -m tools.check
```

The root `uv.lock` pins the development environment, including Ruff and mypy.
The application lockfiles and frozen gateway inputs are separate. Change the
development lockfile deliberately with `uv lock` when updating dependencies.

The command runs the maintained offline Python regression modules,
JavaScript syntax and console tests, Ruff correctness checks, and strict mypy
for the initial typed modules. Each Python test module runs in its own process;
network connections and listener binds fail in this suite; local IPC pairs are
used for framing checks. The initial lint rules catch fatal syntax
and undefined-name errors across server, client and deployment source. Formatting
and strict typing cover the file and logging utilities, database boundary,
schema owner, client transport helpers and runner; the remaining modules still
need gradual adoption.

Local HTTP fixtures are a separate explicit check:

```sh
uv run --locked python -m tools.check --http-only
```

CI runs both commands. Docker, provider execution and historical evidence
scripts remain separate owner-operated workflows with their documented frozen
inputs. These checks do not establish deployment or production acceptance.
`--tests-only` omits lint and type checks when diagnosing test failures.

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
| `server/src/duranki_server/gateway/` | Guard, owned sender transports, adapter, IPC framing and gateway recipes. |
| `server/src/duranki_server/repositories/` | Domain-owned, named SQL queries. |
| `server/src/duranki_server/schema/` | Versioned initial database schema. |
| `server/src/duranki_server/operator_http/` | Operator transport, authentication, routes and application state. |
| `worker/` | Isolated worker source, staged separately from the trusted service package. |
| `clients/python/`, `clients/js/` | Installable network clients. |
| `web/` | Operator console HTML, CSS, and JavaScript. |
| `deploy/local/` | Frozen-input Docker profile and lifecycle tools. |
| `tests/` | Contract fixtures, clients, accounting, gateway, sender, and console checks. |
| `tools/gateway/` | Local synthetic launchers, source staging and evidence export/verification tools. |
| `docs/` | Current architecture, API, operating and development guides. |

Gateway runtime imports use `duranki_server.gateway`. The older flat imports and
script paths remain compatibility shims, sharing the same guard context and
exception classes. Local profile staging takes implementations from the runtime
package and worker source, and takes launch/export tools from `tools/gateway`.
The service package does not include the isolated worker, local launchers or
evidence exporters. Its gateway modules use the local profile's reviewed HTTPX
and HTTPcore closure; importing the base service or gateway package does not load
LiteLLM. Frozen dependencies, image digests and retained evidence are unchanged.
Older qualification runners remain under `tests/gateway_integration`; this move
covers the runtime implementation and active staging, launch and export tools.

See [database and operator server structure](docs/DATABASE.md) for schema
ownership, shared transactions, dispatch boundaries and verification.

## Development status

The current database starts from one fresh initial schema. The local test suite
covers accounting, credential recovery, authorization and operator workflows.
Docker deployment, live-provider execution and production qualification require
their own validation. Learned routing remains future work.

Current guidance is in the [documentation index](docs/README.md).
