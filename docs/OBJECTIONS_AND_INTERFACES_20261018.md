# Widersprüche und Schnittstellenvorbereitung – Integration vom 18.10.2026

Ausgangspunkt ist der zuletzt geprüfte gemeinsame Stand `0f6e8222` auf
`codex/pro-integration-20261016`. Die Änderungen bauen auf dieser Hauptkopie auf.
Die historischen Assistenz-Arbeitskopien wurden ausschließlich gelesen.

## Übernommene und ergänzte Bestandteile

Die Widerspruchsentwürfe aus `pro-stage-billing-objections-20261017` und
`pro-stage-objection-decisions-20261017` wurden fachlich verglichen. Der stärkere
Originalschutz wurde übernommen und um aktuelle Berechtigungsprüfung,
hashgebundene Entscheidungsvorschau, dokumentierte Korrekturerstellung und
Schutz vor verspäteten UI-Antworten ergänzt. Die alte Migrationsbasis
`e1f0a1b2c315` wurde nicht in den aktuellen Graphen kopiert.

Die integrierten Steuer- und TEHA-Pakete aus den früheren PRO-Arbeiten bleiben
Grundlage. Neue Funktionen ersetzen weder Geldquellen noch bestehende
Verbindungs-, Geheimnis-, Transaktions- und Archivgrenzen. Drei abgegrenzte
Sol-6.1-Agenten mit hoher Denktiefe bearbeiteten Fachpakete; die zentrale
Integration prüft zusätzlich gemeinsame Migration, Vollbackup und Browserabläufe.

## Widerspruchsentscheidungen

- Eingang mit tatsächlichem Datum, ursprünglicher Begründung und optionaler
  Einzelabrechnung erfassen.
- Die Erfassung schreibt einen dauerhaften Befehlsbeleg im vorhandenen
  BusinessCommand-Journal atomar mit. Nach verlorener Erfolgsantwort erzeugt
  Wiederholen genau einen Widerspruch; geänderte Angaben unter derselben
  Kennung ergeben einen erklärten Konflikt. Heutige Rechte und Originale
  werden vor jeder Wiederholung erneut geprüft. Die Oberfläche lädt danach
  den heutigen Periodenstatus, auch nach einer zwischenzeitlichen Entscheidung.
- Eine ausdrückliche, begründete Ablehnung mit Akteur, UTC-Zeit, Revision,
  Wiederholungsschlüssel und geprüftem Originalhash speichern.
- Alternativ eine getrennte Korrekturfassung als Entwurf eröffnen. Alle damit
  beantworteten offenen Einwände erhalten nachvollziehbare Entscheidungen;
  bereits abgelehnte Einwände bleiben abgelehnt.
- Der Zustand vor dem Widerspruch wird nur bei belegtem Vorzustand
  wiederhergestellt. Unbekannte historische Zustände werden nicht erraten.
- Finanzposten, Forderungen, Originaltexte und tatsächliche Original-PDF-Bytes
  bleiben bei beiden Entscheidungen unverändert. Ein Korrekturentwurf löst
  keine automatische Zustellung oder Finanzbuchung aus.
- Dokumentierte Korrekturentwürfe werden weiter bearbeitet und nicht gelöscht,
  weil dabei ihre Nachweisverknüpfung verloren ginge.
- Die Detailakte öffnet per Zeilenklick und Tastatur, auch ohne Schreibrecht.
  Die echte 320-Pixel-Prüfung reproduzierte eine Dokumentbreite von 917 Pixeln:
  Widerspruchs-/Fassungstabellen scrollen jetzt in einem eigenen fokussierbaren
  Bereich; Dialogaktionen und Preflight-Kopf umbrechen innerhalb der Ansicht.

Neue additive Migration: `f018a1b2c001`, Vorgänger `f016a1b2c001`. Sie ergänzt
Entscheidungsfelder und einen eindeutigen Entscheidungsindex. Partielle oder
inkompatible Schemata werden ausdrücklich abgewiesen. Ein Downgrade verwirft
keine gespeicherten Entscheidungen oder belegten Vorzustände. Ohne neue
Nachweisdaten bleibt der Rückweg einschließlich der ursprünglichen offenen
Einwände möglich. Beide Fälle werden unter SQLite und PostgreSQL geprüft.
Der normale Programmstart migriert nicht.

Die gemeinsame Prüfung deckte außerdem einen zu eng an den bisherigen Kopf
gebundenen Übernahmepfad für ungestempelte Desktop-Datenbanken auf. Vollständig
geprüfte ORM-Familien werden jetzt nur bis zum bekannten additiven Stand
übernommen; historische Daten-Nacharbeiten und die echte Nachfolgermigration
laufen weiterhin. Bereits akzeptierte dezimale Geldspalten behalten ihre Werte
und Genauigkeit. Teilfamilien, geänderte Typen, Fremdspalten und fehlende
Schlüssel/Indizes werden vor der Übernahme abgewiesen. Die historische
Kommunikationsfamilie besitzt zusätzlich eine eingefrorene Schemaprüfung mit
erneuter Installation ihres Originalschutzes.

## WISO Steuer Windows, Fachjahr 2026

Die bestehende Jahressteuerbasis erhält optionale, versionierte manuelle
Zielobjekt-/Zielzeilenzuordnungen, vollständige Cent-Abstimmung, sichtbare Lücken
und Teiljahreshinweise sowie einen gespeicherten Übertragungsbogen. Der neutrale
ZIP-Download enthält bei ausdrücklich eingerichteter Vorbereitung auch das
Originalprofil, Prüfergebnis, CSV-Bogen und eine verständliche Abgrenzung.
Historische neutrale Profile behalten ihre Hashidentität und vier ZIP-Mitglieder.

Die tatsächlichen historischen Hausverwalteroriginale wurden erneut mit ihren
Prüfsummen verglichen. Ein vollständiger fachlicher Herstellerfeldvertrag und
ein echter WISO-Steuer-Zielimport sind damit nicht nachgewiesen. Es wird keine
XML-Datei mit geratenen Feldnummern erzeugt. Die offizielle Produktbeschreibung
bestätigt den Hausverwalter-Übernahmeweg, nicht unseren eigenen Serializer:
[Buhl Hausverwalter](https://www.buhl.de/software/wiso-hausverwalter-365/).

Die installierte Hausverwalter-Anwendung wurde über den dokumentierten
Computer-Use-Skill angesprochen. Beide Startversuche (zurückgegebene App-ID und
bestätigter EXE-Pfad) meldeten `launched app did not expose a targetable window`;
die erneute Fensterliste enthielt kein WISO-Fenster. Neue isolierte
Hersteller-Änderungsexporte wurden in dieser Runde deshalb nicht erzeugt.
WISO Steuer Windows ist weiterhin nicht als verfügbare Zielinstallation belegt.

Details: [WISO-Vorbereitung](WISO_PREPARATION_20261018.md).

## TEHA

Direkte Folgeaktionen verbinden empfangenes Dokumentverzeichnis mit genauem
Originalempfang, externe Periode mit Dokumentliste und Techniktermin mit
Nutzerempfang. Sie bereiten lokale Läufe vor; ein lesender Dispatch bleibt ein
gesonderter ausdrücklicher Schritt.

Lokale Rückpakete werden vollständig als hashgebundene private JSON-Anhänge
heruntergeladen. Sie bewahren den eingefrorenen Stand und ergänzen heutige
Quellenprüfung, dezimale Kostensummen, Mapping-/Quellkonflikte und Portalnachweise.
Auch nach Löschung einer lokalen Quelle bleiben historische Pakete erreichbar.

Die öffentliche Portaldatei wurde am 18.10.2026 anonym gelesen; weder Login noch
Provider-API-Aufruf erfolgten für diese Beobachtung. Quelle:
`https://kunden.socs.ws/assets/index-CjRzd8_M.js`, 1.274.312 Bytes, SHA-256
`328ac6c642b9892e7604ee67cf4e3c0d83b0b5f8700795561ec01b7b94bfa618`,
Last-Modified 12.10.2026. Der redigierte Katalog beschreibt 78 statische
Aufrufstellen. Roh-JS und Arbeitskatalog bleiben unter ignorierten Artifacts.

Die optionale Folgeauftrag-Vorschau bindet `Altauftrag` an `auftragNummer` und
erhält ausdrücklich ausgewählte Nutzerquellen. Sie trennt Termin-ID,
Auftragsnummer und Nutzer-IDs. Die Gleichheit der Nutzer-IDs aus Terminabruf und
offener Auftragsnutzerliste ist noch nicht authentifiziert abgeglichen. Diese
konkrete Grenze ist in Vorschau, Prüfpaket und Dokumentation ausgewiesen.

Es gibt weiterhin keinen freigegebenen Schreibtransport. Statische Endpoints
beweisen keine Kontoberechtigung, vollständigen Laufzeitvertrag,
Wiederholungssicherheit oder tatsächlich ausgeführten Auftrag. Es wurde keine
Portal-Schreibaktion, Nachricht oder Steuerübermittlung ausgeführt.

Details: [TEHA-Vorbereitung](TEHA_LOCAL_PREPARATION_20261018.md).

## Gemeinsame Prüfung und Freigabe

`scripts/run_daily_browser_qa.py --suite interfaces` startet ausschließlich eine
neue eigene SQL-Testinstallation auf einem freien Loopbackport, erzeugt
synthetische Daten und beendet die eigenen Prozesse. Der Seed verwendet einen
lokalen FixtureProvider; echte TEHA-Netzwerkaktionen werden nicht ausgeführt.
Der Browser blockiert externe Origins.

Die Abläufe prüfen tatsächliche Downloads, Centwerte, historische Profile,
Folgeauftragkennungen, Dokumentempfangsvorbereitung, Eingangsdatum,
Einzelabrechnung, begründete Ablehnung und getrennte Überarbeitung einschließlich
bytegleicher Original-PDFs sowie 320/360/1440-Pixel-Ansichten. Derselbe Ablauf
läuft als verpflichtender Teil des Dokument-/Browserjobs in GitHub CI.
Die Erfassungsprüfung unterbricht ausdrücklich eine bereits erfolgreiche
POST-Antwort und wiederholt denselben Dialogbefehl; die Liste muss danach genau
einen Eintrag enthalten. Der Gegenversuch auf dem ersten Kandidaten erzeugte
zwei Einträge und wurde vor der Auslieferung korrigiert.

Die genaue abschließende Quell-, Windows-Paket-, CI- und Installationsfreigabe
wird separat mit Head/SHA-256 und tatsächlichen Laufverzeichnissen dokumentiert.
Agenten-Teilergebnisse und Arbeitsbaumprüfungen ersetzen diese Freigabe nicht.
