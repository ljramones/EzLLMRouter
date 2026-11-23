# Reviewed native OpenSSL backports

The v4 [OS lock](../os/debian13-arm64.lock.json) selects a local OpenSSL
3.5.9 backport, Node 24.22.3 linked to that shared library, and cryptography
50.0.2+ezllmrouter1 linked to the same library. These are reviewed local outputs,
with `urn:ezllmrouter:native-build` origins; they are not publisher artifacts.
The base image digests, Python and Node versions remain pinned. Of the 117 frozen
wheels, 116 retain their exact bytes, including LiteLLM 1.106.12.

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
