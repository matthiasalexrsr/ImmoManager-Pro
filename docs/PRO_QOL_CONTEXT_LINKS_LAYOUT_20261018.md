# ImmoManager Pro – QoL: Seitenverknüpfungen und responsive Layouts (18.10.2026)

**Isolierter Entwicklungs-Checkpoint, kein Deployment.** Ausgangspunkt: `pro/full-handover-20261016`, Commit `4c7933ee`. Weiterführung der bisherigen Form-/Entwurfs-/Navigations-QoL-Serie.

## Beobachtete Lücken und Verbesserungen

- Die Immobilienakte verwaltete ihre aktive Unterseite bisher nur in flüchtigem React-State: Ein Link von einer anderen Seite konnte nicht zuverlässig direkt zu `Verträge`, `Finanzen` usw. führen. Jetzt ist der aktive Abschnitt URL-basiert: `/properties/:id?tab=units|contracts|finance|documents|maintenance|timeline`. Fehlende oder ungültige `tab`-Werte zeigen sicher die Übersicht. Umschalten respektiert vorhandene andere Query-Parameter und Browser-Zurück/Vorwärts. Die Abschnittsschaltflächen besitzen `aria-pressed` und eine benannte Navigation.
- Das neue wiederverwendbare `RelatedPageLinks` zeigt **echte interne Router-Links** mit eigenen Zieladressen, Tastaturfokus und browserüblichem Öffnen in neuen Tabs. Nichtinterne und fehlende Ziele werden ausgelassen.
- Immobilienakte: Verbindungen zu den ausdrücklich vorhandenen Bereichen **Buchungen dieser Immobilie** (`/bookings?property_id=...`), Mietübersicht, alle Einheiten und alle Verträge. Im Finanzabschnitt bleibt die bisherige spezielle Finanznavigation bestehen; die neue Leiste wird dort nicht zusätzlich dupliziert.
- Einheitenakte: Direkter Sprung zu den Vertrags- und Finanzabschnitten der zugehörigen Immobilie; bei vorhandener Beziehung präzise Links auf **den Mietvertrag** (`/contracts?contract_id=...`) und **das Mieterkonto** (`/tenants/:id/account`). Die Nummern der Vertragsgeschichte sind ebenfalls verlinkt. Für Leerstände werden keine erfundenen Vertrags- oder Mieterkontolinks angezeigt.
- Mieterkonto: Vertragsnummern öffnen den konkret referenzierten Vertrag; unzugeordnete Buchungen öffnen über ihre eindeutige ID `/bookings?booking_id=...` statt nur den Suchbegriff. Zusätzlich ein Link zu den Buchungen des betreffenden Mieters (`/bookings?tenant_id=...`) und zur Vertragsübersicht.
- Immobilienvertragstabelle und Instandhaltungsliste: Vertragsnummern sowie Titel sind echte Tastatur-Links auf vorhandene ID-basierte Ziele; die bisherigen Zeilenaktionen bleiben erhalten.
- Die Links verwenden URL-Encoding für nichttriviale IDs. Es wurden **keine** neuen Serverrouten, Datenformate, Domain-Berechnungen, Lösch- oder Schreibaktionen eingeführt.

## Layout / Barrierearme Navigation

- Neues konsistentes, umbruchfähiges Linklayout auf den betreffenden Detailseiten mit klarem Fokusrahmen.
- Bis 480 px: einspaltige Linkliste; bei 481–640 px ein mobil geeignetes Grid; ab 641 px flexibles Desktoplayout. Tippelemente auf kleinen Bildschirmen mindestens 44 px hoch.
- Immobilienabschnitte bleiben bei schmalen Viewports horizontal scrollbar, ohne die ganze Seite horizontal zu erweitern; fokussierte Tabs erhalten einen sichtbaren Fokusrahmen.
- Das responsive Verhalten wurde in **echtem Edge Chromium Headless** bei 320 px, 375 px und 1280 px (jeweils Viewport) gemessen: kein horizontaler Dokumentüberlauf, keine überlaufende Linkleiste, Linkhöhe bei 320/375 px 44 px, Tastatur-`Enter` navigiert zu `/properties/p1?tab=contracts`. Prüfoberfläche mit repräsentativen Navigations- und Abschnittselementen, **keine vollständige Browser-Akzeptanz der Daten-/Layoutseiten mit Live-Backend**.

## Test- und Buildstand

- `npm.cmd run test -- src/test/RelatedPageLinks.test.jsx src/test/EntityLinks.test.jsx src/test/PropertyDossier.test.jsx src/test/PartyUnitNavigation.test.jsx src/test/TenantAccount.test.jsx src/test/ShellNavigation.test.jsx src/test/WorkspaceNavigation.test.jsx src/test/ListWorkspace.test.jsx src/test/ContractsTenantCache.test.jsx src/test/BookingReviewWorkflow.test.jsx src/test/BookingReviewIndependent.test.jsx src/test/ServiceContracts.test.jsx --maxWorkers=1 --no-file-parallelism`: **88/88 bestanden in 12 Testdateien**.
- `npm.cmd run lint`: erfolgreich.
- `npm.cmd run build`: erfolgreich, weiterhin bekannte, nicht blockierende Warnung `INEFFECTIVE_DYNAMIC_IMPORT` zu `NotificationInbox.jsx`.
- Git-Staging ausschließlich eigener 13 Dateien; `git diff --cached --check` vor Commit.
- Bestehende React-`act()`-Warnungen in `PropertyDossier`/`ListWorkspace`-Tests und eine `key`-Warnung aus `ContractsTenantCache` bei ansonsten bestandenen Tests. Diese separaten Test-/Renderingprobleme wurden nicht mit der Navigationsänderung vermischt.

## Grenzen

Keine Freigabe für Produktions-Deployment, keine manuelle Screenreader-Abnahme, keine echten Backend-/Provider-/PostgreSQL-Integrationstests in dieser Serie. Fünf bereits offene, fremde Backend-Migrations- und Testdateien bleiben **unangetastet und uncommittet**; keine Änderung am zentralen Integrationszweig oder laufenden Installationen.
