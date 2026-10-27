#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ -f ".venv/bin/activate" ]; then source .venv/bin/activate; fi
python scripts/build_exe.py "$@"
