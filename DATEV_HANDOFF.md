# Reviewed DATEV export workflow

`/datev` is reachable from Finance navigation and Bookings. Select a portfolio,
create a reviewed mapping version, choose the period, validate the complete
export, then download its ZIP. Bookings offers the explicit `confirmed` status;
opening an editor or creating a preview never confirms records automatically.
Saving retains the original If-Match revision. Existing linked financial history
continues to prevent changing protected booking values.

Profiles require explicit account/category/direction pairs, the actual account
type, bank G/L and general or personal counter-account numbers, adviser/client
numbers, account length and reviewer confirmation. Account types such as
Girokonto and Mietkonto work without an invented bank/cash translation. This
workflow requires EUR, calendar financial years and reviewed accounts without
automatic VAT. It does not infer VAT, default G/L accounts or invoice references,
submit anything to DATEV, or claim DATEV import certification. Optional Belegfeld1
contains either nothing or the complete internal booking ID after an explicit
profile choice; unsuitable IDs fail validation instead of being shortened.

Profile changes create immutable versions. Preview commands retain their
idempotency key after a failed request; changing the draft creates a new command.
Draft mappings and periods remain visible after server errors. Readonly accounts
can read permitted profiles/journals/downloads; financial write roles create
versions and previews. Portfolio scope independently limits all these reads.

## Published format constraints

The implementation targets EXTF 700, category 21, Buchungsstapel version 13:
31 header fields, 125 data columns, semicolons, prescribed quoted text fields,
CRLF and CP1252 without BOM. The complete export splits by financial year and
the published 99,999 booking rows per CSV. There is no application row-count or
history retention limit. DATEV's published 20xx header-date expressions restrict
this provider export to 2000–2099; other application years remain usable and can
be downloaded through the general filtered Bookings CSV export.

Nonzero amounts are checked in cents without rounding; the DATEV amount field
allows up to 9,999,999,999.99 per row. Account length 4–8 controls general-account
numbers and the additional digit allowed for personal accounts. Text, encoding,
control characters, document references and source mappings are validated without
silent replacement or truncation. An unsuitable booking returns its identifier
and concrete error code so the data or a new profile version can be corrected.

Primary sources checked on 2026-10-01:

- [DATEV format description](https://developer.datev.de/de/file-format/details/datev-format/format-description)
- [DATEV header fields](https://developer.datev.de/de/file-format/details/datev-format/format-description/header)
- [DATEV booking batch fields](https://developer.datev.de/de/file-format/details/datev-format/format-description/booking-batch)
- [Official sample ZIP](https://developer.datev.de/assets/Musterdaten_DATEV_Format_0_7f9322b9cc.zip)

The 125-column header was independently compared with the official sample,
normalized to CP1252, SHA256:
`a4c23ec4e0bf463d455ff9ebb5b2435954349b014042497114e72c1de88d8951`.

## Snapshot, persistence and recovery

The export uses one readonly repeatable PostgreSQL snapshot or explicit SQLite
read transaction, retrieving at most 1,000 source rows per SQL query. Raw
Booking/Account/Category/profile/portfolio queries receive authoritative scope
predicates. Grant, role or activation changes abort with 403, including during
source iteration and before publishing. Missing scope wiring fails closed with 503.
Complete CSVs and ZIP CRC/SHA256 checks finish in a private disk workspace before
HTTP download headers. Windows uses the existing verified private-workspace ACL
helper; POSIX uses restrictive ownership/modes. Cancellation closes the open
file before cleaning the owned workspace. Creation timestamps are explicitly
UTC so Windows does not require an OS/IANA timezone database.

The immutable journal stores manifests and stable export references, not a
permanent financial ZIP. Downloads reconstruct the original version and timestamp
and require the same complete SHA256. Export-relevant source changes return 409
and require a new preview. Keep downloaded packages when permanent external
filing is required. Each ZIP includes the validated CSV files and manifest.json;
the journal additionally records the complete ZIP SHA256 and size. Browser
downloads verify ZIP type, size and SHA256 before creating the download link.
This browser step requires WebCrypto, available with HTTPS or localhost.

Alembic `p1a2b3c4d5e6` follows portfolio scope `o1a2b3c4d5e6`. Metadata registration
supports historical create_all installations. Populated DATEV tables refuse
downgrade before DDL. Business-subset JSON replacement refuses existing DATEV
history before mutation; the complete encrypted database backup retains it.
The legacy `/reports/datev-export` returns 410 with the new workflow and general
CSV alternative instead of offering the former incomplete guessed format.

## Verification and integration

Focused tests cover official field/header evidence, real account types, late
invalid rows, subcent data, 100,001 rows across years/files, SQLite concurrent
writers, immutable/replayed references, malformed downloads, private cleanup,
HTTP financial roles, actual restricted grants/revocation, fresh Alembic
upgrade/downgrade and protected subset restore. The new dedicated PostgreSQL
gates are `backend/tests/test_datev_postgres.py`; they require
`TEST_SERVER_DATABASE_URL` and use isolated UUID schemas. Without that service
they explicitly skip; no local PostgreSQL execution is claimed.

Integrate only this DATEV package and its follow-up commit. The Bookings package
0334038 and portfolio scope core c8ad95e2 are separate prerequisites already
owned by their respective agents. Root owns app-level scope middleware/startup
wiring and CI configuration. No FormModal/ConfirmDialog edits are included.
