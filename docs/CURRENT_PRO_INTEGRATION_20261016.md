# Gemeinsame Integration der PRO-Arbeitsstände, 16. Oktober 2026

Dieser Zweig führt die vorhandenen Fachpakete zusammen. Er ist ein eigener Entwicklungsstand; die laufenden Installationen auf Port 8765 und 8000 wurden dafür nicht geändert. Ein erfolgreicher Einzeltest ist keine Freigabe des Gesamtprodukts oder eines externen Anbieters.

## Herkunft und Auswahl

Ausgangspunkt ist der PRO-Gesamtstand `3017c33034722741bd8d2afc069d10dc76372f59`, der seinerseits auf dem zuvor geprüften Stand `04021da57e009419ae8d07346ad890fdabad6533` aufbaut. Vor jeder Übernahme wurden 22 PRO-Arbeitsbäume inventarisiert und 598 geänderte Dateifassungen mit Hashes gesichert. Der Gesamtarbeitsbaum lieferte 89 zusätzliche Dateien bzw. Dateifassungen. Quellen und ursprüngliche Arbeitsbäume bleiben erhalten.

Das maschinenlesbare Inventar und unveränderte Quellkopien liegen lokal unter `artifacts/pro-inventory-20261016`. Das Inventar enthält Commit, Branch, Änderungsstatus, Dateigröße und SHA-256; ein Dateistand wird dadurch nicht nachträglich als ausgeliefert bezeichnet.

| Quelle | Übernahmeentscheidung |
| --- | --- |
| `pro/interfaces-20261015` | Verschlüsselte Verbindungsspeicherung, Nachweise, Wiederherstellung und Seitenverfahren bereits im Ausgangsstand enthalten. |
| `pro/full-handover-20261016` | Neuester gemeinsamer Code als Grundlage; zusätzliche Dokument- und TEHA-Dateien übernommen. |
| `pro-finish-bank-20261016` | Über die Bank-Commits im Gesamtstand enthalten: Originaldateien, CSV/MT940/CAMT, kontrollierte Übernahme, FinTS-Aufträge und Zuordnungen. Keine ältere Kopie darübergelegt. |
| `pro-finish-finance-20261016`, Finanz-Stage | Bestehende Gesamtintegration beibehalten: Restpostenzuordnung, Periodenbericht und Liquiditätsszenarien. |
| `pro-finish-tax-20261016`, Steuer-Stage | Vorhandene versionierte DATEV-/Jahresaufbereitung beibehalten. Neutraler Export wird nicht als WISO-Herstellerimport umbenannt. |
| `pro-finish-communication-20261016`, Kommunikations-Stage | Bereits integrierte dauerhafte MIME-Outbox und IMAP-Empfang weiterverwendet; persönlicher Hinweisversand darin ergänzt. |
| `pro-finish-daily-20261016` | Gesamtintegration für persönliche Hinweise, Einstellungen, Nummernreservierung und Sitzungsfamilien ergänzt und nachgeprüft. |
| Dokument-Finish und Dokument-Stage | Native DOCX-Arbeitssitzungen, PDF-Ebenen/-Ausgaben, Rechnungsentwürfe und Übergabenachweise integriert; reale optionale Engines gesondert geprüft und korrigiert. |
| TEHA-Finish und TEHA-Stage | Neueren Providervertrag und Empfangs-/Publikationspfad beibehalten; ältere Ergebnisdecodierung nur nach inhaltlicher Prüfung übernommen. |
| Kanal-Finish und Kanal-Stage | WhatsApp, Post und Immobilienportale gezielt übernommen. Konfliktmarkierungen und ältere vollständige Seitenkopien der Stage nicht übernommen. |
| `pro-finish-platform-20261016` | S3-Speicherbindung, portable Sicherung, Plugin-Datenlebenszyklus, geschlossene Aktionsfassade und Registrierungsquote per Dreifachabgleich übernommen. Neuere Bank-/Steuer-/Kommunikations-/TEHA-Prüfungen im Backup erhalten. |
| Finish-Arbeitsbäume für Billing, Ownership, Plans, Operations, Portal | Zum Inventarzeitpunkt keine eigenen Änderungen gegenüber ihrem Ausgangscommit. Die Benennung eines Arbeitsbaums ist kein Implementierungsnachweis. Bestehende ältere Hauptmodule bleiben erhalten; diese zusätzlichen Aufträge bleiben gesondert zu bearbeiten. |

## Zusammengeführte Funktionen

### Dokumentarbeit

- Ein Upload wird vor der Bearbeitung als unveränderliche Originalfassung gesichert. Bearbeitung erzeugt neue Fassungen oder abgeleitete Dokumente.
- Native DOCX-Bytes, private Arbeitssitzungen, serverseitige Zwischenstände, Konfliktvergleich und Wiederholungsbelege. Text, Tabellen, Bilder, Kopf-/Fußzeilen, Kommentare und Änderungsspuren werden am exportierten OOXML kontrolliert.
- PDF-Anmerkungsebenen mit Hervorhebung, Kommentar, Text, Stempel, Freihand und gezeichneter/Bild-Unterschrift. Originalbytes bleiben erhalten.
- PDF-Ausgaben für Einbetten, Seitenreihenfolge, Teilen, Zusammenführen, Drehen, Formulare, Ausschnitt, Ersetzung/Schwärzung, Optimierung und lokale OCR. Schwärzung ist eine gesonderte destruktive Ableitung; Zuschneiden behauptet keine Entfernung vertraulicher Inhalte.
- OCR-Rechnungsvorschläge verwenden die bestehende Rechnungsprüfung; Originalfotos und Rückscans werden einem Übergabeprotokoll zugeordnet.
- Der native PDF-Prozess läuft außerhalb des Webservers; Veröffentlichung prüft Quelle und Rechte nach der Verarbeitung erneut. Der Windows-Launcher besitzt einen eigenen internen Worker-Einstieg ohne Serverstart oder Zugriff auf das Anwenderprofil.

Der lokale DOCX-Baustein liegt unter `optional/document-editor`, sein Lockfile bleibt getrennt. Für einen reproduzierbaren Windows-Build kann `scripts/build_exe.py --with-document-tools` den lokalen Editor vor dem Hauptfrontend bauen. PyMuPDF ist unter `requirements-documents-optional.txt` festgelegt. Optionaler Umfang und Bibliothekslizenzen sind dokumentiert; eine identische Nachbildung aller Word-/Foxit-Funktionen oder kryptografische Signaturprüfung wird nicht behauptet.

### Persönliche Hinweise und Einstellungen

- Ein Hinweis führt über eine überprüfte Quelle zum Fachvorgang. Der persönliche Gelesen-/Archivbeleg folgt der erfolgreichen Ankunft; die fachliche Quelle wird dadurch nicht erledigt.
- Persönliche Hinweis-E-Mails entstehen ausschließlich nach ausdrücklicher Vorschau und Freigabe in der vorhandenen Outbox. Adresse, Rechte, Quellstand, Ruhezeiten und Kanalwahl werden bis unmittelbar vor der Datenübergabe erneut geprüft.
- Ein verlorenes Versandresultat führt zum Abgleich; es löst keine automatische Wiederholung einer möglicherweise bereits ausgeführten externen Aktion aus.
- Einstellungsänderungen sind revisionsgebunden. Eine verspätete Speicherantwort entfernt keinen inzwischen neu bearbeiteten Entwurf. Sitzungswiderruf und Memory-Lesezugriffe dürfen keine später zurückgerollten Zwischenstände beobachten.
- Die Bankimportmaske verwendet die gespeicherte Formatvorlage beim Öffnen. Späte Standardwerte überschreiben weder Eingaben noch die Zuordnung eines wieder geöffneten Imports.

### Schnittstellen und Betrieb

- TEHA: Empfangsläufe, lokale Zuordnung, vollständige Rohfelder, Vorschau, Originalarchiv, Publikationsbelege und wiederaufnehmbare Abschnitte. Rückübertragungen sind an tatsächlich belegte Portalverträge gebunden.
- WhatsApp: explizite Vorlagen-/Medienaufträge, opt-in-bezogene Eingaben, signierter Webhook, monotone Zustellzustände, persönliche Zuordnung empfangener Nachrichten. Anbieterannahme und Zustellung bleiben unterschiedliche Zustände.
- IS24: OAuth1, Objekt-/Bildübertragung, Veröffentlichung, Abgleich und Deaktivierung. OpenImmo/FTPS: Dateitransfer mit eigenem Status; Transfer wird nicht als bestätigte Portalveröffentlichung ausgegeben.
- Post: vorbereiteter Brief, extern gekaufter Frankaturnachweis und tatsächlicher Einwurf bleiben getrennte Schritte. Aktenwerk nutzt dauerhafte Quell-/Hashbelege und blockiert blinde Wiederholungen unklarer Übertragungen.
- S3-kompatible Ablage bindet Originale an Speicherort und Hash. Vollsicherungen übernehmen referenzierte entfernte Originale lokal und prüfen sie vor der Veröffentlichung einer Wiederherstellung.
- Restore prüft die Nachweise für Verbindungen, Bank, Steuer, Kommunikation, TEHA und Kanäle mit den archivierten Schlüsseln. Neue Kanaldateien werden blockweise gehasht; nicht das gesamte Dokumentarchiv wird in einen gemeinsamen Bytepuffer geladen.
- Ein JSON-Teilbestand darf verschlüsselte Schnittstellen-/Kommunikationsnachweise nicht ersetzen. Der vollständige, dafür versionierte Dokument-JSON-Pfad bleibt erhalten.
- Vertrauenswürdige Plugins können deklarierte eigene JSON-Daten kontrolliert migrieren und wiederherstellen. Dies ist keine Sandbox für fremden Python-Code.

## Integrationsfehler, die korrigiert wurden

- Mehrere Alembic-Heads durch eine additive Merge-Revision `f016a1b2c001` vereinigt; vorhandene Revisionskennungen, Eltern und Upgrade-Definitionen bleiben unverändert.
- Die PRO-Downgradehandler verweigerten teilweise sogar bei vollständig leeren neuen Tabellen jede Rücknahme. Sie prüfen jetzt unter einer Schreib-/Schemasperre zuerst sämtliche betroffenen Familien: vorhandene Nachweise verhindern die Rücknahme, leere Zusatzschemas lassen sich entfernen. Der Plattformentwurf durfte zuvor sogar vorhandene Speicher-/Plugindaten löschen; auch dort verhindert die Vorprüfung Datenverlust. Historische fachliche Downgradeprüfungen bleiben dadurch ausführbar.
- TEHA-Importzyklus durch verzögertes Laden des Integrationsmanagers behoben; Kanalmodelle und geschützte/öffentliche Router registriert.
- Akteurfilter kollidierte mit einem gleichnamigen Paging-Parameter; persönliche und geschäftliche Outbox-Seiten funktionieren nun getrennt.
- Sitzungswiderruf, Memory-Leser und Audit-Rollback verwenden passende Sperren. Audit-Leseergebnisse verändern nicht versehentlich das interne Journal.
- Portable Runtime-Dateien werden auch bei unverschlüsselten lokalen Sicherungen korrekt wieder eingelesen; fehlende Referenzdateien verhindern einen falschen Erfolgsstatus.
- Zugangsdatenähnliche Queryparameter einschließlich `hub.verify_token`, `apiKey` und Signaturen werden vor der strukturierten Request-/Fehlerprotokollierung maskiert.
- Neue Kanalansichten laden bei Bedarf und behandeln unvollständige Antworten als Fehler, ohne die normale Nachrichtenansicht zum Absturz zu bringen.
- PDF-Dialoghöhe, eindeutige Werkzeugnamen und tatsächlicher Seitenaufbau werden im Browser geprüft. Der DOCX-Toolbar wird ausdrücklich konfiguriert und nach dem Speichern weiter geprüft.
- Nach erfolgreichem Formularspeichern wird die Browser-Verlassen-Warnung unmittelbar entfernt; fehlgeschlagene Speicherungen behalten den Schutz.
- Ungestempelte aktuelle ORM-Datenbanken werden nur am ausdrücklich geprüften Head übernommen. Fehlende historische Zugriffs-/Jobtabellen durchlaufen weiterhin die bisherigen Übernahmen und Datenrückfüllungen; Schutztrigger werden auch an bereits vorhandenen Tabellen installiert. Ein reines Stempeln darf historische Benutzerrechte oder Miethistorien nicht überspringen.
- Eine vollständige PostgreSQL-Wiederherstellungsprobe inventarisiert die Datei-/Schlüsselreferenzen aus der tatsächlich wiederhergestellten Datenbank und prüft die ausgepackten Originaldateien. Ein lesbarer Dump allein genügt nicht für den Erfolgsstatus.
- Alte Tests erwarten nun die vorgesehenen Sicherheitsverträge: bestätigte Bankvorschau, persönliche Lesebelege, gesperrte Originalüberschreibung, fremde S3-Buckets und vollständig konfigurierte Kanalzugänge. Der Test für Rechnungsmanipulation prüft zusätzlich eine absichtliche Dateiveränderung außerhalb der Anwendung. Die Prüfungen wurden nicht durch Lockerung dieser Schutzregeln passend gemacht.
- Direkt aufgerufene Testdienste geben ihre klassische SQL-Lesesitzung an der Testgrenze zurück; Verbindungstests prüfen weiterhin vor diesem Aufräumen, dass ihre eigenen HTTP-Anfragen keine Verbindung behalten. In eine neue Speicherdatenbank zurückgespielte Dokumenttests verwenden dort ein passendes, getrenntes Benutzerbackend.
- FinTS ist Teil der vollständigen Entwicklungs-/CI-Umgebung. Windows-Bundlewerkzeuge sind festgelegt; installierte native Dokument-/Bankmodule werden ausdrücklich in die Importanalyse aufgenommen.
- Der reale 100.000er-Lauf deckte eine Restbetragsregression auf: Währungs-/Vertragseltern wurden für jede einzelne Forderung erneut geladen. Die gemeinsame Auswertung hält diese Daten jetzt ausschließlich innerhalb ihres eigenen, berechtigten Lesevorgangs vor. Zusammenfassungen berechnen denselben dezimalgenauen Restbetrag ohne unnötige Serialisierung aller Einzelnachweise. Die vollständige Altersliste behält ihre Einzelbelege. Ein SQL-Abfragebudget und unabhängige Betragsorakel sichern den Pfad ab.
- Einstellungsentwürfe werden synchron am Eingabeereignis gesichert. Späte Initialeffekte überschreiben keine neue Eingabe. Bei Objektwechsel werden die bearbeitbaren Karten der alten Immobilie sofort entfernt, bis die Antwort für das gewählte Objekt vorliegt. Ladezustand, fehlgeschlagene Antwort und echter Leerbestand sind getrennt; fehlerhafte Sitzungsantworten führen zu einem wiederholbaren Fehler statt einem Seitenabsturz.
- Neue echte Browserprüfungen sichern Entwurfswiederaufnahme, gespeicherte Tabellendichte, Navigation zum exakten Benachrichtigungsvorgang, persönlichen Archivbeleg, fehlende Quellen, Wiederöffnen und mobile Einstellungen. Sie laufen als Teil des nativen Dokument-/Browser-CI-Jobs auf einer eigenen synthetischen Installation.
- Native PDF-Dialogaktionen umbrechen auch mit Linux-Schriftmetriken bei 320 Pixeln. Die Schließen-Aktion behält einen erreichbaren, einzeiligen Knopf. Browserfehler bewahren Screenshot und Layoutdiagnose; die Windows-Prüfausgabe verkraftet Unicode-Zeichen unabhängig von der Konsolencodepage.
- Die alte Benachrichtigungsliste lädt für das Dashboard nur die angeforderte Seite statt sämtliche persönlichen Hinweiskarten. Filter und seitenübergreifende Snapshotprüfung bleiben erhalten. Ein Test mit 601 Hinweisen prüft Fenster und kombinierte Filter unabhängig in SQLite und Memory.
- Der zusammenhängende Verwaltungs-Stresstest verwendet die kontrollierte Bankübernahme: vollständige Vorschau, ausdrückliche Bestätigung und seitenweise Buchungsnachweise. Er umgeht den neuen Freigabevertrag nicht über einen alten Direktimport.
- Der zusätzliche Verwaltungsablauf zeigte einen zweiten Abfrageengpass: Die Reservierungsprüfung von Zahlungen las jede Buchung einzeln, selbst wenn keine Ausgleichsbelege existierten. Sie validiert ihre Quellen jetzt in begrenzten Sammelabfragen unter der aktuellen Objektberechtigung. Ein unabhängiger SQL-Test mit 1.001 Zahlungsquellen, fehlenden IDs und entzogenen Rechten sichert Kosten und Berechtigungen ab. Der Persistenz-Stresstest vergleicht geschützte Familien über einen schreibgeschützten Fingerabdruck seiner eigenen markierten Testdatenbank; der öffentliche JSON-Export behält seine vollständige Sicherung erfordernde Ablehnung.

## Abnahme und ehrliche Grenzen

Die vollständige SQL-Matrix deckte zusätzlich zwei veraltete Prüfannahmen auf: Der Banktest kennzeichnete eine bereits vollständige ORM-Datenbank noch als ältere Bank-Einzelrevision; seine Fixture verwendet nun die tatsächlich initialisierte aktuelle Revision. Außerdem muss die testweite Rückgabe direkter Lesesitzungen nach sämtlichen Fixture-Finalizern und deren Monkeypatch-Wiederherstellung laufen. Die HTTP-Verbindungstests behalten ihre unveränderten Null-Verbindungs-Assertions innerhalb des Tests. Diese Nachbesserungen betreffen die Prüfumgebung; die abschließende Matrix wird dafür erneut ausgeführt. Die tatsächlichen Installationskopien hatten den regulären Upgradepfad bereits ohne Inhaltsänderungen bestanden.

Prüfungen schreiben isolierte Laufverzeichnisse unter `artifacts/pro-tests`, mit Quellhashes, Befehlsauswahl, JUnit und Ergebnis. Eine rote Vorprüfung bleibt als solche erhalten. Die abschließende Freigabe muss sich auf den dann eingefrorenen Commit beziehen.

Bereits ausgeführt wurden echte lokale PDF-/OCR-Engineprüfungen, native DOCX-Browserbearbeitung mit unabhängigem OOXML-Vergleich, isolierte SQLite-Paketprüfungen, ein wieder gestarteter ASGI-Prozess aus einer portablen Sicherung und neue native PostgreSQL-Konkurrenztests. Browserbilder werden visuell geprüft; ein bloßer Screenshot-Dateiname gilt nicht als Sichtprüfung.

Zwei lokale Großbestandsläufe am unveränderten Quellstand `fde7bc85` sind erfolgreich: 100.000 beziehungsweise eine Million Buchungen, jeweils 72.000 Forderungen über 240 Monate und zehn gleichzeitig aktive Benutzer. Der Millionenlauf verifizierte alle 40 bestätigten Schreibvorgänge, 1.002 HTTP-Anfragen ohne HTTP-Fehler und vollständige Suchtexporte mit mehr als 10.000 Treffern. Der 100.000er-Lauf prüfte zusätzlich das vollständige portable Backup mit Anwendungsstart und Originaldateivergleich nach der Wiederherstellung. Dies ist ein dokumentierter lokaler Kapazitätsnachweis, keine Garantie beliebiger Hardware oder aller fachlichen Langzeitabläufe. Die vollständigen JSON-Berichte liegen unter `artifacts/scale-finance-search`.

Noch gesondert nachzuweisen sind insbesondere tatsächliche Anbieter-Schreibvorgänge, Bankfreigaben/TAN-Verfahren, WISO-Steuer-Zielimport 2026, unabhängige Office-Paginierung komplexer Dokumente, LibreOffice-Konvertierung sowie die abschließende vollständige Produkt-/Coverage-/Installationsabnahme des letzten Commits. Die unabhängigen vollständigen Prüfläufe laufen im Integrationszweig weiter; der abschließende lokale Abnahmebericht benennt deren tatsächliches Ergebnis und den geprüften Commit. Es wurde keine reale E-Mail, WhatsApp-Nachricht, Portalveröffentlichung oder Postbestellung zur Abnahme ausgelöst.
