# Lokaler Release – 1. Oktober 2026

Der vereinte Stand führt die bestehende Immobilienverwaltung als lokale
SQLite-Anwendung fort. [DEVELOPMENT_STATUS.md](../DEVELOPMENT_STATUS.md) beschreibt
die umgesetzten Funktionen und die weiterhin externen Voraussetzungen.

## Start und Daten

Im Projektordner `start.bat` starten. Python 3.11+ und Node.js werden für die
Ersteinrichtung benötigt. Der Starter baut die Oberfläche, speichert den
Installationsschlüssel und verwendet standardmäßig
`%LOCALAPPDATA%\ImmoManagerPro`. Bei einer leeren Installation auf der lokalen
Anmeldeseite das Eigentümerkonto anlegen und optional Zwei-Faktor-Anmeldung
aktivieren. Danach ist die öffentliche Registrierung dauerhaft geschlossen.

Für eine separate Demonstration:

```powershell
.\start.bat -Seed -DataDir "$env:LOCALAPPDATA\ImmoManagerPro-Demo" -Port 8765
```

Das Demokonto ist `demo` / `Demo1234`. Ohne `-Seed` eigene Bestandsdaten erfassen.
Eigentümer weisen weiteren Benutzern ausdrücklich Portfoliozugriffe zu; siehe
[Zugangsmodell](ACCESS_MODEL.md). Alte lokale Projektarchive wurden nicht
verschoben oder gelöscht. Die Entwicklung und ihre Tests verwenden synthetische
Daten in getrennten Ordnern.

## Geprüfte Abläufe

Die Browserprüfung startet für jeden Lauf einen eigenen echten SQLite-Server.
Sie prüft sichtbare Oberflächenaktionen und die gespeicherten API-Ergebnisse:

1. Eigentümeranlage auf leerer Datenbank, geschlossene Registrierung,
   Authenticator-Anmeldung und Deaktivierung.
2. Neue Immobilie/Einheit/Mietvertrag, 750 EUR Monatsforderung, manuelle und
   Bank-Teilzahlung, datierter Storno, Restbetrag und vollständige Begleichung.
3. Teilzahlungen über erneute Anmeldung und Seitenneuladen hinweg.
4. Bankzuordnung und Storno mit erhaltenen Belegen und erneut verfügbarem Budget.
5. Abrechnungsvorprüfung, gespeicherte Einzelabrechnungen, Finalisierung,
   gesperrte Werte und echter PDF-Download.
6. Revisionskette mit tatsächlich bezahlten Vorschüssen, persistentem PDF der
   dritten Revision und ausschließlich gebuchten Korrekturdifferenzen.
7. Verfügbare Guthaben ohne negative Forderung oder behauptete Auszahlung;
   getrennte Eigentümeranteile mit erhaltener Gesamtkostensumme.
8. Geschützte PDF-/Bilddateien und Einheitenfoto nach erneuter Anmeldung.

## Prüfergebnisse

Aktueller Integrationsstand vom 2. Oktober 2026: 693 Frontendtests in 56 Dateien,
ESLint und 45 vollständige reale Edge-/SQLite-Browserabläufe bestanden. Der
CI-Typcheck umfasst nach der Bankzuordnung 73 kritische Quellen und ist lokal
grün; Ruff ist grün. Nach Integration der Rechnungszahlungsbelege bestanden
129 gemeinsame SQLite-Prüfungen (10 explizite Skips), darunter Migration,
Stornos, gemeinsames Guthabenbudget, Quellverlust-Wiederherstellung und die
korrigierten Billing-/Mietanpassungs-Testdaten. Zwei zusätzliche tatsächliche
API-Routerabläufe prüfen autorisierten Zugriff, genau einen Rechnungsbeleg und
keine zweite Cashbuchung mit Memory und SQLite.

Der vollständige gepinnte SQLite-Stand `51f69ef` ergab 2.649 bestandene,
82 übersprungene und 25 fehlgeschlagene Fälle. Diese Fehler lagen beim Aufbau
historischer Testdaten mit inzwischen unzulässiger Doppelbelegung; die
betroffenen Fixtures werden separat korrigiert, ohne die Produktprüfung oder
fachlichen Assertions abzuschwächen. Dieser Lauf ist **keine grüne
Gesamtfreigabe**. Die gemeinsame neue Gesamtsuite und der tatsächliche
PostgreSQL-CI-Lauf bleiben für den aktuellen Integrationsstand erforderlich.
Die neue Bankvorschlags-/Rechnungs-API ist integriert; ihre zusätzliche
Oberfläche wird noch umgesetzt. Ausführliche Beleg- und Upgradebeschreibung:
[Bankzuordnung](BANK_MATCHING.md).

Zusätzlicher integrierter Stand nach den unten dokumentierten früheren Gates:
578 Frontendtests in 46 Dateien, ESLint und Produktionsbuild bestanden.
Der gemeinsame Backend-Memory-Stand mit Portfoliozugriff und DATEV bestand
2.121 Tests (43 ausdrücklich übersprungen). Danach bestanden 27 echte
Fehlerdiagnostik-/Rollbackfälle, 57 Mietserien-/Quellabfragefälle (5 Skips),
vier Startup-/Router-/Resetfälle und eine vollständige frische Alembic-Migration.
Diese lokalen Zahlen sind keine PostgreSQL- oder Gesamtfreigabe; aktuelle
SQL-, Browser- und PostgreSQL-CI-Prüfungen bleiben erforderlich.

Die lokale Abnahme erfolgt auf Windows mit Python 3.14.7 und Microsoft Edge.
Die CI ergänzt Python 3.11/3.12 auf Linux, Playwrights gepinntes Chromium und
einen Docker-Compose-Smoke mit PostgreSQL. Der Compose-Smoke bestätigt Start,
Migration, Healthcheck und ausgelieferte Seiten; die vollständigen fachlichen
Browserabläufe verwenden SQLite.

| Prüfung | Ergebnis |
|---|---|
| Frontend Vitest | 297 Tests in 23 Dateien bestanden |
| ESLint / Vite-Produktionsbuild | bestanden |
| npm audit | 0 bekannte Schwachstellen |
| Backend Memory | 1.385 bestanden, 1 übersprungen; Coverage 86,79 % |
| Backend SQL | 1.385 bestanden, 1 übersprungen; Coverage 86,26 % |
| Ruff | Backend und Backup-Scheduler bestanden |
| Mypy | 43 kritische Quelldateien bestanden |
| pip-audit | keine bekannten Schwachstellen in requirements.txt |
| Echte Browserabläufe | 9 reguläre und 2 Ersteinrichtungsabläufe bestanden |

Die Gesamtsuiten enthalten die atomaren Import-/Zahlungsprüfungen,
Erhaltungsprüfungen der Migrationen und die Recovery-Fehlerfälle. Eine gesonderte
Reihenfolgeprüfung von Migrationen vor Ereignisprotokollierung bestand mit
23 Tests; Alembic lässt vorhandene Anwendungslogger aktiv.

Wiederherstellung wurde mit vollständig verschwundenem ursprünglichem
Datenordner und anschließendem frischen Serverprozess geprüft. Benutzer,
Installationsmarker, TOTP, schlüsselabhängige Kontodaten, fremde SQLite-Tabellen,
Trigger, Belege, Revisionen und lokale Dateiverweise bleiben erhalten. Fehler
bei Passphrase, ZIP-Struktur, Limits, Konfiguration, Dateiverweisen oder
Veröffentlichung erzeugen keine teilweise neue Installation.

## Betrieb und Grenzen

Vollständige Sicherung/Wiederherstellung mit gestoppter Anwendung und neuem
Zielordner nach [RECOVERY.md](RECOVERY.md). JSON-Transfer in Einstellungen deckt
einen Geschäftsdaten-Teilsatz ab. Der Scheduler sichert ausschließlich die
Datenbank. Externe Dateien und Plugin-Code sind separat zu erhalten. Für
frühere Upload-Speicherorte siehe [PRIVATE_FILES.md](PRIVATE_FILES.md).

Monatsforderungen verwenden aktuelle Einheitenbeträge und volle berührte
Vertragsmonate; ungebuchte Altmonate vor Erzeugung prüfen. Gebuchte Forderungen
und belegte Zahlungen bilden die historischen Auswertungen. Eine verfügbare
Gutschrift ist noch keine ausgeführte Rückzahlung.

WhatsApp, Postversand und externe Immobilienportale benötigen weitere
Anbieterimplementierung und echte Zugangsdaten. Mandantentrennung unabhängiger
Organisationen, produktiver PostgreSQL-Betrieb und zusätzliche optionale
KI-Modelle sind gesondert einzurichten und abzunehmen.

## Reproduzierbare Prüfung

```powershell
# In einer separaten Test-PowerShell im Projektordner:
$env:DATABASE_URL = $null # eigene temporäre Testdatenbank statt vorgegebener Laufzeit-URL
$env:TEST_STORE_BACKEND = 'memory' # anschließend 'sql'
$env:COVERAGE_FILE = '.coverage.memory' # für SQL eigener Dateiname
.\.venv\Scripts\python.exe -m pytest backend/tests -q --tb=short --cov=backend --cov-fail-under=80
cd frontend
npm run test
npm run lint
npm run build
$env:IMMO_E2E_CHANNEL = 'msedge' # Linux-CI verwendet standardmäßig Chromium
npm run test:e2e
npm run test:e2e -- --fresh-install
```

Browserabhängigkeiten bei Bedarf mit `npx playwright install chromium` im
Frontendordner installieren. Weitere Informationen in
[frontend/e2e/README.md](../frontend/e2e/README.md).
