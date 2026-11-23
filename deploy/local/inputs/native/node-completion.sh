set -eu
export LC_ALL=C LANG=C SOURCE_DATE_EPOCH=1795392000
cd /inputs
sha256sum --strict -c SHA256SUMS
dpkg -i build-debs/*.deb
cd /out/node-source/node-v24.22.3
export LD_LIBRARY_PATH=/out/dev-prefix/usr/lib/aarch64-linux-gnu
make -j8
mkdir -p /out/node-runtime
cp out/Release/node /out/node-runtime/node
strip /out/node-runtime/node
/out/node-runtime/node -e 'console.log(JSON.stringify(process.versions))' > /out/node-runtime/versions.json
readelf -d /out/node-runtime/node > /out/node-runtime/dynamic.txt
sha256sum /out/node-runtime/node > /out/node-runtime/SHA256SUMS
