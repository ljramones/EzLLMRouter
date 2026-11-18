# EzLLMRouter rebranding — 2026-11-18

## Scope

Product: **EzLLMRouter**. Package organization: **CognitiveDynamics**.
The source directory is now `EzLLMRouter/`. The existing Git history and
pre-existing uncommitted work were preserved. No remote was changed or pushed.

Version **0.3.0** introduces:

- `cognitivedynamics-ezllmrouter-server`, with an `ezllmrouter` command and
  `python -m ezllmrouter_server` entry point.
- `cognitivedynamics-ezllmrouter-client`, imported as `ezllmrouter_client`.
- `@cognitivedynamics/ezllmrouter-client`, with `EzLLMRouterClient` and
  `EzLLMRouterError` exports.
- EzLLMRouter branding in the operator console, visible demo labels, downloads,
  client documentation, and local deployment guide heading.
- A rewritten README and [current architecture overview](../architecture/EZLLMROUTER.md)
  using functional component names: access control, router, usage accounting,
  evaluation, and configuration registry. The current product overview has no
  mythological names or origin story.

The backend remains Python. No performance measurements establish a need for a
language rewrite; retaining the implementation preserves existing validation
and provider integration work. A future language change should address a
measured requirement.

## Compatibility

Legacy implementation namespaces, client class aliases, protocol headers,
schema IDs, stored identities, environment variables, and frozen deployment
artifacts retain their identifiers. The Python wheels include both public and
legacy namespaces. Both class names reference the same implementation and error
type. The CLI documents `--demo-scope` and accepts the older option as a hidden
compatibility alias.

Dated contracts, plans, evidence, artifact hashes, and historical release
scripts remain historical records. They were not relabelled as a newly qualified
release. The new packages do not migrate an existing database or restart a
running profile.

## Validation

Source base: `b84c5b1037b2fdc02a8547c73af499e4a63ea53e`, with pre-existing
uncommitted changes plus this rebranding. The source was not committed.

- Built both Python wheels offline using the cached pinned `uv_build==0.13.1`
  backend. Built the npm tarball offline with lifecycle scripts disabled.
- Installed all three archives into separate temporary Python and Node
  consumers. Verified the new distribution names, version `0.3.0`, public
  imports/exports, and legacy class identity. Python client calls and errors
  were exercised through the new namespace using an isolated transport.
- **22 Python tests passed**: existing client response/transport validation,
  SQLite operator projections, and the credential tests that do not bind
  sockets. These used installed package code. HTTPX dependencies came from
  existing local frozen wheels; the existing server environment supplied
  cryptography dependencies without processing its editable startup file.
- The existing JavaScript client validation passed against the installed npm
  package: 4 positive responses, 19 malformed response cases, 2 invalid selector
  cases, 4 selector mutation controls, and 3 option/unknown outcome cases.
- The installed service entry point passed version, help, new demo flag, and
  legacy demo flag checks without starting the service.
- Existing CRUD, activity/usage, and catalogue view checks passed. The CRUD
  test's expected product label was updated with the console label.
- JavaScript syntax, Python syntax, package metadata, current documentation
  links, and `git diff --check` were checked.

HTTP and browser execution remain unverified here: this executor rejects local
socket binding with `PermissionError: Operation not permitted`. An initial HTTP
test run hit that restriction; it is not recorded as a passing HTTP run. No
provider request, model generation, Docker restart, registry publication, or
deployment occurred. The service's dependency installation and production
readiness were not requalified by these branding checks.

Archive sizes, SHA-256 hashes, runtime versions, and check outcomes are recorded
in [EZLLMROUTER-REBRANDING.json](EZLLMROUTER-REBRANDING.json). Local archives and
their checksum manifest are in the ignored `dist/` directory.
