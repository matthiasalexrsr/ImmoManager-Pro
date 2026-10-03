# SQLite CHECK streaming correction before source

Root's static review identified a real artificial total-stock limit in
c9184c3: `_rows` buffered the complete native function/main/temp catalog and
rejected row 513. Valid independent objects/functions cannot invalidate the
inbox guard. No Root wiring or native execution has occurred yet.

Change only own new SQLite service/tests/docs. Replace total catalog_rows with
positive configurable batch_rows (default 32). Context-managed catalog cursors
stream batches, check the real deadline on each item, and close on early refusal
and native failure. Aggregate only two builtin signatures, two required columns
and at most the main/temp family matches; never buffer unrelated catalog stock.
Single-valued PRAGMA/DDL reads have explicit at-most-two-row result checks, not
a configurable database-wide object threshold. Namespace names remain capped
BLOB reads after verified length/substr binding; per-record DDL bytes/depth/
tokens remain unchanged. Native driver I/O limits remain Root-owned.

Prepared synthetic cases must accept 513 unrelated indexes and 513 unrelated
registered functions, including batch_rows=1, without invoking their callbacks.
Expired real deadlines still refuse before a native call. No test run is part
of this source correction; Root obtains actual native results later.
