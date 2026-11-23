set -eu
export LC_ALL=C LANG=C SOURCE_DATE_EPOCH=1795392000
cd /rust-inputs
sha256sum --strict -c SHA256SUMS
dpkg -i debs/*.deb
python -I -m pip install --no-index --only-binary=:all: --require-hashes --find-links=/crypto-inputs/wheelhouse -r /crypto-inputs/requirements.build.lock
while ! test -f /out/dev-prefix/usr/lib/aarch64-linux-gnu/libcrypto.so.3; do sleep 2; done
mkdir -p /out/crypto-source /out/crypto-wheel
tar -xzf /sources/cryptography-50.0.2.tar.gz -C /out/crypto-source
cd /out/crypto-source/cryptography-50.0.2
sed -i 's/^version = "50.0.2"/version = "50.0.2+ezllmrouter1"/' pyproject.toml
sed -i 's/^__version__ = "50.0.2"/__version__ = "50.0.2+ezllmrouter1"/' src/cryptography/__about__.py
mkdir .cargo
printf '%s
' '[source.crates-io]' 'replace-with = "vendored-sources"' '[source.vendored-sources]' 'directory = "/crypto-inputs/vendor"' > .cargo/config.toml
export OPENSSL_NO_VENDOR=1 OPENSSL_STATIC=0 OPENSSL_DIR=/out/dev-prefix/usr OPENSSL_INCLUDE_DIR=/out/dev-prefix/usr/include OPENSSL_LIB_DIR=/out/dev-prefix/usr/lib/aarch64-linux-gnu
export LD_LIBRARY_PATH=/out/dev-prefix/usr/lib/aarch64-linux-gnu CARGO_NET_OFFLINE=true CARGO_BUILD_JOBS=2
maturin build --release --locked --offline --compatibility linux --interpreter /usr/local/bin/python --out /out/crypto-wheel
rustc --version > /out/crypto-rustc-version.txt
cargo --version >> /out/crypto-rustc-version.txt
sha256sum /out/crypto-wheel/*.whl > /out/crypto-wheel/SHA256SUMS
