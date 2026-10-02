# G37.1 — Explicit immutable document versions

Native isolated source: `assist/document-versioning`, based on `d96206a`.
Historical anchors: `ARCHITEKTURPLAN.md:83`, feature matrix G37.1 and archived
`package_2025-11-12/docs/BENUTZERHANDBUCH.md` (Versionierung: history, comparison,
restoration and comments). General annotations/templates/full-text are G37.2/3.

## Core contract

The existing Document and its original `file_url` remain unchanged. Metadata
(title/tags/date/description/AI fields) remains editable. A user must explicitly
review the managed original's SHA256 and confirm **Archive original** before
uploading new versions. Missing or external originals yield a recoverable 422;
no substitute is labelled as the old original. Managed absolute paths must
resolve inside the current local upload root. Wizard PDFs require the exact
draft/document linkage and the existing authorized immutable PDF checks.

Uploads and restoring a chosen earlier version append a new version. Both keep
the predecessor, publication metadata snapshot, actor, comment, original filename,
SHA256, size, and ordered 64KiB original byte blocks. The current archived version
is the highest version number, distinct from the unchanged legacy original URL.
There is no inferred content truncation, legal certification or cash operation.

Every command contains `expected_document_etag`, `expected_head_id`, explicit
`confirmed`, nonblank comment and actor-bound idempotency key. Identical replay
returns the exact saved receipt; changed inputs give 409. Stale heads give 409 and
stale metadata 412. Native SQLite BEGIN IMMEDIATE and PostgreSQL parent row locks
serialize independent sessions. Memory has account→domain lock ordering and
whole-command rollback. Fresh role/activity/portfolio checks run before and after
publication and before downloading; completed private temporary downloads use
the existing abort-safe `PrivateDownloadResponse`.

## Required Root integration

* Register `backend.db.document_version_models.DOCUMENT_VERSION_MODELS` in Base
  metadata/bootstrap/Alembic autogenerate/full-recovery metadata. Both tables are
  `document_versions` and `document_version_chunks`; migration `y1a2b3c4d5e6` follows
  `x1a2b3c4d5e6`. `ensure_document_version_schema(connection)` is repeatable additive
  create/checkfirst plus SQLite/PostgreSQL immutable update/delete guards. Add the
  native PG test module to the existing dedicated PostgreSQL CI job.
* Include `routers.document_versions.router` under `/api/v1`. Existing `documents`
  ordinary CRUD is separate; nested routes explicitly authenticate and recheck the
  actor's `documents` write capability. HTTP tests exercise real JWT and scope
  middleware, including readonly and foreign/revoked portfolio requests.
* Existing narrow hooks are included in this Core diff: BaseRepository source
  edit guards; Memory document/property/unit edit + generic patch guards;
  `contract_wizard.guard_delete_link` calls version retention first; existing
  `contract_wizard.guard_destructive_reset` also refuses version-journal partial
  merge/replace/reset before mutation. All existing finance/bank/G07 guards remain.
* Register the new memory collections when resetting/disposal/snapshot-normalizing.
  SQL clear_all must refuse `guard_partial_transfer(store)` before DML. Generic
  business JSON contains neither these journals nor their original bytes; business
  import/reset is refused when a journal exists. Only a complete recovery preserves
  registered tables and immutable history.
* G43 hookup is Root-owned. Select exact stored `tenant_id` and contract identity,
  retain historical tenant binding, check the current authorized Doc/property/
  contract chain and fail closed on foreign/conflicting identities. No name/email
  matching and no shared/property-only document expansion. Expose version manifests
  and `services.document_versions.verified_blocks(store,row)` for original bytes in
  the same coherent snapshot. This iterator validates SQL length with a typed
  CASE **before DBAPI materialization**, position, portfolio, size and SHA256;
  Memory checks buffer nbytes before converting. Extend profile-only retention and
  plan-hash/CAS normalization; immutable evidence is retained, never rewritten by
  profile anonymization.
  Live reads also call `validate_manifest(row)` before exposing history or bytes:
  it validates the complete Document snapshot and reuses the shared pure
  `document_version_validation.validate_manifest_identity(row,snapshot)` policy.
  The shared module is supplied separately by Recovery commit `da61a374`;
  no divergent online/offline identity rules are introduced.
* FullRecovery hookup is Root-owned. Source loss is satisfiable only for an exact
  version-1 `archive_original` document/source/subject/portfolio binding with complete
  verified chunks and SHA. Preserve historical snapshot URI on offline restore;
  current absolute document paths can legitimately be rebased to a new upload root.
  Do not compare current path literally with historical URI. All absent pre-y1
  tables are compatible; partial table sets or corrupted journals must fail before
  target/session/credential mutation. No directory-wide/file-key fallback.
* Documents.jsx currently belongs to typed-OCR work. History UI is a separate
  component and Root will insert a small document-ID-bound hook. The historical
  viewer's `/files/download?key=...` conversion must not be used for version URLs;
  version download is an explicit constructed `/documents/{id}/versions/{id}/download`
  with shared API refresh. Do not display current live OCR as historical evidence.

## Verification

Initial combined gate: 85 passed, 10 explicit skips (PG service absent and native
SQL-only/bounded existing cases), including Memory/SQLite versions, actual JWT
HTTP/scope, fresh full Alembic y1 chain + empty downgrade/up + populated refusal,
source loss, absolute-path rebase, corrupt restored chunk rejection, rollback,
metadata/source/cascade guards and existing G07/tenant privacy regressions.
Five Core source files passed mypy; new files passed Ruff after import formatting.
Broader configured-SQL gate: 120 passed, 13 explicit skips including six optional
PG cases, with existing edit-concurrency/G07/privacy tests. Final Core follow-up:
29 passed + one native-SQL-only Memory skip; includes competing new uploads,
adjustable byte-budget failure/retry, explicit confirmation and contract-only
source bindings protecting resolved tenant/unit ancestry.
Final shared-manifest gate: 59 passed and one native-SQL-only Memory skip across
version commands, actual HTTP/schema and the 19 shared pure-manifest cases. A
corrupt snapshot is refused with 503 before exposing history or publishing a
download, including cleanup of its private workspace. Ruff and scoped mypy pass.
Actual PostgreSQL gates use only explicit `TEST_SERVER_DATABASE_URL`, fresh UUID
schema, the full real migration chain, independent sessions and owned cleanup.
They are supplied for CI, not claimed executed locally without that service.
