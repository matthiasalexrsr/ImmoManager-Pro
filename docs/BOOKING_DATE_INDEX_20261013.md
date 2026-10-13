# Datumsindex für Buchungen

Migration `7a2c8e4f1b90` folgt auf `3c7e9a1d5f20` und ergänzt den nicht eindeutigen B-Tree-Index `idx_bookings_date` auf `bookings(booking_date)`. Die ORM-Definition enthält denselben Index für neue Datenbanken. Bestehende Datenbanken erhalten ihn ausschließlich durch das ausdrückliche Upgrade (`python -m backend.upgrade` mit der vorhandenen Vollsicherung); der normale Start verweigert einen älteren Schemastand und ergänzt dabei keinen Index.

Ein nach `account_id` beginnender zusammengesetzter Index ersetzt diesen Zugriff nicht: der Cashflow kann ausschließlich einen Zeitraum filtern, ohne ein einzelnes Konto auszuwählen. Der neue Index erlaubt dann einen selektiven Datumsbereichszugriff. Abfragen über einen großen Anteil des Bestands können weiterhin sinnvollerweise einen Tabellenscan wählen. Der Index benötigt zusätzlichen Speicher und wird bei Buchungsänderungen mitgeführt.

Die kleine reproduzierbare Prüfung in `backend/tests/test_booking_date_index.py` verwendet 12.000 synthetische Buchungen auf 32 Konten, verteilt auf 1.200 Tage. Sie zeichnet die SQL-Abfrage der vorhandenen `booking_totals`-Berechnung mit Monatsgruppierung auf und erklärt genau diese Abfrage vor und nach dem Upgrade. Der gewählte Dreitagesbereich umfasst 30 Buchungen mit zusammen 307,50 €.

- SQLite: vorher `SCAN bookings`, anschließend `SEARCH bookings USING INDEX idx_bookings_date (booking_date>? AND booking_date<?)`.
- PostgreSQL 16.15: vorher `Seq Scan` auf `bookings`, anschließend `Bitmap Heap Scan` mit `Bitmap Index Scan` über `idx_bookings_date` für denselben selektiven Finanzbericht.
- Die fachlichen Summen bleiben vor Upgrade, nach Upgrade, nach Downgrade und erneutem Upgrade identisch; alle 12.000 Buchungen bleiben erhalten.
- Weitere Prüfungen belegen die Startverweigerung beim bisherigen Head sowie die Übernahme einer frischen ORM-Datenbank, deren Index bereits vorhanden ist.

Die Migration ändert keine Finanzklassifikation, Rundung, Zugriffsgrenze oder Cache-Regel. Downgrade entfernt nur den Index; Buchungsdaten bleiben bestehen. Die Planprüfung ist kein Großbenchmark und macht keine Aussage über die Laufzeit ganzer Installationen.
