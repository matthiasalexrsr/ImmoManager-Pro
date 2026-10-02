# P1/P2 Frontend Handoff – Mieterwechsel

Stand: 2. Oktober 2026

## Arbeitsbereich und Abgrenzung

- UI-Worktree: `C:\Users\matth\Documents\Codex\2026-10-01\wi\work\tenancy-workflow-ui`
- Branch: `assist/tenancy-workflow-ui`
- ursprüngliche gemeinsame Basis: `7ccee8ca4518966d1dbb07ef625eb31d2133337a`
- vorheriger UI-Stand: `8fa4e645694983cfc6b48db18054f213563edac9`
- verbindliche Spezifikation: `docs/TENANCY_WORKFLOW_CONTRACT_20261002.md`
- Root-Integrationsworktree, Main, Preview, bestehende Lifecycle-/Korrespondenzdateien und der Core-Worktree wurden nicht verändert.
- Zugangsdaten und TEHA-Daten wurden nicht verwendet.

Der finale Commit, der diese Datei enthält, wird im Root-Handoff/Chat mit vollständiger SHA genannt.

## Aktuell gelesener Core-Sourcevertrag

Der Coreautor arbeitet weiterhin uncommittet in
`C:\Users\matth\Documents\Codex\2026-10-01\wi\work\tenancy-workflow-core`.
Deshalb ist nicht nur dessen Branch-HEAD, sondern der konkrete gelesene Dateistand relevant.

Read-only geprüft:

- `backend/services/tenancy_workflow_types.py`
  SHA-256 `97482DC0BA325EEF3166F9D5989013569C85CBFFA07D14808572182F7A116E86`
- `backend/routers/tenancy_workflows.py`
  SHA-256 `E20D805B4B25BA3C28896DB4E70AED53314B435C9E5036D2EFB88A565674B8EE`
- `backend/services/tenancy_workflow.py`
  SHA-256 `F7AC382BB45335BDF4368C71650BD46A3214AA4C0F20290E365F2A8E0D02C661`

Die UI bildet die dort sichtbaren DTOs und Responseformen ab:

- `CreateTemplate.expected_revision` und `StartTenancyChange.expected_revision` sind exakt `"new"`.
- `TemplateStepInput` verlangt **genau eine** Verantwortung: konkreter `assignee_user_id` **oder** `assignee_role`. Neue UI-Schritte starten deshalb mit einer Rolle; „keine feste Zuweisung“ ist kein editierbarer Zustand mehr.
- `CreateTemplateVersion`: `idempotency_key, expected_revision, based_on_version_id`.
- `UpdateTemplateVersion`: `idempotency_key, expected_revision, steps`.
- `PublishTemplateVersion`: `idempotency_key, expected_revision`.
- `StartTenancyChange`: Auswahlfelder plus `idempotency_key, expected_revision:"new", preview_hash, source_etags`.
- `ReanchorPreview`: `expected_revision` plus beide Übergabetermine.
- `ReanchorTenancyChange`: zusätzlich `idempotency_key, preview_hash, source_etags`.
- `UpdateStep`, `CreateStepTask`, `AddEvidence` und `RemoveEvidence` führen **beide** CAS-Stände: `expected_revision` des Schritts und `expected_change_revision` der Wechselakte.
- `UpdateStep` sendet für `not_applicable` einen bewussten nichtleeren `not_applicable_reason`; bei anderen Zuständen keinen Ausnahmegrund.
- `AddEvidence` sendet `evidence: EvidenceInput`; Dokumentbelege enthalten `document_id` und immutable `document_version_id`.
- `DELETE /tenancy-changes/{change_id}/steps/{step_id}/evidence/{link_id}` besitzt einen JSON-Body vom Typ `RemoveEvidence`; dafür wurde im gemeinsamen API-Client additiv `delJson` ergänzt.
- `CompleteTenancyChange`: `idempotency_key, expected_revision`.
- Create/Update/Publish Template liefern `WorkflowTemplateVersion`.
- Start/Reanchor/Complete/Patch Change liefern eine vollständige `TenancyChange`.
- Step/Task/Evidence-Mutationen liefern den aktualisierten `WorkflowStep`; der Core ändert dabei zugleich die Elternrevision der Wechselakte. Nach **bekannt erfolgreicher** Step-/Task-/Evidence-Mutation lädt der UI-Container deshalb die Wechselakte frisch per `GET /tenancy-changes/{id}`. Es wird keine Elternrevision aus einer Step-Response erfunden.
- Template-/Change-Listen verwenden `{items,next_cursor,has_more}` mit opakem `after`-Cursor.
- Server-`actions` bleiben die autoritative Fähigkeitsquelle für UI-Aktionen; der Server autorisiert jede Mutation erneut.

## Kanonische skalierbare Referenzsuche

Root implementiert den additiven Backend-Endpunkt in einem separaten
`work/workflow-references`-Arbeitsbereich. Der Frontendteil ist auf den verbindlich mitgeteilten Vertrag umgestellt:

`GET /api/v1/workflow-references/{kind}`

Kinds:

- `properties`
- `units`
- `contracts`
- `users`
- `documents`
- `handover-protocols`
- `meter-readings`
- `meters`

Queryparameter:

`search, property_id, unit_id, contract_id, direction, selected_id, cursor, page_size`

Response:

`{items,next_cursor,has_more,selected}`

Frontendverhalten:

- `BoundedReferencePicker` reicht Suchtext an `loadPage` durch; es findet **keine lokale Volltextfilterung** mehr statt.
- Jede Suchänderung verwirft den alten Cursor, bricht die veraltete Anfrage ab und startet mit `cursor=null`.
- „Weitere laden“ reicht den opaken Servercursor und denselben Suchtext unverändert weiter.
- `selected_id` wird bei jedem Request mitgegeben; `response.selected` hält eine bereits gewählte Referenz sichtbar, auch wenn sie nicht auf der aktuellen Trefferseite liegt.
- Es gibt keine browserseitige Gesamtbestandsgrenze.
- Benutzer werden mit `property_id` geladen; die UI erwartet nur minimale Felder wie `id, full_name, role` und verwendet keine E-Mail-/Tokenfelder.
- Verträge werden mit Objekt+Einheit gescopt.
- Dokumente, Übergabeprotokolle und Zählerstände werden mit Objekt, Einheit, fachlichem Vertrag und `direction` geladen.
- Finalisierte/richtungskonsistente Handover-/Meter-Reading-Auswahl wird vom Referenzendpunkt geliefert; die **finale Evidence-Validierung bleibt im Core**.
- Dokumente werden über die kanonische Referenzsuche gewählt; die konkrete unveränderliche Originalfassung wird weiterhin separat über `/documents/{id}/versions` gewählt.
- Die Workflowvorlagenliste selbst ist weiterhin der bestehende `/workflow-templates`-Cursorvertrag ohne `search`; in diesem Picker ist die Suchbox daher bewusst deaktiviert, statt eine nicht vorhandene API zu behaupten.

Da Roots Referenzbackend nicht in diesem UI-Worktree integriert ist, wird keine Live-HTTP-/E2E-Fertigmeldung für `/workflow-references/*` behauptet.

## Implementiertes Sourceartefakt

### Vorlagen und Versionen

- neue Vorlage auf Objekt oder optional Einheit mit erster Draft-Fassung;
- getrennte `move_in`-/`move_out`-Vorlagen;
- mindestens ein Schritt;
- Stable-Key, Position, Titel/Beschreibung;
- Pflicht/optional;
- vier Terminanker:
  `previous_contract_end`, `next_contract_start`,
  `move_out_handover`, `move_in_handover`;
- Offset in Tagen;
- Verantwortung genau als konkreter Benutzer **oder** Rolle;
- Abhängigkeiten über stabile Step-Keys inklusive lokaler Zyklusprüfung;
- Beleganforderung `none|document_original|handover_protocol|meter_reading`;
- neue Fassungen nur aus veröffentlichter/ausgemusterter Basis;
- Editieren/Publizieren nur bei aktueller Server-`action`.

### Wechselakte

- Cursorliste und Detailakte;
- Startmodi `move_out|move_in|turnover`;
- Alt-/Neuvertrag und beide Übergabetermine bleiben getrennte Fakten;
- Start strikt Preview → Confirm mit unverändertem `preview_hash` und `source_etags`;
- Schritte zeigen Originalfälligkeit, aktuelle Fälligkeit, Blockierung, Verantwortung, echte `task_id`, Abschlussfakten und Evidence-Links;
- `not_applicable` nur mit bewusstem Grund;
- Reanchor strikt Preview → Confirm; abgeschlossene/unzutreffende Schritte bleiben unverändert;
- Task-Projektion ausschließlich über `POST .../steps/{step_id}/task`, kein allgemeines Task-CRUD;
- Evidence Add/Remove ausschließlich über die fachlichen Step-Endpunkte;
- Originaldokument immer mit konkreter immutable `document_version_id`;
- finalisierte Übergabeprotokolle und Zählerstände sind über den kanonischen Referenzvertrag auswählbar;
- Aktenabschluss nur bei serverseitiger `complete_change`-Action;
- ausdrücklicher Abbruch über den echten `PatchTenancyChange`-DTO mit Grund.

## CAS, Rechteentzug und unklare Antworten

`useWorkflowCommand` friert vor dem Versand eine tiefe Kopie des vollständigen Commands ein.

- Netzwerkfehler und HTTP 5xx gelten als unklarer Ausgang. Nur der **exakt gleiche eingefrorene Command** mit identischem Idempotenzschlüssel und denselben Revisionen darf wiederholt werden.
- HTTP 409/412 werden nicht automatisch wiederholt; die UI verlangt bewusstes Neuladen/Prüfen.
- HTTP 403 ist kein „unknown success“ und wird nicht exakt wiederholt.
- Der Commandzustand ist an den Principal/Scope-Schlüssel gebunden und wird bei Benutzer-/Rollen-/Grantwechsel verworfen.
- Nach bestätigtem Step-/Task-/Evidence-Erfolg wird frische Parent-Wahrheit gelesen, bevor ein weiterer Child-Command vorbereitet wird.

## Responsive und Sprache

- Responsive Feature-CSS mit expliziten Breakpoints bis 360 px und 320 px.
- Referenzpicker, Formulare, Evidence-Dialog und Aktionen stapeln auf schmalen Ansichten.
- Featuretexte sind DE/EN/ES vorhanden; Wrappertexte wurden ebenfalls lokalisiert.

## Konsolidierung des älteren eigenen Frontendartefakts

Read-only geprüft und **nicht verändert**:

`C:\Users\matth\Documents\Codex\2026-10-01\wi\work\tenancy-workflow-frontend`

Dort verbleiben die bereits vorhandenen uncommitteten modularen Featuredateien und sechs Testdateien auf Basis `7ccee8c`.
Die brauchbaren Teile wurden gezielt in **denselben** aktiven `tenancy-workflow-ui`-Worktree übernommen und anschließend auf die aktuellen Core-DTOs sowie den kanonischen Referenzvertrag korrigiert. Es wurde kein dritter paralleler Entwurf angelegt.

Übernommen bzw. weiterentwickelt wurden insbesondere:

- modulare Template-/Start-/Aktenkomponenten;
- bounded Picker;
- tief eingefrorener Unknown-Success-Replay;
- Principal-Reset;
- Zyklusprüfung;
- die sechs älteren Tests als Basis für die erweiterte Suite.

Der alte Worktree bleibt damit als Herkunftsartefakt erhalten; Root soll den finalen Commit aus `tenancy-workflow-ui` verwenden.

## Relevante Dateien im finalen UI-Artefakt

- `frontend/src/pages/TenancyWorkflows.jsx`
- `frontend/src/pages/TenancyWorkflows.css`
- `frontend/src/features/tenancyWorkflows/BoundedReferencePicker.jsx`
- `frontend/src/features/tenancyWorkflows/DocumentVersionPicker.jsx`
- `frontend/src/features/tenancyWorkflows/EvidenceLinkDialog.jsx`
- `frontend/src/features/tenancyWorkflows/TenancyChangeFile.jsx`
- `frontend/src/features/tenancyWorkflows/TenancyChangeStartForm.jsx`
- `frontend/src/features/tenancyWorkflows/WorkflowTemplateCreateForm.jsx`
- `frontend/src/features/tenancyWorkflows/WorkflowTemplateDesigner.jsx`
- `frontend/src/features/tenancyWorkflows/WorkflowCommandNotice.jsx`
- `frontend/src/features/tenancyWorkflows/TenancyWorkflows.css`
- `frontend/src/features/tenancyWorkflows/referenceLoaders.js`
- `frontend/src/features/tenancyWorkflows/tenancyWorkflowApi.js`
- `frontend/src/features/tenancyWorkflows/tenancyWorkflowModel.js`
- `frontend/src/features/tenancyWorkflows/useWorkflowCommand.js`
- `frontend/src/features/tenancyWorkflows/workflowCopy.js`
- `frontend/src/features/tenancyWorkflows/index.js`
- `frontend/src/api.js` (additives DELETE-mit-JSON-Hilfsmittel)
- Workflowtests unter `frontend/src/test/`
- `docs/TENANCY_WORKFLOW_UI_HANDOFF_20261002.md`

Route/Navigation aus dem ersten UI-Commit bleiben bestehen:
`frontend/src/App.jsx`, `frontend/src/components/Layout.jsx`, `frontend/src/i18n.jsx`.

## Tatsächlich ausgeführte Prüfungen auf dem finalen Sourcezustand

### Gezielte Workflow-Suite

Command:

`npm.cmd test -- BoundedReferencePicker.test.jsx TenancyChangeFile.test.jsx TenancyChangeStartForm.test.jsx TenancyWorkflowModel.test.js WorkflowCommand.test.jsx WorkflowTemplateDesigner.test.jsx WorkflowTemplateCreateForm.test.jsx TenancyWorkflowApiContract.test.js`

Ergebnis: **8 Testdateien, 39 Tests bestanden**.

Enthalten sind u. a.:

- `CreateTemplate expected_revision:"new"`;
- genau ein Verantwortlicher: Benutzer XOR Rolle;
- Create/Update/Publish Template DTOs;
- Start Preview→Confirm mit `expected_revision:"new"`, Hash und Quell-ETags;
- Reanchor Preview→Confirm;
- Step/Task/Evidence mit Step- und Change-Revision;
- Add/Remove Document Evidence inklusive immutable Version;
- finalisierter Meter-Reading-Auswahlpfad;
- DELETE mit JSON-Body;
- serverseitige Referenzsuche mit `search`, `selected_id`, opakem Cursor und `page_size`;
- Suchänderung startet mit leerem Cursor;
- ausgewählte Referenz wird über `response.selected` erhalten;
- Unknown Success exakt wiederholen;
- 409/412 nicht wiederholen;
- 403/Rechteentzug nicht wiederholen;
- Principalwechsel verwirft privaten Commandzustand.

### ESLint

Gezielter ESLint über gemeinsamen API-Client, gesamtes `features/tenancyWorkflows`, Seitencontainer und alle acht Workflow-Testdateien mit `--max-warnings=0`.

Ergebnis: **bestanden, keine Ausgabe/Warnung**.

### Produktionsbuild

`npm.cmd run build`

Ergebnis: **bestanden**, Vite 8.1.0, **670 Module transformiert**.

### Vollständige Frontend-Suite

`npm.cmd test`

Ergebnis: **980/981 Tests bestanden, 78/79 Testdateien bestanden**.

Einziger Fehler:
`src/test/ContractWorkspace.test.jsx` –
`requests only explicit cursor pages, reaches record 125, and returns with the original query`
überschritt unter paralleler Vollsuite das feste 5-s-Testlimit (gemessene Testzeit ca. 5,802 s).
Dieser Bereich wurde durch den Workflow-Diff nicht verändert.

Direkter isolierter Gegencheck auf demselben finalen Sourcezustand:

`npx.cmd vitest run ContractWorkspace.test.jsx --testNamePattern='requests only explicit cursor pages, reaches record 125, and returns with the original query'`

Ergebnis: **1/1 bestanden**, Testzeit **2,362 s** (32 weitere Tests der Datei bewusst übersprungen).

Bestehende fachfremde React-Testwarnungen zu `act(...)` bzw. doppelten Keys wurden im Vollsuite-Output weiterhin ausgegeben; sie stammen nicht aus den Workflowdateien.

## Noch nicht behauptet

- keine Live-HTTP-/Browser-E2E-Abnahme des Core-Branches, solange dessen uncommittete Arbeit nicht integriert ist;
- keine Live-Abnahme von Roots separatem `workflow-references`-Backend in diesem UI-Worktree;
- keine Änderung an Main, Root-Preview, Root-Integrationsworktree, Core-Worktree oder `work/workflow-references`;
- keine Verarbeitung von Zugangsdaten oder TEHA-Daten.
