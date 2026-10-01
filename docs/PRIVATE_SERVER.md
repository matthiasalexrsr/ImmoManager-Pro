# Privater Mehrbenutzer-Server

`compose.private-server.yml` startet die Anwendung mit PostgreSQL und dauerhaft
gespeicherten Anhängen, Konfigurationen und Protokollen. Die Datenbank ist nur
im internen Compose-Netz erreichbar. HTTP lauscht am Server auf
`127.0.0.1:8080`; Fernzugriff erfolgt über einen privaten HTTPS-Zugang.
Für jeden Menschen ein eigenes Benutzerkonto anlegen.

## Einrichtung

Docker mit Compose bereitstellen und die Projektversion auf dem Server
aufbewahren. Die tatsächliche private HTTPS-Adresse zuerst festlegen. In den
folgenden Befehlen `https://immo.example.internal` durch diese Adresse ersetzen:

```powershell
python scripts/configure_private_server.py --origin https://immo.example.internal --output .env.server
docker compose --env-file .env.server -f compose.private-server.yml -p immomanager up -d --build --wait app
docker compose --env-file .env.server -f compose.private-server.yml -p immomanager exec app python scripts/server_admin.py initial-owner --username verwaltung --email verwaltung@example.invalid --full-name "Verwaltung"
```

Die E-Mail-Adresse ebenfalls ersetzen. Das Eigentümerpasswort wird interaktiv
abgefragt. `.env.server` enthält unabhängige Datenbank-, Sitzungs- und
IBAN-Schlüssel, wird vor dem Schreiben geschützt und nicht überschrieben.
Diese Datei mit der Installation erhalten. Keine Schlüssel durch neue Werte
ersetzen, um einen Lesefehler zu umgehen. Der initiale Eigentümer lässt sich
nicht ein zweites Mal über die Einrichtung anlegen.

Bei der Anmeldung Zwei-Faktor-Authentifizierung einrichten und weitere Konten
über die Benutzerverwaltung erstellen. Finanz-, Betriebs- und Eigentümerrollen
steuern die erlaubten Tätigkeiten. Änderungen aus parallelen Formularen werden
auf ihre ursprüngliche Revision geprüft; bei Konflikten bleibt der Entwurf
erhalten und lässt sich mit dem aktuellen Stand abgleichen.

## Privater Fernzugriff

Eine mögliche Verbindung ist Tailscale auf dem Server und den zugelassenen
Geräten. Tailscale Serve stellt einen Dienst für das eigene Tailnet bereit.
Nach Anmeldung und den erforderlichen HTTPS-Einstellungen:

```powershell
tailscale serve --bg http://127.0.0.1:8080
tailscale serve status
```

Die von Serve ausgewiesene HTTPS-Adresse muss der bei der Einrichtung
gespeicherten `APP_ORIGIN` und ihr Host `APP_HOST` entsprechen. Zugriff in den
Tailnet-Regeln auf die vorgesehenen Personen und Geräte beschränken. Die
Anwendung verlangt zusätzlich ihre eigene Anmeldung. Alternative private VPNs
oder ein eigener HTTPS-Reverse-Proxy können denselben lokalen Dienst bedienen.
Konfiguration und Voraussetzungen: [offizielle Tailscale-Serve-Dokumentation](https://tailscale.com/docs/features/tailscale-serve).

## Vollständiges Serverbackup

Die Serversicherung enthält den vollständigen PostgreSQL-Dump, den gesamten
Appdaten- und Upload-Baum, die geschützte Serverkonfiguration und Prüfsummen.
Sie hält die App während der Sicherung an und startet sie anschließend wieder,
wenn sie zuvor lief. Auf dem Docker-Host ausführen:

```powershell
python scripts/private_server_backup.py backup --project immomanager --env-file .env.server --destination "E:\Backups\immomanager-2026-10-01.immobak"
```

Die Passphrase wird interaktiv abgefragt; getrennt vom verschlüsselten Paket
aufbewahren. Zieldatei und nötige temporäre Speicherfläche müssen verfügbar
sein. Bei größeren Beständen das [Kapazitätsprofil](CAPACITY.md) verwenden.

Eine Wiederherstellung erfolgt in ein ausdrücklich neues Projekt mit einer
neuen geschützten Konfigurationsdatei:

```powershell
python scripts/private_server_backup.py restore --project immomanager-recovery --source "E:\Backups\immomanager-2026-10-01.immobak" --env-output .env.server.recovery
```

Vorher die alte App anhalten, wenn der gleiche lokale Port verwendet wird.
Eine vorhandene Installation wird nicht ersetzt. Das Paket benötigt die
passende gespeicherte Compose- und Programmversion; diese zusammen mit den
Sicherungen erhalten. Der Profile-Hash wird geprüft. Ein fehlgeschlagener
Wiederherstellungsversuch behält seine neuen Ressourcen zur Untersuchung,
statt die frühere Installation zu löschen. Danach Anmeldung mit TOTP,
Kontodaten, Belege/Gegenbelege und private Anhänge prüfen.

Die automatisierte Linux-Prüfung erzeugt eine eigene Installation mit echten
PostgreSQL-Prozessen, mehreren Benutzern, TOTP, Zahlungen und Anhängen, erstellt
die verschlüsselte Vollsicherung, entfernt die Quelle und stellt sie in einem
neuen Projekt wieder her. Das ersetzt nicht eine Wiederherstellungsprüfung auf
dem tatsächlich verwendeten Server.

## Betrieb über viele Jahre

Die Daten gehören der eigenen Installation und lassen sich sichern und
exportieren. Große Listen werden schrittweise gelesen. Backups und Schlüssel
auf getrennten Medien erhalten und regelmäßig eine vollständige
Wiederherstellung auf einem zweiten Ziel prüfen. Erfolgreiche Sicherung und
erfolgreiche Wiederherstellung sind zwei getrennte Nachweise.

Wartungsfenster für Sicherheitskorrekturen bleiben erforderlich. Das aktuelle
Serverprofil verwendet PostgreSQL 16; dessen Unterstützung endet am
9. November 2028. PostgreSQL unterstützt jede Hauptversion fünf Jahre und
empfiehlt aktuelle Fehlerkorrekturversionen. Für einen Hauptversionswechsel
die Daten über `pg_upgrade` oder Dump/Wiederherstellung in ein neues getestetes
Profil migrieren, die alte Installation bis zur Abnahme erhalten und erst
danach den Zugang umschalten. Ein Wechsel des Image-Tags allein migriert kein
Datenverzeichnis. [PostgreSQL-Versionierungs- und Upgrade-Regeln](https://www.postgresql.org/support/versioning/).

Das Projekt kann auf zwanzig Jahre Datennutzung vorbereitet werden; ein
zwanzigjähriger Betrieb ohne Sicherheitsupdates oder Erneuerung von Hardware
und unterstützten Laufzeitversionen ist damit nicht nachgewiesen.
