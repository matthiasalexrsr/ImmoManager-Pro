# Integration von Rechnungseingang, Arbeitsabläufen, Migration und Portalen

Dieser Quellstand erweitert den korrigierten Auditstand additiv. Der endgültige Prüfnachweis nennt den getesteten Git-Commit, das gebaute Windows-Testpaket und dessen SHA-256. Ein Quellstand allein ist keine Freigabe der späteren Hostingumgebung.

## Paket vorbereiten

Die E-Rechnungsverarbeitung benötigt das lokale Paket aus `backend/services/e_invoice/assets.json`. `python -m tools.prepare_e_invoice artifacts/e-invoice` lädt ausschließlich beim Build die festgeschriebenen Eingaben, prüft ihre SHA-256 und erzeugt die reproduzierbaren CLI-Pakete. Der Windows-PyInstaller-Build führt diesen Schritt automatisch aus. Die Anwendung lädt beim Start keine Validatoren nach. Ein fehlendes, verändertes oder unvollständiges Paket führt zu einem sichtbaren technischen Prüffehler; der Eingang ist dann nicht übernehmbar.

KoSIT 1.6.3 verwendet XRechnung 3.0.2 mit dem Regelstand 2026-08-31. Mustang 2.26.0 ist als Paketrevision `immo1` enthalten: Jackson Core/Databind 2.22.4, AssertJ 3.27.7 und Byte Buddy 1.17.8 ersetzen die alten eingebetteten Bibliotheken. Validatorcode und Regeln bleiben unverändert. Aus dem KoSIT-Paket wurde ausschließlich die ungenutzte Weboberfläche entfernt. Die Rezepte, Eingangshashes und erwarteten Ausgaben stehen im Quellstand; eine Abweichung bricht den Build ab.

`python scripts/check_e_invoice_runtime.py` prüft echte positive und negative XML-/PDF-Beispiele mit den tatsächlichen Engines. Herkunft und SHA-256 der unveränderten Beispiele stehen in `backend/tests/fixtures/e-invoice-runtime/manifest.json`; abgeleitete Fälle werden im Prüflauf erzeugt. Testdoubles für Fachtransaktionen ersetzen diesen Lauf nicht.

## Aktualisierung und Rückfall

1. Die bisherige Programmversion und eine vollständige, geprüfte Sicherung einschließlich Datenbank, Uploads, Schlüssel und Konfiguration aufbewahren. Ein Kundenexport ersetzt diese Betriebssicherung nicht.
2. Alle Nutzer abmelden und die alte Instanz vollständig beenden. Das neue Programm in ein eigenes Programmverzeichnis entpacken; denselben Datenordner ausdrücklich zuordnen. Für eine Prüfinstallation einen eigenen leeren Datenordner verwenden.
3. Den vorgesehenen Upgradeweg ausführen. Er erstellt vor Änderungen eine Vollsicherung. Die neuen Tabellen sind additiv; die Historienkennung für externe Akteure wird verlustfrei verbreitert. Neue Datenschutzentscheidungen speichern zusätzlich Hashes gesperrter Dateischlüssel. Fehlgeschlagene Migrationen nicht durch manuelles Setzen des Versionsstands übergehen.
4. Anmeldung, Rollen, Rechnungseingang, Arbeitscockpit, Importvorschau und einen neuen Export prüfen. Öffentliche Portale erst nach bestätigter HTTPS-/Proxykonfiguration freigeben.
5. Bei Rückfall die neue Instanz beenden und die geprüfte Sicherung in einen separaten Datenordner mit der dazugehörigen alten Programmversion wiederherstellen. Eine neue Datenbank nicht mit einem alten Programm öffnen. Neue historische Entscheidungen dürfen bei einem Schema-Downgrade nicht abgeschnitten werden.

Nach jeder Wiederherstellung bleiben Portalzugriffe, Suche und KI bis zum dokumentierten Abgleich aktueller Lösch- und Sperrentscheidungen gesperrt. Das separat exportierte Datenschutzjournal nachziehen; wiederaufgetauchte Löschkandidaten ausdrücklich bearbeiten. Anschließend den Wiederherstellungsstand im Datenschutzbereich freigeben und externe Zuordnungen einzeln prüfen. Alte Einladungen und Sitzungen werden nicht wieder aktiviert.

Eine Dokumentlöschung entfernt Datensatz und Suchindex und sperrt bekannte direkte Datei-/OCR-Verweise. Archivoriginale, betroffene Sicherungskopien und erforderliche Aufbewahrungen bleiben gesondert im Auskunfts-/Löschvorgang zu beurteilen; die Anwendung behauptet keine physische Löschung sämtlicher Kopien.

## Portalbetrieb und Wiederherstellung eines Zugangs

`PORTAL_ENABLED=true` und eine vollständige HTTPS-Adresse in `PORTAL_PUBLIC_URL` konfigurieren. Jede Kundeninstanz braucht eigene Datenbank, Schlüssel, Speicher und Backups. `PORTAL_LOCAL_TEST_MODE` ist ausschließlich für einen ausdrücklich lokalen Loopback-Test bestimmt. Interne JWTs gelten nicht als Portal-Anmeldung.

Einladungen und Dokumentveröffentlichungen erfolgen in den Einstellungen unter Portalverwaltung. Für vergessene Passwörter steht dort eine gesonderte Rücksetzung mit erneuter dokumentierter Identitätsprüfung bereit. Sie sperrt alle bisherigen Sitzungen, Einladungen und Zuordnungen des Kontos. Der einmal sichtbare Link gilt 24 Stunden; nach Annahme wird nur das geprüfte Verhältnis wieder zugänglich. Bei verlorener Antwort liefert ein wiederholter Auftrag keinen zweiten geheimen Link und setzt das Konto nicht erneut zurück.

## Hosting-Build

Der Docker-Build erzeugt Frontend, Linux-x64-Laufzeit und den Lizenzbestand im Buildschritt. Die ausgeführte Anwendung enthält keine npm-Installation oder Downloadcaches und läuft als UID/GID 10001. Compose veröffentlicht nur den lokalen Anwendungsport; PostgreSQL erhält keinen Hostport. Passwort und JWT-Schlüssel müssen explizit und pro Instanz verschieden gesetzt werden. Für `POSTGRES_PASSWORD` einen zufälligen URL-tauglichen Wert verwenden, da er in die Verbindungs-URI eingeht.

`docker-compose.yml` ist das Hostingprofil (`ENVIRONMENT=production`). Bevor der Container migriert oder startet, prüft `tools/validate_hosting_config.py` die Einstellungen und nennt bei einem Fehler nur den Namen der Einstellung, nie ihren Wert. Verlangt werden:

| Einstellung | Anforderung |
|---|---|
| `JWT_SECRET_KEY`, `BACKUP_PASSPHRASE` | je mindestens 32 zufällige Zeichen; die Passphrase getrennt von den Sicherungen aufbewahren |
| `CORS_ORIGINS` | die öffentlichen HTTPS-Adressen der Instanz, ohne Pfad und ohne `*` |
| `TRUSTED_PROXY_IPS` | die Adresse des Reverse Proxy, wie der Container sie sieht (z. B. das Gateway des Docker-Netzes), als IP oder CIDR; nie `*` oder `0.0.0.0/0`. Nur von dort übernimmt uvicorn (`--proxy-headers`) Client-Adresse und Schema; ohne das sähe die Anmeldebremse alle Anfragen von einer Adresse. |
| `DATABASE_URL` | die eigene PostgreSQL-Datenbank mit eigenem Benutzer und Passwort (Compose setzt sie aus `POSTGRES_*`) |
| `PORTAL_PUBLIC_URL` | bei eingeschaltetem Portal eine HTTPS-Adresse |
| Demodaten, Selbstregistrierung, Diagnose, Selbstupdate, Testversion, Speicher-Rückfall, lokaler Portaltest | aus; Sicherheitskopfzeilen an |

Das Monitoring (`docker-compose.monitoring.yml`) verlangt ein eigenes `GRAFANA_ADMIN_PASSWORD` und veröffentlicht Prometheus und Grafana nur auf 127.0.0.1, den Blackbox-Exporter gar nicht. `ops/nginx/immomanager.conf.example` ist eine Vorlage für den Reverse Proxy (HTTPS, Weiterleitung von HTTP, ersetzte Forwarding-Header). Für die Entwicklung auf dem eigenen Rechner: `docker compose -f docker-compose.yml -f docker-compose.development.yml up` (`ENVIRONMENT=development`, lokale Adressen, ohne die Prüfung).

Für bestehende Datenvolumes vor dem Wechsel die Zugriffsrechte auf UID/GID 10001 kontrolliert anpassen. Der Reverse Proxy muss HTTPS terminieren, die tatsächliche Proxyadresse muss ausdrücklich vertraut sein; die Host-/Originprüfung des Portals bleibt aktiv. Ressourcenlimits gelten für die Instanz, zusätzlich begrenzen die Prüfprozesse Zeit, Speicher und Ausgabe. Die tatsächliche Linux-/Proxy-/Hostingabnahme ist separat auf der Zielumgebung durchzuführen; eine unter Windows geprüfte Linux-Paketerstellung belegt keine Linux-Ausführung.

## Lizenznachweise

`python -m tools.third_party_notices` erstellt den Bestand der tatsächlich gewählten Python-/npm-/Java-/Regel-/Schriftbestandteile und fügt die festgeschriebenen Quellarchive bei. Fehlende oder veränderte Texte/Archive brechen den Build ab. Im Programm und im externen Portal führt „Lizenzen und Quellarchive“ zu `/api/v1/legal`. Diese öffentliche Route liefert ausschließlich katalogisierte Paketdateien, keine Kundenunterlagen. Downloads prüfen ID, Pfad, Größe und SHA-256 erneut.

MPL-Komponenten einschließlich Saxon und veraPDF werden mit ihren unveränderten entsprechenden Quellen und Texten bereitgestellt; für Logback wird die angebotene EPL-2.0-Option verwendet. Die CEN-Regeln unter EUPL-1.2 bleiben getrennte Prüfbestandteile mit mitgelieferten Quellen. GNU FreeFont wird als eigenständiges Produkt einschließlich Originaldistribution, SFD-Quellen und Lizenz bereitgestellt. Die CEN-/DIN-Erlaubnisvermerke sind im Lizenzbereich sichtbar. Diese Bedingungen werden nicht durch die MIT-Lizenz der Anwendung ersetzt.

Primärquellen: [MPL-FAQ](https://www.mozilla.org/en-US/MPL/2.0/FAQ/), [Saxonica-Lizenzen](https://www.saxonica.com/html/license/terms.html), [EUPL-FAQ](https://interoperable-europe.ec.europa.eu/collection/eupl/faqs), [GNU-FreeFont-FAQ](https://www.gnu.org/software/freefont/FAQ.html), [FeRD-Nutzungsrechte](https://www.ferd-net.de/ueber-uns/ressourcen-1/veroeffentlichungen/haftungsausschluss-und-nutzungsrechte).

Das optionale AGPL-/kommerziell lizenzierte Dokumenteditorprofil bleibt vom Core-Testpaket ausgeschlossen. Tatsächliche Signierung, Anbieterzugänge, Rechte am eigenen Produktmaterial und die Zielhosting-Abnahme bleiben die im Plan gesondert genannten Freigaben. Ein gebautes Betriebssystem-/Containerimage darf erst nach Erfüllung der entsprechenden Quellpflichten seiner konkreten Systempakete weitergegeben werden; das Hostingrezept inventarisiert dafür die tatsächlich installierten Debian-Versionen und Copyrighttexte.
