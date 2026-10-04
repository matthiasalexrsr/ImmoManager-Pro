# Vorcodepräzisierung: Immobilien-Inventar und exakte SQLite-Centsumme

Basis8d2589d, eigene Branch assist/property-inventory-backend; d3bb219 bleibt
auf der alten Branch. Ergänzt den vollständig gelesenen Rootvertrag
PROPERTY_INVENTORY_IMPLEMENTATION_CONTRACT_20261004.md. Noch keine Imports,
Tests, DB-/App-/Serverstarts oder Änderung gemeinsamer Quellen.

## Money- und Installervertrag

Eigene Datei backend/services/property_inventory_money.py liefert reine
Centprüfung/kanonische Ausgabe und kleine eigene SQL-Ausdrücke. Ein gültiger
Quellbetrag wird **vor** Aggregation in Integercents umgewandelt: nichtnegativ,
endlich, höchstens zwei Dezimalstellen und im bestehenden Einzelspaltenbereich
Numeric(12,2). Fehlende und ungültige Quellen bleiben getrennte Zähler. Die
Gesamtsumme selbst hat **keine** neue Betrags-/Bestandsgrenze.

SQLite bekommt ausschließlich auf der tatsächlich benutzten SQLAlchemy-
Connection deren sqlite3.DriverConnection eine eigene create_aggregate-
Registrierung immo_property_exact_cent_sum/1. Kein Engineglobal-Event, keine
Fabrik, kein Verbindungswechsel, keine DDL/DML. Eingabe ist Integercent oder
null; jeder andere Typ wird abgewiesen. Pythonint akkumuliert ohne Int64-
Sumgrenze. finalize gibt kanonischen nichtnegativen Centtext zurück. Ein SQL-
COALESCE behandelt echte leere Gruppen als "0". Ein fehlerhafter Callback
führt zu Quellenfehler, nie Floatfallback. Einzelcentwerte passen aufgrund
des bestehenden Numeric(12,2)-Bereichs in SQLite-Integer; Gesamtsummen nicht
in diesen Typ zurückcasten. PG nutzt SUM(bigint), dessen native Numeric-
Gesamtsumme erst verlustfrei als Text ausgegeben wird.

Neue snapshotgebundene ReadSession: bind ist die gerade aus dem tatsächlichen
Storeengine gewonnene Connection, connection.engine ist genau dieser Engine.
Installer erhält diese Session; deren tatsächliche Connection wird geprüft,
nicht eine globale/ersatzweise Session. Searchcasefold wird ebenfalls auf
dieser Verbindung installiert. Frische zweite PublicationSession bekommt
ihre eigene Registrierung. Es werden keine Caller-DMLs flush/commit ausgeführt.

SQLrentkey: Currency bytewiseASC/nullLast, Centbetrag desiredDir/nullLast,
PropertyID bytewise desiredDir. SQLitebetrag vergleicht length(canonicalText)
und bytewiseText, PG tatsächliche Numericcentwerte. Canonicaltext enthält
keine Vorzeichen, Exponenten oder führenden Nullen außer "0". Cursorposition
ist [Currency|null, Centtext|null, tatsächliche PropertyID]. Centtext wird nie
in float oder Int64-Gesamtsumme umgewandelt. Publicbetrag formatiert rein aus
Centtext in Decimalstring mit exakt zwei Nachkommastellen.

## Additiver Exportadapter für Root

Root besitzt backend/services/inventory_export.py. Neue optionale inventory-
Hooks; fehlt ein Hook, bleibt das bisherige Verhalten bestehender Inventare:

1. prepare_read(session, query): auf der tatsächlichen SnapshotSession und auf
   jeder tatsächlichen frischen LiveSession **vor** statement-Ausführung. Auch
   ohne search ausführen; sonst fehlt die SQLiteaggregation. Der Hook richtet
   ausschließlich eigene reine verbindungsgebundene Funktionen ein. Existing
   ensure_sqlite_casefold darf bei alten Inventaren weiter gelten.
2. page_position(query, row): tatsächlicher Key der letzten Quellrow. Beide
   SQL- und Memoryzweige ersetzen damit optional die bisher feste Zweierform.
   Keine Publicformatierung als Sortwert. Neue Moneyposition hat drei Werte;
   name/city bleibt [Sortwert|null, ID].
3. export_row(row): vor encode_rows auf jede begrenzte Quellrow anwenden;
   unverändert rawrow als Fallback. Neues Inventar gibt dieselbe geprüfte Public-
   DTOprojektion wie JSON aus, insbesondere Decimalbetrag statt interner Cents.
   Aktuelle Vergleichsprüfung nutzt weiterhin inventory.item(...).model_dump.

Eigene property_inventory_export.py delegiert genau diesen Kern, ohne zweite
Queue oder eigenen parallelen Exportkern. Root registriert/includiert die
Route erst nach Adapterkomposition und echten Gates. Optionaler Adapter ist
kein Authoritybeleg und ändert keine vorhandene Auth-/Scopeprüfung.

## Sourceaufteilung und offene echte Abnahme

Neue eigene property_inventory_types.py, property_inventory_money.py,
property_inventory.py, property_inventory_export.py und
routers/property_inventory.py sowie eigene SourceTests. Root besitzt
properties.py-Inklusion, Sharedkernel und Registry/Schema/Auth. Summary
berechnet nur vollständige scope-/matching Counts, kein Währungsgeldtotal.
SQLaggregation der Kindfamilien erfolgt getrennt vor Filter/Sort/Keyset.
Page und Summary haben zwei geschlossene echte Snapshotprojektionen plus
fresh Scopeprüfungen; die spätere HTTProute ergänzt CheckedPublication.

Schwere/native Gates bleiben offen und Rootkoordiniert. Insbesondere echte
SQLiteaggregate über Int64-Summen, PGNumericparität, tatsächliche separate
Parentwriter/Readsnapshots, scoped10002-Walks und Rootexportadapter müssen
belegt werden. Vorcode-/Sourcecommits ersetzen keinen solchen Nachweis.
