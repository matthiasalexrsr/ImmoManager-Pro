# P1/P2 Frontend-Handoff – Mieterwechsel

Stand: 2. Oktober 2026

## 1. Arbeitsstand und Abgrenzung

Aktiver Frontend-Worktree:

- Pfad: `C:\Users\matth\Documents\Codex\2026-10-01\wi\work\tenancy-workflow-ui`
- Branch: `assist/tenancy-workflow-ui`
- Ausgangscommit dieses Nachtrags: `bd34821755a711c201c3a47a1b89ec2ef28f93b1`
- Gemeinsame Basis: `7ccee8ca4518966d1dbb07ef625eb31d2133337a`

Nicht verändert wurden Main, Root-Integrationsworktree, laufende Preview und der Backend-Core-Worktree.

Der ältere eigene Worktree
`C:\Users\matth\Documents\Codex\2026-10-01\wi\work\tenancy-workflow-frontend`
bleibt unverändert erhalten. Er steht weiterhin auf `7ccee8c` und enthält seine ursprünglichen untracked modularen Featuredateien sowie sechs Testdateien. Diese brauchbaren Teile wurden in den aktiven Worktree übernommen, gegen den realen Core-Vertrag korrigiert und dort konsolidiert. Root soll **nicht beide Frontendstände getrennt integrieren**; der Commit dieses Handoffs ist die konsolidierte Fassung.

## 2. Gelesener Core-Sourcevertrag

Der Backendautor arbeitet noch uncommittet auf Branch `assist/tenancy-workflow-core`; dessen HEAD allein beschreibt den gelesenen Vertrag daher nicht. Der letzte Read-only-Abgleich erfolgte auf diesen Dateien:

- `backend/services/tenancy_workflow_types.py`
  SHA-256 `64BB8991BA53B02462649F9830933FE4ACA04C3232C853BEEF4639FD4DFCCEB4`
- `backend/routers/tenancy_workflows.py`
  SHA-256 `E20D805B4B25BA3C28896DB4E70AED53314B435C9E5036D2EFB88A565674B8EE`
- `backend/services/tenancy_workflow.py`
  SHA-256 `2ADA3C716B3C919EDD57FD671BE46C8BAA1D11BADD867E6AA1FAE09CD6EF67E8`

Core-Worktree beim letzten Abgleich: HEAD `7ccee8ca4518966d1dbb07ef625eb31d2133337a`, mit den noch uncommitteten Dateien des Coreautors. An diesen Dateien wurde nichts geschrieben.

## 3. Tatsächlich implementierter Request-/Responsevertrag

Die frühere allgemeine Mutation-Envelope-Annahme wurde entfernt. Jeder Command besitzt jetzt seinen konkret gelesenen DTO-Builder.

### Vorlagen

`POST /workflow-templates`

Request:

`idempotency_key, expected_revision:"new", property_id, unit_id|null, direction, steps[>=1]`

Response: erste `WorkflowTemplateVersion`, Version 1 im Zustand `draft`.

`POST /workflow-templates/{template_id}/versions`

Request:

`idempotency_key, expected_revision, based_on_version_id`

Response: neue `WorkflowTemplateVersion`.

`PUT /workflow-template-versions/{version_id}`

Request:

`idempotency_key, expected_revision, steps[>=1]`

Response: aktualisierte `WorkflowTemplateVersion`.

`POST /workflow-template-versions/{version_id}/publish`

Request:

`idempotency_key, expected_revision`

Response: veröffentlichte `WorkflowTemplateVersion`.

Vorlagenlisten liefern die jeweils neueste `WorkflowTemplateVersion` pro Vorlage als
`{items,next_cursor,has_more}`; der Cursor bleibt opak.

### Start einer Wechselakte

`POST /tenancy-changes/preview`

Request ist die reine `ChangeSelection` ohne Mutationsschlüssel:
Objekt, Einheit, alter/neuer Vertrag, Modus, getrennte Übergabetermine und getrennte Vorlagenversionen.

Response wird gegen die tatsächliche Form validiert:

`preview_hash, snapshot_sha256, source_etags, anchors, affected_steps, conflicts, portfolio_id`.

`POST /tenancy-changes`

Request ist exakt dieselbe Auswahl plus:

`idempotency_key, expected_revision:"new", preview_hash, source_etags`.

Response: vollständige `TenancyChange`.

Eine Änderung der Auswahl oder eines Terminankers verwirft die UI-Vorschau; es wird kein stiller Start mit einer alten Vorschau angeboten.

### Abbruch

`PATCH /tenancy-changes/{change_id}`

Request:

`idempotency_key, expected_revision:<change revision>, state:"cancelled", reason:<nichtleer>`.

Response: vollständige `TenancyChange`.

Die UI verlangt einen ausdrücklichen Abbruchgrund.

### Terminverschiebung

`POST /tenancy-changes/{change_id}/reanchor-preview`

Request:

`expected_revision, move_out_handover_date|null, move_in_handover_date|null`.

Response:

`preview_hash, change_revision, source_etags, affected_steps[], completed_steps_unchanged[]`.

Jeder betroffene offene Schritt wird über
`step_id, original_due_date, current_due_date, new_due_date, task_id`
dargestellt.

`POST /tenancy-changes/{change_id}/reanchor`

Request: dieselben Termine plus
`idempotency_key, expected_revision, preview_hash, source_etags`.

Response: vollständige `TenancyChange`.

### Schrittstatus, Task und Belege

Für alle vier folgenden Commands werden **beide** Revisionen gesendet:

- `expected_revision` = Revision des `WorkflowStepInstance`
- `expected_change_revision` = Revision der Eltern-`TenancyChange`

`PATCH .../steps/{step_id}`

zusätzlich:
`state: open|in_progress|completed|not_applicable` und nur bei
`not_applicable` ein nichtleerer `not_applicable_reason`.

`POST .../steps/{step_id}/task`

nur Commandfelder plus beide Revisionen.

`POST .../steps/{step_id}/evidence`

zusätzlich `evidence: EvidenceInput`.

`DELETE .../steps/{step_id}/evidence/{link_id}`

hat laut Router einen **JSON-Body** mit `RemoveEvidence`; dafür wurde im gemeinsamen API-Client `delJson` ergänzt.

Alle vier Endpunkte liefern nur den aktualisierten `WorkflowStepInstance`, obwohl der Service gleichzeitig auch die Elternrevision erhöht. Nach einem **bekannt erfolgreichen** Step-/Task-/Evidence-Command lädt der Container deshalb die vollständige Akte erneut über
`GET /tenancy-changes/{change_id}`.
Es wird keine Elternrevision aus der Step-Antwort erfunden.

Bei Netzwerkfehler/5xx bleibt dagegen der exakte Command eingefroren und kann mit identischem Idempotency-Key und identischen Revisionen wiederholt werden. 409/412 erzwingt bewusste Neusichtung; 403 nach Rechteentzug ist ein endgültiger UI-Fehler und bietet keine exakte Wiederholung an.

### Abschluss

`POST /tenancy-changes/{change_id}/complete`

Request:

`idempotency_key, expected_revision:<change revision>`.

Response: vollständige `TenancyChange`; serverseitige Blocker bleiben autoritativ.

## 4. DTO-nahe UI-Validierung

Die lokale Vorlagenprüfung bildet die sichtbaren Pydantic-Regeln nach:

- mindestens ein Schritt;
- `stable_key` nur `[A-Za-z0-9_.:-]`, maximal 100 Zeichen;
- eindeutige Stable Keys und Positionen;
- vier getrennte Terminanker;
- Pflicht oder optional;
- konkreter Benutzer **oder** Rolle, nie beides;
- task-fähige Rollen in der Auswahl: `eigentuemer|verwalter|techniker`;
- nur aktive, task-fähige konkrete Benutzer auswählbar;
- eindeutige Abhängigkeitsliste und Zyklusprüfung vor dem Write;
- Belegregel `none|document_original|handover_protocol|meter_reading`.

Die Serverprüfung bleibt maßgeblich.

## 5. Belegidentität

`EvidenceLink` wird gegen die reale Responseform geprüft:

`id, kind, document_id|null, document_version_id|null, handover_protocol_id|null, meter_reading_id|null, snapshot_sha256, created_at`.

Für Dokumente sendet die UI ausschließlich:

`kind:"document_version", document_id, document_version_id`.

Die unveränderliche Version wird aus der bestehenden paginierten Dokumentversionshistorie gewählt. Keine Dateipfade oder öffentlichen URLs werden als Belegidentität verwendet.

Finalisierte Übergabeprotokolle werden bounded angeboten und zusätzlich in der UI auf Einheit/Vertragsrichtung eingegrenzt; der Server prüft die Zuordnung erneut.

Für Zählerstände wird **keine fertige Auswahl behauptet**: Der Core akzeptiert `meter_reading_id`, aber im aktuellen Frontend wird kein frei erfundener oder unvollständig belegter Meter-Picker angeschlossen.

## 6. Bounded Auswahl und verbleibende Referenzlücke

Der konsolidierte `BoundedReferencePicker` unterstützt:

- Legacy-`skip/limit`-Seiten mit explizitem „Weitere laden“;
- opake Workflow-`after`-Cursor unverändert;
- Abbruch alter Requests;
- Erhalt einer bereits ausgewählten Referenz außerhalb der aktuellen Seite;
- keine pauschale Gesamtbestandsgrenze.

Aktuelle bounded Adapter existieren für Immobilien, Einheiten, Verträge, aktive Benutzer, Dokumente, Übergabeprotokolle und Dokumentversionen.

Die vom gemeinsamen Vertrag geforderte **kanonische serverseitige Referenzsuche** über späte Immobilien/Einheiten/Verträge/Benutzer/Belege/Zähler ist weiterhin Root-/P1-Integrationsarbeit. Die UI bezeichnet die Legacy-Seitennavigation nicht als fertige globale Suche.

## 7. Rechteentzug und private UI-Zustände

Der Workflow-Principal-Key enthält:

`user.id, role, portfolio_access, sortierte portfolio_ids, portfolio_access_origin`.

Ändert sich Benutzer, Rolle oder Portfoliofreigabe, werden laufende private Requests abgebrochen und eingefrorene unbekannte Commands dieses vorherigen Principals verworfen. Sichtbare `actions` steuern nur Bedienbarkeit; jede Mutation bleibt serverautorisiert.

Manager-Komfortfunktionen für Vorlagen/Start werden nur Eigentümer/Verwalter angeboten. Operative Step-Aktionen stammen aus den serverberechneten `actions`.

## 8. Konsolidierte Dateien

Featuremodul:

- `frontend/src/features/tenancyWorkflows/BoundedReferencePicker.jsx`
- `DocumentVersionPicker.jsx`
- `EvidenceLinkDialog.jsx`
- `TenancyChangeFile.jsx`
- `TenancyChangeStartForm.jsx`
- `WorkflowTemplateCreateForm.jsx`
- `WorkflowTemplateDesigner.jsx`
- `WorkflowCommandNotice.jsx`
- `TenancyWorkflows.css`
- `referenceLoaders.js`
- `tenancyWorkflowApi.js`
- `tenancyWorkflowModel.js`
- `useWorkflowCommand.js`
- `workflowCopy.js`
- `index.js`

Integration:

- `frontend/src/pages/TenancyWorkflows.jsx`
- `frontend/src/pages/TenancyWorkflows.css`
- `frontend/src/api.js`
- die bereits im vorherigen Commit ergänzten Route-/Navigations-/DE-EN-ES-Labels in `App.jsx`, `Layout.jsx`, `i18n.jsx`.

Superseded Dateien des ersten UI-Entwurfs wurden im aktiven Worktree entfernt:
`frontend/src/components/CursorReferencePicker.jsx`,
`frontend/src/tenancyWorkflowApi.js`,
`frontend/src/tenancyWorkflowText.js` und
`frontend/src/test/TenancyWorkflow.test.jsx`.
Ihre Funktion liegt nun modular und getestet im Featureverzeichnis.

## 9. Tests

Workflow-spezifische Tests:

- `BoundedReferencePicker.test.jsx`
- `TenancyChangeFile.test.jsx`
- `TenancyChangeStartForm.test.jsx`
- `TenancyWorkflowModel.test.js`
- `WorkflowCommand.test.jsx`
- `WorkflowTemplateDesigner.test.jsx`
- `WorkflowTemplateCreateForm.test.jsx`
- `TenancyWorkflowApiContract.test.js`

Sie prüfen unter anderem:

- echte CreateTemplate-/Start-`"new"`-Revision;
- Vorlagenversion Create/Update/Publish;
- vier Terminanker;
- Benutzer oder Rolle;
- Zyklusblockade;
- Start Preview→Confirm;
- expliziten Abbruch;
- Reanchor Preview→Confirm;
- Stepstatus mit Step- und Elternrevision;
- Tasklink mit Step- und Elternrevision;
- immutable Dokumentversion;
- Add/RemoveEvidence mit Step- und Elternrevision;
- DELETE-JSON-Body;
- opake Cursor und späte bounded Referenzen;
- Unknown Success mit rekursiv eingefrorenem identischem Payload;
- 409/412 ohne stillen Replay;
- 403-Rechteentzug ohne Replay;
- Principalwechsel ohne privaten Altzustand.

## 10. Tatsächlich ausgeführte Prüfungen

Auf dem finalen Sourcezustand vor diesem Handoff:

1. Workflow-Suite:
   **8 Testdateien, 36 Tests bestanden.**

2. Gezielter ESLint über API, gesamtes Featuremodul, Container und acht Workflow-Testdateien mit
   `--max-warnings=0`:
   **bestanden, keine Fehler/Warnungen.**

3. `npm.cmd run build`:
   **bestanden**, Vite 8.1.0, **670 Module transformiert**.

4. Vollständiger Frontendlauf auf dem **finalen** Stand:
   **78 Testdateien bestanden, 1 Testdatei fehlgeschlagen; 977/978 Tests bestanden.**
   Der einzige Fehler ist der von diesem Diff unberührte Test
   `ContractWorkspace.test.jsx > requests only explicit cursor pages, reaches record 125, and returns with the original query`.
   Er überschritt im parallelen Gesamtlauf das feste 5000-ms-Testlimit und endete nach 5971 ms als Timeout.
   Sämtliche 36 Workflowtests bestanden auch innerhalb dieses Gesamtlaufs.

5. Timing-Nachprüfung desselben ContractWorkspace-Tests:
   - ein isolierter Lauf bestand mit **3153 ms**;
   - ein späterer isolierter Lauf auf dem finalen Stand lief mit **5743 ms** erneut in dasselbe 5000-ms-Limit.
   Damit ist die Restabweichung reproduzierbar als laufzeitabhängiger Timeout desselben Root-eigenen Tests, nicht als fachlicher Workflow-Assertionfehler. Der UI-Commit ändert keine ContractWorkspace-, ContractLifecycle- oder Korrespondenzdatei.

Der vollständige Frontendlauf wird deshalb ausdrücklich **nicht** als vollständig grün bezeichnet. Die Workflow-spezifischen Gates, ESLint und der Produktionsbuild sind grün.

## 11. Nicht behauptet

- keine produktive Liveintegration, solange Root den uncommitteten Backend-Core nicht integriert hat;
- kein echter Browser-/PostgreSQL-End-to-End-Nachweis der neuen Routen in diesem Frontend-Worktree;
- keine fertige kanonische Referenzsuche;
- kein fertiger Meter-Reading-Picker ohne belegte unveränderliche Auswahl;
- keine Änderung an Core, Main, Root-Preview oder Root-Integrationsworktree;
- keine Verarbeitung von Zugangsdaten oder TEHA-Daten.
