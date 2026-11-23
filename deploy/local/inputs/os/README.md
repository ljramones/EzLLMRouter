# Reviewed Debian runtime inputs

`debian13-arm64.lock.json` selects immutable official Python 3.12.16 and Node
24.22.3 ARM64 images based on Debian 13 (Trixie). Thirteen reviewed Debian archives
update base-files, glibc, OpenSSL, zlib, SQLite, ACL and GCC runtime libraries; the Node closure uses twelve because it
does not install the Python base's OpenSSL command-line package.

The v4 lock records binary/source versions, archive sizes and SHA-256 values,
publisher URLs, role membership, upstream image/config identities and the
build-only installer's hash, plus the exact runtime package-removal closure.
Acquisition used APT's authenticated InRelease and
package-index checks with Debian's archive keyring. The review retains the signed
indexes, keyring identity, exact package metadata and inspected maintainer scripts
under ignored `.artifacts/debian-remediation/`.

Six additional archives come from authenticated Debian testing (Forky) indexes:
SQLite 3.54.1-2, libacl 2.4.0-1, GCC 14 base 14.4.0-4, and the GCC 16 base,
libgcc and libstdc++ closure at 16.2.0-4. Their declared libc dependencies fit
the retained glibc 2.41; offline native and installed-client checks still apply.
The base OS remains Trixie. Each archive records its exact source suite/version,
and the extra origin binds the signed InRelease and archive-keyring hashes.
Inventories use Debian:14 advisory records only for the exact reviewed Forky
binary/source versions; other installed packages retain Debian:13 attribution.
An unknown suite, mismatched source or unauthenticated origin is rejected.
This prevents an OS-wide ecosystem change from concealing retained findings.
The three OpenSSL archives now use the
[reviewed local native backport](../native/README.md). The v4 lock also binds
the shared-SSL Node binary and cryptography wheel, all build recipes, source
artifacts and exact output hashes. Local build origins remain explicit; original
upstream versions are used for advisory queries. All copies require runtime proof
before the native review can mark the nine exact advisories fixed.
Signed indexes, archive inspection and trial results are retained under ignored
`.artifacts/dependency-resolution/`. No custom-built SQLite archive is selected.

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

Existing cached images from older staging can still be reused. Exact historical
v2 packets remain verifiable; origin overrides require v3 metadata. Rebuilding
a v1 context requires preparing current inputs. Source staging does not restart
the persistent profile or approve production acceptance. See the
[validation record](../../../../docs/TESTING-ROADMAP.md#debian-os-remediation-2026-11-22).
