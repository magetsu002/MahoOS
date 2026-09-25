#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
BUILD="$(mktemp -d)"
trap 'rm -rf "$BUILD"' EXIT

cmake     -S "$ROOT/apps/maho-files"     -B "$BUILD"     -G Ninja     -DCMAKE_BUILD_TYPE=Release     -DMAHO_FILES_BUILD_TESTS=ON

cmake --build "$BUILD" --target maho-files-model-tests --parallel 2
QT_QPA_PLATFORM=offscreen ctest --test-dir "$BUILD" --output-on-failure -R maho-files-model-ops
