# Datenbankschema

Das Schema entsteht nur aus dem Programm, nie aus einer SQL-Datei:

- **Neue Datenbank** (SQLite oder PostgreSQL): Der erste Start oder `python -m backend.upgrade` legt sie aus den Modellen in `backend/db/*_models.py` an und vermerkt den aktuellen Migrationsstand.
- **Bestehende Datenbank:** `python -m backend.upgrade` (im Windows-Paket `ImmoManager-Pro.exe upgrade`) legt zuerst ein Vollbackup an und führt dann die Migrationen aus `backend/db/migrations/versions` aus.

Beide Wege ergeben dasselbe Schema; `backend/tests/test_schema_parity.py` prüft das, auch für PostgreSQL.

Die frühere Datei `schema.sql` (33 der heute 159 Tabellen, ohne Migrationsstand) ist entfernt. Eine damit angelegte Datenbank startet nicht.
