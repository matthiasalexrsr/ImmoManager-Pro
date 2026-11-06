#!/bin/bash
# Explicit offline developer deployment only. Customers use a verified installer.
# Usage: ./scripts/update.sh <exact-version-tag> <expected-40-character-commit>
set -euo pipefail

if [ "$#" -ne 2 ]; then
    echo "Use a verified installer for customer updates."
    echo "Developer use only, with the application fully stopped:"
    echo "  $0 <exact-version-tag> <expected-40-character-commit>"
    exit 2
fi

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd -- "$script_dir/.."
exec python -m backend.updater --developer-mode --target-version "$1" --expected-commit "$2"
