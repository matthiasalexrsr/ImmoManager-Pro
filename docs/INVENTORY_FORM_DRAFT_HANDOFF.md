# Einheiten, Dokumente und Wartung: gemeinsame Formularentwürfe

2026-10-03, eigener Branch `assist/bounded-legacy-lists`, Basis `8a6c1afa`.
Plan separat vor Umsetzung committed: `3f0e0f0`,
`docs/INVENTORY_FORM_DRAFT_PLAN.md`. Root integriert selbst.

## Umsetzung

`FormModal` erhält ausschließlich den optionalen Feldrenderer
`render({ value, values, onChange, inputProps })`. Das optionale zweite Argument
von `onChange` wird an die bestehende Feldabhängigkeit als drittes Argument
weitergereicht. Standardfelder bleiben unverändert. Eigene Renderer erhalten
Disabled/Required/Name/ID und Fehlerzuordnung; Picker zeichnen ihren bestehenden
zugänglichen Fieldset/Legend. Vom Renderer verwaltete versteckte Dateireferenzen
werden bei einer bloßen Felderneuberechnung nicht mit leeren Uploaddefaults
überschrieben. Der bestehende Draft-Hook und die bestehende Verschlüsselung
werden unverändert verwendet; keine weitere Draftpersistenz.

Die drei Inventare deklarieren Referenz-IDs als tatsächliche FormModal-Felder.
Immobilienwechsel löscht abhängige IDs; Einheiten-/Vertragswahl übernimmt die
berechtigten übergeordneten IDs zusammen mit der Auswahl. Restorierte IDs werden
über begrenzte Workflowchoices samt selected_id erneut gelesen. Beim Speichern
hat die Payloadrevision Vorrang vor der später gelesenen Modalrevision.

Einheiten laden jetzt vor Edit den vollständigen exakten Datensatz nach. Das
erhält insbesondere Etage/Ausstattung und prüft die Antwort-ID, statt den kleinen
Listenrow zum Originalsnapshot zu erklären. Auch frühere Einheitstypwerte
`Wohnung/Gewerbe/Stellplatz/Keller/Sonstiges` sind im Createformular auswählbar;
keine Umcodierung gespeicherter Originale oder früherer Draftwerte.

Dokumente behalten die hochgeladene `file_url` im selben Draft. Nach Reload ist
kein erneuter Upload erforderlich; nur tatsächlich neu abgeschlossene Uploads
setzen diesen Formularwert neu. OCR, Originalbytes, Vorschau und Versionen bleiben
in ihren bisherigen Abläufen. Ein Actor-/Grantswechsel abortiert zusätzlich
aktive eigene Dokument-Reads/Uploads. Wartung speichert die vollständige
ursprüngliche `appointment_at`-Zeichenfolge; nur der Feldrenderer formatiert
die Anzeige. Revisionquelle und Terminpräzision bleiben auch nach Restore erhalten.

Actor-/Scope-/Grantswechsel entfernen die Formularinstanz und ihre Inhalte;
veraltete Reads und Draftantworten werden verworfen. Savefehler erhalten Werte.
Ein unbestätigter Create-/5xx-Ausgang sperrt weiterhin das Speichern und verlangt
die bestehende ausdrückliche Bestandsprüfung vor Fortsetzung. Keine automatische
POST-Wiederholung und kein neu behaupteter serverseitiger Idempotenzmechanismus.
Die geprüfte Bedienfolge sucht nach bereits gespeicherten Zeilen, bevor ein
Pending-Draft fortgesetzt oder nach erkanntem Erfolg ausdrücklich verworfen wird.

Keine Änderung an Backend, Migration, workflow_references, Tenant-Privacy,
DataTable, Layout, Search, Housing oder Billing; kein Root/Main/Vorschauwrite.

## Bisherige Nachweise und ehrlicher Gatezustand

- Gezielte UI-Suite: Erstlauf **102 bestanden, 1 neue Testannahme fehlgeschlagen**,
  79,43 s. Nur die Erwartung der vom DOM normierten datetime-local-Zeichenfolge
  war zu eng (`.000`); gespeicherter Originalwert war nicht verändert.
  Fokussierter Nachlauf **7 bestanden**, 9,81 s; nach reiner Testhelperbereinigung
  nochmals **7 bestanden**, 16,58 s. Damit alle **103 bisherigen Fälle** belegt:
  FormModal/FormDraft, drei Inventare, Kontakte, Dokument-OCR und Versionshistorie.
  Der zuletzt hinzugefügte Altwert-Createfall wartet noch auf den kleinen UI-Gate.
- Echter Edge, erster kombinierter Lauf mit frischer synthetischer SQLite-App:
  **5 bestehende Fälle bestanden**, 5,8 min Gesamtzeit. Kontakte 2,
  Einheiten/Dokumente/Wartung je 1: vollständige CSV, 503 → tatsächlicher Readproof
  → ausdrückliche Fortsetzung → Retry; bestehende private Felder/Versionen,
  320/360/1440 ohne horizontalen Seitenüberlauf.
  **4 neue Fixturefehler**: Choice-IDs werden absteigend statt nach Anlagezeit
  sortiert; beim neuen Dokumentoriginal fehlte der Pflichtupload. Testfixtures
  korrigiert: garantierter 26. Eintrag über kleinste ID und echter Originalupload.
- Fokussierter zweiter Edge-Lauf: **3 neue Fälle bestanden** (9,3/8,8/7,3 s).
  Alle drei Inventare: tatsächlicher verschlüsselter Draft über Reload,
  restaurierte Auswahl des 26. Referenzeintrags, echter unabhängiger Writer,
  PUT mit restaurierter Originalrevision liefert 412, fremde Änderung bleibt
  erhalten. Wartung sendet unverändert alle ursprünglichen Mikrosekunden.
  Neue Dialogscreenshots 320/360/1440 erzeugt; 320 und Desktop visuell geprüft.
  Der vierte Createfall belegt schon erhaltene Dateireferenz über Reload,
  tatsächlich erfolgreiches POST mit verlorener Antwort/503, Save gesperrt,
  genau eine aktuelle Bestandszeile und unveränderte herunterladbare Originalbytes.
  Sein letzter Cleanup-Schritt scheiterte am verkürzten Selector. Dieser ist
  korrigiert (`Gespeicherten Entwurf verwerfen`); einzelner Endnachlauf ausstehend.
- Produktionsbuild in beiden Browserläufen erfolgreich. Scoped ESLint für
  Quell-/Test-/Browserdateien ohne Warnungen bestanden; nach dem letzten kleinen
  Altwert-/Selectorupdate noch einmal statisch prüfen. diff-check bestanden.
- Keine eigenen Backend-/PostgreSQL-Gates, weil kein Backend geändert wird.
  Browser liefen nacheinander in eigenen frischen Datenverzeichnissen;
  PostgreSQL-Dienst und private Daten blieben unangetastet.

Belege: `inventory-form-drafts-ui.log`, `inventory-form-drafts-ui-final.log`,
`inventory-form-drafts-e2e.log`, `inventory-form-drafts-e2e-final.log`,
`inventory-form-drafts-lint-final.log`. Der Create-Einzelnachlauf erhält eine
eigene Logdatei. Aktuell keine laufende eigene Testsitzung; Browserrunner 42994
und 72606 und UI-Runner 71532/32578/25493 sowie Lint 83584 sind beendet.

## Verbleibend vor finaler Paketabnahme

1. Nach Ende des reservierten Root-PG/History-Gates: kleiner UI-Gate mit dem
   zusätzlichen Altwertfall und unveränderten neuen Draftfällen (8 Fälle),
   scoped ESLint und Build auf finaler Quelle.
2. Genau der einzelne korrigierte Document-Createverlust-/Cleanupbrowserfall.
   Die drei bereits grünen Real-412-Fälle und fünf Bestandsregressionen werden
   ohne zusätzliche Quelleänderung nicht erneut teuer geprüft.
3. Finalen Gatezustand und Prozessbereinigung in diesem Handoff ergänzen.

Alte abweichende Draftfeldschemas (insbesondere frühere Wartungs-Date-only-
Schemas) bleiben unter dem bestehenden sichtbaren Schutz erhalten und werden
kontrolliert zurückgewiesen; keine automatische Schemamigration oder Löschung.
Mieter/Zähler als nächste B-Adapter erst nach Root-Abstimmung; Domainprivacy und
Root-Workflowreferenzen bleiben bei ihren bisherigen Ownern.
