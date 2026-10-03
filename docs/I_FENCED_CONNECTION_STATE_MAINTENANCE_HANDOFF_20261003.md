# I/L: tatsächliche abgesicherte Integrationswartung

Root-Plan `9dbd542`, Quelle `58aaf3e`, Profilkomposition `09c70fa`,
gezielte Erwartungskorrektur `d2c2cbd`. Keine Schemaänderung, Portalaktion oder
Umstellung einer privaten Installation. Die globale verschlüsselte Runtimefactory
ist ein anschließendes eigenes Paket; dieses Dokument bestätigt den expliziten
SQLite-Wartungsweg und keine gesamte I-/L-/A–L-Freigabe.

## Verfahren

`python -m backend.integration_state_upgrade convert --data-dir <installation>
--output <neue-vollsicherung.immobak> --offline` liest die Passphrase zweimal
interaktiv. Die tatsächliche Installationssperre wird vor Konfigurationsauswahl
erworben. `BEGIN IMMEDIATE` schließt unabhängige SQLite-Schreiber aus. Die Auswahl
verwendet gespeicherte explizite Konfiguration, Größenprofil und eine gemeinsame
Deadline; keine Schlüsselannahme aus einer anderen Installation.

Vor Umstellung entstehen ein echtes verschlüsseltes Vollarchiv und dessen echte
isolierte Wiederherstellungsprobe. Das wiederhergestellte Original muss denselben
Dateihash besitzen. Der geschützte Operationsnachweis enthält Identitäten und
Hashes, keine Schlüssel, Passwörter oder Providerkonfiguration. Die Datei wird
unter dem vorhandenen unabhängigen Dateilock mit SHA-Vergleich atomar ersetzt.
Der Nachweis des Kandidaten steht bereits vor dem Ersetzen fest.

`list --data-dir <installation>` findet die Operationskennung auch nach verlorener
Erfolgsantwort. Positive Seitengröße, opaker UUID-Fortsetzungspunkt und begrenzte
Materialisierung vermeiden abgeschnittene Operationshistorien. Ein Abbruch vor
dem ersten Nachweis bleibt als `initialization_incomplete` sichtbar.
`status --data-dir <installation> --operation-id <uuid>` unterscheidet tatsächliche
Originalbytes, den bestätigten verschlüsselten Kandidaten und geänderte Daten.

`rollback --data-dir <installation> --operation-id <uuid> --offline` verlangt erneut
die Archivpassphrase und eine tatsächliche vollständige Wiederherstellungsprobe.
Nur die Integrationsdatei erhält ihre exakten ursprünglichen Bytes zurück.
Spätere Geschäftsdaten bleiben bestehen. Geänderte Zugänge, Konfiguration,
Auswahl oder Archiv werden abgewiesen. Eine bereits zurückgeführte Originaldatei
wird nach der Probe nochmals unter Dateilock geprüft, bevor Erfolg gemeldet wird.

Der frühere ungesicherte `scripts/integration_state_maintenance.py
migrate-plaintext`-Befehl verweist ausdrücklich auf diesen Wartungsweg. Sein
`verify`-Befehl bleibt unverändert lesend. Lowlevel-Konvertierung verlangt den
tatsächlichen erwarteten SHA; normale Store-Schreibzugriffe bleiben kompatibel.

## Tatsächliche Prüfungen

1. Quelle `58aaf3e`: vollständige native Umstellung/Rückweg mit späterer echter
   Geschäftsdatenänderung sowie tatsächlicher CLI-Rundlauf: **2 PASS / 38,06 s**,
   Prozessrahmen 120 s. Dies sind spätere Gatefälle erneut, keine zusätzlichen
   unterschiedlichen Tests.
2. Quelle `09c70fa`: neue Wartungsdatei mit 29 Fällen plus vier gezielt geänderte
   Legacy-/CAS-Fälle: **32 PASS, 1 FAIL / 140,09 s**, harter Rahmen 200 s.
   Der Fehlfall erwartete einen rohen OSError, während der bestehende Store
   korrekt `ConfigStoreError(state_io_failed)` ausgab. Die ursprünglichen Bytes
   wurden nicht ersetzt; die getestete Erwartung wurde auf die tatsächliche
   sichere Fehlerklasse korrigiert. Keine Produktprüfung wurde gelockert.
3. Exakt dieser eine Fall auf `d2c2cbd`: **1 PASS / 8,64 s**, Prozessrahmen 60 s.
   Dazu kam lediglich die konkrete nicht vertrauliche CLI-Handlungsanweisung für
   den bereits vorhandenen I/O-Fehlercode. Keine breite Wiederholung.

Damit sind **33 unterschiedliche positive Fälle** zusammengesetzt belegt, keine
Skips; kein einzelner vollständig grüner 33-Fälle-Lauf wird behauptet. Alle
genannten Prozesse und ihre unabhängigen Schreiber wurden normal geschlossen.
Gemeinsamer isolierter Projektinterpreter, temporäre vollständige SQLitebestände,
ausschließlich synthetische Schlüssel und Daten, keine privaten Datenbankpfade.

Die Fälle beweisen tatsächliche Prozessbeendigung vor/nach Dateiersetzung und
Rückweg, Lebenszeitsperre vor Auswahl, intervenierende Dateischreiber, geänderte
verschlüsselte Payload, falsche Passphrase/verändertes Archiv, Auswahländerung
bei Parsing und unmittelbar vor Veröffentlichung, Noop-Rennen nach Probe,
abgebrochene initiale Operationsliste sowie begrenzte Lockwartezeit nach echter
langer Probe. Ein unabhängiger SQLite-Schreiber blockiert vor Archivarbeit;
vier weitere echte Schreibversuche vor Sicherung, vor/nach Probe und direkt vor
Veröffentlichung wurden abgewehrt. Nach Abschluss konnte derselbe native
Schreibweg die Geschäftsdaten ändern.

CLI-Tests verwenden den tatsächlichen Parser, Wartungsservice, Backup, Probe,
Dateien und Ausgaben. Nur die Windows-Konsolen-Passworteingabe wird im Testchild
auf dessen stdin gelegt. Passwörter stehen weder in argv noch in stdout/stderr.
Positive größere Konfigurationsprofile erreichen den wirklichen Planner und
die erneute Bindungsprüfung jenseits von 16 MiB; kleine Profile verweigern vor
Parsing, Archiv und Zustandsschreiben. Ruff und Mypy der fünf Produktdateien grün.

## Präzise verbleibende Komposition

Globale Runtimefactory, PostgreSQL-/Docker-Appdaten, vollständige Betriebssicherung
und produktive Auslieferung folgen separat. Das reine Konfigurationsleserpaket
besitzt zusätzlich seinen eigenen Nachweis in
[L_BOUNDED_RECOVERY_PLANNER_HANDOFF_20261003.md](L_BOUNDED_RECOVERY_PLANNER_HANDOFF_20261003.md).
Die Wartungsprüfung ist keine Messung von einer Million Geschäftszeilen, keine
20-Jahres-Freigabe und kein externer TEHA-/WISO-Nachweis.
