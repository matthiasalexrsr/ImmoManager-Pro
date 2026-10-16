# ImmoManager PRO – vollständige Frontendregression auf 657 Fällen

**Datum:** 16. Oktober 2026. **Status:** geprüfter Frontend-Kompatibilitätscheckpoint,
keine Gesamtfreigabe des Backends oder aller Handoverpakete.

Quelle: eigenständiger Entwicklungs-Worktree
`pro-stage-frontend-compat-20261016`, aus `57ab0a56`.
Der erste Produkt-/Testcheckpoint liegt bereits als Commit
`dbcbc418` vor. Der nachfolgende Arbeitsschritt entfernt
ausschließlich einen unbenutzten Import und dokumentiert die
vollständige Matrix.
Keine vorhandene Anwenderinstallation, produktive Datenbank,
Port 8000/8765, produktiver Benutzer oder externe Nachricht
wurde für diese Prüfung benutzt.

## Ausgangslage nach TEHA-/Plattform-Zusammenführung

Der vollständige Testlauf der unveränderten UI erfasste
**617 bestandene und 38 fehlgeschlagene Tests**
in 103 Testdateien. Darunter war ein echter unkontrollierter
Komponentenabsturz bei einem unvollständigen
`/notifications/inbox`-Response. In mehreren älteren Testdateien
wurden zusätzlich Mock-Routen statt des tatsächlich
verwendeten `/messages/threads/{id}/page`- und
persönlichen Benachrichtigungs-Receipt-Vertrags benutzt.
Das Auflisten des kompletten Navigationskatalogs erwartete
fälschlich 41 Links, obwohl die neuen, tatsächlich
implementierten DATEV- und Connection-Ziele 43 ergeben.

## Korrekturen ohne Verlust von Invarianten

- `useNotificationInbox`: Erst wenn die Antwort eine
  paginierte `items`-Liste, gültige numerische Gesamt-/
  Ungelesenzahlen sowie geordnete/identifizierbare Einträge
  enthält, wird sie dargestellt. Sonst ein sichtbarer
  wiederholbarer Fehler; **keine** erfundene leere Liste
  und kein Renderabsturz.
- Zwei zusätzliche `NotificationInboxContract`-Gegenproben:
  unvollständige API-Antwort wird verweigert, vollständige
  leere Seite darf als echte leere Seite dargestellt werden.
- `MessagesBoundary`: Abfrage und Antwort werden anhand
  der tatsächlichen Thread-Paging-URL statt anhand einer
  zufälligen Position in einem gemeinsamen Mockarray
  korreliert. Abbruchsignal, Cursor-Rücksprung,
  verlorene ältere Seiten und intakte Entwürfe werden
  weiterhin **explizit** geprüft.
- `KpiSources`: alter Mark-Read-HTTP-Call durch den
  **authentifizierten privaten Receipt-Vertrag** ersetzt.
  Ein abgelehnter Schreibvorgang darf keine ungelesene
  Mitteilung lokal als erledigt ausgeben.
- `WorkCenter`: das bereits produktiv erforderliche
  `api.captureSession`-Orakel in der Testfixture ergänzt;
  die Prüfung eines persönlichen Rollenwechsels entfällt nicht.
- `ShellNavigation`: weiterhin genau sechs direkt erreichbare
  tägliche Haupteinträge, alle weiteren Ziele über benannte
  Tastaturgruppen; zusätzlich werden die tatsächlichen
  DATEV- und Connection-Ziele explizit geprüft.

## Verifizierte Prüfergebnisse

Nach erster Korrektur: gezielter Lauf
**38/38 bestanden** für fünf Dateien (Benachrichtigung,
MessagesBoundary, KPI, Navigation, WorkCenter).
Der zunächst erneut breite Vitest-Lauf erzielte
**627 bestanden, 30 fehlgeschlagen** bei 657 Tests in
104 Dateien. Davon waren **29 reine 5-Sekunden-Zeitüberschreitungen**
unter hoher Testparallelität und ein separater, nicht
gesichert reproduzierter E-Mail-/Renderingfall.

Die anschließende, **vollständig unveränderte Testauswahl**
wurde mit `--maxWorkers=2 --testTimeout=15000 --reporter=dot`
wiederholt. Ergebnis: **657/657 erfolgreich, alle 104 Dateien
bestanden, keine fehlgeschlagenen Tests**.
Der vollständige Output ist im isolierten Ordner
`artifacts/pro-tests/frontend-all-2workers-c54731e352e145529d008a5a1c14e2d6`
erhalten. Das Limit verhindert Testrechner-Überlastung,
es umgeht keine Produktassertions oder Threadgrenzen.
`npm ci --ignore-scripts` installierte zuvor die
Sperrdatei frisch: 283 Pakete, **0 gemeldete Schwachstellen**.
Zusätzlich wurden **ESLint ohne Fehler** und ein kompletter
**Vite-Produktionsbuild** auf dem aktualisierten Stand
nachgewiesen. Der vollständige Vitestlauf wurde nach Commit
`dbcbc418` und einer reinen Lint-Importbereinigung gestartet.
Der letzte Dokumentations-/Bereinigungscommit erhält einen
eigenen abschließenden, hashgebundenen Testnachweis.

## Weiterhin offen

Die vollständige Backendmatrix auf
`57ab0a56` ist trotz **83,63 % gemessener Coverage**
bei 54 roten Fällen nicht abnahmefähig.
Darunter befinden sich alte create_all/Alembic-Übernahmen,
ein fehlendes optionales FinTS-Dependency, historische
Autorisierungs- und Originalschutzassertions sowie
zu lange Windows-QA-Dateipfade. Ein separates QA-Paket
`pro-stage-full-matrix-20261016` bearbeitet diese
Ursachen, ohne geschützte Produktrechte oder
vorherige Revisionen still abzuändern.

Dieser Frontendcheckpoint ist **keine** Freigabe
für TEHA-, WhatsApp-, Portal-, Bank- oder Post-Liveaktionen.
