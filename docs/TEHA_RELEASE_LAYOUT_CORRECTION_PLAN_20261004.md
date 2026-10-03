# TEHA: initial L2 freeze and evidence correction plan

Source base: clean `150aa6619f071c9321a8df0a3008496aea26dcd3` on
`assist/teha-receive-domain`. Root authorized this bounded follow-up after the
original backend chat ended. No other editor is working in this checkout.

## Confirmed release decision

L2 has never been included in Root or delivered to the live 126 installation.
The initial released L2 layout will include the receipt's non-null `mapping_id`,
`mapping_sha256`, mapping foreign key and digest constraint. The earlier L2
source/layout is an isolated development predecessor, not an installed release
to silently upgrade. The reserved revision remains `l2a2b3c4d5e6` after K2.

## Changes before implementation

1. Freeze both L2 tables, constraints and indexes in migration-owned source;
   remove migration dependence on mutable runtime ORM definitions. Absent family
   permits the explicit initial migration. Any present family is refused before
   migration DDL; partial or older development layouts require explicit offline
   maintenance. Runtime schema failures become safe HTTP 503 with a machine code
   and a maintenance-document reference, including preview and download.
2. Make the pure original validator independently bind receipt, immutable mapping
   ID/digest/generation, connection, portfolio and kind-specific target to the
   original's local binding. Runtime reads supply freshly checked parent context
   for property, period, unit and user mappings; no same-portfolio A/B substitution
   is accepted. Technical-order mappings cannot serve as document mappings.
3. Preserve document classification in the immutable TEHA original extension and
   compare it to the archived Document snapshot and the live document during
   replay/download. Preserve supported classification strings rather than forcing
   `teha_document` or inventing an enum. Changes require explicit review rather
   than making a permitted import unusable on its next read.
4. Remove the proposed dynamic actor-only CommitAuthority acceptance. No actual
   Root Unit/Session/transaction/database-target/operation/target contract exists.
   Every mapping/import write therefore remains HTTP 503 before the business
   writer or business DML, including when a fake actor-only module is installed.
   Notification capabilities and generic actor DTOs do not substitute for it.
5. Separate pure manifest/identity test source from runtime-boundary test source.
   Pure helpers must not import auth, global Settings, runtime stores or ORM
   registration. Replace positive fake-capability test claims with explicit
   fail-closed coverage; former positive command tests remain clearly deferred
   until a real Root unit can be exercised in the native slot.

## Verification and scope

Prepare targeted source tests for frozen migration structure, old/partial schema
503, cross-wired mapping/receipt/original bindings, classification round-trip,
and actor-only fake-authority rejection. Inspect diffs only in this slot; do not
run Python imports, tests, application, databases, PostgreSQL, browser or portal.
Root owns native execution and HTTP/database evidence. No private files or
private persisted databases are opened or changed.

No shared Recovery, Registry, Auth, Jobs, Startup or Settings source is edited.
The final handoff will propose a coherent read-only recovery proof over L2,
encrypted History, document versions/chunks and Task targets, distinguish absent
legacy families from partial families, and keep source completion separate from
runtime release acceptance.
