set -eu
dpkg -i /tools/debs/*.deb
for file in /io/*.so; do
 patchelf --replace-needed libpq-53e4e5f8.so.5.18 libpq-ezllmrouter1.so.5 "$file"
done
