#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-$repo_root/.cache/rust-target}"
cargo test --manifest-path "$repo_root/clients/rust/Cargo.toml" --all-targets
cargo clippy --manifest-path "$repo_root/clients/rust/Cargo.toml" --all-targets -- -D clippy::correctness
cargo package --manifest-path "$repo_root/clients/rust/Cargo.toml" --allow-dirty
