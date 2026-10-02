# G37/G43 independent live privacy review

Reviewed Root integration `c028e2f90d8b7f62f44ec7540a6eedc242f65b30` with the
authorized pure validator `da61a374` and live manifest followup `a9362dd`.
Only `document_versions.py`, `tenant_document_versions.py`, this handoff and
the new review tests are changed. `tenant_privacy.py`, Main, Preview and
installation data were not changed.

## Reproduced faults and correction

* A corrupt highest version stored under a different portfolio disappeared from
  scoped SQLite queries. Tenant export and normal history presented the earlier
  version as the full history; archive/upload could attempt an incorrect INSERT
  and fail with a uniqueness error. The export checks authorized graph document
  IDs before filtering. Normal operations check the already authorized document
  and its current portfolio before querying the head or claiming a command.
* A valid empty original with a corrupt extra chunk under a foreign portfolio
  appeared intact in scoped SQLite export and individual download. The central
  byte reader now checks contradictory chunk bindings before the scoped query.
  Legitimate empty originals remain supported.
* SQL `NOT IN` misses NULL while Memory membership rejects it. An actual small
  SQLite truth-table regression covers a damaged nullable historical schema;
  both privacy scope guards now explicitly reject that missing binding. Current
  production NOT NULL constraints remain intact.

The new Core queries return only an existence bit for an already authorized
document/version in the caller's transaction. They never materialize foreign
metadata or bytes. The existing typed SQL CASE/length check still bounds each
binary block to 64 KiB before DBAPI allocation. Corruption returns a neutral 503
and prevents publication/business DML; use a verified intact original backup
rather than rewriting immutable evidence to make a damaged journal pass.

## Verification

The independent tests reuse the existing real Memory/SQLite fixture and cover:
contract-only property/unit resolution; original/upload/restore links and every
original byte after source loss; exact SHA/size; metadata detachment and source
URL redaction; distinct hidden documents without portfolio/party expansion;
hidden-subject profile refusal; corrupt chain/party rejection; role, activity
and grant revocation during compilation or before the first byte; private-output
cleanup; Memory profile CAS; and SQL BLOB query bounds.

The actual full `build_api_v1` with DB-session and portfolio middleware tests
JWT authentication, current roles/grants, private download hash/length and
profile-only retention. Selected users continue to receive the existing HTTP
403 for installation administration; the internal exact-subject helper does not
override that route policy.

Commands (in the isolated worktree, repository venv):

```text
TEST_STORE_BACKEND=sql SQLITE_PERSISTENT_STORE=true ALLOW_INMEMORY_FALLBACK=false
python -m pytest backend/tests/test_tenant_document_versions_review.py backend/tests/test_tenant_document_versions.py -q --tb=short
python -m ruff check backend/services/document_versions.py backend/services/tenant_document_versions.py backend/tests/test_tenant_document_versions_review.py
python -m mypy backend/services/document_versions.py backend/services/tenant_document_versions.py --follow-imports=silent
```

The broader existing document, manifest, integration, tenant privacy and wizard
privacy selection completed with **170 passed / 9 explicit adapter skips** in
each Memory and SQLite environment before the final NULL truth-table addition.
Final focused result is **47 passed / 2 explicit adapter skips**, exit 0; Ruff on
the two services and new tests and Mypy on both services pass. No local PostgreSQL,
Linux, browser or full recovery execution is claimed by this review; those are
separate integration gates. Existing actual private-response disconnect tests
are included in the broader selection.
