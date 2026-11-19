#!/usr/bin/env bash
set -euo pipefail
client_root="$(cd "$(dirname "$0")" && pwd)"
build_dir="$client_root/build"
rm -rf "$build_dir/classes" "$build_dir/test-classes"
mkdir -p "$build_dir/classes"
sources=()
while IFS= read -r -d '' path; do sources+=("$path"); done < <(find "$client_root/src/main/java" -name '*.java' -print0)
javac --release 17 -Xlint:all -Werror -d "$build_dir/classes" "${sources[@]}"
cp -R "$client_root/src/main/resources/." "$build_dir/classes/"
jar --create --file "$build_dir/ezllmrouter-client-0.3.0.jar" -C "$build_dir/classes" .
if [[ "${1:-}" == "test" ]]; then
  mkdir -p "$build_dir/test-classes"
  sources=()
  while IFS= read -r -d '' path; do sources+=("$path"); done < <(find "$client_root/src/test/java" -name '*.java' -print0)
  javac --release 17 -Xlint:all -Werror -cp "$build_dir/ezllmrouter-client-0.3.0.jar" \
    -d "$build_dir/test-classes" "${sources[@]}"
  java -ea -cp "$build_dir/ezllmrouter-client-0.3.0.jar:$build_dir/test-classes" \
    com.cognitivedynamics.ezllmrouter.ClientTest "$client_root/../../tests/client_languages/cases.json"
fi
