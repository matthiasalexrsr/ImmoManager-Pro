# Verbindlicher P1/P2-Vertrag für die gemeinsame Umsetzung

Stand: 2. Oktober 2026. Root gleicht hier den Frontendentwurf aus „Software verbessern und fertigstellen“ mit dem Backendentwurf aus „Software verbessern“ ab. Dies ist ein Implementierungsvertrag, kein Nachweis schon vorhandener neuer Endpunkte. Der ausführliche Plan bleibt `IMPLEMENTIERUNGSPLAN_20261002.md`.

## Gemeinsame Entscheidungen

- Fachliche Tabellen dürfen `tenancy_workflow_*` heißen; die interne HTTP-Oberfläche verwendet die unten festgelegten Namen. Es gibt getrennte Objektvorlagen für Einzug und Auszug. Eine bewusst veröffentlichte Einheitsabweichung ist eine eigene versionierte Vorlage mit `unit_id`; ein laufender Vorgang behält seinen eingefrorenen Stand.
- Veröffentlichte Versionen und Startsnapshot bleiben unveränderlich. Weiterbearbeitung erzeugt einen neuen Entwurf. Ausgemusterte Versionen bleiben für bestehende Akten und Nachweise lesbar.
- Eine Wechselakte bündelt entweder Auszug, Einzug oder beide Richtungen. Die bisherige/neue Vertragsidentität, Vertragsdaten und expliziten Übergabetermine bleiben getrennt. Ein Vertragsende wird nicht still als Übergabetermin verwendet.
- Verantwortung ist entweder ein konkreter aktiver Benutzer oder eine Rolle. Beide Felder gleichzeitig werden zurückgewiesen. Zuweisung ist eine echte Identität, keine Auswertung von `Task.assignee`. Ein freier Anzeigename in der bisherigen Aufgabe bleibt Anzeigeinformation.
- Die Akte besitzt serverberechnete Aktionsfähigkeiten. Eigentümer/Verwalter verwalten Vorlagen und Start-/Termin-/Abschlussbefehle. Operative Durchführung kann eine befugte, ausdrücklich verantwortliche Technikrolle übernehmen. Diese Fähigkeit eröffnet keine Bearbeitung oder Einsicht fremder Vertrags-/Finanzinhalte. Dokumentverknüpfungen prüfen zusätzlich die aktuelle Dokumentberechtigung.
- Bestehende Tasks bleiben die sichtbaren ausführbaren Aufgaben. Die Instanz ist fachliche Quelle, eine eindeutige FK-Verknüpfung bindet ihre Projektion. Allgemeine Task-Schreibpfade dürfen Pflichtschritte, Belegregeln, Abhängigkeiten oder geplante Termine nicht umgehen; verknüpfte Änderungen werden durch denselben Fachbefehl geprüft oder mit einer konkreten nächsten Aktion abgewiesen.
- Eine Ausnahme `not_applicable` benötigt einen nichtleeren Grund und bewusste Entscheidung. Sie ist kein automatischer Vorlagendefault. Pflicht/optional bleiben als ursprüngliche Anforderung erhalten.
- Abhängigkeiten bilden einen Graphen ohne Zyklen. Veröffentlichung, Start und jede bewusste Graphänderung prüfen ihn unter der gemeinsamen Elternrevision. Ein deaktivierter/fehlender Vorgänger wird nicht still als erledigt behandelt.
- Erledigte Schritte, tatsächlicher Abschlusszeitpunkt und Originalfälligkeit bleiben erhalten. Terminänderungen zeigen vorher eine Vorschau und passen nur offene Projektionen an.
- Kein Workflowbefehl erzeugt Mietforderungen, Einnahmen, Zahlungen, Kautionsbewegungen oder externe Nachrichten.

## DTO-Namen und feste Felder

IDs sind Zeichenketten. Datumfelder sind ISO-Daten, Zeitstempel ausdrücklich getrennt. Serverantworten enthalten eine `revision` und einen starken `etag`; Mutationen verwenden genau den gelesenen Stand. UUID-Revisionen dürfen intern verwendet werden, ihre Darstellung muss im Handoff eindeutig beschrieben sein.

`WorkflowTemplateVersion`:

```text
id, template_id, portfolio_id, property_id, unit_id|null,
direction: move_in|move_out, version, state: draft|published|retired,
based_on_version_id|null, revision, etag, created_at, published_at|null,
steps, actions
```

`WorkflowTemplateStep`:

```text
id, stable_key, position, title, description|null,
default_requirement: required|optional,
anchor: previous_contract_end|next_contract_start|move_out_handover|move_in_handover,
offset_days, assignee_user_id|null, assignee_role|null,
depends_on_step_keys[],
evidence_requirement: none|document_original|handover_protocol|meter_reading
```

`TenancyChange`:

```text
id, portfolio_id, property_id, unit_id,
previous_contract_id|null, next_contract_id|null,
mode: move_out|move_in|turnover,
move_out_handover_date|null, move_in_handover_date|null,
move_out_template_version_id|null, move_in_template_version_id|null,
state: draft|active|completed|cancelled,
revision, etag, created_by, created_at, updated_at,
snapshot_sha256, steps, actions
```

Der Startsnapshot bewahrt die tatsächlich gelesenen Vertragsanker und veröffentlichten Vorlagen. Er wird nicht aus später nachgeladenen UI-Labels rekonstruiert. Mindestens ein zur gewählten Richtung passender Vertrag und eine bestätigte Vorlage sind erforderlich. Beide Verträge müssen zur gleichen Einheit/Immobilie gehören; dieselbe Vertragsrolle darf nicht durch parallele Starts doppelt belegt werden. Eine Korrektur-/Abbruchregel muss explizit sein und darf keine zweite aktive Wechselakte für denselben Vorgang erzeugen.

`WorkflowStepInstance`:

```text
id, tenancy_change_id, template_step_key, direction,
title_snapshot, description_snapshot,
requirement: required|optional, not_applicable_reason|null,
anchor, offset_days, original_due_date, due_date,
state: open|blocked|in_progress|completed|not_applicable,
blocked_by_step_ids[], assignee_user_id|null, assignee_role|null,
task_id|null, completed_at|null, completed_by|null,
evidence_links[], revision, etag, actions
```

Originalfälligkeit und abgeschlossene Fakten bleiben auch nach einer Terminänderung unverändert. `blocked` und Abschlussfähigkeit kommen vom Server. Ausführung einer optionalen Aufgabe unterliegt ebenfalls ihrer konfigurierten Belegregel; optional heißt, dass die Akte ohne ihre Erledigung abgeschlossen werden kann. Pflichtschritte müssen erledigt oder bewusst mit einem zulässigen Ausnahmegrund entschieden sein. Die Abschlussantwort benennt noch blockierende Schritte.

`EvidenceLink` verwendet `kind=document_version|handover_protocol|meter_reading` und genau die dafür geltenden IDs. Für ein Original werden `document_id` und `document_version_id` zusammen validiert. Es werden keine Dateipfade/öffentlichen URLs als Belegidentität gespeichert. Verknüpfungen prüfen Portfolio, Objekt, Einheit, Vertragsrichtung und gegebenenfalls Mieterbezug frisch. Übernommene Übergabeprotokolle müssen finalisiert sein; deren normale Schreib- und Unterobjektpfade dürfen die Finalisierung nicht umgehen. Verknüpfte Zählerwerte brauchen einen unveränderlichen überprüfbaren Nachweis oder eine bewusst eingefrorene Fassung, damit nachträgliche Änderungen keine erledigte Belegregel entwerten.

`actions` enthält mindestens `edit_template`, `publish_template`, `edit_change`, `reanchor`, `complete_step`, `link_task`, `link_document`, `complete_change`. Es sind aktuelle serverberechnete Fähigkeiten; jeder Befehl prüft sie erneut. Ein UI-Flag ersetzt keine Autorisierung.

## Verbindliche interne API

```text
GET  /workflow-templates?property_id=&unit_id=&direction=&after=&limit=25
POST /workflow-templates
GET  /workflow-templates/{template_id}
GET  /workflow-templates/{template_id}/versions?after=&limit=25
POST /workflow-templates/{template_id}/versions
GET  /workflow-template-versions/{version_id}
PUT  /workflow-template-versions/{version_id}
POST /workflow-template-versions/{version_id}/publish

GET  /tenancy-changes?property_id=&unit_id=&state=&after=&limit=25
POST /tenancy-changes/preview
POST /tenancy-changes
GET  /tenancy-changes/{change_id}
PATCH /tenancy-changes/{change_id}
POST /tenancy-changes/{change_id}/reanchor-preview
POST /tenancy-changes/{change_id}/reanchor
PATCH /tenancy-changes/{change_id}/steps/{step_id}
POST /tenancy-changes/{change_id}/steps/{step_id}/task
POST /tenancy-changes/{change_id}/steps/{step_id}/evidence
DELETE /tenancy-changes/{change_id}/steps/{step_id}/evidence/{link_id}
POST /tenancy-changes/{change_id}/complete
```

Listen liefern `{items, next_cursor, has_more}`; Cursor bindet Benutzer, aktuelle Rolle/Portfoliofreigaben, Filter und Seitenbudget. `after` ist ein opaker vom Server gelieferter Cursor. Positive konfigurierbare Seiten-/Arbeitsbudgets ersetzen keinen Gesamtbestandsdeckel. Referenzwahl muss auch späte Immobilien, Einheiten, Verträge, Mitarbeiter, Belege und Zähler finden. Detaildaten mit großen Schritt-/Beleglisten benötigen ebenfalls vollständige Seiten und dürfen nicht auf die ersten 100 abgeschnitten werden.

Jeder zustandsändernde Fachbefehl erhält `idempotency_key`, `expected_revision` und seine fachlichen Daten. Ein vorhandener starker `If-Match` darf zusätzlich verwendet werden; widersprüchliche Erwartungen werden zurückgewiesen. Derselbe Benutzer/Schlüssel und dieselbe kanonische Anfrage liefert dasselbe Receipt, eine abweichende Anfrage 409. Frische Rechte werden auch beim Wiederholen geprüft. Unknown Success/Netzwerk/5xx bewahrt in der UI den exakten Befehl; 409/412 verlangt eine bewusste erneute Prüfung und keinen Replay mit still erneuertem Stand.

Start-/Terminvorprüfung liefert `preview_hash`, tatsächliche Anker und betroffene Schritte, ursprüngliche Quell-ETags sowie Abschluss-/Konfliktinformationen. Bestätigung übermittelt exakt denselben Vorschlag/Hash und gelesene Quellstände. Die Anwendung verschiebt bestehende Aufgaben erst nach ausdrücklicher Bestätigung. Originale und erledigte Schritte bleiben unverändert.

## Ownership und Integration

Der Backend-Assistent implementiert eigenständigen Core, Modelle, Migration, Router/Schemas, Service und Coretests im eigenen Checkout. Er liefert zusätzlich die notwendigen Guards in normalen Task-/Übergabe-/Übergabezählerpfaden und beseitigt die belegte 10.000-Abschneidung der Taskdatumsfilter. Neue Tabellen ersetzen diese Korrekturen nicht. Zusammengesetzte SQL-Befehle dürfen keine je Aufgabe committene Facade verwenden.

Der Frontend-Assistent implementiert Komponenten, API-Client, begrenzte referenzfähige Auswahl, DE/EN/ES, responsive CSS und eigene UI-Tests im eigenen Checkout. Routennamen/DTOs dieses Vertrags sind seine Grundlage; produktive Featurebereitschaft wird erst nach tatsächlichem Backend-Handoff bestätigt. Der vorhandene ContractLifecycle-/Korrespondenzdialog bleibt bei Root.

Root verantwortet Produktionsregistrierung, frische Rollen-/Portfoliointegration, Memory-/SQL-Legacybootstrap, Retention/Reset/Transfer, sämtliche Full-Recovery-/Datenschutzgraphpfade, gemeinsame Abnahme und echte Browser-/PostgreSQLbelege. All-or-nothing-Journalfamilien werden vor DML geprüft; ein halb fehlendes Modul darf nicht durch create_all still neu entstehen. Migrationen werden auf den tatsächlichen Head verkettet.

## Gesonderter P1-Befund: alte operative Gesamtläufe

124 vorhandene offene überfällige Mietforderungen haben in der vollständigen Browserprüfung einen Tick mit Budget 100 vollständig zurückgerollt, bevor die Korrespondenzprojektion erreicht wurde. Der Legacytick ist atomar, aber nicht allgemein fortsetzbar. Das ist eine getrennte Infrastrukturarbeit: dauerhaft eingefrorene Arbeitslisten, Cursor/Claims, Teilfortschritt und Wiederaufnahme je Aufgabenart. Die neuen Workflow-Autoren dürfen dies nicht mit einer höheren festen Zahl oder ungeprüfter Änderung der alten Rollbacksemantik überdecken. Root koordiniert diese Ablösung separat, damit neue Akten und TEHA dieselbe erprobte Fortsetzungsinfrastruktur verwenden können.
