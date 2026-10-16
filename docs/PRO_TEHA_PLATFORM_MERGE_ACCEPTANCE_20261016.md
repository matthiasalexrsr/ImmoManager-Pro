# Gemeinsame Integrationsschnittstelle TEHA + Plugin/S3 – Zwischenabnahme

**Status: synthetische Integration im eigenen Entwicklungszweig; kein Release.**

- Checkout `pro-stage-interfaces-teha-platform-20261016`, Branch
  `pro/stage-interfaces-teha-platform-20261016`.
- Grundlage ist der geprüfte API-/Plugin-/S3-Checkpoint `0ef2dd12`
  mit Produktcode `f1a2917e`. Der separate TEHA-Checkpoint
  `d35057c0` wurde über einen Git-Dreiweg-Cherry-Pick übernommen.
- Kein Zugriff auf laufende Anwenderinstallationen, ports 8000/8765,
  reale Schlüssel, TEHA-Portalaktionen, Kauf-/Bank-/Versandprozesse
  oder den zentralen Checkout `claude-review-20261013`.
  Dieser blieb bei `04021da5` sauber.

## Konflikte fachlich aufgelöst

1. `document_versions.Unit` behält den identitätsgebundenen
   Append-Rollback und das separate Writer-Lock bei: Ein fehlgeschlagener
   TEHA-Vorgang darf nie den späteren Auditeintrag eines anderen
   Schreibers entfernen.
2. `full_backup.py` zählt jetzt **gleichzeitig** portable Upload-
   Originalreferenzen, Pluginpakete, Bank-/Kommunikations-/Steuer-
   Schlüssel und die neuen verschlüsselten TEHA-Originalquellen aus
   **demselben** archivierten SQL-Snapshot. Die PG-dump-Variante
   erhält ebenfalls alle TEHA-Schlüssel-IDs und das
   ursprüngliche Runtime-/Originalinventar.
3. `upload_policy.py` schützt unveränderte TEHA-Originaldateien
   zusätzlich zu allen älteren unveränderlichen Dokumentquellen.
4. Die beiden additiven Historien
   `e1f0a1b2c314` (Plattform) und `e1f0a1b2c3f7` (TEHA)
   werden nur über die neue Merge-Revision `e1f0a1b2c315`
   verbunden. Keine Elternrevision wurde geändert. Ein
   zerstörender Downgrade einer belegten Datenbank wird vor dem
   ersten Schritt verweigert.

## Neue echte Sicherheitsgegenprobe

Die Plattform erstellt **kein** Vollarchiv, wenn sie TEHA-Daten
findet, deren Verschlüsselungsschlüssel nicht in der Sicherung
enthalten sind. Der ältere TEHA-Test erwartete ein beschädigtes,
erst beim Restore abgelehntes ZIP; in der gemeinsamen Implementierung
wird es bereits bei `create_full_backup` verweigert. Der
synthetische Quellbestand bleibt erhalten und es erscheint weder
ein finales ZIP noch eine wiederhergestellte Zieldatenbank.

Weiterer Befund: `full_backup._secret_files` kennt drei tatsächlich
archivierte Schlüsselquellen: `keyring.json`, archiviertes
`config/env` und die im passphrasengeschützten
`RUNTIME` abgelegten `secret_keys`. Deren Prüfung war im
privaten TEHA-/Connection-RESTORE nicht einheitlich. Die
vereinheitlichte `_archived_connection_keys`-Funktion
akzeptiert die vorhandenen Schlüsselquellen **ausschließlich aus
dem Backup**, erkennt widersprüchliche Schlüssel-IDs und gibt
bei Fehlern keine Secret-Bytes aus.

## Nachprüfbare Läufe

- Zuerst kombinierte Matrix
  `artifacts/pro-tests/teha-platform-cross-sql-sql-55a63af067db43f2af7df61e5f5b93fa`:
  55 bestanden, 1 umgebungsspezifischer Skip, 1 **roter Test
  wegen der strengeren Backup-Erstellungsgrenze**. Nicht grün
  behaupten. Der folgende gezielte Regressionslauf nach der
  Testkorrektur
  `artifacts/pro-tests/teha-platform-backup-contract-sql-a7ec1b5c26144d27856dc232fa540d43`
  besteht **8/8**.
- Archiv-Runtime/ENV/Keyring-Positiv- und Negativprüfungen:
  `artifacts/pro-tests/archive-runtime-only-key-sql-6be24d546b464031be63a4fd96dc7d6a`
  **6/6 bestanden**.
- Additive gemeinsame Migration aus Altbasis, Altbestandswertvergleich
  und Downgrade-Guard:
  `artifacts/pro-tests/cross-merge-schema-fixed-sql-c81c7f73b9dc489a9ccc1ac60d223477`
  **1/1 bestanden**.
- Kompletter neu installierter Reactteil:
  **29/29** gezielte TEHA-, Plugin-, Connection- und Bank-Komponententests
  bestanden; `npm ci` mit 0 gemeldeten Schwachstellen,
  ESLint und Vite-Produktionsbuild bestanden.
- **Ruff und Mypy --platform linux für 558 Backenddateien** im
  zusammengeführten Arbeitsstand bestanden. Nach jeder nachfolgenden
  Änderung muss die statische Prüfung erneut laufen.
- Native PostgreSQL- und vollständige SQL-Gegenmatrix auf dem
  **späteren Merge-Commit** sind eigenständige noch nicht erfüllte
  Abnahmebedingungen; ältere isolierte Läufe reichen nicht.

## Ausdrücklich weiterhin offen

- Der Channel-Checkpoint `2da46904` besitzt noch keinen
  freigegebenen gemeinsamen Alembic-Head. Seine zuvor blockierte
  Änderung darf nicht über einen anderen Zugang erzwungen werden.
- Die ältere globale IntegrationManager-Konfiguration und
  `integration_connections` besitzen noch keine
  freigegebene alleinige Produktkonfigurationsautorität.
- Es gibt keine autorisierte echte TEHA-Portalsitzung und
  keine Liveabnahme der TEHA-Rückübertragung.
- Der gesamte Handover beinhaltet weitere bislang
  nicht realisierte Fach- und Operationspakete. Weder dieser
  Zusammenführungscommit noch sein Teststatus sind
  eine Vollständigkeits- oder Auslieferungsfreigabe.
