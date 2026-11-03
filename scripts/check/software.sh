#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"
TEST_PYTHON="${TEST_PYTHON:-${ROOT_DIR}/.venv/bin/python}"
"${TEST_PYTHON}" -m unittest discover -s tests -v
node tests/integration_tests/check_image_urls.cjs
while IFS= read -r -d '' script; do
  bash -n "${script}"
done < <(find scripts -type f -name '*.sh' -print0)
for script in ./*.sh; do bash -n "${script}"; done
