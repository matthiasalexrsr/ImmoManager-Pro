# Getrennte k2-Indexreservierung für Zähler und Ablesungen

Root hat am 2026-10-03 exklusiv `k2a2b3c4d5e6` mit Parent
`j2a2b3c4d5e6` reserviert. j2 gehört Domain. Diese Indexänderung folgt dem
vor Quellcode committed `METER_INVENTORY_PLAN.md`, nicht einer eigenmächtigen
Migration oder einem Platzhalter für Domainquellen.

Vorgesehener additive Index:
`standalone_meter_readings(meter_id, reading_date DESC, id COLLATE BINARY/C DESC)`.
Er bedient die konkrete jüngste Ablesung eines Meters und den stabilen
Tagesdatum/ID-Keyset der paginierten Meterhistorie. Bytewise-ID stimmt mit
den vorhandenen SQLite-/PostgreSQL-Sortausdrücken überein. Der Index erstellt
keine Daten, verändert keine Originale oder nullable Maßeinheiten und ergänzt
keine historische Zuordnung. Es gibt keine Datenanzahlgrenze.

Die Migration verwendet explizites Alembic `op.create_index` bzw.
`op.drop_index` mit dialektrichtigem Ausdruck; kein zur Laufzeit an globalen
ORM-Metadaten angehängtes `Index` und keine Startup-DDL. Wiederholtes
Upgrade/Downgrade darf keine doppelt registrierten Pythonindexnamen erzeugen.
Keine Änderung bestehender Migrationen, Modelle oder Recoveryquellen.

Sourcepatch darf jetzt vorbereitet werden. Tatsächliches DDL-/Alembic-Gate
erst nach Übernahme des echten j2 in diesen Checkout und Rootfreigabe eines
abgestimmten Testslots. Natives SQLite und PostgreSQL in UUID-Schema prüfen
Indexausdruck, wiederholtes Upgrade/Downgrade, Originaldaten und reale
EXPLAIN-Ablesepläne. Ein separater Unit-/Prüfdatumindex wird erst durch
konkreten EXPLAIN-Nachweis und weitere Rootreservierung gerechtfertigt.

Ohne diese ausgeführten Gates wird ausschließlich begrenzte SQL-
Ergebnismaterialisierung behauptet, kein indexgestützter Laufzeitnachweis.
