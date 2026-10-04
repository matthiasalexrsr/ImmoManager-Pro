# TEHA initial L2 release: explicit maintenance

L2 `l2a2b3c4d5e6` has never been delivered in Root or live release 126. The
frozen initial release contains `teha_external_mappings` and
`teha_import_receipts`, including the receipt's non-null `mapping_id`,
`mapping_sha256`, RESTRICT mapping foreign key and digest constraint. Historical
DDL is now defined in `backend/db/teha_receive_release_l2.py`; migration and schema
validation do not import the current runtime ORM models.

## Absent family

Root's announced native maintenance slot first verifies the selected installation,
exclusive maintenance access, complete backup, stable encryption keyring and K2
prerequisites. Only then may the normal explicit Alembic maintenance path install
the reserved initial L2 revision. Startup, reads and import commands do not run
DDL or silently create missing tables. Production activation also needs the
separate Root transaction unit and coherent recovery/retention registration.

## Present family

The migration refuses any already-present L2 table before DDL. A partial family,
an earlier isolated development L2 layout without mapping columns, or a different
layout is not automatically detected and repaired. The same revision name in an
old disposable development database is not proof of the final release layout.

An operator must stop here, retain a complete backup and determine the database's
source and whether it contains evidence. An empty disposable development checkout
may be recreated only through an explicitly authorized disposable-database action
in the native slot. A database containing mappings, receipts, originals or history
requires a separate reviewed offline reconciliation plan preserving all evidence;
this follow-up supplies no drop, alter, backfill, upgrade-by-detection or repair.
Never apply disposable-development instructions to private installation data.

Read/preview/download reports HTTP 503 code
`teha_l2_schema_requires_maintenance` with this document's `maintenance_path`.
These paths do not expose the underlying schema exception and do not mutate the
family. Root must execute native SQLite/PostgreSQL and HTTP proof before release.
