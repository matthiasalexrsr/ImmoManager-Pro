# Betriebskostenabrechnung: Regression P1 C (08.10.2026)

Paket „P1 C: Verbrauch/Abrechnung“ aus `CLAUDE_HANDOFF_20261007.md` §9. Geprüft wurde der aktuelle
Zweig (`claude/dreamy-gauss-nmaxhn`, 8578a66) mit seinen eigenen Nutzungszeitraum-/Miethistorien-
Änderungen; die historischen Zweige der anderen Maschine standen nicht zur Verfügung, alte Befunde
wurden deshalb nicht übernommen, sondern jede Zeile zuerst mit einem Test gegen den Ist-Stand geprüft
(Prüfskript-Ergebnis „vorher“), erst danach geändert.

Arbeitszweig `claude/billing-regression`, Migration `c3e8a1f5d9b7` (nach `b8e3d5f7a2c4`, additiv).

## Ergebnis in Kürze

- **Bereits korrekt:** Medium je Schlüssel (`meter_type`), Blocker bei gemischten Zählerarten ohne
  Zählerart, Mieterwechsel/Leerstand tagesgenau inkl. Schaltjahr, Teilmonate bei Ein-/Auszug,
  Leerstand als eigene Partei bei Flächen-, Einheiten-, Personen- und Verbrauchsschlüsseln,
  Größte-Reste-Rundung, Verweigerung veralteter Abrechnungen beim Finalisieren, Leipzig/Köln-Werte.
- **Fehler bzw. fehlende Teile:** Maßeinheiten, Zählerwechsel, datierte Bewohner, Vorauszahlungs-
  änderung mitten im Monat, Widerspruch (Grund verworfen, Periode danach änderbar), Korrekturablauf,
  Statuswechsel per PUT/PATCH, PDF aus Live-Stammdaten, Snapshot-Import, Store-Ebene,
  Löschen eines Verteilerschlüssels mit Kosten finalisierter Perioden.

## Regressionsmatrix

Testdatei: `backend/tests/test_billing_regression.py` (Speicher- und SQL-Modus), PostgreSQL:
`backend/tests/test_billing_regression_postgres.py`. Alle Erwartungswerte sind von Hand gerechnet
und stehen als Kommentar am Test.

| # | Thema | vorher | Befund | Änderung | Test |
| --- | --- | --- | --- | --- | --- |
| A1 | Medium: Schlüssel mit Zählerart zählt nur diese Zähler | Kaltwasser 30/10 m³ → 300/100 €, Warmwasser ignoriert | korrekt | Zeile zeigt jetzt die Einheit (m³) | `test_a1_a_key_counts_only_its_own_medium` |
| A2 | Medium: Schlüssel ohne Zählerart, mehrere Arten | Blocker `CONSUMPTION_METER_TYPE_REQUIRED` | korrekt | – | `test_consumption_keys_do_not_mix_meter_types` (bestehend) |
| A3 | Maßeinheit: kWh und MWh in einem Heizungsschlüssel | kein Feld für die Einheit; 1.000 kWh + 3 MWh als 1.000 : 3 → 797,61 € / 2,39 € | **Fehler** | `meters.measure_unit`, `allocation_keys.measure_unit`; ohne Schlüsseleinheit Blocker `CONSUMPTION_UNIT_MISMATCH`, mit Schlüsseleinheit exakte Umrechnung (MWh→kWh ×1000) und Warnung `CONSUMPTION_UNIT_CONVERTED` → 200 € / 600 € | `test_a2_kwh_and_mwh_are_converted_only_when_the_key_names_its_unit` |
| A4 | Maßeinheit ohne exakten Faktor (HKV↔kWh, Gas m³↔kWh) | würde addiert | **Fehler** | verweigert mit Klartext (Brennwert/Zustandszahl, HKV sind keine kWh) | `test_a3_units_without_an_exact_factor_are_refused` |
| A5 | Einheit passt nicht zur Zählerart; Heizung teils ohne Einheit | nicht geprüft | **fehlte** | Blocker `CONSUMPTION_UNIT_INVALID`; Heizung/Gas ohne Angabe gelten nicht stillschweigend als kWh („ohne Angabe“) | `test_a4_unit_must_fit_the_medium_and_be_known` |
| B1 | Zählerwechsel: alter Zähler deaktiviert, neuer ab 15.06. | alter Zähler ignoriert, neuer ohne Stand am 01.01. → Blocker, keine Abrechnung möglich | **Fehler** | `meters.removal_date`; je Zähler zählt der Dienstzeitraum (Einbau…Ausbau): Endstand alt + Anfangsstand neu, (160−100)+(40−0)=100 m³ → 500/500 € | `test_b1_replacement_adds_final_and_initial_reading` |
| B2 | Zählerwechsel und Mieterwechsel im selben Jahr | Blocker | **Fehler** (wie B1) | A 20+15=35 m³, B 30 m³, C 35 m³ → 350/300/350 € | `test_b2_replacement_and_tenant_change_in_one_year` |
| B3 | Zähler auf demselben Datensatz zurückgesetzt (Sprung 160→40) | Blocker `INVALID_CONSUMPTION` (Summe je Einheit) | korrekt, kein negativer Anteil | Prüfung jetzt je Zähler (zwei Zähler einer Einheit konnten sich vorher gegenseitig verdecken), Meldung nennt Zähler und Ausweg | `test_b3_reset_on_the_same_meter_is_never_a_negative_share` |
| B4 | Deaktivierter Zähler ohne Ausbaudatum, aber mit Ablesungen im Zeitraum | still ignoriert → 60 m³ verschwinden | **Fehler** | Blocker `METER_REMOVAL_DATE_MISSING`; Ausbau vor Einbau wird abgewiesen | `test_b4_a_deactivated_meter_needs_its_removal_date` |
| C1 | Datierte Bewohner: 2 → 3 Personen ab 01.07. | nur `contracts.persons` konstant → 500/500 € | **fehlte** | Tabelle `contract_occupancies` (gültig ab, Personen); Personenschlüssel nach Personentagen: 2×181+3×184=914 zu 730 → 555,96 / 444,04 €; Abschnitte in der Zeile und im PDF | `test_c1_person_key_counts_person_days` |
| C2 | Stand vor der Periode, später 0 Personen | – | fehlte | 1×273+0×92 = 273 zu 365 → 273 / 365 € | `test_c2_occupancy_from_before_the_period_and_down_to_zero` |
| C3 | Bewohnerstand vor Beginn/nach Ende/doppelt | – | fehlte | 400 mit Klartext; Pfad/Vertrag müssen passen | `test_c3_occupancies_stay_within_the_contract` |
| D1 | Echte Abschnitte: Mieterwechsel, Leerstand, Schaltjahr | 60/31/275/366 Tage → 360/186/1.650/1.464 €, Vorauszahlung 200/900 € | korrekt | – | `test_d1_leap_year_days_are_inclusive` |
| D2 | Vorauszahlungsänderung am 16.04. | April mit dem Wert vom 01.04. → 3.000 € | **Fehler** | Abschnitte an jeder Änderung der Miethistorie, Teilmonat nach Tagen: 525 € + 2.550 € = 3.075 €; `advance_sections` in Abrechnung und PDF | `test_d2_an_advance_change_mid_month_splits_the_month_by_days` |
| D3 | Mieter- und Personenwechsel in einer Einheit | Personenwechsel fehlte | fehlte | A 151, B 2×92+4×122=672, C 730 Personentage → 151/672/730 € | `test_d3_tenant_and_person_changes_are_sections_of_their_own` |
| D4 | Teilmonate bei Ein- und Auszug | 70 + 1.120 + 46,67 = 1.236,67 €, 269 Tage | korrekt | – | `test_d4_partial_months_at_move_in_and_move_out` |
| E1 | Leerstand bei Flächen/Einheiten/Personen | Köln-Referenz | korrekt | – | `test_koeln_vacancy_stays_with_the_landlord` (bestehend) |
| E2 | Leerstand beim Verbrauchsschlüssel | 5 von 20 m³ → 50 € Eigentümer, keine Forderung | korrekt | – | `test_e1_vacancy_carries_its_consumption_and_is_never_billed` |
| E3 | Leerstand mit Zählerwechsel während des Leerstands | Blocker (wie B1) | **Fehler** (Folge von B1) | Leerstand (32−30)+(1−0)=3 m³ → 30 € | `test_e2_vacancy_between_tenants_with_a_meter_replaced_while_empty` |
| F1 | Widerspruch erfassen | Grund wurde verworfen, nur Status `disputed` | **Fehler** | Tabelle `billing_objections` (Eingang, Grund, Einzelabrechnung, Stand, Korrektur); `POST /billing/periods/{id}/objections`, `/dispute` speichert den Grund, `GET /billing/objections` | `test_f1_…`, `test_f3_…` |
| F2 | Periode nach Widerspruch | `disputed` galt als änderbar: neu erzeugen, Kosten ändern, Periode löschen, Zeilen patchen | **Fehler** | alle Status ab Finalisierung unveränderlich (409) | `test_f1_an_objection_is_recorded_and_the_issued_version_stays` |
| F3 | Korrekturablauf („Korrektur starten“) | auch aus Entwurf, ohne Bezug zur Fassung, Revisionsnummer nicht an den Zeilen, Original nie „corrected“, Forderungen doppelt | **Fehler** | neue Periode mit `corrects_period_id`, `revision`, `revision_notes`; offene Widersprüche → „in Korrektur“; Finalisieren der Korrektur setzt Original auf `corrected` und Widersprüche auf „erledigt“; Forderungen der Korrektur nur als Differenz (−120 € / −80 €); höchstens eine offene Korrektur je Fassung | `test_f2_a_correction_is_a_new_version_and_bills_only_the_difference` |
| G1 | Finalisierte/zugestellte/widersprochene Fassung ändern | finalized geschützt, disputed nicht | teils **Fehler** | einheitlich 409 für Erzeugen, Periode, Kosten, Zeilen | `test_g1_an_issued_period_refuses_every_change[*]` |
| G2 | Status per PUT/PATCH/POST | PATCH `finalized` ohne Zeilen/Prüfung/Hash; `disputed`→`draft` | **Fehler** | Status nur über Arbeitsschritte; PUT behält Status/Revision; UI-Formular ohne Statusfeld | `test_g2_…`, `test_crud_routers` |
| G3 | PDF/Dokument nach Stammdatenänderung | Mieter/Objekt/Vertrag live aufgelöst; PDF-Bytes bei jedem Abruf anders | **Fehler** | beim Finalisieren eingefrorenes `final_document` (Hash deckt es ab), PDF `invariant`: byte-gleich | `test_g3_the_issued_document_and_pdf_survive_later_edits` |
| G4 | Änderung an der Store-Ebene | `_patch_entity`/Löschen änderte finalisierte Zeilen | **Fehler** | beide Stores verweigern Inhaltsänderungen (nur Zustellfelder) | `test_g4_the_store_refuses_to_change_an_issued_statement` |
| G5 | Snapshot-Import | manipulierte finalisierte Zeile akzeptiert; Merge fügte Zeilen/Kosten hinzu | **Fehler** | Hashprüfung je betroffener Periode; Merge in finalisierte Periode verweigert | `test_g5_a_snapshot_cannot_change_an_issued_version` |
| G6 | Verteilerschlüssel löschen | Kostenpositionen (auch finalisierter Perioden) kaskadierend gelöscht | **Fehler** | 409, solange Kosten den Schlüssel nutzen | `test_g6_a_key_with_costs_is_not_deleted_with_them` |
| G7 | Abweichung heutiger Daten von der Fassung | nicht sichtbar | fehlte | Preflight: `FINAL_VERSION_DIFFERS` (Warnung), `FINAL_VERSION_ALTERED` (Blocker), Kennzahl `final_version_intact` | `test_g3_…`, `test_f1_…` |

## Änderungen im Einzelnen

- `services/utility_billing.py`: Maßeinheiten (Normalisierung, exakte Faktoren, Einheit je Medium,
  Standard nur für Wasser m³ und Strom kWh), Dienstzeitraum je Zähler, Personentage mit Abschnitten,
  Vorauszahlungsabschnitte, Rechnungen über `CachedReads` (Miethistorie einmal gelesen).
- `services/final_statements.py` (neu): Hash über die Fassung (für alte Zeilen unverändert,
  für neue inkl. Nutzungszeitraum, Abschnitte, Revision und eingefrorenem Dokument), Prüfung.
- `routers/billing.py`: unveränderliche Status, Statusschutz, Finalisieren mit eingefrorenem Dokument,
  Widersprüche, Korrekturen, Differenzforderungen, PDF aus der Fassung.
- `routers/contracts.py`: `GET/POST /contracts/{id}/occupancies`, `DELETE …/{occupancy_id}`.
- Stores (`storage.py`, `repositories/*`): neue Tabellen, Schutz finalisierter Zeilen, Kaskaden.
- `services/data_snapshot.py`: Prüfung finalisierter Fassungen beim Import.
- `routers/admin.py`: DSGVO-Auskunft enthält Widersprüche und Bewohnerstände.
- Frontend: Bewohner-Dialog am Vertrag, Maßeinheit/Ausbaudatum am Zähler, Abrechnungseinheit am
  Schlüssel, Widerspruchsliste und Korrekturhinweis in der Abrechnung, „Korrektur starten“ und
  „Widerspruch“ nur an finalisierten Fassungen, kein Statusfeld mehr im Periodenformular;
  i18n de/en/es; Vitest `OccupancyDialog.test.jsx`, `Statements.test.jsx`.
- Migration `c3e8a1f5d9b7`: additiv und gegen create_all-Datenbanken abgesichert; Downgrade wird
  verweigert, solange neue Daten (Widersprüche, Bewohner, eingefrorene Fassungen, Korrekturen,
  Zählerwechsel/Einheiten) existieren.

Portfolio-Grenze: unverändert; die neuen Tabellen hängen über Fremdschlüssel an Vertrag bzw.
Abrechnungsperiode und werden dadurch automatisch gefiltert (PostgreSQL-Test). Alle neuen Endpunkte
sind synchron (Threadpool), keine Datenbankarbeit auf der Event-Loop.

## Prüfungen

| Prüfung | Ergebnis |
| --- | --- |
| `python -m pytest backend/tests -q` (Speicher) | 1.449 bestanden, 24 übersprungen (vorher 1.418 / 21; +3 PostgreSQL-Tests ohne Server übersprungen) |
| `TEST_STORE_BACKEND=sql python -m pytest backend/tests -q` | 1.448 bestanden, 25 übersprungen (vorher 1.417 / 22) |
| PostgreSQL 16 (`IMMO_TEST_POSTGRES_ADMIN_URL`, alle PG-Tests inkl. Geld-Migration mit Downgrade durch die neue Revision und `test_billing_regression_postgres.py`) | 15 bestanden |
| `ruff check backend`, `python -m mypy backend` (2.4.0) | sauber |
| `npx vitest run`, `npm run lint` | 252 bestanden (45 Dateien), sauber |

## Offene Grenzen

- Vor dieser Änderung finalisierte Zeilen haben kein eingefrorenes Dokument: ihr PDF zeigt weiterhin
  heutige Namen; ihr Hash (Altformat) deckt Beträge und Zeilen, nicht die Namen.
- Snapshot-Dateien, deren finalisierte Zeilen schon vorher (alte Regeln, z. B. Patch im Status
  `disputed`) vom Hash abweichen, werden beim Import abgewiesen; die Meldung nennt die Periode.
- Korrekturforderungen verrechnen nur die Forderungen der korrigierten Fassungen (Differenz);
  Zahlungen, Storno und Ausgleich bleiben Paket P1 D.
- Ein zurückgewiesener Widerspruch ist nicht modelliert; ein Widerspruch endet nur über eine
  Korrektur, die Periode bleibt bis dahin `disputed`.
- Umrechnung nur mit exaktem Faktor; Gas m³→kWh (Brennwert, Zustandszahl) und Bewertungsfaktoren
  von Heizkostenverteilern (HeizkostenV) sind nicht modelliert und werden verweigert.
- Lücken zwischen Ausbau und Einbau (ungemessene Tage) werden nicht erkannt; mehrere parallele
  Zähler derselben Art in einer Einheit bleiben erlaubt. Ablesetoleranz unverändert ±7 Tage.
- DSGVO-Anonymisierung ändert eingefrorene Abrechnungen nicht (Aufbewahrungspflicht).
- Bewohnerstände lassen sich anlegen und löschen, nicht bearbeiten.
- Das Zählerformular (PUT) setzt `is_active` weiterhin auf aktiv zurück (Altverhalten); für den
  Zählerwechsel maßgeblich ist das Ausbaudatum.
- Kein echter Browserlauf; UI über Vitest geprüft.
