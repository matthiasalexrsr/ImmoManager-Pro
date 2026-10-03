#!/bin/bash
set -e

# Disk-backed export staging can grow with the data volume.
if [ -n "${TMPDIR:-}" ]; then
  mkdir -p "$TMPDIR"
  chmod 700 "$TMPDIR"
fi

# Schema maintenance is an explicit command (for example: alembic upgrade head).
# An ordinary start, restart, backup resume, or restore must never migrate SQL.

# Execute the main command
exec "$@"
