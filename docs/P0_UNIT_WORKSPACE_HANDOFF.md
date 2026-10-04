# P0 Einheitenakte: Übergabe

Stand: 2026-10-03, Branch `assist/p0-unit-workspace`, Ausgangsbasis `679c8de`.
Integration in den fortgeschrittenen Root erfolgt getrennt durch den Root-Agenten.

## Ergebnis

Die Detailansicht einer Einheit liest einen gezielten, berechtigten Workspace
statt der ersten 100 globalen Verträge/Versicherungen. Aktive Verträge,
vollständige Vertragshistorie und einheitsspezifische Versicherungen sind
unabhängig seitenweise erreichbar. Immobilie und Mietpartei gehören exakt zu
dieser Einheit. Mehrere aktive Verträge werden offengelegt. Die bestehenden
Monatsfelder `cold_rent`, `service_charge_advance` und `heating_advance` werden
richtig verwendet; positive, null und fehlende Werte sind unterscheidbar.

Unit-/Benutzer-/Rollen-/Scopewechsel verwerfen alte private Inhalte synchron;
verspätete Antworten werden verworfen, Requests abgebrochen. Fehler liefern
Retry und bei fortgeschrittenen Cursorseiten einen Neustart. Eine leere spätere
Live-Seite behauptet keinen globalen Leerstand. Lokale Beschriftungen sind auf
Deutsch, Englisch und Spanisch verfügbar. Layout und Stiländerungen betreffen
nur diese Seite.

## Anbindung

- `GET /api/v1/units/{unit_id}/workspace`, Parameter `page_size` (Standard 25),
  `active_cursor`, `history_cursor`, `insurance_cursor`.
- Antwort: `unit`, kleine `property`-Projektion, `active_contracts`,
  `contract_history`, `insurances`; Seiten mit `items`, `has_more`, `next_cursor`.
- Bestehenden Vertragsworkspace und seine Cursor wiederverwendet. Versicherungen
  verwenden den vorhandenen signierten Referenzcursor, gebunden an Einheit,
  Immobilie, Seitengröße und Benutzer-/Portfolio-Scope.
- SQL-Reader liest fünf Fach-SELECTs, davon drei begrenzte Sammlungen; Filter
  wirken vor LIMIT, keine globalen Listen/COUNTs oder Autoflush. Memory hält
  begrenzte Seiten. Elternkontext wird erneut geprüft, aktuelle Auth-/Scope-
  Prüfung direkt vor Veröffentlichung über `CheckedPublicationRoute`.
- Nur zwei Zeilen Anbindung im bestehenden `backend/routers/units.py`; neue
  eigene Router-/Servicemodule. Keine Schemaänderung oder neue Abhängigkeit.
- Monatspreise sind explizit gespeicherte Einheitenwerte, keine behauptete
  historische Vertragsmietberechnung. Gespeicherter Einheitenstatus wird nicht
  stillschweigend aus einem Vertragsstatus überschrieben. Versicherungen ohne
  `unit_id` werden nicht als einheitsspezifische Versicherung ausgegeben.

## Nachweise auf diesem Sourcezustand

| Gate | Ergebnis |
| --- | --- |
| `test_unit_workspace.py`, `test_unit_workspace_postgres.py`, bestehendes `test_contract_workspace.py` gemeinsam | **97 bestanden, 2 erwartete Memory-Skips**, 355,79 s. SQLite, Memory und zwei tatsächliche PostgreSQL-Fälle mit eigenen temporären Schemas. Skips betreffen ausschließlich SQL-Identitymap-/Autoflush-Prüfungen im Memory-Parameter. |
| `UnitOverview.test.jsx` nach letzter UI-Änderung | **13 bestanden**, 11,64 s gesamt. Exakte Namen/Beträge, unabhängige Historyseiten, alte Antworten/Identitäten, sichtbarer Fehler/Retry und leere spätere Seite. |
| `unit-workspace.pw.mjs` nach letzter UI-Änderung | **1 bestanden**, 13,2 s inklusive Browserstart; tatsächlicher Edge, eigene neu migrierte SQLite-App. 27 Verträge, Seiten 25+2, unveränderter aktiver Abschnitt, keine globalen Vertrags-/Mieter-/Versicherungslistencalls, Fehler 503 mit Wiederholung, verständliche Typ-/Statusnamen, 1440-/390-Pixel-Ansicht. |
| Ruff | Neue Backendmodule, zwei Backendtests und Routeranbindung ohne Befund. |
| Mypy Ziel 3.11 und 3.12 | Jeweils beide neuen Backendmodule ohne Befund. |
| ESLint | Geänderte Detailseite, eigener Hook/Text, UI-Test und Browsertest ohne Befund. |
| Produktionsbuild | Erfolgreich, auch durch den finalen isolierten Browsertest neu gebaut. |
| `git diff --check` | Ohne Whitespacefehler. |

Runtime der Backendtests war die vorhandene Python-3.14-Umgebung; Typziele 3.11
und 3.12 sind keine behaupteten separaten Runtime-Läufe. Die PostgreSQL-Fixture
migriert das benötigte eigene Schema bis `a2a2b3c4d5e6`; der Browserlauf migriert
eine leere SQLite-Datenbank durch die vollständige Kette bis zum Branch-Head
`c2a2b3c4d5e6`. Eine bestehende Starlette/httpx-Deprecation-Warnung bleibt.

Lokale Belege:

- `../p0-unit-workspace-composed.log` (kombiniertes Backend-Gate).
- `unit-workspace-ui.log`, `unit-workspace-e2e.log` im Worktree.
- `frontend/test-results/unit-workspace.pw.mjs-unit-36dbb-es-errors-and-mobile-layout/`
  mit `unit-workspace-1440.png` und `unit-workspace-390.png`.
  Beide Größen wurden visuell geprüft, ohne horizontalen Überlauf.

Der Browserlauf hat nur seine eigene synthetische Datenbank und seinen eigenen
Server verwendet. Bestehender Hauptserver, Daten, Housing, Integrationen,
Billing und globale Styles wurden nicht geändert. `frontend/node_modules`
ist lediglich eine ignorierte Junction auf die bereits installierten Root-
Abhängigkeiten; kein neu eingeführtes Repositoryartefakt.

## Nächster Lieferumfang

`P0_LEGACY_LIST_ROLLOUT.md` beschreibt die Folgearbeiten mit aktuellen
Fundstellen, API-/Cache-/Tabellenvertrag und Abnahmen. Reihenfolge:
Einheitenliste → Dokumente → Instandhaltung → Kontakte/Mietparteien → übrige
Finanz-/Zählerlisten. Die erste gemeinsame Extraktion folgt erst auf zwei
nachgewiesene Fachadapter. Keine der übrigen Seiten wurde in diesem Paket
vorgezogen. Das Paket behauptet keinen bereits gemessenen 100.000-Zeilen-
Lasttest oder unveränderliche Snapshots für live geblätterte Seiten.
