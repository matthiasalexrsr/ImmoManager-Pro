# Lokales Offline-Upgrade für Rechnungszahlungsbelege

Ältere eigenständige SQLite-Installationen verwenden teilweise `create_all()`
ohne Alembic-Version. Der Start ergänzt dort lesbare Rechnungs-/Zahlungsspalten,
ersetzt aber absichtlich nicht im laufenden Betrieb den alten Zwei-Ziel-CHECK.
Ein Rechnungsbeleg wird dann mit einem verständlichen Upgradehinweis abgelehnt;
die Bankbuchung und der Entwurf bleiben erhalten.

Für diese **unversionierten lokalen SQLite-Datenbanken** gibt es nun einen
ausdrücklichen Wartungsweg. Keine Alembic-Version wird geraten oder gestempelt.
Eine bereits versionierte Datenbank wird vor Sicherung und DDL abgewiesen und
verwendet weiterhin den regulären Offline-Alembic-Migrationsweg.

1. Anwendung, Dienste und sämtliche anderen Datenbankschreiber stoppen.
2. Zusätzlich eine geprüfte vollständige Installationssicherung behalten:
   Konfiguration, Verschlüsselungsschlüssel und Originaldateien gehören dazu.
   Die unten erzeugte PREVIOUS-Datei enthält die vollständige SQLite-Datenbank,
   einschließlich privater verschlüsselter Entwürfe und SQL-Anlagejournale;
   sie ist allein **kein vollständiges Wiederherstellungsarchiv** für externe
   Uploads oder Schlüssel.
3. Den vorhandenen lokalen Datenbankpfad und einen **neuen** Sicherungspfad
   angeben. Beispiel aus dem Projektverzeichnis:

   ```powershell
   .venv\Scripts\python.exe -m backend.invoice_schema_upgrade --database C:\ImmoManager\data\immomanager.db --backup-output C:\ImmoManager\backups\invoice-PREVIOUS-2026-10-02.sqlite --offline --timeout-seconds 300
   ```

4. Nur nach Erfolg die Anwendung wieder starten. Anschließend einen ausgewählten
   Rechnungsbeleg ausdrücklich prüfen und erfassen; der Wartungsbefehl erzeugt
   selbst keine Zahlung und keinen Stornobeleg.

Das Werkzeug setzt vor den ersten Sicherungsbytes einen privaten Dateizugriff.
Es überschreibt keine vorhandene Sicherung und lehnt Verknüpfungen ab. Die
SQLite-Backup-API übernimmt ein konsistentes vollständiges Datenbankbild,
einschließlich bereits bestätigter WAL-Transaktionen. Danach prüft das Werkzeug
Dateiidentität und `data_version` und nimmt für DDL eine tatsächliche
`BEGIN EXCLUSIVE`-Schreibsperre.

Die bekannten Zahlungs-CHECKs werden auf einen Rechnungsbeleg als drittes Ziel
und den Betrag einer negativen Bankbuchung als Budget erweitert. Die
nachweisbare historische Variante mit additiv angelegtem `allocated_amount`,
bekanntem `ck_bookings_amount_nonzero`, jedoch ohne `ck_bookings_allocation`,
wird ebenfalls unterstützt. Vor jeglicher DDL-/Triggeränderung werden die
vorhandenen Beträge und Zuordnungen zeilenweise auf numerische, endliche Werte
und `0 <= allocated_amount <= abs(amount)` geprüft. Es werden keine Werte
gerundet, repariert oder zurückgesetzt. Bei ungültigem Budget nennt die CLI
die notwendige Beleg-/Zuordnungsprüfung und bewahrt den vollständigen Altstand.
Ein fremder gleichnamiger CHECK oder eine unbekannte Nonzero-Regel wird nicht
ersetzt; alle weiteren ursprünglichen CHECKs bleiben erhalten.

Die Rechnungsreferenz bleibt ein echter FK mit `ON DELETE RESTRICT`, auch wenn sie
zuvor über eine additive inline-REFERENCES-Spalte entstanden war. Vorhandene
explizite historische Bezahlstände werden als Altstand erhalten; neue Belege
werden dadurch nicht erfunden.

Sämtliche ursprünglichen Trigger werden innerhalb derselben Offline-Transaktion
kontrolliert gehalten und exakt wiederhergestellt. So löst ein historisches
Spalten-Backfill keine unabhängigen Geschäftsmutationen aus. Vor dem Commit
werden die ursprünglichen Spaltenwerte aller vorhandenen Tabellen zeilenweise
mit typisierten Hashes verglichen, einschließlich Ciphertext, SQL-Dateibytes,
Zahlungen und Stornos. Originale Spaltendefinitionen, PKs, FKs, Indizes, weitere
CHECKs, Views und Trigger müssen erhalten sein; Integritäts- und FK-Prüfungen
müssen bestehen. Die Vergleichsprüfung liest eine Zeile nach der anderen und
hat keine Bestands-, Jahres- oder Gesamtzeilengrenze.

Bei Zeitbudget, konkurrierendem Schreiber, unerkanntem Schema, DDL- oder
Bestandsprüfungsfehler werden Änderungen zurückgerollt. Eine bereits vollständig
erstellte PREVIOUS-Datei bleibt bestehen. Die CLI nennt eine konkrete
Wiederholungs-/Prüfaktion und gibt Exitcode 2 aus, ohne private SQL-/Pfaddaten
aus einem Treiberfehler auszugeben. Nicht auf eine vermutete Alembic-Version
stempeln. Für einen neuen Versuch immer einen neuen Sicherungsnamen verwenden;
bei einer unbekannten Struktur das konkrete Schema prüfen lassen.

`--timeout-seconds` ist ein anpassbares technisches Laufzeitbudget. Bei größeren
Beständen kann es erhöht werden. Für Sicherung und SQLite-Tabellenneubau ist
zusätzlicher freier Speicher erforderlich. Ein zweiter erfolgreicher Lauf auf
dem bereits aktualisierten Bestand ist möglich und lässt vorhandene Belege,
Stornos und Originaltrigger unverändert.

Die synthetischen Tests in `test_invoice_schema_upgrade.py` erzeugen eine
unversionierte `create_all()`-Installation mit den bekannten früheren
Zahlungsregeln. Sie prüfen beide Altzustände (mit/ohne additive Lesespalten),
echte negative Rechnungszahlung und Storno auf den Cent, private Entwürfe,
unveränderte eingefrorene Vertragsanlagen, unabhängige Trigger, wiederholtes
Upgrade, eine echte nachträgliche Fremdmutation und injiziertes Scheitern nach
tatsächlichem Payments-Tabellenneubau. Keine Benutzerdatenbank oder Preview wird
von diesen Prüfungen gelesen oder geändert.

Der Followup prüft zusätzlich die tatsächlich per `ALTER TABLE` erzeugte
Zuordnungsspalte ohne Budget-CHECK, mit und ohne additive Rechnungslesespalten,
erhaltene fremde CHECKs/Trigger, negative Rechnungszahlung/Storno auf den Cent,
Rollback nach echtem Tabellenneubau, ungültige negative/überhöhte/nichtendliche/
nichtnumerische Altzähler und unbekannte fremde CHECKs. Gemeinsam mit den
bestehenden Credit-Offline- und Bank-Matching-Schema/Recoveryfällen bestanden
29/29 tatsächliche SQLite-/SQL-Gates; Ruff und Mypy auf dem Helper ebenfalls.
Ein zusätzlicher tatsächlicher CLI-Fall prüft Exitcode 2, verständliche
Budget-Prüfanweisung, unveränderte Quelle/PREVIOUS und fehlende private
Zeilen-/Pfadinhalte in der Fehlermeldung.

Eine weitere nachgewiesene SQLite-Variante enthält absteigende zusammengesetzte
Buchungsindizes sowie die früher per `ALTER TABLE` ergänzte `booking_id`-Referenz
mit `ON DELETE RESTRICT`. SQLAlchemy kann beim Reflektieren solcher Tabellen die
Indexsortierung und die inline ergänzte FK-Aktion verlieren. Die n1-/w1-Neubauten
übernehmen deshalb die tatsächlichen FK-Aktionen aus SQLite-PRAGMA-Metadaten und
stellen explizite Indexdefinitionen aus ihrem ursprünglichen `CREATE INDEX` wieder
her. Dadurch bleiben auch Collations, Ausdrucksschlüssel, partielle Bedingungen
und Eindeutigkeit erhalten. Der reguläre PostgreSQL-Migrationspfad bleibt dabei
unverändert.

Die ursprüngliche strenge Erhaltungsprüfung bleibt bestehen. Zusätzliche
synthetische Fälle prüfen genau diese historische Form mit/ohne Budget-CHECK,
vollständige vorherige Datenbank, alle ursprünglichen Zeilen, Dateibytes und
Trigger sowie echte Rechnungszahlung und Storno. Ein regulärer versionierter
n1→w1-Alembic-Lauf prüft dieselben FK-/Indexmerkmale unabhängig vom Offline-CLI.
