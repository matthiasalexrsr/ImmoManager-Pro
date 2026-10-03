# D3 Financial Workspace UI â€“ Planaddendum und Handoff

Stand: 03.10.2026
Branch: `assist/financial-workspace-ui`
Worktree: `C:\Users\matth\Documents\Codex\2026-10-01\wi\work\financial-workspace-ui`
Basis: `18ba896eff397bbe0e46e8a13864f4c33304a11a`

Dieser Plan wurde **vor SourceÃ¤nderungen** erstellt.

## Verbindliche VertrÃ¤ge

Gelesen und maÃŸgeblich:

- `docs/FINANCIAL_WORKSPACE_PLAN_20261003.md`
- `docs/FINANCIAL_CASH_HANDOFF_20261003.md`
- `backend/routers/financial_cash.py`
- `backend/services/financial_cash.py`
- `backend/routers/workflow_references.py`
- `backend/services/workflow_references.py`
- bestehendes `features/unitInventory/ReferenceChoice.jsx`
- bestehende geschÃ¼tzte Blob-/CSV-Patterns im Frontend.

## Cash-HTTP-Vertrag

### Bericht

`GET /reports/cash`

Filter:

- `date_from`
- `date_to`
- `portfolio_id`
- wiederholtes `property_ids`
- `unit_id`
- `account_id`
- `basis=confirmed_cash|recorded_bookings`
- `as_of`

Response:

- `basis`
- `currency` (EUR)
- `filters`
- `source_hash`
- `income`
- `expense`
- `net`
- `source_count`
- `excluded_count`
- `categories[]`
- `months[]`
- `locations[]`
- ohne Detailseite standardmÃ¤ÃŸig keine nutzbare Belegliste.

Alle Geldwerte sind **dezimal formatierte Strings**. Sie werden in der UI niemals
Ã¼ber `Number`, `parseFloat` oder Float-Arithmetik gerundet.

### Quellbelege

`GET /reports/cash/sources`

ZusÃ¤tzlich:

- `after` opaker Cursor
- `source_hash` zwingend fÃ¼r Folgeseiten
- `limit` 1..500

Response wie Bericht plus:

- `items[]`
- `has_more`
- `next_after`

Ein 409 bei geÃ¤ndertem Quellenbestand bedeutet **keinen Nullbestand**. Die UI
zeigt einen klaren QuellenÃ¤nderungszustand und bietet â€žAuswertung aktualisierenâ€œ;
die angewendeten Filter bleiben erhalten, Cursor und alte Quellseiten werden
verworfen.

### VollstÃ¤ndiger CSV

`GET /reports/cash/export.csv`

- identische Filter wie Bericht,
- Exportiert den **vollstÃ¤ndigen** gefilterten Quellenbestand,
- unabhÃ¤ngig von sichtbarer Belegseite,
- geschÃ¼tzter Blob-Download,
- keine clientseitige Rekonstruktion nur aus aktuell sichtbaren Items.

## ReferenceChoice-Vertrag

Erlaubte Kinds und Filter:

### portfolios

- `search`
- optional `portfolio_id` fÃ¼r exakte Bindung
- `selected_id`
- `cursor`
- `page_size`

### accounts

- `portfolio_id`
- `search`
- `selected_id`
- `cursor`
- `page_size`

Keine Property-/Unitfilter.

### properties

- `portfolio_id`
- `search`
- `selected_id`
- `cursor`
- `page_size`

### units

- `portfolio_id`
- `property_id`
- `search`
- `selected_id`
- `cursor`
- `page_size`

Parentwechsel:

- PortfolioÃ¤nderung lÃ¶scht Account, Properties und Unit.
- Property-AuswahlÃ¤nderung lÃ¶scht Unit.
- Entfernte Parentbindung macht die alte abhÃ¤ngige Auswahl sofort ungÃ¼ltig.
- Keine alte `selected_id`-PrÃ¼fung darf unter einem neuen Parent weiterlaufen.

Der vorhandene `ReferenceChoice` wird unverÃ¤ndert wiederverwendet. Kein neuer
shared Picker.

## Filtermodell

Der Arbeitsplatz hÃ¤lt zwei ZustÃ¤nde getrennt:

### Entwurf

Bearbeitbare Eingaben:

- Zeitraum von/bis
- Stichtag
- Portfolio
- Immobilien
- optionale Einheit
- optionales Konto
- Basis `confirmed_cash` oder `recorded_bookings`

Ã„nderungen am Entwurf starten **keinen** Bericht.

### Angewendete Filter

Erst â€žAuswertung anwendenâ€œ erzeugt einen kanonischen Snapshot der Filter und
lÃ¤dt Bericht + erste Belegseite.

Ein behebbarer Fehler:

- bewahrt den angewendeten Filter-Snapshot,
- bewahrt den Entwurf,
- zeigt keine Nullsummen,
- erlaubt denselben Bericht erneut zu laden.

## Actor-/Grantbindung

Privater Zustand ist gebunden an:

- Benutzer-ID
- Rolle
- Write-/Read-Kontext soweit im Authobjekt vorhanden
- Portfoliozugriff / Portfolio-IDs

Bei Ã„nderung:

- Bericht, Quellseiten, Sourcehash, CSV-Zustand und ausgewÃ¤hlte Referenznamen
  werden render-synchron neutral;
- laufende Report-/Source-/CSV-Requests werden abgebrochen;
- der neue Actor beginnt mit neutralem Filter-/Datenzustand.

Keine alten Finanzsummen dÃ¼rfen wÃ¤hrend des neuen Effects noch sichtbar sein.

## Exakte Geldverarbeitung

Neue Feature-Helfer arbeiten mit MoneyStrings ausschlieÃŸlich als Strings bzw.
ganzzahligen Cent-Strings.

Geplant:

- Validierung `^-?\d+\.\d{2}$`
- Konvertierung MoneyString -> signierter BigInt-Centwert
- Formatierung BigInt-Centwert -> lokalisierter EUR-Text
- keine Floatarithmetik
- Charts/Balken nur aus relativen BigInt-VerhÃ¤ltnissen; der fachliche Betrag
  bleibt immer der Original-MoneyString.

Beispiele:

- `0.10` + `0.20` bleibt exakt `0.30`
- sehr groÃŸe/negative Werte verlieren keine Ziffern.

## Darstellung

### Kennzahlen

- Einnahmen
- Ausgaben
- Saldo
- WÃ¤hrung klar EUR
- Quelle: Zahlungsbasis, nicht â€žGewinnâ€œ oder â€žPeriodenergebnisâ€œ.

### Auswertungen

Tabs/Abschnitte aus denselben Berichtssummen:

- Monate
- Kostenarten
- Objekte/Einheiten

Jede Zeile zeigt:

- Einnahmen
- Ausgaben
- Netto
- Anzahl Quellen

Objektkosten ohne Einheit werden als â€žOhne Einheitâ€œ angezeigt.

### Quellbelege

Separate paginierte Tabelle:

- Buchungsdatum
- Konto
- Kategorie
- Objekt
- Einheit
- Betrag
- Status
- einbezogen / ausgeschlossen
- Ausschlussgrund
- Zahlungstext
- Belegreferenz

Kein Ã¶ffentlicher Beleglink wird behauptet; `receipt_url` ist nur eine
Quellreferenz im Bericht und wird nicht als frei zugÃ¤ngliche Datei behandelt.

## Pagination

Der UI-Zustand hÃ¤lt einen Cursor-Stack fÃ¼r Vor/ZurÃ¼ck.

- erste Seite: `after` leer, `source_hash` aus dem Report
- nÃ¤chste Seite: `after=next_after` + exakt derselbe `source_hash`
- vorherige Seite: gespeicherter Cursor aus dem Stack
- Filter-/Actor-/Sourcehashwechsel lÃ¶scht den Stack

Ein Cursorfehler behÃ¤lt angewendete Filter, aber zeigt keine alte Seite als
aktuell.

## CSV

Button â€žVollstÃ¤ndiges CSV herunterladenâ€œ:

- verwendet exakt die **angewendeten** Filter,
- ruft `/reports/cash/export.csv` als geschÃ¼tzten Blob,
- speichert die Serverdatei direkt,
- kein clientseitiges SeitenzusammenfÃ¼gen,
- laufender Export wird bei Actor-/Filterwechsel abgebrochen.

## Sourcehash-Konflikt

HTTP 409 auf Report-/Sources-Request:

- eigener Zustand â€žBuchungsquellen haben sich geÃ¤ndertâ€œ,
- keine Nullsummen,
- alte private Ergebnisse werden nicht als aktuell gezeigt,
- Button â€žAuswertung aktualisierenâ€œ verwendet dieselben angewendeten Filter,
  startet aber bei Seite 1 und erwartet einen neuen Sourcehash.

## Navigation/Wiring

Neue Route und Sidebar-Eintrag:

- Seite: `FinancialWorkspace`
- Navigation: â€žFinanzauswertungenâ€œ

Nur kleines getrenntes Wiring in:

- `App.jsx`
- `Layout.jsx`
- `i18n.jsx`

Keine Ã„nderung an bestehenden `FormModal`, `ReferenceChoice`,
shared Pickern oder globalem Layout.

## Lokales Feature-Ownership

Neu:

- `features/financialWorkspace/financialWorkspaceApi.js`
- `features/financialWorkspace/financialWorkspaceModel.js`
- `features/financialWorkspace/FinancialFilterPanel.jsx`
- `features/financialWorkspace/FinancialSummary.jsx`
- `features/financialWorkspace/FinancialSources.jsx`
- `features/financialWorkspace/FinancialWorkspace.css`
- `pages/FinancialWorkspace.jsx`
- eigene Tests.

## Nicht in D3

Keine Behauptung oder Implementierung von:

- wirtschaftlichem Periodenergebnis
- AfA
- Leistungsabgrenzung
- Finanzierung
- Vertragsprognose
- Vorperiodenvergleich
- XLSX/PDF-Bericht
- dauerhaften Reportjobs
- neuem Backendendpoint

Die Seite ist ausdrÃ¼cklich eine **Zahlungsbasis-/Cash-Sicht**.

## Geplante leichte PrÃ¼fungen vor Root-Browser-QA

Bis zur Slotabstimmung keine schweren Browser-/Recovery-Gates.

Geplant:

- reine MoneyString-/Filtermodelltests
- API-Vertragstest mit exakten Queryparametern
- ReferenceChoice-Parentinvalidierung
- Actorwechsel render-synchron neutral
- 409-Sourcehash-Recovery
- Cursor-Vor/ZurÃ¼ck
- kompletter CSV-Endpoint statt sichtbarer Seite
- gezielter ESLint
- Produktionsbuild erst im vereinbarten kurzen Slot.

Root Ã¼bernimmt gemeinsame Browser-/Recovery-Abnahme.
