# Reviewed native OpenSSL backports

The v4 [OS lock](../os/debian13-arm64.lock.json) selects a local OpenSSL
3.5.9 backport, Node 24.22.3 linked to that shared library, and cryptography
50.0.2+ezllmrouter1 linked to the same library. These are reviewed local outputs,
with `urn:ezllmrouter:native-build` origins; they are not publisher artifacts.
The base image digests, Python and Node versions remain pinned. The subsequent
PostgreSQL bundle reduction described below retains the 117-wheel count and
the exact LiteLLM 1.106.12 wheel.

Eight fixes come from immutable OpenSSL 3.5 maintenance commits. The ninth,
CVE-2026-84786, uses the complete DANE fix and regression test from upstream
[PR 33634](https://github.com/openssl/openssl/pull/33634), still open at the
November 23 review. Its complete base-to-head diff is pinned separately from the
last fixup commit. This is a locally reviewed backport, not a merged upstream
release. The lock records each patch, advisory identity and source artifact hash.

Builds use the pinned Python ARM64 image with no network, verified Debian build
archives, a fixed source epoch and offline Rust crates. Node source matches its
verified signed release checksum manifest. Cryptography source matches the exact
PyPI source artifact; build wheels and Cargo archives are individually hashed.
The build-only setuptools startup hook was inspected; it is absent from the
runtime bundle. Cryptography uses the honest `linux_aarch64` wheel tag, with no
vendored SSL library. Root development locks remain separate platform inputs.

The shell recipes preserve the actual invocations. `node.sh` configured and began
the build with four jobs; `node-completion.sh` completed its cached objects with
eight jobs. The configured Node CA option is overridden by
`NODE_OPTIONS=--use-bundled-ca` in both Node image recipes to preserve the pinned
runtime's bundled trust defaults. `package.py` preserves each original Debian
package's metadata, configuration and maintainer scripts, replacing only the
reviewed OpenSSL native objects and adding explicit backport attribution. The
formatted tracked recipe reproduced all three selected archive hashes.

Build inputs and outputs stay in the private artifact store. The canonical hash
of `native_build.inputs` identifies the build; `native_build.outputs` pins its
three `.deb` files, Node binary and cryptography wheel. Put the five exact files
in `inputs/native/<build-id>/outputs/` and the selected thirteen archives in
`inputs/os/debian13-arm64/`. Preserve the source caches and build/test logs under
ignored `.artifacts/openssl-remediation/`. Normal preparation verifies custody
and copies already reviewed outputs; it never downloads or compiles dependencies.

Source preflight does not clear advisories. Custom versions query upstream
versions, keeping raw severity and findings. The explicit native review requires
the exact advisory record, all selected archive hashes, all six native code
bindings, actual Python/cryptography OpenSSL versions and Node shared-SSL status
in every inventoried image. Changed copies, incomplete images and unknown source
attribution remain blocking. See the
[validation ledger](../../../../docs/TESTING-ROADMAP.md).

## Minimal PostgreSQL native bundle

The v4 lock's separate `native_driver` record selects
`psycopg-binary==3.3.6+ezllmrouter1`. The published Python extension objects are
relinked to exact-version libpq 18.6 built without GSSAPI or LDAP, against the
already reviewed shared OpenSSL. Both Python extension entry points and all
210 libpq exports remain available. PostgreSQL connectivity is not used by the
qualified SQLite profile; Kerberos/LDAP connectivity is deliberately unavailable
in this native bundle. The worker retains the LiteLLM proxy ASGI interface and
its declared dependency closure.

This replaces one more frozen wheel, leaving 116 identical to the preceding
OpenSSL bundle and 115 identical to the original 117-wheel selection. No new
runtime package version or archive is downloaded during preparation. The local
wheel uses an honest `linux_aarch64` tag and upstream 3.3.6 for advisory queries.
It removes sixteen bundled native libraries, including Kerberos, LDAP and the
additional OpenSSL copies missed by the earlier three-copy review. Native
qualification now requires the exact driver objects and a full dependency
inspection for the scoped profile decisions.

`postgresql.sh`, `driver-relink.sh` and `driver.py` preserve the build and
repackaging steps. The original wheel and PostgreSQL source archive hashes,
publisher checksum, compiler inputs, extra authenticated Debian build tools,
feature choices and output identity are bound by `native_driver.inputs`.
The formatted tracked repackager reproduced the selected wheel hash. Preserve
the source caches and logs under ignored `.artifacts/final-seven/`; place the
selected wheel alone in `inputs/native-driver/<build-id>/`. Normal preparation
verifies this output as well as frozen wheel custody before building images.
