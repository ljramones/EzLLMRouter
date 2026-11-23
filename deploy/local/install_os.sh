#!/bin/sh
# Build-only input: the caller mounts this directory read-only with no network.
set -eu
export LC_ALL=C LANG=C LANGUAGE=C
. /etc/os-release
test "$ID" = debian
test "$VERSION_ID" = 13
test "$(dpkg --print-architecture)" = arm64
cd /opt/ezllmrouter/os-inputs
sha256sum --strict -c SHA256SUMS
export DEBIAN_FRONTEND=noninteractive
dpkg --install ./*.deb
test -z "$(dpkg --audit)"
# The sealed manifest names the complete reviewed removal closure. Debian marks
# some tools essential; allow only this exact image-only package change.
record_dir=$(mktemp -d)
dpkg-query -W -f='${db:Status-Status} ${Package}\n' > "$record_dir/before.raw"
sed -n 's/^installed //p' "$record_dir/before.raw" | sort > "$record_dir/before"
sort -u REMOVE-PACKAGES > "$record_dir/expected"
cmp REMOVE-PACKAGES "$record_dir/expected"
comm -23 REMOVE-PACKAGES "$record_dir/before" > "$record_dir/missing"
test ! -s "$record_dir/missing"
set --
while IFS= read -r package; do
    case "$package" in
        ''|[-.+]*|*[!a-z0-9+.-]*) exit 1 ;;
    esac
    set -- "$@" "$package"
done < REMOVE-PACKAGES
test "$#" -gt 0
apt-get --no-download --no-install-recommends --allow-remove-essential purge --yes "$@"
dpkg-query -W -f='${db:Status-Status} ${Package}\n' > "$record_dir/after.raw"
sed -n 's/^installed //p' "$record_dir/after.raw" | sort > "$record_dir/after"
comm -23 "$record_dir/before" "$record_dir/after" > "$record_dir/removed"
cmp REMOVE-PACKAGES "$record_dir/removed"
comm -13 "$record_dir/before" "$record_dir/after" > "$record_dir/added"
test ! -s "$record_dir/added"
rm -rf "$record_dir"
test -z "$(dpkg --audit)"
test ! -e /usr/bin/apt-get
test ! -e /usr/bin/apt
test ! -e /usr/bin/sqv
