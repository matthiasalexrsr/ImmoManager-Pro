# PG16 CHECK source handoff: native integration remains pending

Precode contract: 6ea0cf9. Additive source, new pure tests and frozen Root
synthetic 16.15 snapshot only. Existing validator/registry/recovery/fixtures/
proposal/head are unchanged. No imports, Python, lint, tests, SQL, app, browser
or server processes were started. Git whitespace checks are source review only.

Root native entry point:

```python
from backend.services.notification_inbox_pg16_check import (
    PG16InboxCheckError,
    PG16InboxCheckLimits,
    validate_pg16_notification_identity_check,
)
```

Compose with the current complete shape/parent/data proof on the same selected
business-schema Connection and consistent catalog snapshot. False means whole
absence only, not legacy permission. A temp/other-schema visible relation does
not pass. Errors are fixed `notification_inbox_pg16_check_*` values: limits,
timeout, budget, catalog, version, unsupported tree, missing/invalid guard.
Root can map these to its existing safe schema refusal without native values.

The parser supports exactly PG16's observed 64-bit native tree: two AND leaves,
actual VARs via VARCHAR-to-text binary relabel, native length/textlen 1317,
int4gt operator/function 521/147, and the exact zero int4 Datum representation.
It checks real pg_proc/pg_operator/type/cast semantics independently of names
and reads convalidated/local/inheritance/relation/conkey metadata. conenforced
is read only when the actual catalog reports that field. Unknown major version,
ABI, node, field, boolean expression, comparison or coercion refuses.

All catalog reads target the selected family or fixed native OIDs. The 64-row
catalog result budget is for these **targeted** queries, not total schema,
constraint or function stock. Native conbin byte prefix is capped in SQL;
remaining work/deadline checks and result closure are explicit. Driver-side
I/O/lock bounds remain Root-owned. No CHECK or user callback is evaluated.

Prepared pure gate: `backend/tests/test_notification_inbox_pg16_check.py`.
The frozen snapshot is copied bytewise from Root's explicitly authorized
`artifacts/NOTIFICATION_INBOX_M2_PG16_NATIVE_CHECK_20261004.json`; all table and
constraint OIDs refer to Root's disposable synthetic schema. Parser record
projections explicitly identify additional synthetic query-format facts.
These pure inputs prove no live catalog/Connection acceptance and no pass count
is claimed. Suggested subsequent Root native cases: current M2 positive;
missing/always-true/OR/one-ID/literal/wrong-function checks; NOT VALID; wrong
visible schema/temp shadow; read-only and unchanged transaction. Root owns
their isolated schemas, connection setup, cleanup and native execution.

SQL/query compatibility and actual DBAPI returned representations still need
that native gate. System catalog/binary tampering by a superuser is outside the
declared trusted PostgreSQL runtime assumption. No write authority, M2/L2 chain
activation or startup/full-recovery acceptance is implied by this handoff.
