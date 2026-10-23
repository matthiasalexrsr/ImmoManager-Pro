# Geschützte Integrationsverbindungen – Prüf- und Übernahmepaket vom 16.10.2026

## Auftrag und Abgrenzung

Dieses Paket setzt die bestehende Anwendung im eigenen Zweig `pro/interfaces-20261015` fort.
Der bereits gepushte Nachrichtenstand ist `b264cf81`; der aktuelle Grundstand
der Verbindungsentwicklung ist `c16e0970`. Die hier beschriebenen
Folgekorrrekturen sind mit ihren Quellen und Resultaten getrennt zu committen.

**Keine Benutzerinstallation, echte Zugangsdaten, Produktivbank, Nachrichtenadresse,
Portokäufe oder veröffentlichten Inserate wurden für diese Tests benutzt.**
Der zentrale Integrationszweig, die Windows-Installationen auf 8000/8765,
Anwenderdaten, private Schlüssel und alte Migrationen wurden nicht verändert.

Das ist eine Implementierungs-/Prüflieferung des *gemeinsamen Verbindungsrahmens*.
Sie ersetzt weder das vollständige Handover noch die fehlenden echten
Gegenstellenabnahmen. Der Altproviderpfad bleibt aktiv; der Umschalt-Bridge
ist absichtlich **nicht** implizit aktiviert, solange seine alleinige
Konfigurationsautorität und Migration nicht nachgewiesen sind.

## Funktionierende Wege und Verträge

- Getrennte private SQL-Daten für Verbindung, secret references, Quellbeobachtung,
  Mappingentscheidung, vorbereitete Aktion, Run/Versuch, verschlüsselte Ergebnisblöcke,
  abgeschlossene und verspätete Belege sowie metadatengebundene Ereignisse.
- Geheimnisse und unbekannte Quellfelder werden im vorhandenen Schlüsselring
  verschlüsselt gespeichert. `***` ist Maskierung, kein neuer Secretwert.
  Ohne richtigen Schlüssel wird kein leerer Erfolg und keine verdeckte Reparatur behauptet;
  eine explizite Notabschaltung darf den verschlüsselten Rest erhalten.
- Explizite Aktionsvorschau, Quellen-/Konfigurationsrevision, Wiederholungsschlüssel
  und tatsächliche Rechteprüfung. Ein fremdes Portfolio oder ein alter Benutzer
  erhält weder private Quelle noch Provideraktion. Beobachtetes Feld ist niemals
  automatisch eine neue Schreibberechtigung.
- Die angenommene Aktion speichert ihren Claim **vor** Netzwerk-I/O. Empfangene
  Rohantworten werden in AES-GCM-gebundenen Blöcken mit vollständigen SHA-256-
  und Reihenfolgenbelegen gespeichert. Ein verlorener Browserresponse oder
  ein verspäteter Worker darf denselben externen Auftrag nicht erneut senden.
  Gespeicherte verspätete Resultate sind einzeln, fortsetzbar und nur nach
  ausdrücklicher Prüfung als solche zu übernehmen.
- Vorbereiteter Run und aktueller Providerzustand bleiben getrennt. Bei
  gelöschter Quelle bleibt überprüfbare Historie, aber kein neuer Versand.
  Lesende Quellseiten sind via Cursor fortsetzbar; unmögliche Folgetoken/
  Cursorzyklen werden als Sperrfall behandelt.
- Event- und Run-Leseseiten sind SQL-gestützt begrenzt und zählen unabhängig
  von der sichtbaren Seite. Dabei werden die Rechte des aktuellen Benutzers
  geprüft, nicht nur die des historischen Erstellers.
- Additive Migration `d73f2b9a041c` nach `c61e9a2f034b`, danach
  `e160a1b2c300` für Versuchsbelege und Cursorbesuche. Ausdrücklich belegte
  Daten verhindern destruktive Downgrades. Neue Migrationen anderer Worker
  sind *nicht* automatisch Teil dieses linearen Teilgraphs.

## Wiederherstellung: neue geprüfte Schutzgrenze

Das Offline-Modul `connection_archive.py` validiert Tabellenstruktur und jede
vorhandene private Entität mit ausschließlich explizit übergebenen Archivschlüsseln.
Es liest weder aktuelle Konfiguration noch den Runtime-Schlüsselring. Ein
eingefrorener Run speichert seine Konfiguration im authentifiziert verschlüsselten
`snapshot.config`; ein veralteter `config_token`-Pointer wurde entfernt.

`full_backup.py` führt die private Prüfung jetzt auf der extrahierten SQL-Kopie
bei der Restoreprobe aus. Sie ist dort read-only und berichtet nur gezählte,
nichtgeheime Tatsachen. Eine echte Wiederherstellung prüft vor der
Veröffentlichung des frischen Ziels und markiert einen unterbrochenen
Provider-Write als `unknown`, ohne diesen wiederholt auszuführen.
Staging-Fehler verhindern die Publikation der SQLite-Datenbank. Für ein
PostgreSQL-Wegwerfziel erfolgt die Prüfung innerhalb einer echten
Zieltransaktion nach `pg_restore`; ohne Restoreziel bleibt der
bestehende begrenzte `pg_restore --list`-Hinweis, keine erfundene Vollprobe.
Fehlen die tatsächlich archivierten Schlüssel, ist kein grüner privater
Prüfnachweis möglich.

Der Negativfall **gültiges ZIP-SHA + gültige SQLite-Integrität + beschädigtes
privates Ciphertext** wird von `restore_probe` und `restore_archive`
verweigert, ohne das alte Quellciphertext zu ändern.

## Ausgeführte Nachweise, mit synthetischen Daten

- Korrigierter Offline-Nachweis: **41/41 Memory** unter
  `artifacts/pro-tests/connection-offline-fix-memory-206e56dec0ce4af8bddd13b74863ef45`;
  **41/41 SQLite** unter
  `artifacts/pro-tests/connection-offline-fix-sql-d1683c6c1a254ba684e7f8e2f02e995c`.
  Gegenproben für Archividentität, Referenzen, Ciphertext, Restaurationsfence und
  gespeicherte Eventidentität sind ohne Skip grün.
- Vollständig unabhängig gestartetes PostgreSQL-Cluster
  `artifacts/pro-native/75e4b79c9279439798f5b4a482a80e08`:
  **42/42**, **0 Skips**, anschließend kontrolliert beendet.
  Zusätzlich sind **47/47** im späteren nativen Kombinationslauf
  `artifacts/pro-native/3f62d884fc3c4fddaf7110726de81f69` bestanden.
  Der unabhängige native PostgreSQL-Vollbackup-/Restorenachweis
  `artifacts/pro-native/cfcd970bcfaf4ebc95bcfa2a77a6d87b`
  ist **1/1 ohne Skip** grün. Alle Cluster wurden beendet.
  Keiner dieser Läufe ist ein echter Live-Provider-Nachweis.
- Eigener Playwright-Lauf `artifacts/connection-browser/connections-enbphhzb`:
  **7/7** mit Anmeldung, Anlegen, eingefrorener Vorschau ohne Provideraufruf,
  gesonderter lokaler Bestätigung, readonly-Grenze, Tastatur sowie 1440/360/320px.
  Screenshots `connections-{1440,360,320}.png` wurden visuell begutachtet.
  Nur lokaler `contract-wizard` für den synthetischen Ablauf.
- Gezielte Frontendtests: **8/8** `IntegrationConnections.test.jsx`,
  ESLint und Vite-Produktionsbuild bestanden.
- Vollarchiv-/Restore- und alte Betriebsregressionen:
  **56/56 Memory**, `artifacts/pro-tests/connection-root-backup-memory-116b7987b84d4ff8bd211fbd5a8aa57b`.
  **57/57 SQLite** einschließlich der später ergänzten Manipulationsgegenprobe,
  `artifacts/pro-tests/connection-root-backup-sql-ac2cde9db53b4357ad1686265f412e80`.
  **1/1** manipulierter Ciphertext korrekt abgewiesen,
  `artifacts/pro-tests/tamper-recovery-memory-08f2ce8a8c26466391d16c25bc713b23`.
- Die neue Migrationsprüfung inkl. Bestandswertvergleich und geschütztem
  Downgrade ist bestanden, ebenso der reale Vollrestore mit ausschließlich
  den wiederhergestellten Schlüsseln (`connection-full-restore-{memory,sql}-...`).
- **>10.000** verschlüsselte private Ereignisse und **10.033**
  separate vorbereitete Runs mit identischen Zeitstempeln: alle Cursor
  vollständig in Memory und SQLite. Die SQL-Gegenproben sind unter
  `artifacts/pro-tests/connection-10k-runs-sql-d4de897e51a54edaa9a0b34292cc9293`
  erhalten. Ältere Prüfläufe sind keine Prüfung späterer Änderungen.
- Statisch Ruff sowie Mypy `--platform linux` für 441 Quelldateien
  nach den dokumentierten Typkorrekturen ohne Fehler; die letzte
  gezielte Endprüfung erfolgt erneut auf dem tatsächlichen Commit.

## Fachliche Grenzen und weitere Abnahme

1. Der bisherige globale IntegrationManager und der neue private
   Connection-Speicher besitzen **noch keine freigegebene alleinige
   Konfigurationsautorität**. Das bewusste `connection_bridge_enabled=False`
   ist keine abgeschlossene Altlastübernahme. Zwei aktive produktive
   Konfigurationspfade dürfen nicht still gegeneinander schreiben.
2. Die sieben lokalen Provider-Manifeste sind kein Beweis unterstützter
   Liveaktionen. SMTP-Liveempfänger, TEHA, Banken/FinTS, WhatsApp,
   Postzahlung, Portale, Aktenwerkgegenstelle und weitere fremde
   Integrationen benötigen kontrollierte echte Belege.
3. Die gemeinsame Wiederherstellung für andere neuen Domain-Migrationen,
   externe Backup-Keybündel, PostgreSQL-Ziel-Relokation und
   mehrjährige Vollbestände bleibt in der **Gesamtintegration** gesondert
   abnahmebedürftig; lokale Ciphertext-Tests ersetzen dies nicht.
4. Die übrigen Handoverspakete sind in den 14 koordinierten Worktrees
   inventarisiert und noch nicht als Gesamtsystem zusammengeführt.
   Sie benötigen eigene Fachorakel, Migrationgraph, CI, native
   PostgreSQL- und echte Browserabnahme.

## Übergabe für Codex

Einschließlich aller aktuellen Änderungen in dieser Arbeitskopie, nicht
einzeln alte Rohdokumente cherry-picken. Conflictheads:
`backend/db/__init__.py`, `backend/services/full_backup.py`,
`backend/services/portfolio_scope.py`, `backend/services/integrations/*`.
Den weiteren Domains nicht blind gleiche `down_revision` geben; gemeinsame
Migrationverzweigungen linear beziehungsweise mit ausdrücklicher Alembic-
Merge-Revision integrieren. Die bereits vorhandenen Downgrade-/Originalguards
nicht entfernen. Beim Rollback des Pakets alle neuen Nachweise behalten;
ein älterer ausführbarer Code darf niemals kommentarlos gegen neuere
persistente Tabellen starten.

Prüfkommandos: `scripts/run_pro_matrix.py` mit `--backend memory|sql`,
`scripts/run_pro_native.py --mode workflow`, `scripts/run_connection_browser_qa.py`
mit dem expliziten lokalen Playwrightmodul; jeweils eigene Runtimes/
Wegwerf-Datenbanken. Ein Gesamt-Go verlangt den CI-Lauf auf dem exakten
endgültigen, integrierten Codehash sowie dokumentierte tatsächliche
Benutzer-/Restore-Abnahme. Keine laufende Anwenderinstallation verändern.
