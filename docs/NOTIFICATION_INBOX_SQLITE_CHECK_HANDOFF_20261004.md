# SQLite CHECK source handoff (no execution evidence)

Precode plan: 469e62a, with the source-order clarification that bounded namespace
reads also require length/substr binding proof first. New source and new test
file are additive; existing inbox validation/registry/recovery remain bytewise
untouched by this package. No import, lint, Python, test, app, DB or server
process has been started. Only source reading and Git whitespace checks ran.

Root entry point:

```python
from backend.services.notification_inbox_sqlite_check import (
    SQLiteInboxCheckError,
    SQLiteInboxCheckLimits,
    validate_sqlite_notification_identity_check,
)
```

Compose after the existing complete shape proof, on the **same** actual SQLite
connection/schema snapshot, before accepting the schema/data proof. Retain
exclusive connection use during the complete check. Map SQLiteInboxCheckError
to the existing fixed inbox schema refusal; do not expose driver values. False
is only whole main-family absence, never standalone authorization of an old
archive. The root proof must retain its parent/FK/PK/timestamp/data checks.

Defaults after the streaming correction: 65536 DDL/parser bytes, 4096 tokens,
64 nesting, 32 native catalog rows **per fetch batch**, with no total stock cap.
Only relevant matches are retained. Higher positive profiles are supported explicitly. Driver I/O and lock
deadlines are external; service deadlines check native calls and parsing work.
There is no DML probe or enforcement reset. No function callback is invoked to
prove semantics. Unknown syntax or registered overrides refuse. The service
does not prove writability, Sid/account/parent fences or CommitAuthority.

Prepared tests: `backend/tests/test_notification_inbox_sqlite_check.py`, with
real raw sqlite3 and SQLAlchemy Connection cases plus narrow pure parsing
counterexamples. Suggested first actual Root gate is this file only, under its
normal source freeze and process budget; **counts and passes remain unproved**.
The old strict-xfail gap cases are intentionally unchanged and remain against
the old validator until Root composes and revalidates it.

Normal temporary/user triggers, extra constraints, arbitrary SQL equivalence,
virtual/generated identity columns and noncanonical table suffixes are outside
this narrow proof. Required guard expression supports only the declared AND
of the two actual length checks; accepted extra constraints cannot weaken it.
Trusted native SQLite and an authentic, consistently loaded schema are caller
assumptions, not a promise to authenticate arbitrary writable_schema tampering.

PostgreSQL is a separate follow-up against Root's real 16.15 catalog snapshot;
this source proves no PostgreSQL CHECK semantics and activates no migration.
