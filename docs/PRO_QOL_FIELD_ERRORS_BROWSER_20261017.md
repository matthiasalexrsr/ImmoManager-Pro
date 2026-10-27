# ImmoManager Pro – QoL: Feldgenaue Formularfehler + Edge-Browserprüfung (17.10.2026)

**Isolierter Frontend-Checkpoint; nicht ausgerollt.** Ausgangspunkt: `pro/full-handover-20261016` bei `c6033936`.

## Bedienung und Grenzen

- Die vorhandene allgemeine Speichermeldung, der Schutz der eingegebenen Werte und die explizite Entwurfswiederherstellung bleiben erhalten.
- Validierungsantworten mit Status 400/422 werden nun – soweit eindeutig zuordenbar – unmittelbar beim betroffenen sichtbaren Feld angezeigt (`aria-invalid`, `aria-describedby`). Die Taste `Eingaben prüfen` führt zum **ersten fehlerhaften bearbeitbaren Feld in Bildschirmreihenfolge**, nicht stets zum ersten Formularfeld.
- Unterstützte Fehlerverträge: FastAPI `{detail:[{loc:['body',field],msg}]}` und standardisierte `{error:{message,details:[{field,message}]}}`. Die API reicht die FastAPI-Feldinformationen jetzt zusätzlich zum bestehenden Gesamttext durch.
- Unbekannte, verschachtelte, versteckte oder fremde (z. B. Query-) Felder werden nicht einer falschen Eingabe zugewiesen. Die allgemeine Server-Fehlermeldung bleibt erhalten; bei FastAPI-Listen enthält sie die einzelnen Detailtexte, bei standardisierten Fehlerantworten nur die vom Server gelieferte Zusammenfassung. Ohne eindeutige Feldzuordnung führt `Eingaben prüfen` wie bisher zum ersten bearbeitbaren Feld.
- Bei Änderung eines betroffenen Feldes verschwindet nur dessen veralteter Inline-Fehler, nicht der anderer Felder. Erneuter Klick auf `Speichern` bleibt eine bewusste Benutzeraktion; kein Auto-Retry.
- Keine Änderungen an fachlichen Berechnungen, Rollen, Backend-Verträgen, Entwurfs-Persistenz oder Datenbankmigrationen.

## Nachweise

- `npm.cmd run test -- src/test/FormValidationFeedback.test.js src/test/FormFeedbackRecoveryQol.test.jsx src/test/api.test.js src/test/FormModal.test.jsx src/test/WorkspaceForms.test.jsx src/test/ListFormLifecycle.test.jsx src/test/FirstDay.test.jsx src/test/QolRound4.test.jsx src/test/translations.test.js --maxWorkers=1 --no-file-parallelism`: **94/94 Tests bestanden** (9 Dateien).
- `npm.cmd run lint`: bestanden.
- `npm.cmd run build`: bestanden. Bekannte, unveränderte nicht-blockierende Warnung `INEFFECTIVE_DYNAMIC_IMPORT` für `NotificationInbox.jsx`.
- Reale Microsoft-Edge-Chromium-Headless-Läufe, isoliert auf `127.0.0.1:5179` mit temporärer Vite-Testoberfläche und **simulierten API-Antworten**: `validation` **PASS** (Feld-ID, Fehlerassoziation, Fokus, Eingabeerhalt, de/en/es); `recovery` **PASS** (Bestätigungsabbruch ohne Delete, Wiederherstellen, Fokus, kein fachliches Save und kein Delete). Testseite und lokaler Testserver danach entfernt/beendet.
- Test-Szenarien benutzten keine echten Zugangsdaten, produktiven Nutzer, fachliche Datensätze oder laufenden Installationen.

## Vor Release weiterhin separat

Eine manuelle Screenreader- und Tastaturabnahme (inklusive echter Tab-Reihenfolge), reale Backend-/Provider-Vertragsprüfung, Test an echten kleinen Displays sowie vollständige Plattform-/PostgreSQL-Abnahme sind durch diese Browser-Smokes nicht ersetzt. Bestehende fremde Backend-Migrationsänderungen blieben unberührt.
