# Vollständige lokale Sicherung und Wiederherstellung

Die vollständige Sicherung umfasst eine lokale SQLite-Installation: sämtliche
Tabellen einschließlich Benutzer, Passwort-Hashes, Zwei-Faktor-Zustand,
Installationsmarker, Belegen, Gegenbelegen und Abrechnungen, den gewählten
Upload-Baum, Einstellungen einschließlich JWT-Schlüssel und Integrationszustand.
Programmcode und externe HTTP-/S3-Dateien sind separat zu erhalten. Der Befehl
meldet die Anzahl externer Dateiverweise, ohne deren URLs auszugeben.

## Sicherung erstellen

Anwendung und Hintergrundschreiber stoppen. Im Projektordner ausführen:

```powershell
.\.venv\Scripts\python.exe -m backend.recovery backup --offline --data-dir "$env:LOCALAPPDATA\ImmoManagerPro" --output "D:\Private Backups\ImmoManager.immobak"
```

Die Passphrase wird zweimal interaktiv abgefragt und muss mindestens zwölf
Zeichen haben. Sie erscheint nicht in Kommandozeilenargumenten. Das Archiv ist
mit AES-256-GCM authentifiziert verschlüsselt; die Schlüsselableitung verwendet
PBKDF2-HMAC-SHA256 mit zufälligem Salz und 600.000 Iterationen. Eine vorhandene
Archivdatei wird nicht überschrieben.

Der ausdrücklich gewählte Datenordner und dessen `.env` bestimmen die Quelle.
Bei wiederhergestellten Installationen hat `configuration.json` Vorrang. Fremde
Terminalvariablen werden dabei ignoriert. Ohne gespeicherten JWT-Schlüssel wird
die Sicherung abgelehnt; dieser Schlüssel muss mit der ursprünglichen Laufzeit
übereinstimmen. Schlüsselabhängige IBANs werden vor Veröffentlichung geprüft.

## Alte Upload-Speicherorte

Ältere Versionen speicherten Dateien teilweise im Arbeitsverzeichnis unter
`uploads`. Der aktuelle Server verschiebt oder löscht diese Dateien nicht.
Wähle den tatsächlich verwendeten Baum ausdrücklich:

```powershell
.\.venv\Scripts\python.exe -m backend.recovery backup --offline --data-dir "C:\ImmoManager Daten" --uploads "C:\Alter Programmordner\uploads" --output "D:\Private Backups\ImmoManager.immobak"
```

`--database` und `--integrations` wählen bei Bedarf die tatsächliche absolute
SQLite-Datei bzw. Integrationsdatei. Eine ausdrücklich gewählte fehlende Datei
führt zum Fehler. Es wird genau ein Upload-Baum gesichert. Die Prüfung verlangt,
dass sämtliche lokalen Dokument-/Foto-/Belegverweise darin enthalten sind.
Gemischte oder fehlende Speicherorte verursachen einen Fehler und müssen vor
einer vollständigen Sicherung nachvollziehbar konsolidiert werden. Die alten
Ordner bis zur erfolgreichen Wiederherstellungsprüfung aufbewahren.

## In einen neuen Ordner wiederherstellen

Die kompatible Programmversion bereithalten, die Anwendung stoppen und einen
noch nicht vorhandenen Zielordner wählen:

```powershell
.\.venv\Scripts\python.exe -m backend.recovery restore --archive "D:\Private Backups\ImmoManager.immobak" --destination "D:\Wiederhergestellter ImmoManager"
.\.venv\Scripts\python.exe -m backend.recovery run --data-dir "D:\Wiederhergestellter ImmoManager" --port 8000
```

Die Wiederherstellung benötigt keinen Zugriff auf den früheren Rechner oder
Datenordner. Sie authentifiziert das Archiv vor dem Entpacken und prüft Pfade,
Dateien, Prüfsummen, Größen, Datenbankschema und Fremdschlüssel. Absolute lokale
Dateiverweise werden ausschließlich in der vorbereiteten Kopie umgeschrieben;
Trigger und sämtliche übrigen Geschäftsdaten bleiben erhalten. Erst danach
wird der neue Ordner freigegeben. Falsche Passphrase, beschädigtes Archiv,
fehlende Anhänge, unlesbare Verzeichnisse oder Fehler bei der Veröffentlichung
erzeugen keine teilweise wiederhergestellte Installation.

Der Recovery-Starter liest die exakte JSON-Konfiguration in einem frischen
Prozess. Prüfe anschließend Anmeldung, gegebenenfalls Zwei-Faktor-Anmeldung,
Kontodaten, Zahlungshistorie, Abrechnungen und Dokument-/Fotodownloads. Externe
Plugin-Verzeichnisse sind beim ersten Recovery-Start deaktiviert; die
ursprünglichen Einstellungen bleiben in `original-configuration.json` und
gegebenenfalls `original-runtime.env` erhalten. Plugin-Code separat prüfen und
danach bewusst wieder konfigurieren.

## Umfang und Betriebsgrenzen

Der laufende Server bietet JSON-Export/Import eines definierten Geschäftsdaten-
Teilsatzes. Er sichert keine Benutzer, Upload-Bytes oder komplette Abrechnung.
Der Import läuft vollständig atomar und lehnt nicht unterstützte Quellen ab.
Der Windows-Scheduler erstellt konsistente, unverschlüsselte Datenbank-Snapshots
mit allen Tabellen; externe Konfiguration und Anhänge fehlen darin. Für eine
vollständige lokale Wiederherstellung das verschlüsselte Archiv verwenden.

Standardgrenzen: 8 GiB Gesamtumfang, 4 GiB je Datei, 100.000 Einträge, 16 MiB je
Runtime-Metadatei, 64 MiB Manifest, 32 MiB ZIP-Verzeichnis, 48 Pfad-/JSON-Ebenen
und 300 Sekunden für den Vorgang. ZIP-Verzeichnis und tatsächliche Eintragszahl
werden vor dem regulären ZIP-Parser begrenzt. SQLite-Sicherung umfasst bestätigte
WAL-Änderungen. Änderungen durch andere Schreiber während der Sicherung führen
zum Abbruch; der Offline-Betrieb ist Voraussetzung.

Temporäre Klartextdateien liegen während der Vorbereitung im privaten
Elternverzeichnis des gewählten Ziels. Dieses Verzeichnis benötigt ausreichend
freien Speicher und passende Windows-Zugriffsrechte. Erfolgs-/Fehlerpfade
entfernen ihre eigenen temporären Dateien; ein Stromausfall kann eine spätere
manuelle Prüfung von `.immo-backup-*`/`.immo-restore-*` nötig machen. Archive nur
auf Dateisystemen mit exklusiver Hardlink-Veröffentlichung erzeugen, etwa NTFS.
Windows und Linux werden unterstützt; PostgreSQL, S3-Objektbytes und externe
Plugin-Binaries gehören nicht zum lokalen Recovery-Paket.
