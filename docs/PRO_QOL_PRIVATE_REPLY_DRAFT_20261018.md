# ImmoManager Pro – QoL: Private Antwortentwürfe geschützt (18.10.2026)

**Isolierter Entwicklungsstand, nicht ausgerollt.** Ausgangspunkt: `pro/full-handover-20261016` bei Commit `d4921f9d`.

## Bedienung und Sicherheitsgrenzen

- Der wiedergefundene private Entwurf einer internen Konversation wird nicht mehr über einen einzelnen Klick auf `Entwurf verwerfen` gelöscht. Stattdessen erscheint eine ausdrücklich zu bestätigende Abfrage.
- `Entwurf behalten` und `Escape` brechen diese Abfrage ohne Aufruf von `saved.clear()`, ohne Nachrichtenversand und ohne Textverlust ab. Der Fokus kehrt zur Verwerfen-Schaltfläche zurück.
- Beim Öffnen erhält `Entwurf behalten` den Fokus; der Zustand wird durch `aria-expanded` und nur im geöffneten Zustand durch `aria-controls` kenntlich gemacht. Die Sicherheitsabfrage ist als benannte Gruppe mit verständlicher Warnung aufgebaut.
- Während der Abfrage sind Wiederherstellen, Textbearbeitung und Senden deaktiviert. Auch `Strg/Cmd+Enter` kann dann keinen Nachrichtensendevorgang auslösen. Bei laufendem oder unbestätigtem Versand ist die Löschaktion ebenfalls deaktiviert.
- Synchroner Busy-Guard verhindert wiederholte bestätigte Löschaufrufe. Bei einem Fehler wird der Text weiterhin angezeigt; es gibt keine automatische Wiederholung, nur eine erneute ausdrückliche Bestätigung.
- Zeitlich verspätete Lösch- oder Wiederherstellungsantworten eines alten Threads dürfen nach einem Konversationswechsel nicht den neuen Thread verändern. Die bestehende explizite Vergleichsprüfung vor einer Wiederherstellung wird beibehalten.
- Nach erfolgreichem Verwerfen und dem Verschwinden des Recovery-Hinweises wird der Fokus zum Antwortfeld zurückgeführt. Bereits separat eingegebener Antworttext wird nicht durch das Verwerfen des **wiedergefundenen** Entwurfs gelöscht.
- Die Abfrage verwendet die vorhandenen `ui.form.*`-Texte in Deutsch, Englisch und Spanisch. Es wurden weder die Transport-/Idempotenzbefehle noch serverseitige Zugriffs- oder Revisionsregeln verändert.

## Tatsächliche Prüfungen

- `npm.cmd run test -- src/test/InternalReplyComposerDraftSafety.test.jsx src/test/MessagesBoundary.test.jsx src/test/MessageCommandRecovery.test.jsx src/test/CustomDraftNoticeSafety.test.jsx src/test/CustomBusinessDrafts.test.jsx src/test/WorkspaceForms.test.jsx src/test/FormModal.test.jsx src/test/FormFeedbackRecoveryQol.test.jsx src/test/HandoverProtocolEditor.test.jsx src/test/HandoverProtocolsDialog.test.jsx src/test/HousingConfirmationDialog.test.jsx src/test/HousingConfirmationCommand.test.jsx src/test/RentPayments.test.jsx src/test/WorkCenter.test.jsx src/test/translations.test.js src/test/api.test.js --maxWorkers=1 --no-file-parallelism`: **153/153 bestanden (16 Dateien)**, darin zwölf neue gezielte Antwortentwurf-Regressionen.
- `npm.cmd run lint`: erfolgreich.
- `npm.cmd run build`: erfolgreich; unveränderte nicht blockierende Warnung `INEFFECTIVE_DYNAMIC_IMPORT` zu `NotificationInbox.jsx`.
- Microsoft Edge (Chromium), eigene isolierte Browser-Session über lokale Vite-Testseite auf `127.0.0.1:5187` mit synthetisch berechtigtem Benutzer und **simulierten API-Antworten**: **PASS** mit genau einem simulierten Server-Löschaufruf und null Sendeaufrufen; es wurde kein Wiederherstellen-Button betätigt. Abbruch, Warnung, Fokus und Erhalt des aktuellen Antworttexts waren Teil des Smoke-Checks. Die temporäre Testseite und der Testserver wurden anschließend entfernt/beendet.
- `git diff --cached --check`: erfolgreich.

## Unveränderte offene Punkte

- Keine echte Server-/Provider-/PostgreSQL-Abnahme und keine manuelle native NVDA-/JAWS-/VoiceOver-Prüfung. Der isolierte Edge-Smoke verwendet programmatisch ausgelöste Tastenereignisse und ersetzt keine vollständige unabhängige Tastatur-/Screenreader-Abnahme.
- Bereits vorhandene React-`act()`-Warnungen in `MessagesBoundary.test.jsx` und `WorkCenter.test.jsx` bestehen bei erfolgreichen Tests weiterhin.
- Keine Backend- oder Migrationsänderung in diesem Commit; die fünf schon vorher offenen Backend-Dateien bleiben unangetastet. Kein Merge in den Integrationszweig, keine laufende Installation verändert, kein Deployment.
