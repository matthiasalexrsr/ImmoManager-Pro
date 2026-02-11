#!/bin/bash
set -e

# Run database migrations if alembic is available
if [ -f alembic.ini ]; then
    echo "Running database migrations..."
    alembic upgrade head 2>/dev/null || echo "Migration skipped (using schema.sql init)"
fi

# Execute the main command
exec "$@"
