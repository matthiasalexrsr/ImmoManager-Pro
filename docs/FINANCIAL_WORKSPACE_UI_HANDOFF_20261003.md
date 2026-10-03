# D3 Financial Workspace UI – Plan und Handoff

Stand: 03.10.2026
Branch: `assist/financial-workspace-ui`
Worktree: `C:\Users\matth\Documents\Codex\2026-10-01\wi\work\financial-workspace-ui`
Basis: `18ba896eff397bbe0e46e8a13864f4c33304a11a`

Dieser Plan wurde vor Frontend-Sourceänderungen erstellt.

## Verbindlich gelesen

- `docs/FINANCIAL_WORKSPACE_PLAN_20261003.md`
- `docs/FINANCIAL_CASH_HANDOFF_20261003.md`
- `backend/routers/financial_cash.py`
- `backend/services/financial_cash.py`
- `backend/routers/workflow_references.py`
- `backend/services/workflow_references.py`
- bestehender `ReferenceChoice` / private bounded read
- bestehender geschützter Blob-/CSV-Downloadpfad.

## Echte Cash-HTTP-Verträge

### GET /reports/cash

Filter:

- `date_from`, `date_to`
- `portfolio_id`
- wiederholtes `property_ids`
- `unit_id`
- `account_id`
- `basis=confirmed_cash|recorded_bookings`
- `as_of`

Response:

- `basis`
- `currency=EUR`
- kanonische `filters`
- `source_hash` (SHA-256)
- exakte MoneyStrings `income`, `expense`, `net`
- `source_count`, `excluded_count`
- vollständige Aggregate für `categories`, `months`, `locations`
- erste/optionale Detailseite nur wenn serverseitig angefordert.

Kein Betrag wird für die UI maßgeblich über `Number` oder Float summiert.

### GET /reports/cash/sources

Zusätzlich:

- `after`
- `source_hash`
- `limit` (1..500)

Cursor ist an Benutzer/Scope, alle Filter, Seitengröße und Quellenhash gebunden.
Folgeseiten müssen denselben Sourcehash mitsenden.

Quellzeile enthält u.a.:

- Buchungs-/Konto-/Kategorie-/Objekt-/Einheitsbezüge
- `booking_date`
- exaktes `amount` als MoneyString
- `amount_cents` als ganzzahliger Dezimalstring
- Status
- `included`
- `exclusion_reason`
- Zahlungstext / Belegreferenz.

409 bei geändertem Quellenhash ist kein Leerbestand:
„Buchungsquellen haben sich geändert – Auswertung erneut laden“.

### GET /reports/cash/export.csv

Nimmt dieselben CashFilters und exportiert den **vollständigen** gefilterten Bestand,
nicht die sichtbare Quellseite. Download erfolgt als geschützter Blob.

## ReferenceChoice-Vertrag

Wiederverwendet wird der bestehende bounded `ReferenceChoice`; kein neuer Shared
Picker wird gebaut.

Zulässige Filter:

- `portfolios`: Suche/selected/cursor/page_size; optional eigener `portfolio_id`
- `accounts`: `portfolio_id`
- `properties`: `portfolio_id`
- `units`: `portfolio_id + property_id`

`accounts` und `portfolios` dürfen **keine** property/unit/contract-Filter erhalten.

Parentwechsel:

- Portfolioänderung löscht Properties, Unit und Account.
- Propertyänderung löscht Unit.
- Entfernung des Portfolios löscht alle abhängigen Referenzen.
- alte ausgewählte Namen werden dadurch sofort neu autorisiert/neutral.

Mehrere Immobilien bleiben als echte Mehrfachauswahl erhalten; jede Property wird
über den bounded Referenzdienst gewählt, nicht durch Vollbestandsladen.

## Filtermodell

Filterentwurf und angewendete Filter sind getrennte Zustände.

Entwurf:

- Zeitraum von/bis
- Stichtag
- Basis
- Portfolio
- 0..n Immobilien
- optional Einheit
- optional Konto

„Auswertung anwenden“ übernimmt atomar einen validierten Snapshot.
Datumstipps/Parentwechsel lösen keine Zwischenberichte aus.

Bei behebbaren Report-/Sourcefehlern bleiben angewendete Filter erhalten.
Bei Actor-/Grantwechsel werden Report, Quellen, Cursor, Sourcehash und ausgewählte
private Referenzdarstellungen render-synchron neutralisiert; laufende Requests und
Exporte werden abgebrochen.

## MoneyStrings

Eigener Formatter:

1. akzeptiert ausschließlich /^-?\d+\.\d{2}$/,
2. trennt Vorzeichen/Ganzzahl/Cent als Strings,
3. fügt Tausendergruppen stringbasiert ein,
4. verwendet Locale-Zeichen nur für Darstellung,
5. erzeugt niemals `Number(money)` für fachliche Summen.

Diagrammbalken dürfen ausschließlich aus `*_cents`/MoneyStrings über BigInt-
Verhältnisse skaliert werden; kein Float ist ein fachlicher Betrag.

## Darstellung

- klare Kennzahlkarten Einnahmen / Ausgaben / Saldo, EUR
- Hinweis „Zahlungsbasis“, nicht Periodenergebnis
- Basisumschalter:
  - bestätigte Zahlungen (Standard)
  - aufgezeichnete Buchungen
- Monatsauswertung
- Kostenartenauswertung
- Objekt-/Einheitsauswertung, „ohne Einheit“ sichtbar
- jede Aggregatzeile kann Quellbelege fokussieren/filtern, ohne neue API zu erfinden
- Quellbelegtabelle mit inkludiert/ausgeschlossen + verständlichem Ausschlussgrund
- Belegseiten mit Vor/Zurück-Cursortrail
- source_hash sichtbar nur in technischen Details
- vollständiger CSV-Download unabhängig von sichtbarer Seite.

Nicht behauptet:

- wirtschaftliches Periodenergebnis
- AfA
- Finanzierung
- Forderungs-/Vertragsprognose
- Budget-Istlogik.

## Fehlerzustände

Getrennt:

- Loading
- echte leere Auswertung
- ungültige Response
- HTTP-/Netzwerkfehler
- 409 Quellenänderung
- 422 widersprüchliche Filter/Zuordnung
- 401/403 private Sicht vergessen.

Bei Fehlern keine Nullsummenkarten rendern.

409-Aktion:
„Aktuelle Buchungsquellen neu laden“ – Report neu abrufen, Sourcehash/Cursortrail
verwerfen, Filter beibehalten.

Source-Seitenretry:
gleiche angewendete Filter + gleicher Sourcehash + gleicher Cursor.
Kein stiller Cursorfortschritt.

## Ownership

Neu:

- `features/financialWorkspace/*`
- neue Finanzseite + lokales CSS
- eigener API-/Responsevalidator
- eigene Tests.

Nur kleines Wiring:

- App-Route
- Sidebar unter Finanzen
- DE/EN/ES-Navigation-/Pagecopy.

Nicht ändern:

- Backend
- Root/Main/Preview/E2E
- FormModal
- ReferenceChoice
- shared Picker
- globales Layout/CSS.

## Testkonzept

Leichte UI-/Unit-Verträge:

- große/negative MoneyStrings ohne Number-Rundung
- Filterentwurf vs angewendet
- Parentinvalidierung
- bounded References
- Cash-Responsevalidierung
- Quellenhash 409 + Reload
- Cursorretry
- Actorwechsel neutralisiert private Anzeige
- vollständiger CSV-Pfad enthält Filter, aber keinen Seiten-Cursor
- Aggregat-/Quellzeilen zeigen exakte Werte.

Schwere Browser-/Recovery-Gates bleiben Root und werden während Roots aktuellem
Recovery-Slot nicht von diesem Branch gestartet.
