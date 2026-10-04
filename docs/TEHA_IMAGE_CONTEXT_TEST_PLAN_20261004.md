# TEHA selected image: native context-test source plan

Base: clean Root `c15310d`; own branch `assist/teha-image-context-tests`.
Only a new `tests/image/test_teha_image_context.py` and these own documents
are in scope. No existing test or product file changes. No Python import,
test, compile/lint, database, application, server or browser execution here.
Root runs the finished source package in its exclusive native slot.

## Existing evidence and contract

Root reported the two initial native counterexamples now 2 PASS / 1.20 s
after `023e072`, with import normalization `c15310d`. Separate late-batch
coverage `3514bb3` was 3 PASS / 1.25 s; fresh-import/absent-family coverage
`0745de1` was 1 PASS / 2.19 s. These are Root results, not executions here,
and do not prove the following additional context variants.

The validator owns no connection or transaction. It checks actual caller
query-only/read transaction/trusted-schema flags, native column nullability,
relevant TEMP table/view/index aliases, and missing-main ATTACH fallbacks.
Unrelated objects and attachments with duplicate names which still resolve
to main are compatible. No total schema-object or business-row cap is imposed.

## Five prepared native cases

Reuse the real explicit-key crypto/original `ImageFixture` through the ordinary
same-directory test import `from test_teha_receive_image import ImageFixture`.
The repository uses pytest's default prepend import mode; no package files,
path manipulation, runtime factory or alternate fixture implementation is added.
Each local pytest fixture closes its actual in-memory SQLite connection in
`finally`; ATTACH files are exclusively `:memory:` and close with it.

1. A TEMP index on an unrelated TEMP relation has an upper-case alias of
   `ix_teha_mapping_lookup`. Verify native main/TEMP index metadata and its
   unqualified resolution, then require exactly `TEHA_IMAGE_CONTEXT_REQUIRED`.
2. An actual period mapping references `PERIOD`. Remove only the main
   `billing_periods` relation after creating the same native parent in a quoted
   ATTACH namespace. Verify main absence and actual unqualified attached data,
   then require the same constant refusal. Mixed-case table and schema names
   plus an embedded double quote exercise actual identifier quotation.
3. An attached same-named property relation contains conflicting parent data;
   the existing main relation still wins native resolution. Require the full
   populated crypto/original image to remain valid with the original counts.
4. Unrelated TEMP table/view/index and a quoted attached data relation remain
   valid. Verify their contents are unchanged as well as the full main report.
5. Create 514 unrelated main tables, each with an index: 1,028 actual unrelated
   main catalog objects, with no oversized individual record. Count the native
   table/index objects and require the full populated image to remain valid.
   This proves absence of a 512/513 stock cap; it invents no product limit.

Every call must preserve `in_transaction`, `query_only=1`,
`trusted_schema=0` and actual `total_changes`. Capture only the validator call
and require its native trace statements to be SELECT/PRAGMA, accounting for
SQLite's optional `-- ` prefix on internally traced pragma statements.
Refusals must expose exactly the fixed code, never the quoted alias or path.
Fixture DDL/DML and ATTACH occur before read-only sealing and are not validator
actions. Positive cases verify the actual report and main source/original bytes.

## Root execution and acceptance limits

The new file contains five independent test functions, without parameter expansion.
Propose one `--noconftest -q tests/image/test_teha_image_context.py` run with an
external 90-second deadline; existing fixture calls each use a real 20-second
monotonic validation deadline. Root announces and freezes its own native run.
All five cases remain source-only until Root reports actual results; local
whitespace checks are not native or import acceptance.

No new schema, Registry, startup, Auth, Recovery, keyring or live command behavior
is activated. No command-digest, job-binding, installed retention/transfer or
complete restore guarantee follows from these context cases. The original
timestamp/production-write and personal-inbox authority boundaries stay separate.
