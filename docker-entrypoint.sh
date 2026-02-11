#!/bin/bash
set -e

# Run database migrations
if [ -f alembic.ini ]; then
    echo "Running database migrations..."
    alembic upgrade head
fi

# Execute the main command
exec "$@"
