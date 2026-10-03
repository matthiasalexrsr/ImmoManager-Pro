# SQLite identity CHECK: source contract before implementation

Scope: a new independent `backend/services/notification_inbox_sqlite_check.py`
and new tests only. The existing inbox validator, active migrations, registry,
startup, recovery, authentication and portfolio authority are unchanged. Root
will compose the check after reviewing this source and obtaining native gates.
This work starts no imports, tests, application or database processes.

## API and caller obligations

`validate_sqlite_notification_identity_check(connection, *, limits=None,
deadline=None) -> bool` accepts a real raw sqlite3 connection or SQLAlchemy
SQLite Connection. It returns false only when no main-schema object with the
family name exists, and otherwise returns true only after the checks below.
It raises `SQLiteInboxCheckError` carrying only a fixed code. A differently
cased family object or a view is damage, not an absent legacy family.

Root must retain its current complete shape/parent/data proof. This additional
proof is neither a capability to write nor a commit authority. The caller owns
a consistent schema snapshot and exclusive use of the connection during the
proof, including native function registration and connection PRAGMA settings.
The service neither begins nor ends a transaction, changes settings, installs
functions, repairs schema, nor performs DDL/DML. Driver/lock I/O deadlines remain
the caller's responsibility; monotonic checks bound the work between native
calls and before/after parsing.

Limits are immutable positive integers (excluding bool), configurable without
an arbitrary maximum: DDL bytes 65536, tokens 4096, nesting 64, catalog rows 512.
Catalog fetches are bounded and cursors closed on every outcome. Namespace
enumeration is limited metadata, never a notification/read-state stock scan.

## Native evidence and ordering

1. Read bounded main/temp object-name metadata. Match SQLite's ASCII identifier
   case rules in Python. Reject a temp shadow, wrong-cased main object, view or
   multiple matches; only whole absence returns false.
2. Require exactly one native `PRAGMA ignore_check_constraints` value equal to
   integer zero. Missing/unknown pragma or enabled bypass refuses without reset.
3. Read the complete bounded native `PRAGMA function_list`. Require scalar
   built-in length/1 and substr/3, with deterministic and innocuous flags.
   Refuse any connection function of the same name with matching arity or -1,
   even if a built-in row is also present. Other fixed arities do not bind these
   calls. The substr check protects the bounded metadata read itself. No user
   callback is evaluated as a purported semantics test.
4. Only after that binding proof read native DDL in one query as byte length
   plus a capped BLOB prefix, using the verified length/substr functions.
   Read database encoding (UTF-8/UTF-16le/UTF-16be), decode strictly and also
   enforce the UTF-8 parser-byte budget. Reject over-budget or inconsistent
   length; never read the uncapped DDL into Python first.
5. Native main.table_xinfo must bind both required identifiers to real,
   ordinary, NOT NULL text/VARCHAR columns. This prevents double-quoted
   identifier fallback from turning a missing column into a string literal.
6. Parse the full CREATE TABLE header/body using a bounded tokenizer and
   balanced-parenthesis map. Only one named **table** constraint
   ck_notification_read_identity is accepted. Comment/string/name substrings
   never count as CHECKs. The ordinary main table and optional final semicolon
   are supported; virtual/CREATE-AS/unknown suffixes refuse.
7. Parse its expression into an iterative AST: parenthesized expressions,
   length(real identifier), decimal integer zero, greater-than and AND only.
   Require exactly two leaves, one `length(actor_id)>0` and one
   `length(notification_id)>0`, in either order. Quoted identifiers, whitespace,
   comments and harmless grouping are allowed. OR, literals as arguments,
   casts, COLLATE, CASE, unknown functions/operators and partial guards refuse.
   Additional unrelated constraints cannot weaken this guard and are outside
   this narrow AST contract. This is not a general SQL-equivalence parser.
8. Recheck active setting/function bindings after parsing; caller exclusivity
   remains required. No permanent binding or lifetime-fence claim is made.

Codes distinguish invalid limits, timeout, metadata budget, native catalog,
disabled CHECKs, unsafe function binding, unsupported syntax, missing guard and
invalid guard. SQL, paths, IDs and driver exception values are never emitted.

SQLite documents connection-local function signatures and the CHECK bypass in
[PRAGMA documentation](https://www.sqlite.org/pragma.html), function overloading
by arity in [create_function](https://www.sqlite.org/c3ref/create_function.html),
and the flags in [function flags](https://www.sqlite.org/c3ref/c_deterministic.html).
The native [pragma implementation](https://raw.githubusercontent.com/sqlite/sqlite/master/src/pragma.c)
enumerates built-in and connection functions separately; a built-in row alone
therefore does not prove absence of an override.

## Prepared tests and handoff boundaries

New tests use synthetic in-memory schemas only. They include canonical and
quoted/grouped checks, native missing/true/OR/one-ID/literal counterexamples,
disabled enforcement, registered scalar/variadic/aggregate overrides (callback
must stay uncalled), bounded DDL/token/depth/catalog refusal, malformed input,
UTF-16 DDL, a temp shadow, SQLAlchemy Connection and read-only/transaction
preservation. No test success is claimed before Root actually executes them.
Existing strict-xfail tests against the old validator remain open until Root
wires the additional proof and obtains its actual composite gate.

## Separate PostgreSQL follow-up

Root supplied actual PostgreSQL 16.15 source snapshot
`artifacts/NOTIFICATION_INBOX_M2_PG16_NATIVE_CHECK_20261004.json`: the real guard
is BOOLAND of two int4 > zero calls, with pg_catalog.length(text) and native
VARCHAR-to-text RELABELTYPE arguments. That snapshot guides a separate bounded
PG16 node-tree adapter, after this SQLite source. No rendered-expression regex,
hardcoded constraint-name-only acceptance or DML probe is sufficient.

The adapter will read validated CHECK/actual relation and attribute OIDs,
conkey, native conbin and referenced pg_catalog operators/functions/types from
the same connection/snapshot; verify exact version ABI and each semantic node;
and reject unknown nodes/fields. `conenforced` is checked only if the actual
catalog exposes it (PG16 has no such column). Root retains runtime integration
and will prepare actual PG positive/negative gates. See official
[PG16 pg_constraint](https://www.postgresql.org/docs/16/catalog-pg-constraint.html),
[pg_proc](https://www.postgresql.org/docs/16/catalog-pg-proc.html),
[pg_operator](https://www.postgresql.org/docs/16/catalog-pg-operator.html), and
[native expression nodes](https://raw.githubusercontent.com/postgres/postgres/REL_16_STABLE/src/include/nodes/primnodes.h).

No migrations, schemahead changes, historical catalog mutations, write actions
or CommitAuthority changes are included.
