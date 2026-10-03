# PG16 native identity CHECK: source contract before code

Root explicitly authorized this separate source adapter after supplying its
real PostgreSQL 16.15 snapshot (server_version_num 160015), following five
actual M2 Operations passes on Root 3c96be9. This package runs no imports/tests,
SQL, servers or processes and changes no shared validator/registry/migration.
The existing PG fixture remains untouched; Root owns its native address fix.

New source: `backend/services/notification_inbox_pg16_check.py`; new prepared
tests and a small frozen **synthetic** conbin fixture derived from that snapshot.
Root will independently prepare/run native positive and negative gates.

## API and trust boundary

`validate_pg16_notification_identity_check(connection, *, limits=None,
deadline=None) -> bool` requires a real SQLAlchemy PostgreSQL Connection. It is
construction-free and only queries catalogs on this passed connection. Caller
owns one consistent catalog snapshot and its correct business-schema selection.
False is whole absence in that schema, not authorization of a legacy archive.
The visible unqualified table must be exactly that selected schema's native
relation; temp/search-path shadowing, views, partitioned/inherited tables and
system schemas refuse. Existing complete shape/parent/data proof stays required.
No begin/commit/rollback/settings/DDL/DML or stored-expression evaluation occurs.

Only PostgreSQL **16** node-tree ABI is accepted. Native sample was 16.15, 64-bit;
the zero int4 Datum payload accepts exactly the observed eight all-zero bytes.
Other ABI/nodes/fields/representations refuse with fixed safe codes, including
future major versions. This is intentionally not a general pg_node_tree parser.
Minor-version field changes also refuse unless reviewed explicitly.

Limits are positive immutable ints excluding bool: 65536 native-tree bytes,
8192 tokens, nesting 64 and 64 relevant catalog rows. Larger explicit profiles
are supported. Check remaining time before/after reads and iterative parse;
caller still owns driver I/O/lock timeout. Cursors always close. Returned native
tree is a bounded byte prefix plus actual UTF-8 byte count in the same query;
over-budget refuses before parsing, never transfers full conbin blindly.

## Catalog and expression contract

Resolve current business namespace, exact native relation OID and visible
relation OID. Require an ordinary permanent/unlogged table, no inheritance or
partitioning. Bind actor_id/notification_id to two different positive attnums,
ordinary NOT NULL non-dropped VARCHAR (1043) columns with actual typmod/collation.
No column-name-only or caller DTO substitutes for those catalog bindings.

Find exactly one CHECK named ck_notification_read_identity on this exact
relation/namespace, validated, local, nondeferrable and not inherited. Require
conkey to be exactly the two actual attnums; contypid/confrelid zero. Detect
conenforced through real pg_attribute first; if the native catalog exposes it,
the actual flag must be true. PG16 normally does not expose this column.

Tokenize bounded native conbin and parse containers iteratively. Allow only the
observed strict fields of BOOLEXPR, OPEXPR, FUNCEXPR, RELABELTYPE, VAR and CONST;
reject duplicate/unknown fields, malformed containers, quoted/unrecognized
atoms and unsupported node tags. Location fields are integers, semantically
irrelevant. The entire tree, not a substring, must be consumed.

Exact root is BOOLAND with exactly two OPEXPR children, in either order:

- operator OID 521, function OID 147, boolean result 16, not set-returning,
  zero output/input collations, exactly two arguments;
- left is FUNCEXPR 1317, int4 result 23, scalar/nonvariadic/explicit-call format,
  zero result collation, input collation equal to the bound column;
- its only argument is binary RELABELTYPE to text 25, typmod -1, implicit
  coercion format 2 and identical collation;
- underlying VAR is relation varno 1, varlevelsup 0, exact actual attnum/type/
  typmod/collation, matching syntax-origin varno/attnum and empty nulling bitmap;
- right is non-null by-value int4 CONST 23, len 4, typmod -1, collation zero,
  native length 4 plus exactly eight zero payload bytes. NULL/one/reversed
  operands/other comparisons/OR/partial or duplicate columns all refuse.

Independently bind actual referenced catalog semantics: operator 521 is
pg_catalog.>(int4,int4)->bool with procedure 147; actual pg_proc rows 147 and
1317 are pg_catalog internal immutable strict scalar functions, exact argument/
result OIDs, native prosrc int4gt/textlen, no security-definer or proconfig.
Verify the actual base type records (bool/int4/text/varchar), and binary implicit
pg_cast varchar->text. A user-defined same-spelled function/operator cannot pass
because conbin's actual OID and its real catalog definition are both checked.
Core PostgreSQL/system catalogs are trusted; superuser binary or catalog
tampering outside these checked fields is outside the proof's threat model.

## Primary evidence

PG16 [pg_constraint](https://www.postgresql.org/docs/16/catalog-pg-constraint.html)
defines conbin as internal pg_node_tree and convalidated/conkey/relation binding;
rendered pg_get_constraintdef is useful for display, not this semantics proof.
[pg_proc](https://www.postgresql.org/docs/16/catalog-pg-proc.html) and
[pg_operator](https://www.postgresql.org/docs/16/catalog-pg-operator.html) define
function/operator identities. [Native expression structures](https://raw.githubusercontent.com/postgres/postgres/REL_16_STABLE/src/include/nodes/primnodes.h)
define VAR scope, coercion, constant and boolean fields. The
[PG16 function catalog source](https://raw.githubusercontent.com/postgres/postgres/REL_16_STABLE/src/include/catalog/pg_proc.dat)
confirms OIDs 1317/textlen and 147/int4gt rather than guessing their semantics.

## Prepared evidence and remaining integration

Pure tests parse the actual native sample and meaningful mutations: OR,
unvalidated/disabled catalog flags, wrong scope/attnum, literal/nonzero/null,
wrong function/operator/coercion, duplicate fields, unknown nodes and budgets.
These tests cannot substitute for Root's independent native catalog queries.
Root owns native schemas/fixtures/timeouts, actual positive and catalog-negative
gates, mapping fixed errors and eventual composition on the same connection.
Source-only code and test preparation are not a pass count or M2 activation.
