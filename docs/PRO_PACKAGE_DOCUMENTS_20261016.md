# Dokumentpaket – Entwicklungsübergabe

Arbeitsstand: in Entwicklung, keine Integrations- oder Releasefreigabe. Checkout und Zweig: `pro-finish-documents-20261016` / `pro/finish-documents-20261016`. Ausgang: `c16e0970`. Keine Commits, Installationen oder Provideraktionen.

## Tatsächliche TOOL MATRIX vor Implementierung

Jede Zeile ist ein eigener Abnahmepunkt. „Offen“ bedeutet keine zugesagte Funktion im Ausgangscode. Der vorhandene Viewer bleibt erhalten. Ein Browsereditor-Roundtrip ist erst nach Installation und realem Bibliothekstest nachgewiesen.

| Werkzeug | Tatsächlicher Ausgang | Umsetzung / erforderlicher Nachweis |
|---|---|---|
| Absatzformat | offen | optionaler lokaler OOXML-Editor, Browserprüfung offen |
| Zeichenformat | offen | OOXML-Editor |
| Überschriften | offen | OOXML-Editor |
| Listen | offen | OOXML-Editor |
| Einzüge | offen | OOXML-Editor |
| Tabellen | offen | OOXML-Editor; lange/verschachtelte Tabellen prüfen |
| Bilder | Viewer vorhanden, DOCX offen | OOXML-Editor; Bildbytes/Verankerungen prüfen |
| Links | offen | OOXML-Editor; externe Beziehungen sicher behandeln |
| Seitenformat und Ränder | offen | OOXML-Editor |
| Kopfzeilen | offen | OOXML-Editor; unterschiedliche Abschnitte prüfen |
| Fußzeilen | offen | OOXML-Editor |
| Seitenzahlen | offen | OOXML-Editor |
| Seitenumbrüche | offen | OOXML-Editor |
| Fußnoten | offen | OOXML-Editor, Unterstützung praktisch nachweisen |
| Inhaltsverzeichnis | offen | OOXML-Editor, Aktualisierung praktisch nachweisen |
| Suchen | offen | OOXML-Editor |
| Ersetzen | offen | OOXML-Editor |
| Kommentare | offen | OOXML-Editor |
| Änderungsverfolgung | offen | OOXML-Editor |
| Änderungen annehmen | offen | OOXML-Editor |
| Änderungen ablehnen | offen | OOXML-Editor |
| Rückgängig | offen | OOXML-Editor |
| Wiederholen | offen | OOXML-Editor |
| Vorlagen | vorhandene Fach-PDFs, freier Editor offen | archivierte DOCX als Ausgangsvorlage |
| Autosave | private Formularentwürfe vorhanden, DOCX offen | serverseitige revisionsgebundene DOCX-Zwischenstände |
| Wiederherstellung nach Absturz | DOCX offen | gespeicherte Sitzung + Zwischenstand |
| Zusammenarbeit / Konflikte | DOCX offen | zwei Sitzungen, erwarteter Archivkopf; kein behauptetes Echtzeit-CRDT |
| DOCX-Import/Export | Upload/Download vorhanden | native OOXML-Bytes; keine HTML-Konvertierung |
| PDF-Export aus DOCX | offen | lokale Konvertierung fehlt; darf nicht durch HTML-Druck ersetzt werden |
| PDF-Markierung | offen | versionierte Ebene mit Originalbezug |
| PDF-Hervorhebung | offen | Seite / unrotierte PDF-Punkte / Rotation |
| PDF-Kommentar | offen | Ebene + Autor/Zeit |
| PDF-Textnotiz | offen | Ebene |
| PDF-Freihand | offen | Punktzüge |
| PDF-Stempel | offen | Ebene |
| Gezeichnete Unterschrift | offen | Ebene; keine digitale Signaturbehauptung |
| Bildunterschrift | offen | eingebettete Bildbytes; keine digitale Signaturbehauptung |
| Unterschriebene Rückfassung | offen | neue archivierte Identität und Quellbezug |
| Abgeflachte Ausgabe | offen | abgeleitetes PDF, nie Originalüberschreibung |
| Echte Schwärzung | offen | Text/Bild/Vektor/Metadaten entfernen; unabhängige Inhaltsprüfung erforderlich |
| Digitale Signatur erkennen | offen | Signaturfelder erkennen, kryptografische Gültigkeit „nicht geprüft“ |
| PDF drehen | offen | lokale PDF-Engine |
| PDF Seiten einfügen | offen | archivierte berechtigte Zusatzquelle |
| PDF neu ordnen | offen | explizite Seitenfolge |
| PDF Seiten entnehmen | offen | neuer Export |
| PDF zusammenführen | offen | alle Quellen autorisieren |
| PDF teilen | offen | separate neue Exportidentitäten |
| PDF zuschneiden | offen | Seitenrechteck |
| PDF Formulare | offen | Feldwerte, Signaturfelder nicht überschreiben |
| PDF OCR-Textschicht | OCR-Text separat vorhanden | lokale OCR-Engine/Sprachdaten erforderlich |
| PDF Größenoptimierung | offen | verlustfreie Bereinigung/Kompression |
| PDF Inhaltsbearbeitung | offen | ausdrücklicher Modus: Rechteck entfernen und neuen Text einsetzen; kein Word-Reflow |
| Geschützte PDF | bislang Viewer | verschlüsselte Eingaben verweigern, kein Passwort persistieren |
| Beschädigte PDF/DOCX | bislang Upload | Strukturprüfung, niemals stille Reparatur/Originalersetzung |
| Lange Dokumente / Sonderzeichen | Viewer vorhanden | OOXML-Paket-Erhaltung + reale visuelle Prüfung |
| Originalarchiv gewöhnlicher Uploads | nur erzeugte Fachoriginale | bestehendes blockweises unveränderliches Archiv erweitern |
| OCR → Rechnungsentwurf | Vorschläge vorhanden | bestätigte Feldzuordnung, exakte Beträge, idempotente Invoice; keine Freigabe/Buchung |
| Übergabefotos / Rückscan | externe Dateien veränderlich | eigene archivierte Dokumentidentität + Bindung an Protokoll |

## Komponenten und Voraussetzungen

Die vorgegebene Prüf-Pythonumgebung enthält `reportlab` und `Pillow`, aber **kein** `PyMuPDF`, `pypdf` oder `python-docx` (direkt mit `find_spec` geprüft). Sie wird nicht verändert. Keine neue globale Abhängigkeit.

SuperDoc ist optional zu isolieren; Projektlizenz unverändert. Offizielle Dokumentation: https://docs.superdoc.dev/editor/ und https://docs.superdoc.dev/resources/license/ (AGPLv3 oder kommerziell; keine Lizenz gekauft). Der ältere Import/Export-Link leitet auf v1-Dokumentation um; v1- und v2-Verträge dürfen nicht vermischt werden. Native OOXML-Speicherung ist keine Behauptung vollständiger visueller Formatgleichheit.

## Migration

Implementiert: `d73f2b9a041c → e160a1b2c306`. Additiv, keine Umschreibung veröffentlichter Migrationen. Paketdaten und Archiv bleiben in der bestehenden Datenbank, kein zweites Finanzbuch.

## Implementierter Stand – keine vollständige Paketabnahme

### Bestehende Anwendung und deutsche Bedienung

`Documents.jsx` öffnet die Werkzeuge über die Zeilenaktion oder `?tool_id=<document_id>`. Die Parteiakte verlinkt denselben Weg. Der bestehende Originalbetrachter bleibt erhalten; `PdfPreview.jsx` erhielt lediglich eine optionale Koordinatenebene. Im Übergabeprotokoll bietet `HandoverEvidence.jsx` einen direkten Upload von Originalfotos/Rückscans einschließlich Quellenprüfung, exakter Dateiprüfsumme, Wiederholungsauftrag, paginierter Nachweisliste und Originaldownload.

Die Werkzeuge bieten Archivierung, Sitzungen, native DOCX-/UTF-8-Bearbeitung, private Zwischenstände, Versionsdownloads, Quellenvergleich und ausdrücklich bestätigtes Fortsetzen auf neuer Basis. Eine Speicherung sichert die ausgehenden Bytes zunächst privat, bevor sie gegen den gemeinsamen Archivkopf veröffentlicht. Fehler behalten Eingaben und den exakten Wiederholungsauftrag. Ein Entwurf kann im Verlauf wieder geöffnet werden. Die Oberfläche verwendet `api`, `captureSession` und den bestehenden Dialog-/Rechtevertrag.

Die Rechnungserkennung läuft ausdrücklich lokal (`use_ai=False`) auf den archivierten Bytes. Der Erkennungsauftrag und sein Ergebnis/Fehler bleiben gespeichert und können erneut ausgeführt werden. Vorschläge zeigen die Quelle und verlangen bestätigte Herkunft je Kernfeld. Veraltete Erkennung wird gekennzeichnet. Die Übernahme verwendet **die bestehende** `invoice_review.start_review`-Transaktion mit VAT-Zeilen, Skonto, Fälligkeit und Dublettenprüfung. Ergebnis: Invoice `open`, Review `received`; keine Freigabe, Zahlung oder Buchung. Ein Beleg wird nur einmal übernommen, auch mit neuem Schlüssel. Mehrere Steuerzeilen sind im Formular möglich.

### Tatsächliche Tool-Matrix nach Implementierung

Die vollständige Ausgangsmatrix oben bleibt als Soll-/Ausgangsnachweis erhalten. Für **jede dort aufgeführte Word-Funktion** gilt derzeit: native OOXML-Serverstrecke vorhanden; lokale SuperDoc-Anbindung geschrieben; konkrete Bedienung, Layout und Formatübernahme durch die tatsächliche Bibliothek **nicht abgenommen**. Das betrifft ausdrücklich auch Fußnoten, Inhaltsverzeichnis, Annahme/Ablehnung von Änderungen, Kopf-/Fußzeilen, Seitenzahlen, Vorlagen und alle Formatwerkzeuge. Es wird keine HTML-Rundreise und keine vollständige visuelle Formatgleichheit behauptet.

| Werkzeugbereich | Konkreter Code / Zustand | Nachweis |
|---|---|---|
| Originalupload, Hash, Archiv, Originalbetrachter | `document_work.archive_upload`, `archived_upload`, bestehende Archivblöcke/-trigger | Memory/SQLite; Dateitausch und gewöhnlicher unzugeordneter Eingang |
| DOCX, Langdokument, Tabellen, Bilder, Kopf-/Fußzeilen, Sonderzeichen | ZIP-/OOXML-Prüfung, unveränderte Paketbytes, eigene Fassungen | Server-Roundtrip geprüft; **kein** geprüfter Editor-Roundtrip |
| Lokaler Word-Editor und dessen vollständige Werkzeugliste | `optional/document-editor` + `DocxEditor.jsx`, native Blob-Ein-/Ausgabe, Suggesting-Modus | Bibliothekinstallation und echte Bedien-/Layoutprüfung offen |
| UTF-8-Texteditor | `PlainTextEditor.jsx`, gleiche Sitzungs-/Fassungsgrenze | Server einschließlich leerer neuer Fassung geprüft |
| Autosave, Wiederanlauf, zwei Editoren, Quellenvergleich | private serverseitige Zwischenstände; erwartete Sitzungsrevision und Archivkopf; Rebase nur nach Bestätigung | Memory/SQLite einschließlich zwei unabhängiger SQL-Verbindungen und Crashpuffer |
| DOCX → PDF | `document_conversion.py`, lokales LibreOffice, eigener Prozess/eigenes temporäres Profil, Timeout | Fehlende Komponente und wiederholbarer Auftrag geprüft; echte Konvertierung offen |
| PDF Highlight/Kommentar/Text/Freihand/Stempel/Zeichen-/Bildunterschrift | typisierte Ebene; unrotierte PDF-Punkte, Seitenrotation; stabile Annotation-ID, Autor/Zeit und Änderungsautor; append-only Historie | Code vorhanden; native PDF-Engine- und Browserprüfung offen |
| PDF abgeflachte Ausgabe | `document_pdf._flatten`, neue Dokument-/Archividentität, gespeicherte Ebene | Enginegate vorbereitet, nicht ausgeführt |
| PDF Drehen / Einfügen / Ordnen / Entnehmen / Zusammenführen / Teilen | `document_pdf.transform`, autorisierte archivierte Zusatzquellen, explizite Seiten-/Gruppenfolge | Enginegate vorbereitet, nicht ausgeführt |
| PDF Zuschneiden | sichtbarer Crop, ausdrücklich **keine** Schwärzung | Enginegate offen |
| PDF Formulare | vorhandene Felder auslesen/ausfüllen, Signaturfelder nicht überschreiben; Seitenprüfung mit Folgecursor | Enginegate offen; **kein freier Formularfeld-Designer** |
| PDF Signaturen | Signaturfelder/Flags erkennen, Gültigkeit `not_verified`; veränderte Ausgabe `modified_bytes` | keine kryptografische Validierung behauptet; Enginegate offen |
| PDF echte Schwärzung | Bereichsinhalte entfernen; anschließend alle Seiten aus sichtbaren Pixeln neu aufbauen; keine Originalobjekte, Textschicht, Anhänge, Formulare oder Metadaten übernehmen | Code und unabhängiger Objekt-/Metadaten-/Pixeltest vorhanden; tatsächliche Engineausführung offen |
| PDF expliziter Inhaltsmodus | gewähltes Rechteck entfernen und Unicode-Text einsetzen; keine Zusage von Word-artigem Reflow | Enginegate offen |
| PDF Optimierung | Bereinigung/Deflate in neuer Ausgabe | Enginegate offen; keine garantierte Größenreduktion |
| PDF OCR-Textschicht | lokale PyMuPDF/Tesseract-Pixel-OCR `deu+eng`, neue durchsuchbare Ausgabe | Sprachdaten/Engine und echter Nachweis offen |
| Geschützte / korrupte Dateien | sichere DOCX-Strukturprüfung, Größen-/ZIP-/Beziehungsgrenzen, aktive Inhalte abweisen; PDF-Engine verweigert verschlüsselte/still reparierte Dateien | DOCX geprüft; vollständige PDF-Eingangsprüfung erst mit optionaler Engine |
| Rechnungsoriginal / kontrollierte OCR-Übernahme | lokaler Erkennungsauftrag, sichtbare Felder/Herkunft, bestehende Review-Transaktion, Originalbezug und Replays | reale PDF-Texterkennung und Fachorakel in Pakettests; kein Provideraufruf |
| Übergabeoriginalfoto / Rückscan | direkte transaktionale Archivierung ohne veränderliche Dateikopie; eigener Document/Version/Hash; unveränderliche Linkhistorie mit Protokoll-FK | Memory/SQLite; Konflikt, Replay und Löschschutz |

### Daten-/API-Vertrag

Neue additive Tabelle `document_work_events`: Dokument, Bestand, optional Protokoll-FK, Autor, Art, Ressource, fortlaufende Revision, global benutzergebundener Befehlsschlüssel, Befehlsfingerprint, JSON-Zustand, Zeit. Einzigartig: `(actor_id, command_key)` und `(resource_id, revision)`. Datenbanktrigger verweigern UPDATE/DELETE der Historie. Ein zusätzlicher Trigger schützt Vertrag/Einheit eines mit Nachweisen verbundenen Protokolls. Bestehende Archivtabellen, Blöcke und Originalschutz bleiben bestehen. Die Speicheradressen neuer Ausgaben/Nachweise sind virtuelle Uploadpfade; die Bytes liegen im bestehenden Datenbankarchiv.

Schreibbefehle binden `expected_version`, `expected_sha256`, `expected_document_revision` und `command_key`. Sitzungen zusätzlich an Autor/Modus/Sitzungsrevision; Annotationen an eine erwartete gemeinsame Ebenenrevision. Gleicher Befehl nach verlorener Antwort liefert dasselbe Ergebnis; geänderte Nutzlast mit gleichem Schlüssel, veraltete Quelle oder veraltete Sitzung erzeugt 409. Formular-/Formatfehler: 422; fehlende optionale Engine: 503; Quellen außerhalb der aktuellen Rechte: 404; entzogene Schreibrechte: 403. Die Kontosperre und der aktuelle Bestands-Scope werden bis Commit aus dem vorhandenen Archivvertrag übernommen. Exporte prüfen alle Zusatzquellen erneut vor Veröffentlichung. Zwei Worker können rechnen, veröffentlichen aber durch die Dokument-/Transaktionssperre nur ein Ergebnis.

Öffentliche Endpunkte unter `/api/v1/documents/{id}/work`: `source`, `capabilities`, `archive`, `versions`, `versions/{id}/download`, `sessions`, `sessions/{id}`, `sessions/{id}/docx`, `/text`, `/annotations`, `/rebase`, `pdf-inspection`, `choices/{pdfs|protocols}`, `exports`, `exports/{id}`, `exports/{id}/run`, `analysis`, `analysis/{id}/run`, `invoice-proposal`, `invoice-takeover`, `evidence`, `evidence-protocol/{id}`, `history`. Direkte Nachweisstrecke: `/api/v1/handover-protocols/{id}/evidence` (GET/Multipart-POST) und `/source`.

Bestandsverträglichkeit: bestehende Routen bleiben vorhanden. Normale Dateiabrufe liefern nach Archivierung das erste archivierte Original statt einer ersetzten Festplattendatei; bearbeitete Fassungen werden ausdrücklich über den Versionsdownload geöffnet. Nicht archivierte, noch unzugeordnete Eingangsdateien bleiben im bisherigen Viewer verwendbar. `invoice_review._file_digest` prüft archivierte Blöcke statt einer veränderlichen Uploaddatei. Eine geänderte aktive Fassung kann damit keine alte Belegprüfung als unverändert ausgeben.

Snapshots wurden auf Format **9** erweitert. Die vorhandene schemaabgeleitete Snapshotstrecke übernimmt die neue Geschäftstabelle einschließlich privater Zwischenstände, Ergebnisse und Links; Originalbytes bleiben im vorhandenen Archiv-Snapshot. Ein frischer InMemoryStore-Restore wurde aus beiden Testvarianten geprüft. Vollbackup/Restore einschließlich Benutzeridentitäten und der kompletten Anwendung wurde hier **nicht** ausgeführt und bleibt Koordinatorgate.

### Dateien mit Integrationskonfliktpotenzial

Gemeinsam berührt: `backend/db/__init__.py`, `backend/storage.py`, `backend/repositories/sql_store.py`, `backend/routing.py`, `backend/routers/files.py`, `backend/services/upload_policy.py`, `backend/services/data_snapshot.py`, `backend/services/invoice_review.py`, Handover-Router/-Service und bestehende Dokument-/Partei-/Handover-Oberflächen. Neue Helfer gehören diesem Paket. `connection_evidence.py` wurde weder angelegt noch geändert. Keine anderen Checkouts, Liveports, Benutzerkonfigurationen oder Geheimnisse verwendet; keine Commits/Pushes/Veröffentlichungen.

## Abhängigkeiten und lokale Voraussetzungen

- **PyMuPDF==1.26.7**, exakt in `requirements-documents-optional.txt`: PDF-Parsing, Seitenwerkzeuge, Darstellung, Redaction, OCR-Anbindung. AGPLv3/commercial von Artifex. Nicht installiert, nicht zum Standard-Requirementsatz hinzugefügt. Lizenzpflichten müssen vor Aktivierung geklärt werden.
- **superdoc==2.19.0-next.11**, exakt aus dem offiziellen Paketmanifest beobachteter **Vorabstand**, in `optional/document-editor/package.json`; **vite==8.1.0** zum separaten Build. AGPL-3.0 bzw. kommerzielle Option. Kein Kauf und keine Änderung der Projektlizenz. Separate Verpackung ist **keine** Behauptung, dass AGPL-Pflichten dadurch entfallen. Verfügbarkeit im Registry, Transitiv-Lock, Build und v2-Vertrag müssen vor Integration nachgewiesen werden. Es wurde kein optionales `npm install`/`npm ci` ausgeführt.
- Lokales LibreOffice für DOCX→PDF: expliziter absoluter `DOCUMENT_LIBREOFFICE_EXECUTABLE`-Pfad; kein automatischer Download/keine ausführbare Dateisuche. **Konkrete geprüfte LibreOffice-Version noch offen.** Prozess verwendet ein eigenes temporäres Profil und validierte DOCX ohne Makros/OLE/externe Vorlagen. Keine Benutzerprofile oder globalen Sicherheitseinstellungen werden geändert.
- Tesseract-Sprachdaten Deutsch/Englisch für die neue PDF-OCR-Schicht: Installation/Versionsnachweis offen. Keine Sprachpakete heruntergeladen. Schon vorhandene lokale Text-/OCR-Helfer bleiben separat nutzbar.
- SuperDoc-Telemetrie wird in der optionalen Komponente ausdrücklich deaktiviert. Dokumente kommen als lokale Blobs; keine CDN-/Cloudeditor-URL und kein Cloudkonto. Der tatsächliche Browser-Netzwerknachweis ist noch offen.

## Ausgeführte Prüfungen und noch auszuführende Gates

Alle Backendläufe über die vorgegebene unveränderte `review-venv-20261013\Scripts\python.exe` und `scripts/run_pro_matrix.py`, mit eigenen Laufpfaden und ohne xdist-Worker. Der Parallel-Editor-Test verwendet gezielt zwei Thread-/SQL-Verbindungen innerhalb **eines** pytest-Prozesses; keine parallelen Testsuiten.

- Memory: zuletzt **42 bestanden**, Label `docs-verified-memory`, Verzeichnis `artifacts/pro-tests/docs-verified-memory-memory-b41054b33d5d45209bc067a729595498`. Enthält Paketfälle, additive Migration, Dateihelfer sowie ausgewählte bestehende VAT-/Skonto-/Receipt-/Archivregressionen. `input.json`, `result.json`, `junit.xml`, `pytest.log` dokumentieren Quellhashes, Ausgangscommit und Auswahl.
- Nach der abschließenden Entkopplung zurückgegebener Memory-Lesezustände wurden **4 weitere gezielte Memory-Fälle bestanden**: Originalbetrachter, zwei Editoren mit Rebase/Crashpuffer, frischer Restore und lokale PDF-Erkennung. Verzeichnis `artifacts/pro-tests/docs-final-read-memory-memory-8c97c3ecb2ff420aa10baa1f7ad965b9`. Der 42-Fall-Memory-Bericht gehört zum dort festgehaltenen Quellhash, der spätere Vier-Fall-Bericht zur korrigierten Lesegrenze.
- SQLite: **42 bestanden**, Label `docs-verified-sql`, Verzeichnis `artifacts/pro-tests/docs-verified-sql-sql-ecb040ec102c492aa308c680e69b9438`. Früherer erweiterter Zwischenstand: 24 bestanden unter `docs-sql-restore-fix-sql-55c80e7530714e7fba5bb46c9598b31c`. Auch der native lokale PDF-Texterkennungstest läuft gegen echte archivierte PDF-Bytes und den vorhandenen Parser, ohne Mockadapter.
- Frontend: abschließend **34 bestanden**, ausschließlich `DocumentWorkbench.test.jsx`, `PdfPreview.test.jsx`, `PartyDocumentsPage.test.jsx`, `--maxWorkers=1 --no-file-parallelism`. Nachweise: `artifacts/document-ui-qa/input.json` (Quellhashes) und `results.json` (Vitest). Tatsächliche Bibliotheks-/Layoutprüfung ist darin nicht enthalten. Die vorhandene `node_modules`-Kopie wurde nur verwendet; **kein npm-ci-Nachweis**.
- Gezieltes Ruff zuletzt sauber; Mypy (Linux-Plattform, acht neue/erweiterte Paketmodule) sauber; gezieltes ESLint sauber; `node --check scripts/document_browser_qa.mjs` und `git diff --check` sauber. Die Quellstände sind uncommittete Änderungen auf `c16e0970`; maßgeblich sind die jeweiligen `input.json`-Quellhashes, nicht die unveränderte Git-HEAD allein.
- Nach den Matrixläufen wurde die Seitenrotation auch beim Einbetten von Bildunterschriften an die optionale PDF-Engine weitergereicht. Diese native Stelle ist statisch geprüft, aber ausdrücklich weiterhin Teil des **nicht ausgeführten** Engine-/Browsergates.
- Frühere rote Läufe bleiben erhalten: erste Memory-Fixture nutzte fälschlich ein Read-Modell als Create-Modell; erster SQLite-Lauf scheiterte an der alten Bulk-Bereinigung selbstreferenzierender Versionsketten; ein weiterer Restore-Fall deckte eine unnötige Schreibtransaktion beim Lesen einer Sitzung auf. Diese Fehler wurden korrigiert, keine Gates gelockert.

### Vorbereitete tatsächliche Gates für den Koordinator

1. Optionale Abhängigkeiten in einer **eigenen** abgestimmten Umgebung installieren, Lizenz-/Registry-/Locknachweise aufnehmen. Für SuperDoc den separaten Component-Build ausführen, anschließend diesen Frontendstand bauen. Kein globales Paket installieren.
2. Native PDF-Fälle ausdrücklich mit Matrix auswählen: `scripts/run_pro_matrix.py --backend memory --label docs-pdf-engine tools/document_pdf_engine_cases.py`. Fehlende Engine ist dort ein harter Fehler, kein Skip. Enthält unabhängige Seiten-/Text-/Formular-/Metadaten-/Anhang-/Pixelorakel, geschützte/kaputte PDFs und alle sieben Annotationstypen. **Noch nicht ausgeführt.** OCR-Sprachdaten und echter LibreOffice-Konvertierungsfall benötigen zusätzliche echte Gegenproben.
3. Tatsächlicher Browser: `scripts/run_document_browser_qa.py --playwright <abgestimmtes lokales Playwright-Modul> --output artifacts/document-browser`. Der Runner verlangt den lokalen Component-/Frontendbuild, startet nur seine eigene synthetische Installation auf freiem Port, verweigert 8000/8765 und stoppt nur eigene Prozesse. Prüft Archivierung, tatsächliches Öffnen/Speichern des DOCX, PDF-Annotation/Export, 1440/360/320, Tastatur, Originalhashes und blockierte externe Requests. Screenshots und exportiertes DOCX müssen **angesehen** und in einer unabhängigen Office-Anwendung verglichen werden. **Nicht ausgeführt.**
4. Browser- und Office-Abnahme muss zusätzlich echte Textänderungen sowie jede Word-Matrixzeile, Reflow/Tabellen über Seiten, Kopf-/Fußzeilen, TOC/Fußnoten, Bilder, Kommentare und Änderungsannahme/-ablehnung praktisch prüfen. Der vorbereitete Browser-Smoke allein deckt diese Liste nicht vollständig ab.
5. PostgreSQL mit unabhängigen Verbindungen, Migration vom vollständigen aktuellen Schema über beide Integrationswege, Vollbackup/Restore, Kontowechsel und große Dokumentbestände bleiben getrennte Koordinatorgates.

## Genuine offene Implementierung / Grenzen

Das Paket ist **nicht vollständig abgenommen** und wird nicht als Fertigstellung des Gesamtauftrags gemeldet.

- Die optionale DOCX-Bibliothek ist nicht installiert/gebaut. Daher fehlen ein real nachgewiesener editierbarer Browserweg und die tatsächliche Einzelabnahme sämtlicher Word-Werkzeuge. Der Vorabversions-Pin benötigt besondere Kompatibilitätsprüfung; es gibt noch keinen Transitiv-Lock.
- Die PDF-Engine ist nicht installiert. Die konkrete Implementierung ist vorhanden, aber noch nicht an der echten Engine ausgeführt; Koordinaten, Zeichnungen, Unicodeeinfügung, Signaturerkennung, Redaction und Formularverhalten müssen die vorbereiteten Orakel bestehen.
- PDF-Formulare können vorhandene Felder ausfüllen. Ein freier Designer zum Anlegen neuer Felder ist nicht implementiert.
- Exportjobs sind dauerhaft, wiederholbar und atomar veröffentlicht. Ein Prozessabbruch führt zu erneuter Berechnung des gespeicherten Auftrags. **Seitenweise Rechen-Checkpoints und automatisches Hintergrund-Scheduling fehlen**; sehr große Aufträge können daher wiederholt das Zeitlimit erreichen. Das ist ein Implementierungsrest, kein externer Nachweismangel.
- DOCX-/Text-Autosave sichert periodisch (20 Sekunden) und ausdrücklich vor Veröffentlichung. Unmittelbar vor dem ersten Autosave eintretender Browser-/Rechnerabsturz kann noch nicht exportierte lokale Editoränderungen verlieren. Kein sofortiger nativer IndexedDB-Absturzpuffer implementiert.
- Kein CRDT/Echtzeit-Coediting. Zusammenarbeit erfolgt durch getrennte private Sitzungen, Konfliktprüfung, Quellenvergleich und bestätigtes Rebase. Digitale Signaturen werden erkannt/als ungeprüft behandelt; keine kryptografische Vertrauenskette, qualifizierte Signatur oder Signaturerzeugung implementiert.
- PDF-Schwärzung erhält bewusst eine rein bildbasierte neue Ausgabe; Textsuche/Formulare/Signaturen/Metadaten werden entfernt. Die Originalbytes bleiben als gesondertes archiviertes Beweismittel vorhanden.
- Gewöhnliche PDF-Archivierung kann ohne optionale Engine nur Header/EOF plausibilisieren. Vollständige Struktur-/Verschlüsselungsprüfung geschieht bei den tatsächlichen PDF-Werkzeugen; ein korruptes Original wird dadurch nicht still repariert.

## Übernahme und Rückweg

Zuerst neue Modelle/Helfer und additive Migration übernehmen, anschließend Router-/Archiv-/Rechnungsprüfung-Anschlüsse und Oberfläche konfliktbewusst zusammenführen. Kein Commit wurde erstellt. Neue Migration `e160a1b2c306` bleibt Kind von `d73f2b9a041c`; fremde Paketheads durch eine **neue** Koordinator-Mergerevision zusammenführen. Der Downgrade verweigert bewusst das Löschen von Wiederanlauf-/Nachweisgeschichte. Rückweg nur über eine vollständige vorherige Sicherung, niemals über das Löschen der neuen Tabellen an einem Anwenderbestand. Kein Einsatz an Live-Daten vor unabhängiger Integration, Bibliotheks-/Lizenzprüfung und den offenen Gates.
