# Migration, Sicherung und Rückfall

Anleitung zum integrierten Windows-Testpaket, 26.10.2026. Der zugehörige Laufzeitquellstand steht in `PAKET-INHALT.json`. Der Ergebnisbericht und die SHA-256-Liste bezeichnen den tatsächlich geprüften Auslieferungsstand.

## Programm und Daten getrennt halten

Das vollständige ZIP in ein neues Programmverzeichnis entpacken. Die EXE benötigt den mitgelieferten Ordner `_internal`, einschließlich Java-Laufzeit, Validatoren, Regeln, Lizenztexten und entsprechenden Quellarchiven. Einzelnes Kopieren der EXE ist keine Installation.

Für einen ersten lokalen Test `Start-Test.cmd` verwenden. Er startet `Start-Test.ps1` mit einer bereinigten Kindprozessumgebung und festgelegten lokalen Testpfaden. Geerbte Datenbank-, Datei- und Geheimniskonfigurationen werden nicht übernommen. Der Datenordner `Testdaten` liegt neben dem Starter. Eine `.env` neben der EXE wird von diesem Teststarter zurückgewiesen. Bestehende Einstellungen im ausdrücklich lokalen Testdatenordner bleiben für spätere Teststarts erhalten. Eine bestehende Kundeninstallation wird über ihren ausdrücklich gewählten Datenordner gestartet. Keine vorgegebenen Zugangsdaten übernehmen; in einer leeren Installation das eigene Eigentümerkonto anlegen.

Die folgenden PowerShell-Beispiele verwenden Platzhalterpfade, die vor Ausführung an die eigene Installation anzupassen sind:

```powershell
$ImmoExe = 'C:\ImmoManager\Integration\ImmoManager-Pro\ImmoManager-Pro.exe'
$ImmoData = 'D:\ImmoManager\Kunde-A'
```

`upgrade` beziehungsweise `ops` muss unmittelbar nach dem EXE-Pfad stehen. `--data-dir` folgt dahinter; der Launcher entfernt diese Option, bevor er den Fachbefehl ausführt. Bei jedem Betriebsbefehl denselben beabsichtigten Datenordner angeben.

Konfigurationsvorrang beachten: Bereits gesetzte Prozess-Umgebungsvariablen haben Vorrang. Danach wird eine `.env` neben der EXE, anschließend die `.env` des Datenordners gelesen, jeweils ohne vorhandene Werte zu überschreiben. Ein bereits gesetztes `DATABASE_URL`, `UPLOADS_DIR`, `BACKUP_DIR` oder eine externe Speicher-/Schlüsselkonfiguration kann deshalb auf einen anderen Bestand zeigen. Vor der Aktualisierung Zielpfade und Datenbankverbindung prüfen, ohne Geheimnisse in Berichte oder Konsolenausgaben zu kopieren. `--data-dir` allein ist bei abweichenden Umgebungswerten keine Isolationsgarantie.

## Vor der Aktualisierung

1. Die bisherige Programmversion mit allen Bestandteilen aufbewahren. Den Datenordner, die Datenbankart und separat konfigurierte Speicherorte dokumentieren.
2. Alle Nutzer abmelden und Schreibzugriffe beenden. Die alte Instanz einschließlich ihrer Hintergrundjobs stoppen. Das Upgrade nicht neben einer weiterlaufenden Instanz ausführen.
3. Eine Vollsicherung erstellen und prüfen. Sie muss Datenbank, Originaldateien, benötigte Schlüssel und Betriebskonfiguration enthalten. Ein Kundenexport ersetzt diese Sicherung nicht.
4. Das aktuelle Datenschutzjournal gesondert exportieren und geschützt aufbewahren. Spätere Lösch- und Sperrentscheidungen müssen auch dann nachgezogen werden, wenn ein älterer Datenstand wiederhergestellt wird.
5. Sicherung und alte Programmversion außerhalb des zu aktualisierenden Programmverzeichnisses aufbewahren. Den geplanten Rückfallzeitpunkt und die Behandlung späterer Geschäftsvorfälle festlegen.

Für eine unabhängig wiederherstellbare Betriebskonfiguration `BACKUP_PASSPHRASE` vor der Sicherung über den geschützten Konfigurationsweg setzen und getrennt von der Sicherung aufbewahren. Eine bloß vorhandene ZIP-Datei oder `archive_verified` genügt nicht als Nachweis der wiederherstellbaren Schlüssel und Laufzeitkonfiguration.

## Upgrade durchführen

```powershell
& $ImmoExe upgrade --check --data-dir $ImmoData
```

Rückgabecode `0` bedeutet, dass der Prüfbefehl keinen ausstehenden Upgradebedarf meldet. `5` bezeichnet einen nötigen Upgrade-Schritt. Die Textausgabe zusätzlich auf den erkannten Datenbankzustand prüfen. Anschließend:

```powershell
& $ImmoExe upgrade --data-dir $ImmoData
```

Vor der Migration eines älteren Bestands erstellt und prüft dieser Weg eine Vollsicherung. Scheitert sie, wird das Schema nicht verändert. Den Schalter `--no-backup` für die reguläre Kundenaktualisierung nicht verwenden. Fehlermeldungen durch manuelles Setzen der Schema-Version zu umgehen, ist kein zulässiger Wiederanlauf.

Die Erweiterung legt zusätzliche Fachtabellen an. Die Historienkennung wird für externe Akteure verlustfrei verbreitert; Datenschutzentscheidungen erhalten zusätzlich Hashes gesperrter Dateiverweise. Erwarteter Schema-Head dieses Quellstands: `f8a0124d6e9b`.

| Code | Bedeutung | Nächster Schritt |
| --- | --- | --- |
| 0 | Upgrade erfolgreich oder kein Upgrade erforderlich | Erkannte Revision und Datenordner prüfen; Anwendung starten. |
| 2 | Vorab-Sicherung fehlgeschlagen | Speicher-/Sicherungsproblem beheben; Schema blieb unverändert. |
| 3 | Datenbankzugriff oder Upgrade fehlgeschlagen | Ausgabe prüfen; vorhandene Vorab-Sicherung erhalten und kontrolliert wiederherstellen. |
| 4 | Datenbank neuer als das Programm | Passende neuere Programmversion verwenden. |
| 5 | Nur bei `--check`: Upgrade erforderlich | Den regulären Upgradebefehl ausführen. |

```powershell
& $ImmoExe --data-dir $ImmoData --host 127.0.0.1 --port 18765 --no-browser
```

Nach erfolgreichem Start interne Anmeldung und Rollen, Originalbeleg-Download, Rechnungseingang, Arbeitscockpit, Importvorschau und einen neuen Kundenexport prüfen. Einladungen und öffentliche Portalzugriffe erst nach Prüfung der tatsächlichen Betriebsadresse freigeben.

## Vollsicherung und Wiederherstellungsprobe

```powershell
& $ImmoExe ops backup --data-dir $ImmoData
```

Den im JSON-Ergebnis ausgewiesenen Archivnamen und das tatsächliche Sicherungsverzeichnis verwenden. Bei Standardkonfiguration liegen die Vollsicherungen unter `backups\full` im Datenordner; eine angepasste Konfiguration kann abweichen.

```powershell
$ImmoArchiv = 'D:\ImmoManager\Kunde-A\backups\full\ARCHIVNAME.zip'
& $ImmoExe ops verify $ImmoArchiv --data-dir $ImmoData
& $ImmoExe ops probe $ImmoArchiv --data-dir $ImmoData
```

`verify` prüft Manifest und Prüfsummen. `probe` führt eine isolierte Wiederherstellungsprobe aus. Das Ergebnis muss für den geplanten Betrieb bewertet werden: `data_verified` bestätigt die technischen Daten-/Anhangsprüfungen, `archive_only` ist ein unvollständiger Wiederherstellungsnachweis. Diese Zustände geben Portal, Suche oder KI nicht frei. Bei geschützter Sicherung kann `probe` zusätzlich `--passphrase-env IMMO_RESTORE_PASSPHRASE` erhalten; die benannte Umgebungsvariable ist vorher sicher zu befüllen. Den geheimen Wert nicht als Befehlsargument eintragen.

## In ein neues Verzeichnis wiederherstellen

Die Quellinstanz stoppen. Ein noch nicht vorhandenes oder leeres Ziel verwenden:

```powershell
$ImmoRestoreData = 'D:\ImmoManager\Wiederherstellung-Kunde-A'
& $ImmoExe ops restore $ImmoArchiv --target $ImmoRestoreData --data-dir $ImmoData --passphrase-env IMMO_RESTORE_PASSPHRASE
```

Der Befehl überschreibt kein befülltes Zielverzeichnis. Er prüft das Archiv und geschützte Verbindungen, schreibt die wiederhergestellten Dateien zunächst in einen gesonderten Arbeitsbereich und publiziert das Ergebnis anschließend als Zielverzeichnis. Die gesicherten Originalpfade werden nicht blind als neue SQLite-/Uploadpfade verwendet. Die ursprüngliche Konfiguration bleibt zur Prüfung unter `.env.from-backup` beziehungsweise `runtime.from-backup.json` erhalten.

Bei PostgreSQL zusätzlich eine ausdrücklich für die Wiederherstellung bestimmte leere Zieldatenbank über `--pg-target-url` angeben. Ohne diesen Parameter wird der Dump als `postgres.dump` bereitgestellt; er ist damit noch nicht in eine Zieldatenbank eingespielt. Verbindung, Rechte, `pg_dump`/`pg_restore` und Passwortschutz auf der tatsächlichen Zielumgebung gesondert prüfen. Die hier protokollierten Windows-/PostgreSQL-Prüfungen ersetzen keine Hostingabnahme.

Danach ausschließlich die neue Zielzuordnung verwenden:

```powershell
& $ImmoExe upgrade --data-dir $ImmoRestoreData
& $ImmoExe --data-dir $ImmoRestoreData --host 127.0.0.1 --port 18765 --no-browser
```

## Datenschutzabgleich vor Zugriffsfreigabe

Jede Wiederherstellung erzeugt eine neue Umgebungskennung. Portalzugriffe, Suche, KI und die geschützten allgemeinen Dateizugriffe bleiben bis zum Abgleich gesperrt. Ein erfolgreiches technisches Restore-Ergebnis hebt diese Sperre nicht auf.

1. Mit einem berechtigten internen Konto Einstellungen → Datenschutz öffnen.
2. Das jüngste gesondert aufbewahrte Datenschutzjournal importieren und mit dem wiederhergestellten Bestand abgleichen.
3. Wiederaufgetauchte bereits gelöschte oder gesperrte Daten sowie fehlende Nachweise ausdrücklich bearbeiten. Ein Fristablauf hebt eine Aufbewahrungssperre nicht auf.
4. Die Wiederherstellungsprüfung mit Begründung erst bestätigen, wenn die aktuellen Entscheidungen berücksichtigt sind.
5. Externe Identitäten und Vertrags-/Eigentumszuordnungen einzeln prüfen. Alte Sitzungen und Einladungen werden nicht als gültige Zugänge wiederhergestellt; Dokumente benötigen weiterhin eine ausdrückliche Veröffentlichung der konkreten Version.

Die Anwendung behauptet keine physische Löschung sämtlicher Archiv- und Sicherungskopien. Bei Löschvorgängen werden Datensatz/Suchindex und bekannte direkte Datei-/OCR-Verweise berücksichtigt; aufbewahrungspflichtige Originale und vorhandene Sicherungskopien bleiben im dokumentierten Vorgang zu beurteilen.

## Rückfall auf den bisherigen Programmstand

Die neue Instanz beenden und deren letzten Zustand gesondert sichern. Die geprüfte Sicherung **vor** dem Upgrade mit der dazugehörigen alten Programmversion in ein eigenes Datenverzeichnis wiederherstellen. Eine neue Datenbank nicht mit einem alten Programm öffnen und keine Tabellen oder Historien zur Erzwingung eines Downgrades abschneiden.

Zwischen Upgrade und Rückfall entstandene Geschäftsvorfälle sind in der alten Sicherung nicht enthalten. Sie müssen anhand des erhaltenen neueren Bestands ausdrücklich abgeglichen werden. Das betrifft auch Löschungen, Sperren und Widerrufe. Ein alter Programmstand besitzt die neu hinzugefügte Datenschutzfreigabe möglicherweise noch nicht: Seine Such-/Datei-/KI-Funktionen deshalb nicht als automatisch durch das neue Journal abgesichert ansehen. Zugriffe erst wieder zulassen, wenn die aktuellen Entscheidungen im tatsächlich zurückgerollten System wirksam umgesetzt sind. Ist dieser Nachweis nicht möglich, die neue Version reparieren, statt den alten Bestand öffentlich freizugeben.

## Kundenübernahme und Portabilität

CSV-Vorlagen existieren für Immobilien, Einheiten, Parteien, Verträge, Kontenzuordnungen und offene Posten. Externe Referenzen müssen zusammenpassen. Die Vorschau zeigt Feldzuordnung, Fehler, Dubletten sowie Mengen-/Betragsabgleiche und verändert noch keine Geschäftsdaten. Erst die bestätigte Übernahme schreibt nach erneuter Prüfung des Zielbestands atomar. Bei zwischenzeitlicher Zieländerung Vorschau erneuern; einen Konflikt nicht durch Teilimport umgehen.

Der Kundenexport enthält vereinbarte Geschäftsdaten, Beziehungen, Originale und Prüfsummen. Zugangstoken, Schlüssel und private Mitarbeitereinstellungen gehören nicht hinein. Bei einem frischen Wiederimport sind historische Portalzugänge und Bankfreigaben keine aktuellen Befugnisse. Betriebssicherungen mit geschützten Laufzeitdaten weiterhin über `ops restore` wiederherstellen.

## Portal- und Hostingkonfiguration

Für öffentlichen Betrieb `PORTAL_ENABLED=true` und eine vollständige HTTPS-Adresse in `PORTAL_PUBLIC_URL` setzen. Den lokalen Testmodus dort abschalten. Je Kunde eigene Instanz, Datenbank, Schlüssel, Dateispeicher und Sicherungen verwenden. Reverse Proxy, vertraute Proxyadresse und Host-/Originprüfung auf der echten Infrastruktur prüfen.

Das Hostingrezept baut Frontend, Linux-x64-Laufzeit und Lizenzbestand und verwendet UID/GID 10001. Bestehende Volumerechte müssen dazu passen. Die Windows-Prüfung eines Linux-Pakets belegt keine Linux-Ausführung. Tatsächliche Linux-/Proxy-/Containerabnahme, Herausgebersignierung und reale Anbieterzugänge bleiben die gesonderten Freigabeschritte des Plans.

## Reproduzierbarkeit und Lizenzbestand

Die lokalen E-Rechnungsvalidatoren und Regeln sind im Paket enthalten. Ein fehlendes oder verändertes Paket führt zu einem technischen Prüfstatus; der Beleg darf dann nicht übernommen werden. Quellstand, feste Asset-Hashes und Buildrezepte im Quellarchiv erhalten. Der Lizenzbereich `/api/v1/legal` stellt ausschließlich katalogisierte Paketdateien mit erneuter Pfad-/Größen-/Hashprüfung bereit. Lizenztexte und entsprechende Quellen zusammen mit dem Programm weitergeben; der MIT-Hinweis der Anwendung ersetzt die Bedingungen einzelner Bestandteile nicht.
