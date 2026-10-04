# Paket C: eingefrorene Mietpartei neuer Abrechnungsfassungen

Plan auf tatsächlichem Domainstand `1a3386c`, 03.10.2026. Produktcode erst nach
diesem Plan. j2 bleibt Widerspruchsjournal, k2 ist für Meter reserviert. Dieses
Paket benötigt nach den gelesenen Quellen keine neue DDL oder Revision.

## Tatsächliche Quellen und fehlender Nachweis

`UtilityStatement` speichert period_id, contract_id, unit_id, Finanzbeträge,
Originalrevision, snapshot_hash, Kostenpositionen, Vorauszahlungsbelege und
Quellenabrechnung. Keines dieser Felder speichert damalige tenant_id oder
Adressatenidentität. Rückprojektion aus `Contract.tenant_id` wäre historisch
unbelegt. Das j2-Journal hat diesen Ausgangszustand bisher ausdrücklich als
`verified_at_case_opening` beschrieben und nach Eröffnung eingefroren.

Die einzige tatsächliche reguläre Finalisierung ist
`billing_settlement.finalize_period`, aufgerufen vom Billingrouter und den
direkten Domainwegen. Sie überprüft Preflight, vollständige Verträge,
centgenaue Kostensumme, berechnete Grundlagen und tatsächliche Zahlungen;
anschließend schreibt sie gemeinsamen Settlement-Originalhash, Statements
und Periodenstatus atomar. Bereits finalisierte/zugestellte Perioden werden
idempotent zurückgegeben. Korrekturen entstehen als eigene Perioden und
Statements mit echter Quellenkette und eigener Revision. Öffentliche CRUD-
Pfade dürfen Finalisierung oder berechnete Originalfelder nicht umgehen.

`line_items` ist eine echte Kostenpositionsliste; legitime reine Eigentümer-
kosten können eine leere Mieterkostenliste besitzen. `advance_details` ist
eine echte Zahlungsbelegliste mit rent_charge_id und kann ebenfalls leer sein.
Beide Listen dürfen keine künstliche Identitäts-/Kostenzeile erhalten.
`BillingPeriod.owner_cost_share` enthält bereits den Original-JSON-Vertrag der
Gesamtfassung: Kostenanteile, Policy, Eigentümerkostenpositionen und tatsächliche
historische Quellen. Er geht unverändert in `settlement.snapshot_hash` ein.
Hier kann eine ausdrücklich versionierte Originalparteienfamilie ergänzt
werden, ohne Datentyp, SQL-Spalten oder ursprüngliche Kostenlisten zu ändern.

## Versionierter Original-JSON-Vertrag

Neue Finalisierung ergänzt `owner_cost_share.statement_parties` mit einer
eindeutigen Schemafassung und nach Statement-ID getrennten Einträgen. Jede
Fassung enthält tatsächliche Statement-/Perioden-/Revisions-/Quellen-ID,
Portfolio-/Objekt-/Einheiten-/Vertragsbindung, eingefrorene tenant_id, Name
und damalige postalische Identität, Erfassungszeit und belegte Herkunft.
Keine Bankdaten, privaten Notizen oder beliebigen Tenantfelder kopieren.
Der vollständige Perioden-Originalhash bindet diese JSON-Familie mit ein.

Die Familie ist genau vollständig für die tatsächlich finalisierten Statements.
Vollleerstand hat eine ausdrücklich leere Parteienfamilie. Fehlende Familie
bezeichnet ältere unbekannte Identität; ein vorhandener unvollständiger,
unbekannt versionierter oder widersprüchlicher Block ist beschädigt und darf
keine Legacyfallback-Interpretation auslösen. Die Darstellung darf fehlenden
historischen Nachweis nicht aus dem heutigen Vertrag nachtragen.

Bei einer neuen ursprünglichen Fassung wird die Vertragspartei unter den
vorhandenen Account-/Immobilien-/Rootperioden-/Vertragssperren tatsächlich
gelesen und Tenant-ID/Identität eingefroren. Änderung der Berechnungsgrundlagen
zwischen Generierung und Finalisierung muss einschließlich tenant_id erkannt
werden. Profiländerungen nach Abschluss verändern das gespeicherte Original
und seinen Hash nicht. Reguläre Finalisierung einer bereits finalisierten alten
Fassung ist keine Nachmigration und ergänzt dort nichts.

## Korrektur und Widerspruch

Eine Korrekturfassung mit belegter Quellenpartei übernimmt diese konkrete
Partei und ursprüngliche Identität mit Quellenbezug. Der heutige Vertrag darf
keine andere Mietpartei in die alte Korrekturkette einführen. Die neue Fassung
hat ihre eigene Statement-ID/Revision/Erfassungszeit und bindet die tatsächlich
belegte Quellenfassung. Ein historisches Original ohne Parteienblock bleibt
unbekannt; eine jetzt tatsächlich finalisierte Korrektur kann ihre heutige
geprüfte Partei belegen, ohne das frühere Original rückwirkend zu bestimmen.

Widerspruchseröffnung verwendet bei vorhandenem geprüften Block dessen
tenant_id und gespeicherte Identität, mit `party_binding` als ausdrücklichem
Finalisierungsnachweis. Seine Originalkopie enthält den genau passenden
Partieneintrag. Fehlt der Block, bleibt der bereits eingeführte Modus
`verified_at_case_opening` erhalten. Korrekturverknüpfung vergleicht neben
Vertrag/Quellenkette die belegte konkrete Partei; heutige Vertragszuordnung
ersetzt keinen Nachweis. Bestehende j2-Fälle werden nicht umgeschrieben.

## Originalschutz und Datenschutz

Öffentliche Finalisierungs-/Update-/Deletepfade dürfen neue oder vorhandene
Parteienoriginale nicht überschreiben. Interne Zustell-/Status-/Korrektur-
schritte erhalten die komplette vorhandene Familie. Tatsächliche Stammdaten-
änderungen dürfen Namen/Kontaktdaten verändern; eine neue Mietpartei bekommt
einen neuen Vertrag. Eingefrorene Elternbezüge erhalten ihren normalen
Existenz-/Löschschutz auch ohne bereits eröffnete Widerspruchsakte.

Datenschutz ermittelt Statements bei vorhandenem Block anhand der exakt
eingefrorenen tenant_id. Eine inzwischen andere Vertragspartei erhält weder
das frühere Original noch dessen eingefrorene Identität. Der frühere Mieter
erhält ausschließlich seine Statement-ID/Originalparteienfassung, niemals den
Block anderer Personen aus derselben Gesamtperiode. Legacydaten behalten
ihre bisherige aktuelle Vertragsgraph-Semantik mit ausdrücklicher Aussage,
dass damalige Identität dort nicht eingefroren ist. Widerspruchsgraph bleibt
exakt nach Case.tenant_id gefiltert.

SQL-Subjectfilter verwenden native JSON-Ausdrücke/Joins und scopegebundene
Abfragen; verdeckte belegte Originale werden nur als Existenz auf vollständige
Privacyberechtigung geprüft. Keine beliebige Suche nach Namen/Adressen oder
komplette Materialisierung fremder Periodenidentitäten. Anonymisierung nennt
erhaltene Name-/Adress-/Parteienoriginale in der Vorschau und bindet deren
Inhalte an den bestätigten Plan. Profilanonymisierung verändert sie nicht.

## Reine Restoreprüfung und Rootgrenze

Ein eigener reiner Originalvalidator prüft vollständigen Schematyp,
Statementmenge, natürliche Datums-/Revisionsfelder, Eltern-ID-Existenz,
finalisierte Fassung und ursprünglichen Settlement-Hash sowie belegte
Korrekturquellen-/Parteienkette. Er vergleicht historische Namen nicht mit
heute bearbeiteten Tenantprofilen. Vorhandener Parteienblock muss konsequent
mit einer neuen Journalbindung übereinstimmen. Fehlender Block ist Legacy,
kein Fehler und kein Anlass zu einer Rekonstruktion.

Root erhält einen klaren Validatorhook für Fälle ohne Journal und für native
Recoverybilder. Eigene Quellen dürfen die zentrale Registry, Recovery,
Settings, CI, UI oder Rootdateien nicht verändern. Bestehende vollständige
Perioden-/Statement-Backups führen die ergänzte JSON-Familie bereits mit.
Kein SQL-DDL, Migrationseinstieg oder Startupreparatur wird hier eingeführt.

## Kleine Abnahmepakete und Gegenbelege

1. Reine versionierte Typ-/Quellenprüfung, atomare Originalfinalisierung und
   kleine Memory-/SQLite-Gegenbelege mit tatsächlicher Erzeugung/Finalisierung.
2. Journaleröffnung/Korrekturverknüpfung und Elternschutz, jeweils neue belegte
   Partei und unverändert akzeptierter Legacy-Fallback.
3. Exakte Privacyprojektion/Anonymisierung und reiner Restorevalidator mit
   geänderten heutigen Profil-/Vertragsdaten, fremder Nachfolgepartei und
   ursprünglicher Parteienfamilie.
4. Gezielte tatsächliche PostgreSQL-Abnahme nach Slotabstimmung: unabhängige
   SQL-Verbindungen, echte Originalfinalisierung/Sperren, echte Korrektur,
   Originalhash und sauberes vollständiges Restore. Eigene zufällige Schemas,
   ausschließlich synthetische Daten, kein Dienstlebenszyklus.

Gegenbelege: Änderung einer Partei vor Finalisierung wird nicht still einer
alten Generierung zugeschrieben; Name/Adresse nach Finalisierung verändern
das Original nicht; spätere Vertragspartei erhält keine alte Privatidentität;
Korrektur bleibt bei der belegten ursprünglichen Partei; alte Fassung wird
beim erneuten Finalisierungsaufruf nicht nachgebessert; beschädigter vorhandener
Block wird nicht als Legacy akzeptiert; neu berechnete Journalhashes machen
falsche Parteien-/Originalbezüge im Restore nicht gültig; unabhängiger Writer
kann zwischen tatsächlicher Finalisierung und Commit keinen anderen
Adressaten veröffentlichen; Backup erhält Originalidentität und Hash.
