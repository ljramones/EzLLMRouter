#!/bin/sh
# Build-only input: the caller mounts this directory read-only with no network.
set -eu
. /etc/os-release
test "$ID" = debian
test "$VERSION_ID" = 13
test "$(dpkg --print-architecture)" = arm64
cd /opt/ezllmrouter/os-inputs
sha256sum --strict -c SHA256SUMS
export DEBIAN_FRONTEND=noninteractive
dpkg --install ./*.deb
test -z "$(dpkg --audit)"
# The running application does not manage system packages or verify APT indexes.
# Debian protects APT as essential. This image-only removal must remove exactly
# these three tooling packages; preserve every other installed package.
record_dir=$(mktemp -d)
dpkg-query -W -f='${db:Status-Status} ${Package}\n' > "$record_dir/before.raw"
sed -n 's/^installed //p' "$record_dir/before.raw" | sort > "$record_dir/before"
apt-get --no-download --no-install-recommends --allow-remove-essential purge --yes apt libapt-pkg7.0 sqv
dpkg-query -W -f='${db:Status-Status} ${Package}\n' > "$record_dir/after.raw"
sed -n 's/^installed //p' "$record_dir/after.raw" | sort > "$record_dir/after"
comm -23 "$record_dir/before" "$record_dir/after" > "$record_dir/removed"
printf '%s\n' apt libapt-pkg7.0 sqv | cmp - "$record_dir/removed"
rm -rf "$record_dir"
test -z "$(dpkg --audit)"
test ! -e /usr/bin/apt-get
test ! -e /usr/bin/apt
test ! -e /usr/bin/sqv
