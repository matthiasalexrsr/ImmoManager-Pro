# AI UTF-8 keyword regression fix handoff

Parent: `fa12ef7c10ef1c72dd1e899dc080c21fea6a3a05`  
Branch/Worktree: `assist/ai-complete-extraction` / `work/ai-complete-extraction`

This follow-up is intentionally narrow.

## Corrected

Only `backend/services/ai/message_ai.py` was corrected in production code:

- removed the UTF-8 BOM;
- restored the three action-item keywords to normal UTF-8:
  - `überweisen`
  - `prüfen`
  - `klären`
- no other keyword, algorithm, DTO, router, auth, OCR, recovery, schema or
  workflow behavior was changed.

The previous bytes contained the double-decoded spellings
`Ã¼berweisen`, `prÃ¼fen`, `klÃ¤ren`. The final file decodes as plain
UTF-8 without BOM and contains each corrected keyword once, with zero remaining
occurrences of the three mojibake variants.

## Regression test

`backend/tests/test_ai_extraction_review_fixes.py` adds
`test_action_item_unicode_keywords_and_message_ai_source_encoding`.

It verifies both source encoding and business behavior:

- source file does not start with `EF BB BF`;
- the three correct UTF-8 keywords are present;
- the three mojibake spellings are absent;
- three separate synthetic sentences
  `Bitte überweisen. Bitte prüfen. Bitte klären.`
  produce exactly three action items and each keyword is recognized.

No private data, live provider, model download or external message is used.

## Gates run

Focused review tests:

`pytest backend/tests/test_ai_extraction_review_fixes.py -q -rs --tb=short`

Result: **10 passed**.

Existing AI/integration suite:

`pytest backend/tests/test_ai_services.py backend/tests/test_ai_full_text.py backend/tests/test_ai_extraction_review_fixes.py backend/tests/test_integration_manager.py backend/tests/test_integrations_router.py -q -rs --tb=short`

Result: **63 passed**, with one pre-existing Starlette TestClient deprecation
warning.

Static gates:

- Ruff on the changed service/test: passed.
- configured Mypy on `message_ai.py`: **Success: no issues found in 1 source file**.
- `py_compile`: passed.
- `git diff --check`: passed.
- direct byte check: `bom False`, correct keyword counts `[1,1,1]`,
  mojibake counts `[0,0,0]`.

No Wohnungsgeberbestätigung architecture/schema work was started.
