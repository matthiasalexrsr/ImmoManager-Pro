# ImmoManager Pro – QoL: Formularfehler und Entwurfswiederherstellung (17.10.2026)

**Isolierter Entwicklungsstand. Keine Änderung an laufenden Installationen.**
Ausgangspunkt: `pro/full-handover-20261016`, Commit `93480c04` (QoL-Sammelaktionen).

## Bedienung

- Wenn ein fachlicher Formular-Speichervorgang fehlschlägt, wird der Fehler für Tastatur- und Screenreader-Nutzung fokussierbar angezeigt. `Eingaben prüfen` führt zurück zum ersten bearbeitbaren Feld.
- Die eingegebenen Feldwerte und ein ggf. bereits lokal/auf dem Server gesicherter Entwurf bleiben nach einem fehlgeschlagenen Speichern erhalten. Es erfolgt keine automatische fachliche Wiederholung.
- Nach `Entwurf wiederaufnehmen` wechselt der Fokus zu den wiederhergestellten Eingaben. Die bestehende explizite Versionsprüfung und die fachliche Speicherschranke bleiben bestehen.
- `Entwurf verwerfen` bei einem wiedergefundenen Entwurf öffnet jetzt eine explizite zweite Bestätigung. `Entwurf behalten` löscht nichts und gibt den Tastaturfokus an die Verwerfen-Aktion zurück; erst `Endgültig verwerfen` ruft die vorhandene Entwurfslöschung auf.
- Neue Bedienhinweise in `de-DE`, `en-US` und `es-ES`.

## Prüfstand

- `npm.cmd run test -- src/test/FormFeedbackRecoveryQol.test.jsx src/test/FormModal.test.jsx src/test/WorkspaceForms.test.jsx src/test/ListFormLifecycle.test.jsx src/test/FirstDay.test.jsx src/test/QolRound4.test.jsx src/test/translations.test.js --maxWorkers=1 --no-file-parallelism`: **79/79 Tests bestanden** (7 Dateien), darunter 5 neue Regressionstests.
- `npm.cmd run lint`: bestanden.
- `npm.cmd run build`: bestanden. Unveränderte, nicht blockierende Warnung `INEFFECTIVE_DYNAMIC_IMPORT` für `NotificationInbox.jsx`.
- `git diff --check`: bestanden.

## Abgrenzung

- Nur gemeinsame Formularoberfläche, kleine CSS-Regeln, Übersetzungskataloge, neue Tests und dieser Bericht; keine Backend-, Datenbank- oder Geschäftsvorgangsänderung.
- Bereits vorhandene fremde Frontend-Teständerungen und Backend-Migrationsarbeiten bleiben unangetastet und sind nicht Bestandteil des QoL-Commits.
- Keine unabhängige Prüfung mit realem Browser, Screenreader oder echten Server-/Provider-Verträgen. Diese Abnahmen bleiben vor einem Release separat erforderlich.
