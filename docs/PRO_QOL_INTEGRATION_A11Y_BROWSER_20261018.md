# ImmoManager Pro – QoL: integrierter Frontend- und Browser-Gate

Stand: 18. Oktober 2026, isolierter Prüfzweig `pro/qol-integration-qa-20261017`.
**Entwicklungsnachweis – keine Integrations- oder Produktivfreigabe.**

## Ausgangslage und sichere Zusammenführung

- Ausgangspunkt war der neuere QoL-Entwicklungsstand `fa558fab` auf `pro/full-handover-20261016` mit Feldvalidierung, Formular-Entwurfsrettung und bereits vorhandenen Bulk-Aktionsverbesserungen.
- Der separat geprüfte React-Warnungs- und Browser-QA-Commit `f9688419` wurde per konfliktfreiem Cherry-pick als `adffb873` auf einen **neuen, sauberen Worktree** übernommen. Die ursprüngliche QA-Fassung und der zentrale Integrations-Checkout wurden nicht verändert.
- Die fünf im ursprünglichen Entwicklungsworktree vorliegenden offenen Backend-/Migrationstest-Änderungen wurden nicht in den QA-Worktree kopiert; der QA-Commit enthält keine Backend-Migration oder produktive Anwendungskomponente.
- Frontend-Abhängigkeiten wurden im QA-Worktree separat aus dem lokalen npm-Cache installiert: `npm.cmd ci --offline --no-audit --no-fund` (Exit 0, 283 Pakete). Kein Junction- oder Vite-Dateifreigabe-Workaround nötig.

## Vollständiger Frontend-Gate auf dem kombinierten Quellstand

- `npm.cmd run test -- --maxWorkers=1 --no-file-parallelism`: **731/731 Tests bestanden, 111/111 Testdateien bestanden, 0 fehlgeschlagen, Exit 0.** Dabei **0 React-`act(...)`-Warnungen und 0 React-Listenschlüssel-Warnungen**.
- `npm.cmd run lint`: **bestanden, Exit 0**.
- `npm.cmd run build`: **bestanden, Exit 0**. Weiterhin ein nicht-blockierender, bereits bekannter Vite-Hinweis `INEFFECTIVE_DYNAMIC_IMPORT` für `NotificationInbox.jsx`.
- Der Prüfzweig testet die früheren Tabellen-QoL-Verbesserungen und die neueren Formularänderungen gemeinsam; er ist keine Datenbank-, Live-Anbieter- oder Serverfreigabe.

## Unabhängige Browser-Matrix (synthetische Datensätze)

Ein ausschließlich lokal gebundener, temporärer Vite-Server (`127.0.0.1:5182`) lieferte eine synthetische Tabelle mit drei Vorgängen. Playwright prüfte **Chromium und Microsoft Edge** bei **320, 360 und 1440 Pixel Breite**, jeweils mit `de-DE` und `Europe/Berlin`: **66/66 technische Browserassertionen bestanden (11 pro Kombination)**.

Geprüft: alle Zeilen sichtbar; gleichnamige Aktionsschaltflächen behalten ihren Namen; datensatzbezogene `aria-description` sowohl im DOM als auch in den tatsächlichen Browser-Accessibility-Trees; Aktion per Enter; Zeilenöffnung per Leertaste; Auswahlfilter dedupliziert `1` und `"1"`; lokaler Endtag `2026-10-17` einschließlich `23:40`, ohne Einträge vom `18.10.`; kein globales horizontales Überlaufen bei 320/360/1440 Pixel; keine unbehandelten Seitenfehler.

- Prüfskript: `C:\Temp\immo-qol-edge-chromium-matrix-20261017.mjs`; Protokoll: `C:\Temp\immo-qol-browser-matrix-20261017.log`. Beide bleiben ausschließlich lokal außerhalb des Git-Commits.
- Temporäre Vite-Testseite und Testkomponente wurden gelöscht, der Entwicklungsserver beendet und Port `5182` geschlossen. Es wurden keine echten Nutzer, Datenbanken, Konten oder externen Dienste verwendet.
- Auch Edge verwendet Chromium: Dies sind zwei Browserprodukte, **keine zwei unabhängigen Rendering-Engines**. Firefox und Safari sind noch nicht abgenommen.

## Screenreader-Grenze und nächster Abnahmeschritt

Windows Narrator ist als Systemprogramm vorhanden. NVDA und JAWS wurden an den üblichen Installationsorten nicht gefunden. Zur Vermeidung einer ungefragten Veränderung des interaktiven Windows-Desktops wurde Narrator **nicht** automatisch eingeschaltet oder als echte Sprachausgabeprüfung ausgegeben.

Die manuelle Screenreader-Abnahme bleibt offen: Tabellenüberschrift und Spalten ansagen lassen; nacheinander zwei gleichnamige Aktionen auf verschiedenen Datensätzen ansteuern und Name **plus richtigen Datensatzkontext** prüfen; mit Tab, Shift+Tab, Enter und Leertaste navigieren; aktivierte Spalten- und Datumsfilter, Fokus bei Escape, 320-/360-Pixel-Ansicht und Löschaktionen überprüfen. Die technische Browser-Accessibility-Tree-Prüfung ersetzt nicht die beobachtete Ansage durch einen Screenreader.

## Freigabegrenze

Der zentrale Integrations-Checkout `claude-review-20261013` blieb auf `04021da5`. Produktive Installationen, Migrationen, echte Anbieter und Nutzerdaten wurden nicht angefasst. Der neue QA-Zweig ist zur unabhängigen Code- und Screenreader-Prüfung vorbereitet, **nicht zur Produktion freigegeben**.
