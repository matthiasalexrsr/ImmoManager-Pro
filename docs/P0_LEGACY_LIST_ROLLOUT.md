# Vollständige Listen und serverseitige Projektionen

Plan nach dem begrenzten Einheitenworkspace, Basis `679c8de`; noch keine
Umstellung fremder Seiten in diesem Paket. Erneut gegen den integrierten Root
abgleichen, bevor ein Folgepaket beginnt.

## Konkrete erste Lieferstrecken

| Reihenfolge | Seite und heutiger Befund | Serverprojektion und Abnahme |
| --- | --- | --- |
| 1 | `Units.jsx:29`: erstes 100er-Fenster, Fehler als `[]`; ab Zeile 81 Filter/Kennzahlen lokal, Referenzen aus globalem Cache. | Einheitenworkspace-Liste mit Immobilie, eindeutigen/mehreren aktiven Parteien, echten Statusfiltern, fehlenden Angaben und vollständigen Aggregaten. Gespeicherten Einheitenstatus von Vertragsbelegung trennen. Einheit 101+ durch Suchbegriff, Filter, Referenzwahl und Detailnavigation erreichbar. |
| 2 | `Documents.jsx:77`: erster Ausschnitt plus lokale Zuordnungs-/OCR-Filter und Kennzahlen. | Dokumentprojektion mit berechtigten Zuordnungsnamen, OCR- und Zuordnungsfiltern vor LIMIT. Original-/Versions-/Downloadrechte aus bestehendem Dokumentkern weiterverwenden. Neuester Upload erscheint nach Mutation in der passenden Filtermenge; fehlgeschlagener Reload zeigt keinen leeren Bestand. |
| 3 | `Maintenance.jsx:41`: erster Ausschnitt, Dringlichkeit/Fristen/Kennzahlen lokal. `routers/maintenance.py:28` liest bei Datumsfilter maximal 10.000 und filtert danach. | Datum, Dringlichkeit, Zuständigkeit und offene Vorgänge in SQL filtern, Termine/Zeitzone explizit. Fall 10.001 im Datumsfenster nachweisbar; Fristenzahlen unabhängig von geladener Seite. Bestehende Schäden/Projektplanung bei der Migration nicht durch bloßes CRUD ersetzen. |
| 4 | `Contacts.jsx:56`: erster Ausschnitt, Typfilter und Zähler lokal; Router liest Gesamtmenge vor Slice. `Tenants.jsx:32` lädt bereits alle statt nur 100, skaliert jedoch mit Gesamtbestand. | Kontakte und Mietparteien erhalten getrennte Fachprojektionen. Tenant-Vertragsbezug darf keine beliebige erste Partei sein. Tenant-/Kontakt-Sichtbarkeit über bestehenden Scopekern; unzugeordnete Kontakte nicht pauschal freigeben. Suche, Archivstatus, SEPA-/E-Mail-Lücken und Typzahlen global korrekt. |
| 5 | `Insurances.jsx:7`, `Accounts.jsx`, `Meters.jsx` und übrige `FinanceCrudPage`-Nutzer verwenden Sammellader/Referenzlisten; konkrete Hookaufrufe pro Seite vor Migration inventarisieren. | Pro Fachgebiet nur benötigte Namens-/Statusprojektion und bounded Referenzpicker. Bei Konten ausschließlich bestehenden Saldo-/Buchungsnachweis wiederverwenden, keine zweite Finanzwahrheit. Messwerte separat paginieren. Fachseiten einzeln abnehmen. |

Kein gemeinsames `getAll` als vermeintliche Lösung: Das beseitigt Abschneiden,
verlagert Speicher, Netzlast, Suchkosten und Berechtigungszustand aber in den
Browser. `DataStoreContext.jsx:98` und `useFinanceData.js:26` sind deshalb
gezielte Folgebaustellen, kein Anlass für einen ungetesteten Austausch aller
Verbraucher. Bestehende begrenzte Vertrags-, Bank- und Workflow-Reader bleiben
maßgeblich und werden nicht neu implementiert.

## Gemeinsamer Vertrag, kleine Fachadapter

1. **Query:** je Ressource validiertes Modell mit erlaubten Such-/Sortierfeldern,
   fachlichen Filtern, `page_size`, signiertem Cursor. Keine beliebigen SQL-
   Feldnamen. Sortierung immer mit stabiler ID und expliziter NULL-Reihenfolge.
   Cursor bindet Ressource, normalisierte Query, Benutzer/Scope und Version.
   Seitenbudget begrenzt eine Übertragung, nie die erreichbare Gesamtmenge.
2. **Leseseite:** `{items, has_more, next_cursor}` und kleine erforderliche
   Bezeichnungen direkt aus scoped SQL-Joins. Filter und Rechte vor LIMIT;
   keine ORM-Autoflush-Nebenwirkungen. Memory verwendet begrenzte Auswahl.
   Dieselben frischen Auth-/Scopeprüfungen vor Veröffentlichung wie im
   Einheiten-/Vertragsworkspace; no-store für private Ergebnisse.
3. **Kennzahlen:** eigener fachlich benannter Aggregate-Reader über dieselbe
   Filterbasis, ohne Pagination. SQL COUNT/SUM/CASE statt Browserzählung.
   Finanzbeträge verwenden vorhandene Cent-/Ledger-Modelle. Antworten tragen
   Queryidentität und Erhebungszeit; eine live gelesene Seite wird nicht als
   unveränderlicher Gesamtsnapshot dargestellt. Teure Aggregate separat laden
   und bei Fehlern ausdrücklich als nicht verfügbar anzeigen, nie als Null.
4. **React:** `usePagedWorkspace({resource, principalKey, query})` mit
   AbortController, Requestgeneration, synchroner Verwerfung alter privater
   Resultate und servergebundenem Cursorpfad. Filter-/Benutzer-/Scopewechsel
   setzt Seiten zurück. Mutation invalidiert betroffene Listen/Aggregate und
   genaue Referenzen. Kein Cache allein nach `entityKey`; keine späte Antwort
   darf Daten eines vorherigen Nutzers wieder einsetzen.
5. **Tabelle:** bestehende Spalten-/Zellen-/Aktionsdarstellung weiterverwenden,
   aber expliziten Servermodus ergänzen. Dieser sortiert/filtert/paginiert
   nicht nochmals das gelieferte Teilfenster. Suche mit kurzer Verzögerung,
   tastaturbedienbare Seitennavigation, unterscheidbare Lade-/Leer-/Fehler-
   zustände, Retry und Neustart bei ungültigem Cursor. Fokus beim Seitenwechsel
   sinnvoll zum Ergebnisbereich führen. Kleine wirklich vollständige lokale
   Tabellen können den bisherigen lokalen Modus behalten.
6. **Referenzen:** Suchpicker aus vorhandenen Vertrags-/Workflow-Referenzen
   adaptieren; ausgewählten Datensatz gezielt nachladen. Einträge auf Position
   101+ in Formularen auswählbar, bestehende unbekannte ID nicht still löschen.
7. **Exporte:** sichtbare Seite als solche kennzeichnen; vollständiger Export
   gehört auf den Server mit derselben Query und Rechtebindung. Große Exporte
   dauerhaft als wiederaufnehmbaren Auftrag und archivierte Ausgabe behandeln,
   Fortschritt/Abbruch/Fehler sichtbar. Finanzexporte verwenden ihre vorhandenen
   geprüften Snapshots. CSV-Escaping allein verhindert keine Tabellenformeln:
   führende Formelzeichen pro Zelle sicher behandeln und gezielt testen.

Gemeinsame Helfer erst nach zwei nachgewiesenen Fachadaptern extrahieren, etwa
Einheiten und Dokumente. Kein generischer Leser mit Ressourcennamen aus freier
Benutzereingabe und kein Austausch aller Seiten in einem Commit.

## Abnahmen je Lieferung

- Treffer jenseits Position 100 sowie Datumsfall jenseits 10.000; alle
  Cursorseiten bei unverändertem Bestand vollständig und ohne Duplikate.
- SQLite und tatsächliches PostgreSQL: gleiche Reihenfolge bei gleichen
  Sortierwerten/NULLs, passende Indizes und nachvollziehbarer Abfrageplan;
  Listenqueries ohne globale Materialisierung. Lastprofil mit mindestens
  100.000 synthetischen Fachzeilen in einem gesonderten Performance-Gate.
- Vollständige Kennzahlen über den gleichen berechtigten Suchraum, unabhängig
  von Seitengröße und aktiver Cursorposition; keine gerundeten Float-Summen
  für finanzielle Nachweise.
- Benutzer-/Portfolio-/Filterwechsel und verspätete Antworten; Rechteentzug
  während Abfrage, Export oder Download; keine Namen/Daten aus altem Scope.
- Einfügungen/Löschungen während Navigation sind ehrliche Live-Seiten mit
  sicherem Neustart; keine Behauptung eines eingefrorenen Exports.
- Browser: Suchen, Blättern, Editieren mit bestehendem Revisionsschutz,
  Fehler/Retry, Tastatur, 390-Pixel-Layout und vollständiger Exportnachweis.
- Erst nach bestandener Einzelstrecke Root integrieren; danach nächste
  Fachseite. Housing, Billing und Kommunikationspakete getrennt integrieren.
