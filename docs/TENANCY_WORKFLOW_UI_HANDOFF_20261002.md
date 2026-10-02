# P1/P2 Frontend Handoff – Mieterwechsel

Stand: 2. Oktober 2026

## Basis und Abgrenzung

- Arbeitsbasis: `7ccee8ca4518966d1dbb07ef625eb31d2133337a`
- Branch: `assist/tenancy-workflow-ui`
- Worktree: `C:\Users\matth\Documents\Codex\2026-10-01\wi\work\tenancy-workflow-ui`
- Verbindlicher Vertrag: `docs/TENANCY_WORKFLOW_CONTRACT_20261002.md`
- Root-Integrationsworktree, Main, Preview sowie bestehende Lifecycle-/Korrespondenzkomponenten wurden nicht als Arbeitsziel benutzt oder verändert.

## Implementiertes Sourceartefakt

Neue Seite `/tenancy-workflows` mit zwei Arbeitsbereichen:

1. **Objektbezogene Vorlagen/Versionen**
   - getrennte Ein-/Auszugsrichtung;
   - Objekt- und optionale Einheitsabweichung;
   - Versionsliste und Draft-Stepeditor;
   - Pflicht/optional;
   - vier feste Terminanker `previous_contract_end`, `next_contract_start`, `move_out_handover`, `move_in_handover`;
   - Versatz in Tagen;
   - Verantwortung als aktiver konkreter Benutzer **oder** Rolle; UI löscht das jeweils andere Feld;
   - Abhängigkeiten über stabile Step-Keys;
   - Belegregeln `none|document_original|handover_protocol|meter_reading`;
   - Publikation nur, wenn die serverberechnete Action `publish_template` vorliegt.

2. **Wechselakte**
   - Cursorliste und Detailakte;
   - Start als `move_out|move_in|turnover`;
   - bisheriger/neuer Vertrag und Übergabetermine bleiben getrennt;
   - Start als Preview→Confirm mit unverändertem `preview_hash` und übernommenen Quell-ETags;
   - Checkliste mit blocked/open/in_progress/completed/not_applicable, Originalfälligkeit, aktueller Fälligkeit, Task-ID und Beleganzahl;
   - `not_applicable` verlangt einen nichtleeren bewussten Grund;
   - Terminverschiebung als Reanchor Preview→Confirm; kein direktes Taskverschieben im Browser;
   - Step-Abschluss über den fachlichen Step-Endpunkt, nicht über allgemeines Task-CRUD;
   - Task-Projektion über `POST .../steps/{step_id}/task`;
   - Belegverknüpfung über den fachlichen Evidence-Endpunkt;
   - Dokumentoriginale wählen zuerst ein berechtigtes Dokument und anschließend eine konkrete immutable `document_version_id` aus der vorhandenen paginierten Versionshistorie;
   - Aktenabschluss nur bei aktueller serverseitiger Action `complete_change`.

## CAS, Idempotenz und unklare Antworten

Alle zustandsändernden Workflowbefehle werden im Frontend mit `idempotency_key` und `expected_revision` aufgebaut. Bei Netzwerkfehler oder 5xx bleibt exakt dasselbe Payload-Objekt gespeichert und kann über „Exakten Befehl erneut senden“ erneut gesendet werden. 409/412 erzeugt dagegen nur die Aufforderung zum bewussten Neuladen; es gibt keinen stillen Replay mit erneuerter Revision.

`actions` wird defensiv sowohl als Namensliste als auch als boolesches Fähigkeitsobjekt gelesen. Die Fähigkeit steuert nur die Sichtbarkeit; der Server bleibt für jede Mutation autoritativ.

## Bounded Referenzwahl

`CursorReferencePicker` lädt 25 Einträge pro Seite und übernimmt opake Cursor unverändert. Für vorhandene Legacy-Referenzlisten (Immobilien, Einheiten, Verträge, Benutzer, Dokumente) gibt es einen begrenzten Skip/Limit-Adapter, der späte Seiten nachladen kann. Dokumentversionen verwenden die vorhandene `before/next_before`-Historie und werden in denselben Picker adaptiert.

Die Workflowlisten selbst verwenden ausschließlich `{items,next_cursor,has_more}` und den opaken `after`-Cursor des neuen Vertrags.

## Responsive / Sprache

- Eigene responsive Darstellung mit Breakpoints für <= 900 px, <= 520 px und explizit <= 360 px.
- Formulare/Belegsteuerung werden auf schmalen Ansichten einspaltig; Referenzpicker stapeln auf 360 px.
- Arbeitsoberfläche besitzt DE/EN/ES-Texte; Navigation enthält für alle drei Sprachen den neuen Eintrag.

## Geänderte/Neue Dateien

- `frontend/src/pages/TenancyWorkflows.jsx`
- `frontend/src/pages/TenancyWorkflows.css`
- `frontend/src/components/CursorReferencePicker.jsx`
- `frontend/src/tenancyWorkflowApi.js`
- `frontend/src/tenancyWorkflowText.js`
- `frontend/src/test/TenancyWorkflow.test.jsx`
- `frontend/src/App.jsx` (nur lazy route + Route)
- `frontend/src/components/Layout.jsx` (nur Navigationseintrag)
- `frontend/src/i18n.jsx` (nur Navigationslabel DE/EN/ES)
- `docs/TENANCY_WORKFLOW_UI_HANDOFF_20261002.md`

## Präzise Backendabhängigkeiten vor Live-Abnahme

Der verbindliche Vertrag legt Routen und Response-DTOs fest, aber nicht für jeden Command das vollständige Request-Schema. Die UI hat deshalb folgende eng begrenzte Annahmen, die mit dem Backendautor vor Merge abgeglichen werden müssen:

1. `POST /tenancy-changes/{change_id}/steps/{step_id}/task` erhält nur den Command-Envelope (`idempotency_key`, `expected_revision`) und erzeugt/verknüpft die kanonische Task-Projektion serverseitig. Falls der Backend-Command zusätzliche explizite Felder verlangt, muss nur `linkTask()` angepasst werden.
2. `POST .../evidence` erhält den Command-Envelope plus `evidence: EvidenceLinkInput`. Für `document_version` sendet die UI zwingend `kind, document_id, document_version_id`; für die anderen Arten `kind` plus `handover_protocol_id` bzw. `meter_reading_id`.
3. Create-/Publish-/PUT-Commands der Vorlagen verwenden denselben allgemeinen Command-Envelope. Der Backendautor muss bestätigen, ob bei Neuanlage `expected_revision: null` akzeptiert wird oder ein separater Create-DTO ohne Revision vorgesehen ist.
4. Start- und Reanchor-Bestätigung senden `preview_hash` und `source_etags` (Fallback auf `original_source_etags`). Der endgültige Backendfeldname für die Quellstände muss exakt mit diesem Vertrag abgeglichen werden.
5. Der Vertrag fordert vollständige Referenzwahl, definiert aber keine neuen Suchendpunkte für Benutzer/Verträge/Dokumente/Zähler. Die UI kann vorhandene paginierte Listen vollständig nachladen; serverseitige Suchfilter können später in den Loader eingesetzt werden, ohne den Picker zu ändern.
6. Der Backend-Branch ist in diesem Worktree nicht integriert. Deshalb wurden keine Live-HTTP- oder Browser-End-to-End-Behauptungen für die neuen Workflowrouten gemacht.

## Tatsächlich ausgeführte Prüfungen

Mit versionsgleichem `package-lock.json`; im isolierten Worktree wurde für die Ausführung lediglich eine lokale `node_modules`-Junction auf die vorhandene Installation verwendet.

- Gezielter ESLint auf allen geänderten JS/JSX-Dateien mit `--max-warnings=0`: **bestanden**, keine Ausgabe/Fehler.
- `npm.cmd test -- TenancyWorkflow.test.jsx`: **4 Tests bestanden**.
  - exakter Command bleibt bei Unknown Success identisch;
  - Step-Abschluss trägt die gelesene Step-Revision;
  - bounded Picker folgt dem gelieferten Cursor;
  - 409/412 und Netzwerk/5xx werden korrekt getrennt.
- `npm.cmd run build`: **bestanden**, Vite 8.1.0, 655 Module transformiert.
- Der erste globale `npm run lint`-Versuch ohne Worktree-`node_modules` scheiterte ausschließlich an fehlender lokaler Toolauflösung. Ein anschließender globaler Lauf mit Junction wurde wegen Verzeichnisdurchquerung abgebrochen; deshalb ist nur der gezielte Lint oben als gültige Lint-Prüfung dokumentiert.

## Nicht behauptet

- keine produktive Featurebereitschaft ohne Backend-Handoff;
- keine Browser-/PostgreSQL-Abnahme der neuen Workflowrouten;
- keine Änderung an Main, Root-Preview oder Root-Integrationsworktree;
- keine Verarbeitung von Zugangsdaten oder TEHA-Daten.
