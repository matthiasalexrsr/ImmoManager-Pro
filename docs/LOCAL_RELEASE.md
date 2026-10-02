# Lokaler Release – 2. Oktober 2026

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

### Neuer lokal abgenommener Vertragsablauf

G06.1 ergänzt geprüfte Verlängerungen und Kündigungen mit privaten Entwürfen,
aktuellen Konfliktprüfungen und unveränderlichen Bestätigungsbelegen. Ein
Folgevertrag bekommt eine neue Identität; bestehende Forderungen, Zahlungen
und Kautionsangaben werden nicht kopiert. Kündigungen beachten das bestätigte
inklusive Mietende und lassen sich danach ausdrücklich manuell abschließen.
Ein früheres bestätigtes Mietende kann durch einen neuen geprüften Vorgang
abgelöst werden, ohne dessen ursprüngliche Bestätigung umzuschreiben.

Die gemeinsamen tatsächlichen SQLite-/Edge-Prüfungen bestanden alle sieben
ausgewählten Vertrags-/Sitzungs-/Kalender-/Dokumentabläufe; drei ergänzende
Wizard-Abläufe bestanden ebenfalls. Das komplette Frontend bestand 865 Tests
in 69 Dateien. Datenbank-, Reset-, Import- und Wiederherstellungsnachweise sowie
der tatsächlich reproduzierte und behobene Dialogverlust beim Listenrefresh
sind in [G06_RELEASE_VERIFICATION.md](G06_RELEASE_VERIFICATION.md) getrennt
belegt. Die neue vollständige CI und unabhängige PostgreSQL-Prüfung müssen
noch auf dem nächsten veröffentlichten Commit ausgeführt werden.

G06.2-Fristenautomation, Vorlagendokumente und Versandverfolgung sind weiterhin
offen. Die Skalierung der Vertragsübersicht benötigt zusätzlich die laufende
Workspace-Integration; diese Abnahme erklärt keinen Gesamtabschluss.

### Vollständig bestandener veröffentlichter Stand

[CI #124](https://github.com/matthiasalexrsr/ImmoManager-Pro/actions/runs/36966629656)
auf `82930ad7760486264536f150e08ddaf97e1ac361` ist vollständig erfolgreich
abgeschlossen. Jeder der vier Memory-/SQLite-Läufe unter Python 3.11/3.12
bestand 3.323 Tests mit 149 ausdrücklichen Skips und 90 % Coverage. Die
Frontendprüfung bestand 829 Tests in 67 Dateien, Lint und Produktionsbuild.
113 Mypy-Quellen und die ausgeführten Sicherheitsprüfungen bestanden.

Linux Chromium bestand alle 60 Verwaltungsabläufe sowie beide gesonderten
Owner-/TOTP-Abläufe auf einer leeren Installation. Die unabhängigen tatsächlichen
PostgreSQL-Gruppen bestanden zusammen 182 Tests mit einem ausdrücklichen Skip,
einschließlich der beiden korrigierten Kalender-Snapshot-/Body-Prüfungen und
Dokumentversionen samt Wiederherstellung. Beide verpflichtenden nativen
Linux-OCR-Gruppen bestanden jeweils 124 Tests ohne Skip. Der private
PostgreSQL-Serverlebenszyklus, der allgemeine Docker-Compose-Smoke und das
abschließende Betriebsbereitschaftsgate bestanden ebenfalls.

Diese Abnahme gilt genau für den oben genannten veröffentlichten Commit.
Die oben beschriebenen neuen Vertragsabläufe und die übrigen offenen Punkte
des [historischen Inventars](HISTORICAL_FEATURE_MATRIX.md) benötigen ihre eigenen
vollständigen CI-Nachweise. WISO Steuer für Windows ist hier weiterhin nicht
installiert; ein echter Import in dieses Verbraucherprogramm ist deshalb
keine ausgeführte Prüfung. Die folgenden älteren CI-Befunde dokumentieren
die behobenen Ursachen und ihre Korrektur, nicht den aktuellen Gesamtstatus.

### Frühere Befunde und lokale Nachweise

CI #123 (`4e36b07`) ist abgeschlossen. Jeder der vier Memory-/SQLite-Läufe
unter Python 3.11/3.12 bestand 3.300 Fälle und übersprang 149 ausdrücklich;
vier Tests scheiterten je Lauf: zwei ältere Migrationsprüfungen erwarteten
weiter den bisherigen x1-Head, und die neue Capture-Handler-Prüfung setzte
ungewollt einen von vorherigen Tests abhängigen INFO-Loglevel voraus. Der
Nachtrag prüft den tatsächlichen eindeutigen Alembic-Head und aktiviert den
getesteten Ereignislogger ausdrücklich, auch bei WARNING am Rootlogger.
32 gemeinsame tatsächliche Migrations-/Betriebsmetrikenfälle bestanden.

Das gesamte Frontend, beide verpflichtenden nativen Linux-OCR-Gruppen und der
private PostgreSQL-Serverlebenszyklus bestanden. PostgreSQL-Dokumentversionen,
unabhängige Writer und deren Recovery bestanden ebenfalls; zwei Kalenderfälle
scheiterten vor Ausführung ihrer eigentlichen Prüfung, weil die ausgewählten
Portfolios gegen den globalen Entwicklungsbestand geprüft wurden. Beide
Testaufbauten binden nun den tatsächlichen eigenen SQLStore. Dies wird weiterhin
durch die nächste echte PostgreSQL-CI nachgewiesen, nicht durch einen lokalen Skip.

Linux Chromium bestand 59 Abläufe, einschließlich aller drei neuen
Mehrfachsitzungsfälle. Ein Datenschutzfall erwartete noch den alten Exporttext
ohne Dokumentversionen. Die ausdrückliche neue Umfangsprüfung plus leere
Version-/Originalbestände bestand danach in einem echten frischen SQLite-/Edge-Lauf.
Der allgemeine Compose-Smoke wurde wegen der Backendfehler übersprungen;
Gesamtfreigabe bleibt ausstehend.

Der Vertrags-Datumsfilter besitzt keine frühere 10.000-Zeilen-Gesamtgrenze mehr.
SQL filtert Scope, Stammdaten und Daten vor OFFSET/LIMIT; Memory wählt nur die
angeforderte Seite unter dem vorhandenen reentranten Fachlock aus. Der
Baseline-Bestand mit 10.002 synthetischen Verträgen reproduzierte die fehlenden
Treffer; parallele Memory-Löschung beziehungsweise Portfolioänderung
reproduzierte den fehlenden Leselock. Beide Nachträge sind integriert. Root
bestand 21 gemeinsame Datumsfilter-/Kalenderfälle mit drei ausdrücklichen
Adapter-/PostgreSQL-Skips sowie Ruff und die CI-Typprüfung mit 113 Quellen für
Linux/Python 3.11 und Windows/Python 3.12. Details:
[Vertrags-Datumsfilter](CONTRACT_DATE_FILTER.md).

Die lokale Vorschau wurde nach einer neuen ownergeschützten bytegenauen Kopie
aller acht vorhandenen Dateien aktualisiert. Beim Release-124-Nachtrag behalten
81 bestehende Geschäftstabellen (einschließlich der beiden Dokumentversionstabellen)
ihre bisherigen Spaltenwerte vollständig; SQLite-Integrität und FKs
sowie unveränderte Installationsschlüssel sind geprüft. Fehlende frühere
Demo-Originale bleiben ausdrücklich ungelöst und wurden nicht erfunden.
Die neue dauerhafte private Windows-OCR-Installation in
`Documents\ImmoManagerPro\tools\ocr-2026-10-release123` bestand eine erneute
echte PNG-/Raster-PDF-/Sprach-/Versionsprüfung. Alle sechs Werkzeugwerte sind
dauerhaft in der privaten Datenkonfiguration gespeichert. Tatsächliche Demo-
Anmeldung, Kalender, Dokumenthistorie und Betriebsmetriken antworteten HTTP 200.

Der aktuelle gemeinsame Dokument-/Kalender-/Sitzungsstand bestand lokal 829
Frontendfälle in 67 Dateien mit zwei Testworkern, ESLint und Ruff. Die vollständige
CI-Typprüfung mit Mypy 2.4.0 bestand mit 112 Quelldateien sowohl für
Linux/Python 3.11 als auch Windows/Python 3.12. 243
Dokument-/Auskunfts-/Wiederherstellungsfälle bestanden
(fünf ausdrückliche Adapter-Skips), einschließlich verschwundener Quelle,
neuem Wiederherstellungsziel und frischer Anmeldung. Der gemeinsame
Kalender-/DATEV-/Berechtigungs-HTTP-Lauf bestand nach dem letzten Body-Guard
72 Fälle (zehn ausdrückliche Skips). Zehn Dokument-/Mieterdownloadfälle bestanden
erneut mit dem gemeinsamen privaten Download-Response.
Fünf echte Edge-/SQLite-Abläufe bestanden nach frischer vollständiger
y1-Migration: Originalarchivierung, Versionsupload, verlorene Erfolgsantwort,
Wiederholungsbefehl, Restore und alle Originaldownloads; außerdem stabiler
Portfolio-ICS-Download, tatsächliche Readonly-Termine und 320/360-Pixel-Layouts;
außerdem drei Mehrfachsitzungsfälle mit echtem Backend: konkurrierender Refresh,
absichtlich veralteter Renderer-Speicher sowie Benutzerwechsel mit entfernten
privaten Ansichten und anschließender tabübergreifender Abmeldung.
Die unabhängigen PostgreSQL-Dokument-/Recovery-/Kalenderfälle sind in der CI
registriert; ihr neuer gemeinsamer Lauf steht noch aus. Der Kalender prüft
aktuelle Quellzuordnungen vor dem Header und vor weiteren betroffenen
Bodyblöcken. Tatsächliche ASGI-Tests verschieben eine Quelle beziehungsweise
entziehen eine Berechtigung nach dem ersten Block: weitere private Bytes werden
nicht gelesen oder ausgeliefert, und temporäre Dateien werden entfernt.

Dokumentfassungen ersetzen keine alten Originaldateien oder deren `file_url`.
Ein fehlendes Original wird vor erster Archivierung ausdrücklich angezeigt.
Eine vollständig geprüfte bereits archivierte Originalfassung bleibt dagegen
auch nach Verlust ihrer früheren Uploadquelle wiederherstellbar. Hinweise und
Grenzen stehen in [Dokumentversionen](G37_DOCUMENT_VERSIONING_HANDOFF.md) und
[Kalenderexport](CALENDAR_ICAL_EXPORT.md).

CI #122 (`d25ca2d`) bestand die verpflichtende echte Linux-OCR-Prüfung mit
jeweils 124 ausgeführten Memory-/SQLite-Fällen ohne Skip, das Frontend sowie
die PostgreSQL-Parallelitäts- und private Server-Lebenszyklusprüfung.
Die beiden Memory-Matrixjobs stoppten zunächst an vier plattformabhängigen
Typmeldungen in Runtime-Locking und dem OCR-Werkzeugmanifest. Der enge
Nachtrag verwendet denselben dynamischen Plattformimport wie der POSIX-Pfad
und ein ausdrücklich typisiertes Werkzeugmanifest. Root bestand danach die
vollständigen 101 Quellen mit Linux/Python-3.11- und Windows/Python-3.12-Ziel
sowie die vier tatsächlichen Runtime-Konfigurationsfälle. Die neue gemeinsame
CI-Abnahme dieses Nachtrags bleibt gesondert nachzuweisen.

CI #122 ist inzwischen abgeschlossen. Beide SQLite-Gesamtläufe bestanden
3.062 Fälle und übersprangen 118 ausdrücklich, meldeten aber jeweils drei
Fehler: Zwei Logfälle verloren die Request-ID nach Austausch der Root-Handler;
ein HTTP-Vertragstest setzte bei einem synthetischen unvollständigen PDF
verfügbare native Werkzeuge voraus. Der Nachtrag bindet den vorhandenen
RequestContextFilter an den Ereignislogger und hält die PDF-Extraktion im
HTTP-Vertragstest kontrolliert; die verpflichtende echte OCR-Prüfung bleibt
unverändert. 54 gemeinsame Log-/HTTP-/Diagnostik-/Konsolenfälle bestanden
auf diesem korrigierten lokalen Stand. Die Browserprüfung bestand 55 Fälle
und meldete einen echten konkurrierenden Refreshfehler zwischen zwei Tabs.
Die integrierte Korrektur speichert Zugangsdaten atomar in IndexedDB und markiert
eine Rotation vor dem einmaligen HTTP-Aufruf. Ein unklarer Ausgang führt zur
ausdrücklichen Wiederholung im ursprünglichen Tab oder einer neuen Anmeldung,
ohne einen bereits verbrauchten Refresh nochmals zu senden. Verspätete Antworten
überschreiben keine neuere Sitzung; ein Benutzerwechsel lädt die Ansicht vollständig
neu. Die drei neuen tatsächlichen Edge-Fälle sind oben aufgeführt; Linux Chromium
bleibt durch die neue gemeinsame CI nachzuweisen. Details:
[Mehrfachanmeldung](AUTH_MULTITAB_COORDINATION.md).
Der allgemeine Compose-Smoke wurde wegen der
fehlgeschlagenen Backendgates übersprungen. Eine Gesamtfreigabe ist damit
weiterhin nicht belegt.

Das ausdrückliche Windows-OCR-Werkzeugsetup ist ebenfalls integriert. Es prüft
52 fest versionierte Pakete und den Bootstrap per SHA256, installiert ausschließlich
in ein neues privates Ziel und prüft tatsächlich PNG und Raster-PDF mit
unverändertem Original-SHA. 38 Setuptests bestanden auf dem gemeinsamen Root-Stand.
Der getrennte Implementierungslauf bestand Memory und SQLite mit jeweils
58 Fällen und fünf bestehenden optionalen Discovery-Skips; echte native
Unicode-Installation und Prüfung sind dokumentiert in
[Windows-OCR-Werkzeuge](WINDOWS_OCR_TOOLS.md). Die Installation aktiviert selbst
keine Anwendungskonfiguration. Ein neu gebautes EXE wird damit nicht behauptet.

Der nächste vereinte Prüfstand enthält G51-Betriebsübersicht, G38-PDF-/Bild-OCR,
die mobile Settings-Korrektur und die bewahrende Offline-Rechnungswartung.
Root bestand tatsächlich 763 Frontendfälle in 62 Dateien, ESLint sowie drei
Edge-/SQLite-Browserabläufe bei 320/360 Pixeln einschließlich Dateifeld-Fokus,
Tab-Reihenfolge, Skiplink und manuell aktualisierter Betriebsübersicht.
Der gemeinsame SQL-Lauf mit echten lokalen OCR-Werkzeugen bestand 150 Fälle;
nur zwei ausdrücklich Linux-spezifische Prozessfälle wurden auf Windows
übersprungen. Er enthält Raster-PDF, PNG/JPEG/TIFF/BMP/WebP, OCR-Konfiguration,
bekannte Altzahlungsstrukturen, strikte Index-/FK-/Originalbewahrung und
Wiederherstellung. Ruff und der vollständige CI-Mypy-Aufruf mit 101 Quellen
bestanden. Ein vorheriger unter paralleler Last ausgeführter SQL-Lauf hatte
einen 30-Sekunden-Testtimeout beim simulierten Frozen-Start; der gezielte
Wiederholungslauf und der abschließende gemeinsame Lauf bestanden.
Ein tatsächlich gebautes EXE ist damit weiterhin nicht geprüft.

Die echte lokale Vorschau wurde nach erneuter vollständiger privater,
bytegenauer Kopie aller acht vorhandenen Dateien offline erfolgreich
aktualisiert. Sämtliche ursprünglichen Tabellenwerte, Spaltendefinitionen,
Beziehungen, Indizes, fremden CHECKs, Views und Trigger bestanden die
unveränderte Bewahrungsprüfung vor Commit; keine Alembic-Version wurde geraten.
Login und das echte JSON-Metrik-Endpoint antworteten nach Neustart mit HTTP 200;
SQLite wurde als erreichbar und tatsächlich persistent ausgewiesen.
Die vorherige Datenbank bleibt separat privat erhalten. Die zehn früheren
Demo-Dateiverweise ohne vorhandene Originaldatei bleiben ungeklärt; die
physische Bestandskopie ist deshalb keine behauptete vollständige
Originaldatei-Wiederherstellung dieses Demo-Bestands.

OCR-Ressourcenbudgets einschließlich Auflösung sind explizit anpassbar, ohne
willkürliche Produktobergrenze. Originale bleiben bei Budget-/Werkzeugfehlern
erhalten; korrigierbare Hinweise und erneute Verarbeitung sind möglich.
Der neue erforderliche Linux-OCR-Job prüft tatsächliche Werkzeuge, deutsche
und englische Sprachdaten und Prozessbereinigung ohne Skips. Die vollständige
neue Linux-/PostgreSQL-/Browser-/Container-CI muss den vereinten Source-Stand
noch bestätigen; der allgemeine Compose-Importfix ist darin enthalten.

CI #121 auf `c6d9f63` ist abgeschlossen. Die vier vollständigen Linux-
Backendläufe (Memory/SQLite, Python 3.11/3.12) bestanden jeweils mit 2.891
Tests, 109 expliziten Skips und 90 % Coverage. Die Browserprüfung bestand
53 Verwaltungsabläufe und zwei frische Owner-/TOTP-Abläufe.
CI #121 bestätigte die gesamte PostgreSQL-Gruppe mit 169
bestandenen Fällen und einem expliziten Skip. Alle sechs Teilgruppen bestanden,
einschließlich der zuvor fehlgeschlagenen Vertrags-PDF-Treiberfälle sowie
Bankzuordnung und konkurrierender privater Entwürfe. Auch der private
PostgreSQL-Containerlebenszyklus bestand. Der zusätzliche allgemeine Compose-
Smoketest scheiterte nach erfolgreichen Migrationen beim App-Import, weil
das Image das erforderliche scripts-Paket nicht enthielt. Der Dockerfile
kopiert nun Runtime-Scripts und pyproject.toml; dessen tatsächlicher neuer
Container-Nachweis steht noch aus. Das Frontend
meldete 728 bestandene Fälle und einen zeitabhängigen Testfehler: Bestätigung
eines Guthabenbelegs und anschließendes Laden können gleichzeitig jeweils
eine Statusmeldung haben. Der korrigierte Test hält die tatsächliche
Read-only-Neuladung bewusst an und prüft Erfolg, Laden und genau einen
Finanzschreibbefehl getrennt; alle elf Guthabenjournaltests bestanden.

Die integrierte Betriebsübersicht samt unabhängiger Probe-Korrektur bestand
lokal 46 gemeinsame SQL-/Konsole-/Diagnostikfälle und zehn tatsächliche
SQLite-/Connection-/Transaktionsprüfungen. Das vollständige vereinte
Frontend einschließlich OCR bestand 763 Tests in 62 Dateien; Lint ist grün. Der Probe meldet
flüchtige SQLite-Binds ehrlich, erhält fremde Transaktionen und testet
ausschließlich Erreichbarkeit. Details: [Betriebsübersicht](G51_OPERATIONAL_METRICS_HANDOFF.md).

Der sichere Offline-Upgradeweg für bekannte unversionierte lokale
Rechnungsbelegschemata ist integriert; 19 gemeinsame SQL-/Upgrade-/Recovery-
Fälle bestanden. Details: [Rechnungsschema-Upgrade](INVOICE_SCHEMA_UPGRADE.md).
Der reale ältere Vorschau-Bestand mit additivem allocated_amount ohne
Allocation-CHECK wurde zunächst vor Veröffentlichung zurückgerollt. Der
geprüfte Anschluss erhält auch tatsächliche DESC-/Collation-/Expression-
Indizes und die ON-DELETE-Regeln historischer inline-FKs. Er wurde inzwischen
nach erneuter privater Bestandskopie erfolgreich offline angewandt.

CI #120 auf `ca3c923` ist abgeschlossen. Beide vollständigen Linux-Memory-
Läufe (Python 3.11/3.12) bestanden mit jeweils 2.881 Tests, 109 expliziten
Skips und 90 % Coverage. Auch der tatsächliche SMTP-Prozessfall bestand.
Frontend: 728 Tests in 59 Dateien, Lint, Audit und Build bestanden. Der private
PostgreSQL-Serverlebenszyklus bestand. Dies ist noch keine Gesamtfreigabe:
beide SQL-Läufe meldeten jeweils vier Fehler bei der strikten Vorprüfung
erhaltener Steuer-/Versandnachweise; PostgreSQL meldete drei Fehler beim
Auslesen binärer Vertrags-PDF-Blöcke; die Browserprüfung bestand 51 von 52
Fällen, mit einer veralteten Umfangsbehauptung in der Mieterauskunft.

Die anschließenden Korrekturen verweigern bekannte Reset-Konflikte vor dem
ersten Schreibbefehl und erhalten die Serialisierung gegen parallele neue
Entwürfe. SQLAlchemy verarbeitet PostgreSQL-Binärblöcke explizit als
LargeBinary, mit begrenzter Konvertierung von Treiber-Memoryviews. 23
Reset-/Recovery-Fälle bestanden (acht PostgreSQL-Skips), ebenso 47
Datenschutz-/Dateibelegfälle (drei PostgreSQL-Skips). Sieben tatsächliche
Edge-/SQLite-Abläufe bestanden auf dem korrigierten Stand, einschließlich
Vertragsassistenten-Initialisierung, Mieterauskunft und Speichern während
eines laufenden Autosaves. Die neuen PostgreSQL-Korrekturen benötigen ihren
echten CI-Nachweis. Unabhängige PostgreSQL-Gruppen laufen künftig auch nach
einem fachlichen Fehler einer anderen Gruppe; ein Fehler bleibt weiterhin
ein fehlgeschlagenes Gate.

22 gemeinsame Windows-Konsole-/Laufzeit-/Diagnostikprüfungen bestanden.
Umgeleitete cp1252-Konsolen geben Unicode sicher aus; UTF-8-Dateiprotokolle
erhalten die Originalzeichen und JSON-Konsolenprotokolle bleiben gültiges
JSON. Ruff und der erweiterte CI-Typcheck über 84 kritische Quellen bestanden.

Aktueller Integrationsstand vom 2. Oktober 2026: 727 Frontendtests in 59 Dateien
bestanden. Die integrierte Bankzuordnung, private Formularentwürfe und die
mobile Vertragsansicht bestanden gemeinsam acht tatsächliche Edge-/SQLite-
Browserabläufe. Der CI-Typcheck umfasst 82 kritische Quellen und ist lokal
grün; Ruff ist grün. Nach Integration der Rechnungszahlungsbelege bestanden
129 gemeinsame SQLite-Prüfungen (10 explizite Skips), darunter Migration,
Stornos, gemeinsames Guthabenbudget, Quellverlust-Wiederherstellung und die
korrigierten Billing-/Mietanpassungs-Testdaten. Zwei zusätzliche tatsächliche
API-Routerabläufe prüfen autorisierten Zugriff, genau einen Rechnungsbeleg und
keine zweite Cashbuchung mit Memory und SQLite.

Die vollständigen gepinnten Memory- und SQLite-Läufe auf `2b0e149` ergaben
jeweils 2.753 bestandene, 87 übersprungene und drei fehlgeschlagene Fälle.
Die inzwischen korrigierten historischen Credit-Schema-/Rechnungs-Fixtures
bestanden anschließend gemeinsam 16 Prüfungen. Die vorherigen 25 Fehler beim
Aufbau unzulässig doppelt belegter Vertragsfixtures sind in diesen beiden
Gesamtläufen beseitigt. Die neuen Codeänderungen benötigen ihre gemeinsame
CI-Abnahme; die gepinnten Läufe sind **keine grüne Gesamtfreigabe**.
Die neue Bankvorschlags-/Rechnungsoberfläche ist integriert: bewusste Auswahl,
erneute Prüfung nach Quelländerung, echte Teilzahlungsbelege und Stornos.
Eine neue Rechnung kann über die API nicht ohne Zahlungsbeleg als bezahlt oder
teilbezahlt angelegt werden; fünf gemeinsame tatsächliche API-/Bestandsfälle
bestanden mit Memory und SQLite. Übernommene historische Zahlbeträge bleiben
erhalten, und die Oberfläche unterscheidet sie von tatsächlich erfassten Belegen.
Ausführliche Beleg- und Upgradebeschreibung:
[Bankzuordnung](BANK_MATCHING.md).

Die Folgeprüfung CI #119 bestand Frontend und den tatsächlichen privaten
PostgreSQL-Serverlebenszyklus, meldete jedoch neue Integrationsbefunde: drei
Migration-/Rechnungs-Contractfälle, den Prozentzeichen-Import von PostgreSQL-
Verbindungsoptionen, einen Vertragsassistenten-Überlauf bei 360 Pixeln sowie
einen SMTP-Prozessbereinigungsfall unter Python 3.11. Diese Befunde werden
gezielt korrigiert; der neue Linux-Nachweis der SMTP-Prozessbereinigung
bestand inzwischen in beiden vollständigen Memory-Läufen von CI #120.
CI #119 ist keine Gesamtfreigabe. Der Prozentzeichen-Fix
bestand eine tatsächliche vollständige Migration mit Prozentzeichen im
SQLite-Dateipfad. Die Rückwärtsprüfung der Vollsicherung für das v1-
Zahlungsschema bestand mit Belegen und Originalbytes; zusammen mit bestehenden
Rechnungsschema-Prüfungen bestanden sieben Fälle.

Persönliche Formularentwürfe sind unter einem eigenen Feldkontext verschlüsselt,
bewusst wiederherstellbar und durch ursprüngliche Fachrevision und eigenen
Entwurfs-CAS geschützt. Vollbackup/Restore und privater Server-Restore prüfen
die gespeicherten Hüllen mit den tatsächlichen Archivschlüsseln vor Freigabe;
Teilimport und Zurücksetzen verweigern Verlust bestehender Entwürfe. 96
gemeinsame Recovery-/Sicherheitsfälle bestanden (ein PostgreSQL-Skip), inklusive
tatsächlich entfernter Quelle und neuem authentifizierten Prozess. Zwei frische
Migrationsfälle bestätigten vollständige x1-Kette, Datenbewahrung und Übernahme
einer bereits additiv angelegten Entwurfstabelle. Details: [Formularentwürfe](FORM_DRAFTS.md).

Die Mieterauskunft enthält zugeordnete Vertragsentwürfe, historische
Prüf-/Veröffentlichungsnachweise, ausgewählte Vorlagenversionen, PDFs und
Originalanlagen aus einem kohärenten Snapshot. Andere Personen und private
Formularinhalte werden nicht offengelegt. Die Profil-Anonymisierung benennt
weiterhin gespeicherte Belege ausdrücklich; sie behauptet keine vollständige
Löschung. 73 gemeinsame Datenschutz-/Entwurfsfälle bestanden, fünf tatsächliche
PostgreSQL-Varianten benötigen den CI-Service. Der tatsächliche Quellverlust-
Restore samt neuer authentifizierter Auskunft ist darin enthalten. Details:
[Vertragsnachweise in der Auskunft](G43_WIZARD_PRIVACY_HANDOFF.md).

Neu angelegte Demodokumente verweisen auf keine erfundenen Originaldateien.
Ihre Beschreibung erklärt den fehlenden Originalbeleg. Ein tatsächlich neu
erzeugter Demobestand bestand die verschlüsselte Vollsicherung/Wiederherstellung
unter Erhalt aller zehn Dokumentmetadaten. Alte Demo-Verweise werden durch
diese Seedkorrektur nicht automatisch verändert. Fehlende echte Dateiquellen
müssen vor einer als vollständig bestätigten Sicherung korrigiert werden.

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
