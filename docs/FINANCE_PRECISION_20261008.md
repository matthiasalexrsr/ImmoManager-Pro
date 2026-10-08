# Finanzen: centgenau, einheitlich gefiltert, ohne Doppelzählung

Stand 8. Oktober 2026, Branch `claude/finance-precision` (auf `claude/dreamy-gauss-nmaxhn`). Umsetzung des Pakets „P1 D: Finanzen“ aus Abschnitt 9 der Übergabe (`CLAUDE_HANDOFF_20261007.md`). Grundlage ist der heutige Code; die in der Übergabe genannten historischen Zweige lagen nicht vor. Die PostgreSQL-Spalten sind seit `d7a2f9c4e681` dezimal ([Migration](POSTGRES_DECIMAL_MIGRATION_20261007.md)); offen waren die Rechnungen in Python, die Filter und die Abgrenzung der Sichten.

## Regel

**Beträge sind Cent.**

- Ein gespeicherter Betrag (Buchung, Forderung, Rechnung, Miete) geht als Centbetrag in jede Rechnung ein: kaufmännisch gerundet (`ROUND_HALF_UP`), 2,675 wird 2,68 €. Summen, Differenzen und Vergleiche sind exakte `Decimal`-Rechnung, nie `float`.
- Abgeleitete Beträge (Durchschnitte, anteilige Mieten, Aufteilungen) werden einmal gerundet, dort wo sie entstehen. Aufteilungen verteilen Restcents nach dem größten Rest, die Teile ergeben exakt das Ganze.
- Neue Buchungen und Zahlungszuordnungen werden beim Speichern auf Cent gerundet; ein Betrag, der dabei 0 wird, wird abgewiesen. Ältere Werte mit mehr Nachkommastellen bleiben lesbar und werden beim Rechnen je Wert gerundet.
- Die API liefert Beträge weiter als JSON-Zahlen in der bisherigen Form (`0.3`, `1250.0`), nie `-0.0`. Das Frontend braucht keine Änderung, um die Zahlen zu lesen.

**Drei Sichten, getrennt.**

| Sicht | Endpunkt | Was zählt |
| --- | --- | --- |
| Zahlungsübersicht (Ist) | `GET /reports/cashflow` | Buchungen mit Buchungsdatum im Zeitraum, nach Einnahme- oder Ausgabenseite. Je Monat eine Zeile. |
| Periodenergebnis (Soll) | `GET /reports/period-result` (neu) | In ganzen Kalendermonaten: Sollmiete aus dem Mietverlauf der Verträge + sonstige Erträge − Kosten. Zahlungen von Mietern zählen nicht, sie begleichen die Sollmiete. |
| Prognose | `GET /reports/liquidity-forecast` | Für jeden künftigen Monat: Sollmiete der laufenden Verträge (Vertragsende und Mietverlauf beachtet) + Durchschnitt der sonstigen Erträge − Durchschnitt der Kosten. Kontostand heute als Start. |

- **Einnahme oder Ausgabe:** nach dem Typ der Kategorie; ohne Kategorie ist Geld mit Mieterbezug Einnahme (Miete, ihre Rückbuchung, Erstattung), alles andere nach Vorzeichen.
- **Sollmiete:** warm (Kaltmiete + Vorauszahlungen), der Monat des Ein- und Auszugs nach Tagen, Entwürfe schulden nichts. Dieselbe Rechnung wie im Mieterkonto.
- **Sonstige Erträge:** Einnahmen mit Einnahmekategorie, ohne Mieter und ohne Einheit (Zinsen, eine ohne Mieter gebuchte Nachzahlung). Eingänge ohne Kategorie oder mit Einheitsbezug können noch nicht zugeordnete Miete sein; sie stehen getrennt als `unassigned_income` und nicht im Ergebnis.
- **Kosten:** Buchungen der Ausgabenseite ohne Mieterbezug, nach Buchungsdatum. Rechnungen kommen nicht hinzu, ihre Zahlung ist bereits eine Ausgabenbuchung.
- **Nullmonate:** Jede Monatsreihe enthält jeden Monat des Zeitraums, Monate ohne Buchung als Nullzeile. Die Durchschnitte der Prognose teilen durch alle vollen Kalendermonate der letzten zwölf, nicht nur durch die Monate mit Einnahmen; Monate vor der ersten Buchung zählen nicht.

**Storno, Teilzahlung, Guthaben: einmal gezählt.**

- Ein **Storno** ist eine eigene Buchung, die auf die stornierte Buchung verweist (`reverses_booking_id`). Es hat das umgekehrte Vorzeichen, zusammen mit weiteren Stornos höchstens deren Betrag, dasselbe Konto, dieselbe Kategorie, dasselbe Objekt, dieselbe Einheit, denselben Mieter und liegt nicht vor ihr. Ein Storno wird nicht storniert. Der Verweis ist nach dem Buchen fest.
- Auswertungen verrechnen Storno und Original: Das Storno zählt auf der Seite des Originals, im Monat seines eigenen Datums. Eine Rücklastschrift mindert die Einnahmen und ist keine Ausgabe. Bisher stand sie zweimal in den Bruttozahlen (Einnahme und Ausgabe).
- Im Mieterkonto wird das Storno denselben Verträgen gutgeschrieben wie das Original, in dessen Verhältnis, und mindert genau diese Zahlung. Eine stornierte Buchung lässt sich weder umbuchen noch löschen, solange ihr Storno besteht; ihr Betrag deckt immer die Stornos.
- **Teilzahlungen** werden dem Vertrag gutgeschrieben und zählen bis zum Stichtag; spätere Zahlungen zählen weder als bezahlt noch als nicht zugeordnet (Mieterkonto, Abrechnung des Vertrags, Mahnvorschlag).
- Eine **Überzahlung** ist das Guthaben des Vertrags (`overpaid`), keine nicht zugeordnete Zahlung. Nicht zugeordnetes Geld steht getrennt und mindert keinen Saldo. Gutschriften aus Nebenkostenabrechnungen (negative Forderungen) werden weiter nie mit offenen Forderungen verrechnet.

**Gleiche Filter für alle Finanzberichte:** `date_from`, `date_to` (einschließlich), `portfolio_id`, `property_id`, `unit_id`.

| Datensatz | Zeitraum nach | Portfolio | Objekt | Einheit |
| --- | --- | --- | --- | --- |
| Buchung | Buchungsdatum | des Kontos | genanntes Objekt, sonst das der Einheit | genannte Einheit |
| Vertrag, Sollmiete | Monate des Mietverlaufs | des Objekts | des Vertrags | des Vertrags |
| Forderung | Fälligkeit | über den Vertrag | über den Vertrag | über den Vertrag |
| Rechnung | Rechnungsdatum | des Objekts | genanntes Objekt | nie (Rechnungen gehören zum Objekt) |
| Anfangsbestand der Konten | – | Konten des Portfolios | nicht enthalten | nicht enthalten |

Ein Zeitraum, der nach seinem Ende beginnt, wird mit 422 abgewiesen. Eine unbekannte oder fremde ID ergibt leere Zahlen, keinen Fehler. Die Portfoliogrenze des Kontos gilt zusätzlich: Ein eingeschränktes Konto bekommt dieselben Zahlen wie ein Eigentümer mit Filter auf seine Portfolios.

## Bestandsaufnahme vorher

| Endpunkt | Zahlen | Lesen | Filter | Doppelzählung / Fehler | Jetzt |
| --- | --- | --- | --- | --- | --- |
| `GET /dashboard/stats` | nur Anzahlen; Vorabprüfung verglich `float(amount) <= 0` | ganze Listen in Python | keine | – | Vergleich in Cent; sonst unverändert |
| `GET /reports/summary` | float-Summen | alle Buchungen (Cache), Forderungen, Rechnungen in Python | keine | – | Decimal; Buchungen per SQL-Summe; Zeitraum, Portfolio, Objekt, Einheit (auch für die Anzahlen) |
| `GET /reports/finance` | float je Kategorie | alle Buchungen in Python | keine | – | SQL `GROUP BY` Kategorie in Cent; alle Filter |
| `GET /reports/cashflow` | float | alle Buchungen in Python | nur `months` | Einnahme/Ausgabe nach Vorzeichen: Rücklastschrift als Einnahme **und** Ausgabe | Seitenregel, Storno saldiert, Monatsreihe mit Nullmonaten, alle Filter |
| `GET /reports/receivables-aging` | float | alle Forderungen | keine | Gutschriften schon getrennt | Decimal; Filter über den Vertrag, Zeitraum = Fälligkeit |
| `GET /reports/liquidity-forecast` | float, am Ende gerundet | alle Buchungen | nur `property_id` | Durchschnitt nur über Monate **mit Einnahmen** (Nullmonate fehlten, Ausgaben durch Einnahmemonate geteilt); Kontostand enthielt künftige Buchungen; Einnahmen als Fortschreibung vergangener Zahlungen | Sollmiete der Verträge + Durchschnitte über volle Monate inkl. Nullmonate; Stand bis heute; Portfolio, Objekt, Einheit |
| `GET /reports/maintenance-costs` | float | alle Fälle | keine | – | Decimal; Portfolio, Objekt, Einheit |
| `GET /reports/datev-export` | `abs(float)` mit `:.2f` (binäre Rundung) | alle Buchungen | Datum | – | Cent; zusätzlich Portfolio, Objekt, Einheit; Storno als eigene Zeile mit umgekehrtem S/H |
| `GET /reports/pdf/{name}` | wie oben | wie oben | keine | wie oben | nutzt die neuen Berechnungen ohne Filter |
| `GET /accounts` (Saldo) | float-Summe aller Buchungen, `round(…, 2)` | alle Buchungen in Python | Portfolio, Typ | – | SQL-Summe je Konto in Cent |
| `GET /budgets/analysis` | float | alle Budgets | Objekt, Jahr | – | Decimal |
| `GET /tenants/{id}/account` | Decimal je Vertrag; nicht zugeordnet float; Summen im Browser float | Buchungen des Mieters | Stichtag | Zahlungen **nach** dem Stichtag zählten als bezahlt; Rundung `HALF_EVEN` | Stichtag schneidet ab; Summen (`totals`) in Cent vom Server; Storno gespiegelt; `HALF_UP` |
| `GET /contracts/{id}/settlement`, `POST …/dunning-campaign` | Decimal | Zahlungen des Mieters | Stichtag | spätere Zahlungen zählten | Stichtag schneidet ab |
| Zahlungszuordnung (`POST /bookings`, `PUT …/allocations`, `allocate-unassigned`) | Decimal, Rundung `HALF_EVEN` | Verträge des Mieters | – | Rückbuchung nach Regeln statt wie das Original | `HALF_UP`; Storno folgt dem Original |
| `GET /review` | Decimal; Kaution/Kappung float mit +0,005-Toleranz | alle Buchungen | Stichtag | stornierte Zahlungen blieben „nicht zugeordnet“; Division durch 0 bei Vormiete 0 | exakte Vergleiche; Storno und Original zusammen entschieden |
| `POST /invoices/{id}/match` | Decimal | alle Buchungen | – | stornierte Zahlungen galten als offen | Stornos und Stornierte ausgenommen bzw. nur mit Rest |
| `GET /admin/dsgvo/tenant/{id}/export`, `GET /data/export` | keine Summen, Werte wie gespeichert | Datensätze | Mieter / alles | – | unverändert; Buchungen tragen jetzt `reverses_booking_id` |
| Nebenkostenabrechnung (`/billing/…/generate`, Export, PDF, Forderungen) | bereits Decimal, Cents nach größtem Rest | je Abrechnungszeitraum | Zeitraum | – | unverändert |

## Technik

| Ebene | Umsetzung |
| --- | --- |
| Geld | `backend/domain/money.py`: `money()` (Centbetrag, `HALF_UP`, Float über seine kürzeste Darstellung), `cents()`, `money_sum()`, `as_number()` für JSON. |
| Klassifizierung und Filter | `backend/services/finance_ledger.py`: `FinanceFilter`, `Dimensions` (Zuordnung von Datensätzen), `booking_totals()` mit Gruppen Monat, Kategorie, Konto. |
| SQL | Eine Abfrage über die Session der Anfrage: innere Auswahl klassifiziert jede Buchung (Seite, Mieter, Kategorie, Einheit) und rechnet ganze Cent, die äußere summiert per `GROUP BY` (PostgreSQL würde gebundene CASE-Literale zwischen SELECT und GROUP BY nicht gleichsetzen). PostgreSQL: `ROUND(amount::numeric, 2) * 100`; SQLite (REAL): `ROUND(amount * 100 ± 1e-7)`, damit z. B. 1,005 wie die eingegebene Dezimalzahl gerundet wird. Die Portfoliogrenze setzt `portfolio_scope` auf jede Auswahl, auch auf die Unterabfragen der Filter. |
| Speicher-Store | Dieselbe Klassifizierung in Python über die bereits begrenzten Sammlungen. Beide Wege liefern für dieselben Daten dieselben Werte (Tests laufen auf beiden). |
| Berichte | `backend/services/report_service.py`: Zusammenfassung, Kategorien, Forderungsalter, Zahlungsübersicht, Periodenergebnis, Prognose, Instandhaltung; Sollmiete über `LeaseEngine` und den Mietverlauf (`CachedReads`, ein Lesevorgang für alle Mietstände). |
| Router | `backend/routers/reports.py`: gemeinsame `Annotated`-Parameter (auch als normale Funktion aufrufbar, z. B. für den PDF-Export); neuer Endpunkt `/reports/period-result` (JSON und CSV). Die Finanzberichte tragen zusätzlich `filters` (wie angewandt), die drei Sichten auch `basis` (`cash`, `accrual`, `forecast`), die Zahlungsübersicht `monthly`, die Prognose je Monat `projected_rent` und `projected_other_income` sowie `history_months`, das Mieterkonto `totals`; bestehende Felder bleiben. |
| Storno | `backend/domain/booking_reversal.py` (Regeln), geprüft in beiden Stores bei Anlegen, Ändern und Teiländern; `POST /bookings/{id}/reverse` (Betrag ohne Vorzeichen, sonst der Rest; Datum heute, nicht vor dem Original); Löschschutz in `deletion_guard`; Spiegelung der Zuordnung in `payment_allocations.mirror_allocation`. |
| Migration | `f3b9c1d7e2a5` nach `c3e8a1f5d9b7`: `bookings.reverses_booking_id` (Verweis auf `bookings`, `ON DELETE SET NULL`) und Index `idx_bookings_reverses`. Bestehende Buchungen bleiben gewöhnliche Buchungen. Der Downgrade wird abgewiesen, solange ein Storno existiert (die ältere Version würde es als eigene Einnahme oder Ausgabe zählen); ohne Stornos entfernt er Index und Spalte. Auf einer aus `create_all()` übernommenen SQLite-Datenbank bleibt die ungenutzte Spalte stehen, weil SQLite die tabellenweite Referenz nicht entfernen kann. |
| Caches | Unverändert: Ergebnisse von `one_at_a_time` sind nach Parametern und Zugriffsbereich getrennt, `whole_table("bookings")` nach Zugriffsbereich. Keine Datenbankarbeit im Event-Loop (alle Endpunkte synchron im Threadpool), keine eigenen Engine-Verbindungen. |
| Frontend | Mieterkonto zeigt die Summen des Servers (ältere Server: wie bisher addiert). Buchungen: Kennzeichen „Storno“ in der Liste, „Storno von“ mit Link in der Detailansicht, Aktion „Stornieren“ mit Bestätigung. |

## Nachweise

| Prüfung | Ergebnis |
| --- | --- |
| `backend/tests/test_finance_precision.py` (Speicher und SQLite) | 20 Tests je Store: 0,1 + 0,2, 3 × 33,33, 100 × 11,11; Rundung; Nullmonate; Rücklastschrift als Storno; Teilzahlung über Monate; Überzahlung als Guthaben; Filter Objekt/Einheit/Portfolio; eingeschränktes Konto; Zahlungsübersicht, Periodenergebnis und Prognose eines kleinen Bestands mit von Hand gerechneten Werten; Storno-Regeln, Löschschutz, Prüfliste, Rechnungsabgleich, DATEV; SQLite-Centsumme von Altwerten mit drei Nachkommastellen gleich der Python-Rundung. |
| `backend/tests/test_finance_precision_postgres.py` (PostgreSQL 16) | 3 Tests: Summen als `Decimal` aus der Datenbank (100 × 11,11 = 1111,00; Storno netto 0), Portfoliogrenze für SQL-Summen, Migration (Verweis `SET NULL`, Index, Downgrade abgewiesen mit Storno, danach möglich, erneutes Upgrade). |
| `backend/tests/test_migrations.py` | 2 neue SQLite-Prüfungen: Upgrade erhält Buchungen, Downgrade-Schutz, übernommene `create_all()`-Datenbank. |
| `backend/tests/test_portfolio_scope_http.py` | Der bestehende Differenztest prüft automatisch auch `/reports/period-result`: Zahlen eines eingeschränkten Kontos = Zahlen ohne das fremde Portfolio. |
| Backend gesamt, Speicher-Store mit PostgreSQL 16 (`IMMO_TEST_POSTGRES_ADMIN_URL`) | 1456 bestanden, 8 übersprungen (vorher ohne PostgreSQL: 1418 bestanden, 21 übersprungen). |
| Backend gesamt, SQLite-Store (`TEST_STORE_BACKEND=sql`) | 1439 bestanden, 25 übersprungen (vorher 1417 bestanden, 22 übersprungen). |
| Frontend | `src/test/FinancePrecision.test.jsx` (4 Tests): Serversummen statt Float-Addition (0,1 + 0,2 − 0,3 bleibt „Offen 0,00 €“ ohne Warnfarbe), Storno nach Bestätigung, keine Buchung ohne Bestätigung, Storno mit Verweis und ohne zweite Stornoaktion. Gesamt 251 Tests in 45 Dateien, ESLint ohne Befund. |
| Statische Prüfung | `ruff check backend` ohne Befund; `python -m mypy backend` (mypy 2.4.0) ohne Befund in 270 Dateien. |

## Sichtbare Änderungen

- Zahlungsübersicht (Dashboard „Finanzen im Überblick“, Analyse): Rückbuchungen von Mieten mindern die Einnahmen statt als Ausgabe zu erscheinen. Einnahmen und Ausgaben werden dadurch kleiner, der Saldo bleibt gleich.
- Liquiditätsprognose: Einnahmen sind jetzt die Sollmieten der Verträge plus sonstige Erträge; Ausgaben der Durchschnitt über volle Monate einschließlich Monaten ohne Kosten. Bisher waren Einnahmen und Ausgaben durch die Zahl der Monate mit Einnahmen geteilt. Der Startsaldo enthält keine künftig datierten Buchungen mehr.
- Mieterkonto mit Stichtag in der Vergangenheit: Zahlungen nach dem Stichtag zählen nicht mehr als bezahlt (gleiches gilt für Abrechnung und Mahnvorschlag eines Vertrags).
- Prüfliste: eine vollständig stornierte Zahlung erscheint nicht mehr als „nicht zugeordnet“.
- Neue Buchungen mit mehr als zwei Nachkommastellen werden auf Cent gerundet.
- Neu: Periodenergebnis (API und CSV), Stornieren in der Buchungsansicht, Filter in allen Finanzberichten.

## Bewusst offen

- **Sollstellungen und manuelle Forderungen** gehen nicht ins Periodenergebnis ein: Die Sollmiete kommt allein aus dem Mietverlauf, sonst würden Mietrückstände doppelt zählen (die Testversion legt für Rückstände zusätzlich Forderungen und Sollstellungen an). Manuelle Forderungen erscheinen in Zusammenfassung und Forderungsalter.
- **Nebenkostenabrechnungen** werden nicht dem Abrechnungsjahr zugeordnet. Ihre Zahlungen zählen ohne Mieterbezug als sonstiger Ertrag oder Kosten, mit Mieterbezug begleichen sie das Mieterkonto.
- Eine Buchung mit **Einnahmekategorie ohne Mieter und ohne Einheit** zählt als sonstiger Ertrag. Ist sie in Wahrheit Miete, zählt sie zusätzlich zur Sollmiete; die Prüfliste meldet bisher nur Eingänge ohne Kategorie.
- **Kosten** zählen nach Zahlungsdatum, nicht nach Rechnungsdatum; Rechnungen ohne Ausgabenbuchung fehlen im Periodenergebnis.
- Die **Prognose** nimmt vollständige, pünktliche Mietzahlung an, rechnet keine Rückstände ein, berücksichtigt keine bereits erfassten künftigen Buchungen und keine noch nicht angewendeten Mietanpassungen; der Rest des laufenden Monats fehlt. Der Zeitraum-Filter gilt für sie nicht.
- **Mieterkonto** listet weiterhin auch Vertragsentwürfe mit Soll (das Periodenergebnis nicht).
- Status `partial` einer Forderung: `amount_due` gilt als offen, es gibt kein Feld für den bezahlten Teil.
- **Nur Buchungen werden in der Datenbank summiert.** Verträge, Forderungen und Rechnungen werden weiter in Python gelesen (begrenzt durch ihre Zahl); DATEV-Export, Prüfliste und Mieterkonten brauchen jede einzelne Buchung und lesen sie wie bisher.
- **Frontend-Listen** (Buchungs-Kennzahlen, Mietübersicht, Kontenliste, Objektakte) addieren angezeigte Beträge weiter im Browser; angezeigt wird gerundet. Die Kennzahl Einnahmen/Ausgaben der Buchungsliste zählt nach Vorzeichen und weicht bei Rückbuchungen von der Zahlungsübersicht ab.
- Dashboard-Kennzahlen (Anzahlen), Belegung und auslaufende Verträge haben keine Filter.
- SQLite-Altwerte mit mehr als zwei Nachkommastellen: die Datenbanksumme rundet bis vier Nachkommastellen und Beträge bis 10⁸ € wie Python (200 000 Zufallswerte ohne Abweichung); darüber hinaus ist ein Cent Abweichung möglich. PostgreSQL rundet exakt.
- DATEV: Ein Storno ist eine Gegenbuchung, ohne Generalumkehr-Kennzeichen.
- Rechnungen, Forderungen, Mieten und Budgets werden beim Speichern nicht auf Cent gerundet, nur beim Rechnen.
