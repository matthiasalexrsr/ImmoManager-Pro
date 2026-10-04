# Immobilienübersicht – serverseitiges Inventory: Vorcodeplan

Stand: 04.10.2026

Worktree: `work/financial-workspace-browser-qa`
Root-Referenzstand read-only: `103482a25cfdae4b8712b8f90f45f932e1b80a07`

Dieses Dokument ist ausschließlich Vorcodeanalyse. Es definiert keine produktive
Route und implementiert keine API-Anfrage. Root legt den tatsächlichen
Backendvertrag und die finalen Endpointpfade erst nach dieser Abstimmung fest.

## Gelesene Referenzquellen

Read-only geprüft:

- `frontend/src/pages/Properties.jsx`
- `frontend/src/pages/Properties.css`
- `frontend/src/features/unitInventory/read.js`
- `frontend/src/features/unitInventory/ReferenceChoice.jsx`
- `frontend/src/features/unitInventory/UnitInventory.jsx`
- `frontend/src/features/unitInventory/UnitInventory.css`
- `backend/services/unit_inventory.py`

Keine privaten Bestandsdaten oder Zugangsdaten wurden gelesen.

## Ist-Zustand

`Properties.jsx` lädt heute drei breite Bestände in den Browser:

1. alle sichtbaren Properties über `api.getAll('/properties')`,
2. alle sichtbaren Units über DataStore/`/units`,
3. alle sichtbaren Maintenance-Fälle über DataStore/`/maintenance`.

Zusätzlich wird der Portfoliobestand vollständig geladen.

Der Browser berechnet danach pro Property:

- Portfolio-Name,
- Einheitenzahl,
- vermietete Einheiten,
- leerstehende Einheiten,
- Auslastung,
- gesamte monatliche Kaltmiete,
- offene/in Bearbeitung befindliche Wartungsfälle.

Suche, Portfoliofilter, Status-/Prüffilter und Sortierung laufen ebenfalls über
den vollständig geladenen Bestand.

## Bestehende Nutzerfunktionen, die erhalten bleiben

### Suche

Serverseitig mindestens über:

- Property-Name
- Straße
- PLZ
- Stadt
- Portfolio-Name
- Property-Type.

### Filter

Bestehende Bedienbegriffe:

- Alle
- Aktiv
- Inaktiv
- Leerstand vorhanden
- Offene Wartung vorhanden
- Portfolio.

### Sortierung

Bestehend:

- Name
- Stadt
- monatliche Kaltmiete.

Künftig vollständig serverseitig und stabil.

### Ansichten

- Kartenansicht
- Tabellenansicht.

Beide verwenden ausschließlich dieselbe aktuelle Serverseite.

### Detailnavigation

Unverändert:

- Karte → `/properties/{id}`
- Tabellenzeile/-name → `/properties/{id}`.

Kein neues Property-Detail-, Einheiten-History- oder Historymodul.

## Übernehmbares Muster aus UnitInventory

`unit_inventory.py` und dessen UI zeigen bereits das gewünschte Muster:

- scope-gebundene serverseitige Query,
- Unicode-/Casefold-Suche,
- serverseitige Filter,
- serverseitige Sortierung,
- stabile Keysetpagination mit Sortwert + ID,
- opaker Cursor,
- Cursorbindung an Query + Scope,
- page_size-Budget,
- Vollmengen-Kennzahlen getrennt von der sichtbaren Seite,
- render-synchrone Principalbindung,
- Abort bei Wechsel/Unmount,
- Cursortrail für Vor/Zurück,
- bounded `ReferenceChoice`,
- keine anwachsende Stockliste.

Properties soll dieses Muster fachlich übernehmen, ohne UnitInventory/shared
Helfer umzubauen.

# Minimal benötigter Backendvertrag

Die API existiert noch nicht. Deshalb werden nur logische Operationen und
DTO-Semantiken festgelegt. Root bestimmt später die konkreten Routes.

## Logische Operation A: PropertyInventoryPage

### Query

Mindestens:

```
search: string | null
portfolio_id: string | null
status: "active" | "inactive" | null
view: "all" | "vacancy" | "open_maintenance"
sort_by: "name" | "city" | "monthly_cold_rent"
sort_order: "asc" | "desc"
page_size: integer
cursor: opaque string | null
```

Semantik:

- search trimmen; leer → null,
- Steuerzeichen ablehnen,
- vacancy = mindestens eine sichtbare Unit mit Status vacant,
- open_maintenance = mindestens ein sichtbarer Fall mit open/in_progress,
- Sortierung vollständig serverseitig,
- stabile Tie-Break-Sortierung über Property-ID,
- fehlende Mietwerte bei Mietsortierung deterministisch zuletzt,
- page_size mit Servermaximum,
- Cursor opak.

### Cursorbindung

Cursor bindet mindestens:

- User/Role/Portfolio-Scope,
- vollständige Query ohne Cursor,
- Sortierung,
- Seitengröße.

Nach Actor-/Grant-/Filter-/Sortwechsel wird der alte Cursor ungültig.

Bei ungültigem Cursor:

- klarer 422-artiger Fehler,
- UI bietet erste Seite neu laden,
- alte Seite wird nicht als aktuell ausgegeben.

Keine Offsetpagination.

## PropertyInventoryItem

Mindestens:

```
id
portfolio_id
portfolio_name
name
property_type
status
address_line
postal_code
city
country

unit_count
occupied_count
vacant_count
occupancy_percent

monthly_cold_rent
monthly_cold_rent_complete

open_maintenance_count

edit_etag | äquivalente bestehende Revisionsinformation
```

### Aggregatsemantik pro Property

`unit_count`:
alle aktuell sichtbaren Units der Property.

`occupied_count`:
heutige Semantik beibehalten: status in {occupied,rented}.

`vacant_count`:
status == vacant.

`occupancy_percent`:
ganzzahlig, klar gerundet; null bei null Units.

`monthly_cold_rent`:

- serverseitig exakt aggregiert,
- bevorzugt Decimal/MoneyString statt Browser-Float-Summe,
- null, wenn die heutige Vollständigkeitsregel nicht erfüllt ist.

`monthly_cold_rent_complete`:
true nur, wenn alle zugehörigen Units eine Kaltmietangabe besitzen.

Unvollständige Mietbasis darf nie als 0 € erscheinen.

`open_maintenance_count`:
Anzahl open/in_progress im aktuellen Scope.

## Logische Operation B: PropertyInventorySummary

Kennzahlen gelten für den vollständigen gefilterten Trefferbestand, nicht nur
die sichtbare Seite.

Mindestens:

```
total_properties
total_units
occupied_units
vacant_units
occupancy_percent
```

Semantik:

- total_properties = vollständige Anzahl der Querytreffer,
- total_units = Summe der Units über alle Treffer,
- occupied_units = vollständige occupied/rented-Semantik,
- vacant_units = vollständige Leerstandssumme,
- occupancy_percent = null bei null Units, sonst klar gerundet.

Kein `items.length` als Fake-Gesamtzahl.

Root kann zwei Reads analog UnitInventory oder eine gemeinsame
Page+Summary-Response wählen. Bei zwei Reads müssen beide dieselbe
Query-/Scope-Semantik besitzen. Bei Summaryfehler zeigt die UI keine Nullen.

Ein Snapshot-/Source-Token wird nur verwendet, falls Root ihn tatsächlich als
Backendvertrag definiert; das Frontend erfindet keinen.

# Portfolioauswahl ohne Vollbestand

Der Portfoliostock soll nicht als neue Vollbestandsabhängigkeit erhalten
bleiben.

Für Filter und Property-Formular soll der vorhandene bounded
`ReferenceChoice kind="portfolios"` genutzt werden:

- search,
- selected_id,
- opaker Cursor,
- page_size 25,
- aktuelle Scopeprüfung.

Kein vollständiges `/portfolios`-Array nur für Dropdowns.

# Geplantes Frontend-Zustandsmodell nach Backendfreigabe

Noch nicht implementiert.

## Principalbindung

Wrapper-Key analog UnitInventory:

`principalKey(useAuth()?.user)`

bindet:

- User-ID,
- Rolle,
- portfolio_access,
- portfolio_access_origin,
- sortierte portfolio_ids,
- sortierte write_permissions.

Bei Wechsel:

- alte Page synchron weg,
- alte Summary synchron weg,
- Cursortrail weg,
- alter Portfolio-Name weg,
- laufende Reads/Detailopens/Exports aborten,
- Modal des alten Actors nicht übernehmen.

## Queryzustand

Ein kanonischer Filterzustand:

```
search
portfolio_id
status
view
sort_by
sort_order
```

Filteränderung:

- Cursortrail zurück auf erste Seite,
- Page neu laden,
- Summary mit denselben Filtern neu laden.

Suche:

- serverseitig,
- kurze Debounce-/Deferred-Strategie möglich,
- kein Browserfilter auf Page-Items.

## Pagination

Analog UnitInventory:

- trail = [null],
- Next hängt nur next_cursor an,
- Previous kürzt den Trail,
- Page-Items werden ersetzt statt zu einem Gesamtcache angehängt.

Statuszeile „25 von 143 Treffern“ nur mit echtem summary.total_properties.

# Kartenansicht

Sichtbar bleiben:

- Portfolio + Typ,
- Name,
- Adresse,
- Status,
- Einheitenzahl,
- Auslastung,
- monatliche Kaltmiete,
- Leerstandsignal,
- offene Wartung.

Unvollständige Mietbasis:

- „Angaben unvollständig“ oder „—“ mit Hinweis,
- niemals 0 €.

Edit/Delete bleiben nach vorhandenem Schreibrecht verfügbar.

# Tabellenansicht

Dieselben Page-Items wie die Kartenansicht.

Spalten:

- Property/Adresse
- Portfolio
- Units
- Auslastung
- monatliche Kaltmiete
- offene Wartung
- Status.

Keine zweite lokale Sortierung, Pagination oder Suche.

Falls DataTable lokale Sortier-/Filterlogik erzwingt, soll die spätere
Implementierung eine lokale semantische Tabelle in Properties verwenden; Shared
DataTable wird nicht verändert.

# Detail- und Editnavigation

## Details

Bestehend lassen: `/properties/{id}`.

## Edit

Ein Listenitem muss nicht alle Editfelder enthalten.

Vor Edit-Modal:

- bestehendes Property-Detail über vorhandenen CRUD-Read frisch laden,
- ID prüfen,
- aktuellen ETag/Revision übernehmen,
- Request bei Actor-/Scopewechsel aborten.

Keine Historymodule entwickeln.

## Delete

Revision-/ETag-Schutz beibehalten.

Nach Delete:

- Page + Summary neu laden,
- falls Seite leer wird sinnvoll zurück/erste Seite,
- keinen Browserstock manuell mutieren.

# Fehlerzustände

## Initial

- eigener Page-Loadingzustand,
- Summary separat „Kennzahlen werden berechnet“.

## Pagefehler

- keine alte Page als aktuell,
- Filter bleiben erhalten,
- Retry derselben Query/Page,
- 401/403/404 → Zugriff geändert/neutral.

## Summaryfehler

- gültige Liste darf nutzbar bleiben,
- Kennzahlen „nicht verfügbar“/„—“,
- niemals vier Nullen.

## Cursorfehler

- „Listenseite ist nicht mehr gültig“,
- explizit erste Seite neu laden,
- kein stilles Replay mit anderem Cursor.

## Kindaggregate

Units/Maintenance werden künftig serverseitig in die Pageprojektion
eingerechnet. Die Übersicht lädt dafür keine vollständigen Childbestände mehr.

# Leerzustände

Unterscheiden:

1. Keine Properties im aktuellen Scope
   - echter Bestandsleerzustand
   - bei Schreibrecht CTA „Immobilie anlegen“.

2. Keine Filter-/Suchtreffer
   - Filterleerzustand
   - CTA „Filter zurücksetzen“.

3. Fehler
   - niemals als leer darstellen.

# Aktualisieren

„Aktualisieren“:

- laufende Page-/Summaryreads aborten,
- Query behalten,
- Cursor auf erste Seite,
- Page + Summary neu laden.

Kein erneutes Volladen von Units/Maintenance/Properties.

# 320 / 360 / 1440

## 1440

- vier Kennzahlkarten in einer Reihe,
- kompakte Toolbar,
- mehrspaltiges Kartenraster,
- Tabelle nutzt verfügbare Breite.

## 360 / 320

- Kennzahlen 2×N oder 1×N ohne Mindestbreitenüberlauf,
- Suche volle Breite,
- Portfolio-/Sortierfelder stapeln,
- Filterchips umbrechen,
- Hauptaktion mindestens 44 px,
- Karten einspaltig,
- Tabelle ausschließlich im eigenen horizontalen Scrollcontainer,
- Pager umbrechbar,
- lange Namen/Adressen/Portfolios overflow-wrap:anywhere,
- documentElement selbst ohne Horizontaloverflow.

# Tastatur/Fokus

- Suchfeld mit zugänglichem Namen,
- Filterbuttons aria-pressed,
- Viewswitch aria-pressed,
- Pager als nav,
- Tabellen-Scrollregion fokussierbar,
- Cardname echter Link,
- Edit/Delete echte Buttons,
- Fokus nach Modalclose nach bestehender Modalpraxis.

# Write-Verhalten

Bestehende Property-CRUD-Commands bleiben unverändert.

Create/Edit/Delete verwenden weiterhin die bestehenden CRUD-Routen.

Nur die Übersichtslade-/Filterarchitektur wird nach Backendfreigabe ersetzt.

Create/Edit-Formular:

- Portfolioauswahl künftig bounded,
- Shared FormModal nicht verändern.

# Spätere Akzeptanzfälle

Nach bestätigtem Backendvertrag sollen mindestens geprüft werden:

1. Page 1 bleibt im Serverbudget.
2. Summary zählt >Seitengröße vollständig.
3. Suche findet späte Treffer ohne Browserstock.
4. Portfoliofilter wird serverseitig gebunden.
5. Aktiv/Inaktiv/Vacancy/Open-Maintenance sind serverseitig.
6. Name/Stadt/Miete sortieren stabil über Seiten.
7. Page 2 nutzt opaken Cursor mit identischer Query.
8. Filteränderung verwirft alten Cursor.
9. Actor-/Grantwechsel neutralisiert Page/Summary im ersten Render.
10. Pagefehler zeigt keine alte Page.
11. Summaryfehler zeigt keine Nullkennzahlen.
12. Cards/Table verwenden dieselben Page-Items.
13. Detailnavigation bleibt /properties/{id}.
14. Edit lädt volle Property frisch.
15. 320/360/1440 ohne Seitenüberlauf.

# Explizit nicht Teil dieses Vorcodepakets

- keine neuen produktiven Requests,
- keine neuen Routes,
- kein Frontendproduktcode,
- keine Backendänderung,
- keine Shared-Componentänderung,
- keine Tests/Collection,
- kein Build,
- kein Browser,
- keine DB,
- keine App-/Serverstarts,
- keine Einheiten-History,
- keine Property-History,
- keine privaten Daten.

## Backend-Blocker für den nächsten Schritt

Frontendimplementierung beginnt erst nach Root-Handoff mit:

- finalen Route(s),
- Queryfeldnamen,
- Sortierwerten,
- Page-DTO,
- Summary-DTO oder kombinierter Response,
- Cursor-/Scope-Bindung,
- maximaler Seitengröße,
- Rent-Aggregatsemantik,
- Maintenance-Aggregatsemantik,
- Revision/ETag im Listenitem,
- 401/403/404/422-Semantik.

Bis dahin bleibt `Properties.jsx` unverändert.
