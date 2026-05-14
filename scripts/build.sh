#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"

VENV="/tmp/steammanifesto-venv"
echo "==> Creating build environment"
python3 -m venv "$VENV" 2>/dev/null || true
"$VENV/bin/pip" install --quiet pyinstaller pyside6

echo "==> Building SteamManfiesto standalone executable"
/tmp/steammanifesto-venv/bin/pyinstaller \
    "$PROJECT_ROOT/build.spec" \
    --distpath "$PROJECT_ROOT/dist" \
    --workpath "$PROJECT_ROOT/build" \
    --clean

echo ""
echo "==> Done! Binary at: $PROJECT_ROOT/dist/SteamManfiesto"
echo "    Run: ./dist/SteamManfiesto"
