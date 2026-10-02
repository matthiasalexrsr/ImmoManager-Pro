# G37 real browser workflow and mobile upload regression

Isolated branch `assist/document-version-browser` starts at Root's integration
`c028e2f`; it does not modify Main or the preview database. The existing runner
creates its own empty SQLite database, runs the complete Alembic chain through
y1, seeds synthetic demo data, starts its owned server, and removes its test
directory afterward. No application routes, authentication, or file responses
are mocked; only one committed upload response is deliberately lost.

Run with `npm run test:e2e -- document-versions.pw.mjs` in frontend. Windows QA
used installed Edge (`IMMO_E2E_CHANNEL=msedge`) and the existing Python runtime
via `IMMO_E2E_PYTHON`. Linux CI uses the existing pinned Chromium configuration.

The browser proves upload plus real metadata creation, explicit original hash
review/confirmation, a new version with retained draft and receipt after a lost
response, and restoration as a third immutable version. All original/new/restored
downloads match their exact synthetic bytes and SHA256; the legacy original URI
and file bytes remain unchanged. New real readonly and foreign-portfolio accounts
log in through the UI: readonly reads/downloads and cannot restore (403); foreign
history/downloads are 404 and anonymous downloads are 401. No additional journal
row is introduced by retries or forbidden actions.

Mobile checks exercise both 320 and 360 pixels **before any reload removes the
upload receipt**, with the dialog closed immediately after metadata creation and
open/closed again after restoration. The viewport and document widths match;
the dialog and buttons fit. Shift+Tab/Tab wrap from Close to the last reachable
comparison checkbox and back, and closing restores focus to the document action.
A real 320px viewport screenshot is attached to the test result and visually
inspected; no screenshots or test database are committed.

The red baseline exposed the complete unbroken upload URI in the centered
photo-drop-zone span, widening a 360px page to 390px. The repair adds only a
Documents.css import and documents-page class: the source receipt spans can
shrink/wrap within that page. The complete URI remains visible. A scoped mobile
header grid also gives the dialog heading and complete source title their own
full-width rows. No overflow hiding, global styles, toolbar handlers, source
replacement, or backend change is included.

Final verification: actual Edge/SQLite 1/1 passed (19.1s test, 20.8s suite), fresh
full Alembic y1 startup passed, 20 version-history and 6 existing typed-OCR UI
cases passed, ESLint and the production build passed. PostgreSQL and Linux
Chromium execution remain the existing dedicated CI gates, not local claims.
