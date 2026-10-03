# C: eingefrorene Parteien neuer Abrechnungsoriginale

Stand 03.10.2026 im eigenen Domaincheckout. Umsetzung folgt dem getrennt
committeten Plan `abceaaf`. Keine DDL, neue Migration, zentrale Registry-,
Recovery-, Settings-, CI-, UI- oder Rootänderung. j2 und reserviertes k2 bleiben
unverändert. Die Basisreparatur `7a037ed` nicht erneut übernehmen.

## Quellen und Verhalten

Neue tatsächliche Finalisierung ergänzt ausschließlich das bestehende,
bereits vollständig gehashte `BillingPeriod.owner_cost_share` um
`statement_parties`: Schema `utility-statement-parties/1`, Einträge nach
konkreter UtilityStatement-ID. Der Block enthält vollständige ursprüngliche
Portfolio-/Objekt-/Einheiten-/Vertrags-/Mieterbindung und Name/postalische
Identität sowie tatsächlichen Erfassungszeitpunkt, Akteur und Quellenfassung.
Keine erfundenen Kosten-/Zahlungszeilen und keine privaten Notizen/Bankdaten.

`billing_settlement.finalize_period` ist weiterhin der tatsächliche atomare
Finalisierungsweg. Die Berechnungsbasis bindet nun auch die aktuelle tenant_id;
ein Parteienwechsel nach Generierung verlangt eine echte Neugenerierung.
Tenantzeilen werden während Erfassung bis Commit nativ FOR SHARE gehalten.
Name/Adresse dürfen später im Profil geändert/anonymisiert werden. Alte
bereits finalisierte Fassungen werden auch beim erneuten Finalisierungsaufruf
nicht ergänzt. Ein vorhandener Originalparteienblock darf weder neu eingefroren
noch intern überschrieben/entfernt werden. Normale Elternlöschung und Änderung
der ursprünglichen Elternbindung sind auch ohne eröffnete Akte geschützt.

Korrekturen aus belegtem Original übernehmen dessen tenant_id und Identität,
mit eigener neuer Erfassung und tatsächlichem Source-ID/Source-Hash. Die
Korrektur einer alten unbelegten Fassung friert nur ihre tatsächlich jetzt
geprüfte Partei ein (`contract_at_correction_finalization`); die historische
Fassung bleibt unbelegt. Reine Restoreprüfung vergleicht natürliche Fassung,
Revision, Status, Property/Dates, vollständige Statementmenge, Elternexistenz,
Quellenhash, Quellenpartei und ursprünglichen Gesamtperiodenhash. Heutiger
Tenantname und heutige Contract.tenant_id werden nicht als historischer Beweis
verwendet.

Widerspruchseröffnung verwendet den passenden belegten Eintrag und speichert
ihn in der konkreten Statement-Originalkopie. Neuer Modus:
`frozen_at_statement_finalization`. Historische Fassungen ohne Block behalten
`verified_at_case_opening`. Korrekturverknüpfung und Restore prüfen belegte
Parteien jeder Quellenfassung; bestehende Fälle werden nicht umgeschrieben.

Privacy ergänzt ausschließlich passende `frozen_utility_statement_originals`
(je eigenes Statement und dessen eigener Partei). Der gemeinsame Periodenblock
anderer Personen wird nicht exportiert. Nach einer ausdrücklich synthetischen
unabhängigen nativen Vertragsumbindung erhält die spätere Vertragspartei keine
frühere Identität/Einzelabrechnung/Akte. Anonymisierung erhält den Originalblock
und benennt dessen Name/Adresse in der bestätigten Vorschau. Native Subject-
JSONfilter, gezielte scoped Abfragen, vollständige Subject-Scope-Prüfung und
bestehende Immobilien-/Accountschreibsperren bleiben wirksam.

## Reine Hooks für Root

`backend/services/billing_statement_parties.py` enthält reine Typen, Familie,
`party(statement, period)` und zwei unabhängige Originalvalidatoren. Kein Auth-,
Store-, SQL-, App-, Settings-, Dependencies- oder operativer Scopeimport.
Alle operativen/native Hilfen liegen separat in
`billing_statement_party_storage.py`.

Vollständiges tatsächliches Snapshotbild:

```python
validate_statement_parties(*, parents)
```

`parents` enthält vollständige tatsächliche Dictionarymaps `portfolios`,
`properties`, `units`, `contracts`, `tenants`, `billing_periods`,
`utility_statements`. Diesen Hook auch bei völlig leerem/fehlendem Journal
aufrufen. Fehlende Originalfamilie bleibt explizit Legacy; vorhandene
malformed/unvollständige Familie ist Fehler. Vollständige Snapshotvariante
berechnet den tatsächlichen unveränderten Settlement-Hash selbst.

Periodischer nativer Stream:

```python
validate_period_statement_parties(
    period, statements, *, parents, verified_period_hash=None,
)
```

`period` ist die tatsächliche vollständige Periodenzeile; `statements` ist ein
Iterator über sämtliche tatsächlichen Statements dieser Periode. Mit explizitem
`verified_period_hash` liest der Hook den Iterator genau einmal, prüft jeden
konkreten Eintrag und am Ende exakte Vollständigkeit/keine doppelten IDs. Ohne
Hash berechnet er die vollständigen Originalbytes selbst. Der explizite Hash
ist ausschließlich internes Ergebnis des nativen Root-Gesamtperiodenhashers,
niemals HTTP-/JSON-Daten oder ein akzeptierter Requestcache. Elternmaps dürfen
gezielt oder lazy nur tatsächliche referenzierte Zeilen laden. Benötigt sind
pro Eintrag seine Portfolio-/Property-/Unit-/Contract-/Tenant-ID sowie bei
Korrektur die tatsächliche Source-Statement- und Source-Period-Zeile. Keine
vollständige globale Materialisierung fremder Datensätze vorausgesetzt.

Der reine Disputevalidator importiert diesen Hook, wenn kein interner Hashcache
übergeben wird. Bei internem `verified_period_hashes` prüft er die konkrete
Aktenbindung; Root muss zusätzlich den periodischen Originalhook für sämtliche
finalisierten Perioden aufrufen, einschließlich Perioden ohne Akte. Vollständige
Originalfamilienprüfung und echter nativer Hash dürfen nicht durch begrenzte
Case-Parentmaps ersetzt werden.

## Getrennte Vorbereitungscommits

- `c92e184`: ausschließlich interner Keywordparameter
  `verified_period_hashes: Mapping[str, str] | None` am bestehenden
  `validate_dispute_snapshot`, kein HTTP-Vertrag.
- `5d4386a`: exakt unveränderte `IMMUTABLE`/`snapshot_hash` in reinem
  `billing_originals.py`; Settlement reexportiert alte öffentliche Symbole.

Produktcommits:

- `fb5868d`: versionierter Original-JSON-Vertrag, reine Typen/Validatoren,
  operative Nativehelper, tatsächliche Finalisierung und Parentretention.
- `a09a35c`: Akten-/Korrekturbindung, exakte Privacy, Pure-Restoreverknüpfung
  und tatsächliche sieben fachliche Testfälle auf Memory/SQLite/PostgreSQL.

Die beiden Vorbereitungen sind unabhängig von den Parteienproduktcommits und wurden
Root bereits unmittelbar gemeldet. Produktcommits in der angegebenen Reihenfolge
zusammen komponieren, bevor der produktweite C-Gate ausgeführt wird.

## Tatsächliche Nachweise und Grenzen

- Echter Memory-/SQLite-Finalisierungssmoke: 2 PASS (13.83 s).
- Weitere Memory-/SQLite-Korrektur-/Legacy-/Privacy-/Parteienwechsel:
  6 PASS (30.10 s).
- Originalstream mit Gegenbelegen, Anonymisierung ohne Akte, tatsächlicher
  SQLitebackup/Reopen: 5 PASS, 1 begründeter Memory-Backupskip (29.43 s).
- Strikter echter PostgreSQL-Lauf in sechs eigenen zufälligen Schemas:
  5 PASS (66.57 s), ein reiner psycopg2/psycopg3-Fehler der SQLSTATE-Assertion.
  Tatsächliche 55P03-Sperre war bereits korrekt. Ausschließlich diese Assertion
  korrigiert; genau der sechste Fall danach 1 PASS (14.27 s). Keine PG-Skips
  als Abnahme gerechnet. Alle Produktquellen blieben während dieser Läufe gleich.
- Frischer Subprozess mit aktiver Ablehnung aller Runtime-/Storeimports und
  tatsächlich wiedergeöffnetem Original-/Hash-Gegenbeleg sowie normales
  TenantDELETE ohne Akte 409: 2 PASS (13.75 s). Frischer Prozess akzeptiert die
  echten unveränderten Originale und lehnt bearbeitete Identität ab.
- Ruff der berührten Quellen und Mypy vier neuer/geänderter Domainquellen grün.

Kein gesamter A–L-Gate, keine Root-Kompositionsabnahme, keine neue Migration und
kein produktives Provider-/Privatdaten-Experiment behauptet. Native unabhängige
Vertragsumbindung ist ein ausdrücklich synthetischer Gegenbeleg; normale
API-Änderung wird 409 abgewehrt. Ein beliebiger administrativer Native-SQL-Writer
kann JSONfelder ohne neue DDL verändern; die Originalhash-/Pure-Restoreprüfung
weist beschädigte JSONoriginale ab. Kein neuer SQL-Trigger wird behauptet.
