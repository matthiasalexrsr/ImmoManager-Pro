# Vollständige Einheitenliste

Basis `5e636e0`, Branch `assist/bounded-legacy-lists`, 2026-10-03.

Neue additive Routen `/units/inventory/page`, `/summary`, `/export` behalten
alle bestehenden CRUD- und Arraylisten bei. Suche, Status/Art, Immobilie,
Flächen-/Mietbereich und Prüfansichten wirken vor dem SQL-Limit. Stabile
NULL-/ID-Sortierung, signierte Cursor mit Query-/Benutzer-/Scopebindung.
Getrennte vollständige Aggregate zählen nur passende berechtigte Einheiten;
Nullmieten werden berücksichtigt, fehlende Mietbeträge getrennt behandelt.
Mehrere aktive Verträge werden sichtbar, nicht als beliebiger Mieter ausgegeben.

CSV kommt vollständig aus derselben gefilterten SQL-Quelle, begrenzten Batches
und eigener Lesetransaktion. Vor jeder Ausgabe werden Zugriff, Anmeldung und
die aktuelle berechtigte Projektion erneut geprüft. Änderungen führen zu
einem fehlgeschlagenen Export, keiner behaupteten vollständigen Teildatei.
Textformeln werden geschützt. Memory-Referenzbetrieb verwendet begrenzte
Live-Seiten. Der Browser löst den Download erst nach vollständigem Empfang
aus; sein Blob belegt die Größe der fertigen Datei, kein globaler Listen-Cache.
Ein persistenter wiederaufnehmbarer Exportauftrag bleibt eine getrennte
Erweiterung für sehr große Exporte; dieser Stand behauptet ihn nicht.

Die Einheitenoberfläche erhält serverseitige Filter/Sortierung, getrennte
Kennzahlen, erreichbare Folgeseiten und vollständigen Export. Exakte, bounded
Immobilienauswahl verwendet vorhandene Workflowreferenzen. Such-/Formulareingaben
bleiben bei Fehlern erhalten. Revisionsschutz bleibt an der gelesenen Einheit;
Benutzer-/Scopewechsel entfernen alte private Inhalte und Formulare synchron.
Nur eigene Komponenten/Styles, bestehendes DataTable/FormModal unverändert.

Nachweise:

- Memory/SQLite: **25 bestanden, 1 erwarteter Memory-Skip** (SQL-Identitymap),
  72,24 s. Suche an Position 101/1001/10001, CSV mit 10.002 Zeilen, Aggregate,
  NULL-/Gleichstandsortierung, keine globalen Listen, Autoflush, Scopeentzug,
  Formular-/Legacy-HTTP-Kompatibilität und späte Veröffentlichungsprüfung.
- Tatsächliches PostgreSQL, nach kontrolliertem Wiederstart durch den
  Plattform-Agenten: **2 bestanden**, 45,72 s, strikter Gate-Runner bestätigt
  null Skips; volle 10.002-Zeilenquelle/CSV und stabile NULL-Sortierung.
- UI: **10 bestanden**, 5,42 s; Filter-/Actor-/Scope-/Rollenraces, fehlende
  Kennzahlen, Formfehler mit erhaltenem Originalstand und vollständiger Export.
- Echter Edge: **1 bestanden**, 14,4 s; 102 Immobilien, spätere Referenzwahl,
  27 Einheiten/Seiten 25+2, CSV mit allen 27 vom zweiten Fenster aus,
  503-Speicherfehler → erhaltener Entwurf → erfolgreiches Anlegen. Viewports
  320/360/1440 ohne horizontalen Seitenüberlauf. Anschließend ausschließlich
  scoped CSS für Eingabehöhe, Tabellenbreite und kompakte mobile Kennzahlen
  verbessert; abschließende kombinierte Browserprüfung folgt mit Dokumenten.
- Ruff, scoped ESLint, Mypy Ziel 3.11 und Produktionsbuild erfolgreich.

Belege im Worktree: `unit-inventory-backend.log`, `unit-inventory-pg.log`,
`unit-inventory-ui.log`, `unit-inventory-e2e.log`, `unit-inventory-build.log`.
Früherer PG-Versuch scheiterte mangels Listener; das spätere echte Gate ersetzt
diesen Versuch nicht stillschweigend durch einen Skip. Keine neue Migration,
keine Änderung fremder Search-/Housing-/Billing-/Layoutdateien.

Der Dokumentadapter ist im selben Worktree als folgende separate Lieferung in
Arbeit und wird nicht als bereits erledigt erklärt. Nach beiden nachgewiesenen
Fachadaptern können die gemeinsamen Cursor-/Export-/React-Bausteine gezielt
extrahiert werden; kein Massenumbau der übrigen Listen.
