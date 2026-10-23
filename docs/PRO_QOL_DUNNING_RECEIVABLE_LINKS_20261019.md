# ImmoManager Pro – QoL: Mahnakten, Forderungen und Konten verknüpfen (19.10.2026)

**Isolierter Frontend-Checkpoint; nicht ausgerollt.** Ausgangspunkt: Branch `pro/full-handover-20261016`, Commit `63d14a20`. Keine Backend-Dateien bearbeitet.

## Befund und Umsetzung

- Die Vertrags-Mahnakte hatte nur einen Rücklink zur allgemeinen Mahnübersicht. Das Backend liefert im `contract_file`-Ergebnis eine **belastbare Vertrags-ID und Mieter-ID**, aber Immobilien- und Einheitenangaben nur als **Anzeigenamen** (nachgelesen in `backend/services/dunning.py`). Folglich werden aus diesen Anzeigenamen **keine IDs abgeleitet**.
- Die Mahnakte zeigt nun die gemeinsame, benannte und responsive `RelatedPageLinks`-Leiste mit nativen React-Router-Links zum **konkreten Mietvertrag** (`/contracts?contract_id=...`) und zu **dessen Forderungen** (`/receivables?contract_id=...`). Nur bei gelieferter `tenant_id` kommen **Mieterkonto** (`/tenants/:id/account`) und **Buchungen dieses Mieters** (`/bookings?tenant_id=...`) hinzu. Alle IDs werden URL-encodiert.
- Die Forderungsliste verlinkt den Vertrag anhand der geladenen Vertragsdaten. Ist ein `dunning_level` vorhanden, führt ein zusätzlicher Link zum bestehenden **vertragsbezogenen Mahnaktenpfad** (`/dunning/contracts/:contractId`). Bei einer fehlenden zugeordneten Vertragsakte bleibt die Zeile sichtbar, es entsteht aber **kein irreführender Link**.
- Die gesonderte `receivablesLinks.css` hält Vertragsnummer und Mahnaktenlink optisch unterscheidbar und umbruchfähig; bei höchstens 480 px erhalten die Linkziele mindestens 44 px Höhe und sichtbare Tastaturfokusrahmen.
- `dunningText` stellt die neuen Navigationsbeschriftungen in **Deutsch, Englisch und Spanisch** bereit. Vorhandene Schreibrechte, Forderungsfilter, Statusberechnung und Mahn-/Buchungs-/Entwurfsaktionen wurden nicht verändert.

## Tatsächlich durchgeführte Qualitätssicherung

- Fokusprüfung: `npm.cmd run test -- src/test/Dunning.test.jsx src/test/DunningReceivablesLinks.test.jsx src/test/EntityLinks.test.jsx src/test/WorkspaceSources.test.jsx --maxWorkers=1 --no-file-parallelism`: **29/29 bestanden**.
- Erweiterte Regression: `npm.cmd run test -- src/test/Dunning.test.jsx src/test/DunningReceivablesLinks.test.jsx src/test/WorkspaceSources.test.jsx src/test/EntityLinks.test.jsx src/test/FinancePrecision.test.jsx src/test/FinancePackagesV2.test.jsx src/test/TenantAccount.test.jsx src/test/BookingReviewWorkflow.test.jsx src/test/ServiceContracts.test.jsx src/test/MaintenanceProject.test.jsx src/test/PropertyDossier.test.jsx src/test/PartyUnitNavigation.test.jsx src/test/ShellNavigation.test.jsx src/test/WorkspaceNavigation.test.jsx src/test/RelatedPageLinks.test.jsx src/test/ContractsTenantCache.test.jsx src/test/ListWorkspace.test.jsx src/test/translations.test.js --maxWorkers=1 --no-file-parallelism`: **135/135 bestanden, 18 Testdateien**.
- `npm.cmd run lint`: erfolgreich. `npm.cmd run build`: erfolgreich. Bekannte, nicht blockierende Warnung `INEFFECTIVE_DYNAMIC_IMPORT` zu `NotificationInbox.jsx` bleibt bestehen.
- Microsoft Edge Chromium Headless mit **tatsächlich gerenderter Mahnaktenkomponente**, ausschließlich simulierten GET-Antworten und schreibgeschützter Browser-Testrolle: **PASS** bei 320, 375 und 1280 px. Kein globaler Seiten- oder Linkleistenüberlauf; mobile Linkhöhe gemessen: mindestens **44 px**. Die Forderungstabelle scrollt bei Bedarf innerhalb ihres Containers. Echtes `Enter` öffnete den korrekten Vertrags-Forderungsfilter; der Smoke registrierte **0 fachliche Schreibaufrufe**.
- Die neue Forderungstabellen-Darstellung wurde per Vitest mit der echten DataTable-Komponente getestet. **Keine gesonderte native Edge-Layoutmessung dieser Tabelle**. Der Browser-Smoke verwendet synthetische Daten und ersetzt **keinen** echten Backend-/Provider-End-to-End-Test.
- Lokaler Vite-Testserver, temporäre Edge-Testseite, CDP-Testtreiber und isolierter Browserprozess wurden nach der Prüfung beendet beziehungsweise entfernt.
- `git diff --cached --check` sowie exklusives Staging ausschließlich der zugehörigen Frontend-, Test- und Dokumentationsdateien vor Commit vorgesehen und abschließend verifiziert.

## Offene Abnahme und Abgrenzung

- Die bereits bestehenden React-`act()`-Warnungen in Immobilien-/Listen-Tests und eine `key`-Warnung in `ContractsTenantCache` bleiben als separate Testqualitätsthemen; alle ausgewählten Tests bestehen.
- Manuelle NVDA-/JAWS-/VoiceOver-Prüfung, vollständige mobile Geräteabnahme und E2E mit echtem Backend/PostgreSQL bleiben für eine Releasefreigabe offen.
- **Kein Merge und kein Deployment.** Die fünf vorbestehenden fremden Backend-Migrations- und Backend-Teständerungen sowie Integrationszweig und laufende Installationen bleiben unangetastet.
