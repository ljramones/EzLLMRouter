set -eu
export LC_ALL=C LANG=C SOURCE_DATE_EPOCH=1795478400
cd /inputs
sha256sum --strict -c SHA256SUMS
dpkg -i build-debs/*.deb /review/build-tools/debs/*.deb
mkdir -p /out/source
tar -xzf /review/postgresql-18.6.tar.gz -C /out/source
cd /out/source/postgresql-18.6
export CPPFLAGS=-I/ssl/include CFLAGS='-O2 -fstack-protector-strong -D_FORTIFY_SOURCE=3' LDFLAGS='-L/ssl/lib/aarch64-linux-gnu -Wl,-z,relro,-z,now' LD_LIBRARY_PATH=/ssl/lib/aarch64-linux-gnu
./configure --prefix=/opt/ezllmrouter/postgresql --with-ssl=openssl --without-gssapi --without-ldap --without-icu --without-readline --without-zlib --disable-nls --without-lz4 --without-zstd --without-libxml --without-libxslt --disable-rpath
make -j8 -C src/interfaces/libpq
cp src/interfaces/libpq/libpq.so.5.18 /out/libpq-ezllmrouter1.so.5
patchelf --set-soname libpq-ezllmrouter1.so.5 /out/libpq-ezllmrouter1.so.5
readelf -d /out/libpq-ezllmrouter1.so.5 > /out/dynamic.txt
cp src/include/pg_config.h /out/pg_config.h
sha256sum /out/libpq-ezllmrouter1.so.5 > /out/SHA256SUMS
