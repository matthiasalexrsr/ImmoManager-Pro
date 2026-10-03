# L: zentrale Startwege mit dem vollständigen Backup verbinden

Plan vor Änderungen an den zentralen Quellen. Basis `838089a`; die fertige
Backupreihe und ihr präziser Handoff sind integriert. Die tatsächlichen
Startup-/Recoverydateien wurden gelesen. Keine private Installation wird für
diese Komposition gestartet, gestoppt, gesichert oder migriert.

## Unterstützte Lebensdauer

1. `backend.app` nimmt die reine Importfence vor Auth-, Settings-, Dependency-,
   Router-, Plugin- und Loggingimporten. Direkter SQLite-ASGI hält die native
   Lease bis Prozessende; er erhält keinen geratenen Steuerkanal.
2. `backend.dependencies` nimmt denselben früh wiederverwendbaren Schutz vor
   SQL-Initialisierung, auch bei direktem Import ohne den App-Einstieg.
3. Die bestehende async Lebensspanne wird unter die Konfigurationsprüfung der
   bereits gehaltenen Fence gestellt. Scheduler-/Plugin-/Authworker beenden
   ihre Arbeit vollständig vor Rückkehr zum kontrollierten Launcher.
4. `backend.recovery run` nimmt ManagedRuntime vor dem Laden wiederhergestellter
   Umgebung, bindet die tatsächlich geladene Konfiguration und verwendet den
   kontrollierten Server. Source-/Exe-Wurzel, Datenordner und Port sind explizit.
5. Der ausdrückliche manuelle SQLite-Vollbackupbefehl nimmt die Installations-
   lease vor Plan-/Schlüssel-/SQLoperationen und einen echten SQLite-Writerslot
   für die Archivphase. Ein belegter Start verhindert den Offlinebefehl.
6. PostgreSQL startet unverändert über den gesonderten Containerlebenszyklus;
   dort greift die hier integrierte SQLitefence nicht.

Vorhandene `--offline`-Angabe allein darf nicht als Prozessnachweis ausgegeben
werden. Neue automatische Sicherung wird erst nach eigener Laufzeitaufnahme
und gemeinsamer Freigabe aktiviert. Die ältere Vorschau bleibt unberührt.

## Native Prüfungen

- Tatsächlicher central app-/dependencies-Import unter gehaltenem Kernellease
  scheitert vor Settings, Datenbank, Log und Worker. Kein reparierender Startup.
- Zwei unabhängige Prozesse können denselben SQLite-Datenordner nicht öffnen;
  das gilt auch zwischen direktem ASGI und kontrolliertem Launcher.
- Bestehender strikter Produktionsstart funktioniert mit unverändertem Schema
  und nativ verweigertem CREATE/ALTER/DROP.
- Tatsächliche wiederhergestellte vollständige Installation startet über
  RecoveryRun; der Controller erkennt dieselbe Instanz, kann sie ordentlich
  stoppen und bestätigt Prozessende, Leasefreigabe und unveränderte Bytes.
- Der vorhandene echte Runner-/Crash-/Zweitkopie-/Restoretest wird auf Root
  erneut komponiert, ohne weitere parallele schwere Tests auf dem Rechner.
- Bewährte Formular-/Housing-/Billing-UI wird auf dem gemeinsamen Stand geprüft.

Ein fehlender Dockerdaemon bleibt eine ausdrücklich offene reale Betriebs-
abnahme; Vertragsmocks ersetzen ihn nicht. Große Archiv-/Finanzbestände,
kompletter A–L-Gesamtlauf und kontrollierte Auslieferung bleiben eigene Gates.
