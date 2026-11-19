#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
export GOTOOLCHAIN=local
export GOCACHE="${GOCACHE:-$repo_root/.cache/go-build}"
if [[ "${1:-}" == "--http" ]]; then
  python3 -I -S "$repo_root/tests/client_languages/http_fixture.py"
  exit
fi
cd "$repo_root/clients/go"
if [[ -n "$(gofmt -l .)" ]]; then
  gofmt -l .
  exit 1
fi
go vet ./...
go test -race ./...
bash "$repo_root/clients/java/build.sh" test
