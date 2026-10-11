# Rechnungsprüfung: vom Eingang über Freigabe und Zahlung bis zum Ergebnis

Stand 11. Oktober 2026, Branch `claude/invoice-review` (auf `claude/dreamy-gauss-nmaxhn`, `7034701`). Teil „Rechnungsprüfung“ des Pakets „P1/P2 D/K: Finanz-/Kommunikationsabläufe“ aus Abschnitt 9 von `CLAUDE_HANDOFF_20261007.md` („Kaution, Mahnung, Rechnungsprüfung, Widersprüche bis Beleg/Zahlung/Ergebnis verbinden“). Kaution und Mahnung entstehen parallel in eigenen Zweigen. Migration **`c9f4a2e7b1d5`** nach `5e8b2d4f7a19` (beim Zusammenführen neu verketten; sie ist in sich geschlossen).

## Bestandsaufnahme vor dem Bau

| Vorhanden | Verwendung in der Rechnungsprüfung |
| --- | --- |
| `invoices` mit `/invoices` (CRUD, `/match`) und den UI-Vertragsfeldern (`invoice_number`, `source_document_id` …) | bleibt **die** Rechnung. Keine zweite Rechnungstabelle, keine Spalte an `invoices` geändert. Die Prüfung ist eine Zeile daneben (`invoice_reviews`). `/invoices` antwortet unverändert. |
| `maintenance_order_invoices` (je Rechnung höchstens ein Auftrag), Nachträge, `domain/project_costs.py` | ist die Zuordnung „Auftrag“ der sachlichen Prüfung; ein Nachtrag kann zusätzlich genannt werden. Die Projektzahlen rechnen geprüfte Rechnungen mit dem freigegebenen Betrag. |
| `invoice_payments` (Ausgabenbuchung → Rechnung) | **sind** die Zahlungen. Kein eigenes Zahlungsbuch; Status bezahlt/teilweise/überzahlt wird daraus abgeleitet. |
| `service_contract_invoices`, Abgleich, Kostenübernahme (`cost_items.service_contract_invoice_id`) | ist die Zuordnung „Objektvertrag“; Abgleich und Übernahme rechnen geprüfte Rechnungen mit dem freigegebenen Betrag, abgelehnte gar nicht. |
| `cost_items` der Nebenkostenabrechnung | Ziel der einmaligen Übernahme frei zugeordneter umlagefähiger Rechnungen. |
| Dokumente (`/documents/import` mit OCR), Dateiablage | Beleg = vorhandenes Dokument (Hochladen aus dem Erfassungsdialog). Die OCR-Analyse bleibt wie sie ist; die Prüfung übernimmt keine OCR-Werte ungefragt. |
| Dokumentversionsarchiv | archiviert nur erzeugte Originale („No public route archives ordinary uploads yet“). Die Prüfung hält statt dessen den SHA-256 der Belegdatei beim Eingang fest und meldet Abweichungen. |
| `permissions.py`, Portfolio-Grenze, Löschschutz, Snapshot (Format 4), DSGVO-Auskunft | erweitert (siehe Technik). |

## Regel

1. **Eingang.** Eine Rechnung bekommt Eingangsdatum und Originalbeleg (hochgeladenes PDF/Bild). Bestehende Rechnungen bleiben „nicht geprüft (Bestand)“, bis jemand den Eingang erfasst; nichts wird erzwungen. Neue Rechnung und Eingang lassen sich in einem Schritt erfassen (ganz oder gar nicht).
   - **Dublettenschlüssel** Lieferant + Rechnungsnummer, unabhängig von Schreibweise, Rechtsform, Trennzeichen und führenden Nullen („Dach-Müller GmbH & Co. KG“/„RE-0042“ = „dach müller“/„re 42“). Ein Eingang mit gleichem Schlüssel wird abgewiesen, außer er wird mit Begründung bestätigt (steht im Verlauf).
   - **Verdacht** gleicher Lieferant, gleicher Bruttobetrag, Rechnungsdatum höchstens N Tage auseinander (Einstellung, Standard 14): Hinweis, keine Sperre.
   - **Skonto** (Prozent, Frist in Tagen ab Rechnungsdatum) und Fälligkeit (Fälligkeitsdatum der Rechnung oder Zahlungsziel in Tagen) werden beim Eingang festgelegt.
2. **Sachliche Prüfung** – ist die Leistung erbracht und beauftragt?
   - Zuordnung: Auftrag einer Instandhaltungsakte (optional mit genehmigtem Nachtrag), Rechnung eines Objektvertrags, oder freie Kostenstelle (Objekt, Einheit, Kostenart, umlagefähig ja/nein).
   - Abweichungen als Hinweis: Summe der Rechnungen über Auftrag + genehmigten Nachträgen, Rechnung über dem Nachtrag, Tarif (geplante Abschläge im Leistungszeitraum) gegen Rechnung, angerechnete gegen geplante Abschläge (Abrechnung), Überschneidung des Leistungszeitraums mit einer bereits freigegebenen Rechnung desselben Vertrags, fehlende Zuordnung.
   - Ergebnis „bestätigt“ oder „beanstandet“ (mit Begründung).
3. **Rechnerische Prüfung.** Netto + Steuer = Brutto je Steuersatz (mehrere Sätze als Steuerzeilen). Ein Cent Abweichung je Satz ist Rundung (Info), mehr ist ein Fehler; unbekannte Sätze (nicht 0/5/7/16/19 %) sind ein Hinweis. Die Pflichtangaben nach **§ 14 Abs. 4 UStG** sind eine Checkliste: Ausstellungsdatum, Nummer, Entgelt je Satz und Steuersatz/-betrag werden automatisch belegt, der Leistungszeitpunkt bei Vertragsrechnungen aus dem Leistungszeitraum, der Rest bestätigt der Prüfer. Bis zur Kleinbetragsgrenze (§ 33 UStDV, Standard 250 € brutto) gelten die verringerten Angaben. **Fehlende Angaben sind ein Hinweis, keine automatische Ablehnung.**
4. **Entscheidung** mit Begründung: freigeben (ohne Pflichtbegründung), teilweise freigeben, ablehnen, Rückfrage beim Lieferanten. Freigabe setzt beide Prüfungen voraus; ist eine beanstandet, geht nur Teilfreigabe, Ablehnung oder Rückfrage. Nach Rückfrage geht die Prüfung weiter. Abgelehnt und freigegeben sind endgültig.
   - **Vier-Augen-Grenze** (Einstellung, Standard aus): Über der Grenze (Brutto) geben nur Eigentümer oder Verwaltung frei, und nie wer sachlich oder rechnerisch geprüft hat. Darunter gibt auch die Buchhaltung frei.
5. **Verlauf.** Jeder Schritt (Eingang, Dublettenbegründung, Änderung der Eingangsdaten, Prüfungen, Entscheidung, Widerspruch, Übernahme) wird in derselben Transaktion als neue Zeile geschrieben: wer (Name und Rolle zum Zeitpunkt), wann, Betrag, Begründung, Details (z. B. die geprüften Beträge). Nichts davon lässt sich ändern: kein Endpunkt, die Datenbank verweigert jedes UPDATE, eine Rechnung mit Verlauf wird nicht gelöscht (auch nicht per Massenlöschung). Nach der Entscheidung bleiben Lieferant, Nummer, Datum, Objekt und Beträge der Rechnung auch über `/invoices` wie geprüft; Status, Notizen, Kategorie bleiben änderbar. Werden Beträge vor der Entscheidung nach der rechnerischen Prüfung geändert, meldet die Prüfung das.
6. **Zahlung.** Zahlungen sind zugeordnete Ausgabenbuchungen (`invoice_payments`), Stornos mindern sie wie in den Projektzahlen. Abgeleitet: zu zahlen = Freigabe + nachträglich anerkannter Teil − Gutschrift über den strittigen Teil hinaus; Status offen / teilweise bezahlt / bezahlt / überzahlt; Skonto zählt, wenn alle Zahlungen bis zur Frist eingingen und zusammen mindestens „zu zahlen − Skonto“ ergeben. **Zahlungsvorschläge** enthalten nur freigegebene Rechnungen mit offenem Betrag, sortiert nach „zahlen bis“ (Skontofrist, sonst Fälligkeit), mit Skontobetrag. Es entsteht keine Zahlungsdatei, nichts wird übermittelt. Eine abgelehnte Rechnung und eine Gutschrift werden nicht bezahlt (409); Zahlungen vor der Freigabe sind möglich (z. B. Lastschrift) und werden als Hinweis gezeigt.
7. **Widerspruch/Reklamation.** Eine Teilfreigabe eröffnet den Widerspruch über den nicht freigegebenen Teil; er bleibt offen und wird nicht vorgeschlagen. Eine **Gutschrift** ist eine eigene Rechnung mit Art „Gutschrift“, die ihre Rechnung nennt (keinem Auftrag/Vertrag zugeordnet, nur rechnerisch geprüft, ganz übernommen oder abgelehnt). Ergebnis des Widerspruchs: Gutschrift erhalten, nachträglich teilweise anerkannt (Betrag; über der Grenze mit Vier-Augen-Regel) oder ausgebucht; der Rest wird jeweils ausgebucht. Beispiel: 1.190 € Rechnung, 990 € freigegeben, Gutschrift 150 €, Rest 50 € ausgebucht; zu zahlen 990 €.
8. **Ergebnis für andere Module.**
   - Projektakte: „abgerechnet“ zählt eine geprüfte Rechnung mit ihrem Ergebnis (in Prüfung: Brutto, freigegeben: Freigabe ± Widerspruch − genutztes Skonto), eine abgelehnte oder eine Gutschrift gar nicht; jede Rechnung höchstens einmal (eindeutige Zuordnung).
   - Objektvertrag: Abgleich und Kostenübernahme rechnen ebenso; abgelehnte Rechnungen werden mit Grund „rejected“, noch nicht freigegebene mit „not_approved“ übersprungen. Die Rechnungsliste des Vertrags zeigt Status und zählenden Betrag.
   - Nebenkostenabrechnung: eine frei zugeordnete, umlagefähige, freigegebene Rechnung ohne offenen Widerspruch wird **einmal** übernommen (Kostenposition mit Betrag, Netto anteilig, Steuersatz, Kostenart, Beleg). Vertragsrechnungen gehen weiterhin über die Vertragsübernahme (zeitanteilig, nach Standorten); beide Wege schließen sich gegenseitig aus. Wird die Kostenposition gelöscht, kann erneut übernommen werden.
   - Bestandsrechnungen (ohne Prüfung) zählen überall wie bisher.
9. **Rechte** (`backend/permissions.py`, im Schreibvorgang unter Kontosperre erneut geprüft):

   | Aktion | Eigentümer/Verwaltung | Buchhaltung | Technik | Nur Lesen |
   | --- | --- | --- | --- | --- |
   | Eingang erfassen/ändern, neue Rechnung mit Eingang | ja | ja | nein | nein |
   | Sachliche Prüfung | ja | **nein** | nur Rechnungen zu einem Instandhaltungsauftrag | nein |
   | Rechnerische Prüfung | ja | ja | nein | nein |
   | Entscheiden | ja | bis zur Vier-Augen-Grenze; Ablehnen/Rückfrage immer | nein | nein |
   | Widerspruch klären, Zahlungen zuordnen, in Abrechnung übernehmen | ja | ja | nein | nein |
   | Einstellungen (Grenzen) | ja | nein (lesen ja) | nein (lesen ja) | nein (lesen ja) |

   Begründung: Sachlich bestätigt, wer die Leistung beauftragt hat oder vor Ort sah; rechnerisch prüft und zahlt die Buchhaltung. So sind zwei Personen an jeder Rechnung beteiligt, auch unter der Grenze.
10. **Portfolio-Grenze** überall: Eingang, Zahlen, Vorschläge, Dublettenprüfung und Dateien sehen nur Rechnungen der eigenen Portfolios; fremde Rechnungen ergeben 404, auch beim Schreiben. Eine freie Kostenstelle in einem fremden Portfolio wird abgewiesen. Dubletten in fremden Portfolios bleiben einem eingeschränkten Konto verborgen.

## Technik

| Ebene | Umsetzung |
| --- | --- |
| Tabellen (Migration `c9f4a2e7b1d5` nach `5e8b2d4f7a19`) | `invoice_reviews` (Rechnung UNIQUE, RESTRICT; Gutschrift → Rechnung RESTRICT; Beleg, Objekt, Einheit, Nachtrag SET NULL; CHECKs für Art, Status, Prüfergebnisse, Widerspruch, Skonto, Gutschriftziel), `invoice_review_events` (UNIQUE Rechnung + Folgenummer; Trigger verweigert UPDATE in SQLite und PostgreSQL), `invoice_cost_transfers` (Rechnung UNIQUE RESTRICT; Kostenposition UNIQUE CASCADE), `invoice_review_settings` (eine Zeile `default`). Keine bestehende Tabelle oder Spalte geändert. Bedingt angelegt (vorhandene Tabellen/Indizes werden übernommen, Trigger ergänzt); Downgrade abgewiesen, solange eine Prüfung, ein Verlaufseintrag oder eine Übernahme existiert. Normale Starts ändern kein bestehendes Schema; leere Datenbank: `create_all` + Trigger + Stempel. |
| Modelle | `backend/db/invoice_review_models.py` (ORM, über `db/__init__.py` und `schema_state.initialise_empty` registriert), `backend/invoice_review_models.py` (Pydantic, Lesemodelle spiegeln die Tabellen). Geld `NUMERIC(12,2)`, gerechnet in Cent (`domain/money.py`). |
| Fachlogik ohne Speicher | `backend/domain/invoice_review.py`: Dublettenschlüssel, Steuer je Satz, § 14-Checkliste, Abweichungen Auftrag/Vertrag, Abrechnung (zu zahlen, bezahlt, offen, strittig, Skonto, Status, zählender Betrag). |
| Dienst | `backend/services/invoice_review.py`: jede Änderung in einer Arbeitseinheit (`maintenance_projects.work`: eigene Session, SQLite `BEGIN IMMEDIATE`, PostgreSQL `FOR UPDATE` auf der Rechnung, Konto gesperrt und Rechte bis zum Commit geprüft, Portfolio-Zaun), Verlaufseintrag in derselben Transaktion. Lesen über `maintenance_rows.Rows` (Speicher- und SQL-Store gleich; Registry um Prüf-, Vertrags- und Abrechnungstabellen erweitert, `memory_cascade` folgt den neuen ON-DELETE-Regeln). |
| API | `backend/routers/invoice_review.py`: `GET /invoice-review/inbox` (Filter `status` = legacy/received/query/approved/partially_approved/rejected/pending/dispute, `due` = overdue/week/month, `skonto`, `property_id`, `q`; Filter vor der Seitenbildung, `total` zählt alle Treffer), `GET /invoice-review/payment-proposals`, `GET /invoice-review/duplicates`, `GET/PUT /invoice-review/settings`, `POST /invoice-review/receipts`; je Rechnung `GET/POST/PATCH /invoices/{id}/review`, `POST …/factual-check`, `…/arithmetic-check`, `…/decision`, `…/dispute`, `…/cost-transfer`. Zahlungen weiter über `/invoices/{id}/payments`. Alle Handler synchron (Threadpool), keine Datenbankarbeit auf der Eventschleife. |
| Anschlüsse | `maintenance_projects._costs` (zählender Betrag), `link_invoice` und `add_invoice_payment` (abgelehnte Rechnung/Gutschrift abgewiesen); `service_contracts._bills(reviewed=True)` für Abgleich und Übernahme, `add_bill` (abgelehnt/Gutschrift abgewiesen), Rechnungsliste mit `review`; `routers/invoices.py` (Löschen/Ändern nach Entscheidung), `routers/admin.py` (Massenlöschung, DSGVO). |
| Rechte | `INVOICE_FACTUAL` in `permissions.py`: Technik darf nur `…/review/factual-check`, Buchhaltung genau das nicht; `/invoice-review/receipts` gehört zur Buchhaltung; Einstellungen nur Eigentümer/Verwaltung. Rollenabhängige Regeln (Grenze, Technik nur für Auftragsrechnungen) im Dienst. |
| Portfolio-Grenze | über die Fremdschlüssel zur Rechnung (→ Objekt → Portfolio); `invoice_review_settings` ist `GLOBAL_READ` (alle lesen, nur Konten mit vollem Zugriff ändern). |
| Snapshot | Die vier Tabellen sind Felder des Speicher-Stores und damit in Export/Import/Wiederherstellung. **Snapshot-Format 5** (ältere Programme lehnen die Datei ab, statt Prüfungen still zu verwerfen). |
| DSGVO | Die Auskunft eines Mieters enthält Prüfungen (mit Verlauf), deren Beleg ein Dokument seiner Verträge ist. |
| Oberfläche | Finanzen → **Rechnungsprüfung** (`/invoice-review`, `/invoice-review/:id`): Eingang mit Suche und Filtern (Status, Fälligkeit, Skonto, Objekt), serverseitige Seiten; Reiter Zahlungsvorschläge mit Summe und Hinweis „keine Zahlungsdatei“; Erfassen neuer Rechnungen mit Belegupload und Live-Dublettenprüfung; Einstellungen. Prüfansicht: Beleg (PDF im vorhandenen PDF-Viewer, sonst Dateiansicht) **neben** Rechnung, Prüfhinweisen, sachlicher/rechnerischer Prüfung mit Steuerzeilen und § 14-Checkliste, Entscheidung, Zahlung (seitenweise Buchungsauswahl), Widerspruch/Gutschriften, Übernahme und unveränderlichem Verlauf; unter 1100 px einspaltig. Schaltflächen nach `abilities` des Servers. Texte de/en/es (`features/invoiceReview/text.js`, Navigationseintrag in `i18n/*.json`). |

## Nachweise

| Prüfung | Ergebnis |
| --- | --- |
| `backend/tests/test_invoice_review.py` (Speicher und SQLite) | 24 Tests je Store: Dublettenschlüssel, Steuer je Satz/Rundung/unbekannter Satz/fehlender Steuerbetrag, § 14-Checkliste mit Kleinbetrag, Abrechnung (Teilfreigabe, Gutschrift, nachträglich anerkannt, Skonto rechtzeitig/verspätet, überzahlt); Eingang mit Beleg-Prüfsumme und Manipulationserkennung, Dublette abgewiesen/mit Begründung, Verdacht als Hinweis, neue Rechnung + Eingang atomar; sachliche Prüfung gegen Auftrag + Nachtrag (über Auftrag 167 €, über Nachtrag 357 €) und Technik-/Buchhaltungsrechte; gegen Objektvertrag (Tarifabweichung 450 €, Zeitraumüberschneidung); rechnerische Prüfung mit Steuerzeilen und Beanstandung; Vier-Augen über der Grenze (Buchhaltung 403, Prüfer 409, zweite Verwaltung freigegeben); Rechte im Schreibvorgang (Rolle entzogen → 403); Teilfreigabe → Widerspruch → Gutschrift → Ausbuchung, Projektzahlen 990 € genau einmal, Vorschläge; Widerspruch per Teilanerkennung; Rückfrage und Ablehnung (Projektzahlen 0, Zahlung 409, Übernahme 409, Zuordnung 409); abgelehnte Vertragsrechnung nicht übernommen, Abgleich ohne sie; unveränderlicher Verlauf (API 409, Löschen/Massenlöschen abgewiesen, SQL-Trigger); Zahlungsstatus mit Skonto und Überzahlung; Eingangsfilter und Seiten; einmalige Übernahme in die Nebenkostenabrechnung; Bestandsrechnungen unverändert; Nur-Lesen und eingeschränktes Konto (Liste, 404, Vorschläge, Dubletten verborgen); Snapshot-Rundlauf; DSGVO-Auskunft; Migration auf/ab mit abgewiesenem Downgrade (SQLite). |
| `backend/tests/test_invoice_review_postgres.py` (PostgreSQL 16) | 4 Tests: Migration (Fremdschlüsselregeln, Trigger, RESTRICT, Downgrade abgewiesen – Revision bleibt –, danach möglich, erneutes Upgrade mit Trigger), Ablauf in Cent mit Skonto, vier gleichzeitige Entscheidungen → genau eine, vier gleichzeitige Übernahmen → genau eine Kostenposition, Verlaufsnummern lückenlos; Portfolio-Grenze im Dienst. |
| Angepasste Tests | `test_service_contracts.py` (Snapshot-Format ≥ 4), `test_dsgvo.py` (zwei neue Schlüssel der Auskunft), `ShellNavigation.test.jsx` (40 Navigationsziele). |
| Frontend | `frontend/src/test/InvoiceReview.test.jsx` (6 Tests): Eingang mit Status- und Zahlungsstand, Filter und Seiten an den Server, Zahlungsvorschläge ohne Bankaktion, Prüfansicht mit Beleg/Checkliste/Hinweisen/Vier-Augen/Verlauf, rechnerische Prüfung mit Checkliste und Begründungspflicht beim Ablehnen, Eingang einer Bestandsrechnung, Nur-Lesen, Textparität de/en/es. |
| Browser (Chromium headless, isolierte SQLite-Instanz, synthetische Daten nur über die HTTP-API angelegt) | 360 × 800 und 1440 × 960: Eingang, Prüfansicht mit PDF-Beleg (Canvas gerendert) neben den Prüfungen, teilfreigegebene Rechnung mit Widerspruch, Zahlungsvorschläge; kein seitliches Scrollen, keine Konsolenfehler. Gefunden und behoben: Skontobetrag vor der Freigabe als 0,00 € angezeigt (jetzt Prozentsatz), Checklistenhinweis bei 360 px zerrissen. |

Gesamtläufe: siehe Abschnitt „Gesamtläufe“.

## Bewusst offen

- **Beleg als archiviertes Original:** Der Beleg wird über seinen SHA-256 beim Eingang überwacht, nicht ins Dokumentversionsarchiv kopiert (das Archiv hat noch keinen Weg für gewöhnliche Uploads). Eine veränderte Datei wird erkannt, aber nicht wiederhergestellt.
- **OCR-Vorbelegung:** Die vorhandene OCR-Analyse füllt den Erfassungsdialog noch nicht automatisch.
- **Filter „unbezahlt“ im Eingang** (Fälligkeit, Skonto) vergleicht Zahlungen mit Freigabe bzw. Brutto abzüglich Skonto; Gutschriften und nachträgliche Anerkennungen berücksichtigt erst die Zeile selbst (sie zeigt den exakten Stand).
- **Zahlungen zu Objektverträgen** (`service_contract_payments`) zählen im Vertrag, nicht im Zahlungsstatus der Rechnung; dort zählen nur `invoice_payments`.
- **Skonto in der Nebenkostenabrechnung:** Übernommen wird der Betrag zum Zeitpunkt der Übernahme; ein später genutztes Skonto ändert die Kostenposition nicht.
- **Abgelehnt und freigegeben sind endgültig;** eine Wiederaufnahme (z. B. nach Irrtum) gibt es nicht, nur eine neue Rechnung/Gutschrift.
- **Dubletten über Portfoliogrenzen** sieht ein eingeschränktes Konto nicht; der Schlüssel greift dann nicht.
- **Lieferanten** sind Freitext der Rechnung, nicht Kontakte des Adressbuchs; die DSGVO-Auskunft für Lieferanten als Personen fehlt (Auskunft gibt es nur für Mieter).
- **Keine externen Aktionen:** keine Zahlungsdatei (SEPA), keine E-Mail an Lieferanten, keine Benachrichtigung vor Skonto-/Fälligkeitsfristen.
- **Änderungen an Rechnungen vor der Entscheidung** setzen bereits erfasste Prüfungen nicht zurück; die Prüfung zeigt „nach der rechnerischen Prüfung geändert“.

## Gesamtläufe

Linux, Python 3.11.15, PostgreSQL 16 lokal (`IMMO_TEST_POSTGRES_ADMIN_URL`), Node 22:

| Prüfung | Ergebnis (Ausgangsstand `7034701`) |
| --- | --- |
| Backend Speicher-Modus + PostgreSQL | MEM_RESULT |
| Backend SQL-Modus (`TEST_STORE_BACKEND=sql`) + PostgreSQL | SQL_RESULT |
| `ruff check backend`, `python -m mypy backend` | LINT_RESULT |
| Frontend `npx vitest run` | VITEST_RESULT |
| `npm run lint`, `npm run build` | sauber bzw. gebaut |
