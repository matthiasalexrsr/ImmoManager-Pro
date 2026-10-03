# Kontakte: begrenzte Quellen bei vollständigem Bestand

Nächster einzelner Fachadapter nach `eb7df7e`, eigener Branch
`assist/bounded-legacy-lists`. Ownership: bestehender Contacts-Arrayrouter,
additive contact_inventory-/contact_list-Module und eigene Kontaktoberfläche.
Keine Tenant-Privacy-/Lifecycle-/shared workflow_references-Änderung, keine
Migration, keine neue Kontaktidentität und keine automatische Zusammenführung
von Contact und Tenant. Das Contact-Modell hat keine direkte Tenant-Verknüpfung.

1. Bestehende `/contacts`-Parameter und Arrayantwort behalten, globale
   `list_contacts()`-Materialisierung durch scoped SQL vor OFFSET/LIMIT ersetzen.
   Altsortierfelder bleiben zulässig; stabile NULL-/ID-Reihenfolge. Memory mit
   begrenztem Heap, kein Vollabruf. Exakte Detail-/CRUD-Routen weiterverwenden.
2. Additive `/contacts/inventory/page|summary|export`: Rolle, Suche und
   Prüfansichten ohne E-Mail/Telefon/Name. Anzeigename aus Firma bzw. Vor- und
   Nachname; Leerzeichen gelten nicht als vorhandene Kontaktdaten. Suche über
   Name/Firma/E-Mail/Telefon/Mobil/Ort/PLZ/Land. Cursorquery/scopesigned;
   Byte-/NULL-/ID-Sortierung auf Memory/SQLite/PG gleich.
3. Kleine Listen-/CSV-Projektion für normale Kontaktdaten. IBAN/BIC/Steuer-ID/
   Notizen werden nicht ungefragt in jede Listenzeile geladen. Vor Bearbeiten
   vollständiges exaktes Detail samt Originalrevision; alle bestehenden Felder
   inklusive bisher im Formular fehlendem Land/BIC erhalten. Kompletter
   gefilterter CSV-Bestand über gemeinsamen geprüften Snapshotexporter.
4. SQL-Aggregate unabhängig von Seiten: Gesamt/Rollen/fehlende E-Mail/Telefon.
   Kontakte benötigen vorhandene explizite Portfolio-Grants; historische
   ungebundene Kontakte werden beschränkten Nutzern nicht neu offengelegt.
   Scope-/Tokenwechsel zwischen Read und Ausgabe bzw. Export unterbinden.
5. Oberfläche nutzt den nachgewiesenen Inventoryhook und lokale Styles,
   Filter-/Fehler-/Leerzustände getrennt, Formen behalten Eingaben nach Fehler,
   Rolle readonly ohne Schreibaktionen. Bestehende vertrauliche Formulardaten
   werden bei Actor-/Scopewechsel synchron entfernt. Keine globalen Referenzen.
6. Abnahme: Treffer 101/1001/10001, vollständiges CSV/Aggregate, explizite Grants,
   kein Autoflush, exakter Detailabruf mit Revisionsschutz, fehlgeschlagener
   Retry, alte Antworten verwerfen, echte PG- und 320/360/1440-Browserprüfung.

Mieter folgt als eigenes Paket; der Domain-Agent behält Datenschutz-/
Lebenszyklus-Guards. Diese Lieferung führt keine Mieterarchivierung, Löschung
oder sonstige Profile zusammen und ändert keine finanziellen Ableitungen.
