# Local connectors result — 2026-11-18

Source base: `008cd004083da8367b0c45076ee418009beaaec2` on `main`, with the
existing uncommitted account/launcher work and this connector change. Server
version: **0.3.2**. Python/JavaScript client versions and adopted model API
contracts are unchanged.

## Delivered

External cloud connection setup is labelled **External Providers**. A separate
**Local Connectors** page is available in both native and accounting-only
consoles. Its server profiles cover native Ollama discovery and OpenAI-compatible
inventory for LM Studio, vLLM, llama.cpp, LocalAI, and generic compatible servers.

Administrators can save endpoints, discover installed/available models, select
models, enable/disable a connector, update settings, and delete the connector.
Ollama discovery includes optional running-model and version metadata; other
servers expose the fields available through `/v1/models`. Unknown values remain
unknown. Discovery does not pull or execute models.

Connector records, encrypted optional API keys, inventory snapshots, and exact
model selections persist in SQLite. Writes check current administrator authority
and revisions, hold the existing authority gate for commit, and record an audit
entry. Inventory requests run outside the database/authority lock and cannot
overwrite concurrent settings changes. Changed endpoints do not inherit an old
API key unless the user explicitly supplies a key for the new endpoint.

Reads are limited to fixed GET endpoints on checked local/private addresses.
DNS answers are validated before a pinned connection, HTTPS retains certificate
validation, and redirects/proxy inheritance are not used. Response and inventory
sizes are bounded. Missing encrypted-store keys do not silently generate a
replacement or expose/erase the previous credential.

The [operator guide](../LOCAL-CONNECTORS.md) documents setup, Docker addressing,
the APIs, and the boundary between inventory selection and model execution.

## Observed validation

- **70 Python tests passed** with Python **3.12.15**: new connector discovery,
  storage, transport, and operator handler cases plus existing account,
  registry, and projection checks.
- The cases cover all six server profiles, Ollama installed/loaded metadata,
  optional-endpoint failures, exact model IDs, incomplete inventories, missing
  models, persistence, stale writes, concurrent edits, key encryption/binding,
  missing-key recovery, endpoint/key separation, permission/Origin/CSRF denial,
  DNS and private-address controls, TLS verification, redirects, bounded reads,
  duplicate/invalid metadata, and credential echo redaction.
- Node **24.22.1** passed five interaction/view suites: new connector pages,
  named-user management, existing CRUD, catalogue, and activity/usage. The new
  case exercises external/local separation, server defaults, explicit discovery,
  model selection, read-only controls, secret-field clearing, deletion, and
  both console routes. All **15** console JavaScript files passed syntax checks.
- Built the **0.3.2** service wheel offline with pinned **uv_build 0.13.1**.
  The temporary installed consumer passed CLI/version checks and **4** handler
  cases covering the connector lifecycle, authorization, static asset serving,
  and first-use account password enforcement. Service code came from the
  installed wheel. Existing native cryptography dependencies came from the
  checked local environment without processing its editable startup file.
- `./start.sh --version` reports **0.3.2** after updating the editable source
  package offline. Only help/version startup checks ran; no runtime state or
  live service was created by those checks.
- Python syntax, release metadata, documentation links, exact wheel/source
  matching, and `git diff --check` passed.

Artifact: `dist/cognitivedynamics_ezllmrouter_server-0.3.2-py3-none-any.whl`.
Size: **176591 bytes**. SHA-256:
`163940132ad2a0d57cd0f48c5f39ca66d0b304c0110c2fcd8526fd9623a6e778`.
The local `dist/MANIFEST.sha256` also records this archive.

## Live limits

A read-only native Ollama discovery check at `http://127.0.0.1:11434` returned
`SERVER_UNREACHABLE` from this executor. No live container inventory, Docker
runtime variant, or actual generation was verified. The controlled responses
and in-memory HTTP streams above are not a live-server or browser observation.

The executor restricts socket binding, so the complete socket-backed HTTP and
visual browser walkthrough remain unperformed. No container was started or
modified, no model was downloaded or run, and no provider generation occurred.
No live application profile was restarted, deployed, or pushed. Connector-level
model selections do not grant user authority or add local inference dispatch to
the accounting-only launcher.
