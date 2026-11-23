# Reviewed Debian runtime inputs

`debian13-arm64.lock.json` selects immutable official Python 3.12.16 and Node
24.22.3 ARM64 images based on Debian 13 (Trixie). Seven reviewed Debian archives
update base-files, glibc, OpenSSL and zlib; the Node closure uses six because it
does not install the Python base's OpenSSL command-line package.

The lock records binary/source versions, archive sizes and SHA-256 values,
publisher URLs, role membership, upstream image/config identities and the
build-only installer's hash. Acquisition used APT's authenticated InRelease and
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

`install_os.sh` runs only during an offline Docker build. It checks Debian's
version/architecture, verifies every archive hash, installs the selected local
packages and checks package consistency. Debian protects APT as essential; the
image-only removal explicitly permits removing exactly `apt`, `libapt-pkg7.0`
and `sqv`. An installed-package census rejects any additional removal. Do not
run this script on a host. Dpkg remains available for exact runtime inventories.

Final image qualification checks the actual installed versions and APT's absence.
Existing cached images from older staging can still be reused; rebuilding an old
context requires preparing the reviewed OS inputs. Source staging does not restart
the persistent profile or approve production acceptance. See the
[validation record](../../../../docs/TESTING-ROADMAP.md#debian-os-remediation-2026-11-22).
