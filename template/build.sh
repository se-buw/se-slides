#!/usr/bin/env bash
# Builds this course with the shared se-slides tools: ./build.sh [lecture ...] [--pdf] [--strict]
set -euo pipefail
cd "$(dirname "$0")"
core=_extensions/se-slides/tools/build.sh
[ -f "$core" ] || { echo "Shared tools missing. Run: git submodule update --init"; exit 1; }
exec bash "$core" "$@"
