# Package B: Wartung und Schäden

Aufbauend auf den nachgewiesenen Einheiten-/Dokumentadaptern, eigener Branch
`assist/bounded-legacy-lists`. Zuständigkeit: Wartungsrouter, eigene
`maintenance_list`-/`maintenance_inventory`-Module und Wartungsoberfläche,
zugehörige Tests. Keine Root-/Search-/Housing-/Billing-/Layoutdateien, keine
Migration und kein pauschaler Umbau anderer Listen.

1. Zuerst den belegten 10.000-Zwischendeckel der bestehenden Datumsroute
   entfernen. SQL-Filter und Berechtigung vor OFFSET/LIMIT, stabile NULL-/ID-
   Sortierung, Memory als begrenzter Heap. Bestehendes Array/Parameter/CRUD
   bleiben kompatibel. Test an Position 10.025, inklusive Scope/Offset/
   Gleichständen und schmutziger ORM-Session; echter PG, separater Commit.
2. Additive `/maintenance/inventory/page|summary|export`: kleine autorisierte
   Projektion mit Immobilien-/Einheitnamen, Cursorbindung und unabhängige
   Aggregate. Suche/Titel/Zuständiger/Handwerker/Gemeldet von sowie Status,
   Priorität, Kategorie, Immobilie/Einheit, Fälligkeit/Termin. Prüfansichten
   überfällig/ohne Termin/ohne Zuständigen. Überfälligkeit auf explizitem
   Tagesbezug je Anfrage statt seit Browserstart eingefrorenem Datum.
3. Bewährte gemeinsame Export-/Read-Bausteine nach zwei Fachadaptern gezielt
   extrahieren. Export bleibt vollständig und erhält SQL-Snapshot/Live-Fences.
   Es wird keine dateigroße Browser-/RAM-Grenze als dauerhafter Exportjob verkauft.
4. Übersicht mit serverseitigen Filtern, separatem Fehlerzustand pro Quelle,
   Folgeseiten, CSV. Bounded Immobilien-/Einheitenwahl, erhaltene Entwürfe bei
   Fehler, exakter Detailabruf vor Bearbeiten, vorhandene Revisionsprüfung.
   Alle bisherigen Fachfelder erhalten; Termine einschließlich Uhrzeit.
5. Backend Memory/SQLite/echtes PG, 101/1001/10001, vollständige Exporte und
   Summen, keine globalen Listen, Race-/Scope-/Tokenfälle. UI-Eingabefehler,
   Actor-/Filterwechsel; realer Browser 320/360/1440, Formular und Nachladen.

Erst danach Kontakte/Mieter als folgende einzelne Fachadapter. Zusätzliche
Indizes werden anhand tatsächlicher Abfragepläne separat vorgeschlagen und
vor einer Migration beim Root reserviert.

## Erste Lieferung: bestehender Datumsfilter

Implementiert in `maintenance_list.py`, am bestehenden Arrayendpunkt angebunden.
Datum, Property/Status und Berechtigungen greifen vor SQL-OFFSET/LIMIT; kein
10.000er Vorabruf. NULLs zuletzt und eindeutiger ID-Tiebreaker in beiden
Sortierrichtungen. Memory verwendet einen Heap von höchstens skip+limit;
der neue Cursoradapter wird später auch hohe Offsets vermeiden.

Nachweise 2026-10-03: Memory/SQLite **7 bestanden, 1 erwarteter SQL-only-Skip**,
30,33 s; echtes PostgreSQL **2 bestanden ohne Skips**, 21,11 s. Treffer 10.025,
Scopeentzug, stabile NULL-/Offset-Reihenfolge, unveröffentlichte ORM-Änderung
bleibt unangetastet, bestehender HTTP-Arrayvertrag erhalten. Ruff/Mypy 3.11
bestanden. Logs `maintenance-date-backend.log`, `maintenance-date-pg.log`.
Der erste Testlauf erwartete fälschlich 401 bei Scopeentzug; die bestehende
403-Semantik wurde korrekt im Test abgebildet, Runtime nicht umgebogen.
