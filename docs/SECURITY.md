# Security and runtime inputs

## Credentials and accounts

The initial administrator receives a randomly generated temporary password in
an owner-only file and must change it before using the console. Passwords use
salted scrypt verifiers. Sessions are time limited and recheck account state;
mutations validate Origin and CSRF before reading request bodies.

Credential stores use independent encryption keyrings. Secret resolution is
permission checked and audited without logging plaintext credentials. See
[encryption and rotation](ENCRYPTION.md) and [users and permissions](USER-MANAGEMENT.md).

HTTP servers bound concurrent connections and socket/input timeouts. Logs use
structured metadata and exclude credentials, prompts and response bodies.
Treat model-server origins and service credentials as trusted configuration.

## Execution isolation

The request-preparation worker has no provider credentials or network interface.
The trusted sender validates current authority at transmission, records intent,
and retains uncertain outcomes for recovery. A successful admission is not
permanent authority to send. External accounting never dispatches a model call.

## Dependency and artifact policy

The development environment is pinned by the root `uv.lock`. The isolated gateway
uses a separately reviewed, hash-checked set of 117 wheels and pinned base images.
Its lock and inventory are in [the gateway input directory](../deploy/local/inputs/gateway/).
Changing documentation or a file location does not approve replacement inputs.

Do not install or run `litellm==1.107.0` or its corresponding image. The
[publisher's incident report](https://docs.litellm.ai/blog/security-incident-oct-21-2026)
identifies that release as compromised. The reviewed worker remains pinned to
`litellm==1.105.1`; this is a statement about the selected profile, not an approval
of other releases or environments.

Use explicit reviewed wheel hashes and image digests. Before proposing updates,
review current advisories, published artifact provenance, affected interfaces
and startup hooks, then repeat the relevant isolation and installed-package
checks. Never substitute a mutable image tag or reacquire frozen inputs silently.

Use the Node version pinned in `.nvmrc`. Keep dependencies, package and image
identities separate from runtime acceptance claims. Store private recovery
material outside documentation and evidence exports.
