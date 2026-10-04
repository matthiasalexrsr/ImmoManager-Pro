# TEHA transactional command source – historical handoff 2026-10-03

This document records the development predecessor at `150aa66`, following
`8015fe5`, `45824f6` and `503854a`. Its release and authority claims are
superseded by `TEHA_RELEASE_LAYOUT_CORRECTION_HANDOFF_20261004.md`.

L2 was never delivered in Root/live126. The final initial release includes the
receipt's non-null mapping ID/digest/FK. Earlier isolated source/database layouts
are not schema-identical and are never silently repaired; follow
`TEHA_L2_MAINTENANCE_20261004.md`.

## Authority correction

The predecessor proposed a dynamically imported actor-only `CommitAuthority`
and validator. That contract cannot prove the actual Session, transaction,
database target, operation or resource targets. It has been removed. Root has
not supplied an actual TEHA write unit, and this package invents no replacement
generic type. Every public mapping/document/task write and `_work(write=True)`
returns 503 `teha_write_unit_unavailable` before business access, even if an
actor-only fake module is installed. Notification capabilities do not unlock it.

Management serialization, request-token checks and fresh scope/role checks
remain supplemental fences. Prepared SQL/atomicity code behind the write gate
does not constitute a positive commit guarantee or runtime acceptance.

## Source and activation

Prepared source covers mapping confirmation, local preview, document/task
import, exact immutable receipt replay and DocumentVersion download. Source
History binds a stable opaque connection namespace and hashes the complete
sanitized source; original bytes remain in the existing document chunk family.
No provider write or finance mutation is present.

The router defines local endpoints with `WorkflowAuthorityRoute`; it is not
registered by this checkout's central routing. These are dormant route/source
changes. Root retains ownership of registration, actual unit integration,
Recovery/retention, Startup, Settings and any future job adapter.

## Historical test observations

The predecessor reported seven passing tests from
`backend/tests/test_teha_transaction_boundaries_pure.py`. That file imported the
runtime service and thereby Auth/config/Settings. Even `--noconftest` could not
make those imports no-runtime. The observed PASS was not a no-runtime proof.
Its positive actor-only assertion and the unexecuted synthetic positive command
suite have been removed. Their source remains in Git history for review.

The correction provides independent manifest tests under `tests/pure` and
explicit native-slot runtime boundary/schema tests under `backend/tests`.
No Python imports, tests, application, database, PostgreSQL, browser or portal
processes were run in the 2026-10-04 correction slot. New runtime acceptance
belongs to Root; old Ruff/Mypy/compile results do not validate the new source.
