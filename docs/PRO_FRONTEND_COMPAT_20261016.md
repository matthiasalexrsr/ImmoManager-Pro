# Frontend-Gesamtmatrix: bestätigte Vertragskorrekturen 16.10.2026

Der gemeinsame Commit `57ab0a56` hatte im kompletten Vitest-Lauf
`artifacts/pro-tests/frontend-full-57ab0a56-e9f9eca494cf479e8b13c53120c2b915`
**617 bestanden und 38 fehlgeschlagen (24 Testdateien)**, zusätzlich
einen unbehandelten Fehler in `NotificationInbox`. Dies ist **kein**
erfolgreicher Gesamttest.

Eigenständiger Korrektur-Worktree `pro/stage-frontend-compat-20261016`;
der zentrale Checkout und die Anwenderinstallationen bleiben unberührt.

## Reparierte API-/UI-Grenze

`useNotificationInbox` erwartet jetzt ein vollständiges,
paginiertes Notification-DTO mit `items`, `total`,
`unread_count` und eindeutig identifizierten Einträgen.
Bei unvollständigen Responses zeigt es einen sichtbaren,
wiederholbaren Fehler statt einer unsichtbar leeren Liste oder
einem React-Laufzeitabsturz. Veraltete Nachrichtendaten werden
nicht als gültige Benachrichtigungsseite ausgegeben.

Die Tests `NotificationInboxContract.test.jsx` prüfen
den negativen und positiven Fall; `KpiSources.test.jsx`
fragt keine obsolete individuelle `PATCH /notifications/id`-
Schnittstelle mehr ab, sondern prüft den tatsächlich
gesendeten wiederholungssicheren `POST /notifications/all/receipt`
inklusive Snapshot und den Erhalt ungelesener Einträge bei
fehlgeschlagenem Write.

Die zuvor überprüften `MessagesBoundary`-Testorakel fragen
die konkrete URL/den Cursor ab und verwechseln Nebeneffekte
des persönlichen Eingangs nicht mit Nachrichten-GETs.
Die WorkCenter-Test-Mockoberfläche enthält `captureSession`,
ohne die reale Session-Schranke auszuschalten.
Die Sidebar-Regression verlangt weiterhin sechs direkte
Alltagslinks und die zwei tatsächlich hinzugekommenen
DATEV-/Connection-Ziele im erweiterten Menü.

## Prüfung und weitere Lücken

Der gezielte Integrationslauf mit fünf React-Testdateien
`NotificationInboxContract`, `KpiSources`,
`MessagesBoundary`, `WorkCenter`, `ShellNavigation`
bestand mit **38/38 Tests**, ESLint ebenfalls. Früherer
Lauf vor der korrigierten Inbox-/Thread-Testbasis war rot.
Die volle Vitest-Matrix wurde für diese Korrektur **noch nicht**
wiederholt; sie bleibt Freigabeblocker. Weitere 24
ursprünglich betroffene Dateien müssen nach einer exakten
Endfassung erneut fachlich geprüft werden. Keine echte
Nachricht oder externe Provideraktion wurde gesendet.
