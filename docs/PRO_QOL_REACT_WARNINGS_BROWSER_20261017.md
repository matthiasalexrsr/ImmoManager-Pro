# ImmoManager Pro – QoL: React-Testwarnungen und isolierte Chromium-Abnahme

Stand: 17. Oktober 2026. Isolierter Fortsetzungszweig `pro/qol-warnings-browser-20261017` ab `93480c04` (enthält den ursprünglichen Checkpoint `ff99f4f6`). **Kein Release, keine Migration und kein Zugriff auf produktive Nutzerdaten.**

## Ausgangsbefund und Korrektur

Die komplette, vor dieser Etappe erneut durchlaufene Vitest-Matrix war weiterhin grün (720/720 Tests, 109/109 Dateien), meldete aber 13 React-`act(...)`-Warnungen und drei Warnungen zu fehlenden Listenschlüsseln. Die Warnungen wurden anhand der betroffenen Testdateien reproduziert und nicht per `console`-Mock oder pauschaler Unterdrückung ausgeblendet.

- Zwei Vertrags-/Parteitests verwendeten unvollständige Übersetzungs-Mocks: Für die Aktion „Bewohner“ fehlte das Label, sodass im gerenderten Aktionsarray kein eindeutiger Schlüssel entstand. Die Mocks enthalten nun dieses Label.
- Der Einstellungskatalog-Mock lieferte irrtümlich Einstellungsdatensätze ohne Sitzungs-ID an `/auth/users/me/settings/sessions`. Ein eigener Antwortzweig liefert dafür eine leere Sitzungsliste; die echten Einstellungstests behalten ihre Prüfwerte.
- Asynchrone React-Updates nach Tastatur-, Register-, Filter-, Navigations- und Auswahlaktionen werden in den betroffenen Tests durch das Beobachten des tatsächlichen Ergebnisses oder `act(async ...)` abgeschlossen. Betroffen sind Parteiakte, Immobilienakte, Dashboard, Immobilienlisten, Nachrichten, Kommunikation und Arbeitszentrale.

**Gezielte Verifikation:** 18/18 Schlüssel-Tests, 34/34 Partei-/Immobilien-Tests und 55/55 weitere React-Ablauftests erfolgreich. In diesen drei wiederholten Paketen keine der zuvor beobachteten React-Warnungen.

## Unabhängige Browserprüfung (synthetische Daten)

Auf Port `127.0.0.1:5180` wurde ausschließlich ein temporärer Vite-QA-Einstieg mit drei erfundenen Vorgängen geladen. Playwright startete den lokal installierten Chromium-Browser mit `locale=de-DE` und `timezoneId=Europe/Berlin`. Ergebnis: **14/14 Browser-Checks bestanden**.

Geprüft wurden drei sichtbare Zeilen; unveränderte Schaltflächen-Namen; zwei unterscheidbare `aria-description`-Texte **auch im tatsächlichen Chromium-Accessibility-Tree (CDP)**; Aktivierung einer Tabellenaktion per Enter; Öffnen einer Tabellenzeile per Enter; Deduplizierung von Zahl `1` und Text `"1"` im nativen Auswahlfilter; korrekte Auswahlmöglichkeiten; inklusive Datumsgrenze „Bis 2026-10-17“ einschließlich 23:40 Uhr; Ausschluss des Folgetags 18.10.; sowie keine unbehandelten Browser-Fehler.

Die temporären Frontend-Testdateien wurden nach dem Browserlauf entfernt. Das Testskript liegt lokal unter `C:\Temp\immo-qol-isolated-browser-20261017.mjs`, der Screenshot unter `C:\Temp\immo-qol-isolated-chromium.png`. Diese QA-Dateien sind **nicht** Teil des Commits. Der isolierte Entwicklungsserver wurde beendet.

## Qualitätsgates und Grenzen

- ESLint (`npm.cmd run lint`) erfolgreich, Exit 0.
- Vite-Produktionsbuild (`npm.cmd run build`) erfolgreich, Exit 0. Ein Hinweis zur gemischten dynamischen/statischen Einbindung von `NotificationInbox` ist ein nicht-blockierender Bundler-Hinweis.
- **Abschließende vollständige Frontend-Matrix im isolierten Worktree:** **721/721 Tests und 109/109 Testdateien bestanden, 0 Fehler, Exit 0; 0 React-`act(...)`-Warnungen und 0 Listenschlüssel-Warnungen.** Der zusätzliche Test gegenüber dem Ausgangsstand stammt aus dem bereits enthaltenen Bulk-Aktions-Checkpoint `93480c04`.
- Reproduzierbarer Prüfaufruf: `npm.cmd run test -- --maxWorkers=1 --no-file-parallelism` nach regulärer Installation der Frontend-Abhängigkeiten. In dieser isolierten Prüfung waren `node_modules` vorübergehend per Windows-Junction aus dem ursprünglichen Checkout eingebunden; deshalb war beim konkreten Lauf zusätzlich `--config vite-qol-verify.config.mjs` mit einer temporären Vite-Dateifreigabe erforderlich. Diese Hilfskonfiguration und die Junction sind nicht Teil des Commits.
- Die Browserprüfung testet DOM/ARIA-Attribute und Tastatur unter Chromium. Sie ersetzt **keinen tatsächlichen Screenreader-Test** (NVDA/JAWS/VoiceOver), keine weiteren Browser-Engines und keine Prüfung mit echten Anwenderdaten.
- Der Integrations-Checkout `claude-review-20261013` (HEAD `04021da5`), laufende Installationen und externe Anbieter wurden nicht verändert. Die fünf im ursprünglichen Checkout vorhandenen Backend-/Migrationstest-Änderungen wurden nicht in den isolierten Zweig übernommen. Ebenso ausgeschlossen sind später parallel entstandene Änderungen an `FormModal.jsx`, `workspace.css` und Übersetzungsdateien.

**Freigabe:** Nur isolierter Frontend-QA-Checkpoint, keine Produktivfreigabe.
