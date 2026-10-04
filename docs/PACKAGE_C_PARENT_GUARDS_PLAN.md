# Paket C5: Elternschutz und Personenbezug

Konkretes Addendum vor Code, Basis `bc90599`, eigener Branch
`assist/measurement-parent-guards`. C0–C4 bleiben unverändert erhalten.

## Tatsächliche Anbindung

SQL-Update/Patch läuft in `BaseRepository._write`, Löschung in `delete`.
Beide benutzen bereits `no_autoflush_guard` und Lifecycle-Elternsperren.
Die neue Messquellensperre muss **vor** diesen Elternsperren liegen, wie
bei `measurement_history.work`: Accountverwaltung, Messimmobilie, Eltern.
Direkte Repository-Aufrufer müssen denselben Weg verwenden wie HTTP.
Memory-Update/Patch/Delete läuft durch `_version_mutation`; dort lässt sich
der gemeinsame Schutz vor jeder Mutation und vor Teil-Kaskaden einsetzen.

Neue eigene Guardfunktionen prüfen nur Existenzbits außerhalb der
Portfoliofilter, damit verborgene Originale geschützt sind, ohne IDs oder
Inhalte offenzulegen. Unit→Property, Property→Portfolio,
Contract→Property/Unit/Tenant und AllocationKey→Property bleiben bei
historischen Quellen unverändert. Normale Bezeichnungen/Termine werden
nicht pauschal gesperrt. Meter→Unit bleibt erlaubt; datierte Zuordnungen
sind gerade keine Kopie der heutigen Zählerstammdaten.

Löschungen von Portfolio, Immobilie, Einheit, Vertrag, Mieter, Zähler und
Schlüssel prüfen auch zurückgenommene Originale. Dokumentversionen bleiben
im vorhandenen unveränderlichen Dokumentoriginalschutz; vorhandene
Evidence-Referenzen ergänzen dessen Memory-Elternschutz. Keine Historie
wird bei Fehlern umgeschrieben oder aus aktuellen Stammdaten rekonstruiert.
Konflikte erklären Aufbewahrung und den Weg über begründete Quellenkorrektur
bzw. eine neue tatsächliche Zuordnung mit eigenem Stammdatensatz.

## Rechte, Sperren und Privacy

SQL-Leser ermitteln nur betroffene Immobilien-IDs, sperren sie geordnet und
prüfen danach die tatsächliche Elternbindung erneut. Frische Rolle/Scope
und vorhandene Request-Credential werden für gewöhnliche Aufrufer mit
Request-Scope vor Speicherung und Veröffentlichung geprüft. Direkte
interne Aufrufer ohne Benutzerkontext behalten ihre bestehende Semantik,
aber nicht das Recht, historische Bindungen zu beschädigen.

Memory verwendet Account- vor Domain-Sperre, damit Bestätigung und normale
Mutationen dieselbe Reihenfolge haben. SQL-Privacy nimmt die Messsperren
nach Account-/Operational-Sperren und vor Domain-Eltern, einschließlich
des Falls einer ersten gerade konkurrierend entstehenden Quelle.

Die bestehende `retained_measurement_subject`-Projektion wird in den
konsistenten Personenexport und dessen Planhash aufgenommen. Nur exakte
Belegungsfakten dieser Person und minimale Befehlsmetadaten erscheinen.
Der komplette gemeinsame `command.request` mit möglichen Nachmieterdaten
bleibt ausgeschlossen. Anonymisierung nennt erhaltene Originale und prüft
Vollständigkeit/Freshness bis Commit; die Memory-Snapshotnormalisierung
erkennt die neue ORM-Familie statt Objektidentitäten zu vergleichen.

## Commit- und Prüfplan

1. Dieses Addendum, ohne Produktcode.
2. Zentrale gewöhnliche Parentwriter mit eigenen Guardfunktionen; Memory,
   SQL-Update/Patch/Delete und reparierbare Konflikte.
3. Privacy-Projektion/Fence und konkrete native Regressionen.
4. Handoff mit ausgeführten Gates und übrig bleibenden Grenzen.

Gegenbelege auf Memory, echter Alembic-SQLite und PostgreSQL: normaler
PATCH/PUT und direkter Repository-Aufruf, Eltern-Neuzuordnung/Löschung,
erlaubte Stammdatenänderung/Zählerwiederverwendung, Bestätigung gegen
parallelen gewöhnlichen Writer, Rechteverlust, keine halbe Memory-Kaskade,
Personenexport mit alter/neuer Mietpartei im selben Befehl sowie erneute
Anonymisierungsvorschau nach Quellenänderung. Reine Restorefamilie,
Migrationsfolge, zentrale Modelregistrierung, Startup und Recoveryexport
gehören Root und werden nicht parallel verändert.

Das Widerspruchsjournal (Grund, Anlagen, konkrete Abrechnungsfassung) wird
danach als eigenständiges Paket geplant, nicht hier beiläufig implementiert.
