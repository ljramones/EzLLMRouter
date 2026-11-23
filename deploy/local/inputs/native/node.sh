set -eu
export LC_ALL=C LANG=C SOURCE_DATE_EPOCH=1795392000
cd /inputs
sha256sum --strict -c SHA256SUMS
dpkg -i build-debs/*.deb
while ! test -f /out/openssl-code-sha256.txt; do sleep 2; done
make -C /out/openssl-build install_dev DESTDIR=/out/dev-prefix
mkdir -p /out/node-source
tar -xJf /sources/node-v24.22.3.tar.xz -C /out/node-source
cd /out/node-source/node-v24.22.3
export LD_LIBRARY_PATH=/out/dev-prefix/usr/lib/aarch64-linux-gnu
./configure --prefix=/usr/local --without-npm --without-corepack --shared-openssl --shared-openssl-includes=/out/dev-prefix/usr/include --shared-openssl-libpath=/out/dev-prefix/usr/lib/aarch64-linux-gnu --openssl-use-def-ca-store
make -j4
mkdir -p /out/node-runtime
cp out/Release/node /out/node-runtime/node
strip /out/node-runtime/node
/out/node-runtime/node -e 'console.log(JSON.stringify(process.versions))' > /out/node-runtime/versions.json
readelf -d /out/node-runtime/node > /out/node-runtime/dynamic.txt
sha256sum /out/node-runtime/node > /out/node-runtime/SHA256SUMS
