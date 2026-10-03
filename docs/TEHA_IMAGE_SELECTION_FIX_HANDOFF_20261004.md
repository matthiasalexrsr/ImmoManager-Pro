# Selected TEHA image: narrow correction handoff

Own base `57bdaaa`, branch `assist/teha-image-review-fixes`, checkout
`work/encrypted-runtime-factory`. No Root or Domain checkout edits.

## Actual baseline evidence

Own `0298060` contains only the pre-code plan and two actual fixture
regressions. Root integrated it as `cc2b7a6` and ran the two node IDs with the
unchanged image validator plus its separate filtered-presence change
`727195f`. Root reported both assertions failing with `DID NOT RAISE`, 1.98 s,
outer hard budget 60 s, exit 1. The real native `notnull=0/pk=1` and populated
main/empty TEMP/unqualified-empty setups succeeded before the validator call.
This confirms two product counterexamples, not two positive PASS results.
Root's artifact is `TEHA_IMAGE_SELECTION_GAPS_PRECORRECTION_cc2b7a6_20261004.xml`.

## Local product correction

`teha_receive_image_schema.py` now compares the actual `table_info.notnull`
bits with frozen column nullability. It does not infer native NOT NULL from a
VARCHAR primary key. Its local table/index PRAGMAs explicitly select main.

`teha_receive_image.py` calls `assert_main_name_binding` before schema,
History, generic originals and L2 evidence reads. The guard uses only the
existing caller connection and read-only queries. It checks the fixed L2,
History, original and parent/grant names actually read by these APIs:

- TEMP tables/views with those names refuse, including native NOCASE aliases.
- TEMP indexes aliasing main indexes on these relations also refuse, protecting
  reused unqualified index PRAGMAs.
- Only fixed main-presence facts are retained. For a relevant relation missing
  from main, a matching table/view in an attached schema refuses. Unrelated
  attachments and unrelated TEMP objects do not fail because of their number.
  Attached aliases are streamed, SQL byte-bounded and quoted as identifiers.

Failures use existing constant context/schema/budget codes. Object names,
database aliases, paths, SQL, payloads and keys do not enter errors. Deadline
checks surround queries and each streamed alias; Root continues to own native
per-statement progress cancellation. No DDL, DML, pragma change, transaction
change, key lookup or repair is added.

The two shared Presence helpers, migrations, Registry, Recovery, Settings,
Auth, startup and live TEHA commands are untouched. Root owns its separate
filtered-presence correction. This patch adds no business-row or catalog-stock
cap and silently truncates nothing.

## Exact next native acceptance

Root should repeat precisely these original counterexamples after applying the
separate product commit:

```text
tests/image/test_teha_receive_image.py::test_frozen_varchar_primary_key_requires_native_not_null
tests/image/test_teha_receive_image.py::test_empty_case_aliased_temp_shadows_cannot_hide_populated_main_image
```

Use `--noconftest -q`, a single native process and the same external 60-second
budget. The existing complete real-crypto/original-image positive case is the
smallest compatibility control. Root also owns additional context cases:
same-name TEMP view, TEMP index alias on an unrelated TEMP relation, missing
main parent supplied only by an ATTACH alias (including quoted/case aliases),
and successful images with unrelated TEMP/attached objects. These are proposed
native checks here, not asserted results or extra implemented test functions.

No Python imports, test/lint/compile, app, database, provider, server or browser
processes were started by this agent. Source/Git inspection and whitespace
checks are the only local verification. Native post-correction results remain
Root-owned and unexecuted in this checkout.

Root separately reported fresh-process import/absent-family boundary
`0745de1`: 1 PASS, 2.19 s, hard 30 s, with blocked runtime modules/factories
and preserved caller raw transaction. That narrower proof does not establish
populated crypto, full restore or this correction's context variants.
Command-digest reconstruction, populated jobs, full later receipt/reverse
batches and installed retention/transfer closure retain their existing explicit
limits; no total TEHA or A–L acceptance claim follows from this package.
