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

## Abnahme und ehrliche Grenzen

Prüfungen schreiben isolierte Laufverzeichnisse unter `artifacts/pro-tests`, mit Quellhashes, Befehlsauswahl, JUnit und Ergebnis. Eine rote Vorprüfung bleibt als solche erhalten. Die abschließende Freigabe muss sich auf den dann eingefrorenen Commit beziehen.

Bereits ausgeführt wurden echte lokale PDF-/OCR-Engineprüfungen, native DOCX-Browserbearbeitung mit unabhängigem OOXML-Vergleich, isolierte SQLite-Paketprüfungen, ein wieder gestarteter ASGI-Prozess aus einer portablen Sicherung und neue native PostgreSQL-Konkurrenztests. Browserbilder werden visuell geprüft; ein bloßer Screenshot-Dateiname gilt nicht als Sichtprüfung.

Noch gesondert nachzuweisen sind insbesondere tatsächliche Anbieter-Schreibvorgänge, Bankfreigaben/TAN-Verfahren, WISO-Steuer-Zielimport 2026, unabhängige Office-Paginierung komplexer Dokumente, LibreOffice-Konvertierung sowie die abschließende vollständige Produkt-/Coverage-/Großbestands-/Installationsabnahme. Die unabhängigen vollständigen Prüfläufe laufen im Integrationszweig weiter. Es wurde keine reale E-Mail, WhatsApp-Nachricht, Portalveröffentlichung oder Postbestellung zur Abnahme ausgelöst.
