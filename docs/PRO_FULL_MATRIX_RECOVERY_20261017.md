# PRO Handover – sichere Migrations-, Berechtigungs- und Restore-Matrix
**Fortsetzung 17.10.2026, Entwicklungscheckpoint – kein Release.**

Der isolierte Zweig `pro/stage-full-matrix-20261016` baut ausschließlich auf
`57ab0a56` (TEHA + Plugin/S3) auf. Der zentrale Referenz-Checkout
`claude-review-20261013` blieb bei `04021da5` sauber. Die Ports
8000/8765, reale Anwenderdatensätze, Fremdprovider und externe
Zahlungs-/Versandaktionen wurden nicht benutzt.

## Behobene technische / fachliche Ursachen

1. **Sichere Übernahme aktueller, aber unversionierter ORM-Datenbanken.**
   Das Hilfsmodul `backend/db/migrations/adopt_existing.py` akzeptiert
   additive, bereits vorhandene Tabellenfamilien ausschließlich nach
   exakt gleichen Tabellen, Spalten, Typen, PRIMARY KEY/NOT NULL,
   eindeutigen Indizes, CHECK/UNIQUE-Constraints, Fremdschlüsseln
   einschließlich Löschregeln. Teilfamilien oder weniger geschützte
   Datenstrukturen scheitern **vor** einer Migration. Der normale
   Upgradeweg auf ältere, tatsächlich unvollständige Bestände
   bleibt ausdrücklich erhalten. Die vorhandenen additiven
   Communication-, Daily-, Inbox-, Session-, TEHA- und
   Plattformmigrationen verwenden die Prüfung. Die alte
   Migrationshistorie wurde nicht umnummeriert.
2. **Keine teilweise destruktiven SQLite-Downgrades.** Die gemeinsame
   Merge-Revision `e1f0a1b2c315` stoppt den Rückbau bereits
   an der ersten Grenze, auch wenn das Schema aktuell leer ist.
   Historische, für sich reversible Migrationen werden nach
   Rückstellung auf ihren **eigenen** alten Versionsstand
   geprüft – nicht mittels unberechtigtem Rückbau aller
   neuen, bewusst unveränderlichen Quellbelege.
3. **Kürzere, eigens isolierte Windows-Runtimes.** `run_pro_matrix.py`
   speichert JUnit/Logs weiterhin unter dem benannten
   `artifacts/pro-tests/`-Pfad, legt Originalfotos, PDFs,
   Schlüssel und Testdatenbanken dagegen in einem pro Lauf
   neu erzeugten Unterordner `artifacts/r/<uuid>` ab.
   Der Prüflauf bewahrt zusätzlich den SHA256 des Launchers
   auf. An produktiven Speichergrenzen wurde nichts gelockert.
4. **Bankimporte benötigen eine bestätigte Vorschau.** Die drei
   alten CSV-Beispiele prüfen weiterhin genau ihre Centbeträge,
   fehlerhaften Datensätze und deutsche Dezimaltrennzeichen.
   Die frühere unautorisierte Autoverbuchung wird nun
   **explizit mit HTTP 409 zurückgewiesen**, und der Buchungsstand
   bleibt unverändert. Der separate echte Import-/Matching-Vertrag
   existiert weiterhin unter `test_bank_imports_controlled.py`.
5. **Persönliche Benachrichtigungsquittungen statt globaler
   Statusumschaltung.** Das Legacy-Blindmarkieren und
   status-PATCH bleibt gesperrt. Lesende persönliche Eingänge,
   `read_all` mit Snapshot und Idempotenzschlüssel, filtrierte
   Quittungen sowie gültige Nichtvorhandensein-/Zugriffsmeldungen
   werden getestet. Ein fehlgeschlagener Quittungsversuch
   überschreibt keinen Benachrichtigungsoriginalstatus.
6. **Kryptographische Backup-Kontextbindung.** Der
   `test_message_recovery.py`-Fixture verschlüsselt
   Erweiterungsdaten jetzt unter ihrem authentifizierten
   archivierten JSON-Pfad
   `integrations/qa-extension/proof`; die Restoreprüfung
   akzeptiert keine willkürliche Ersatzbindung.
7. **Unveränderbare Rechnungsoriginale.** Der Anwendungsspeicher
   verweigert das Überschreiben gleicher Schlüssel mit neuen
   Bytes. Der Rechnungstest beweist zuerst diese Ablehnung,
   simuliert dann eine **außerhalb der Anwendung** erfolgte
   Beschädigung seiner eigenen synthetischen lokalen
   Wegwerfdatei und verlangt eine erkannte
   `document_changed`-Abweichung.
8. **Vollrestore erweitert, nicht abgeschwächt.** Die älteren
   Backup-Tests verlangen weiterhin den entschlüsselten
   Ursprung und prüfen nun zusätzlich die Zählbelege der neuen
   Bank-, Steuer- und Kommunikationsfamilien, die früher nicht
   in der Antwort enthalten waren.

## Nachprüfbare gezielte Resultate

- Historische Downgrades, ausschließlich korrekte alte Revisionen:
  `artifacts/pro-tests/historical-revision-specific-sql-16c958f824c24ef39dd144ce4423fcec`:
  **7/7 SQLite**.
- Vollständige Migration-/Adoptionssuite inkl. Guard-Negativfällen:
  `artifacts/pro-tests/migration-full-current-sql-582b1bd89c404f2baec67aab8ba52727`:
  **37/37 SQLite**.
- Bank-/persönliche Benachrichtigungs-API und CSV-Originalparser:
  `artifacts/pro-tests/personal-bank-current-sql-sql-d8a526aa6ba74617b141de3b05f771f9`:
  **53/53 SQLite**; Memory-Proben je 22/22 Benachrichtigungen
  und 31/31 Bank-/Formatfälle.
- Unveränderte Backup-, Rechnungs- und Benachrichtigungsquellen:
  `artifacts/pro-tests/backup-invoice-notice-verified-memory-4c6ef8d278e747549bb1678eacd28239`:
  **3/3 Memory**, ohne Skip. Derselbe komplette
  Backup-/Invoice-/Notification-E2E-Block unter
  `artifacts/pro-tests/backup-invoice-notice-verified-sql-2083bdface8a49aaaf83d05ddeef3c5a`:
  **3/3 SQLite**, ohne Skip.
- Schutzberechtigungen der alten Blindmarkierung gegen die
  persönliche Receipt-API:
  `artifacts/pro-tests/notice-stress-permissions-memory-3fb0f874743e44a08104601908add762`:
  **22/22 Memory**.
- Nachricht mit eingefrorener Quellrevision und Archiv-/AAD:
  `artifacts/pro-tests/message-restore-bound-key-memory-243fd2715114434392669a21da15dfdf`:
  **1/1 Memory**.
- Der frühere gemischte Backend-Volllauf vor dieser
  Korrektur bestand **2612** Fälle, meldete aber **54 Fehler**,
  **114 Skips** und **83,63 % Zeilenabdeckung**.
  Es wurde nun ein erneuter vollständiger Memory-/Coverage-
  Lauf unter `artifacts/pro-tests/backend-full-corrected-memory-46b2b18ebed4428db6bde2ee222ceb73`
  gestartet. Er lief **während** der nachfolgenden
  weiteren Testdateiänderungen; daher ist sein Provenienzstatus
  `historical_working_tree`, nicht der Beleg des späteren
  Commits. Die Gesamtmatrix erst nach beendeter eigener
  Prüfung und unverändertem Quellhash als bestanden deklarieren.
- Der separate Frontend-Kompatibilitätscheckpoint
  `pro/stage-frontend-compat-20261016`, `b209025a`
  enthält **657/657** vollständige React-Tests (104 Dateien,
  zwei Testworker, unveränderte Assertions). Er ist noch
  **nicht** mit diesem Backendcheckpoint zusammengeführt.
- Backend-Ruff sowie Mypy `--platform linux` sind nach den
  letzten Typ-/Testkorrekturen für **562 Quelldateien grün**.

## Release-Blocker, die durch diese Teillieferung NICHT verschwinden

Der gesamte Handover-Auftrag ist noch offen. Insbesondere
fehlen der exakte kombinierte Git-Head aus allen übrigen
Fachpaketen, die vollständige native PostgreSQL-/Memory-/SQL-
Matrix ohne ungeprüfte Skips, echte Anbieter-/Zielsystembelege
für TEHA, Banking/FinTS, Portale, WhatsApp/Post, DATEV/WISO
und Aktenwerk, die einzig autoritative Legacy-/Connection-
Konfigurationsverwaltung, der vollständig wiederhergestellte
Gesamtbestand auf eigener Testinstallation sowie die
größeren Fach-/Performance-/Restoreprüfungen.
Die optionalen FinTS-Bibliotheken wurden in anderen isolierten
Arbeitskopien nachgewiesen, nicht als native Livebankverbindung.
Die historische Audit/Notifications-API benötigt zusätzlich
eine vollständige kombinierte Auth- und Lastabnahme.

**Keine Änderungen an laufenden Userinstallationen, kein Push
auf den zentralen Branch, keine Auslieferungsfreigabe.**
