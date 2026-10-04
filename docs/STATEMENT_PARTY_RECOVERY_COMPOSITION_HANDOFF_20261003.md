# C: whole native party originals composed with recovery

Root's pre-code plan is `STATEMENT_PARTY_RECOVERY_COMPOSITION_PLAN_20261003`.
The actual Domain finalization/party packet is composed; no new DDL is needed.

## Actual behavior

`billing_statement_party_database` pages every native billing period, including
those with no dispute. Present party families receive the pure Domain period
proof and a hash computed from every actual statement, streamed in unchanged
canonical JSON. Parent references load through small native LRU work caches;
they never limit identities. Source statements also verify their complete
native source-period hash, including older originals without a party family.
Old periods without the family remain unchanged; malformed present originals
and partial billing tables fail. The helper has no auth, runtime, settings,
Store, storage or operational-party imports and performs no DDL or mutation.

Full backup approval, staged file proof and restored-session/worker
normalization call it before modifying state. The shared business-subset/reset
guard now protects party originals even when there are no dispute cases.
Its native SQL existence query examines the family key, including a malformed
present null value, without copying every period to application memory.
Writer barriers include the billing parents before retained child families.

The common native read helper now requests a real PostgreSQL server cursor.
Using fetchmany by itself could leave an entire result buffered in the driver;
bounded fetching now reaches that layer too. Every cursor closes on completion
or failure. Raw SQLite retains its bound-parameter read-only path.

## Actual proof

- Five composed SQLite cases passed in 31.87 seconds: whole frozen originals
  with no case after current-name edits, fresh-process import denial, actual
  raw SQLite proof, invalid identity rejected before session changes/archive
  approval, no-case subset/reset refusal, absent/partial old families, and the
  previously composed native journal original smoke. The count is five tests,
  not the number of assertions.
- Six selected cases passed in 79.92 seconds with no skips: three actual
  PostgreSQL no-case/security/subset cases, the native PostgreSQL case
  proof, and both actual encrypted full-container original/evidence roundtrips.
  The containers now contain and prove the actual frozen-party contract.
- Ruff and Mypy passed for all six changed product sources.

Logs are outside the checkout: `work/root-party-recovery-sqlite.log` and
`work/root-party-postgres-full-recovery.log`. Only owned synthetic SQLite files
and dedicated UUID PostgreSQL schemas were used. The live private preview
remains unchanged.

## Remaining composition work

The independent source-correction and rehashed missing-sibling negative cases
still need dedicated native tests, beyond Domain's pure stream counterexamples.
The shared legacy-upgrade/startup/fullbackup-runner regression must include this
new source commit. Large-period and large-history performance are unproved.
Bounded statement choices, reviewed encrypted command drafts, the pending
restore hook fix and the dispute UI remain separate work. This is not the
complete A-L product release or a private installation migration.
