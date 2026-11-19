# User management result — 2026-11-18

Source base: `008cd004083da8367b0c45076ee418009beaaec2` on `main`, with the
uncommitted user-management changes. Server version: **0.3.1**. Client package
versions and model API contracts are unchanged.

## Delivered

Named browser accounts use the existing SQLite principal registry, with a
separate salted scrypt password-verifier table. An empty account table receives
the initial administrator; bootstrap environment overrides apply only once.
Named users must change temporary passwords before accessing other APIs.

Users & Permissions provides account creation, reading, editing, disabling,
deletion, password reset, effective role permissions, and access to the existing
model-grant editor. It is available in the native and accounting-only consoles.
Non-administrators see only their own account on this page. Existing identity
and API-credential tooling remains supported.

Password, username, role, and account-status changes invalidate sessions as
appropriate. Role and status changes through the existing registry API also
invalidate named sessions. The last active administrator with a console login
is protected through both management APIs. Deleted identities retain accounting
and audit attribution while losing password and API-credential access.

The [operator guide](../USER-MANAGEMENT.md) documents credentials, setup,
permissions, lifecycle behavior, and endpoints.

## Observed checks

- **41 Python tests passed** across the new account and handler suites and the
  existing registry and SQLite projection suites, using Python **3.12.15**.
  The checks include first-use password changes, restart persistence, stale
  revisions, duplicate-user rollback, role denial, Origin/CSRF enforcement,
  session revocation, last-administrator protection, explicit model grants,
  login throttling, and full-length Unicode password round trips.
- The operator handler tests exercise the actual handler methods and HTTP
  headers through in-memory streams. They do not bind a socket or run a browser.
- Node **24.22.1** passed the user-console interaction test and existing CRUD,
  activity/usage, and catalogue view checks. The new test covers named sign-in,
  forced password change, account CRUD/reset, role controls, secret-field
  clearing, exact password preservation, and non-administrator account display.
- Console JavaScript syntax, Python syntax, package metadata, documentation
  links, and `git diff --check` passed.
- Built the service wheel offline with the existing pinned **uv_build 0.13.1**
  backend. Installed it into a temporary consumer, verified the installed
  version and CLI, and passed **3 installed-package handler cases** for first
  sign-in, account CRUD, and Unicode passwords. Service modules were loaded
  from the installed wheel. Existing native cryptography dependencies were
  supplied from the checked local environment without processing its editable
  startup file; dependency installation was not separately requalified.

Artifact: `dist/cognitivedynamics_ezllmrouter_server-0.3.1-py3-none-any.whl`.
SHA-256: `12761cae211c24246cc17c100b4c59dbdb0aa2ae52ae412b808d0c2b9f4ce175`.
The local `dist/MANIFEST.sha256` also records the archive hash.

## Limits

No model request, provider call, running-profile restart, live database update,
push, or deployment occurred. Local socket binding is restricted in this
executor, so full socket-backed HTTP and visual browser verification remain
unperformed. These results qualify the local component, handler, and installed
package checks listed above, rather than a deployed browser session.
