# Paket C: historische Mess- und Belegungsgrundlage

Konkreter Implementierungsplan vor Produktänderungen, 3. Oktober 2026.
Eigene saubere Basis: Root `5de8762`, Branch
`assist/billing-measurement-history`. Reservierte Migration:
`g2a2b3c4d5e6` nach tatsächlichem Scheduler-`f2a2b3c4d5e6`; keine Ersatzrevision,
kein Stamp und kein Kopieren uncommitteter Root-Arbeit.

## Befund und fachliche Invarianten

P0 trennt Medien und Maßeinheiten, kann aber mangels historischen Modells
unterjährige Wechsel nicht verteilen. Die bestehenden `Meter`, `Unit` und
`StandaloneMeterReading` sind bearbeitbare Stammdaten. Sie beweisen weder
historische Bewohnerzahlen noch überschneidungsfreie Messkreise. Deshalb
werden daraus keine historischen Tatsachen durch eine Migration erzeugt.

Historische Angaben werden ausdrücklich erfasst und bestätigt. Zeitabschnitte
verwenden `valid_from` einschließlich und `valid_until` ausschließlich;
Ablesungen beziehen sich auf eine Tagesgrenze. Eine vorhandene Jahresperiode
01.01.–31.12. entspricht damit den Grenzen 01.01. und 01.01. des Folgejahres.
Der alte P0-Pfad bleibt erkennbar kompatibel, solange keine historische
Zuordnung für den verwendeten Schlüssel angelegt wurde. Historischer Modus
darf keine fehlende Einheit still durch aktuelle Stammdaten ersetzen.

## Persistente Familie und tatsächliche Schreib-DTOs

Neue Module `measurement_history_types`, `measurement_history_models`,
`measurement_history_schema`, `measurement_history_validation`,
`measurement_history`, `measurement_history_calculation` und Router
`measurement_history`. Alle Namen stehen unter den vorhandenen
`backend/services`, `backend/db` bzw. `backend/routers`.

Vier Tabellen, explizite Portfolio-/Immobilien-/Einheitsbindung:

1. `measurement_ledgers`: ein revisionsgezählter Kopf je Einheit; keine
   Erstellung beim Lesen. Der erste bestätigte Schreibbefehl legt ihn an.
2. `measurement_commands`: unveränderliche Befehlsquittungen mit Actor,
   Idempotenzschlüssel, kanonischem Request-Hash, erwartetem/neuem Stand und
   Resultat-IDs. Wiederholung desselben Befehls liefert dieselbe Quittung;
   wiederverwendeter Schlüssel mit anderer Nutzlast ist ein Konflikt.
3. `measurement_facts`: unveränderliche Fassungen mit stabiler `source_key`,
   `predecessor_id`, Typ, Zeitgrenzen, Ledgerrevision/Position, kanonischem
   Inhalts-Hash, Actor, Begründung und den relevanten echten Elternreferenzen.
   Eine Korrektur ersetzt die wirksame Fassung, niemals das Original.
   Eine Rücknahme ist eine begründete neue Fassung mit Rücknahmekennzeichen.
4. `measurement_evidence`: Verknüpfungen einer Fassung zu unveränderlichen
   `DocumentVersion`-Originalen einschließlich geprüftem Inhalts-Hash.

`MeasurementCommand` enthält `expected_revision`, `idempotency_key` und eine
atomare Liste `changes`. Eine Änderung benennt ihre `source_key`, gegebenenfalls
die exakt erwartete Vorgängerfassung und ihren Grund. Fünf strikt typisierte
Nutzlasten, keine beliebigen JSON-Befehle:

- `MeterAssignment`: tatsächlicher Zähler, Medium, Maßeinheit, datierte
  Betriebszeit und ausdrücklich erfasster `circuit_path`. Zählerersatz bekommt
  eine neue Zuordnung am selben Messkreis mit angrenzenden Betriebszeiten.
- `BoundaryReading`: Zuordnungsbezug, Tagesgrenze und endlicher nicht negativer
  Decimal-Messwert als Text. Ein erfasster Wert wird als Original bewahrt;
  spätere Korrekturen benötigen einen Vorgänger und einen Grund.
- `OccupancyInterval`: belegter Zeitraum, tatsächlicher Vertrag oder ausdrücklich
  Leerstand, tatsächliche Bewohnerzahl. Personenanzahlen sind ganze nicht
  negative Werte. Vertrags- und Leerstandsintervalle dürfen sich nicht
  überschneiden; ein verwendeter Zeitraum muss lückenlos belegt sein.
- `AllocationSelection`: verwendeter Umlageschlüssel, Zeitraum und ausgewählte
  Messkreise; ausdrückliche Bestätigung ihrer Überschneidungsfreiheit mit Grund.
  Gleichzeitige Auswahl eines Hauptkreises und eines seiner Unterkreise wird
  zurückgewiesen. Mehrere Geräte am selben Kreis müssen zeitlich anschließen.
  Personenschlüssel können ausdrücklich die historischen Belegungsabschnitte
  als Grundlage auswählen.
- `ProrationApproval`: ausdrücklich freigegebene Zeitaufteilung zwischen zwei
  benannten Originalgrenzablesungen, betroffene Zuordnung, Begründung und
  mindestens ein Dokumentoriginal. Ohne diese Freigabe keine Interpolation.

Die Auswahl ist fachliche Bestätigung einer realen Messstruktur; Bezeichnungen
allein sind kein automatischer Nachweis. Haupt-/Unterkreisbeziehungen werden
aus erfassten Pfaden geprüft, niemals aus Zählernummern oder Freitext geraten.

## Transaktionen, Rechte und Konflikte

Schreibbefehle laufen in einer eigenen SQL-Transaktion bzw. unter den vorhandenen
Memory-Account-/Domain-Sperren mit Undo ausschließlich der eigenen Zeilen.
SQLite erhält `BEGIN IMMEDIATE`. PostgreSQL erhält eine transaktionsgebundene
Quellensperre je Immobilie, bevor Eltern-/Vertragssperren genommen werden.
Die Abrechnungs-Transaktion verwendet denselben Träger vor ihren bestehenden
Vertragssperren. Die Sperre funktioniert auch vor dem ersten Ledgerdatensatz.
Quellen können so nicht zwischen Berechnung und Commit ausgetauscht werden.

Fresh Actor, aktuelle Rolle, Portfoliozugriff und echte Request-Credential
werden beim Eintritt und vor Commit geprüft. SQL-Accountverwaltung und Eltern
werden entsprechend den vorhandenen Mustern eingezäunt. Referenzen auf Zähler,
Schlüssel, Vertrag, Mieter und Dokumentversion müssen zum erlaubten realen
Elternobjekt passen. FK-/Unique-/Check-Constraints und Update/Delete-Guards
erhalten Originale auch außerhalb der normalen API. Alte oder konkurrierende
Revisionen führen zu 409 und lassen keinerlei halbe Fakten zurück.

Die neue API wird über die zulässige kleine Billing-Router-Anbindung ergänzt:
periodisch begrenzte Quellen lesen, Journal über Keyset-Seiten lesen,
Bestätigungsbefehl ausführen und Abrechnungsvorprüfung abrufen. Kein DDL beim
HTTP-Aufruf, kein Vollbestands-Export als Bearbeitungsformular.

## Berechnung und Quellenrevision

SQL-Selektoren begrenzen nach Immobilie/Einheit, benötigten Schlüsseln und
Periodengrenzen; geeignete Indizes unterstützen diese Zugriffe. Wirksame
Fassungen werden vor der Zeitfilterung durch vorhandene Nachfolger ausgeschlossen:
eine in ein anderes Jahr verschobene Korrektur darf ihr altes Original nicht
wieder wirksam machen. Die Quellenliste enthält IDs und Inhalts-Hashes der
tatsächlich herangezogenen Fassungen samt Belegreferenzen.

Der gemeinsame Prüfer schneidet ausgewählte Messkreise an Gerätewechseln,
Mieterwechseln und Periodengrenzen. Jede Teilstrecke benötigt ihre realen
Grenzablesungen; nur dokumentiert freigegebene Strecken erlauben Tagesprorata.
Verbrauch wird je Vertrag und für Leerstand separat dem Eigentümer zugeordnet.
Personengewichte entstehen aus Bewohnerzahl × tatsächlichen Abschnittstagen.
Zeitanteile werden danach nicht nochmals auf den bereits geteilten Verbrauch
angewandt. Gesamtmengen und Kosten müssen erhalten bleiben, einschließlich
Nullverbrauch und Rundung über die vorhandene Cent-Verteilung.

`billing_settlement.calculation_hash` bekommt ausschließlich den zusätzlichen
periodenspezifischen Quellenbezug; eine Quellenkorrektur macht einen früheren
Entwurf ungültig. Fertige Originalabrechnungen bleiben unverändert. Eine neue
Korrekturabrechnung darf neue bestätigte Quellen verwenden. Der zweite kleine
freigegebene Hook sitzt in `atomic_billing` für die gemeinsame Quellensperre.

## Recovery und Privacy als explizite Integrationsgrenze

Neue reine Validatoren prüfen vollständige Familien, Referenzen, Elternbindung,
Zeit-/Typinvarianten, kanonische Hashes, Vorgängerketten, Befehlszuordnung,
eindeutige Positionen/Revisionen und Dokumentbezüge. Kein Validator erstellt
Tabellen, repariert Quellen oder ersetzt historische Werte durch heutige Werte.
Downgrade verweigert das Verwerfen vorhandener historischer Quellen.

Eigene Snapshot-/Selector-/Privacy-Helfer beschreiben Aufnahmereihenfolge,
Aufbewahrung und den Personenbezug anhand tatsächlicher und eingefrorener
Vertrags-/Mieterreferenzen. Historische Finanzbelege werden als aufbewahrte
Quellen ausgewiesen; allgemeines Löschen darf sie nicht still entfernen.
Zentrale Startup-/Restore-/Privacy-Hooks bleiben Root vorbehalten. Das Handoff
benennt jeden nötigen Hook; vollständige Recovery-/Privacy-Abnahme wird erst
nach dessen Integration behauptet.

## Kleine Commitpakete und Gegenprüfungen

1. **C0 Plan**: dieser konkrete Plan, ohne Produktänderung.
2. **C1 Quellenfamilie**: DTOs, Tabellen, g2-Migration, Schema-/Graphvalidatoren
   und reine Invariantentests. Echtes f2 als uncommittete Testvoraussetzung erst
   nach Lieferung; kein Platzhalter.
3. **C2 Bearbeitung**: Journal, transaktionale API, Revision/Idempotenz, fresh
   Auth/Scope und unveränderliche Belege. Tests für fremdes Portfolio,
   unzulässige Eltern, verlorene Rechte, Wiederholung und parallele Änderung.
4. **C3 Abrechnung**: Zeitraumselektoren, historische Gewichte, Vorprüfung,
   Quellenhash und beide Lock-/Hash-Hooks. Tatsächliche HTTP-Gegenbelege für
   Zählerersatz, getrennte Medien, Haupt-/Unterzähler, Mietwechsel, Leerstand,
   Bewohnerwechsel, fehlerhafte Grenzen, korrigierte Originalwerte und bewusst
   freigegebene gegenüber nicht freigegebener Zeitaufteilung.
5. **C4 Integrationsnachweise**: echte historische SQLite- und PostgreSQL-
   Migrationen, native parallele SQL-Schreiber sowie Quellenänderung zwischen
   Calculate und Commit, begrenzte SQL-Abfragen, Recovery-/Privacy-Snapshots,
   relevante vorhandene P0-/Abrechnungsregressionen und präzises Handoff.

## Separater klarer Folgeschritt: Widerspruchsjournal

Bestand tatsächlich geprüft: `billing.py:918` nimmt `reason` entgegen,
reicht ihn aber nicht weiter; `billing_settlement.dispute_period` schreibt nur
`status=disputed`. Ein dauerhaftes Journal mit Grund, Anlagen und konkretem
Abrechnungs-/Fassungsbezug fehlt. Das bleibt ein eigener nachfolgender Schritt
mit eigener Migration und fachlicher Abnahme. Paket C behauptet hierzu keine
Vollständigkeit und ändert die vorhandenen Widerspruchsdaten nicht beiläufig.
