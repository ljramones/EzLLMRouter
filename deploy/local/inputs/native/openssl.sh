set -eu
export LC_ALL=C LANG=C SOURCE_DATE_EPOCH=1795392000
cd /inputs
sha256sum --strict -c SHA256SUMS
dpkg -i build-debs/*.deb
mkdir -p /out/source /out/openssl-build
tar -xzf /inputs/openssl_3.5.9.orig.tar.gz -C /out/source
cd /out/source/openssl-3.5.9
tar -xJf /inputs/openssl_3.5.9-1~deb13u1.debian.tar.xz
while IFS= read -r file; do
 patch --batch --forward --fuzz=0 -p1 < "debian/patches/$file"
done < debian/patches/series
while IFS= read -r file; do
 patch --batch --forward --fuzz=0 -p1 < "/inputs/$file"
done < /inputs/PATCHES
sed -i 's/^BUILD_METADATA=.*/BUILD_METADATA="ezllmrouter1"/' VERSION.dat
cd /out/openssl-build
HASHBANGPERL=/usr/bin/perl CFLAGS='-O2 -g0 -fstack-protector-strong -D_FORTIFY_SOURCE=3 -fPIC' LDFLAGS='-Wl,-z,relro,-z,now' /out/source/openssl-3.5.9/Configure shared --prefix=/usr --openssldir=/usr/lib/ssl --libdir=lib/aarch64-linux-gnu no-idea no-mdc2 no-rc5 no-ssl3 no-ssl3-method enable-unit-test enable-rfc3779 enable-cms no-capieng no-rdrand enable-tfo enable-zstd enable-zlib enable-fips enable-ec_nistp_64_gcc_128 no-padlockeng debian-arm64
make -j8 all
make test HARNESS_JOBS=8 TESTS='test_pem_read_depr test_ec test_x509 test_crl test_verify test_evp test_evp_extra test_cms test_dane test_quic_stream test_quic_tserver test_quicapi test_quicfaults'
./util/wrap.pl apps/openssl version -a > /out/openssl-version.txt
perl configdata.pm --dump > /out/openssl-config.txt
sha256sum libcrypto.so.3 libssl.so.3 providers/legacy.so apps/openssl > /out/openssl-code-sha256.txt
dpkg-query -W > /out/build-packages.txt
