# Dokumentwerkzeuge – gemeinsamer PRO-Entwicklungscheckpoint (16.10.2026)

**Stand:** Dokumentpaket in den getrennten Gesamtzweig `pro/full-handover-20261016` aufgenommen; **keine Integrations-, Installations- oder Releasefreigabe**. Der zentrale Checkout und beide laufenden Anwenderinstallationen sind nicht berührt.

## Zusammengeführter Funktionsumfang

Der bisherige unveränderliche Originalspeicher bleibt maßgeblich. Das Dokumentpaket ergänzt geschützte Originaluploads, private DOCX-/Text-Arbeitssitzungen mit erwarteter Revision und Wiederholungsschlüssel, native Bytes statt HTML-Roundtrips, versionierte PDF-Anmerkungsebenen und abgeleitete Exporte, gesicherte Quellen für OCR-Rechnungsvorschläge sowie originale Übergabefotos/Rückscans. Die neuen SQL-Dokumentereignisse werden durch die unveränderte Paketmigration `e160a1b2c306` aufgenommen. Die additive reine Merge-Revision `e1f0a1b2c3f6` verbindet sie mit `e1f0a1b2c3f5`, ohne bestehende Migrationen umzuschreiben.

Die Quell- und Werkzeugmatrix in `docs/PRO_PACKAGE_DOCUMENTS_20261016.md` bleibt maßgeblich. Sie bezeichnet alle nicht nachgewiesenen Office-/PDF-Bibliotheksfunktionen ausdrücklich als offen.

## Korrigierte Integrationskanten

- Der ursprüngliche Invoice-Review-Migrationstest prüft seine Downgrade-Sperre jetzt gezielt an seinem **eigenen** alten Review-Head `c9f4a2e7b1d5` und migriert danach weiterhin auf den vollständigen Gesamt-Head. Ein späterer Dokument-Head darf einen absichtlich irreversiblen Downgrade nicht fälschlich als Invoice-Review-Fehler ausgeben. Der erste tatsächliche gemeinsame Memory-Lauf hatte hier **1 Fehler bei 56 Erfolgen**, nicht 57 Erfolge.
- Der neu integrierte Inbox-SQL-Code trennt Variablennamen zwischen Memory-Summen und SQL-`case`-Ausdrücken; Laufzeitlogik ist unverändert. Das unabhängige OOXML-Testfixture benennt die exakten Byte-/Stringwerte typisiert. Beide zuvor sichtbaren Typfehlerbereiche sind bereinigt.
- Ein bereits vorhandener echter Memory-Audit-Nebenläufigkeitsfehler wurde korrigiert: der private `Unit`-Rollback entfernt seine eigene angehängte Ereignisinstanz, nicht blind das letzte spätere Fremdereignis. Das in-memory Auditjournal besitzt jetzt ein gemeinsames Schreib-`RLock`. Ein Thread-Gegenbeispiel mit späterem Fremdereignis läuft grün. Zusätzliche Audit-Lesekopie-/Clear-Nacharbeit konnte wegen eines blockierten Tool-Schreibaufrufs nicht ausgeführt werden und wird hier nicht als realisiert bezeichnet.
- Die Sortierreihenfolge des neuen Dokumentrouters wurde berichtigt; keine alte Route entfernt.

## Tatsächlich verifizierte Läufe dieses kombinierten Arbeitsstands

| Nachweis | Beobachtetes Ergebnis |
| --- | --- |
| Dokumentarbeit, Dokumentmigration, bestehende Rechnungsprüfung – Memory, **nach** Testkorrektur | **57/57 bestanden**, 0 Skip; `artifacts/pro-tests/documents-rebased-memory-memory-65b9f862683842fa8064789b23c2833a` |
| Vorheriger kombinierter Memory-Lauf | **56 bestanden, 1 fehlgeschlagen** (Review-Downgrade-Annahme); `artifacts/pro-tests/integrated-doc-20261016-memory-7849fcf374d54d11a8d77439a546bbbf` |
| Audit-Rollback mit parallelem Fremdeintrag | **1/1 bestanden**; `artifacts/pro-tests/audit-memory-20261016-memory-b9badc81a4494ec7b02955f0e625be3a` |
| Frontend: DocumentWorkbench, PDF-Viewer, Parteidokumente | **34/34 bestanden**, 0 Skip |
| Vite-Produktionsbuild im isolierten Frontend | **Bestanden**, 732 Module |
| `mypy --platform linux backend` nach Korrekturen | **Bestanden**, 532 Dateien |
| `ruff check backend`, `git diff --check` | **Bestanden** |

Die Testergebnisse beziehen sich ausschließlich auf den Entwicklungs-Arbeitsstand. Die Matrix legt `input.json`, Quellhashes, JUnit-XML und `result.json` je Lauf im eigenen `artifacts/pro-tests`-Ordner ab. Die Dependency-Deprecation-Warnung in Starlette/httpx blieb erhalten. Eine lokale Referenzinstallation vorhandener Frontend-Abhängigkeiten ist kein `npm ci`-Nachweis.

**Nicht bestanden bzw. nicht ausgeführt:** Ein neuer kombinierter SQL-Matrix-Aufruf wurde vom Remote-Tool-Sicherheitscheck blockiert; dies ist keine SQL-Abnahme. Die historische Paket-SQL-Prüfung `42/42` war vor der Gesamtzusammenführung und wird nicht dafür umbenannt. Native PostgreSQL-Gegenprüfungen, kompletter Backend-/Frontend-/Coverage-Lauf, tatsächliche PDF-Engine (PyMuPDF), lokaler DOCX-Editor/SuperDoc, Tesseract, LibreOffice-Konvertierung, unabhängige Office-/Signatur-/Schwärzungsprüfung, Browserablauf 320/360/1440, saubere `npm ci` und Installations-/Restorefreigabe fehlen. Kein externer Anbieter oder produktiver Datenbestand wurde angesprochen.

## Sichere Fortsetzung

Vor Freigabe: Lizenz-/Version-/Lockprüfung der optionalen lokalen PDF- und DOCX-Bausteine, Ausführung von `tools/document_pdf_engine_cases.py` mit echter Engine, Office-/Browservergleich aller Werkzeugmatrixzeilen, isolierte SQLite- und native PostgreSQL-Integration mit zwei Verbindungen, gemeinsamer vollständiger Restore- und Lastnachweis. Die anderen PRO-Pakete bleiben getrennte Integrationsschritte. Codex übernimmt später die unabhängige Prüfung und Auslieferung, nicht dieser Entwicklungscheckpoint.

## Nachtrag zu Ausführungssperren

Der spätere Versuch, den integrierten Stand zu stagen und als eigenen Entwicklungscheckpoint zu committen, wurde vom Remote-Tool-Sicherheitscheck **vor Ausführung blockiert**. Ebenso wurde der anschließende neue Daily-Memory-Gesamtlauf blockiert. Für diese beiden Aktionen liegt deshalb ausdrücklich **kein Commit und kein neuer Gesamtprüfnachweis** vor. Der Entwicklungsarbeitsbaum und die oben protokollierten abgeschlossenen Läufe bleiben maßgeblich. Eine Sperre wurde nicht mit einer alternativen Befehlsdarstellung umgangen.
