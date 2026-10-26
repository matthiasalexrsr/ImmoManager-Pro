# Base image pinned by tag and digest (rebuild steps: docs/OPERATIONS_BACKUP_SECRETS_20261008.md).
FROM node:24.21.0-bookworm-slim@sha256:d6aa754f16b3197301076f047b5def2f02ea1dbbc2ca920407d46d7ec7f87b20 AS frontend-build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11.15-slim-bookworm@sha256:d29f48a31a8b408ed19272ca1e7b10ebae13b240a27e862d3d4217c528e2e0c3 AS runtime

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
COPY requirements-pip.txt requirements.txt constraints.txt ./
COPY requirements-runtime.txt ./
RUN pip install --no-cache-dir -r requirements-pip.txt \
    && pip install --no-cache-dir -r requirements-runtime.txt -c constraints.txt

# Build-only download and license inventory. No npm installation, build helpers
# or download cache is copied into the operated application image.
FROM runtime AS package
COPY backend/ backend/
COPY tools/ tools/
COPY packaging/ packaging/
COPY LICENSE requirements-runtime.txt ./
COPY mietvertrag_wizard_fastapi_reportlab_pro/ mietvertrag_wizard_fastapi_reportlab_pro/
COPY --from=frontend-build /frontend/ frontend/
RUN python -m tools.prepare_e_invoice /app/artifacts/e-invoice --platform linux-x64 \
    && IMMO_PACKAGE_TARGET=hosting python -c "from tools.third_party_notices import generate; generate('/app/notices')"

FROM runtime AS application
# Copy application code
COPY backend/ backend/
COPY db/ db/
COPY alembic.ini .
COPY i18n/ i18n/
COPY mietvertrag_wizard_fastapi_reportlab_pro/ mietvertrag_wizard_fastapi_reportlab_pro/

COPY --from=frontend-build /frontend/dist/ frontend/dist/
COPY --from=package /app/artifacts/e-invoice/ /app/e-invoice/
COPY --from=package /app/notices/ /app/THIRD_PARTY_NOTICES/
ENV E_INVOICE_BUNDLE=/app/e-invoice
ENV THIRD_PARTY_NOTICES_DIR=/app/THIRD_PARTY_NOTICES

# Copy entrypoint script
COPY docker-entrypoint.sh .
RUN chmod +x docker-entrypoint.sh

# Persistent data: uploads, integration settings, key file, logs and full backups (volume in compose)
ENV DATA_DIR=/app/data
RUN groupadd --gid 10001 immomanager \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /app/data immomanager \
    && mkdir -p /app/data && chown 10001:10001 /app/data
USER 10001:10001

EXPOSE 8000

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
