# Contract lifecycle API

All routes require authentication and current contract/portfolio access. Writes
require the existing contracts capability. Open drafts are private to their actor;
confirmed history is readable by currently authorized actors, including readonly.

Prefix: `/contracts/{contract_id}/lifecycle`.

| Method/path | Body |
| --- | --- |
| POST `/drafts` | `DraftCreate` (201) |
| GET `/drafts?before=&limit=25` | Own open drafts, keyset page |
| GET `/history?before=&limit=25` | Confirmed/finalized evidence, keyset page |
| GET `/drafts/{draft_id}` | Current draft/result |
| POST `/drafts/{draft_id}/edit` | `DraftEdit` |
| POST `/drafts/{draft_id}/review` | `RevisionCommand` |
| POST `/drafts/{draft_id}/confirm` | `Confirmation` |
| POST `/drafts/{draft_id}/finalize` | `Confirmation` |

Commands use `idempotency_key` and `expected_contract_etag` (existing strong
contracts ETag). Except creation, they require `expected_revision` (UUID string).
Edit/create contain `data`: `operation`, nonblank `reason`, plus either:

- `renewal`: `new_contract_number`, `new_start_date`, `new_end_date` (required;
  explicit null allowed). Existing parent must have a finite inclusive end;
  successor starts strictly afterwards. Same tenant/property/unit, new active
  contract; economic fields are not copied.
- `termination`: `termination_end_date` (inclusive). No cash/refund/cancellation
  of obligations is inferred. Future termination remains active.

Confirm/finalize add `reviewed_hash` (SHA256 hex) and `confirmed: true`. Confirm
checks the reviewed source and obligations again. Finalize requires a pending
termination and a server UTC date strictly after its accepted end, and uses the
current parent ETag. An authorized successor staff member may finalize.

Draft/result: `id`, `contract_id`, `portfolio_id`, `property_id`, `unit_id`,
`tenant_id`, `actor_id`, `revision`, `state`, `data`, `source_contract_etag`,
`review`, `review_hash`, `applied_contract_etag`, `successor_contract_id`,
`finalized_contract_etag`, `supersedes_draft_id`, `superseded_by_draft_id`,
`created_at`, `updated_at`, `persistent`. States: `draft`, `reviewed`, `confirmed`
(renewal), `pending_effective`, `completed`, `superseded`. Review includes the source snapshot,
proposed contract, known rent-period conflicts and existing obligations warnings.
Ordinary receivables due after the rental end are warnings, not proof of an
out-of-period service. Obligations are kept unchanged.

Page: `items`, `next_before` (opaque string/null), `persistent`. History items
are immutable successful command results (`operation` confirm/finalize), with
`id`, `draft_id`, `actor_id`, `created_at`, `result`, plus `current_state`,
`supersedes_draft_id`, `superseded_by_draft_id` outside that original result.

A pending termination can be explicitly superseded by a newly reviewed earlier
end date. `review.supersedes` is null or `{id, termination_end_date, review_hash}`;
the predecessor identity and proof are part of the new review hash. Confirm
atomically closes the predecessor as `superseded`, links both sides and changes
the parent. Earlier data/review/commands remain immutable. A lost-reply replay
still returns the exact original pending result. Finalize on the superseded
draft returns409 with its successor ID. Stale or simultaneous corrections
require reloading/reviewing; completed terminations cannot be superseded.

The review object contains `source_contract`, `source_contract_etag`,
`related_etags` (property/unit/tenant), `proposed_contract`, `data`, `supersedes`,
`date_policy`, `notice_policy` and `obligations`. Obligations have all-row counts
(`rent_charge_count`, `receivable_count`, `receivables_due_after_end_count`,
`rent_period_conflict_count`), at most20 example rows in the corresponding
`*_sample` arrays, `snapshot_sha256` and the explicit keep-unchanged `policy`.
The sample bound limits the response; it does not limit stored history or
silently omit obligations from the counts/hash.

Same key/payload replay returns the stored result, including after a lost reply;
different key reuse conflicts (409). Draft/source changes require reloading and
review (409/412). Inaccessible or foreign private drafts return 404, insufficient
write permission 403, malformed command 422. No automatic sending, worker or
legal validity claim.
