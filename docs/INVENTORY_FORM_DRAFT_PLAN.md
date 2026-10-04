# Einheiten, Dokumente und Wartung: dauerhafte Formularentwürfe

2026-10-03, eigener Branch `assist/bounded-legacy-lists`, Basis `8a6c1afa`.
Dieses Paket ist vom Root nach Kontakte separat freigegeben. Plan vor Code.

## Umfang und Grenzen

Nur eine optionale feldbezogene Erweiterung des bestehenden `FormModal`, die
drei eigenen Inventaradapter und unmittelbar zugehörige Tests/Styles. Keine
Änderung an DataTable, Layout, Search, Housing, Billing, Root-API,
workflow_references, Tenant-Privacy oder Datenbankschema. Root integriert selbst;
kein Schreiben in Root/Main/Vorschau und keine eigene Integration.

1. `field.render({ value, values, onChange, inputProps })` ergänzt die bestehenden
   Standardfelder. Der Renderer verändert dieselben FormModal-Werte; abhängige
   Referenzen verwenden weiterhin `field.onChange`, optional mit Auswahldetail.
   Busy/Disabled und Fehlerhinweise bleiben berücksichtigt. Keine zweite
   Draftpersistenz, kein Picker-Sidecar und kein Gesamtbestandsabruf.
2. Immobilien-/Einheiten-/Vertrags-IDs werden echte deklarierte Felder der drei
   Formulare. Ausschließlich bestehendes `draftConfig`/`useFormDraft` verwenden.
   Beim Wiederherstellen werden alle IDs erneut über bounded Choices geprüft.
   Immobilienwechsel löscht abhängige Einheit/Vertrag; Einheit-/Vertragswahl
   übernimmt die belegten übergeordneten IDs in einem einzigen Werteupdate.
3. Speichern verwendet die am Payload erhaltene Originalrevision vor der später
   gelesenen Modalrevision. Ein echter konkurrierender Writer muss 412 auslösen;
   Eingaben und Referenzen bleiben erhalten. Benutzer-/Grantswechsel entfernt
   Formulare und bricht eigene Reads/Uploads ab; späte Antworten bleiben privat.
4. Dokumente behalten `file_url` als bereits hochgeladene Referenz im selben
   Draft. Wiederherstellung darf sie nicht mit einem leeren Uploadzustand
   überschreiben. Neue Uploads aktualisieren diesen Wert gezielt; Datei-Bytes
   werden nicht im Draft gespeichert. Vorhandene Upload-/OCR-/Versionswege
   bleiben erhalten. Wartung speichert die ursprüngliche vollständige Terminzeit
   als Draftsnapshot und verwendet sie, solange das sichtbare Feld unverändert
   ist, auch nach Wiederherstellung.
5. Der bestehende Unsicherheitszustand nach verlorenem/5xx-Ergebnis bleibt
   bestehen. Keine automatische Geschäfts-POST-Wiederholung. Browsernachweise
   prüfen vor expliziter Fortsetzung den tatsächlichen bounded Bestand und bei
   Create auch einen bereits gespeicherten Datensatz, um keine Dublette blind
   anzulegen. Alte abweichende Feldschemas werden weiterhin kontrolliert
   zurückgewiesen; keine automatische Schemamigration und kein stilles Löschen.

## Geplante Abnahme

- Fokussierte FormModal-/FormDraft- und Inventartests: Rendererwerte inklusive
  abhängiger IDs, Reloadrestoration, geänderte Referenzen, Revisionvorrang,
  Dateireferenz und Terminpräzision, Savefehler und Actor-/Scope-/Grantsraces.
- Echter Edge mit frischer synthetischer SQLite-App: dauerhafter Draft über
  Reload bei allen drei Adaptern, Auswahl jenseits erster Referenzseiten,
  echte konkurrierende Writer/412, 503 bzw. verlorene Createantwort mit
  Bestandsprüfung vor Fortsetzung; Tastatur und 320/360/1440 ohne Überlauf.
- Bestehende Dokument-OCR/Versions- und Kontakte-Draftregressionen,
  Produktionsbuild, scoped ESLint und diff-check.
- Keine Backendänderung, daher kein neues eigenes schweres Backend-/PG-Gate.
  Browser- und UI-Gates starten erst nach Root-Slotfreigabe und nacheinander.
  Tatsächliche Ergebnisse, Fehlläufe und offene Grenzen in separatem Handoff.
