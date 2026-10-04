# Paket C – Widerspruchsakte: UI-Handoff, 03.10.2026

## Eigene Quelle und Übergabestand

Eigener Checkout `work/billing-dispute-ui`, Branch `assist/billing-dispute-ui`,
aus sauberem Root `f9e8edc`. Keine Root-/Main-/Previewquelle beschrieben.
Vorcodeplan `3310dba` blieb vor allen Produktänderungen separat committed.
Backend, Recovery, Registry, CI, SharedFormModal und SharedDraftpolicy bleiben
Rootbesitz; StatementChoices/FrozenParties stammen aus Domains Isolation.

Root hat die ersten vier eigenen Quellen bereits zentral übernommen:

| Eigener Commit | Inhalt |
| --- | --- |
| `3310dba` | Tatsächliche Analyse, Grenzen und Vorcodeplan |
| `df69d69` | DTO-/Original-/Preview-/Receipt-/Envelopeprüfungen und acht Modellfälle |
| `3191703` | Eigene deutsche/englische/spanische Featuretexte |
| `90ee452` | Aktenstatus, bounded Liste/Chronik, exact Originale/Versionsdownload, acht Lesefälle |
| `8be0829` | Echter Sharedhook-Restore/850-ms-Regressionsnachweis |
| `bc203e1` | Gemeinsamer verschlüsselter Draftkern mit exakt erhaltenem Domainbefehl und acht echten Hookfällen |
| `a91858c` | Bounded Dokument-/Originalversionswahl, belegte Originalperson, sechs Wahl-/Originalfälle |
| `0b80c1d` | Workspace/Formulare, äußerer Scopezaun, bewusste Quellenübernahme, acht Formularfälle |
| `5ced847` | Gesperrte Pendingrestore-UI, tatsächliches Originalevent für Berichtigung, Grantentzug, Aktionsverben/Fehlerfokus |

Die separate eigene Übernahme `f9ee6c8` entspricht Roots Sharedhookfix
`d40ea9c`; **nicht nochmals nach Root übernehmen**. Auf der älteren Basis
waren zwei darin enthaltene Root-Dokumente neu; ihre vollständigen sauberen
Commitfassungen wurden bei diesem Dependencycherry erhalten. Keine uncommittete
Rootquelle wurde kopiert.

## Konkreter Root-Wiringvertrag

`frontend/src/features/billingDisputes/BillingDisputeWorkspace.jsx` liefert
den Defaultexport `BillingDisputeWorkspace({periodId, propertyId})`.
Root mountet ihn in den bestehenden Details der tatsächlich ausgewählten
Abrechnungsperiode. Er enthält Read/Commands/Draftrecovery selbst und benötigt
keine Legacy-Gesamtlisten von Statements, Mietern, Dokumenten oder Versionen.
Aktuelle Auth wird intern gelesen; Principal enthält Actor, Rolle,
Portfoliogrants und tatsächliche `write_permissions`. Kontextänderungen remounten
die Featurequelle und abortieren deren HTTPs/Downloads; alte Antworten erscheinen
nicht im neuen Kontext. Bestehende Billing-Gesamtlisten wurden nicht umgebaut.

Root ersetzt den alten Grunddialog/Perioden-`dispute`-POST im eigenen kleinen
Wiringcommit. Diese Übergabe enthält keinen `Statements.jsx`- oder globalen
i18n-JSON-Wiringpatch. Die Legacy-Statementtests benötigen tatsächlich einen
Authuser für das neue private Feature, nicht nur einen Rollenstring.

## Tatsächliche Quellen und Bedienung

Status, Aktenliste, Detail, Chronik und Originalevent verwenden ausschließlich
die bestehenden `/billing/disputes`-Routen. Aktuelle Listen-/Chronikpakete sind
je 25 Zeilen, Cursor-/Revisiontrail hält nur Seitenschlüssel. Authorized
Servergesamtzahlen werden unverändert angezeigt; 503/fehlerhafte Antworten sind
Fehler, kein leerer Aktenbestand. Alte `disputed`-Perioden ohne vollständige Akte
bleiben ausdrücklich historisch unvollständig.

Die verbindliche neue Statementwahl nutzt `/workflow-references/statements`
mit **genau** `period_id` oder `dispute_case_id` plus bestehenden bounded
Such-/Selected-/Cursorparametern. Nach Auswahl folgt der echte einzelne
`/billing/statements/{id}`. Originalrevision/hash werden ausdrücklich aus diesem
Detail übernommen. Korrekturen gehören tatsächlich zur späteren Korrekturperiode:
das Detail wird gegen deren frisch selektierte `billing_period_id`, Vertrag,
Einheit, Revision und Hash geprüft, nicht gegen die alte Aktenperiode.

Originalpositionen behalten nullbasierte DTO-Indizes und vollständiges
Abrechnungsoriginal. Lediglich die Darstellung innerhalb eines Einzeloriginals
hat Seiten zu 25 Positionen. Anlagenwahl: tatsächliche bounded Dokumentwahl,
dann `/documents/{id}/versions?limit=25&before=...`. Nur unveränderbare
`version_id`s werden Domainwerte. Der Suchdokumentkontext ist keine Anlage.
Restored IDs vor Vorschau bleiben als zu prüfende Auswahl sichtbar; kein
erfundener Originalname und kein Vollhistorien-Restoreselector.

Vorschau prüft vollständigen unveränderten Request, Originalbindung und
Manifestmenge. Native Domain prüft Zuordnung und tatsächliche Originalbytes;
UI-Originaldownload nutzt den authentisierten echten Versiondownload, prüft
die Manifestgröße und verwendet den Originaldateinamen. Optionale
`original_snapshot.original_party` wird ausschließlich aus belegtem Original
gezeigt; ältere Quellen bekommen keine heutige Mieteridentität ergänzt.

Notiz, Prüfung, Rücknahme, Abschluss, Wiederaufnahme und Korrekturverknüpfung
folgen tatsächlichen Aktenzuständen. Berichtigung wird ausschließlich nach
exact Originalevent-GET mit dessen `corrects_event_id` eröffnet; kein historisches
Ereignis wird editiert. Domain bleibt für die endgültige Zulässigkeit maßgeblich.
Aktenaktionen erzeugen keine automatische Forderung/Erstattung/Zustellung.

## Gemeinsamer Draftvertrag und exakter Replay

Collection `billing/disputes`, `entity_id=null`, `form_key=open:<periodId>` oder
`event:<caseId>`, vier Textfelder `period_id`, `case_id`, `command_json`,
`review_json`. Bearbeitbarer Anfang erlaubt leere Gründe/Daten und Nullreferenzen;
gewählte Referenzen bleiben frisch autorisiert. `review_json` enthält das echte
vollständige Domainpreview, `command_json` den vollständigen bestätigbaren DTO
mit UUID, Originalrevision und Previewhash. Kein zusätzlicher Speicherpfad.

Vor DomainPOST muss der gemeinsame Kern erfolgreich dieselbe Nutzlast mit
`submission_pending=true` speichern. Bei fehlender Antwort/5xx sperrt die UI
Bearbeitung, neue Vorschau, Discard und generisches Resume; angeboten wird nur
der unveränderte idempotente Replay. Restore hält denselben Befehl auch über
650 ms Autosave hinweg pending. Roots tatsächlicher Sharedfix erhält Pending
beim Restore/Retry und liefert numerischen `errorStatus` für den äußeren
401/403/404-Zaun. Explizites allgemeines Resume bleibt beim generischen Kern
bewusst erhalten; C ruft es für unbekannte Ergebnisse nicht auf.

Bekannte 409/412 erhalten Eingaben und ursprüngliche Revision. Aktueller
Akten-/Originalstand wird ausdrücklich übernommen, niemals automatisch
rebasiert. Ein geprüfter erfolgreicher Receipt wird einmal publiziert;
fehlgeschlagenes Draftcleanup wiederholt nur DELETE, keinen DomainPOST.
Keyboardfokus geht beim Öffnen zum Vorgang, bei Fehlern zur Meldung, nach
Abschluss zurück zur Aktenübersicht. Lokales CSS begrenzt Tabellenoverflow.

## Tatsächlich ausgeführte Gates

**43 unterschiedliche synthetische UI-/Modell-/echte-Hookfälle sind grün**:
8 Modelle, 8 ReadUI, 2 Pendingrestore, 8 Controller, 6 OriginalChoices,
11 Formular-/Workspacefälle. Keine Backend- oder native Browserpasszahlen
werden diesen Unitnachweisen zugerechnet.

* Modelle/ReadUI/OriginalChoices gemeinsam: 22 PASS, 6,01 s.
* Echter Pendingrestore nach Sharedfix: 2 PASS; Controller: 8 PASS.
* Letzte ursprüngliche Formularserie: 8 PASS, 6,84 s, Exit 0.
* Gezielt hinzugefügte RestoredPendingActions: 3 PASS, 5,01 s;
  acht zuvor grüne Fälle wurden dort nicht ausgewählt.
* Aktualisierter echter Readonly-Selector: 1 PASS im relevanten Nachlauf.
* Scoped ESLint und `git diff --check` grün.

Ehrliche erste Fehler: Ein ReadUI-Währungsselector berücksichtigte NBSP nicht;
gezielt korrigiert, später komplette acht Lesefälle grün. Echter Sharedhook
auf f9-Basis verlor beim Restore nach 850 ms pending (1 FAIL/1 PASS);
Rootfix d40ea9c schloss das (2 PASS). Ein Formularselector wartete nach dem
beabsichtigten Source-Remount nicht auf den neuen Read; asynchron korrigiert,
relevanter Nachlauf und spätere ganze Achtserie grün. Kein Produktfehler wurde
durch künstlichen Nativeendpoint oder ausgelassene Behauptung verdeckt.

Noch offen unter Rootbesitz: tatsächlicher specialDraftpolicy-Nativenachweis,
vollständige Backendkomposition/Billingwiring, Produktionsbuild sowie ein einziger
abgestimmter Browserlauf mit nativer eigener SQLDB und echten APIs. Domain
meldete StatementChoice 7ed9100/Root fb70fa4 mit Memory-, vier SQLite- und vier
PG-HTTPfällen grün; das ist externe Domain-/Rootevidenz, kein eigener UIgate.
Der Browservorcodeplan wird separat geliefert. Keine A–L-Gesamtabnahme.
