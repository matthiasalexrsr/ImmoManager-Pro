# Local iCalendar export

Endpoint: `GET /api/v1/calendar/export.ics?portfolio_id=<id>`.

The endpoint is read-only and authenticated. It uses the same live portfolio scope as
ordinary calendar reads. A selected-portfolio user receives 404 for a foreign portfolio.
The export is fully assembled before the response is published and the captured scope is
revalidated afterwards, so a grant change aborts with 403 instead of returning an old
calendar.

## Snapshot and private download

The HTTP response never streams directly from the database. `prepare_calendar_download`
uses the same private-export primitives as the existing DATEV/tenant exports:
`CompiledExport`, `private_workspace`, `protected_new_file` and
`PrivateDownloadResponse`.

There is no calendar-row limit. `ICAL_BATCH_SIZE` limits only one in-memory page:

- the memory reference backend holds the existing store lock for the complete private
  compilation and selects bounded keyset batches; calendar create/update/delete use that
  same mutation lock, so a concurrent create cannot modify `raw.values()` mid-export;
- SQLite uses one explicit read transaction, established before event paging;
- PostgreSQL uses one `REPEATABLE READ`, read-only snapshot;
- SQL events are fetched by `(event_date, COALESCE(event_time,''), id)` keyset batches,
  never by OFFSET and never as one complete list.

The portfolio row (including its timezone) and all exported events come from that same
snapshot. Concurrent ordinary data changes therefore cannot produce a mixed file.
Portfolio grants are different: the captured live authorization is rechecked before the
snapshot, between batches, after the complete private file is written, before response
publication and while the already-completed file is transferred. In addition, each
exported event writes one protected private range-index record
`[start_byte,end_byte,event_id]`. Before release the index is reread in bounded batches
and checked against the current scoped event graph. This catches event moves and
property/unit relationship moves that happened after the frozen data snapshot, without
loading all IDs or unrelated/foreign events into application memory. The same live
relationship check runs once more immediately before the download response is returned.
Even an unrestricted owner is narrowed to the explicitly requested portfolio for both
the frozen query and these live checks.

A revocation or relationship move before publication returns an error response with no
calendar attachment. The shared `PrivateDownloadResponse` accepts optional synchronous
`before_start` and `before_chunk(start,end)` guards. Calendar uses `before_start` for
the complete bounded relationship check immediately before `http.response.start`;
existing DATEV/tenant users leave both optional callbacks unset.

For body transfer, calendar keeps one sequential cursor open on the protected range
index. Before each private 1 MiB block it checks only event IDs whose serialized byte
ranges overlap that block. The guard runs before the corresponding private-file
`read()`; a failed second-block guard therefore does not load that block into the send
buffer. An event spanning a block boundary remains as one active record and is rechecked
before the following block. Index records are never rescanned from the beginning, so
transfer validation is O(number of exported events), not O(events × body blocks). A
source/grant change after headers therefore terminates the response before affected
subsequent bytes; the declared `Content-Length` is not completed and no final successful
body frame is emitted. Disconnects and all guard failures close/remove only the owned
private workspace.

Late validation errors (for example an invalid time on the last event) delete the private
workspace and occur before successful response headers. The response includes
`Content-Length` and `X-Content-SHA256` calculated from the completed file; neither is
predicted from a partial export.

## Mapping

Only existing `CalendarEvent` fields are serialized:

- `title` -> `SUMMARY`
- `event_type` -> one escaped `CATEGORIES` text value
- `event_date` -> `DTSTART;VALUE=DATE` when no event time exists
- `event_time` -> portfolio-local wall time converted to UTC `DTSTART`
- `location` -> `LOCATION`
- `description` -> `DESCRIPTION`
- `participants` -> `X-IMMOMANAGER-PARTICIPANTS` only; it is **not** emitted as
  `ATTENDEE` and therefore does not create invitation semantics.

No `METHOD`, `ORGANIZER`, invitations, OAuth operation or external delivery is
performed. There is no schema or frontend change.

The UID is deterministic for the existing event ID. Existing UUID IDs are emitted as a
UUID URN; a deterministic UUIDv5 fallback is used only for legacy non-UUID IDs.

## Time zones

Each export is for exactly one existing portfolio. Its existing `Portfolio.timezone`
is the source IANA time zone. Timed events are converted to UTC and the source zone is
recorded as `X-IMMOMANAGER-SOURCE-TZID`; this avoids floating local times and avoids
requiring generated `VTIMEZONE` rules. Nonexistent or ambiguous local wall times around
DST transitions are rejected with HTTP 422 rather than guessed.

Python `zoneinfo` uses system IANA data or the first-party `tzdata` package. Windows
does not normally provide IANA zone files, so `tzdata` is a runtime dependency here.
The project pins `tzdata==2026.4` in requirements and allows `>=2026.4,<2027` in the
package metadata. The package is maintained by the Python Software Foundation and
published under Apache-2.0.

References:

- RFC 5545, iCalendar: https://datatracker.ietf.org/doc/html/rfc5545
- Python `zoneinfo` data-source documentation:
  https://docs.python.org/3/library/zoneinfo.html
- `tzdata` 2026.4 package metadata/license:
  https://pypi.org/project/tzdata/2026.4/

## Encoding and folding

The response is UTF-8 with CRLF line endings. RFC 5545 TEXT escaping is applied to
backslash, comma, semicolon and intentional newlines. Physical content lines are folded
at no more than 75 UTF-8 octets without splitting a UTF-8 code point; continuation lines
start with one space.

Download headers are:

- `Content-Type: text/calendar; charset=utf-8`
- `Content-Disposition: attachment; filename="immomanager-calendar.ics"`
- `Cache-Control: private, no-store`
- `X-Content-Type-Options: nosniff`
