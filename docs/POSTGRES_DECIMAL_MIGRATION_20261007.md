# Dezimale PostgreSQL-Beträge – Migration vom 7. Oktober 2026

Die Migration `d7a2f9c4e681` folgt auf `8c4d2e6f1a93` und korrigiert die
historischen PostgreSQL-Betragsspalten. Die ursprünglichen Migrationen legten
39 heute als `Numeric` deklarierte Felder als Gleitkommazahlen an. Damit ergab
`SUM(bookings.amount)` für 100 gespeicherte Zahlungen zu 11,11 EUR den Wert
`1111.0000000000002`. Nach der Migration ist die Datenbanksumme exakt `1111.00`.

## Umfang der geprüften Spalten

Der Umfang ist in der Migration festgeschrieben. Die Migration importiert kein
ORM-Modell und erweitert ihren Wirkungsbereich daher nicht durch spätere
Modelländerungen.

| Tabelle | Historisch gleitkommagenaue Felder, jetzt dezimal |
| --- | --- |
| `accounts` | `opening_balance`, `balance` |
| `bookings` | `amount` |
| `budgets` | `planned_amount`, `actual_amount` |
| `contracts` | `deposit_amount` |
| `cost_items` | `amount` |
| `deposits` | `amount`, `deductions` |
| `insurances` | `coverage_amount`, `premium_amount` |
| `invoices` | `net_amount`, `vat_amount`, `gross_amount`, `vat_rate` |
| `listings` | `target_rent`, `service_charge` |
| `maintenance_cases` | `estimated_cost` |
| `properties` | `purchase_price`, `market_value` |
| `receivables` | `amount_due` |
| `rent_adjustments` | `previous_rent`, `new_rent`, `increase_percent`, `index_value` |
| `rent_charges` | `cold_rent`, `service_charge`, `heating_charge`, `other_charges`, `amount_paid` |
| `tax_rates` | `rate` |
| `units` | `cold_rent`, `service_charge_advance`, `heating_advance` |
| `utility_statements` | `total_cost`, `advance_paid`, `balance` |

Sieben weitere deklarierte Dezimalfelder waren bereits korrekt angelegt:
`cost_items.vat_rate/net_amount/gross_amount`,
`contract_rent_periods.cold_rent/service_charge_advance/heating_advance` und
`payment_allocations.amount`. Mengen, Flächen und Zählerstände bleiben außerhalb
dieser Korrektur. Der Regressionstest prüft sämtliche 46 aktuellen
`Numeric`-Deklarationen gegen den tatsächlich migrierten PostgreSQL-Katalog.

## Datenerhalt und Rückwärtskompatibilität

Nur tatsächlich als Gleitkommazahl gespeicherte Felder werden auf `NUMERIC` ohne
Präzisions- oder Skalenbegrenzung umgestellt. Ein pauschales `NUMERIC(12, 2)`
würde vorher zulässige Werte mit mehr als zwei Nachkommastellen runden und große
Altbeträge zurückweisen. Bereits vorhandene Dezimalspalten behalten ihren Typ,
ihre Skala und ihre Daten, auch bei Übernahme einer Datenbank aus `create_all()`.

Die Umwandlung nutzt `spalte::text::numeric` mit transaktionslokalem
`extra_float_digits = 3`. Eine direkte Umwandlung von Float nach Numeric kann
signifikante Ziffern verlieren. Die Textdarstellung bewahrt den vorhandenen
Float als rückkonvertierbaren Dezimalwert. Sie rekonstruiert keine früheren
Eingabeziffern, die schon bei der ursprünglichen Speicherung als Float verloren
gingen. Geprüft wurden unter anderem 17 signifikante Ziffern, mehr als zwei
Nachkommastellen, große Beträge, sehr kleine Werte und die endlichen Grenzwerte
von Double Precision. Die binäre Darstellung aller Testwerte war vor der
Migration und nach Rückkonvertierung identisch.

PostgreSQL führt diese Änderung in der Alembic-Transaktion aus. Pro Tabelle
werden die betroffenen Spalten zusammen geändert; bei größeren Beständen ist
mit Tabellenumschreibung und exklusiven Tabellensperren während der Migration
zu rechnen. Der Test mit kleinen synthetischen Daten liefert keine Laufzeit-
oder Verfügbarkeitszusage für große Produktionsbestände.

Der Downgrade dieser Revision lässt die Dezimaltypen bewusst bestehen. Eine
Rückumwandlung in Double Precision könnte neue genaue Dezimalwerte beschädigen.
Die vorherige Anwendung kann die dezimalen Daten weiterhin lesen; ein erneutes
Upgrade ist möglich. Andere historische Downgrades behalten ihr eigenes
bisheriges Verhalten.

Für SQLite ist diese Migration ein No-op. Seine numerische Affinität garantiert
keine exakte Dezimalarithmetik; eine Tabellenneuanlage allein würde dieses
Problem nicht lösen. Die vorhandenen SQLite-Upgrade-, Übernahme- und
Downgradeprüfungen bleiben erfolgreich.

Das ORM verwendet weiterhin `Numeric(12, 2, asdecimal=False)` und Python-
`float`-Werte. Die Änderung behebt die PostgreSQL-Speicherung und serverseitige
Summen; eine vollständige Decimal-Umstellung der Python-Rechnungen ist damit
nicht abgeschlossen. Auch bestehende Centbegrenzungen bereits dezimaler
Spalten bleiben bestehen.

## Wiederholbare Prüfung

`backend/tests/test_postgres_money_migration.py` benötigt ausdrücklich einen
isolierten lokalen PostgreSQL-Server und einen Benutzer mit `CREATE DATABASE`.
Jeder Test legt eine eigene Datenbank `immoqa_money_<uuid>` an und entfernt
ausschließlich diese selbst angelegte Datenbank. Ohne die Umgebungsvariable
werden die PostgreSQL-Prüfungen übersprungen.

```powershell
$env:IMMO_TEST_POSTGRES_ADMIN_URL = 'postgresql+psycopg2://test_user@127.0.0.1:5432/postgres'
python -m pytest backend/tests/test_postgres_money_migration.py backend/tests/test_migrations.py -q
```

Geprüft auf PostgreSQL 16.15 und Python 3.12: vier echte PostgreSQL-Prüfungen
sowie neun SQLite-Migrationsprüfungen bestanden. Acht Warnungen betreffen den
bestehenden Python-3.12-Datetime-Adapter von SQLite. Der frische Summen-Test
schlug vor der Änderung mit `1111.0000000000002 != Decimal('1111.00')` fehl.
