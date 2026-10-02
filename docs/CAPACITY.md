# Große Datenbestände und einstellbare Betriebskapazität

Die Zahl gespeicherter Buchungen, Verträge, Belege und Nutzungsjahre ist nicht
durch eine Lizenz- oder Datensatzobergrenze beschränkt. Buchungsseiten verwenden
einen Cursor, Abfragen erfolgen in der Datenbank, CSV-Dateien werden aus einer
konsistenten Datenansicht portionsweise erzeugt. Eine Seitengröße begrenzt eine
Antwort und lässt sich durch weiteres Blättern fortsetzen.

Sicherungen benötigen endliche Ressourcenbudgets, damit beschädigte Archive
und unbeabsichtigt riesige Vorgänge den Rechner nicht lahmlegen. Diese Budgets
sind jetzt ausdrücklich einstellbar. `capacity.example.json` zeigt das Format;
die hohen Beispielwerte sind keine Zusage zur Leistung eines bestimmten Servers.
Die tatsächlichen Werte passend zu Speicherplatz, RAM und Zeitfenster wählen.

```powershell
python -m backend.recovery backup --offline --data-dir "D:\ImmoManager" --output "E:\Backups\immo.immobak" --capacity-file "D:\capacity.json"
python -m backend.recovery restore --archive "E:\Backups\immo.immobak" --destination "D:\ImmoManager-Recovery" --capacity-file "D:\capacity.json"
python scripts/private_server_backup.py backup --project immomanager --destination "E:\Backups\server.immobak" --env-file .env.server --capacity-file "D:\capacity.json"
python scripts/private_server_backup.py restore --project immomanager-recovery --source "E:\Backups\server.immobak" --env-output .env.server.recovery --capacity-file "D:\capacity.json"
```

`--timeout-seconds` überschreibt das Zeitfenster im Profil. Nicht angegebene
Werte behalten ihre dokumentierten Voreinstellungen. Profilversion 1 unterstützt
zwei Bereiche mit diesen Feldern:

| Bereich | Einstellbare Felder |
| --- | --- |
| `sqlite_recovery` | `total_bytes`, `file_bytes`, `files`, `compression_ratio`, `timeout_seconds`, `metadata_bytes`, `manifest_bytes`, `central_directory_bytes` |
| `private_server_backup` | `package_bytes`, `dump_bytes`, `tar_bytes`, `expanded_data_bytes`, `entries`, `metadata_bytes`, `small_bytes`, `command_output_bytes`, `timeout_seconds` |

Größen sind Bytes, Anzahlen positive ganze Zahlen, Zeiten positive endliche
Sekundenwerte. Doppelte, unbekannte oder ungültige Felder führen vor dem
Passwortdialog und vor Datenänderungen zu einem erklärten Fehler. Bei einem
überschrittenen Budget Ressourcen prüfen, Profil korrigieren und den Vorgang
erneut ausführen. Vorhandene Installationen und Sicherungsdateien werden nicht
überschrieben; eine abgebrochene Vorbereitung wird nicht als Erfolg ausgegeben.

Dateibytes und Datenbank-Dumps werden gestreamt. Das lokale SQLite-Archiv hält
seinen Dateikatalog und das Manifest im RAM; viele Millionen einzelne Anhänge
benötigen daher auch bei kleinen Dateien entsprechend Arbeitsspeicher. Für
größere Mehrbenutzerbestände ist das PostgreSQL-Serverprofil vorgesehen. Auch
dessen TAR-Pfadprüfung benötigt Metadaten pro Dateipfad. Kein Profil hebt die
Prüfung von Prüfsummen, Fremdschlüsseln, Authentifizierung, Pfadtraversierung,
Symlinks/Reparsepunkten oder widersprüchlichen Archivstrukturen auf.

Das geprüfte SQLite-Buchungsszenario mit 100.000 Zeilen verwendete für die
Seitenausgabe etwa 3,55 MiB und für den CSV-Export etwa 1,91 MiB zusätzliche
Python-Allokationen. Das ist ein Entwicklungsnachweis, keine Messung des
gesamten Prozesses und keine Garantie für jeden Filter oder Server.
