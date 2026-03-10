#!/bin/bash
set -e

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
