# Contract evidence in tenant disclosure

The existing authenticated `/admin/dsgvo/tenant/{id}/export` JSON download now
includes explicitly related contract drafts, retained review/command snapshots,
selected immutable template versions, signatures, attachment manifests and the
stored PDF/original bytes. Unrelated tenant/portfolio records are excluded.
Historical edits from tenant A to B disclose A's retained command evidence while
redacting B's current draft content. Unassigned prospects are not matched by
name/email; unselected template versions and arbitrary free-text references are
not attributed to a person.

The ordinary top-level tenant graph remains compatible. With wizard evidence its
schema is `tenant-data-graph/3`. `contract_wizard_files` contains SHA256, byte size,
evidence ID and encoding. `wizard_file_contents` maps each ID to ordered
`{position, data_base64}` blocks. Concatenating strictly decoded blocks yields the
original PDF/attachment; validate byte size and SHA256 against its manifest.
Metadata-only attachment links do not claim original bytes. Superseded editable
review PDFs not retained by the underlying journal are not invented/recreated.

Downloads are fully validated in one SQL repeatable snapshot (SQLite explicitly
begins its read transaction) before HTTP success. SQL reads stored PDF BLOBs in
64 KiB substrings and original chunk rows in bounded batches. The buffer size is
not a total file/record limit. Private temporary output uses the existing real
Windows ACL/POSIX protection helper and is removed on failure, disconnect or
successful completion. Fresh rights are checked during preparation and sending.

`anonymization-preview` and the confirmed command remain explicitly
`tenant_profile_only`: original contract documents, retained draft/review/result
fields, template body/title, signer/reference/note and original attachment bytes
can contain personal information and remain unchanged. Preview and result name
these retained collections and fields. This operation does not erase immutable
documents or assert a legal retention decision. All selected evidence/manifests
participate in the preview hash. Hidden portfolio relations block profile changes
without exporting their content. PostgreSQL locks related draft parents NOWAIT
under the tenant transaction; an in-progress journal write returns a recoverable
409 rather than a reversed lock-order deadlock. SQLite uses its real exclusive
writer transaction and Memory acquires account management then the shared
financial RLock, matching private editor writes and fresh auth reads.

Private G40 `form_drafts` for explicit `tenants/entity_id` targets remain opaque
across users: only count and an aggregated version digest enter the retention
manifest/preview hash. No ciphertext, private editor fields or owner IDs are
exported/decrypted. Their contents are explicitly excluded and must be handled by
the respective editor's owner. Expired ciphertext still counts until actually
discarded. Unbound new drafts and free-text references elsewhere cannot safely be
attributed from their public identity. Normal tenant deletion is blocked while
these explicitly bound drafts or historical wizard snapshots remain. The tenant
row lock/SQLite BEGIN IMMEDIATE is acquired before that retention check, sharing
the resource lock used by G40 saves.

Contract-bound source attachments now require the selected existing tenant to
match the freshly scoped/locked source contract. General property attachments
remain supported. Historical foreign contract evidence is preserved, but refuses
a partial privacy export. The command never fetches external URLs.

No new schema/bootstrap hook is required: the six existing v1 wizard tables are
used, and the optional private-draft table is detected without importing G40's
core. Complete SQL recovery already preserves the journals and bytes. The new
synthetic recovery test encrypts a full backup, removes its original installation,
restores elsewhere, starts a fresh process and verifies the actual authenticated
JSON download and every original hash despite source-file loss. This is distinct
from a supported business-subset import, which remains guarded.

Integration keeps G10's existing three-target invoice/payment privacy guards:
neither `tenant_data_graph.py` nor `tenant_graph_source.py` is replaced. Product
hooks are limited to `tenant_privacy.py`, `contract_wizard.py`, the existing admin
export handler and two new privacy services. Root owns CI/app/settings/recovery.

PostgreSQL gates are in `backend/tests/test_tenant_wizard_privacy_postgres.py`.
They use the established disposable UUID-schema fixture and only the explicit
`TEST_SERVER_DATABASE_URL`; absence skips three gates, never falls back to a
production URL or claims PostgreSQL proof. Include this file in the dedicated PG
CI command. The actual signature concurrency gate uses two independent sessions
and the normal wizard command; the SQLite private-draft/delete race gate also
uses independent connections and proves the unlocked retention-check baseline
can orphan a draft. The bounded native Memory thread regression demonstrates
that the opposite auth/financial lock order stalls concurrent private writes.
Local verification counts are supplied with the commit.

Verification on the isolated native branch: the final new suites pass 44 cases
with 6 explicit skips (three backend-specific Memory/SQLite cases and three PG
cases without the dedicated service). This includes the actual source-gone
encrypted recovery/new-process authenticated disclosure. Existing full focused
Privacy/Credit/Wizard/API gates passed 124/125 cases with 10 skips in
Memory/SQLite respectively; the legacy Privacy/Credit subset was rerun after the
Memory lock-order change (32 passed, 3 skips). Ruff and scoped mypy (five product
sources) pass. Both narrowly disabled-lock baselines fail their respective
parallel functional test, while the actual implementation passes. Linux/PG
proof must come from the dedicated integrated CI, not these explicit local skips.
