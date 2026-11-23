#!/usr/bin/env bash
# Pin every Docker image to the versions tested in uv.lock.
#
# Each image keeps its own requirements.txt (what it installs); pip installs it with
# `-c constraints.txt`, so every package, direct or indirect, gets exactly the uv.lock version.
# Without this, `>=` ranges let an image pick up new major versions nobody tested
# (23 Nov 2026: haystack-ai 3.5 in the image vs 2.30 tested broke every Chat answer).
#
#   scripts/export_constraints.sh           # rewrite app/ and frontend/constraints.txt from uv.lock
#   scripts/export_constraints.sh --check   # CI: fail if they are out of step with uv.lock
set -euo pipefail
cd "$(dirname "$0")/.."

generate() {
  # --locked: fail if uv.lock is out of step with pyproject.toml (run `uv lock` first).
  # --no-header: compare versions only, not the uv command line.
  uv export --locked --no-header --no-hashes --no-emit-project --format requirements-txt -q
}

targets=(app/constraints.txt frontend/constraints.txt)  # the runner image uses app/constraints.txt

if [[ "${1:-}" == "--check" ]]; then
  expected="$(generate)"
  for t in "${targets[@]}"; do
    if ! diff -q <(printf '%s\n' "$expected") "$t" >/dev/null 2>&1; then
      echo "ERROR: $t is out of step with uv.lock. Run scripts/export_constraints.sh and commit." >&2
      exit 1
    fi
  done
  echo "constraints.txt files match uv.lock"
  exit 0
fi

out="$(generate)"
for t in "${targets[@]}"; do
  printf '%s\n' "$out" > "$t"
done
echo "wrote ${targets[*]} from uv.lock"
