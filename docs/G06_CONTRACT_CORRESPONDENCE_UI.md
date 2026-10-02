# G06.2: manual contract dates and correspondence

Isolated frontend package based on published f3203d5. Backend files, Main,
Preview data, CI and browser tests are unchanged. The matching backend is
released as 8aabaa0895ccc10af61dd9714d7f75ab9b8c966e in
work/contract-correspondence; its runtime, recovery,
privacy and calendar hooks belong to Root integration.

## Entry and workflow

The existing ContractLifecycle dialog has an additional “Dates & letters” area.
Contracts.jsx and the server-paged contract workspace are unchanged. The child
area remains mounted when another outer tab is selected, retaining its private
letter, edited values and exact uncertain command. Pending mutations and PDF
downloads lock the dialog's tabs, close buttons, Escape and backdrop. Existing
focus containment and opener restoration remain in use.

The actor/grant-bound area initially shows authorized approved letters. Own
drafts and deliberately entered management dates are separate bounded lists.
Dates and their basis are entered explicitly and require a confirmation
checkbox. No date is inferred from notice-period text or contract dates.

A letter uses custom plain text or an explicitly selected immutable G07
template version. Creating a template or another version requires confirmation;
the predecessor ID is explicit. A version conflict retains the edited text and
offers a deliberate change of predecessor after loading/selecting current
versions. The optional accepted lifecycle command is selected from bounded
contract-specific history. No new templates, legal wording or deadlines are
invented automatically.

Save, review and approve are separate actions. Local changes invalidate review
consent and block approval until explicitly saved and reviewed. Approval consent
is tied to draft ID, UUID revision and review hash and additionally opens the
existing confirmation dialog. Publication needs both rental and documents write
permission; drafting/review require rental write permission. Readonly actors can
read authorized approved history and download its stored original.

Approved content is immutable. Observed dispatch/receipt events require a date,
evidence reference, note, an explicit confirmation checkbox and a separate
confirmation dialog. Receipt identifies an existing dispatch event. Changed
sources prevent another dispatch; receipt of a previously recorded dispatch
remains available. Events record observations, send nothing and assert no legal
delivery or legal validity. Event and letter histories use independent server
cursor pages of 25, never unbounded reference fetches.

## HTTP and recovery contracts

The panel constructs paths beneath /contracts/{contract_id}/correspondence.
It uses drafts, history and deadlines; draft edit/review/approve; review-pdf;
immutable download; and events. All parameters and IDs are encoded. Downloads
use api.getBlob and an owned revocable Blob URL. DTO download_url is never sent
an Authorization header or used as a navigation target. MIME and PDF magic are
checked before download; the backend verifies stored PDF hashes/bytes. The
review displays its SHA-256 for evidence.

Every mutation carries its generated idempotency key and exact expected UUID
revision / contract ETag where required. A network failure, 5xx or malformed
acknowledgement freezes the command and exposes an explicit exact retry with
the same payload and key. Historical command results are validated separately
from freshly loaded current_contract_etag/source_review_status. A successful
POST followed by a failed GET is acknowledged as saved and offers a reload,
without incorrectly offering to rerun the command.

409/412 retain entered values and require an explicit refresh. After refresh,
a deliberately saved change uses the new source/revision and a new key.
Changing actor, role, write grants, portfolio grants or contract remounts the
area and aborts pending requests. Late replies cannot publish into the new
context. Server 401/403/404 clears private values and source catalogs. Reviewed
source IDs, portfolio binding and data are checked before rendering; unrelated
private actor drafts and foreign/malformed deadline pages are rejected.

Template editing and uncertain template commands also remain mounted across
inner section changes. Their uncertain command freezes additional mutations
until explicitly retried. After an event-CAS refresh, evidence fields remain
but the observation checkbox must be confirmed again. An initial 422 read
offers an explicit retry with page size 1, supporting a legitimately smaller
configured transfer budget without relaxing validation or changing any data.

## Verification and remaining integration

Executed on the final production source: all 70 Vitest files passed (905 tests,
two workers). Three additional budget-1 cursor/abort/denial tests were added
after that full run without changing production source; the final focused run
passed 79 tests across correspondence and both existing lifecycle test files,
including all 43 new correspondence tests. Global ESLint, production build and
git diff --check exited successfully. Tests use synthetic API responses; no
backend or browser execution is implied by these frontend results.

The focused test file covers explicit dates, save/review/approval, local review
invalidation, uncertain exact retry, source/revision conflicts, duplicate
commands, acknowledgement-refresh failures, source/actor denials, readonly
foreign approved history, PDF failures/revocation, stale dispatch versus receipt,
event confirmation reset, bounded templates, template conflicts, outer-tab
retention, pending-close prevention, keyboard use and DE/EN/ES labels.

Scoped CSS wraps dialog tabs, dates, evidence, long text/hash values and actions
at narrow widths; it does not mask overflow. Actual 320/360 px browser geometry,
fresh SQL roundtrip, readonly/foreign HTTP behavior and full combined backend
integration must be checked by Root's authorized browser runner after the
matching backend and runtime hooks are integrated. No independent browser
execution is claimed by this package.
