# Selected TEHA image: native nullability and name-binding correction

Base: clean Root `57bdaaa`, own branch `assist/teha-image-review-fixes`.
This is the pre-code plan for the two independently reviewed source gaps.
Root owns every native run and the shared Presence helpers. No Python import,
test, database, application, server or browser execution is authorized here.

## Source counterexamples before product changes

The frozen L2 string primary keys are explicitly non-null. The shared SQLite
schema helper currently infers non-null from either the native `notnull` bit
or the primary-key bit. SQLite ordinary VARCHAR primary keys do not themselves
imply NOT NULL. The image-specific verifier checks types but does not correct
that distinction. A fixture which removes only `id VARCHAR NOT NULL` from the
mapping DDL, keeping `id VARCHAR`, its primary key, populated normal rows,
constraints, indexes and guards, cannot currently be distinguished.

The image-specific DDL queries inspect the main catalog, but reused schema,
History and original validators and L2 data queries resolve unqualified names.
SQLite resolves TEMP before MAIN. A caller transaction with empty, identically
shaped TEMP tables for both L2 tables and document versions/chunks can retain
the populated main image and its immutable guards while scanning empty TEMP
data. `query_only=ON`, `trusted_schema=OFF` and a read transaction do not prove
that those names resolve to the selected main image.

Official native semantics: [SQLite primary keys](https://www.sqlite.org/lang_createtable.html#the_primary_key)
and [database object name resolution](https://www.sqlite.org/lang_naming.html).
These are source counterexamples; they have not been executed in this slot.

## First commit: actual fixture regressions, unchanged product

Extend only the existing isolated image test fixture and add these two node IDs:

```text
tests/image/test_teha_receive_image.py::test_frozen_varchar_primary_key_requires_native_not_null
tests/image/test_teha_receive_image.py::test_empty_case_aliased_temp_shadows_cannot_hide_populated_main_image
```

The first asserts actual PRAGMA `notnull=0`, `pk=1` and a normal populated
mapping before expecting `TEHA_IMAGE_SCHEMA_INVALID`. It does not insert a null
row: a data failure must not substitute for the missing schema proof.

The second first installs real main guards, then creates empty TEMP tables
from the actual main DDL, with identical L2 indexes. Mixed/upper-case names
exercise SQLite's native ASCII case-insensitive identifier resolution. Explicit
main and temp counts prove that populated main evidence still exists and that
the shadows are empty before requiring `TEHA_IMAGE_CONTEXT_REQUIRED`.

Root can run the two node IDs on this commit with the unchanged product,
`--noconftest`, one process and an external 60-second budget. Expected source
baseline is two refusal-assertion failures; actual results belong to Root.
Then Root can apply the separate product commit and repeat the same node IDs.
There are no PASS claims, imports or test starts here.

## Second commit: smallest local product correction

Only `teha_receive_image_schema.py` and `teha_receive_image.py` change:

1. Compare native `table_info.notnull` separately with every frozen column's
   `nullable` contract. Qualify the local schema PRAGMAs to `main`. Do not infer
   VARCHAR non-nullability from its primary key or modify the shared helper.
2. Before any schema, History, original or evidence read, reject actual TEMP
   table/view shadows of the fixed relation names used by these APIs. Also
   reject TEMP index aliases of main indexes on those relations, because
   reused unqualified index PRAGMAs have the same resolution issue. Native
   NOCASE matching covers ASCII identifier aliases rather than exact spelling.
3. Reject an ATTACH fallback only where a relevant relation is absent from
   main and a same-named table/view in an attached schema could supply it.
   Unrelated TEMP objects and attached databases are not stock-size limits.
   Main presence results have only the fixed target cardinality; attached
   aliases are streamed, SQL byte-bounded and safely quoted. No full catalog
   is transferred, no arbitrary catalog count or business-row cap is added.

Every guard is SELECT/PRAGMA-only on the existing caller connection. It changes
no pragma, transaction, keys, provider configuration, schema or original bytes.
Use existing constant `TEHA_IMAGE_CONTEXT_REQUIRED` and schema failure mapping;
never include object names, aliases, paths, key values or SQL in diagnostics.
Keep explicit deadline checks around the guard queries; Root continues to own
per-statement SQLite progress-handler cancellation.

## Root-owned composition and remaining limits

Root separately fixes filtered presence reads in
`backend/db/teha_receive_schema.py` and
`backend/services/document_version_validation.py`; neither file is edited here.
Shared Recovery, Registry, migration, Auth, startup and live TEHA commands remain
unchanged. The closed job binding and unreconstructed command-digest boundaries
remain unchanged. Full receipt/reverse-closure later-batch native gates and a
fresh-process import-boundary gate remain separate unexecuted acceptance work.
The two fixture regressions do not prove these unrelated boundaries or a full
restore composition. Attach fallback and TEMP index alias refusals additionally
need Root's native source-focused cases before claiming those native guarantees.
