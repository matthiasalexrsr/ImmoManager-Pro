# Objekt- und Energieverträge: Anbieter, Standorte, Tarife, Fristen, Soll/Rechnung/Zahlung

Stand 8./9. Oktober 2026, Branch `claude/service-contracts` (auf `claude/dreamy-gauss-nmaxhn`, `27fe494`). Umsetzung des Pakets „P1 G: Objekt-/Energieverträge“ aus Abschnitt 9 der Übergabe (`CLAUDE_HANDOFF_20261007.md`). Die dort genannten historischen Zweige (z. B. `service-contract-g1-writer-plan`) lagen nicht vor; gebaut wurde auf dem heutigen Code: gemeinsames Adressbuch (Kontakte), Rechnungen, Buchungen, Dokumente, Kostenpositionen der Nebenkostenabrechnung, dauerhafter Job-Kern und Portfolio-Grenze. Migration `5e8b2d4f7a19` nach `a4d8e2f6c1b9`.

## Regel

**Was ein Objektvertrag ist.** Ein laufender Vertrag eines Objekts mit einem Anbieter: Strom, Gas, Fernwärme, Wasser/Abwasser, Müllabfuhr, Hausreinigung, Hauswart, Aufzugswartung, Gartenpflege, Winterdienst, Schornsteinfeger, Heizungswartung, Kabel-TV/Antenne, Sonstiges. Versicherungen bleiben im eigenen Modul (Deckungssumme, Prämie, Schadenbezug); sie werden nicht doppelt geführt.

- **Anbieter** ist ein Kontakt des gemeinsamen Adressbuchs. Ein eingeschränktes Konto darf jeden lesbaren Kontakt als Anbieter wählen, auch einen, der nicht an sein Portfolio gebunden ist. Ändern darf es den Kontakt weiterhin nur nach der bisherigen Adressbuchregel. Ein Anbieter mit Vertrag lässt sich nicht löschen (409).
- **Standorte** (viele je Vertrag): Immobilie, optional Einheit und Zähler, Zählpunkt/Marktlokation, Kostengewicht und Gültigkeit. Einheit und Zähler müssen zur Immobilie gehören, ein Standort kommt je Vertrag nur einmal vor, der letzte Standort bleibt. Ein gelöschter Zähler macht den Standort zum Objektstandort (SET NULL). Immobilie und Einheit mit Standort lassen sich nicht löschen (409).
- **Tarifhistorie:** Ein Tarif gilt ab seinem Datum bis zum Beginn des nächsten (je Vertrag und Tag nur einer, nicht vor Vertragsbeginn, nicht nach Vertragsende). Er hält Grundpreis (je Monat oder Jahr), Arbeitspreise mit Einheit (kWh, m³, Stück …, bis sechs Nachkommastellen, exakt als Text gespeichert), Preisgarantie bis, Abschlag/Rate mit Rhythmus (monatlich bis jährlich) und Fälligkeitstag, Brutto-/Nettopreise mit Steuersatz. „Welcher Tarif galt am Tag X“ beantwortet `GET /service-contracts/{id}/tariffs/at?date=X`.

**Laufzeit, Verlängerung, Kündigung.** Kalenderrechnung nach §§ 187, 188 BGB (`backend/domain/service_contract_terms.py`):

| Fall | Regel | Beispiel |
| --- | --- | --- |
| Laufzeit von N Monaten ab Tag S | endet am Vortag des Tages mit S's Zahl; fehlt er im Zielmonat, am Monatsletzten (§ 188 III) | 01.01.2025 + 24 → 31.12.2026; 31.01. + 1 → 28.02. (29.02.2028); 29.02.2028 + 12 → 28.02.2029; 01.03.2027 + 12 → 29.02.2028 |
| Kündigungsfrist | beginnt am Tag nach dem Zugang (§ 187 I), endet am Tag gleicher Zahl bzw. gleichen Wochentags, sonst am Monatsletzten | Zugang 31.01., 1 Monat → 28.02. |
| Spätester Zugang für ein Ende E | letzter Tag, dessen Frist noch bis E reicht | 3 Monate zum 31.12. → 30.09.; zum 30.06. → 31.03.; zum 28.02.2027 → 30.11.2026; 1 Monat zum 29.02.2028 → 31.01.2028; 6 Wochen zum 31.12.2026 → 19.11.2026 |
| § 193 BGB | verschiebt Kündigungsfristen nicht; die Daten bleiben, auch am Wochenende | – |

- **Verlängerungsarten:** `none` endet nach der ersten Laufzeit (Enddatum oder Mindestlaufzeit, eins von beiden). `fixed` verlängert sich um `renewal_months`, solange nicht rechtzeitig gekündigt wird; jede Verlängerung beginnt am Tag nach dem Ende der vorigen. `indefinite` läuft nach der ersten Laufzeit (oder von Beginn an) unbefristet und endet zum nächsten Termin der Art „jederzeit / Monats- / Quartals- / Jahresende“, den die Frist erreicht.
- **Nächste Kündigungsfrist** (`fixed`): das erste Laufzeitende, dessen spätester Zugang noch nicht vorbei ist; verpasst man ihn um einen Tag, gilt das Ende der Verlängerung. `indefinite` hat nach der ersten Laufzeit keine feste Frist; angezeigt wird, wozu eine heute zugehende Kündigung wirkt.
- **Kündigung erfassen** (`POST /service-contracts/{id}/cancel`): Zugangsdatum, optional der Termin. Ohne Termin gilt der frühestmögliche; ein früherer wird abgewiesen („wirkt frühestens zum …“), außer ausdrücklich als außerordentliche/Sonderkündigung (`?extraordinary=true`). Zurücknehmen mit `DELETE …/cancel`. Status: `upcoming`, `active`, `cancelled`, `ended`.

**Erwartung, Rechnung, Zahlung: getrennt, jeder Betrag einmal** (`backend/domain/service_contract_finance.py`):

| Sicht | Quelle | zählt als |
| --- | --- | --- |
| Erwartung (Soll) | Abschläge/Raten des jeweils gültigen Tarifs, Fälligkeitstag je Monat (kurze Monate: Monatsletzter), nur innerhalb der Vertragslaufzeit | Zahlungsverpflichtung, **keine Kosten** |
| Rechnung | eine vorhandene Rechnung (`invoices`), dem Vertrag mit Leistungszeitraum zugeordnet; je Rechnung höchstens ein Vertrag (eindeutig in der Datenbank). Abrechnungen rechnen bereits verlangte Abschläge an. | Bruttobetrag = **Kosten** des Leistungszeitraums; noch geschuldet = Brutto − angerechnete Abschläge (negativ: Guthaben) |
| Zahlung | Teil einer Buchung (`bookings`), dem Vertrag zugeordnet: positiv an den Anbieter, negativ Erstattung; je Vertrag und Buchung einmal, über alle Verträge höchstens der Buchungsbetrag; keine Mieterzahlungen | Ist-Zahlung |

Offen = Soll + (Rechnungen − angerechnete Abschläge) − Zahlungen. Kosten = Rechnungen, zeitanteilig nach Leistungstagen im Zeitraum. Beispiel (in Tests): 12 × 100 € Abschlag 2026, Abrechnung 2026 im Februar 2027 über 1.350 € mit 1.200 € angerechnet, Nachzahlung 150 €. 2026: Soll 1.200, gezahlt 1.200, offen 0, Kosten 1.350. 2027: Rechnungen 1.350, angerechnet 1.200, gezahlt 150, offen 0. Beide Jahre zusammen: Verpflichtungen = Kosten = Zahlungen = 1.350 €. Ohne die Anrechnung stünden 2.550 € Kosten bzw. Verpflichtungen da.

Die bestehenden Finanzberichte (Zahlungsübersicht, Periodenergebnis, Prognose) bleiben unverändert: Die Zahlungen sind dieselben Buchungen, die dort schon als Ausgaben zählen; Objektverträge erzeugen keine eigenen Buchungen.

**Kosten in die Nebenkostenabrechnung, keine zweite Kostenrechnung.** Nur ein als umlagefähig markierter Vertrag überträgt Rechnungen (`POST /service-contracts/{id}/cost-transfers` mit Abrechnungsperiode und Verteilerschlüssel desselben Objekts) in die bestehenden Kostenpositionen (`cost_items`):

- Betrag = Brutto der Rechnung × Leistungstage in der Periode / alle Leistungstage (einmal auf Cent gerundet) × Anteil des Objekts an den Kostengewichten der im Zeitraum gültigen Standorte (größter Rest, die Teile aller Objekte ergeben exakt die Rechnung) × umlagefähiger Prozentsatz (z. B. Hauswart 80 %).
- Die Kostenposition trägt ihre Herkunft (`cost_items.service_contract_invoice_id`). Je Abrechnungsperiode und Rechnung gibt es höchstens eine Position (eindeutiger Index). Eine Korrektur übernimmt die Herkunft mit der Kopie, eine erneute Übernahme in die Korrektur überspringt sie deshalb. Beim Bearbeiten einer Kostenposition bleibt die Herkunft erhalten.
- Finalisierte Perioden nehmen nichts mehr auf (409). Eine übernommene Rechnung lässt sich weder lösen noch ändern, solange die Kostenposition besteht; eine verknüpfte Rechnung lässt sich nicht löschen (409).

**Portfolio-Grenze (Entscheidung).** Ein Objektvertrag hat keinen eigenen Portfolioverweis; er gehört zu den Portfolios seiner Standorte.

- **Lesen:** Ein Vertrag ist sichtbar, wenn mindestens ein Standort sichtbar ist. Standortzeilen anderer Portfolios bleiben verborgen, ebenso Rechnungs-, Zahlungs- und Dokumentzuordnungen, deren Rechnung, Buchung oder Dokument das Konto nicht sieht. Die Antwort sagt, dass weitere Standorte existieren (`restricted: true`, in Zahlen `partial: true`), nennt sie aber nicht.
- **Schreiben:** Den Vertrag und alles, was an ihm hängt (Standorte, Tarife, Kündigung, Rechnungen, Zahlungen, Dokumente, Kostenübernahme, Löschen), ändert nur ein Konto, das **alle** Standorte sieht; sonst 403. Ein eingeschränktes Konto legt Verträge mit Standorten in seinen Portfolios an; ein Standort außerhalb wird abgewiesen, ohne dass etwas gespeichert wird.
- Kontakte bleiben ein gemeinsames Adressbuch (siehe oben).

**Fristen-Erinnerungen.** Täglich um 06:30 Uhr (Europe/Berlin) läuft der dauerhafte Installationsjob `service_contracts.deadlines`. Für jede Kündigungsfrist, jedes Ende einer Preisgarantie des jeweils gültigen Tarifs und jedes feste Vertragsende, dessen Vorlauf (`reminder_days`, Standard 30 Tage) begonnen hat, entstehen genau eine Aufgabe (fällig am Fristtag, beim Objekt des ersten Standorts, Priorität hoch bei Kündigungsfristen) und eine Benachrichtigung (`service_contract_deadline`, Bezug auf den Vertrag). Genau einmal heißt: je Vertrag, Art und Fristdatum, über alle Läufe und Worker. Ändert sich die Laufzeit, entsteht für das neue Datum eine neue Erinnerung.

## Technik

| Ebene | Umsetzung |
| --- | --- |
| Tabellen (Migration `5e8b2d4f7a19` nach `a4d8e2f6c1b9`) | `service_contracts` (Anbieter `contacts` RESTRICT; CHECKs für Verlängerungsart, Fristeinheit, Daten, Prozent), `service_contract_locations` (Immobilie/Einheit CASCADE, Zähler SET NULL; Gewicht > 0), `service_contract_tariffs` (UNIQUE Vertrag + Datum; Arbeitspreise als JSON mit Dezimaltext), `service_contract_invoices` (Rechnung UNIQUE, RESTRICT; Art `regular`/`settlement`; Leistungszeitraum), `service_contract_payments` (Buchung CASCADE; UNIQUE Vertrag + Buchung; Betrag ≠ 0; optional Rechnung, SET NULL), `service_contract_documents` (Dokument CASCADE; UNIQUE). `cost_items.service_contract_invoice_id` ohne Fremdschlüssel (SQLite-Downgrade ohne Tabellenumbau) mit eindeutigem Index (Periode, Herkunft). Alles bedingt angelegt (bestehende Tabelle, Spalte, Index werden übersprungen). Der Downgrade wird abgewiesen, solange ein Vertrag oder eine übernommene Kostenposition existiert. |
| Modelle | `backend/db/service_contract_models.py` (ORM, über `backend/db/__init__.py` und `schema_state.initialise_empty` registriert), `backend/models_service_contracts.py` (Pydantic; Lesemodelle spiegeln die Tabellen Feld für Feld). Geld als Cent (`domain.money`), Arbeitspreise als exakter Dezimaltext. |
| Fachlogik | `backend/domain/service_contract_terms.py` (Laufzeit, Fristen, Status), `backend/domain/service_contract_finance.py` (Tarif am Tag, Fälligkeiten, Abgleich, Anteile), `backend/services/service_contracts.py` (Prüfungen, Sichten, Zahlungs- und Rechnungsregeln, Kostenübernahme). |
| Speicher | Speicher-Store: `backend/storage_service_contracts.py` (Mixin von `InMemoryStore`; Mehrzeilen-Schreibvorgänge ganz oder gar nicht; die Kaskaden der SQL-Fremdschlüssel bei Buchung, Dokument, Zähler, Immobilie, Einheit nachgebildet). SQL: `backend/repositories/service_contract_repo.py` (eine Transaktion je Vorgang; Vertrag und Standorte in zwei Flushes derselben Transaktion; Verstöße gegen Eindeutigkeit werden zu verständlichen 400-Meldungen). `NotFoundError`/`ValidationError` liegen jetzt in `backend/store_errors.py` (weiterhin aus `backend.storage` importierbar). |
| Portfolio-Grenze | `backend/services/portfolio_scope.py`: SQL-Kriterium für `service_contracts` = existiert ein sichtbarer Standort; die Kante Standort → Vertrag zählt für die Sichtbarkeit nicht (wie Vertrag → Mieter). Schreibwächter: Referenzen auf `SHARED_READ`-Tabellen brauchen nur Lesbarkeit; Vertrag oder Kindzeile eines Vertrags mit verborgenem Standort → 403. Zeilen, die derselbe Schreiber in derselben Transaktion anlegt, gelten als sichtbare Eltern (`db.info`, nach Commit/Rollback geleert; Speicher-Store: `created_together`). Ressourcenalias `service_contract` für Benachrichtigungen. |
| API | `backend/routers/service_contracts.py` unter `/api/v1/service-contracts`: Liste (Filter Immobilie, Einheit, Zähler, Art, Anbieter, Status, Suche) und Fristenübersicht `/deadlines`, Detail, Anlegen (mit Standorten und erstem Tarif), Ändern, Löschen (nur ohne Rechnungen und Zahlungen), Kündigen/Zurücknehmen, `/terms`, Standorte, Tarife, `/tariffs/at`, `/instalments`, Rechnungen (vorhandene zuordnen oder neu erfassen), Zahlungen mit Vorschlägen (`/payment-candidates`: Nummer, Anbieter, Abschlagsbetrag, Objekt), `/reconciliation`, Kostenübernahme, Dokumente. Alle Endpunkte synchron (Threadpool), keine Datenbankarbeit im Event-Loop. Veraltete Bearbeitung über `updated_at` → 409. |
| Rechte | Schreiben: Eigentümer, Verwalter. Buchhaltung zusätzlich Rechnungen, Zahlungen und Kostenübernahme (`backend/permissions.py`). |
| Löschschutz | `deletion_guard`: Immobilie/Einheit mit Standort, Kontakt als Anbieter, verknüpfte Rechnung (auch Massenlöschung). Der Schutz für Kontakt und Rechnung zählt Verweise aller Portfolios. |
| Job | `backend/services/jobs/service_contract_deadlines.py`, registriert in `scheduler.PERIODIC` (täglich 06:30). Abschnitte zu 200 Verträgen, Checkpoint je Abschnitt; Vorkommensbuch `service_contract:<id>:<art>` / `v1` / Fristdatum. SQL: Aufgaben, Benachrichtigungen, Buch und Checkpoint in einer Transaktion. |
| Snapshot | Die sechs Tabellen sind Felder von `InMemoryStore` und damit automatisch in Export/Import; `cost_items` trägt die Herkunft. Snapshot-Format **4** (ältere Programme lehnen die Datei ab, statt Verträge still zu verwerfen). |
| Frontend | Navigation Portfolio → „Objektverträge“ (`/service-contracts`, `/service-contracts/:id`). Liste mit Suche, Art- und Statusfilter, Fristen der nächsten 90 Tage. Akte mit Kennzahlen und Reitern Stammdaten, Standorte, Tarife, Fristen, Erwartung/Rechnungen/Zahlungen (Jahr, Soll/Rechnungen/angerechnet/gezahlt/offen/Kosten, Rechnungen mit Übernahmen, Zahlungen, geplante Abschläge), Dokumente (zuordnen, hochladen, ansehen). Bei verborgenen Standorten nur Lesen mit Hinweis. Texte de/en/es. Dateien: `frontend/src/pages/ServiceContracts.jsx`, `ServiceContractDetail.jsx`, `frontend/src/features/serviceContracts/`. |

## Nachweise

| Prüfung | Ergebnis |
| --- | --- |
| `backend/tests/test_service_contract_terms.py` | 51 Tabellen- und Eigenschaftstests: Laufzeitende (Monatsende, Schaltjahr, 29.02.), Fristende, spätester Zugang (u. a. 30.09., 31.03., 30.11., 31.01.2028, 19.11.), für 7 Fristen jeder Kalendertag 2024–2028 gegen die Definition, Verlängerung fest/unbefristet, Quartals-/Jahresende, Kündigung, widersprüchliche Angaben; Tarif am Tag, Fälligkeiten, Abschläge über Tarifwechsel und Vertragsende, Abgleich ohne Doppelzählung, Anteile auf den Cent. |
| `backend/tests/test_service_contracts.py` (Speicher und SQLite) | 22 Tests je Store: Anlegen mit Standort/Tarif, Fristen über die API, Filter; Prüfungen; Tarifhistorie; Kündigung inkl. außerordentlich; veraltete Bearbeitung; Soll/Rechnung/Zahlung (Beispiel oben), Teil- und Mehrfachzuordnung, Vorzeichen, Mieterzahlung abgewiesen, Zahlungsvorschläge; Kostenübernahme 2 : 1, zweite Übernahme übersprungen, finalisierte Periode 409, Korrektur mit Herkunft, zeitanteilig 181/365 × 80 %; Dokumente; Löschschutz; Rechte; Sichtbarkeit mit Standorten in zwei Portfolios (Liste, Detail, 404, 403 für jede Änderungsart, normales Arbeiten im eigenen Portfolio, Anlegen mit gemeinsamem Anbieter); Erinnerungsjob (einmal je Frist, neue Frist nach Änderung, Sicht eines eingeschränkten Kontos); Snapshot-Rundlauf; jeder lesende Endpunkt mit IDs des fremden Portfolios (5 IDs × alle GET-Routen). |
| `backend/tests/test_service_contracts_postgres.py` (PostgreSQL 16) | 4 Tests: Migration (Fremdschlüsselregeln, eindeutiger Index, Downgrade abgewiesen und danach möglich, erneutes Upgrade), Portfolio-Grenze inkl. Wächter unterhalb der Fachschicht, vier gleichzeitige Kostenübernahmen derselben Rechnung → genau eine Kostenposition, drei Worker × zwei Läufe → genau eine Aufgabe und eine Benachrichtigung. |
| `backend/tests/test_migrations.py` | 2 neue SQLite-Prüfungen: Upgrade erhält Zeilen, Vorgaben, Eindeutigkeit (Rechnung, Tarif je Tag, Buchung je Vertrag, Herkunft je Periode), RESTRICT des Anbieters, abgewiesener Downgrade, Kaskaden, Rundlauf; übernommene `create_all()`-Datenbank. |
| Angepasste Tests | `test_durable_jobs.py` (der neue tägliche Job läuft mit), `test_document_versions.py` (Snapshot-Format ≥ 3), `test_postgres_money_migration.py` (nach dem Downgrade nur vorhandene Tabellen prüfen). |
| Frontend | `frontend/src/test/ServiceContracts.test.jsx` (11 Tests: Nutzdaten, Liste/Filter/Fristen, Akte, Reiter, exakte Preise, Fristkarte, Finanzzahlen, Nur-Lesen bei verborgenen Standorten, Kündigungsdialog, Dokumente); `ShellNavigation.test.jsx` 39 Ziele; Übersetzungstest für de/en/es. |

Die Gesamtläufe stehen im Abschnitt „Gesamtläufe“ unten.

## Bewusst offen

- **Versicherungen** bleiben getrennt; ihre Fristen laufen nicht über diesen Job.
- **Kalender:** Fristen erscheinen als Aufgaben und Benachrichtigungen, nicht als Kalendereinträge.
- **Veraltete Erinnerungen:** Ändert sich eine Frist, bleibt die Aufgabe zum alten Datum stehen (sie wird nicht automatisch geschlossen). Eine Frist, die während einer Ausfallzeit länger als der Vorlauf ganz verstrichen ist, wird nicht nachträglich gemeldet.
- **Aufgabe bei Verträgen über mehrere Portfolios** hängt am Objekt des ersten Standorts; Konten nur des anderen Portfolios sehen die Benachrichtigung (sie hängt am Vertrag), aber nicht die Aufgabe.
- **Eingeschränkte Konten** sehen bei Verträgen mit fremden Standorten nur Teilzahlen und erfahren, dass weitere Standorte existieren (nicht welche). Ändern und Kostenübernahme brauchen Zugriff auf alle Standorte.
- **Zeitanteile über mehrere Abrechnungsperioden** werden je Periode einzeln gerundet; die Summe kann um einen Cent von der Rechnung abweichen. Überlappende Abrechnungsperioden desselben Objekts werden nicht erkannt.
- **Abschläge** sind Plan aus dem Tarif; der tatsächliche Abschlagsplan des Versorgers (z. B. elf Abschläge im Jahr) muss als Tarifzeile mit passendem Rhythmus erfasst werden. Verbrauchsprognosen, Preisvergleiche, Grundpreis-/Arbeitspreis-Kostenschätzung und eine automatische Zahlungszuordnung (Bankabgleich) fehlen; Zahlungsvorschläge sind Vorschläge.
- **Rechnungen** zählen in der Vertragssicht nach Rechnungsdatum (Verpflichtung) bzw. nach Leistungstagen (Kosten); die allgemeinen Finanzberichte behandeln Rechnungen unverändert (siehe Finanzdokument).
- **Sonderkündigungsrecht** (z. B. bei Preiserhöhung) wird nicht berechnet; außerordentliche Kündigungen werden auf ausdrücklichen Wunsch ohne Fristprüfung erfasst.
- **Browserprüfung:** siehe „Gesamtläufe“; keine Prüfung mit echten Versorgerdaten.

## Gesamtläufe

Linux, Python 3.11.15, PostgreSQL 16 lokal (`IMMO_TEST_POSTGRES_ADMIN_URL`), Node 22:

| Prüfung | Ergebnis (Ausgangsstand `27fe494`) |
| --- | --- |
| Backend Speicher-Modus + PostgreSQL | 1610 bestanden, 8 übersprungen (vorher 1531 / 8) |
| Backend SQL-Modus (`TEST_STORE_BACKEND=sql`) + PostgreSQL | 1609 bestanden, 9 übersprungen (vorher 1530 / 9) |
| `ruff check backend`, `python -m mypy backend` (2.4.0) | sauber, 296 Dateien |
| Frontend `npx vitest run --maxWorkers=1` | 48 Dateien, 271 Tests bestanden (davon 11 neu) |
| `npm run lint`, `npm run build` | sauber bzw. gebaut |
| Browser (Chromium headless, isolierte QA-Datenbank) | 360 × 800 und 1440 × 960: Liste, alle sechs Reiter, Finanzzahlen, exakter Arbeitspreis, Anlegen über das Formular bei 360 px, eingeschränktes Konto (Hinweis, kein Bearbeiten, nur eigener Standort); kein seitliches Scrollen, keine Konsolenfehler. Gefunden und behoben: unsichtbare Tabellenköpfe (`sr-only`) ließen bei 360 px die Seite seitlich scrollen. |

Ein paralleler Vitest-Lauf während der Backend-Gesamtläufe hatte Zeitüberschreitungen in bestehenden, nicht betroffenen Tests (Vertrags-Cache, Parteiakte); der serielle Lauf ohne Last ist vollständig grün.
