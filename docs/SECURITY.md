# Security and runtime inputs

## Credentials and accounts

The initial administrator receives a randomly generated temporary password in
an owner-only file and must change it before using the console. Passwords use
salted scrypt verifiers. Sessions are time limited and recheck account state;
mutations validate Origin and CSRF before reading request bodies.

Credential stores use independent encryption keyrings. Secret resolution is
permission checked and audited without logging plaintext credentials. See
[encryption and rotation](ENCRYPTION.md) and [users and permissions](USER-MANAGEMENT.md).

HTTP, Unix IPC and console ingress listeners bound concurrent connections and
socket waits. HTTP input uses an absolute deadline without per-request timer
threads. Execution queues and ephemeral operator credentials are also bounded;
see [runtime resource ownership](RESOURCES.md). Logs use
structured metadata and exclude credentials, prompts and response bodies.
Treat model-server origins and service credentials as trusted configuration.
Expected client API rejections log an INFO event with the public code and status;
unexpected failures retain sanitized stack locations. Empty connections and idle
keep-alive expiry emit no request/failure event. Partial request timeouts remain
visible. Operator access labels use the matched route and literal action positions;
queries, credentials and dynamic IDs remain excluded, including IDs that happen
to equal route words such as `models` or `password`. The logging contract tests
check the exact field schema and level across all current route bindings.

Trusted provider replies have independent 65,536-byte encoded and decoded caps.
Compressed streams must reach their end marker with no trailing member or data;
gzip and wrapped/raw deflate are decoded with a bounded output allocation.
Truncated or oversized replies remain uncertain outcomes and cannot trigger an
automatic provider replay. Client-facing SDK transports require identity encoding.

Provider metadata probes validate all resolved addresses before connecting to
one approved IPv4 or IPv6 sockaddr. TLS still verifies the configured hostname.
Invalid trust material is rejected before opening a socket; response, TLS and
socket cleanup also runs after transport or response-size failures. These
fixed GET probes do not generate model work.

## Operator login and browser transport

Named login throttling follows the backend peer and canonical username together.
Each pair allows at most 20 failed or pending attempts in a rolling minute,
two concurrent verifications, and eight concurrent logins across the application.
After five failures, a retry must wait 50 ms, doubling after each subsequent
failure up to two seconds. Requests arriving too soon are rejected without
sleeping or checking a password. Unknown usernames share a peer bucket (ten per
minute, 64 peer buckets and one concurrent unknown-user check globally), reserving
verification capacity for known accounts. Password changes use a separate throttle.
Successful authentication clears that identity's failures. Credential-only login
uses the client address instead. The throttle retains at most 512 identities as
keyed hashes, without usernames or passwords, evicting the oldest inactive entry
when full. A failed login cannot block the same account from another peer.
Reverse proxies must apply client-level throttling before shared backend
connections; forwarded headers do not change the backend peer identity.
Password hashing has its own two-operation concurrency limit. Expected operator
login failures return safe errors without error-level stack traces. Unexpected
failures return 503 and log only sanitized diagnostic metadata.

Sessions are capped at four per principal and 64 per application. A new login
replaces that principal's oldest session, revoking its attached wire credential.
Non-administrator sessions occupy at most 56 slots; administrators can displace
an ordinary session when the global table is full.

The TCP console binds only to `127.0.0.1` and accepts loopback Host authorities.
An embedding application can instead use `operator_web.serve` with a Unix socket
and an explicit canonical HTTPS `public_origin` behind a trusted reverse proxy.
That mode requires matching Host and Origin values and sets Secure on both
session creation and clearing cookies. Forwarded headers do not enable HTTPS
mode. The stock launchers remain local-only; they do not expose a remote-hosting
switch. Keep the proxy's backend socket private and restrict access at the proxy.

Both HTTP servers close a connection before replying when a declared request
body remains unread or its framing is ambiguous. Rejected body bytes cannot be
interpreted as another request on a reused backend connection.

The Unix socket directory must belong to the service user and must not be
group- or other-writable. Socket permissions are set to `0600` after binding and
before listening; a permission failure prevents the listener from starting.
The local profile gives the service ownership of `/link/sender` and the isolated
worker ownership of `/link/worker` using separate volumes. Each peer sees the
other's socket volume read-only. The worker can connect to the sender but cannot
replace or remove its socket. `local_profile.py` includes an explicit ownership
probe; this topology still needs validation on the target Docker runtime.

Responses constrain form submission to the same origin. The explicit HTTPS proxy
mode also emits HSTS with a one-year maximum age. CSRF comparisons handle arbitrary
header bytes as a rejection. CSV exports prefix spreadsheet formula strings with
an apostrophe, while preserving numeric negative decimal amounts.

## Secret inputs

Production launchers read mounted private credential files and pass provider
keys explicitly to trusted adapters. Guarded sends use the invocation's bound
key; they do not fall back to a process environment variable. Synthetic test
harness inputs and the isolated worker's public placeholder key are separate
from production credentials.

Bootstrap passwords come from the owner-only password file or an explicit
`UserManager` constructor argument. `EZLLMROUTER_ADMIN_PASSWORD` is ignored;
`EZLLMROUTER_ADMIN_USERNAME` remains a non-secret initial username setting.
See [first sign-in](USER-MANAGEMENT.md#first-sign-in) for password file semantics.

## Execution isolation

The request-preparation worker has no provider credentials or network interface.
The trusted sender validates current authority at transmission, records intent,
and retains uncertain outcomes for recovery. A successful admission is not
permanent authority to send. External accounting never dispatches a model call.

## Instance identity and optional display lookup

`Registry(identity=InstanceIdentity(...))` configures the owner ID, default task
class, credential consumer principal and release purpose. The accounting CLI
exposes `--owner-id`, `--task-class`, `--credential-consumer-id` and
`--credential-release-purpose`. Defaults preserve the existing local identities;
they are not hard-coded authorization checks. `--platform-id` selects the platform
for a newly created default dataset. Existing dataset identities are preserved.

Changing owner settings does not rename or migrate persisted principals: opening
a registry with an unknown configured owner fails. Changing the credential
consumer requires provisioning that explicit service principal and preserving
its private bootstrap token. Existing grants, revisions and audit history remain
authoritative; changing the default task class does not grant its use.

The operator makes no external display-user request unless both
`--identity-origin` and one or more `--identity-cookie` values are set. Origins
must use HTTPS or loopback HTTP; each cookie name matches exactly. Only those
cookies go to the configured `/api/me`, with a two-second socket timeout and a
4 KiB body bound. Redirects are not followed, and only string `id` and `name`
fields return to the console. This optional display lookup grants no router
permissions. The operator session cookie is not implicitly forwarded.

## Dependency and artifact policy

The development environment is pinned by the root `uv.lock`. The isolated gateway
uses a separately reviewed, hash-checked set of 117 wheels and pinned base images.
Its lock and inventory are in [the gateway input directory](../deploy/local/inputs/gateway/).
Changing documentation or a file location does not approve replacement inputs.

Do not install or run `litellm==1.107.0` or its corresponding image. The
[publisher's incident report](https://docs.litellm.ai/blog/security-incident-oct-21-2026)
identifies that release as compromised. The reviewed worker is pinned to the
maintained `litellm==1.106.12` backport and its exact published ARM64 wheel hash.
The [current validation record](TESTING-ROADMAP.md#release-input-remediation-2026-11-22)
records incident/advisory review, publisher evidence, dependency compatibility,
actual offline builds and remaining provenance limits. This selection does not
approve other releases, other environments or production acceptance.

Use explicit reviewed wheel hashes and image digests. Before proposing updates,
review current advisories, published artifact provenance, affected interfaces
and startup hooks, then repeat the relevant isolation and installed-package
checks. Never substitute a mutable image tag or reacquire frozen inputs silently.

Custody verification checks the complete wheel dependency closure, target Python
constraints and selected extras before building. Runtime Python images omit
pip/ensurepip; the JavaScript consumer omits global npm/corepack/yarn. These are
checked in the actual images, including the derived Python image used by ingress
and namespace helpers. Upstream build images retain their own tooling and remain
separately inventoried. Removing installers does not clear OS advisories.

The [Debian OS lock](../deploy/local/inputs/os/README.md) adds a separately
reviewed set of signed-index/hash-checked archives. Its role closures and installer
identity enter source staging and dependency inventories. Actual image checks
verify installed versions and removal of APT tooling. The 117 frozen wheels are
unchanged by this OS transition. Release acceptance still requires review of all
remaining advisory findings and the qualified target's evidence.

The runtime OS policy removes 19 additional unused login, PAM, mount/namespace and
terminal packages with an exact sealed removal list. libc, GCC runtime libraries,
certificates, dpkg/tar and timezone support remain. Qualification rejects removed
tools, setuid/setgid files or locale overrides: images and live profile processes
use `LANG=LC_ALL=C.UTF-8` and `LANGUAGE=C`. Package findings for retained libraries
remain visible; removing compiler or command-line components does not qualify
their native callers.

Qualification inventories regular files and symbolic links across the image
filesystem, including unmanaged copies outside standard executable directories.
It rejects the removed executable names, ACL/attribute command-line utilities,
infocmp, and unpacked Pod::Text/Archive::Tar modules. File type, mode and Perl
module paths distinguish executable tools from account data and unrelated
Debconf modules. Incomplete, duplicate or malformed inventories fail. The result
records a canonical metadata hash; it does not prove absence of renamed, archived
or statically embedded code, or waive source-package advisories for retained
libraries.

An explicit component review can resolve a source-package match for a binary
package that does not contain the affected component. The
[review catalog](../tools/security_component_reviews.json) binds each case to
the complete advisory hash, exact binary/source versions, signed-index archive
hash and reviewed library/module code hashes, including executable aliases.
`tools.release_inventory --query --component-reviews PATH` checks those bytes
and the complete file census again in each immutable image. All attributed
sources must pass; an added binary, changed code/advisory, missing component
check or expired review leaves the match blocked. Reviews last at most seven
days. Raw findings and severity remain unchanged in `findings.json`; the
separate `dispositions.json` records the effective gate and per-image reasons.
This review covers the matched Debian artifacts only and grants no exemption
to other bundled copies or unreviewed native interfaces.

Use the Node version pinned in `.nvmrc`. Keep dependencies, package and image
identities separate from runtime acceptance claims. Store private recovery
material outside documentation and evidence exports.

## Source security gates

The offline gate scans reachable Git history and current source for credential
patterns and high-entropy tokens without printing matching values. Full-history
CI runs before installing project dependencies. Synthetic/public findings need
exceptions bound to exact blob hashes and finding identities; an exception does
not approve modified contents. This does not inspect ignored private runtime
files or establish that a heuristic scanner detects every possible secret.

Ruff security rules cover worker, deployment and tools code as well as server
and Python-client sources. Reviewed findings retain exact statement/location
identities, enclosing-code hashes and source hashes, so equal-count replacements
or disabled guards cannot inherit an exception. Dependency checks retain declared artifact digests, local-source
identities and native manifest scope; absent native transitive locks and
unavailable archive bytes remain explicit limits. See the
[development guide](DEVELOPMENT.md) for commands, bootstrap provenance and scope.
