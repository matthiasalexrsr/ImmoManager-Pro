# Refresh coordination across browser tabs

CI122's real trace showed two POSTs with the same refresh-token hash: the first
returned 200, the second returned 401 22 ms later. The backend correctly revoked
the family on replay. No token values are reproduced here.

The old client used Web Locks plus a Local Storage reread. Cross-renderer storage
visibility is not a synchronization guarantee; the [HTML Web Storage
specification](https://html.spec.whatwg.org/multipage/webstorage.html) explicitly
leaves cross-agent-cluster interactions unspecified. Delayed renderer visibility
is a plausible explanation for the observed trace, not a claim about Edge's
internal implementation. The new browser regression reproduces that ordering
with a delayed renderer cache and actual backend responses.

The API client now keeps a same-origin IndexedDB session record. Login, rotation,
invalidation and logout use the existing Web Lock when available. IndexedDB
read/write transactions provide the atomic claim and publication checks; a
rotation response cannot overwrite a newer login or logout even without Web
Locks. Access and refresh credentials commit together before the lock is released.
The existing Local Storage keys remain compatible with consumers. No credential
is placed in a URL, log or third-party request. This has the same origin-script
trust boundary as the existing token storage; it does not introduce HttpOnly
cookie protection.

Before sending a one-use refresh credential, the client commits a rotation
intent. A lost response or failed pair commit leaves that intent in place instead
of resending a possibly consumed credential. If the originating tab received the
new pair but its browser commit failed, an explicit retry commits the retained
pair without another HTTP refresh. Other tabs wait for confirmed state through a
visible recoverable error. If the response was lost or that tab was closed,
signing in again replaces the unresolved intent. Opening a retry page does not
automatically replay the old token. Browsers without IndexedDB retain the existing
single-realm fallback; cross-renderer durable coordination requires IndexedDB.

Logout clears the local pair immediately, revokes the latest known family, then
commits a logout tombstone. A pending old refresh cannot restore it. A pending
login in the same tab cannot publish after logout. The protected route aborts
validation on cleanup and ignores its late response. Network/storage failures
offer retry without erasing a newly successful login; only current credential
invalidation in the API removes the pair.

A successful `/auth/me` response is also bound to its actual request credential:
an old 200 cannot publish the previous actor after a new login. Token-free local
notifications and native storage events detect principal/session-family changes.
Those changes reload the open tab, dropping its AuthContext, shared data cache and
private dialog state before fresh validation. Ordinary rotation within the same
family does not reload or discard an open editor. JWT claim parsing here is only
a change signal, never an authorization decision.

## Reproduction and acceptance

From `frontend/`:

```powershell
npm run test -- src/test/SessionRefreshStorage.test.js src/test/ProtectedRoute.test.jsx src/test/SessionRefresh.test.js src/test/api.test.js src/test/Login.test.jsx src/test/TwoFactorSection.test.jsx
$env:IMMO_E2E_CHANNEL = 'msedge'
$env:IMMO_E2E_PYTHON = '<project>\.venv\Scripts\python.exe'
npm run test:e2e -- auth-sessions.pw.mjs
npm run test:e2e -- --fresh-install
```

The runner builds the frontend, migrates a new isolated SQLite database, starts a
real loopback backend and removes only its own temporary installation. The normal
session suite covers one simultaneous refresh, deterministic stale renderer
storage, successful backend authentication in both tabs, other-browser session
revocation and logout. API responses are not mocked. The setup suite preserves
initial-owner creation, TOTP enable/login/disable and the existing core workflow.
Linux CI uses pinned Playwright Chromium through the existing runner. No timeout,
retry count or existing session assertion was weakened.

Acceptance on 2026-10-02, isolated branch based on `5ee37ba`:

- 786 frontend tests in 64 files passed with two Vitest workers; 53 focused
  authentication tests passed, including 23 new regressions. ESLint passed.
- Three actual SQLite/Edge session cases passed, including owner-to-selected
  readonly actor change: the previous property and open editor disappear, the
  actual `/auth/me` returns the new user, and remote logout denies both tabs.
- Two actual empty-installation SQLite/Edge cases passed: owner/TOTP and the
  existing first-owner rental/payment/reversal workflow. Fresh Alembic migration
  runs before backend startup in each runner installation.
- Baseline reproduced the stale-renderer browser failure against the actual
  backend; the initial eleven narrow regressions yielded ten failures and one
  pass against old sources. The original concurrent-session assertion remains.
- An unrestricted-worker full unit run had one existing bank-lookup mock remain
  in its loading state past its standard assertion deadline. That unchanged
  panel passed all nine focused cases; the two-worker complete run passed.

Only Edge was executed locally. The new tests remain discoverable by the existing
Linux Chromium CI configuration; Linux execution is an integration gate, not a
local result claimed here. Main, Preview and actual user installations were not
modified by this package.
