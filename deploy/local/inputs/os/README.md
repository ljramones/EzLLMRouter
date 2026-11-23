# Reviewed Debian runtime inputs

`debian13-arm64.lock.json` selects immutable official Python 3.12.16 and Node
24.22.3 ARM64 images based on Debian 13 (Trixie). Seven reviewed Debian archives
update base-files, glibc, OpenSSL and zlib; the Node closure uses six because it
does not install the Python base's OpenSSL command-line package.

The v2 lock records binary/source versions, archive sizes and SHA-256 values,
publisher URLs, role membership, upstream image/config identities and the
build-only installer's hash, plus the exact runtime package-removal closure.
Acquisition used APT's authenticated InRelease and
package-index checks with Debian's archive keyring. The review retains the signed
indexes, keyring identity, exact package metadata and inspected maintainer scripts
under ignored `.artifacts/debian-remediation/`.

Use a fresh artifact store preserving the existing 117-wheel custody manifest.
Place exactly the selected `.deb` archives in
`EZLLMROUTER_ARTIFACT_ROOT/inputs/os/debian13-arm64/`, then verify locally:

```sh
.venv/bin/python -m tools.gateway.os_inputs --store /absolute/path/to/fresh-artifact-store
```

This command checks the complete archive set, bytes, hashes, links and installer
identity without acquiring or executing packages. Preparation copies each role's
selected archives into read-only build mounts and records them in the source
packet. Builders reject modified archives, checksum manifests, installer scripts
and metadata that differs from that packet before building an image.

Preparation seals a canonical `REMOVE-PACKAGES` file alongside the archives and
includes its hash in `SHA256SUMS`. Custody checks reject protected runtime/library
packages, duplicates, unsafe arguments, changed removal lists and altered source
packets before Docker executes. No archive or base-image version changes with
this runtime policy.

`install_os.sh` runs only during an offline Docker build. It checks Debian's
version/architecture, verifies archive/removal hashes, installs the selected local
packages and checks package consistency. The 22-package removal closure includes
the previous APT tools plus 19 unused login/password, PAM, mount/namespace and
terminal packages and their reviewed dependencies. Debian protects some of these
as essential; the image-only override permits exactly the sealed removal set.
Before/after censuses reject missing inputs, extra removals or added packages.
The installer uses the C locale for deterministic checks. Do not run it on a host.
Dpkg and tar remain together; Python libraries, libc/libstdc++, certificates and
timezone data are retained.

Final qualification checks actual installed versions, all 22 package removals,
absence of the removed commands and zero setuid/setgid files. Inspection helpers
run separately with read access to private image directories; application roles
retain their non-root, zero-capability configuration. All image/live-profile
locales must be `LANG=LC_ALL=C.UTF-8` and `LANGUAGE=C`, constraining gettext's
locale inputs while preserving UTF-8 behavior. These restrictions do not waive
glibc, GCC or other remaining package findings.

Existing cached images from older staging can still be reused; rebuilding an old
v1 context requires preparing the v2 inputs. Source staging does not restart
the persistent profile or approve production acceptance. See the
[validation record](../../../../docs/TESTING-ROADMAP.md#debian-os-remediation-2026-11-22).
