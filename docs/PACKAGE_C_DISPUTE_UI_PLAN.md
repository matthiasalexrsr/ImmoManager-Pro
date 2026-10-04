# C: Widerspruchsakte in der bestehenden Abrechnungsbedienung

Plan vor Code, 2026-10-03. Saubere Basis `f9e8edc`; eigener Checkout
`work/billing-dispute-ui`, Branch `assist/billing-dispute-ui`. Grundlage:
vollständig freigegebene Roadmap A–L, `PACKAGE_C_DISPUTE_JOURNAL_PLAN.md`,
dessen tatsächlicher Handoff und die geprüften Router/DTOs/Dienste.
Kein A–L-Gesamtabschluss und kein neuer finanzieller Automatismus.

## Nachgewiesene Ausgangslage und Eigentum

`Statements.jsx` bietet Perioden-, Kosten- und Einzelabrechnungsansichten,
bereits getrennte Zustellung/Korrektur/Forderungsbestätigung. Sein alter
Widerspruchbutton sendet den privaten Grund im Queryparameter an den inzwischen
abgewiesenen Periodenendpunkt. Die bisherige Abrechnungsansicht lädt sämtliche
Stammdaten/Statements über `getAll`; dieses Paket ergänzt darin einen kleinen
konkreten Einstieg, übernimmt diesen Bestand aber nicht als neuen Aktenselector.

Die echten neuen Wege liegen unter `/billing/disputes`: Open/Append-Preview,
Open/Append-Bestätigung, keysetbasierte Aktenliste, Detail, Chronik,
Originalereignis und Periodenstatus. Sie liefern JSON-DTOs und exakte Quittungen.
`OpenDispute` bindet konkrete finalisierte Einzelabrechnung, Revision, Hash,
Eingangsdatum, Grund, Positionen und Originalversionen. `AppendDisputeEvent`
bindet aktuelle Aktenrevision und eine der sieben tatsächlichen Folgeaktionen.
Der identische Actor/Befehl liefert dieselbe Quittung; anderes Inhaltspaar oder
veraltete Revision ergibt 409. Keine neue Kennung bei verlorenem Ergebnis.

Eigener Besitz: neue `billingDisputes`-Featuredateien/CSS/gezielte Tests/docs;
gesonderter kleiner `Statements.jsx`-Wiringcommit und eigener i18n-Slice.
Keine Backend-, DDL-, Modell-/Registry-/Recovery-/CI-, Shared-FormModal-,
Draft-/Policy-/Referenz- oder sonstigen Billingproduktänderungen. Root besitzt
gemeinsame Draft-/Choiceverträge und Nativekomposition; Domain erweitert gerade
belegte Personenbindung zukünftiger Originale. Nur saubere freigegebene
Nachfolgecommits aufnehmen, niemals uncommittete Rootquellen kopieren.

## Verbindliche UI-Abläufe

Die neue Aktenregion sitzt im ausgewählten Periodenkontext. Sie lädt zunächst
den tatsächlichen Periodenstatus und eine begrenzte gefilterte Aktenseite.
Statusfilter und Vor-/Zurückblättern behalten höchstens eine Seite, keinen
wachsenden Aktenbestand. Gesamt-/offene Zahlen kommen aus dem echten Status.
`legacy_disputed_without_complete_case` bleibt ausdrücklich ein Altstatus ohne
erfundene vollständige Akte. Die Sammelperiode wird nicht durch Aktenaktionen
auf disputed gesetzt, und Finanz-/Zustellabläufe bleiben gesondert bestätigt.

Eröffnung wählt den tatsächlichen Vorgangstyp: Einzelabrechnung oder
Objektprüfung auf der vorhandenen Eigentümergrundlage. Einzelabrechnungen
kommen aus einer echten autorisierten bounded Auswahl, danach exakter GET
`/billing/statements/{id}`. Tabellenprojektionen sind keine Originalquelle.
Objektprüfung benutzt ausschließlich Original/Hash des echten Periodenstatus,
ohne willkürlichen Mietbezug. Anzeige nennt Quelle/Revision/Datum/Beträge,
Positionen und historischen Personenhinweis; heutige Stammdaten ersetzen
keine eingefrorene frühere Identität.

Grund und tatsächlicher Eingang werden eingegeben; Positionscheckboxen nennen
Originalindizes und originale Beschreibungen/Beträge. Eine begrenzte Darstellung
der Positionen eines einzelnen ohnehin vollständigen Originalsnapshots ist
kein begrenzter Gesamtbestand. Originalanlagen werden in zwei echten Stufen
gewählt: `workflow-references/documents` mit Objekt-/Vertragskontext, dann
`/documents/{id}/versions?before=...&limit=25`. Nur unveränderliche bestehende
Versionen, keine mutable Datei als Ersatz und kein Uploadautomatismus.
Ausgewählte Versionen bleiben explizite IDs; die Domain prüft Bytes/Bindung
nochmals. Fehlende/verdeckte Auswahl ist reparierbarer Fehler, keine leere
historische Aussage.

Vorschau sendet vollständigen DTO als JSON. Die Antwort muss dieselben
Eingaben/Kennungen/Revisionen binden. Danach Originalfassung, Positionen,
Grund/Datum, Anlagenmanifeste und die konkrete Folgeaktion lesbar prüfen.
Bestätigen sendet exakt `preview.request` plus denselben `preview_hash`.
Jede Eingabeänderung verwirft ausschließlich die Vorschau und fordert eine
neue Prüfung; kein stilles Aktualisieren einer ursprünglichen Revision.

Akte lesen: exaktes Detail mit original_snapshot, ursprünglicher Bindung,
Hash/Revision, aktuellem Zustand und latest_event. Chronik paginiert nach
Revision, zeigt Erfassung und tatsächliches Beobachtungsdatum getrennt,
Grund/Actor/Positionsbezug/Anlagen sowie Berichtigungs- und Korrekturverweise.
Originalereignis bei Bedarf exakt nach ID lesen. Originalversionsdownload
verwendet ausschließlich den echten authentifizierten Versionsweg, mit
Abbruch bei Kontext-/Actorwechsel und freigegebenen Objekt-URLs.

Notiz, Prüfung, Rücknahme, Abschluss, Wiederaufnahme, Berichtigung und
Korrekturverknüpfung entsprechen dem tatsächlichen `event_state`:
Prüfung/Rücknahme/Abschluss bei open/in_review, Wiederaufnahme bei
withdrawn/closed, Notiz/Berichtigung/Link in allen bestehenden Zuständen.
Berichtigung nennt ein geprüftes unverändertes Ereignis derselben Akte;
die Korrekturverknüpfung wählt eine tatsächlich finalisierte Quellenkette.
Frühere Ereignisse/Abrechnungen bleiben vollständig sichtbar erhalten.

## Private dauerhafte Befehlsentwürfe – notwendiger Rootvertrag

Die bestehende `form_drafts.POLICIES` erlaubt keine Journalbefehle;
`_safe_values` erlaubt Strings und Stringlisten, aber keine Integerlisten
oder komplexe Original-/Previewobjekte. Neue UI schreibt keinen Sidecar,
LocalStorage oder parallelen Draftdienst. Der unveränderte gemeinsame
`useFormDraft`-Kern wird direkt mit eigenem aktengebundenem UIadapter genutzt;
gemeinsame Hooks/FormModal/Policies bleiben Rootbesitz.

Vorgeschlagener Rootvertrag: collection `billing/disputes`, entity_id null,
form_key `open:<period-uuid>` beziehungsweise `event:<case-uuid>` (unter 80
Zeichen). Skalare fields/values/original_values: `period_id`, `case_id`
(leer bei Eröffnung), `command_json`, `review_json`. Die JSONstrings erhalten
auch unvollständige Formulareingaben, vollständige DTOs/Positionen/Versionen,
die UUID und nach Vorschau deren vollständigen Hash/Bindung. Root muss
Struktur, Kontext und tatsächliche Referenzen frisch autorisieren; kein
umbenannter gewöhnlicher Stammdatendraft. `submission_pending`, Verschlüsselung,
TTL/Bytebudget, Tab-CAS und Actor/Grantschutz bleiben der bestehende Kern.

Vor Domainbestätigung ist die unveränderte vorbereitete Nutzlast erfolgreich
als pending zu persistieren. Ein 5xx/Netzfehler oder ungültiges Erfolgsergebnis
verriegelt die Nutzlast; Reloadrestore erhält exakt denselben Befehl mit
Previewhash/Idempotenzkennzeichen. Bewusstes erneutes Senden darf nicht erst
eine neue Vorschau oder UUID erzeugen. Erfolgsquittung wird geprüft, danach
Draftcleanup separat; Cleanupfehler dürfen keinen DomainPOST erneut auslösen.
Bekannte 409/412 erhalten Eingaben; aktuelles Original/Revision wird bewusst
geprüft, bevor eine neue Vorschau entsteht. Automatisches Rebase oder Ersatz
einer möglicherweise schon bestätigten Befehlskennung ist ausgeschlossen.

## Tatsächlich fehlender bounded Choicevertrag – Rootbesitz

Bestehendes `ReferenceKind` kennt keine UtilityStatements; Query kennt keine
Periode/Akte. Vorschlag: realer `workflow-references/statements`-Vertrag mit
`period_id` bei Eröffnung oder `dispute_case_id` bei Korrekturwahl plus
search/selected_id/cursor/page_size. Bestehende Form `{items, selected,
has_more, next_cursor}`; minimale Projektion id/label/billing_period_id,
contract_id/unit_id, revision/snapshot_hash/status und ausschließlich belegte
Personenanzeige. Eröffnung: echte immutable Statements der Periode mit Hash;
Korrektur: echte finalisierte Quellenkette zur Akte/derselben Person.
selected_id frisch autorisieren. Vollquelle folgt über vorhandenen exact GET.
Kein fake Weg bis Root diesen oder einen konkret genannten alternativen
Journalchoicevertrag sauber implementiert. Die Document-/Versionenwege
existieren bereits und werden tatsächlich genutzt.

## Berechtigungen, Navigation und Darstellung

Eigentümer/Verwalter/Buchhaltung erhalten Billingbefehle, Techniker/Readonly
nur tatsächlich autorisierte Lesewege. Aktuelle Servergrants und nicht bloß
Rollennamen sind maßgeblich. Principal enthält Actor/Role/Portfoliogrants/
write_permissions. Perioden-/Akten-/Actorwechsel abortieren eigene Reads,
Previews, Writes und Downloads; alte Antworten veröffentlichen nichts im
neuen Kontext. Scopefehler verbergen private Detail-/Forminhalte und bieten
bewusstes erneutes Lesen. Serverfehler bleiben Fehler; fehlende Familien sind
kein leeres Journal. Alle Bereiche haben Namen, Labels, Fokus nach Öffnen/
Fehler, natürliche Tastaturreihenfolge und responsive lokale Tabellen.

## Kleine Commits und koordinierte Prüfung

Nach diesem Plan zuerst reine DTO-/Response-/Stateadapter und eigene
Featurekomponenten; danach gesondert Billingwiring/i18n und zielgenaue Tests.
Rootabhängigkeiten werden ausdrücklich gemeldet; unabhängig mögliche Reads/
Darstellung werden weiter entwickelt. Keine schweren PG-/Browser-/Nativegates
ohne abgestimmten Slot, keine Dienste beenden.

Gezielte UI-Fälle: echte bounded Akten-/Chronik-/Choiceverträge, exakte
Originalquelle, Altstatus/Personengrenzen, Previewgleichheit/Änderungsinvalidierung,
vollständige DTOs/Positions-/Originalanlagenbindung, erlaubte Zustandsaktionen,
echte Fehler vs leer, 409/412-Eingabenerhalt, schneller Kontextwechsel und
Scopeentzug, verschlüsselter Draftreload mit exakt gleichem pending Befehl,
Erfolg trotz verlorener Antwort ohne zweite Akte, separater Cleanupretry,
Originalversionsdownload. Berührte bestehende Statement-/Translation-/Rollen-
Prüfungen nur gezielt an den ersetzten alten Widerspruchbutton anpassen.

Root übernimmt tatsächliche Backendkomposition. Ein einzelner später
koordinierter echter Browserlauf nutzt synthetische finalisierte Abrechnung
und archivierte Originalanlage, Chronik/Folgeereignisse/Berichtigung/Link,
verlorene Bestätigung und Reloadretry, Rechte/Fokus sowie 320/360/1440.
Nur tatsächlich ausgeführte Gates/Skips behaupten. Saubere Quellencommits und
ehrlicher Handoff nennen Rootabhängigkeiten und bleiben auf Paket C begrenzt.
