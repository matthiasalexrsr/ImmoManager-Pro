# P0 Verbrauchsabrechnung: Übergabe

Stand: 3. Oktober 2026. Arbeitsbasis `679c8de`, Branch
`assist/p0-consumption-billing`. Keine UI-, Startup- oder History-Änderungen.

## Verhalten

Ein Kostenschlüssel verwendet nur Zähler seines ausdrücklich deklarierten
Mediums und seiner Maßeinheit. Der Gegenfall Wasser 10 m³ + Strom 1000 kWh
gegen Wasser 10 m³ verteilt Wasserkosten daher 50:50. Ein zusätzlicher
Stromkostenschlüssel hat seine eigene Grundlage. Ein einzelner belegter
Nullverbrauch ist zulässig. Unvollständige oder widersprüchliche Quellen
blockieren vor dem Schreiben und liefern bearbeitbare Vorprüfungsbefunde.
Personenanteile benötigen `Unit.person_count`; `rooms` ist kein Ersatz mehr.

Vorprüfung und Erzeugung verwenden denselben reinen Prüfer
`backend/services/billing_consumption.py`. Die bestehende Quellenrevision
erfasst die neuen DTO-Felder automatisch: Nach deren Änderung müssen Entwürfe
neu erzeugt werden. Finalisierte Abrechnungen werden nicht neu berechnet.

## Formular- und API-Vertrag für Root

| DTO | Feld | Bedeutung |
| --- | --- | --- |
| `AllocationKeyCreate`, `AllocationKeyPatch`, `AllocationKey` | `consumption_medium: str \| null` | Exakte Zuordnung zu `Meter.meter_type`, z. B. `cold_water`, `hot_water`, `electricity`, `heating`, `gas`. |
| dieselben | `consumption_unit: str \| null` | Tatsächliche physikalische Einheit, z. B. `m³` oder `kWh`. |
| `MeterCreate`, `MeterPatch`, `Meter` | `measurement_unit: str \| null` | Deklarierte Originaleinheit der vorhandenen Zählerstände. |

Die bestehenden Endpunkte speichern diese Felder vollständig in Memory/SQL:

- `POST /api/v1/billing/allocation-keys`,
  `PATCH /api/v1/billing/allocation-keys/{id}`; vorhandenes PUT ebenfalls.
- `POST /api/v1/meters`, `PATCH /api/v1/meters/{id}`.
- `GET /api/v1/billing/periods/{id}/preflight` liefert Befunde;
  `POST .../{id}/generate` verweigert eine ungeklärte Grundlage mit HTTP 400.

Bestehende ETag-/If-Match-, Berechtigungs- und Finalisierungsregeln gelten
weiter. Null darf gespeichert werden, damit Altdaten und Entwürfe schrittweise
reparierbar bleiben. Leer-/Whitespace-Zeichenketten werden abgewiesen; äußere
Leerzeichen werden entfernt. Keine Schreibweisen-, Einheiten- oder
Medienableitung aus Namen, Notizen, Kostenbeschreibungen oder Zählertyp.

Die Oberfläche soll beide Schlüsselangaben bei `key_type=consumption` sowie
die Zählereinheit bearbeitbar machen. Vorschläge dürfen bestehende tatsächliche
Zählertypen anbieten; keine automatische Bestätigung für Altbestände.
Eine Änderung der Einheit bedeutet eine Stammdatenkorrektur, keine Umrechnung
der Messwerte. Originalbelege müssen die korrigierte Deklaration bestätigen.
Bereits finalisiert verwendete Schlüssel bleiben geschützt: eine neue Fassung
anlegen und ausschließlich Entwurfskosten auf diese umstellen.

## Befunde und sinnvolle Reparatur

| Code | Reparatur |
| --- | --- |
| `MISSING_CONSUMPTION_BINDING` | Medium und Einheit am Entwurfsschlüssel ergänzen; für bereits finalisiert verwendete Schlüssel neue Fassung anlegen. |
| `MISSING_CONSUMPTION_METER` | Exakte Zuordnung und vorhandenen Zähler mit Periodenbezug prüfen. |
| `MISSING_METER_UNIT` | Tatsächliche Zählereinheit ergänzen. |
| `CONSUMPTION_UNIT_MISMATCH` | Originaleinheiten prüfen; echte Umrechnung benötigt ein späteres belegtes Umrechnungsmodell. |
| `MISSING_CONSUMPTION_BOUNDARY` | Eindeutige Originalablesungen am Periodenbeginn und -ende ergänzen. |
| `INVALID_CONSUMPTION_READING` | Negativen oder nicht endlichen Messwert anhand des Originals korrigieren. |
| `AMBIGUOUS_CONSUMPTION_READING` | Unterschiedliche Werte desselben Ablesetages klären. Identische Duplikate zählen nur einmal. |
| `CONSUMPTION_READING_DECREASE` | Fehler, Überlauf oder Wechsel fachlich klären; keine stille Differenzbildung. |
| `CONSUMPTION_METER_CHANGE_BASIS_MISSING` | Unterjährigen Einbau mit belegten Teilperioden aufbereiten. |
| `CONSUMPTION_TENANCY_BASIS_MISSING` | Teilbelegung/Mieterwechsel benötigt datierte Verbrauchsanteile. |
| `ZERO_CONSUMPTION_TOTAL` | Bei Kosten trotz belegtem Gesamtverbrauch null eine fachlich bestätigte andere Verteilungsgrundlage wählen. |
| bestehendes `MISSING_PERSON_COUNT` | Tatsächliche Bewohnerzahl pflegen; Zimmerzahl wird nicht verwendet. |

`context` nennt Schlüssel-, Einheits-, Zähler- und gegebenenfalls Ablesungs-IDs.
Das bisherige generische `MISSING_CONSUMPTION` bleibt bei fehlender vollständiger
Grundlage als zusätzlicher kompatibler Befund erhalten.

## Migration und Tests

Migration `e2a2b3c4d5e6` folgt auf `d2a2b3c4d5e6`. Sie ergänzt drei nullable
Textspalten ohne Backfill und ändert keine alten Abrechnungen. Bereits
vorhandene Teilspalten werden vor DDL als Schemaabweichung abgewiesen. Vor dem
Downgrade werden alle drei Spalten geprüft; gepflegte Werte verhindern den
Datenverlust. Native Spaltenoperationen erhalten Tabellen, Indizes und Trigger.

Lokale Testvoraussetzungen aus exakt Root `8bb1d26` wurden nur uncommittet
übernommen und nach den Prüfungen wieder entfernt: `backend/db/integration_history_models.py`,
`backend/db/integration_history_schema.py`,
`backend/db/migrations/versions/d2a2b3c4d5e6_private_integration_history.py`,
`backend/services/integrations/history_types.py`. Diese vier Dateien sind
kein Bestandteil dieses Pakets; Root besitzt sie bereits. Keine Manager-
oder Startup-Voraussetzung wurde kopiert. Keine private Hauptdatenbank wurde
gelesen, migriert oder gestempelt.

Nachweise auf Python 3.14.7:

- Bestehende Abrechnungsregressionen: Memory 134 bestanden/1 backendbedingter
  Skip; SQL/SQLite 134 bestanden/1 backendbedingter Skip. Umfasst Engine,
  Vorprüfung, Workflow, Sprint2, Integrität, Leerstand, NK6, Export und
  `TestGenerateUtilityStatements`.
- Neue HTTP-Fälle: 32 Prüfungen über den echten API-Routergraph mit Login,
  Portfolio-Grenzen, ETag-Bearbeitung, Memory und vollständig migriertem SQLite.
  Im letzten vollständigen Lauf bestanden 31/32. Dieser Lauf dauerte wegen
  Host-Unterbrechung von 00:33 bis 09:43 über neun Stunden; der verbleibende
  Memory-Zugriffstest bekam nach der Unterbrechung für seine alte Owner-Sitzung
  HTTP 401, während das frisch angemeldete Peer-Konto korrekt HTTP 404 erhielt.
  Das spricht für zwischenzeitlichen Sitzungsablauf. Beide Varianten dieses
  Tests bestanden anschließend unverändert erneut (2/2 in 19,60 Sekunden).
  Damit wurden alle 32 Fälle am finalen Stand erfolgreich geprüft. Es wird kein
  durchgehend grüner letzter Gesamtlauf behauptet.
- Ein ursprünglicher Test verglich SQLite-Schreibantwort und geladene Antwort
  einschließlich unterschiedlicher UTC-Suffixdarstellung. Auf gespeicherte
  GET-Baseline korrigiert; beide Backendvarianten und beide Zuordnungsreparaturen
  danach im gezielten Lauf bestanden (4/4). Produktzeitstempel unverändert.
- SQLite: 5/5 bestanden, darunter tatsächliche historische Migration,
  unveränderte alte Werte/FKs/Indizes/Trigger, verlustverweigernder Downgrade
  für jedes neue Feld sowie vorhandener vollständiger ORM-Schemavertrag.
- PostgreSQL: tatsächliche komplette historische Alembic-Kette bis d2,
  e2-Upgrade, d2-Downgrade, e2-Reupgrade und reale Spaltenprüfung bestanden.
  Nur zufällig benanntes synthetisches Schema verwendet und anschließend
  entfernt; weder public-Schema noch Dienst verändert. Dieser einmalige
  native Integrationslauf ist kein neu hinzugefügter CI-Test.
- Ruff für alle neun Produkt-/Testdateien und Mypy der drei fachlichen
  Quellen mit Zielversion 3.11 und 3.12 bestanden. Dies ersetzt keine reale
  Laufzeitprüfung unter Python 3.11/3.12.

Logs liegen außerhalb des Commitumfangs unter `work/`:
`p0-consumption-regression-memory.log`, `p0-consumption-regression-sql.log`,
`p0-consumption-migration-second.log`, `p0-consumption-postgres-migration.log`,
`p0-consumption-http-final-focused.log`, `p0-consumption-http-final.log`,
`p0-consumption-http-scope-final.log`.
Die HTTP-Tests melden eine bereits bestehende Starlette/httpx-Abkündigung.

## Bewusst verbleibende Grenzen und Integrationsreihenfolge

1. Root integriert erst History-d2, dann dieses e2-Paket und die drei UI-Felder.
   Die kombinierte Release-/Migrationsprüfung bleibt Root-Verantwortung.
2. Ohne datiertes Ablesungs-/Wechselmodell sind exakte Grenzablesungen an beiden
   Periodentagen erforderlich. Keine Interpolation oder Einheitenumrechnung.
   Aktivflag heute entfernt keine historische Quelle: deaktivierte Zähler mit
   Periodenablesungen werden berücksichtigt; ohne datierte Deaktivierung ist
   eine feinere Abgrenzung erst mit dem Wechselmodell möglich.
3. Verbrauch wird hier nur für eine durchgehende einzelne Belegung pro Einheit
   erzeugt. Unterjährige Mieterwechsel, Teilbelegung und Leerstand benötigen
   ein nachgelagertes belegtes Teilperiodenmodell. Der vorhandene Leerstands-
   blocker bleibt bestehen. Das ist eine erklärte Quellenlücke, keine Schätzung.
4. Bewohnerzahlen sind weiterhin aktuelle Einheitsstammdaten. Datiert wechselnde
   Bewohnerzahlen/Personentage benötigen ein eigenes Belegungsmodell; dieser
   Fix entfernt ausschließlich den sachlich falschen Zimmerersatz.
5. Das bestehende Modell kennt weder Haupt-/Unterzählerhierarchien noch
   ausdrücklich ein-/ausgeschlossene Messkreise. Gleiches Medium und gleiche
   Einheit allein beweisen keine überschneidungsfreie Messstruktur. Mehrere
   passende Zähler derselben Einheit werden weiterhin addiert; deren
   Überschneidungsfreiheit muss bis zum Messkreismodell fachlich gegeben sein.
6. Die bestehende Datensuche lädt Listen weiterhin vollständig. Dieses Paket
   ändert keine Abfrage-/Index-/Streamingarchitektur und erhebt deshalb keine
   neue Behauptung zur Eignung für 20 Jahre große Datenbestände.
