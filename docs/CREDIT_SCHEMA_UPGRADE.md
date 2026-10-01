# Ältere lokale Guthabenstruktur aktualisieren

Neue Installationen und die reguläre Alembic-Kette enthalten die Guthabenstruktur.
Bei älteren lokalen SQLite-Installationen, deren Tabellen mit create_all angelegt
wurden, lässt die alte Bankbuchungsprüfung keine Zuordnung zu negativen
Auszahlungsbuchungen zu. Die Anwendung meldet diesen Zustand vor der Buchung mit
einem Handlungshinweis. Der vorhandene Entwurf kann nach dem Upgrade erneut
bestätigt werden.

1. Anwendung, Hintergrunddienste und alle anderen Schreiber stoppen.
2. Eine vollständige Sicherung nach [RECOVERY.md](RECOVERY.md) erstellen und auf
   einem anderen Ziel prüfen. Konfiguration, Verschlüsselungsschlüssel und
   Dateien gehören dazu.
3. Für eine **unversionierte create_all-Datenbank** den folgenden Befehl mit den
   tatsächlichen lokalen Pfaden ausführen. Der Sicherungsname muss neu sein:

   ```powershell
   .venv\Scripts\python.exe -m backend.credit_schema_upgrade --database C:\ImmoManager\data\immomanager.db --backup-output C:\ImmoManager\backups\before-credit-2026-10-01.sqlite --offline --timeout-seconds 300
   ```

4. Anwendung starten, Guthabenübersicht öffnen und den Auszahlungsentwurf prüfen.
   Der Befehl erzeugt selbst zusätzlich eine private vollständige
   SQLite-Datenbankkopie vor jeder Schreibänderung. Diese Kopie enthält keine
   hochgeladenen Dateien oder Konfiguration und ersetzt die Vollsicherung nicht.

Der Befehl ändert nur die Bankzuordnungsprüfung und legt fehlende Guthabenjournale
an. Vorhandene Zeilen, Indizes und Trigger bleiben erhalten. Fremdschlüssel und
Datenbankintegrität werden vor und nach dem Upgrade geprüft. Ein tatsächlicher
Fehler nach dem Tabellenumbau rollt den Umbau zurück. Die zuvor fertiggestellte
Datenbankkopie bleibt für die Wiederherstellung erhalten. Ein anderer Schreiber
zwischen Sicherung und exklusiver Migration führt zum Abbruch. Bestehende
Sicherungen werden niemals überschrieben.

Bei großen Datenbanken darf das technische Laufzeitbudget über
`--timeout-seconds` erhöht werden. Es gibt keine zusätzliche Zeilen- oder
Gesamtgrößengrenze; ausreichender Plattenplatz für Kopie und Tabellenumbau bleibt
erforderlich. Abbrüche nennen den Wiederholungsweg und geben keine Rohdaten oder
Treibertexte aus.

**Versionierte Alembic-Datenbanken:** Der Befehl verweigert diese ausdrücklich,
damit die Versionshistorie nicht inkonsistent wird. Bei gestoppter Anwendung
die reguläre Migration `alembic upgrade head` mit der tatsächlichen
Installationskonfiguration verwenden. Die separate SQLite-Migrationsverbindung
arbeitet mit einer ausdrücklich begonnenen DDL-Transaktion. Die n1-Migration
verweigert eine Verbindung mit eingeschalteter Fremdschlüsselerzwingung vor dem
Tabellenumbau; sie prüft alle Fremdschlüssel danach. Bei PostgreSQL läuft die
reguläre Migration ohne SQLite-Tabellenumbau.
