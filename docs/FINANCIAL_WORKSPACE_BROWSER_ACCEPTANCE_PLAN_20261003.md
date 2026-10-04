# FinancialWorkspace Browser Acceptance – Prüfplan

Stand: 03.10.2026  
Branch: `assist/financial-workspace-browser-qa`  
Worktree: `C:\Users\matth\Documents\Codex\2026-10-01\wi\work\financial-workspace-browser-qa`  
Basis: `e2a29de9cd812d47d78a0c2a7f1ed12297569c02`

Dieser Checkout enthält ausschließlich Browser-QA-Planung und eigene Testquellen.
Root-/Main-/Preview-/Backend-/shared-Core-/CI-Dateien werden nicht geändert.

## Status dieses Dokuments

Noch **kein** Browser-, SQLite-, PostgreSQL-, Recovery- oder Buildlauf gestartet.
Die nachfolgenden Punkte sind Prüfanforderungen und erwartete Assertions, keine
Erfolgsaussage. Der spätere Lauf berichtet echte Fehler unverändert.

## Tatsächlich gelesene Verträge

Frontend:

- integrierte `FinancialWorkspace`-Seite
- `financialWorkspaceApi.js`
- `financialWorkspaceModel.js`
- `ReferenceChoice.jsx`
- Playwright-Config und bestehende Browsercases für Auth, Portfoliozugriff,
  Cursor/CSV, Sourcekonflikte und Viewports.

Backend:

- `GET /api/v1/reports/cash`
- `GET /api/v1/reports/cash/sources`
- `GET /api/v1/reports/cash/export.csv`
- `GET /api/v1/workflow-references/{kind}`
- reale Create-DTOs für Portfolio, Property, Unit, Account, Category, Booking.

Keine Testquelle verwendet einen erfundenen Endpoint.

## Synthetische Fixture

Der Test erzeugt ausschließlich Daten mit zufälligem Präfix und
`example.test`-Benutzername/-Adresse.

### Owner-Setup

Mit dem vorhandenen Demo-Owner werden angelegt:

- sichtbares Portfolio A,
- verborgenes Portfolio B,
- zwei Immobilien in A,
- eine Einheit in Immobilie A1,
- ein Konto in A,
- ein verborgenes Konto in B,
- zwei Kostenarten in A,
- mindestens 60 Buchungen im sichtbaren Portfolio.

Keine produktiven Namen, Kontonummern, Portalwerte oder echten Personen.

### Eingeschränkter Browseractor

Zusätzlich wird ein synthetischer `verwalter` angelegt mit:

- `portfolio_access=selected`
- genau Portfolio A
- Locale `de-DE`.

Die FinancialWorkspace-UI wird ausschließlich unter diesem eingeschränkten
Benutzer bedient. Owner-Token dient nur zur Fixtureerzeugung und zur gezielten
parallelen Quelländerung für den Sourcehash-Konflikt.

## Buchungsbestand

Der sichtbare Bestand umfasst mehr als 50 Quellen, damit die echte
`/reports/cash/sources`-Cursorfolge benutzt werden muss.

Verteilt werden Buchungen über:

- Januar, Februar und März 2026,
- beide Kostenarten,
- Immobilie A1 + Einheit,
- Immobilie A2 ohne Einheit,
- bestätigte Einnahmen,
- bestätigte Ausgaben,
- explizit `0.10` + `0.20`,
- unbestätigte Quelle,
- stornierte Quelle,
- Quelle nach dem gewählten Stichtag,
- mindestens eine synthetische `receipt_url`-Referenz,
- mindestens ein Zahlungstext mit führendem `=SUM(...)` zur CSV-Zellschutzprüfung.

Der Test hält erwartete Geldwerte als **Integer-Cents/BigInt**, nicht als
Gleitkomma-Summen.

## Browserablauf

### 1. Reale Auth und Portfoliofilter

- als eingeschränkter Manager anmelden,
- `/financial-workspace` öffnen,
- Portfolio-Suche findet Portfolio A,
- Portfolio B darf nicht als auswählbare Referenz erscheinen,
- nach Auswahl von A:
  - Kontoauswahl ist mit `portfolio_id=A` gebunden,
  - Immobilienauswahl ist mit `portfolio_id=A` gebunden,
- nach Auswahl genau einer Immobilie:
  - Einheitenauswahl ist mit `portfolio_id=A&property_id=A1` gebunden,
- verborgenes Konto/Objekt darf nicht über den sichtbaren Picker erscheinen.

Zusätzlich werden die Request-URLs der ReferenceChoice-Calls beobachtet; die
erwarteten Parentfilter müssen tatsächlich am Server ankommen.

### 2. Formularfehler und Tastatur

Vor dem ersten gültigen Bericht:

- `date_from > date_to` eintragen,
- „Auswertung anwenden“ per Tastatur auslösen,
- konkrete Filterfehlermeldung erwarten,
- sicherstellen, dass dabei **kein** `/reports/cash`-Request veröffentlicht wird.

Danach Werte korrigieren.

Tastaturprüfung:

- Fokus auf Datumseingaben und Basiswahl,
- Tab-Reihenfolge bis zur Hauptaktion,
- Quellbelegregion ist fokussierbar,
- Vor-/Zurückbuttons sind tastaturerreichbar.

### 3. Angewendete Filter

Erster gültiger Lauf mit:

- Portfolio A
- einem Objekt A1
- Einheit A1/U1
- Konto A
- Zeitraum
- Stichtag
- `confirmed_cash`.

Der Test prüft am echten HTTP-Request die Queryparameter.

Danach zweiter Lauf:

- Einheit entfernen,
- Immobilie A2 ergänzen,
- beide Immobilien anwenden.

Dadurch werden Monats-/Kostenarten-/Objektauswertungen einschließlich
Objektkosten ohne Einheit geprüft.

### 4. Exakte Geldwerte

Geprüft werden:

- Einnahmen
- Ausgaben
- Saldo
- Monatswerte
- Kostenartenwerte
- Objekt-/Einheitswerte.

Erwartungen werden im Test aus Integer-Cents berechnet und in denselben
deutschen MoneyString-Text überführt, ohne JS-Float-Summen.

Spezifisch muss `0.10 + 0.20` als exakt `0,30 €` in der passenden
Aggregation aufgehen.

### 5. Quellbelegseiten und Cursor

Mit >50 Quellen:

- Seite 1 zeigt die echte erste Sources-Seite,
- „Nächste Seite“ erzeugt Request mit:
  - altem `source_hash`
  - `after=next_after`
  - identischen Filtern,
- keine Quelle darf seitenübergreifend doppelt sein,
- „Vorherige Seite“ lädt wieder den gespeicherten Cursorzustand.

Die UI darf keine Vollbestandsliste im Browser halten, um die Pagination zu
simulieren.

### 6. Sourcehash-Konflikt

Nach geladener erster Quellseite erzeugt der Owner über den echten Booking-POST
eine weitere Buchung innerhalb derselben angewendeten Filter.

Anschließend:

- „Nächste Seite“ mit altem Hash muss serverseitig 409 liefern,
- UI zeigt „Die Buchungsquellen haben sich geändert.“,
- keine Nullsumme darf erscheinen,
- angewendete Filter bleiben sichtbar,
- „Aktuelle Buchungsquellen neu laden“ startet bewusst wieder Seite 1,
- neuer Report erhält einen neuen `source_hash`,
- die neue Quelle wird anschließend im vollständigen Bestand berücksichtigt.

### 7. Vollständiges CSV

Browser klickt „Vollständiges CSV“.

Geprüft:

- echter Download-Event,
- Dateiname `zahlungsquellen.csv`,
- Downloadrequest ist `/api/v1/reports/cash/export.csv`,
- dieselben angewendeten Filter,
- **kein** `after`,
- **kein** `source_hash`,
- CSV enthält alle gefilterten Quellen, auch außerhalb der sichtbaren Seite,
- ausgeschlossene Quellen bleiben mit Status/Grund enthalten,
- `=SUM(...)`-Text ist durch den Server geschützt,
- verborgenes Portfolio B ist nicht enthalten.

### 8. Berechtigungsentzug

Nach erfolgreichem Bericht wird dem Browseractor der Portfoliozugriff auf A über
den Owner entzogen.

Danach wird eine neue echte Finanz-/Reference-Abfrage ausgelöst:

- alter sichtbarer Finanzstand darf nicht als aktueller Bestand stehen bleiben,
- nicht mehr erlaubte direkte IDs dürfen keine Daten offenlegen,
- private Referenznamen aus A dürfen nicht unter neuem Scope auswählbar bleiben.

Dieser Teil darf reale 401/403/404/leer-scope-Semantik nur so akzeptieren, wie
der Server sie tatsächlich liefert; der Test erfindet keinen Erfolgszustand.

## Viewports

Nach erfolgreich aufgebautem Bericht werden geprüft:

- 1440×1000
- 360×844
- 320×844

Für jede Breite:

- `documentElement.scrollWidth <= innerWidth`,
- Filter/Hauptaktion sichtbar,
- breite Quelltabelle bleibt in ihrem eigenen Scrollcontainer,
- keine Seite wird durch Sourcehash, Namen oder Geldwerte horizontal verbreitert,
- Screenshot als Testartefakt.

Der bekannte FullPageScreenshot-/Sticky-Header-Effekt wird nicht als globaler
Layoutfehler gewertet; vor Screenshots wird `scrollTop=0` gesetzt.

## Fehlerreport

Der spätere reale Lauf wird nicht als „grün“ vorausgesetzt.

Bei Fehlern werden berichtet:

- fehlgeschlagene Assertion,
- HTTP-Status + Responsebody soweit nicht sensitiv,
- betroffene Request-URL ohne Tokens,
- Screenshot/Trace-Pfad,
- ob Fehler UI, Cash-Vertrag, Reference-Filter, Auth/Scope oder Testfixture betrifft.

Keine Zugangstokens, Passwörter oder private Daten werden in Handoff/Chat
ausgegeben.

## Noch nicht gestartet

Wegen koordinierter Rechnerlast aktuell bewusst nicht ausgeführt:

- Playwright-Browserlauf,
- Produktionsbuild,
- SQLite-/PostgreSQL-Recovery,
- Gesamt-E2E.

Nach Commit der Testquellen wird der konkrete Playwright-Aufruf angekündigt und
erst nach Slotfreigabe gestartet.

## Vorgesehener isolierter Lauf nach Slotfreigabe

Aus `frontend`:

`npm run test:e2e -- financial-workspace.pw.mjs`

Der bestehende Runner führt dabei automatisch den Produktionsbuild aus, migriert eine eigene temporäre SQLite-Datenbank bis Alembic-Head, startet den lokalen Backendserver mit synthetischer Demo-Basis und ruft ausschließlich diese Playwright-Datei auf. Dieser Lauf wurde in der Vorbereitungsphase ausdrücklich **noch nicht** gestartet.

## Statischer Native-Source-Audit nach Testquellenreview

Ohne Browser-/Backend-/Buildstart wurden die Testannahmen nochmals direkt gegen die aktuellen nativen Quellen abgeglichen:

- `financial_cash.py` sortiert Quellbelege stabil nach `(booking_date,id)` und bindet Cursor an Filter, Scope, Seitengröße und Sourcehash.
- Sources-Seiten liefern dieselben Gesamtsummen und denselben `source_hash` wie der Report; Seite 2 muss ID-disjunkt zu Seite 1 sein, „Vorherige Seite“ muss serverseitig wieder exakt die IDs von Seite 1 liefern.
- Die erste Sources-Seite wird im Browsercase jetzt zusätzlich an exakt beide angewendeten Immobilien, fehlende Einheit, Konto, Basis, Stichtag und den Report-`source_hash` gebunden. Eine verspätete frühere Ein-Objekt-Antwort kann dadurch nicht versehentlich als aktuelle Seite akzeptiert werden.
- Verborgene Portfolio-/Kontoreferenzen werden nicht mehr nur über „kein Button sichtbar“ geprüft. Der Test wartet auf die echte `workflow-references`-Response mit exaktem Suchtext/Parentfilter und prüft, dass die verborgene ID nicht in `items` vorkommt.
- Zusätzlich wird ein direkter Cash-Request auf das nicht berechtigte Portfolio mit dem eingeschränkten Browseractor geprüft; nur der native 403/404-Scope-Abweis ist zulässig und der Responsebody darf weder verborgenen Namen noch Booking-ID enthalten.
- `ReferenceChoice` wurde unverändert gelassen; seine nativen Queryfelder `search,selected_id,cursor,page_size` und Parentfilter werden im Browsercase beobachtet.
- `csv_chunks` exportiert aus demselben vollständigen Source-Iterator, schützt Textzellen über `csv_cell` und ist unabhängig von sichtbaren Quellseiten. Der Browsercase prüft daher vollständige IDs, ausgeschlossene Quellen und den geschützten Formeltext.
- Eine Quellzeile mit `receipt_url` wird ausdrücklich als reine Belegreferenz geprüft; die FinancialWorkspace-UI darf daraus keinen öffentlichen Link rendern.

Statische Prüfungen nach diesen Korrekturen:

- `node --check frontend/e2e/financial-workspace.pw.mjs`: bestanden.
- `git diff --check`: bestanden.

Weiterhin **nicht** ausgeführt: Playwright, Testserver, Build, SQLite/PostgreSQL oder Recovery.
