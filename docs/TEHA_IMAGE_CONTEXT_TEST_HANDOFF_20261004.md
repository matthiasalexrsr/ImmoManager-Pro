# TEHA selected image: additive native context tests

Base `c15310d`, branch `assist/teha-image-context-tests`, own checkout
`work/encrypted-runtime-factory`. Pre-code plan is `06acd6b`. The following
source commit adds only `tests/image/test_teha_image_context.py` and this own
handoff. Existing test sources and all product/shared files remain byte-identical.

## Exact five prepared node IDs

```text
tests/image/test_teha_image_context.py::test_ascii_temp_index_alias_of_relevant_main_index_is_refused
tests/image/test_teha_image_context.py::test_missing_main_period_parent_supplied_by_quoted_attach_is_refused
tests/image/test_teha_image_context.py::test_same_named_attach_relation_with_existing_main_remains_compatible
tests/image/test_teha_image_context.py::test_unrelated_temp_and_quoted_attach_objects_remain_compatible
tests/image/test_teha_image_context.py::test_more_than_513_unrelated_catalog_objects_remain_compatible
```

The new file imports the existing real-crypto/original `ImageFixture` through
the ordinary same-directory test import, with no new path/package infrastructure.
Each case gets its own native `:memory:` main connection and closes it in
`finally`. Attachments also use only `:memory:`, with a native database-list
assertion that the exact selected alias has an empty file path. The cases use
actual SQL and PRAGMA results before the validator invocation, not fake cursors,
auth DTOs, metadata mocks or helper-only code assertions.

- The TEMP index has the upper-case native name `IX_TEHA_MAPPING_LOOKUP` on
  an unrelated TEMP table. The main index remains on the L2 mapping relation.
  Actual unqualified index_info returns the TEMP column rather than main's
  four lookup fields before constant-code refusal is required.
- The missing-main case adds an actual period mapping, supplies its real
  parent only from attached `Incoming "ArChIvE"` / `BiLlInG_PeRiOdS`, and
  proves native main absence and unqualified attached resolution. This makes
  the production alias-quoting branch traverse an embedded double quote.
- The existing-main case stores a conflicting same-named attached property
  parent. Actual unqualified resolution still returns the main portfolio, and
  the complete crypto/original image must stay valid.
- The irrelevant-object case adds a native TEMP table/view/index and a quoted
  memory attachment with independent data. Complete validation must preserve
  those values and the main image.
- The large-stock case creates exactly 514 unrelated main tables and 514
  indexes, verifies both native counts, and requires compatibility. Individual
  records remain small; 1,028 unrelated catalog objects impose no product cap.

Every actual validator invocation, including expected refusals, asserts native
`query_only=1`, `trusted_schema=0`, open caller transaction, unchanged
`total_changes`, and byte-identical main immutable manifests/original chunks.
Native trace statements are SELECT/PRAGMA only (including SQLite's optional
internal `-- ` trace prefix). Refusals expose exactly the fixed code. Positive
cases require actual family presence and counts `(1,1,1,0)` while retaining
`command_digest_reconstructed=False`.

## Execution ownership and limits

Proposed single Root-owned gate, repository-default pytest prepend mode:

```text
python -m pytest --noconftest -q tests/image/test_teha_image_context.py
```

The five functions are not parametrized. Use one native process, an external
90-second hard deadline and each existing fixture's actual 20-second monotonic
validation deadline. Root should freeze merged sources, execute and record
native outcomes before treating any of these prepared assertions as passed.

This agent started no Python/import, test/lint/compile, database, app, server,
provider or browser process. Only source/Git operations and whitespace checks
occurred. No new PASS, native collection or runtime-import proof is claimed.
Root's previously reported two original counterexample successes, three late-
batch cases and one fresh-import/absent-family case remain separate evidence.
This package adds no write/CommitAuthority, command-digest reconstruction,
populated job proof, Registry/migration, installed retention or complete restore
acceptance. No private installation or original database was accessed.
