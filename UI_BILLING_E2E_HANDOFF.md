# Echte Billing-Browserregressionen: Finalisierung, Revision, PDF

Basis: 6b58ab3 (Root enthält 3 echte Browserabläufe und Payment-Backend 0d5ff91).
Branch: assist/billing-finalization-e2e; Worktree: work/statements-review.
Keine Root-Integration, kein Push. Keine Änderungen an Anwendung, Backend, Rollen,
Schema, Import/Sicherung, Dependencies, bestehendem Runner oder CI.

Das separate i18n-Paket bleibt auf assist/statements-ui-reliability, Commit c6a40dd.
Dieser E2E-Patch kann unabhängig davon cherry-gepickt werden.

## Neue automatisch entdeckte Tests

frontend/e2e/billing-finalization.pw.mjs ergänzt den vorhandenen Runner um:

1. Finalisierung über UI nach Generierung und Review, persistente Snapshot-Hashes,
   erwartete Beträge für zwei Einheiten, schreibgeschützte Kosten, HTTP 409 bei
   Kostenänderung/Neugenerierung der finalisierten Periode, idempotente erneute
   Finalisierung, Reload und echter geschützter PDF-Download.
2. Revision über UI mit kodierter Begründung, neue Periode/Kosten-IDs, Kostenänderung
   nur in der Kopie, neue Berechnung und Finalisierung. Die vollständigen alten
   Statements einschließlich Hashes sowie die ursprünglichen Kosten bleiben
   unverändert. Reload, Korrektur-PDF und mobile Revision werden geprüft.
3. Finalisierung ohne generierte Statements: echte HTTP-400-Ablehnung sichtbar im
   Browser; Periode bleibt im Review, keine Statements werden erzeugt.

Alle Mutationen laufen gegen die echte FastAPI/SQLite-Anwendung, ohne Request-
Interception. Der existierende Runner erzeugt/entfernt nur seine eigene frische
Testdatenbank. Login erfolgt über das UI als vorhandener Demo-Eigentümer.

Die Fixture erstellt über öffentliche APIs ein eigenes Portfolio, ein Objekt,
zwei Einheiten (60/40 m²), zwei aktive Verträge, einen Flächenschlüssel und eine
Periode 2025. 800 EUR Kosten ergeben 480/320 EUR Anteile; hinterlegte monatliche
Vorauszahlungen ergeben 120/60 EUR Jahresvorschüsse. Die Korrektur auf 900 EUR
liefert für Einheit A 540 EUR Anteil und 420 EUR Saldo. Es sind hinterlegte
Vorschüsse, kein behaupteter Nachweis tatsächlicher Payment-Eingänge.

## PDF-Prüfung und Grenzen

Der Browser klickt den tatsächlichen PDF-Knopf. Geprüft werden HTTP 200,
application/pdf (kein Text-/HTML-Fallback), Content-Disposition, Dateiname,
erfolgreicher Download, PDF-Signatur/EOF und vollständige Content-Length.
Die gespeicherten PDFs werden als Playwright-Artefakte angehängt.

Im ersten Lauf lieferte Edge für diese PDF im DevTools-Response/Trace einen leeren
Body, während der gespeicherte Download alle 1956 Bytes laut Content-Length enthielt.
Deshalb prüft der Test den echten Download statt response.body(). Das ist keine
API-Simulation. Die PDF-Seite wurde zusätzlich ausgelesen und separat gerendert;
der folgende fachliche Nummerierungsfehler ist darin tatsächlich sichtbar.
Die CI prüft PDF-Transport, nicht vollständige PDF-Textsemantik oder Layout-Parität.

## Offener fachlicher Defekt: Revisionsnummer nicht fortgeschrieben

API-Antwort zur Korrektur: revision=2. Beide neu generierten und finalisierten
Statements haben revision=1. Das echte Korrektur-PDF druckt ebenfalls Revision: 1.
Beträge, eigene IDs, Quelldaten-Isolation und Snapshots sind korrekt; die Nummer
ist es nicht. Der grüne Testlauf ist KEIN Nachweis vollständiger Revisionskorrektheit.

Dieser Befund wurde in AGENT_COORDINATION_UI.md vor Backendänderungen gemeldet.
Backend/Schema/Rollen wurden nicht geändert. Ein Parser für den Periodentitel wäre
kein belastbarer Ersatz für persistente Revisions-/Quellperioden-Metadaten.

Die getrennte Diagnose frontend/e2e/assert-revision-counter.mjs liest das tatsächlich
aufgezeichnete revision-records.json und verlangt konsistente Nummerierung. Sie
endet auf dieser Basis mit Exit 1 (erwartet 2, erhalten [1,1]). Sie wird nicht als
bestandener Test mitgezählt. Nach dem Backendfix sollte ihre Assertion direkt in
den Revisions-Browsertest übernommen werden, statt nur manuell geprüft zu werden.

## Ausführen im vorhandenen Setup (aus frontend)

```powershell
$env:IMMO_E2E_CHANNEL = 'msedge'
$env:IMMO_E2E_PYTHON = 'C:\path\to\ImmoManager-Pro\.venv\Scripts\python.exe'
npm run test:e2e -- billing-finalization.pw.mjs
$record = Get-ChildItem test-results -Recurse -Filter revision-records.json | Select-Object -First 1
node e2e/assert-revision-counter.mjs $record.FullName
```

Für den normalen Gesamtlauf: npm run test:e2e. Unter Linux bestehende Chromium-
Installation des CI-Jobs verwenden und IMMO_E2E_CHANNEL weglassen.

## Verifiziert

Drei vollständige Läufe auf jeweils frischer SQLite-Testdatenbank: je 6/6 Browser-
Tests bestanden (3 vorhanden + 3 neu), darunter reale Zahlungen/Bankzuordnung/Storno.
Finaler Lauf 6/6 grün, Nummerierungsdiagnose separat rot (Exit 1). Keine Rollenänderung.
Die Frontend-Units auf E2E-Basis 6b58ab3: 123/123 grün; das unabhängige i18n-Paket
hat auf seinem eigenen Basisstand 130/130. Diese Zahlen nicht zusammenzählen.
ESLint final ohne Warnungen/Fehler, Build über Runner und git diff --check grün.

Nachweise: work/ui-billing-e2e-evidence/reviewed-final-run.log, final-lint.log,
unit-tests.json, revision-counter-diagnostic.log und reviewed-results/ mit PDFs,
Screenshots, backend.log sowie revision-records.json. Der letzte Gesamtlauf
bestand alle 6 Tests in 44,2 Sekunden Testzeit. Alle Browserprozesse wurden vom
vorhandenen Runner beendet; seine temporäre Datenbank wurde entfernt.

Der Nummerierungsabgleich ist bewusst getrennt sichtbar, nicht als erwarteter
Fehler/Skip innerhalb einer vermeintlich vollständigen grünen Revisionstest-Suite
versteckt. Die eigentliche fachliche Korrektur bleibt als Backend-Arbeit offen.

API-/Download-Pattern: offizielle Playwright-Dokumentation, APIRequestContext und
Downloads (page.waitForEvent('download'), Download.saveAs). Keine zusätzliche
PDF-Parser- oder Browser-Abhängigkeit in diesem Paket.
