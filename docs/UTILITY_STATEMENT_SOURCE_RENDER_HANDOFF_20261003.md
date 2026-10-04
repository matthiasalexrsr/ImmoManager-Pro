# C: checked utility statement sources, PDFs and preserved draft previews

Own checkout `work/statement-choices`, branch `assist/statement-choices`, enriched
by an ordinary merge of Root `ff4b1a5`. This is the first Source/Renderer packet.
It creates no archived original, Document, version, receipt or delivery event.
Shared document/registry/recovery/settings/CI/UI/migration files are unchanged.

## Commits to compose

- `36ce2ce`: exact source DTO/digest/profile plan before code.
- `ccb2d2b`: separate draft preservation contract before that follow-up code.
- `38d1b9f`: pure source DTO plus coherent native reader, renderer, bounded
  Billingrouter integration and actual original tests.
- `038ea57`: distinct watermarked draft mode, actual stored source JSON,
  authenticated draft PDF/ZIP compatibility and targeted tests.

Root already took initial source plan `40f9efa` as `e270e8e`. Do not cherry-pick
the enrichment merge `bdbcad5`, previous Choice work or foreign Root commits.
Compose both product commits before calling the PDF/ZIP usability work done.

## Operative contract and exact proof

`GET /api/v1/billing/statements/<id>/original-source` returns only strict
`utility-statement-original-source/1`, with profile
`utility-statement-pdf-preview/1`. Unfinalized source returns 409. Source digest
is SHA256 of typed UTF8 JSON, sorted keys, ensure_ascii=False, compact
separators, allow_nan=False, excluding source_digest itself. It binds selected
statement JSON, actual retained period context, original party/unknown mode,
entire direct-to-oldest chain and render profile. It differs from the existing
whole-period settlement hash, whose canonical bytes remain unchanged.

`statement_original` excludes mutable status/delivery/update bookkeeping and
retains snapshot_hash, financial details and calculation_hash. Context labels
itself `retained_period_reference`; current labels/property names/unit labels
are absent. No finalization-era date/display-name proof is invented. Frozen
party is exactly the proved StatementParty. Older missing party family remains
`historical_party_unproved`/null, with explicit PDF text. Missing/invalid actual
original hashes do not become a checked original by guessing new proof.

Actual source reads reuse billing_disputes.work, its actor/authority/scope
fences and read snapshot. SQL rows stream only complete affected periods by ID;
SQL global list_utility_statements is unnecessary and fails in the native proof
if called. Hash memoization is restricted to these actual affected periods.
Existing pure complete-family validation uses targeted parents and proves
frozen parent/tenant IDs, exact complete party coverage and actual ancestors.
Referenced old periods also get real whole-period hashes, even without old
party proof. Tenant existence uses only its actual ID in SQL/Memory; today's
tenant profile is never an original identity source. Current contract tenant
rebinding cannot replace the proved frozen tenant. Cycles, mismatched source
periods/dates/revisions/units/contracts/properties or corrupt siblings fail.

Existing authenticated PDF GET and period ZIP choose actual saved state within
the same read snapshot. Immutable PDF emits X-Utility-Original-SHA256,
X-Utility-Source-SHA256, X-Content-SHA256, X-Utility-Render-Profile and
X-Utility-Preview=checked-derivation. JSON/PDF/ZIP are private,no-store and vary
by Authorization. CheckedPublicationRoute rechecks token/grants before response
start, including after full PDF rendering. A missing renderer gives 503, never
plain text reported as successful PDF. ZIP uses fixed metadata/statement order
and includes exact source JSON alongside each same-byte individual PDF.

Actual draft/review instead emits `utility-statement-draft-source/1`, mode=draft,
profile `utility-statement-draft-pdf-preview/1`, statement_draft, not_frozen/null
party and optional verified previous_original. Previous original proves only
that earlier source, with exact typed contract/unit/date/revision linkage.
Draft source contains no current tenant/display name or fake final hash. Every
page has real rotated ENTWURF glyphs plus an explicit draft heading/footer.
Draft PDF says X-Utility-Preview=draft-derivation and omits Original-SHA256.
Original-source endpoint stays strict even while useful draft PDF/ZIP work.
Empty ZIP keeps 400; foreign source 404; invalid source/mixed original 409.

Pure source validation imports no Auth/config/dependencies/app/storage,
repositories, SQLAlchemy or operative billing modules. Rendering is a checked
derivation of an already verified operative source. DTO/digest validation by
itself is no substitute for actual parent/whole-period source verification at
a future archive commit; no external client hash cache is accepted here.

## Actual focused acceptance and boundaries

Original Memory: four first cases passed before a grant-mutation fixture
scope mistake stopped the first gate (33.75s). After only fixture correction,
three selected cases passed (21.48s), including a repeated first proof, actual
token/grant publication loss and multipage/pure imports. Six distinct original
cases were green. Original SQLite: five real PASS/34.04s, no skips. The later
extra source-GET-in-DML-recorder assertion was not present in that first SQLite
run; its actual proof is the subsequent PostgreSQL run below.

Draft Memory: two domain cases passed before a rotated-text-extraction test
assumption (17.25s); then multipage plus four authenticated legacy API test
replacements passed (5 PASS/23.33s). Seven distinct Memory cases were green.
Product remained unchanged throughout those test-only repairs. Existing direct
PDF/ZIP tests now use actual authenticated HTTP generation, no bypass/fallback.
The later persisted-GET helper refinement was explicitly tested by native
SQLite/PG, not retroactively claimed as a new Memory gate.

Draft SQLite: two real PASS/19.94s, no skips, after fixture comparison used the
actual saved Statement GET. The generate response's precommit UTC timestamp
differs from the existing native naive DateTime representation; no product
timestamp or original bytes were rewritten to make that comparison pass.

Final PostgreSQL on unchanged final product: **7 PASS/90.77s, zero skips**.
Actual dedicated localhost:58112 cluster, seven separately created/dropped
UUID measurement schemas, never public or service restarts. Five original
families plus two draft families covered:

- Actual finalization, profile/label change, delivery status change, exact
  original/source SHA, repeat PDF and ZIP bytes, and source JSON matching ZIP.
- Genuine no-DML source GET/PDF/ZIP, with global native statement listing
  explicitly forbidden; selected member still sees original frozen party
  after independent actual contract-tenant rebind.
- Two real correction revisions, descendant source lineage and corrupt
  unselected old-period sibling rejected by actual full source hash.
- Current sibling corruption plus missing frozen sibling entry rejected even
  after attacker-style native owner/statement rehash.
- Explicit actual pre-party generated legacy fixture, unknown historic party,
  draft-original conflict, real unauthorized and foreign actors rejected.
- Real generated PDF followed by independent grant change/token revocation
  before publication; regular 403/401, no successful bytes published.
- Actual draft JSON/financials/headers, no Document creation, genuine
  finalization switches to immutable proof; actual correction draft verifies
  previous original and rejects corrupted old-period sibling.

Visual QA used bundled Noto regular/bold and real actually generated records,
with Latin, Greek, Cyrillic, escaped metacharacters and long cost lines. Original
PDF: four real Poppler PNG pages individually inspected; repeated table headers,
page numbers, all positions/39,00 EUR complete, no clipping/overlap/.notdef.
Draft PDF: four current Poppler PNG pages individually inspected; all positions,
37,00 EUR, readable watermark each page and clean transitions. Tests require
actual font glyphs; draft test inspects actual rotated PDF paint glyphs and
separately extracts unrotated text, rather than mistaking geometric extraction
for missing watermark or missing financial content.

Same previously emitted original DTO rendered after the draft extension is
byte-identical to its prior actual PDF: SHA256
`edcd03ba0b61477b0bbfde1148bddcbd453bb92d484145987bba9956dbdab779`.
Fresh process source blocker/negative mutations passed. Final Ruff of all eight
changed Python files and Mypy of the two services passed; diff-check passed.
Native/Python processes ended and heavy slot released to UI before handoff.

No actual archive receipt, archived byte replay after restore or dispatch
acceptance is claimed. Those are the next separately owned composition using
the existing DocumentVersion core and exact utility original subtype, Root
registry/restore hooks and actor/idempotency checks through actual commit.
