set -eu
export LC_ALL=C LANG=C SOURCE_DATE_EPOCH=1795478400
cd /inputs
sha256sum --strict -c SHA256SUMS
dpkg -i build-debs/*.deb
cd /review/inputs
sha256sum --strict -c SHA256SUMS
mkdir -p /codec/source /codec/outputs
tar -xzf zstd-1.6.0.tar.gz -C /codec/source
cd /codec/source/zstd-1.6.0
export CFLAGS='-O2 -g0 -fPIC -fstack-protector-strong -D_FORTIFY_SOURCE=3'
export LDFLAGS='-Wl,-z,relro,-z,now'
make -j8 -C lib
make -j8 -C tests fuzzer
./tests/fuzzer -i1000 > /codec/upstream-tests.log 2>&1
gcc $CFLAGS -Ilib /recipes/zstd-regression.c lib/libzstd.a -pthread -o /codec/regression-fixed
/codec/regression-fixed > /codec/regression-fixed.log
cd /codec/parent-zstd
make -j8 -C lib libzstd.a
gcc $CFLAGS -Ilib /recipes/zstd-regression.c lib/libzstd.a -pthread -o /codec/regression-parent
set +e
/codec/regression-parent > /codec/regression-parent.log
status=$?
set -e
test "$status" = 1
cd /out/node-source/node-v24.22.3
mv deps/zstd/lib /codec/parent-vendored-lib
cp /out/node-runtime/node /codec/parent-node
cp -a /review/source/zstd-1.6.0/lib deps/zstd/lib
find deps/zstd/lib -type f -exec touch {} +
touch src/node_metadata.cc
unset CFLAGS LDFLAGS
export LD_LIBRARY_PATH=/out/dev-prefix/usr/lib/aarch64-linux-gnu
make -j8 node
cp out/Release/node /codec/outputs/node-v24.22.3-ezllmrouter2-linux-arm64
strip /codec/outputs/node-v24.22.3-ezllmrouter2-linux-arm64
/codec/outputs/node-v24.22.3-ezllmrouter2-linux-arm64 -e 'console.log(JSON.stringify({versions:process.versions,shared_openssl:process.config.variables.node_shared_openssl}))' > /codec/node-versions.json
readelf -d /codec/outputs/node-v24.22.3-ezllmrouter2-linux-arm64 > /codec/node-dynamic.txt
python -I /recipes/zstd-package.py
sha256sum /codec/outputs/* > /codec/SHA256SUMS
