# C: central immutable dispute journal composition

Plan before source edits, against Root `e2c7652`. The complete Domain packet
`d0e0ab3` and its exact API/restore handoff are integrated. The early model
registry, native startup checks, subset-transfer boundaries and all full-recovery
paths were inspected. Ordinary parent/Privacy guards are already connected.

1. Register all four j2 models before fresh setup and Alembic metadata use.
   Explicit dev/test setup alone installs new original guards when the complete
   family was absent. Existing partial or weakened families fail without repair.
   Production validates the declared migration head and native guard bodies.
2. Add a pure read-only raw-SQLite/SQLAlchemy database validator. It pages case
   identities and loads only each case's journal and required parents, including
   source/correction statements and the complete affected period used for the
   original hash. Native FKs and guards are checked before any security DML.
   No application, auth, singleton, provider or dependency imports are permitted.
3. Connect that proof before backup image approval, staged-file rebasing and
   restored-session/claim normalization. Entirely absent old families are
   compatible; partial schema, orphan records, weakened triggers, broken original
   hashes/receipts/party bindings/correction chains prevent publication.
4. Refuse business subset export/import/reset with retained originals, including
   the first-writer race under existing account/domain/history barriers. Existing
   complete recovery carries SQLite originals verbatim and validates them first.
5. Connect the Memory/business-family exporter only through its established
   retained-family contract. Avoid a competing recovery container or plaintext
   originals. Original document-version chunks remain fully validated.

Focused synthetic gates cover raw SQLite and real PostgreSQL, successful complete
roundtrip with original reason/evidence, corrupt journal rejection before
security DML/publication, actual no-DDL startup and first-writer subset refusal.
Existing fixtures that explicitly build fresh native metadata install actual j2
guards; product startup never repairs a missing original trigger.

The historical party limitation remains visible. The separate next Domain
packet will freeze actual parties on future finalization; it cannot rewrite
previously published originals. Journal UI and the full A–L release gate remain
open after this central backend composition.
