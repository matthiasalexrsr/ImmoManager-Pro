#!/bin/bash
set -e

# Disk-backed export staging can grow with the data volume.
if [ -n "${TMPDIR:-}" ]; then
  mkdir -p "$TMPDIR"
  chmod 700 "$TMPDIR"
fi

# Run database migrations (fail loudly if they fail)
if [ -f alembic.ini ]; then
    echo "Running database migrations..."
    if ! alembic upgrade head; then
        echo "ERROR: Database migration failed! Exiting." >&2
        exit 1
    fi
    echo "Migrations applied successfully."
fi

# Execute the main command
exec "$@"
