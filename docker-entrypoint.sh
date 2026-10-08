#!/bin/bash
set -e

# Explicit upgrade before the server starts: a database behind the Alembic head gets a
# verified full backup (database, uploads, configuration, keys) first, then the migrations.
# The server itself never changes the schema; it refuses an outdated database.
# Set IMMO_SKIP_UPGRADE=true to start without this step (the server then refuses if needed).
if [ "${IMMO_SKIP_UPGRADE:-false}" != "true" ]; then
    echo "Checking database schema (python -m backend.upgrade)..."
    if ! python -m backend.upgrade; then
        echo "ERROR: Explicit upgrade failed; the server is not started." >&2
        exit 1
    fi
fi

# Execute the main command
exec "$@"
