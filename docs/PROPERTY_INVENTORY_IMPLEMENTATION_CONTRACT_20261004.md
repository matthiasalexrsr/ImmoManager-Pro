# Gemeinsamer Implementierungsvertrag: Immobilienübersicht

Rootentscheidung nach tatsächlicher Backendanalyse d3bb219 und Übergabe des
bisherigen Frontend-Assistenten54815a5. Umsetzung innerhalb des autorisierten
Plans Paket B; keine Benutzerentscheidung mehr erforderlich. Referenzbasis ist
der Rootcommit dieses Dokuments. Beide Arbeiten wechseln ausschließlich aus
sauberem eigenem Checkout auf eigene neue Branches dieser Basis. Frühere
Übergaben bleiben in ihren ursprünglichen Branches erhalten.

## Leseschnittstellen und Felder

Additive GET /api/v1/properties/inventory/page und /summary; später /export.
Query exakt Backendvorschlag: search, portfolio_id, status, property_type,
view=all|manual_vacancy|open_maintenance|no_current_contract|multiple_current_contracts,
as_of als verpflichtendes Datum, sort_by=name|city|unit_cold_rent_sum,
sort_order=asc|desc, page_size=25 im bestehenden Einzelbudget, cursor.
Alle weiteren Felder sind verboten. Page enthält items/has_more/next_cursor/as_of.
Summary enthält as_of/scope_totals/matching_totals. Cursor nicht für Summary
oder Export verwenden. Neue Seite ersetzt alte Seite; kein wachsender Stockcache.

Item erweitert vollständiges bestehendes Property plus echtes edit_etag:
portfolio_name/address, rent_currency/unit_cold_rent_sum,
rent_known_unit_count/rent_missing_unit_count/rent_invalid_unit_count,
unit_count/occupied_unit_count/no_current_contract_unit_count/
multiple_current_contract_unit_count,
manual_occupied_unit_count/manual_vacant_unit_count/manual_reserved_unit_count,
open_maintenance_count/unknown_maintenance_status_count.
Totals enthalten property_count und dieselben fachlichen Countfelder.
Keine Gesamtgeldsumme über verschiedene Währungen und keine unbounded Liste
aller Währungen. Propertyrevision bleibt unabhängig von Kindaggregaten.

as_of wird im UI einmal als aktueller lokaler Kalendertag initialisiert,
sichtbar angezeigt und ist als Betrachtungstag wählbar. Active/terminated
Verträge belegen inklusiv Start-/Endtag, gültige actual Unit-/Property-/Tenant-
und Scopebeziehung vorausgesetzt. Keine Tenantpersonendaten in dieser Übersicht.
Mehrere gültige aktuelle Verträge zählen die Einheit genau einmal und erzeugen
den gesonderten Prüfhinweis. Keine Umdeutung des manuellen vacant-Filters:
UI nennt ihn ausdrücklich „Leerstand erfasst“; „Ohne aktuellen Vertrag“ ist
eine getrennte Ansicht. Reserved ohne Vertrag wird nicht als freigegeben erklärt.

## Geld und Sortierung

unit_cold_rent_sum ist die vollständige monatliche Summe aktueller gültiger
Unit-Stammmietwerte, einschließlich unvermieteter Units. Label „Stammmieten“
mit Hinweis; keine Ertrags-, Forderungs- oder Vertragsmietbehauptung.
Centprüfung, Integercents vor der Aggregation und kanonischer Decimalstring.
SQLite nutzt eine eigene verbindungsgebundene exakte Centaggregation mit
Pythonint-Akkumulator und Centstring-Ausgabe, um keine Int64-Gesamtbetragsgrenze
einzuführen. Keine DDL/DML und kein Summieren ungeprüfter Floatquellen.
SQLite-Betragssort verwendet Länge und bytewise kanonischen positiven Centtext;
PG verwendet seine native SUM(bigint)-Numericquelle. Installer-/Sortiervertrag
wird vor Code als eigener Plan konkretisiert. Unvollständige/ungültige Quellen
ergeben null, keine0Summe.
Gültiger leerer Unitbestand mit belegter Währung ergibt0.00.

rent_currency übernimmt die tatsächlich deklarierte nichtblanke Portfolio-
Währungsangabe als Gruppenlabel; fehlende/blanke Quelle ist null. Kein stiller
EURersatz, keine künstliche Beschränkung aller Altwerte auf eine neue Währungsliste.
Bei Stammmietsortierung werden verschiedene Währungslabels ausdrücklich
gruppiert: Currency bytewiseASC/null-last, Betrag Integercents in gewünschter
Richtung/null-last, Property-ID bytewise in derselben Betrag-Richtung.
Cursor trägt Währungslabel, exakten Centstring bzw. null und tatsächlicheID.
UIlabel „Stammmieten nach Währung“, keine Aussage über Wechselkurse oder
vergleichbare Beträge unterschiedlicher Währungen. Andere Sorts behalten
Sortwert/null-last plus bytewiseID. Exporte nutzen exakt dieselben Schlüssel.
Die Darstellung verwendet die Decimalstringquelle; keine JS-Zahlensummen.
Unbekannte Währungslabels bleiben anzeigbar statt einen Formatierungsfehler
auszulösen. Invalid-/Overflowquellen liefern bearbeitbare Hinweise/Fehler,
keine Datenänderung oder stillen Floatfallback.

## Oberfläche und Integration

Gemeinsame serverseitige Seite für Karten/Tabelle, keine browserseitige
Nachsortierung/-suche. Vier Hauptkennzahlen aus scope_totals, explizit
„Berechtigter Bestand“; Trefferanzeige aus matching_totals. Kennzahlfehler ist
kein Nullbestand. Portfoliofilter und Formauswahl verwenden bestehenden
bounded ReferenceChoice. Keine eager Units/Maintenance/Portfolio-Stockloads.
Vor Edit aktuellen vollständigen CRUDdatensatz und echte Revision laden;
Kaufpreis0 und bestehende Nullable-/Readonly-/Formdraftsemantik erhalten.
Keine Shared-DataTable/FormModal/UnitInventory/PropertyDetail-Neuentwicklung.

Actor-/Grantwechsel neutralisiert alle Page-/Summary-/Auswahldaten im ersten
Render und bricht alte Requests ab.409 → explizit erste Seite neu laden;
401/403 → neutraler Zugriffszustand;422 → bearbeitbarer Filter-/Cursorfehler.
Ladefehler/Leerbestand/keineTreffer sind verschieden. Pager mit Vor/Zurück,
Filteränderung setzt Cursor zurück. Detailroute /properties/{id} bleibt erhalten.
320/360/1440 und Tastaturbedienung nach Frontendplan54815a5.

Backend gruppiert Units/Contracts/Maintenance getrennt vor dem Seitenlimit,
actual Parents/Scope vor jeder Kennzahl. Zwei echte frische Projektionen für
Page/Summary nach dem geschlossenen ersten Snapshot; Änderungen409. Vorhandene
CheckedPublication ergänzt Account/Sidprüfung. Kein DDL-/Write-/Schemaeffekt.
Memoryreferenz gruppiert einmal unter bestehendem Lock; SQLmaterialisierung
bleibt seitenbegrenzt. Root montiert die additive Route zentral nach Prüfung.

Zuerst konkrete reine Source-/Testpakete, danach zentrale tatsächliche SQLite-,
PostgreSQL-, HTTP-/Export- und Browserabnahme. Native Starts bleiben Rootowned;
Agenten führen bis zum zugeteilten Slot keine Imports/Tests/Build/Server aus.
