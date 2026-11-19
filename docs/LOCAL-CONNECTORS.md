# External providers and local connectors

Server **0.3.3** separates the console's connection setup into two pages:

- **External Providers** manages third-party cloud API connections.
- **Local Connectors** manages model servers on this machine, a private LAN, or
  a shared Docker network.

Stop an older instance with **Ctrl+C**, run **`./start.sh`**, then open
**http://127.0.0.1:48761/integration**. Sign in as an administrator and choose
**Local Connectors → Add local connector**.

## Availability and finding servers

Each saved connector has an **Availability** indicator and a last-check time:

| Indicator | Meaning |
| --- | --- |
| Online · green | The selected HTTP API returned a valid response. An empty model list still counts as Online. |
| Offline · red | The server could not be reached, its name could not be resolved, or the request timed out. |
| Checking · blue | A check is queued or in progress. |
| Needs attention · amber | The server requires authentication, has a TLS problem, or returned an unexpected API response. Hover for the reason. |
| Check blocked · amber | The service environment denied the connection; availability is unknown. |
| Not checked / Check outdated | No observation is available, or the last observation is over 45 seconds old. |

Saved connectors are checked when the page opens and every **15 seconds** while
it is visible. Choose **Check now** for a manual refresh, or uncheck
**Auto-check every 15 seconds** to pause automatic checks. Checks stop when you
leave the page, sign out, or open a connector form. They update status without
discarding search text or unsaved model choices.

Administrators can choose **Find local servers** to check common localhost
ports: `11434`, `1234`, `8080`, **`8081`**, `8000`, `9997`, and `30000`.
This includes Ollama's native API and common OpenAI-compatible APIs. The result
shows each address and availability. Choose **Add connector**, confirm the
server type and optional API key, then **Connect and discover models**. Existing
saved endpoints offer **Models** instead. Found addresses continue refreshing
while this page is open and auto-check is enabled.

The port hints do not identify the runtime with certainty: LocalAI, llama.cpp,
and other servers can expose the same compatible API. The scan does not save
connectors automatically. Use **Add local connector** for custom ports, LAN
addresses, or Docker service names. `localhost` is relative to EzLLMRouter's
process; it cannot scan another container's unexposed ports.

Availability uses HTTP GET metadata requests, similar to a health check. It
does not use ICMP, load a model, or verify that generation will succeed. Ollama
uses `/api/version` with `/api/tags` fallback for older servers; compatible
servers use `/v1/models`. Authentication uses each saved connector's optional
key. Unsaved localhost checks have no API key and may show Needs attention.
Availability and configuration are separate: Online does not enable a
connector or select models.

## Supported server profiles

| Server | Default URL | Discovery API |
| --- | --- | --- |
| Ollama | `http://localhost:11434` | `/api/tags`, with optional `/api/ps` and `/api/version` metadata |
| LM Studio | `http://localhost:1234` | `/v1/models` |
| vLLM | `http://localhost:8000` | `/v1/models` |
| llama.cpp | `http://localhost:8080` | `/v1/models` |
| LocalAI | `http://localhost:8080` | `/v1/models` |
| Other OpenAI-compatible server | `http://localhost:8000` | `/v1/models` |

The server must expose the listed HTTP API. Selecting a profile is not proof
that every version of that runtime implements it. Additional compatible servers
can use the generic profile. An OpenAI-compatible base URL may include `/v1`;
the discovery request still uses `/v1/models` once.

## Connecting to a container

Enter a connection name, server type, and server URL. API keys are optional for
servers that allow unauthenticated local access. Choose **Connect and discover
models** to save the connector and read its inventory.

The URL is resolved from the machine or container running EzLLMRouter:

| Where EzLLMRouter runs | Model server address |
| --- | --- |
| On the host, with Ollama's port published as `11434:11434` | `http://localhost:11434` |
| In a container sharing Ollama's Docker network | `http://ollama:11434`, using the actual service name |
| In Docker Desktop, reaching a model server on the host | `http://host.docker.internal:11434` |
| On another machine on your LAN | The server's private address and published port, such as `http://192.168.1.20:11434` |

Inside an EzLLMRouter container, `localhost` refers to that container. Docker
service-name discovery requires a shared network. Publish the model server's
port when connecting from the host; changing a URL does not publish it.

The connector reads the server's API rather than the Docker daemon. It does not
enumerate all host containers, require a Docker socket mount, start containers,
pull models, unload models, or remove files from a model server.

## Inventory and selection

Ollama discovery lists installed model IDs and any reported model size, family,
format, parameter count, and quantization. When its running-model API is
available, the console also shows loaded status and reported VRAM bytes.
Optional version or running-model failures leave installed inventory available
and mark the missing metadata as unknown.

OpenAI-compatible discovery lists the exact model IDs exposed by that server,
with context-window metadata when reported. This may represent loaded models
or the server's wider available catalogue; missing load state, size, or
quantization is shown as unknown.

Select models and choose **Enable selected models**. Discovery alone does not
enable a connector or select every model. Enablement requires a complete,
current inventory and exact discovered IDs. Changed settings invalidate old
discovery and selections. A model removed from the server makes a retained
selection need attention until corrected. Browsing or refreshing a console page
checks availability. For administrators, **Models** refreshes the selected
server's inventory and opens its details; **Discover models** refreshes it again
from that detail page. Opening a saved detail URL shows the saved inventory
alongside a fresh availability check. Read-only operators inspect saved
inventories and cannot run full discovery.

These are connector-level model choices. They do not create user grants,
approved execution configurations, prices, or inference attempts. This change
adds connection inventory and selection; the accounting-only launcher continues
to leave model execution disabled. Actual model dispatch through these adapters
requires its own implementation and qualification.

## Credentials, permissions, and errors

Administrators can create, edit, discover, enable, disable, and delete local
connectors. Read-only operators can inspect saved inventories and selections.
Both roles can check saved connectors' availability. Finding unsaved localhost
servers requires an administrator. Ordinary users cannot administer or inspect
the local connector catalogue. Mutations and queued checks require the current
session, allowed Origin, and CSRF token. Record changes and full discovery also
require the expected revision and are audited. Availability is cached in memory;
checks do not change record revisions, selections, audit history, or permissions.

Optional API keys use authenticated encryption with a dedicated connector
keyring. They are not returned by the API or included in model metadata. Retain
the database and its keyrings together for recovery; see [encryption and rotation](ENCRYPTION.md).
Missing keys fail closed. Replacing an endpoint or server type clears
its previous key unless a key for the new endpoint is explicitly supplied.
Deleting a connector clears its key while retaining its audit identity.

HTTP connections are limited to loopback, RFC 1918 private IPv4, and private
IPv6 addresses. Hostnames are resolved and checked before each request, and the
connection uses the checked address. Public, link-local, metadata-service, and
unspecified addresses are refused. Redirects and proxy inheritance are not used.
HTTPS retains normal certificate and hostname verification; self-signed servers
need a certificate trusted by the service environment.

Discovery uses only fixed GET inventory endpoints, request timeouts, a 1 MiB
response limit, and a 1,000-model inventory limit. An incomplete inventory cannot
be enabled. Errors explain unreachable ports, unresolved names, authentication,
unsupported endpoints, and TLS failures without returning server error bodies.
Availability checks use a 1.5-second transport budget per endpoint, reuse the
same address and response protections, and run through a four-worker pool with
at most 64 pending checks. DNS resolution uses the system resolver. Concurrent
checks are coalesced; repeat requests reuse observations for 10 seconds, or at
least 2 seconds for manual refresh. Settings changes invalidate old status, and
late results for a previous configuration cannot become its current status.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET / POST | `/operator/v1/local-connectors` | List profiles and connectors / create a connector. |
| GET | `/operator/v1/local-connectors/availability` | Read cached saved-connector availability. |
| POST | `/operator/v1/local-connectors/check` | Queue saved-connector checks and return current observations. |
| GET | `/operator/v1/local-connectors/nearby` | Read cached common-localhost results; administrator only. |
| POST | `/operator/v1/local-connectors/find` | Queue fixed localhost checks; administrator only. |
| GET / POST / DELETE | `/operator/v1/local-connectors/{id}` | Inspect / edit / delete. |
| POST | `/operator/v1/local-connectors/{id}/discover` | Read model-server inventory explicitly. |
| POST | `/operator/v1/local-connectors/{id}/models` | Save selected models and enabled state. |

Create accepts `display_name`, `kind`, `base_url`, and optional `api_key`.
Edit uses those profile fields plus `expected_revision`; omit `api_key` to keep
it when the endpoint is unchanged, or send an empty string to remove it.
Discovery and deletion accept `expected_revision`. Model selection accepts
`expected_revision`, `selected_models`, and `enabled`.

`check` accepts optional `connector_ids` (up to 64 distinct saved IDs; omit for
all) and boolean `force`. `find` accepts optional boolean `force`. Neither
accepts arbitrary addresses or paths. Queue responses can contain `checking`;
poll the corresponding cached GET endpoint for completion. Availability fields
include `state`, safe `reason`, `checked_at`, `latency_ms`, `reachable` (possibly
unknown), `stale`, and a configuration digest; compatible inventories may also
report `model_count`. Observations are lost on service restart.

See [development checks](DEVELOPMENT.md) for the maintained test commands.
