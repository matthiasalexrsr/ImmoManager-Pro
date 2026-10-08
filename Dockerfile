# Base image pinned by tag and digest (rebuild steps: docs/OPERATIONS_BACKUP_SECRETS_20261008.md).
FROM python:3.11.15-slim-bookworm@sha256:d29f48a31a8b408ed19272ca1e7b10ebae13b240a27e862d3d4217c528e2e0c3

WORKDIR /app

# pg_dump/pg_restore 16 (PGDG) for full backups of the PostgreSQL 16 service; bookworm ships 15,
# which refuses to dump a newer server.
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
       > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update && apt-get install -y --no-install-recommends postgresql-client-16 \
    && apt-get purge -y gnupg && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# Python dependencies: direct pins plus the whole transitive tree
COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt

# Copy application code
COPY backend/ backend/
COPY db/ db/
COPY alembic.ini .
COPY i18n/ i18n/
COPY mietvertrag_wizard_fastapi_reportlab_pro/ mietvertrag_wizard_fastapi_reportlab_pro/

# Copy pre-built frontend (run `cd frontend && npm ci && npm run build` before docker build)
COPY frontend/dist/ frontend/dist/

# Copy entrypoint script
COPY docker-entrypoint.sh .
RUN chmod +x docker-entrypoint.sh

# Persistent data: uploads, integration settings, key file, logs and full backups (volume in compose)
ENV DATA_DIR=/app/data
RUN mkdir -p /app/data

EXPOSE 8000

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
