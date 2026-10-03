# G43 contract correspondence evidence

This additive integration requires the final G06.2 core `8aabaa0895ccc10af61dd9714d7f75ab9b8c966e` and its runtime model/schema hooks. It introduces no database tables or migration. Installation/startup, reset/partial-transfer guards, recovery and the browser integration remain in the separate runtime package.

## Exact relationship and immutable original

Tenant graph version 6 adds `contract_correspondence_drafts`, `contract_correspondence_commands` and `contract_correspondence_events`. Only approved drafts and their approval/manual-event receipts are exported. Each draft must match the exact tenant, contract, unit, property and current authorized portfolio; a shared property or a successor with another tenant does not establish membership. A boolean raw existence check detects contradictory hidden parent/child bindings before JSON is selected. It returns a denial, without foreign metadata.

Shared G06 validators check the frozen approval result and the complete event result against their actual journal rows. Creation and the exact review used by approval must have a unique receipt; the query selects only receipt identity/hash and the two relevant JSON scalars, never earlier private request/result bodies. Each exported row has a canonical SHA-256. `scope.contract_correspondence` includes the receipt proofs and a digest of the full selected correspondence evidence plus the opaque private-work state.

Reviewed contract/context, immutable template identity/body hash, allowlisted historical names and an optional accepted lifecycle receipt are checked explicitly. A later legitimate supersession does not rewrite the earlier lifecycle state or command result in a letter. The original must be the exact matching version 1 `archive_original`, including actor, subjects and reviewed PDF SHA. The existing document-version graph verifies its full chunk chain and bytes; `prepare_tenant_export` includes those original bytes once in `document_version_contents`. Export never rerenders an approved historical PDF.

## Private work and profile anonymization

Open drafts, recipients, bodies, actors and earlier private edit/review command responses are not included. `scope.private_correspondence_drafts` contains a count and an opaque revision digest. This state participates in the anonymization plan hash, so a changed private draft invalidates an earlier plan without revealing its contents.

The memory comparison serializes all three declared journal model types, rather than comparing ORM object identities. SQL uses the existing coherent snapshot and tenant/contract lock protocol; SQL projections apply explicit subject/scope predicates and fetch evidence in batches of 100. No total tenant-history limit or first-100 truncation is imposed. Current parent bindings are loaded once from the selected tenant contracts with minimal, scoped property/unit projections in batches of 500. These bindings stay internal to validation and do not add parent entities to the privacy export.

Profile-only anonymization preserves every approved/private journal row and archived original. Its preview and response explicitly disclose retained original recipients, old source names and manual observation notes, and count retained private work without exposing contents. Destructive anonymization requires access to every linked correspondence portfolio. Fresh scope checks and private output cleanup remain in the enclosing G43 transaction/download workflow.

`manual_observation_only` is preserved throughout. These rows describe explicit human observations; this package does not perform dispatch or establish delivery or legal validity.

## Focused checks

The new `test_tenant_correspondence_privacy.py` uses actual core commands and synthetic Memory/SQLite data. It checks archived PDF bytes and complete payload hashes, previous/private text exclusion, all-three-journal retention after profile anonymization, private-change conflicts, same-property tenant isolation, corrupted bindings/actors/missing receipts/contradictory responses, cleanup after grant withdrawal, legitimate lifecycle supersession and 101 consecutive manual observations without batch truncation. SQL query checks inspect the selected proof columns.

PostgreSQL and actual browser execution are not claimed by this package. Full recovery of the complete graph must additionally run against the separately integrated runtime/recovery hooks.
