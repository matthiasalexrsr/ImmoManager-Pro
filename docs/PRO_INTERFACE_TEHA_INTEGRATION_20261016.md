# TEHA – Integration auf dem bisherigen Schnittstellen-/Finanz-/Kommunikationszweig

Stand: 16.10.2026. Entwicklungsworktree:
`pro-stage-interfaces-teha-20261016`, ab `3017c330`.
**Keine Freigabe der laufenden Anwenderinstallationen** (8000/8765);
keine echten TEHA-Konten, kein externer Auftrag, kein Produktiv-Import.

## Implementierte Vertragsgrenzen

- Der TEHA-Leseprovider wird nach dem Import seiner Klassen initialisiert:
  der unmittelbare Providerimport darf keine zirkuläre Initialisierung des
  globalen Integrationsmanagers auslösen.
- Die eingefrorene externe Quelle wird nur aus dem *authentifiziert
  metadata-gebundenen* v2-Ergebnisnachweis der ConnectionRuns gelesen.
  Der zentrale `connection_evidence.result_value` prüft
  Kontext, Run-ID, Blocksequenz, SHA256, Byteanzahl und vollständige Größe.
  Die zuvor v1-spezifische einfache Base64-Interpretation wurde entfernt.
- Importseiten und erneute Bestätigungen verwenden dauerhafte
  Wiederholungsschlüssel, revisionsgebundene Quellidentitäten und
  ausdrücklich gewählte Zielakten. Rechteentzug und veraltete
  Aktenstände sperren die weitere Übernahme; erhaltene Originale bleiben
  unverändert überprüfbar.
- Ein separater additiver TEHA-Zweig `e160a1b2c307` folgt auf
  `d73f2b9a041c`. Der *neue*, datenfreie Merge-Head
  `e1f0a1b2c3f7` verbindet ihn mit dem bisher integrierten
  `e1f0a1b2c3f5` und verweigert den partiellen SQLite-Downgrade
  **vor** dem Rückbau, sobald geschützte Originalbelege bestehen.
- `full_backup.py` zählt die benötigten TEHA-Schlüssel nur aus dem
  eingefrorenen Datenbank-Snapshot. Die generische Vollrestoreprobe
  überprüft die verschlüsselten TEHA-Batches, Identitäten, Mappings,
  Originalversionen, Quittungen und Return-Drafts **mit Archivschlüsseln**,
  ohne Zugriff auf die aktuelle Schlüsseldatei oder Provider.
  Ein vollständig gültiges ZIP ohne diese Schlüssel erhält keinen
  grünen Restorebeleg.
- Die Rücksendung von Kosten-/Nutzerdaten oder Aufträgen ist mangels
  belastbarem externer Schreibvertrag **nicht freigeschaltet**.
  Verfügbare Entwürfe sind keine erfolgten Übertragungen.

## Reproduzierte Abnahme – synthetische Daten

- `teha-v2-suite-memory-f9a49be302054fea8214053935648b12`:
  **222 bestanden, 3 kontextabhängig übersprungen**.
- `teha-v2-suite-sql-4aa5f96376f1477c989102ef5063be7e`:
  **224 bestanden, 1 kontextabhängig übersprungen**.
- Vollbackup auf einer tatsächlich isolierten SQLite-Testdatenbank:
  `teha-restore-stamped-sql-b9cdc395594c4bf3ba28da7ab9377775`:
  **2/2**, darunter Ablehnung ohne Schlüssel und Restaurationsprüfung.
  Der Quellfixture wurde mit Alembic-Head gestempelt, weil er bewusst
  `Base.metadata.create_all` für unabhängige Mehrsitzungstests nutzt.
- Native, eigens gestartete und danach beendete PostgreSQL-Instanz:
  `artifacts/pro-native/e1254ed9017446e38ef8da0359f30a47`,
  **5/5 ohne Skip** mit gesonderten konkurrierenden SQL-Sitzungen.
- Frontend: nach frischem `npm ci` **38/38** TEHA/Connection/
  Bank/Kommunikation-Komponententests, ESLint und Vite-Build erfolgreich.
  Die React-Tests melden lediglich bereits bekannte `act`-Warnungen.
- Nach einer unabhängigen Audit-Rollbackkorrektur für nachfolgende
  parallele Anhänge: **3/3** einschließlich Rechteentzug/TEHA. Die
  erweiterte aktuelle Memory-Matrix meldet **232 bestanden,
  5 kontextabhängig übersprungen** unter
  `teha-static-final-memory-21c2cd977f83415eaa38c41b7035534c`.
- Ruff und Mypy `--platform linux`: 542 Backenddateien fehlerfrei.
  Die erneute, vergrößerte kombinierte SQLite-Matrix ist mit
  **226 bestanden, 1 kontextabhängig übersprungen** abgeschlossen:
  `teha-static-final-sql-cf6eee78eb8542bfa146ff0074410336`.
  Beide umfangreichen neuen Läufe wurden noch mit dem Ausgangs-HEAD
  `3017c330` gegen die uncommittete, nun exakt dokumentierte
  Arbeitskopie gestartet. Das Commit und seine nachfolgenden Gates
  müssen im Endmanifest getrennt als finaler Codehash geprüft werden.

## Beweisgrenzen

TEHA-Live-Portal, TEHA-Zugriffsfreigabe, Lieferantenschema unter
Realbedingungen, echte Dokumenten-/Periode-/Abrechnungshistorie,
nicht nachgewiesene externen Schreibverträge, browsergestützte
produktähnliche Akzeptanz sowie die **Zusammenführung mit allen
anderen Paketen auf einem endgültigen Codehash** sind offen.
Die funktionierenden lokalen synthetischen Verträge sind nicht
automatisch eine Live-Portalzertifizierung.

Andere Branch-Quellen und der zentrale Referenzcheckout wurden nicht
beschrieben oder gemerged. Datenbanken, Browser und PostgreSQL liefen
jeweils nur in isolierten QA-Verzeichnissen.
