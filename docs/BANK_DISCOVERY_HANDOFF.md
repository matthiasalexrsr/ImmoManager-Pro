# Bank original discovery

Plan before implementation (base 92c30c9, isolated assist/bank-discovery):

- Build a private, transient, complete JSONL artifact from the existing bank source chunks. No new persistent original, cache or journal family.
- Bind the manifest to import ID, source SHA256/byte length and mapping hash. Keep the staged business state, rows, receipts and bookings unchanged, including invalid imports.
- CSV: preserve duplicate header occurrences, every column and every physical/logical record, decoded values and exact raw lexemes. Positions distinguish zero-based source bytes (including BOM) from zero-based decoded characters (excluding BOM), and one-based physical lines.
- MT940: preserve every tag occurrence, continuation and other source content, including unknown fields. Observe available raw regex fields without running business conversion or bank-data loggers.
- Prepare to EOF and publish only after validation. A footer reports actual counts and completeness. Decode/CSV syntax failures explicitly mark structured parsing incomplete and include all original bytes as positioned base64 records; they never claim successful business parsing.
- Configurable positive record/field, temporary-byte and elapsed-time budgets refuse the whole artifact with actionable resource errors, never a successful sample. No total row cap.
- Reuse PrivateDownloadResponse cleanup and fresh bank account/import authority after preparation, before response start and before each later byte range. Revalidate the bearer session too. Only the owned protected temporary workspace is removed.
- Tests use synthetic CSV/MT940 and isolated Memory/SQLite, optional dedicated PostgreSQL. Cover duplicate/unknown/late values, invalid-business originals, malformed/decode evidence, source corruption, revocation and cleanup. No live-bank access.

## API and integration

`GET /api/v1/bookings/imports/{import_id}/discovery` is an additive authenticated, account/portfolio-scoped read. Existing readonly readers may download it. No new startup, metadata, migration, recovery, retention or frontend hook is needed: the bank-import router is already registered, and the original schema is unchanged. The only Settings additions are these operator-controlled positive technical budgets:

| Environment field | Default | Meaning |
| --- | --- | --- |
| `BANK_DISCOVERY_RECORD_MAX_CHARS` | 8 Mi characters | One CSV logical record or MT940 field/unassigned segment |
| `BANK_DISCOVERY_FIELD_MAX_CHARS` | 1 Mi characters | One decoded CSV value or MT940 raw field |
| `BANK_DISCOVERY_TEMP_MAX_BYTES` | 2 GiB | Combined protected source spool and complete JSONL artifact |
| `BANK_DISCOVERY_TIMEOUT_SECONDS` | 120 | Complete preparation elapsed-time budget |

The byte/character budgets reject booleans and non-integer numbers; elapsed time must be positive and finite. These limits never silently truncate data and introduce no total record-count ceiling. An oversized record, field, temporary artifact or elapsed run returns an explicit `BANK_DISCOVERY_*` 422 error with an adjustment/retry direction. Integrity failures return 409; missing/foreign objects 404; changed grants 403; expired/revoked authentication 401.

The response is `application/x-ndjson`, private/no-store/nosniff, fixed safe filename `bank-discovery.jsonl`. Headers give complete size, artifact SHA256, original SHA256 and mapping hash. Each prepared source chunk is independently checked against the fresh account/import binding; SQL checks its length before loading its BLOB, and validates consecutive chunk numbers, exact byte count, SHA256 and absence of extra/negative chunks. Mapping content is rehashed. The finished response uses the existing `PrivateDownloadResponse` cleanup, fresh bank authority and bearer checks after preparation, immediately before headers, before worker reads and again before forwarding each nonempty ASGI body. Source transactions/scopes are closed before streaming yields. Revocation aborts the stream; a consumer must require the declared byte length/hash and final EOF record.

Temporary directories reuse `private_workspace`: verified Windows ACL, POSIX owner-only directory, exclusive files (0600 on POSIX). Neither successful, denied, failed-to-send nor resource-failed requests retain an artifact cache. Cleanup removes only the exact owned directory; no database mutation or original replacement occurs.

## JSONL interpretation

1. `manifest`: original/import/mapping identity, unchanged staged `business_state`, actual encoding/mapping, parser/version policy. The raw capture observer uses the installed `mt-940` regex group definitions; no amount/date conversion or MT940 logger invocation.
2. `encoding`: concrete UTF-8/UTF-16 endianness/CP1252 and BOM byte length.
3. Every `csv_header`/`csv_record` contains its raw record, logical ordinal, original position and indexed `cells`. Duplicate names stay separate. Each cell exposes its untrimmed decoded `value`, exact `raw_value` lexeme and byte/character/line span; surplus/missing business columns are not discarded. Blank and multiline records remain reconstructable.
4. Every `mt940_tag` exposes tag/ordinal, raw text, unchanged value including original line endings, position and every available named regex raw capture with its own position. Unknown/unmatched tags remain complete raw values. `mt940_unassigned` retains envelopes, trailers and other content; the ordered raw records reconstruct the decoded source.
5. A malformed encoding/CSV yields `parser_error` plus every `raw_source_chunk` as base64 with exact byte spans. CSV error position is explicitly the first affected logical record; decoding error byte position is exact. The raw chunk sequence reconstructs the original bytes including BOM. No guessed replacement characters, repaired format or successful prefix claim.
6. Final `eof` repeats source/import/mapping identity, `original_complete`, `parser_complete`, actual parsed evidence counters and `records_sha256` over all preceding exact JSONL bytes including newlines. On parser failure counters describe only the parsed prefix; base64 records provide the entire original.

`parser_complete` means the discovery reader reached EOF. It is **not** successful business validation, a DATEV/MT940 certification or permission to publish bookings. A CSV with duplicate headers and an MT940 file with unknown tags can be fully inventoried while their staged business state remains `invalid`. All existing BankRow errors, mapping rules, reviewed/confirmed receipts and allocations stay unchanged.

Primary library references: [MT940 tag parser API](https://mt940.readthedocs.io/en/stable/mt940.tags.html), [official source](https://github.com/wolph/mt940). Library version is included in the manifest; raw tag data remains authoritative even when no regex projection matches.

## Verification

Only synthetic originals, isolated local databases and dedicated random PostgreSQL schemas are used. No Preview/user database, live bank, external send or browser was touched. Exact executed gate totals are recorded in the final handoff message.

Final-source checks (02.10.2026): focused suite under `TEST_STORE_BACKEND=sql`: **58 passed / 1 explicit skip** (the optional PG test had no URL in that process). The same PostgreSQL test was then executed against the authorized dedicated local test service: **1 passed**, random schema only. Changed-source Ruff, three-source Mypy, Python compilation and Git whitespace checks pass. A broader preceding compatibility run passed all **64 existing** bank cases with four expected legacy-store skips; its one earlier synthetic admin-grant fixture failure was corrected to use an independent administrative context and passed both independently and in the final focused run. That earlier broad process is not presented as an entirely green final-source combined run.

Important publication regression: `test_token_change_between_worker_read_and_asgi_send_publishes_no_private_buffer` runs for Memory and SQLite. It revokes the actual bearer after a successful worker-read authorization but before ASGI forwarding, then asserts that only response headers were sent, no private body escaped and the protected temporary directory was removed.

Additional real HTTP/ASGI cases cover private readonly download, fresh grant changes after complete snapshot construction, revocation before first header/after first byte range, account reparenting outside an old identity cache, header-send failure and cleanup. Source tests cover 602 transaction rows with duplicate header names, non-ASCII/BOM/UTF-16 byte-vs-character offsets, multiline/escaped values, unknown MT940 tags and discarded raw fields, corrupt/extra/oversized source chunks, resource errors, malformed retained originals and already committed imports without another booking.

Line spans are cursor boundaries: after a terminal CR/LF, `line_end` points to the next one-based line, rather than naming an inclusive last physical line. Byte and character end positions are exclusive. CSV `column_index` is zero-based and logical `ordinal` includes the header and blank records.

Run local focused suite: `python -m pytest backend/tests/test_bank_discovery.py -q`. PostgreSQL gate: set `TEST_SERVER_DATABASE_URL` to a dedicated test service, then run `python -m pytest backend/tests/test_bank_discovery_postgres.py -q`. Its fixture creates and drops only its random `immo_private_<UUID>` schema. Broader compatibility gate uses the existing `test_bank_imports.py`, `test_bank_imports_http.py`, `test_bank_import_download.py` and `test_bank_import_guards.py`. No CI file was changed.
