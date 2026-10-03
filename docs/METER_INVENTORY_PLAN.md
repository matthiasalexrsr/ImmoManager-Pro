# B: vollständiges Zählerinventar und begrenzte Ableselisten

Plan vor Quelländerungen, 2026-10-03. Basis: `3e153413feb7455b3f957ba84d42e60b44f1b2a7`;
Checkout `work/bounded-meter-inventory`, Branch `assist/bounded-meter-inventory`.
Der vorherige Checkout `work/bounded-legacy-lists` bleibt sauber erhalten.

## Freigabe, belegter Bestand und Zuständigkeit

Grundlage sind der vollständig freigegebene A–L-Plan in
`IMPLEMENTATION_ROADMAP_20261003.md`, `BOUNDED_LISTS_PLAN.md`,
`P0_CONSUMPTION_BILLING_PLAN.md`, `PACKAGE_C_MEASUREMENT_HISTORY_PLAN.md`,
dessen Handoff sowie `DURABLE_SCHEDULER_PLAN_20261003.md`. B erweitert die
vollständig erreichbare Bestandsarbeit; C erhält historische Originalquellen;
E und Startup/Recovery bleiben Root zugeordnet. Maßgeblich ist die aktuelle
Root-Zuteilung, nicht ältere Besitzerzeilen in Dokumenten.

Eigenbesitz: neuer Inventardienst, additive kleinste Meterrouter-Erweiterung,
eigenes Meterfrontend, gezielte Tests und Dokumentation. `Meter`/`MeterORM`
werden ausschließlich gelesen. Keine Änderungen an `measurement_history*`,
Quelle-/Abrechnungsmodellen, Privacy, zentralen Stores/Repositories/Scopes,
Shared FormModal/Referenzen, Startup/Recovery/CI, DataTable/Layout oder Root,
Main und Preview. Root allein integriert und reserviert Migrationen;
Domain besitzt die aktuelle j2→h2-Komposition.

Tatsächliche Datenwege:

- `Meters.jsx` lädt `/meters`, `/meters/readings/all`, `/units` und
  `/properties` vollständig über `useFinanceData`. Die Anzeige gruppiert
  und sortiert sämtliche Ablesungen im Browser. Die Kennzahlen und CSV
  hängen dadurch am vollständig materialisierten Bestand.
- `routers/meters_standalone.py` bietet bestehendes Meter-CRUD und
  Standalone-Ablesungen. Der einzelne alte Ableseweg filtert erst nach
  `store.list_standalone_meter_readings()`. Handover-`MeterReading` ist eine
  andere Familie und wird nicht ersetzt.
- `MeterCreate` fordert `unit_id` und beliebiges `meter_type`. Die nullable
  `measurement_unit` wird validiert, aber nicht aus dem Typ abgeleitet.
  Vertragshinweise, Termine, Standort, Anbieter und `is_active` existieren.
- `StandaloneMeterReading` speichert `meter_id`, Tagesdatum, Floatwert,
  Erfassenden, Foto und Notizen; keine historische Maßeinheit oder
  historische Einheitenzuordnung. Gleiche Tagesdaten brauchen einen
  expliziten ID-Tiebreak. Floatwerte werden nicht heimlich konvertiert.
- SQL liegt im `SQLAlchemyStore`/FinanceRepository; Memory in den tatsächlichen
  `meters`-/`standalone_meter_readings`-Dictionaries. Core-Lesewege benötigen
  explizites `scoped_clause`, Memory `memory_visible`, beide frische
  Benutzerbindung vor/nach dem Lesen. Keine globalen `list_*`-Hilfsaufrufe.
- `measurement_parent_guards` und immutable g2-Fakten schützen Originale.
  Eine heutige Meter→Unit-Zuordnung ist keine historische Zuordnung;
  bestätigte Fakten bleiben die Abrechnungsgrundlage. Deren Dienste,
  Originalabrufe, Privacy-Fence und Locks bleiben unverändert.

## Additive Leseverträge

1. `/meters/inventory/page`: validierte Filter, `items`, `has_more`,
   `next_cursor`; `page_size` ist ein Paketlimit, kein Bestandslimit.
   Jede Zeile enthält vollständige Meterstammdaten, aktuelle Property/Unit-
   Bezeichnung/IDs, `edit_etag` und ausschließlich den tatsächlich jüngsten
   Standalone-Stand mit Datum/ID. Fehlende Ablesung bleibt ausdrücklich null.
2. `/meters/inventory/summary`: vollständige autorisierte SQL-Aggregate über
   denselben Filter: Gesamtzahl, aktiv/inaktiv, ohne Ablesung, ungeklärte
   Maßeinheit, überfällige und binnen 30 Tagen fällige Prüfung. Ein expliziter
   Tagesstichtag verhindert verschiedene Bewertungen zwischen Seiten.
   Kein Gesamtverbrauch oder Summieren verschiedener physikalischer Einheiten.
3. `/meters/inventory/export`: vollständiger gefilterter CSV-Export unabhängig
   von der sichtbaren Seite. Wiederverwendung des bestehenden Snapshot-
   Exporters mit begrenzten Paketen, CSV-Formelschutz und Revalidierung von
   Benutzer/Grants sowie aktueller autorisierter Projektion vor jedem Paket.
   Originale Rohwerte einschließlich kundenspezifischer Typen/Einheiten
   bleiben im Export erhalten. Ein Seitencursor beim Gesamtexport wird abgelehnt.
4. `/meters/inventory/detail/{meter_id}`: exakte vollständige, frisch
   autorisierte Editquelle samt ursprünglicher Revision. Keine Rekonstruktion
   aus Tabellen-/Auswahlprojektionen. Fehlend oder verborgen ergibt 404.
5. `/meters/{meter_id}/readings/page`: eigenständige begrenzte Standalone-
   Ableseseite, Datum-von/bis und Textsuche über Erfassenden/Notizen,
   Tagesdatum+Bytewise-ID-Keyset, Standard neueste zuerst. Der Meter wird vor
   dem Lesen exakt autorisiert, um fehlend/verborgen von wirklich leer zu
   unterscheiden. Response enthält `items`, `has_more`, `next_cursor`.
   Kein Lesen aller anderen Meter oder aller Ablesungen. Alte öffentliche
   Listen-/CRUD-Antwortformen bleiben kompatibel.

Inventarfilter: Unicode-Casefold-Suche über Seriennummer, Typ, Maßeinheit,
Standort, Anbieter, Vertragsnummer und aktuelle Property/Unit-Bezeichnung;
exakte Property-/Unit-/Typ-/Anbieter-/Einheitenfilter, aktiv/inaktiv,
Prüfansichten (ohne Ablesung, ungeklärte Maßeinheit, überfällig, in 30 Tagen),
Prüfdatumgrenzen. Frei gespeicherte Textwerte müssen auswählbar/erreichbar
bleiben. SQL-LIKE-Metazeichen werden wörtlich behandelt.

Stabile Sortierung über whitelisted Seriennummer, Typ, Maßeinheit,
Property/Unit, Anbieter, Prüfdatum und letztes Ablesedatum/Stand. NULL immer
zuletzt, Bytewise-ID als zweite Komponente in gleicher Richtung; gleiche
Werte/Tagesdaten gehen nicht verloren. Signierter Cursor bindet Query,
Sortierung, Seite, Stichtag, Actor/Scope, im Ableseweg zusätzlich Meter-ID.
Geänderte Filter oder Grants benötigen die erste Seite.

## Begrenzte SQL- und Memory-Arbeit

Der SQL-Basisselektor verbindet Meter→Unit→Property und deren autorisierte
Projektion. Die letzte Ablesung wird durch einen korrelierten
`ORDER BY reading_date DESC, id COLLATE BINARY/C DESC LIMIT 1`-IDselektor
und Join auf genau diese Ablesung geliefert: kein globales Window über
alle Historien, kein ORM-N+1, keine vorherige Komplettliste. Für die normale
Inventarseite materialisiert die Anwendung höchstens `page_size + 1` Meter
und maximal deren eine letzte Ablesung. Letztstandfilter/-sortierungen und
vollständige Aggregate benötigen die zugehörigen DB-Prädikate, aber keine
unbegrenzte Python-Ergebnisliste. Jeder Leseweg läuft ohne Autoflush.

Die Ableseseite liest höchstens `page_size + 1` Zeilen des ausgewählten
Meters. Memory-Referenzarbeit darf den vorhandenen Bestand durchlaufen,
verwendet aber begrenzte Auswahlheaps und keine vollständigen sortierten
Historien-/Meterkopien; SQL-Skalierungsnachweise werden davon getrennt.

## Oberfläche und bestehende Schreibabläufe

Eigene `meterInventory`-Featuredateien ersetzen nur die Meterseite. Gemeinsam
erprobte `useInventory`, `usePrivateRead`, `ReferenceChoice`,
`revisionOptions` und FormModal werden verwendet, nicht parallel kopiert.
Eindeutige Lade-, Fehler-, Zugriff- und Leerzustände; Kenngrößenfehler dürfen
keine Nullzahlen vortäuschen. Desktop/Mobil haben zugängliche Filter,
Lesen/Anlegen/Bearbeiten/Löschen, CSV und Vor-/Zurückseiten ohne wachsenden
Datensatzcache. Eine geladene Meterdetailquelle und eine Ableseseite bleiben
auch bei Inventarseitenwechsel nachvollziehbar.

Meteranlage/-bearbeitung erhält dauerhafte `draftConfig` für `meters`.
Property-/Unitwahl sind geschützte bounded Referenzen; `unit_id` muss echter
FormModal-Wert sein. Aktuelle Basis 3e15341 enthält noch kein `field.render`:
Root integriert das bereits fertige Draftpaket; vor UI-Implementierung wird
dessen bestätigter Nachfolgecommit in diesen eigenen Checkout aufgenommen.
Keine erneute Sharedänderung oder zweite Draftpersistenz.

Exact Detail öffnet erst nach Prüfung von ID, vollständiger Quelle und
Revision. Wiederhergestellte ursprüngliche Revision im Payload hat beim
Speichern Vorrang vor späterem Detailstand. Fehler/412 erhalten Eingaben;
bei Actor-/Grantwechsel abortieren und verbergen sämtliche privaten
Requests/Formulare/Exporte. Status `is_active` sowie bestehende optionale
Felder bleiben editierbar; bekannte und kundenspezifische Typen/Einheiten
werden nicht umgeschrieben. Nullable Maßeinheit bleibt sichtbar ungeklärt.

Bestehende Ablesungseingabe bleibt erhalten und nutzt den exakt geöffneten
Meter (kein All-Meters-Auswahlcache). Nach Erfolg werden Inventar/aktuelle
Ableseseite neu geladen. Bestehende Foto-/Notizdaten bleiben unangetastet.
Die aktuelle Stammdateneinheit wird als aktuell bezeichnet. Einzelne alte
Ablesungen werden nicht mit dieser heutigen Einheit historisch etikettiert;
die bisherige Browser-`consumption`-Spalte darf keinen unbelegten Verbrauch
aus mutable Stammdaten ableiten. Die Originalstände bleiben sichtbar.

Unklarer Create-/Ablese-POST-Erfolg führt zum bewusst zu prüfenden Bestand,
keinem automatischen Wiederholungs-POST. Meterdrafts nutzen die bestehende
pending-Bestandprüfung. Ablesungseingabe bewahrt Fehlerwerte und fordert
bei verlorenem Ergebnis vor einer Wiederholung die gezielte Ableselisten-
prüfung; keine neue serverseitige Idempotenzbehauptung. Vorhandene Routen-
lücke: der Reading-POST prüft den URL-Meter, schreibt aber `payload.meter_id`.
Der kleinste Routerfix verweigert mismatching IDs vor dem unveränderten
Store-Aufruf; kein stilles Umhängen, historische Quellen bleiben unverändert.

## Getrennter Indexplan – keine DDL-Freigabe

Die tatsächlichen Meter-/Standalone-ORMs und vorhandenen Migrationen haben
keinen passenden Ableseindex. Vorschlag zur Root-Reservierung:
`standalone_meter_readings(meter_id, reading_date DESC, id COLLATE BINARY/C DESC)`.
Dieser Index unterstützt letzte Ablesung und keysetbasierte Detailhistorie.
Zusätzlich nach realem EXPLAIN-Nachweis prüfen:
`meters(unit_id, id COLLATE BINARY/C)` und häufig genutzte Prüfdatumordnung.
Keine Vielzahl spekulativer Sort-/Suchindizes, keine implizite Startup-DDL,
keine Änderung bestehender Migrationen oder ORM-Metadaten in diesem Slice.
Neue Alembic-ID/Parent und DDL gehören zu einem separat von Root reservierten
Commit nach Abgleich mit j2→h2. Ohne Index wird nur begrenzte Materialisierung,
keine indexgestützte Laufzeit oder beliebige Bestandsgröße behauptet.

## Geplante ehrliche Gates und Reihenfolge

Nach Plancommit zuerst Service/Router und gezielte Backendtests, dann eigener
UIadapter und dessen Tests. Source-/statische Checks sind jetzt freigegeben;
Root belegt aktuell PG-Lauf 22889. Keine PostgreSQL-, Browser- oder großen
Testläufe vor koordinierter Slotfreigabe.

- Memory plus natives SQLite: spät auffindbare Zähler (>100/1.000/10.000),
  vollständige Aggregat-/CSV-Zahl, gleiche/null Sortwerte beide Richtungen,
  heutige Zählerzuordnung, originale freie Maßeinheit, stabile jüngste
  Ablesung bei gleichem Tag und eine große Historie eines einzelnen Meters.
  Verbot aller globalen Listenleser. Capture SQL/Ergebnismaterialisierung:
  begrenzte Seiten/Detail, kein Autoflush und keine Write-/DDL-Anweisungen.
- HTTP/Scope: Authentifizierung, private/no-store/Vary, gefilterte Inhalte,
  fremde Meter/Ablesungen, Cursor-Tampering/Query/Actorbindung, frischer
  Rechteverlust unmittelbar vor Veröffentlichung, Exportabbruch bei
  Revocation oder parallel veränderter Meter/Unit/Property/letzter Ablesung.
  Mismatching Reading-POST schreibt nichts; alte Antwortformen bleiben.
- PostgreSQL erst im exklusiv abgestimmten Slot: dieselbe stabile letzte
  Ablesung/Keyset/Scope/Export-Komposition im eigenen UUID-Schema. EXPLAIN
  und Indexgate getrennt nach Rootreservierung; kein `public`, PrivatDB,
  Liveprovider oder fremde Service-/Prozessbeendigung.
- UI: keine Legacy-All-Leser; Seiten/Filter/CSV, error vs leer, exaktes Edit,
  komplette restored Meterdraft-/Unitreferenz/Originalrevision, 412-
  Eingabenerhalt, unbekannte Maßeinheit, Actor-/Grant-Abbruch, begrenzte
  Ableseseiten und erhaltene Eingabe einschließlich unklarer POST-Recovery.
  Bestehende generische Finance-/Role-Tests werden nur für den abgelösten
  Meterkontrakt gezielt angepasst, ihre übrigen Erwartungen bleiben.
- Ein koordinierter echter Browserlauf mit synthetischen Daten: 320/360/1440,
  spät gefundener Zähler, Seiten-/Historienwechsel, freie/fehlende Einheit,
  Draftreload mit originaler Revision und unabhängiger Writer-412 sowie
  erfolgreich gespeicherter/verlorener POST→Bestandprüfung. Tatsächliche
  Teilläufe/Fehler/Skips separat protokollieren. Build/Lint/diff-check und
  saubere Quell-/Handoffcommits, Root erhält exakte Hashes und Restgrenzen.

### Belegte Präzisierung während der Umsetzung

Rootfreigegebene Indexreservierung k2→j2 wurde separat geplant und als
reiner Sourcepatch vorbereitet; DDL bleibt bis zum abgestimmten Graph-/Slotgate
aus. Die bestehende private Draftpolicy unterstützt bereits ausdrücklich
`meters/readings`/`StandaloneMeterReading`; deshalb verwendet die erhaltene
Ableseeingabe dieselbe FormModalpersistenz mit metergebundenem
`formKey=meter:<id>`. Damit bleiben Eingabe und unklarer POST-Erfolg auch nach
Reload prüfbar, ohne eine zweite Persistenz oder neue serverseitige
Idempotenz. Erfolgreiche Ablesungen laden die erste Detailseite neu.

Kein Fortschritt von E, keine fertige historische Quellen-UI, kein vollständiger
Startup-/Recoverybeleg und kein indexgestützter Laufzeitnachweis werden aus
diesem B-Adapter abgeleitet.
