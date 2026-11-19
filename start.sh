#!/usr/bin/env bash
set -euo pipefail

project_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v uv >/dev/null 2>&1; then
  printf '%s\n' 'EzLLMRouter requires uv and Python 3.12. Install uv, then run ./start.sh again.' >&2
  exit 127
fi

# Keep newly created databases, credentials, and state directories private.
umask 077

exec uv run --project "$project_dir/server" --frozen --no-python-downloads \
  ezllmrouter \
  --db "$project_dir/local-instance/service.sqlite" \
  --secrets-dir "$project_dir/local-instance/secrets" \
  --web-root "$project_dir/web" \
  "$@"
