# Kontakte: vollständiger berechtigter Bestand und erhaltene Entwürfe

2026-10-03, eigener Branch `assist/bounded-legacy-lists`, auf `eb7df7e`.
Plan vor Umsetzung: `CONTACT_INVENTORY_PLAN.md`. Keine Migration und keine
Änderungen an Tenant-Privacy/Lifecycle, workflow_references, globalem Layout,
Search, Housing oder gemeinsamen UI-Dateien.

## Ergebnis

Der bestehende `/contacts`-Arrayendpunkt bleibt kompatibel, liest jetzt mit
Scope und Sortierung vor OFFSET/LIMIT aus SQL statt erst den ganzen Bestand
in RAM zu laden. Neue `/contacts/inventory/page|summary|export` liefern stabile
Cursorseiten, unabhängige Gesamtkennzahlen und die vollständige gefilterte
CSV-Quelle. Suche, Rolle, fehlende E-Mail/Telefon/Name und Sortierung werden
serverseitig angewandt. Die Listenprojektion enthält allgemeine Kontaktdaten;
Bank-/Steuerdaten und Notizen bleiben im exakt geladenen Einzelkontakt.

Die Kontakte behalten die bestehende Identität und explizite Portfolio-Grants.
Historische ungebundene Kontakte werden beschränkten Benutzern nicht zusätzlich
sichtbar gemacht. Kein automatisches Zusammenführen mit Tenant-Profilen.
Cursor und Ausgabe sind an Query/ActorScope gebunden; Export nutzt den bereits
geprüften gemeinsamen Snapshotexporter mit begrenzten Batches, Formelschutz und
erneuter Scope-/Token-/Datenprüfung. Vor Bearbeiten wird das vollständige Detail
samt Originalrevision gelesen. Land und BIC sind nun auch im Formular verfügbar.

Die Oberfläche verwendet den vorhandenen Inventoryhook mit eigenen Adaptern:
getrennte Fehler-, Lade- und Leerzustände, vollständige Kennzahlen, Seitenwechsel
und unabhängiger Export. Actor-/Scopewechsel entfernen alte vertrauliche Daten;
verspätete Antworten oder abweichende Detail-IDs werden verworfen. Bestehender
verschlüsselter Formulardraft bleibt eingebunden. Beim Wiederherstellen hat
dessen Originalrevision Vorrang vor der später gelesenen Formularrevision;
ein inzwischen geänderter Kontakt wird daher mit 412 geschützt statt überschrieben.

## Nachweise

- Memory/SQLite: **20 bestanden, 2 erwartete SQL-only-Memory-Skips**, 88,28 s.
  Positionen 101/1001/10001, 10.002 vollständige CSV-Zeilen, Legacy-OFFSET 10000
  mit vollständigem DTO, unabhängige Aggregate, kleine Projektion, explizite
  Grants, entzogenes Exportrecht, NULL-Sortierung, Unicode-Suche, kein Autoflush,
  reale Exportkonkurrenz und letzte HTTP-Veröffentlichungsprüfung.
- Tatsächliches PostgreSQL: **5 bestanden, keine Skips**, 58,80 s; strikter
  Gate-Runner bestätigt alle Fälle. Große Quelle, Grants, Anzeigenamen,
  NULL-Cursor und realer konkurrierender Exportwriter.
- Oberfläche: **9 bestanden**, 28,23 s. Serverpagination/Fehler, vollständige
  Felder und Revision, Benutzer-/Scope-/Rollenwechsel, alte Seitenantworten,
  falsche Detail-ID und fehlgeschlagener vollständiger Export.
- Echter Edge mit frischer synthetischer SQLite-App: **2 bestanden**, 20,8 s.
  27 Kontakte als 25+2; vollständiges CSV von Seite 2 ohne private Bank-/Steuer-
  und Notizfelder; echter verschlüsselter Draft nach Reload wiederhergestellt;
  503 erhält Eingaben, Bestandsprüfung und Retry erfolgreich; vorhandene private
  Felder erhalten. Zweiter Fall: realer konkurrierender Writer nach Draftspeichern,
  Wiederherstellung und PUT liefern 412, fremde Änderung bleibt erhalten.
  Viewports 320/360/1440 ohne Seitenüberlauf, Desktop und 320 visuell geprüft.
- Produktionsbuild, scoped ESLint, Ruff, Mypy Ziele 3.11/3.12 und diff-check grün.

Logs im Checkout: `contact-inventory-backend.log`, `contact-inventory-pg.log`,
`contact-inventory-ui.log`, `contact-inventory-e2e-final.log`. Der erste
Browserversuch (`contact-inventory-e2e.log`) erreichte bei gemessener 100%-CPU-
Hostlast den Backendstart nicht innerhalb von 90 s; keine Tests liefen dabei.
Nach Ende des parallelen schweren Root-Gates lief genau ein frischer Versuch
vollständig erfolgreich. Finale Exec-Sitzung 69776 beendet mit Exit 0; keine
verbliebenen Python-/Node-/Edge-Prozesse mit diesem Checkout oder temporärem
Browser-App-Pfad gefunden. Gemeinsamer PostgreSQL-Dienst bleibt unangetastet.

## Verbleibende Aufgaben / Übergabe

- Vollständige CSVs sind serverseitig begrenzt gelesen, der Browser-Blob bleibt
  dateigroß. Dauerhafte wiederaufnehmbare Exportaufträge bleiben Folgepflicht.
- Alte persönliche Drafts mit abweichendem Feldschema werden vom bestehenden
  Schutz kontrolliert zurückgewiesen; keine automatische Schemamigration und
  kein stilles Verwerfen dieser Drafts.
- Units/Documents/Maintenance haben erhaltene Eingaben im offenen Fehlerdialog,
  ihre neuen Referenzpicker sind aber noch nicht an permanente Draftrestoration
  angebunden. Root hat als separates nächstes Paket einen optionalen Feldrenderer
  in FormModal plus diese drei eigenen Adapter autorisiert. Erst Plan schreiben;
  kontrollierte Referenzen vollständig in FormModal-Werte/Draftpayload übernehmen,
  restaurierte Originalrevision schützen, Dokument-Dateireferenzen und Terminzeit
  erhalten. Keine weitere gemeinsame UI-Datei ändern.
- Danach Mieter und verbleibende Altlisten einzeln; Tenant-Privacy/Lifecycle
  weiter unter Domain-Ownership, workflow_references unter Root-Ownership.

Nach diesem Kontakte-Commit keine weiteren Code-/Testarbeiten bis zur vom Root
angekündigten Modellübergabe (Nutzerwunsch GPT-6.1 Sol, Sehr Hoch).
