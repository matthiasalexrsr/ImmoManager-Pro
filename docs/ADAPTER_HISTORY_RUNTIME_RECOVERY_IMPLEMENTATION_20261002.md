# Konkrete Einbindung der Adapterhistorie

Vor Code gelesen: Rootplan `ADAPTER_HISTORY_RUNTIME_RECOVERY_PLAN_20261002.md`
aus dem unveränderten Commit `d8696c5`. Eigener Checkout
`work/integration-history-runtime`, Branch
`assist/integration-history-runtime-recovery`. Core-Autor besitzt weiterhin alle
Historien-/Manager-/Routerquellen in seinem getrennten Checkout.

## Versionierung und API-Abgleich

Zuerst den ersten versionierten Corestand übernehmen und vollständig lesen;
keine fremden Arbeitskopien als eigene Quellen kopieren. Eigene Hookcommits
beginnen nach diesem Basiscommit und verändern keine Coredateien. Angekündigte
APIs vor dem versionierten Abgleich:

- `integration_history_models.HISTORY_MODELS/TABLES`: genau fünf Tabellen;
  die Lauftabelle heißt `integration_runs`.
- `integration_history_schema.ensure_history_schema(connection)`: rein lesend,
  vollständig fehlend `False`, teilweise Familie/fehlende Spalten verweigert.
- `history_validation.validate_history_journal(connection, configuration,
  deadline=None)`: rein offline, SQLite/SQLAlchemy, fehlende Familie vor
  Schlüsselauflösung; vorhandene Fakten mit explizitem Archivschlüsselring.
- `history_store.configure_history(session_factory)`: eigener dauerhafter
  SQL-Speicher auf der tatsächlichen DATABASE_URL, unabhängig vom Domänenmodus.
- Restore-Normalisierung und Lauf-/Clear-Serialisierung werden am ersten
  versionierten API-Vertrag ergänzt, bevor davon abhängiger Code entsteht.

## Umsetzungsreihenfolge

1. Registrierungen in normalem `db/session.py` und Alembic ergänzen. Lokaler
   Start prüft die vollständige optionale Familie vor `create_all`, einschließlich
   Metadaten. Frisches explizites Setup/Migration darf DDL besitzen; der Validator
   und Recoverybridge schreiben niemals Tabellen oder technische Köpfe nach.
   Historienkonfiguration außerhalb des möglichen Memory-Domänenfallbacks
   initialisieren; Datenbankfehler dürfen keine RAM-Historie erzeugen.
2. Testkonfiguration noch vor Import von Anwendung/Session immer auf eine eigene
   temporäre DATABASE_URL setzen, wenn keine ausdrückliche synthetische URL
   vorhanden ist. Das gilt auch im Memory-Domänenmodus. Dieser neue tatsächliche
   SQL-Nebenspeicher darf weder die Produktdatenbank noch fremde Testdateien
   berühren; nur das eigene Tempverzeichnis wird nach Session-/Engine-Abschluss
   entfernt.
3. Einen schmalen Recoverybridge mit Schlüssel- und Fehlergrenzen ergänzen.
   SQLite-`_database_info` besitzt keine Archivkonfiguration: dort nur optionale
   Metadatenprüfung plus Legacy-Ausnahmen der gemeinsamen ORM-Tabellenliste.
   Anschließend `verify_history(database, explicitConfiguration)` auf dem
   unveränderten staged Bild, analog zu IBAN/Entwurfsprüfungen. Auf Sicherungs-
   und Restorepfaden erfolgt die volle Crypto-/AAD-Prüfung vor Dateiverweis-
   Rebasing, Claims, Sitzungswiderruf und Signierrotation.
4. SQL-`invalidate_and_inspect` erhält bereits eine ausdrückliche Konfiguration:
   volle lesende Historienprüfung in der Caller-Offline-Transaktion, danach
   Restore-Normalisierung begonnener Läufe. Kein Provideraufruf oder Replay;
   Ausgang bleibt unbestätigt. Normalisierung, Job-Claimreset und Sessionwiderruf
   rollen bei jedem Folgeschaden gemeinsam zurück.
5. Subsetexport/Import und generischer Reset verweigern tatsächliche vorhandene
   Lauf-/Ergebnisfakten mit Verweis auf Vollarchive. Reine technische Heads und
   minimale Clearbelege bleiben erhalten und erzeugen keinen dauerhaften
   Subsetkonflikt. SQL `clear_all` überspringt ausdrücklich alle fünf Tabellen.
   Vor destruktiver Domänen-DML recheck hinter derselben Writerbarriere; Pending-
   Historien-DML wird nicht committed. Memory-Domänenmodus liest/serialisiert die
   tatsächliche separate SQL-Historie, nicht erfundene RAM-Kopien. Lockreihenfolge
   wird mit dem versionierten Start/Clearvertrag abgestimmt.
6. Echte Gates: frische Alembic-Linie und Up-/Downgrade; beschädigte Familie vor
   DDL; vollständig altes Vollarchiv; verschlüsseltes SQLite-Roundtrip mit echten
   Resultchunks; falscher Schlüssel/AAD; offene Ausführung; PostgreSQL-Offline-
   Transaktion samt Folgefehlerrollback; Pending-/Parallelreset und Clear-only-
   Wiederholung. Bestehende Startup-/Recovery-/Transferprüfungen mitlaufen lassen.
   CI und Typ-/Lintlisten enthalten alle neuen Produktmodule ausdrücklich.

## Abnahmekriterien und Grenzen

Keine Änderung an UI, AI, Historienkern, Manager, Router oder PrivacyFence.
Kein Schreiben in Root/Main/Preview, keine Provideraktionen, kein Push. Jeder
gesicherte Inhalt ist ein tatsächlicher versionierter Corefact. Eine fehlende
Schlüsselkonfiguration, beschädigte Familie oder unbestätigte Ausführung wird
niemals als erfolgreiche Zustellung oder leere RAM-Historie ausgegeben.
Coretests ersetzen nicht die zusätzlichen tatsächlichen Archiv-/Laufzeitgates.
Abweichungen von diesem Plan werden vor ihrer Implementierung dokumentiert.
