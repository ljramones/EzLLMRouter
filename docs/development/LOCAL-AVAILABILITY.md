# Local connector availability result — 2026-11-18

Source base: `008cd004083da8367b0c45076ee418009beaaec2` on `main`, with the
existing uncommitted account, launcher, and connector work. Server version:
**0.3.3**. This extends the [0.3.2 connector result](LOCAL-CONNECTORS.md);
historical results and frozen deployment inputs remain intact.

## Delivered

Local Connectors shows API availability separately from saved configuration:
Online, Offline, Checking, Needs attention, Check blocked, Not checked, and
Check outdated. The indicators include last-check time and elapsed milliseconds.
An empty compatible model catalogue still counts as Online. Authentication,
TLS, invalid responses, and denied service-environment connections have distinct
safe reasons rather than all being reported as an offline server.

Saved endpoints are checked when the page opens and every 15 seconds while
visible and automatic checking is enabled. Check now requests a manual refresh.
Queued observations are read again after two seconds. Page navigation, sign-out,
password change, and connector forms stop the page's polling. Status updates do
not reconstruct model controls or discard search text and unsaved selections.
Old observations cease displaying Online as current after 45 seconds.

Administrators can explicitly Find local servers on fixed localhost ports
11434, 1234, 8080, 8081, 8000, 9997, and 30000. This includes the owner's LocalAI
test address on 8081. Compatible API labels and port hints do not assert a
runtime identity. Found addresses refresh while that list remains open with
automatic checking enabled. Finding addresses does not save connectors;
Add connector opens a prefilled form for review. Saved localhost endpoints,
including equivalent loopback addresses and /v1 bases, link to their existing
connector. Custom ports, LAN servers, and Docker service names use manual setup.

The Models action refreshes the selected server's inventory for administrators
and opens its details. Read-only operators inspect saved inventories. Both
roles can request availability of saved endpoints; unsaved localhost finding
requires an administrator. Ordinary users and accounts awaiting their first
password change cannot inspect or probe these endpoints.

Availability is an in-memory observation, with no SQLite record, selection,
authority epoch, or audit mutation. A four-worker pool allows at most 64 pending
checks and coalesces concurrent checks. Results have a 10-second normal cooldown
and a minimum 2-second manual cooldown. The cache holds at most 512 identities.
Settings changes invalidate observations, and late results cannot overwrite a
different configuration. Shutdown closes the monitor with the operator server.

Probes use existing fixed GET metadata paths, local-address validation, DNS
pinning, HTTPS verification, redirect refusal, and response limits. Their
transport budget is 1.5 seconds per endpoint; DNS uses the system resolver.
They do not query Docker, run inference, load models, or download models. A
working metadata API is not qualification of model execution or routing.

The [operator guide](../LOCAL-CONNECTORS.md) describes controls, API routes,
permissions, localhost scope, and the distinction between availability,
inventory, and enablement.

## Observed validation

- **87 Python tests passed** on Python **3.12.15** across availability,
  connector storage/discovery/transport/handlers, accounts, registry, and
  projection. New cases verify coalescing, bounded queues, stale/configuration
  invalidation, late-result rejection, secret/error redaction, permission denial,
  Origin/CSRF checks, fixed metadata paths, older Ollama fallback, empty-list
  availability, localhost scan scope, existing-endpoint matching, and unchanged
  persistent records/audit/authority after probes.
- **Five JavaScript interaction suites passed** on Node **24.22.1**: connector
  pages, users, CRUD, catalogue, and activity/usage. The connector suite uses
  controlled responses and timers to verify Online/Offline changes, stale
  indicators, preserved model choices/search, pause/hidden/navigation/form
  lifecycle, finding and prefilling LocalAI on 8081, no automatic persistence,
  Models refresh, permissions, and existing connector lifecycle. All **15**
  console JavaScript files passed syntax checks.
- Built the **0.3.3** wheel offline with pinned **uv_build 0.13.1**. Its Python
  files matched source exactly. A temporary installed consumer passed **6**
  handler cases covering availability, localhost finding and read-only denial,
  the connector lifecycle, discovery authorization, static assets, and mandatory
  first-use password change. Server modules were verified to load from that
  installed wheel. Existing native cryptography dependencies came from the
  checked local environment without processing editable startup files.
- `./start.sh --version` reports **0.3.3** after an offline editable-package
  update. Only version startup ran; it did not create or restart a live service.
- Python syntax, package-version consistency, current documentation links,
  artifact/source matching, and `git diff --check` passed.

Artifact: `dist/cognitivedynamics_ezllmrouter_server-0.3.3-py3-none-any.whl`.
Size: **179662 bytes**. SHA-256:
`934cea28742d7b6ea15c0d42706972dd4c2e211fa05d280024beafa6f5ad70f2`.
The local `dist/MANIFEST.sha256` records the archive.

## Live limits

The owner reports Ollama and LocalAI running. This executor previously received
permission-denied errors when attempting host loopback connections; those are
not evidence that the owner's servers are offline. No new live model-server
request, Docker operation, real-browser observation, profile restart, or model
execution was performed for this change. The controlled tests above establish
source and installed-package behavior, not live-runtime acceptance.
