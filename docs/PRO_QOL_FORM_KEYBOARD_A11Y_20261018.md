# ImmoManager Pro – QoL: Formular-Tastaturführung und Feldhinweise (18.10.2026)

**Isolierter, nicht ausgerollter Frontend-Checkpoint.** Ausgangspunkt: `pro/full-handover-20261016`, Commit `fa558fab`.

## Konkrete Verbesserungen

- `Escape` bei der Bestätigung **„Entwurf verwerfen“** schließt zuerst ausschließlich diese zweite Bestätigungsstufe. Fokus zurück auf „Entwurf verwerfen“; weder `draft.clear()` noch fachlicher Save oder Formular-Schließen werden dadurch gestartet.
- `Strg/Cmd+Enter` startet während dieser Bestätigung und einer laufenden Entwurflöschung keinen fachlichen Speichervorgang. Eine einmal ausgelöste bestätigte Löschung kann nicht durch `Escape` versehentlich den gesamten Dialog schließen.
- Die Frage **„Ungespeicherte Änderungen verwerfen?“** bekommt jetzt beim Erscheinen zuverlässig den Tastaturfokus auf „Weiter bearbeiten“. Bei Abbruch durch `Escape` oder Button wird der frühere Eingabefokus wiederhergestellt, gegebenenfalls mit Fallback auf das erste aktive Formularfeld.
- Nach explizit abgeschlossenem Verwerfen eines wiedergefundenen Entwurfs geht der Fokus in die wieder editierbaren Felder.
- `aria-describedby` verknüpft vorhandene Feldhinweise mit Text-, Zahlen-, Datums-, Auswahl- und Freitextfeldern. Tritt ein serverseitiger Feldfehler auf, sind **Fehlertext und ursprünglicher Hinweis gemeinsam** referenziert; nach der Korrektur bleibt der Hinweis erhalten.
- Unverändert: serverseitige Berechtigungen, Verwerfen-/Speichern-Entscheidung, Entwurfs-Persistenz, Bestands- und Migrationslogik.

## Regressionsnachweise

- 9 gezielte Vitest-Dateien, darunter die erweiterten `FormModal.test.jsx` und `FormFeedbackRecoveryQol.test.jsx`: **97/97 Tests bestanden**.
- `npm.cmd run lint`: bestanden.
- `npm.cmd run build`: bestanden; bekannte nicht blockierende Warnung `INEFFECTIVE_DYNAMIC_IMPORT` für `NotificationInbox.jsx` unverändert.
- `git diff --cached --check`: bestanden.

## Isolierter echter Browser-Tastaturtest

- Microsoft Edge (Chromium), isolierte lokale Vite-Seite und temporäres Benutzerprofil, Zugriff über Chrome DevTools Protocol; echte Browser-Tastaturereignisse `Escape`, `Tab`, `Umschalt+Tab`, `Enter`, `Strg+Enter`. Keine produktiven Konten oder Serverdaten.
- **PASS discard**: Fokus auf der Rückfrage, Esc kehrt zum Eingabefeld zurück, Werte bleiben erhalten, Tab-Fokusfalle funktioniert in beiden Richtungen.
- **PASS validation**: Fehlermeldung fokussiert, `Tab` zur Prüfaktion und `Enter` zum betroffenen Feld, Feldhinweis und Fehlermeldung gleichzeitig verknüpft, kein automatischer weiterer Save.
- **PASS recovery**: `Enter` öffnet Löschbestätigung, `Escape` schließt nur die Bestätigung und fokussiert die ursprüngliche Aktion, kein Lösch-, Save- oder Schließ-Aufruf.
- Testseiten, CDP-Steuerdatei und Testserver nach dem Durchlauf entfernt beziehungsweise beendet.

## Release-Grenzen

Kein manueller Test mit NVDA/JAWS/VoiceOver, keine vollständig verifizierte Accessibility-Tree-/Screenreader-Abnahme und kein realer Backend-/PostgreSQL-/Provider-End-to-End-Test. Vor einem Release gesondert nachholen. Bereits offene fremde Backend-Migrationsänderungen und der zentrale Integrationszweig bleiben unangetastet. Kein Deployment.
