# Übergabe B: Zählerinventar und begrenzte Originalablesungen

Stand 2026-10-03. Eigencheckout `work/bounded-meter-inventory`, Branch
`assist/bounded-meter-inventory`, Ausgangsbasis `3e15341`. Plan vor Code:
`85f3681`; getrennte Rootreservierung des Indexplans: `643652b`.
Der frühere Checkout `work/bounded-legacy-lists` bleibt sauber bei `0f3dc29`.
Root integriert allein; keine Änderungen an Root, Main oder Preview.

## Gelieferter Umfang

Die Meterseite verwendet additive private Lesewege statt `/meters`,
`/meters/readings/all`, `/units` oder `/properties` als Komplettlisten.
Serverfilter und Unicode-Suche erreichen den gesamten autorisierten Bestand;
stabile signierte Keysets liefern `items`, `has_more`, `next_cursor`.
NULL steht zuletzt, Tages-/Sortwertgleichheit hat einen byteweisen ID-Tiebreak.
Cursor sind an Query, Stichtag, Actor/Scope und bei Ablesungen an Meter-ID gebunden.
Die Paketgröße ist konfigurierbar über das bestehende Arbeitsbudget und begrenzt
keinen Bestand. Normale Inventarseiten selektieren zuerst höchstens
`page_size + 1` Meter und holen danach genau deren jüngste originale Ablesung.
Sortierung nach letztem Datum/Stand benötigt entsprechende DB-Projektionen.

Die fünf neuen API-Verträge unter `/api/v1/meters` sind:

| Weg | Inhalt |
| --- | --- |
| `/inventory/page` | Vollständige aktuelle Meterzeile, aktuelle Property/Unit, tatsächlicher letzter Stand, ETag und begrenzte Seite |
| `/inventory/summary` | Vollständige autorisierte Gesamt-, Status-, Ablesungs-, Einheiten- und Prüfdatumzählungen mit denselben Filtern |
| `/inventory/export` | Vollständige gefilterte CSV unabhängig von der sichtbaren Seite, bestehender Snapshotexporter mit Revalidierung und Formelschutz |
| `/inventory/detail/{meter_id}` | Exakte frisch autorisierte vollständige Editquelle mit Originalrevision; fehlend/verborgen 404 |
| `/{meter_id}/readings/page` | Erst nach Öffnen geladene Meterhistorie mit Datum-/Notizsuche und Tagesdatum/ID-Keyset |

Geschützte Referenzen bleiben echte FormModalwerte. Meter- und metergebundene
Readingdrafts verwenden ausschließlich die bestehende private Draftpersistenz.
Wiederhergestellte Originalrevision hat beim PUT Vorrang vor neuem Detailstand.
412 und andere Savefehler erhalten Eingaben. Actor-/Grantwechsel remounten,
abortieren und verbergen private Daten/Formulare; Fehler sind keine leeren Listen
oder Nullkennzahlen. Ein unklarer Create-/Readingerfolg bleibt nach Reload
bewusst zu prüfen und erzeugt keinen automatischen zweiten POST.

Nullable und kundenspezifische Maßeinheiten/Typen sowie Status und bisherige
optionale Stammdaten bleiben erhalten. Ablesungen zeigen unveränderte originale
Zahlen, Datum, Erfassenden und Notizen. Die heutige Stammdateneinheit ist als
aktuell bezeichnet; einzelne Originalablesungen erhalten daraus keine erfundene
historische Einheit oder Verbrauchsrechnung. g2-Historien und bestätigte
Zuordnungen bleiben maßgebliche Abrechnungsquellen.

Der kleinste bestehende Reading-POST-Pfad verweigert einen fremden
`payload.meter_id` bei abweichender URL-ID vor dem Storeaufruf (400 ohne fremde
ID/Typoffenbarung). Eine echte HTTP-Regression mit unberechtigter fremder ID
weist kein Schreiben nach und kontrolliert den weiterhin gültigen 201-Pfad.
Legacyantwortformen bleiben erhalten.

## Index und Zuständigkeitsgrenzen

Rootreservierter `k2a2b3c4d5e6 -> j2a2b3c4d5e6` erzeugt ausschließlich
`ix_meter_readings_latest` auf
`standalone_meter_readings(meter_id, reading_date DESC, id COLLATE BINARY/C DESC)`.
Explizites Alembic `op.create_index` mutiert keine globalen Pythonmetadaten.
Natives SQLite und PostgreSQL belegen zwei Downgrade/Reupgradezyklen, unveränderte
Originale und reale Indexnutzung für Latest-/spätere Ableseseiten mit 10.003
Originalständen. Kein weiterer spekulativer Inventarindex und keine Startup-DDL.

Eigener Code umfasst Meterdienst, Exportwrapper, additive Meterrouter/minimalen
POST-Guard, eigenen Frontendadapter/CSS, eigene Tests und diese Dokumentation.
`Meter`/ORM, `measurement_history*`, historische Quelle-/Abrechnungsmodelle,
Shared FormModal/Referenzen, Privacy, Stores/Scopes, Startup/Recovery/CI,
DataTable/Layout bleiben außerhalb der Produktänderung.

## Ausgeführte Gates, getrennte Läufe

Alle nachstehenden Läufe waren seriell und mit Root koordiniert. Ausschließlich
synthetische lokale Daten; PostgreSQL je Fall im vom Test erzeugten UUID-Schema,
nie `public`. Der echte Browser verwendete Edge, eine frische vollständig bis k2
migrierte SQLiteDB und eigene Ports/Daten. Keine laufenden eigenen Testprozesse.

| Gate | Tatsächliches Ergebnis |
| --- | --- |
| Neue Meter-UI-Suite | 10 PASS, 6,87 s; vorher 9 PASS/1 falscher Pendingbutton-Selector, anschließend vollständiger korrigierter Nachlauf |
| Dienst/HTTP Memory+SQLite | Erstlauf 32 PASS, 2 erwartete SQL-only-Memory-Skips, 6 FAIL wegen unklarer SQL-JOIN-Anker; Produktfix `27fb959`, exakt 6 rote Nachläufe PASS in 26,11 s. Insgesamt 38 distinct PASS, 2 Memory-Skips |
| SQLite native Index + vier betroffene Dienstfälle | 6 PASS, 2 nicht gewählte PG-Fälle, 11,81 s; echte vollständige Alembickette j2/k2, SQLmaterialisierung/Autoflush/10kCSV/lange Historie/Scope nach LIMIT-Patch |
| Weitere SQLite-Null/Tie-Keysets nach LIMIT-Patch | 4 PASS, 36 nicht gewählt, 6,61 s; Seriennummer und Prüfdatum in beiden Richtungen |
| Strikter PostgreSQL-Achtfällelauf | 2 native Index-/EXPLAIN-Fälle PASS, 6 Dienstfälle FAIL in 37,93 s: wiederverwendete alte Lifecyclefixture migrierte ausdrücklich nur a2, e2-Maßeinheit fehlte |
| PostgreSQL nur sechs rote Dienstfälle | Eigene Fixture `aeb5eee` migriert actual head k2; 6 PASS, 0 Skip, 62,98 s. Zusammen 8 distinct PG-PASS, 0 PG-Skip |
| Ein echter Edge-Browserlauf | Genau 3 PASS, 26,9 s, ein Worker, keine Wiederholung; vorher Build PASS in 2,64 s |
| Bestehende FinancePages/RoleControls | 103 PASS, 10 FAIL in 19,21 s; ausschließlich alte Wartungs-/Dokumenten-Rollenfixtures erwarteten die abgelöste generische Tabelle |
| Nur diese zehn alten Rollenfälle | Testfixturefix `9db0ad7`, 10 PASS, 46 nicht gewählt, 5,31 s; keine Produktänderung. Insgesamt 113 distinct bestehende UI-PASS über getrennte Läufe |
| Meterrollen nach Testparametrisierung | 5 PASS, 51 nicht gewählt, 4,12 s |
| Statische Checks | Scoped Ruff, scoped ESLint mit 0 Warnungen, `git diff --check` PASS |

Wiederholte/überlappende Fälle werden nicht addiert. Backend insgesamt 38
Dienst/HTTP-PASS plus 4 native Indexfälle und 6 PG-Dienstfälle = 48 distinct PASS,
2 Memory-Skips. UI insgesamt 10 neue + 113 bestehende = 123 distinct PASS über
die angegebenen Läufe. Kein einzelner durchgehend grüner Gesamt-Erstlauf und
kein Root-Startup-/Recovery-/CI-Abschluss wird daraus behauptet.

Der echte Browser belegt:

1. 27 gefilterte Zähler über zwei Seiten, serverseitig richtiger Latest-Tiebreak,
   31 Originalablesungen über zwei separate Seiten, vollständige 27-ZählerCSV,
   freie/ungeklärte Einheiten, keine verbotenen Komplettlisten.
2. Einheit erst auf zweiter bounded Auswahlseite; verschlüsselter Draft hält
   echte Referenz und ursprünglichen Timestamp, Reload stellt ihn wieder her;
   unabhängiger Writer führt tatsächlich zu HTTP 412, Eingaben bleiben erhalten.
3. Tatsächlich erfolgreicher HTTP 201 wird als 503 verloren; Pendingdraft bleibt
   nach Reload erhalten, begrenzte Historie beweist den gespeicherten Stand,
   bewusstes Verwerfen produziert exakt einen POST und genau eine Ablesung.

Screenshots `meters-1440.png`, `meters-360.png`, `meters-320.png` unter
`frontend/test-results/meter-inventory.pw.mjs-met-d26e2--desktop-and-narrow-screens`
wurden visuell geprüft; Dokumentbreite bleibt innerhalb des Viewports. Die
vollständigen Tabellen scrollen lokal horizontal; Filter/Aktionen umbrechen.
Screenshots und Testreport sind lokale ignorierte Prüfarbeitsprodukte.

## Bekannte Grenzen und Rootintegration

Live-Keysetseiten sind keine Bestandssnapshots. Vollständige Kennzahlen/CSV sind
autorisierte Vollprojektionen; keine beliebige Such-/Sortlaufzeitgarantie.
Der Indexnachweis betrifft die konkreten Meterreadingpläne, nicht jeden
Inventarsortierer. Memoryreferenzarbeit und natives SQL sind getrennt belegt.

Vor diesem B-Umbau gespeicherte Meterdrafts enthalten kein `is_active`-Feld.
Der unveränderte gemeinsame Schemaschutz erkennt diese abweichende Struktur,
bewahrt den Entwurf und blockiert automatisches Restore/Überschreiben. Dieser
Slice migriert keine früheren Draftschemata. Neue Meterdrafts mit Status und
metergebundene Readingdrafts sind vollständig belegt. Auch eine historische
Quellen-UI, historische Einheitenbackfills und neue Billingregeln gehören nicht
zu diesem B-Adapter.

Bereits in Root vorhandene Abhängigkeiten nicht doppelt übernehmen:
`73cc076`/`8241a21` (hier `8fef5be`/`98d6e8d`), echte Domain-j2
`d0e0ab3`/`e2c7652` (hier `1196640`/`5fece6d`) und f2-Metadatenfix
`b64341a` (hier `0866d2b`). Diese wurden auf ausdrückliche Rootanweisung in
den Eigencheckout aufgenommen; gemeinsame Quellen wurden hier nicht parallel
entwickelt.

Eigene Reihenfolge zur Prüfung/Übernahme:

1. `85f3681` – Inventarplan vor Code.
2. `643652b` – getrennter reservierter k2-Indexplan.
3. `028e327` – reine reservierte k2-Migrationsquelle.
4. `72c8a68` – bounded Inventar, Originalablesungen, UI und fokussierte Tests.
5. `3a69634` – eigene Fixtures mit echter j2/k2-Komposition; Journalguards nur
   im wiederverwendeten Testfixture installiert, zentrale Runtime bleibt Root.
6. `27fb959` – expliziter SQL-FROM/Detailanker.
7. `09193fb` – native k2-/EXPLAIN-Regressionsquelle.
8. `e7d26c1` – normale Meterseite zuerst begrenzen, Latest danach verbinden.
9. `aeb5eee` – PG-Dienstfixture gegen tatsächlichen vollständigen Head.
10. `9db0ad7` – alte Wartungs-/Dokumenten-Rollenfixtures aktualisiert.
11. Abschließender Handoffcommit – dieses Dokument.

Root muss die kombinierte Runtime-/Recovery-/Registry-/CI-Komposition auf seiner
aktuellen Basis selbst prüfen. Dieser Handoff verändert deren Quellen nicht.
