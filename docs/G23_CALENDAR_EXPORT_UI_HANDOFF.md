# G23.2 — explicit calendar download

The Calendar page now offers an explicitly selected, authorized portfolio's
existing events as an ICS download. Readonly users can read and export their
visible appointments. The file is a snapshot to import into a calendar app;
this workflow neither synchronizes future changes nor sends invitations.
Descriptions and participant details can be included, as the UI explains.

## Integration

This UI branch starts at Root `5ee37ba`. Backend prerequisites `bc9099c` and
`c0cf706` are present as local cherry-picks solely for verification; the native
UI commit does not change their backend, dependency or documentation files.
Root coordinates the backend's additional fresh-scope/Memory-create review.

The independent `CalendarExportPanel` uses the existing shared `api.get` and
`api.getBlob` contracts. Portfolio choices are fetched in bounded pages of 50
(one additional row detects the next page), with no aggregate `getAll` or total
portfolio cap. A portfolio is never automatically selected. HTTP/auth failures
remain errors. Before creating a download URL, the panel checks calendar MIME
and bounded beginning/end markers; full ICS validation and coherent snapshot
construction remain the backend's responsibility. No second full text copy of
the calendar is constructed by the UI.

Duplicate clicks are blocked synchronously. Portfolio/page changes abort the
request and discard stale results; actor, role and portfolio-grant changes
remount the actor-bound panel. Unmount aborts outstanding work and clears owned
Blob URLs/timers. Signals and request identity are checked again immediately
before the link is activated. Downloads use a fixed safe filename; no arbitrary
DTO URL is trusted with the Authorization header.

An actual readonly browser run exposed an existing Calendar loading dependency:
the denied administration-only `/calendar/schedules` request rejected the shared
Promise and left existing events invisible. Calendar now skips optional
administration reads and `OperationalTickPanel` without `canWrite`, hides the
unread schedule column, and reloads/aborts shared reads on actor/grant/permission
changes. Old actor rows and open forms are hidden during that transition.
The export panel stays available while event loading runs or fails. Existing
CRUD, revision checks, schedules and write guards retain their API contracts.

## Executed verification

- 23 focused frontend regressions: DE/EN/ES and readonly selection; HTTP
  401/403/404/422/500 without a false download; HTML/JSON/truncated calendar;
  duplicate clicks; portfolio, actor, grant and unmount aborts; bounded paging;
  invalid-list retry; actual readonly table rows with denied scheduler stubs;
  role-switch abort and late-row suppression; export access during load failure.
- Final real Edge/SQLite browser case passed (12.5 s / 14.1 s suite), on a new
  runner-owned database migrated to the actual Alembic head. It creates synthetic
  events through real APIs, downloads real ICS bytes, checks scoped contents,
  stable UIDs/identical repeat hashes, timed UTC and all-day dates, escaped
  descriptions, participant data without invitation fields, and retained source
  events. A fresh readonly login sees an existing event in the real table and
  downloads identical bytes; foreign export is 404, anonymous export 401 and an
  attempted readonly write 403. Both owner and readonly layouts fit 320/360 px;
  select/download targets are at least 44 px and keyboard navigation is checked.
  The attached 360 px screenshot was visually inspected.
- Scoped ESLint and the production build passed. The final complete frontend
  suite passed: 786 tests / 64 files, using two workers to avoid oversubscribing
  the shared Windows host. Before the readonly follow-up, the complete 783-test
  suite also passed. Earlier high-parallelism runs exposed only an initial new
  status assertion (corrected to await its rendered completion) and existing
  lookup/test timeouts; no unrelated tests or product guards were changed.

The browser runner owns its disposable data/server and cleans them up; no Main,
Preview database, OCR/G37 source or user-owned calendar was changed. On Windows,
the backend needs its declared `tzdata==2026.4` dependency. For this isolated
proof it was installed into a separate owned runtime target and supplied through
`PYTHONPATH`; the shared Main virtual environment was not modified.
