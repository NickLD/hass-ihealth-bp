#!/usr/bin/env bash
# Run the test suite in a Linux container matching Home Assistant 2026.10 (Python 3.14).
set -euo pipefail
cd "$(dirname "$0")/.."
docker build -q -f docker/test.Dockerfile -t ihealth-bp-test . >/dev/null
src=$(pwd -W 2>/dev/null || pwd)
MSYS_NO_PATHCONV=1 docker run --rm -v "$src":/src -w /src -e PYTHONDONTWRITEBYTECODE=1 \
  ihealth-bp-test python -m pytest -p no:cacheprovider "$@"
