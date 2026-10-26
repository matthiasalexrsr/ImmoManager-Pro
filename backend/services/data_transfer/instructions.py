CSV_INSTRUCTIONS = """# Datenübernahme – CSV-Version 1

Dateien unverändert benennen: properties.csv (Immobilien), units.csv (Einheiten),
parties.csv (Parteien), contracts.csv (Verträge), accounts.csv (Bankkontenzuordnungen),
receivables.csv (offene Forderungen). Nur benötigte Dateien auswählen.
UTF-8, vorzugsweise Semikolon; Komma/Tabulator werden erkannt. Die erste Zeile enthält
Spaltennamen. Abweichende Kopfzeilen lassen sich im Assistenten ausdrücklich zuordnen.
Keine Tausendertrennzeichen; Dezimalpunkt oder Dezimalkomma; Geldbeträge centgenau.
Datumswerte: JJJJ-MM-TT. Zeilen dürfen keine ausgeführten Tabellenformeln enthalten.

external_ref muss innerhalb einer Parteiart/Datensatzart und des Quellsystems stabil
und eindeutig bleiben. Das Quellsystem und der gewählte Zielbestand bilden den
Namensraum. IDs werden daraus reproduzierbar abgeleitet. Referenzen verwenden diese
externen Werte: property_ref → properties, unit_ref → units, tenant_ref → Mieter aus
parties, contract_ref → contracts, owner_ref → Eigentümerkontakt aus parties.
Vorhandene interne Datensätze können über „Bestehende Referenzen“ ausdrücklich
zugeordnet werden (z. B. properties:HAUS-1 → vorhandene Immobilien-ID). Sie werden
dabei unverändert verwendet; für einen zugeordneten Vertrag werden keine neuen
Mietperioden angelegt. Andere Datensätze mit gleichen IDs und abweichenden Angaben
sperren die Übernahme. Namensähnliche Datensätze werden als mögliche Dublette gezeigt.

property_type/unit_type: residential, commercial, mixed bzw. die vorhandenen
Fachtypen der Anwendung. party_kind: tenant (full_name erforderlich), owner,
supplier oder manager (Vorname/Nachname oder company_name erforderlich).
Vertragsstatus: active, terminated, expired, draft. account_type gemäß den
vorhandenen Kontoarten; die Vorschau zeigt ungültige Werte vor der Übernahme.

Laufende Verträge: ledger_start ist der Monatserste, ab dem das Mietkonto hier
geführt wird (nach Vertragsbeginn und vor Vertragsende); carried_balance ist der
Saldo zu diesem Tag, positiv = Forderung, negativ = Guthaben. Ohne ledger_start
berechnet die Anwendung die Miete ab Vertragsbeginn. cold_rent und Vorauszahlungen
beschreiben genau eine Mietperiode; historische Änderungen benötigen den bestehenden
ImmoManager-Snapshot mit contract_rent_periods. carried_balance und offene Posten
dürfen dieselbe Forderung nicht doppelt enthalten. Die Mengen-/Betragskontrolle und
die Bestätigung sind verpflichtend. Die receivables-Vorlage übernimmt positive
Restforderungen; Zahlungsverläufe und Gutschriften übernimmt das Snapshotformat.
Ein Nullsaldo ist ausdrücklich mit 0 anzugeben. Bankkonten importieren den
opening_balance und setzen balance auf diesen Anfangsstand; Buchungen nicht erneut
in den Anfangssaldo einrechnen. Bankdatenimporte erteilen keine Zahlungsfreigabe.

Die Vorschau speichert nur Quelldateien und Prüfprotokoll. Geschäftsdaten werden
erst nach Ihrer Bestätigung gemeinsam übernommen. Ändert sich der Zielbestand,
muss die Vorschau erneuert werden. Bei Fehlern erfolgt keine Teilübernahme.
Wiederholte Übernahme desselben Auftrags ist idempotent. Wiederholte Quelldateien
mit demselben Quellsystem verwenden dieselben IDs; identische Daten werden übersprungen.

Ältere ImmoManager-JSON-Snapshots bleiben importierbar. Vollsicherungen mit
Betriebsdaten, Konten oder Schlüsseln ausschließlich über „Wiederherstellung“ laden.
Vor jeder echten Migration ein geprüftes Vollbackup erstellen und für den Rückfall
aufbewahren. Der Assistent ersetzt oder löscht keine bestehenden Geschäftsdaten.
"""
