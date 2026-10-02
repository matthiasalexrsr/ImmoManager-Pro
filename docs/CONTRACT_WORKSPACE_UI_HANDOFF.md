# Vertragsworkspace: Frontend

Basis: Root-Lifecycle-UI acaee75918983dca721a0fab445d4f34120e081e.
Unveränderter Backendvoraussetzungscommit d70bb8dca5748c3d0ab458d4e80783fecfb60216
ist hier als 89fd110 übernommen. Bei Root nur den separaten Frontendcommit
integrieren; Backend, Router und Einstellungen besitzt Root.

## Verhalten

- Die Tabelle fragt ausschließlich GET /contracts/workspace/page ab. Suche,
  Status, Start-ab/Ende-bis, genaue Property/Unit/Tenant-Bezüge, Ansichten und
  Sortierung gelten vor serverseitiger Seitenauswahl.
- Vorgänger/Nachfolger verwenden ausschließlich opake Servercursor. Filter-
  und Sortwechsel beginnen bewusst auf der ersten Seite. Es gibt keine
  Bestandsgrenze und kein automatisches Zusammenladen aller Seiten.
  NULL-Enden bei Ende-bis und Unicode-Suche folgen dem Backendvertrag.
- Anzeigenamen und aktueller Unit-Kaltmietwert kommen aus der autorisierten
  gemeinsamen DTO-Abfrage. Ein sichtbarer Hinweis unterscheidet aktuelle
  Einheitsdaten von wirksamen Mietanpassungen und historischen Sollstellungen.
  Restlaufzeiten beruhen auf reference_date der Cursoraufnahme. Zusammenfassungen
  zählen ausdrücklich nur die geladene Seite.
- Cursorfehler verlangen bewussten Neustart mit denselben Filtern, Sortierung
  und Seitengröße. Ein kleineres konfiguriertes Seitenbudget bietet einen
  ausdrücklichen Neustart mit einer Zeile; jedes gültige positive Serverbudget
  lässt das zu. Weitere Seiten bleiben frei erreichbar.
- Der CSV-Knopf exportiert nur die sichtbare Seite, ohne neue Abfrage.
  Namen, Überschriften, Quotes, Semikolons und CR/LF sind escaped;
  potenzielle Formeln in Textzellen bleiben Text. Zahlen bleiben Zahlen.
  Knopf und Dateiname behaupten keinen vollständigen Bestandsexport.

## Bearbeitung und Rechte

Der Editor nutzt die vorhandenen begrenzten
/contract-wizard/choices/{properties|units|tenants}-Abfragen mit Suche,
25er-Seiten und exakter selected_id. Units bleiben an die gewählte Property
gebunden; ein Propertywechsel leert die Unit-Auswahl.
Bestehende archivierte Tenants werden ausschließlich über einen geschützten
Einzelabruf für den bereits gebundenen Vertrag erhalten, nicht als allgemeine
neue Mieterauswahl. Für das Grid gibt es kein Property-/Unit-/Tenant-getAll
und keine First-100-Namensauflösung.

Die originale starke edit_etag wird unverändert an den Datensatzsnapshot
gebunden, einschließlich sechs Mikrosekunden und serverseitiger RFC3986-ID-
Kodierung. Normale Formular-/Listenaktualisierungen ändern ihn nicht.
Nur bewusster Konfliktabgleich im vorhandenen FormModal ersetzt dessen
Payloadrevision. PUT überstimmt sie anschließend nicht durch die ältere
Tabellenrevision; DELETE verwendet den konkreten ursprünglichen Zeilensnapshot.

Actor-/Rollen-/Portfolio-/Schreibberechtigungswechsel remounten den Workspace,
beenden Requests und verwerfen private Dialoge. Späte Antworten dürfen keine
alten Subjects anzeigen. Frische 401/403 schließen offene private Dialoge.
Readonly behält Suche, Paging, seitengebundenen Export und Ablaufhistorie
ohne CRUD-Schreibaktionen. Wartende Löschbestätigung lebt nach Entzug und
erneuter Freigabe nicht wieder auf.

Lifecycle und Editor liegen außerhalb aller Loading-/Fehler-/Empty-Zweige.
Listenrefresh verliert weder die private Ablaufakte noch Prüfung/exakte Retry.
G06-Backend und Finanz-/Occupancy-/Journalguards bleiben unverändert.
Lookup-Enter löst keinen impliziten Save/Filter aus. Tastaturfokus nach Sortieren
und Paging bleibt erreichbar; Fokusfalle/busy Submit kommen vom FormModal.
DE/EN/ES sind additiv; fehlende contracts.form.*-Labels sind entfernt.

## Tatsächliche Prüfung

Im eigenen Checkout mit Vitest --maxWorkers=2, globalem ESLint --max-warnings=0,
Vite build und diff --check. Final: 898/898 Tests in 70 Dateien grün, darunter
36 Workspace-/Lifecycle-Rowhook-Fälle; globaler Lint ohne Warnungen, Build und
Whitespaceprüfung grün. Der identische Unicode-/MV-137-Suchfall wurde im
getrennten Baseline-Checkout gegen die alte First-100-Oberfläche tatsächlich
rot ausgeführt: MV-137 trotz Suche unerreichbar, anschließend im neuen Workspace
grün. Auch der 412-Abgleichsfall wurde vor Korrektur tatsächlich rot: zweiter
PUT alter ETag; danach neuer bewusst geprüfter ETag mit lokalem Feldwert.

Funktionale Fälle: Suche jenseits 100, 125 Einträge über fünf explizite Seiten,
Filter/Sortierung, NULL/0, Cursorneustart, kleines Serverbudget, fehlerhafte DTOs,
RFC3986-ID/ETags, späte Antworten, Rechteentzug, Parent-Read-Fehler, ausgewählte
Referenzen jenseits 100, Property/Unit-Änderung, Lookup-Paging/Enter, archivierte
Tenant-Einzelbindung, Formular-/Konfliktfehler, CSV und alle drei Sprachen.

Unveränderter Backendstand hier erneut mit eigenen synthetischen Memory/SQLite-
Fixtures geprüft: 77 bestanden / 8 explizite Skips; sieben ohne dedizierte PG-
Test-URL und eine nicht passende Memory-Variante. Keine lokale PG-Ausführung
behauptet. Gemeinsame SQLite/Edge-, 320/360px- und PG-Abnahme liegt bei Root.
Hier wurde gemäß Koordination keine parallele Browserinstanz gestartet.
