# Instandhaltung: vom Schaden zur Projektakte

Stand 8.–11. Oktober 2026, Branch `claude/maintenance-projects` (auf `claude/dreamy-gauss-nmaxhn`, `27fe494`). Umsetzung des Pakets „P1 H: Schäden/Projekte“ aus Abschnitt 9 von `CLAUDE_HANDOFF_20261007.md`. Migration **`b6d4f1a8c2e7`** nach `f3b9c1d7e2a5` (beim Zusammenführen ggf. neu verketten).

## Regel

1. **Der vorhandene Instandhaltungsfall ist die Projektakte.** Es gibt keine zweite Entität „Projekt“. Alle neuen Tabellen hängen am Fall (`maintenance_cases`) und damit an Objekt/Einheit; die bisherige API `/maintenance` bleibt unverändert nutzbar.
2. **Statusablauf mit Verlauf:** Offen → In Bearbeitung → Erledigt; Abbruch und Wiederaufnahme mit Pflichtgrund. Jeder Statuswechsel – auch über das alte `PUT`/`PATCH` – wird in derselben Transaktion in `change_history` festgehalten (wer, wann, von → nach, Grund). Abschließen setzt voraus: alle Arbeitspakete erledigt oder entfallen, kein Protokollentwurf, kein unentschiedener Nachtrag, kein aktiver Auftrag. Abbrechen setzt voraus: kein aktiver Auftrag. Ein Fall ohne Projektdaten verhält sich wie bisher.
3. **Arbeitspakete und Abhängigkeiten ohne Kreise.** Abhängigkeit = Ende-Anfang (der Nachfolger beginnt, wenn der Vorgänger erledigt oder entfallen ist). Eine Abhängigkeit, die einen Kreis schließen würde – direkt oder über beliebig viele Zwischenschritte –, wird abgelehnt und nennt den Kreis: „Abhängigkeit abgelehnt: Sie würde einen Kreis bilden („Rinne“ → „Gerüst“ → „Dach“ → „Rinne“). Arbeitspakete dürfen nicht zirkulär voneinander abhängen.“ Keine Abhängigkeit über Aktengrenzen. Beginnen vor erledigtem Vorgänger, Wiederöffnen bei schon begonnenem Nachfolger und eine Abhängigkeit, die dem erreichten Stand widerspricht, werden abgelehnt. Planabweichungen (Nachfolger beginnt vor Ende des Vorgängers) werden als Hinweis gezeigt. Phasen sind ein Feld des Arbeitspakets, Meilensteine eine Art.
4. **Termine sind Kalendertermine.** Ein Termin der Akte ist ein normaler Eintrag in `calendar_events` (Objekt/Einheit der Akte) plus Verknüpfung; Löschen entfernt beide.
5. **Handwerker sind Kontakte des gemeinsamen Adressbuchs.** Zuordnung mit Rolle und Gewerk; ein beauftragtes Angebot ordnet seinen Kontakt automatisch zu.
6. **Angebot → Auftrag → Nachtrag → Rechnung → Zahlung, keine zweite Kostenbuchhaltung.**
   - Ein Auftrag entsteht nur durch Beauftragung eines Angebots (genau ein Auftrag je Angebot), Beträge eingefroren; konkurrierende Angebote desselben Arbeitspakets können dabei abgelehnt werden. Ein offener Fall geht dabei in Bearbeitung.
   - Nachträge (auch Minderungen, negativ) zählen erst nach Genehmigung.
   - Rechnungen sind die **vorhandenen Rechnungen** (`invoices`), neu erfasst aus der Akte oder zugeordnet; jede Rechnung höchstens einem Auftrag (eindeutig), nur vom Objekt der Akte, nicht storniert.
   - Bezahlt wird über **Buchungen**: `invoice_payments` ordnet eine Ausgabenbuchung (negativ, kein Storno) einer Rechnung zu. Je Buchung höchstens ihr Betrag abzüglich Stornos und anderer Zuordnungen, je Rechnung höchstens ihr Bruttobetrag.
   - Budget (das bisherige `estimated_cost`), beauftragt, abgerechnet, bezahlt, noch abzurechnen/zu zahlen und Restbudget werden **abgeleitet** (`backend/domain/project_costs.py`), in Cent (`domain/money.py`). Ein später storniertes Zahlungsbuchung zählt nicht mehr; eine Buchung, die mehrere Rechnungen/Akten bezahlt, wird insgesamt nur einmal gezählt (Zuordnungen in ihrer Reihenfolge). Hinweise: Rechnung über Auftrag, Beauftragung/Rechnungen über Budget, Zahlung auf stornierte Rechnung, Rechnung „bezahlt“ markiert ohne Buchungsbeleg.
   - Rechnung eines Projektauftrags und Buchung mit Rechnungszuordnung werden nicht per Einzelklick gelöscht (409); ein Auftrag mit Rechnungen wird nicht storniert.
7. **Protokolle (Abnahme, Begehung, Ortstermin)** mit Ergebnis, Mängeln (Ort, Gewicht, Frist, Fotos) und Fotos der Akte. Abschließen erzeugt in **einer** Transaktion: PDF (mit eingebetteten, verkleinerten Fotos und ihrem SHA-256, Inhaltsprüfsumme), Dokument `maintenance_protocol`, **unveränderliches Original** im Dokumentversionsarchiv (`document_versions`, Manifest enthält den Protokollinhalt und seinen Hash) und Protokollzeile `final`. Danach: kein Ändern/Löschen (409), die Datenbank verweigert jedes UPDATE einer finalen Zeile (Trigger), die Akte mit finalem Protokoll ist nicht löschbar. Lesen prüft Zeile ↔ Original („Original geprüft“ / „Weicht vom archivierten Original ab“, PDF dann 503). Wiederholung mit gleichem Befehlsschlüssel liefert das gleiche Ergebnis. Eine Abnahme „abgenommen“/„mit Mängeln“ schließt ihren Auftrag ab.
8. **Rechte** (`backend/permissions.py`, im Schreibvorgang unter Kontosperre erneut geprüft):

   | Aktion | Eigentümer/Verwalter | Technik | Buchhaltung | Nur Lesen |
   | --- | --- | --- | --- | --- |
   | Akte, Status, Arbeitspakete, Abhängigkeiten, Termine, Handwerker | ja | ja | nein | nein |
   | Angebote erfassen, Nachträge vorschlagen | ja | ja | nein | nein |
   | Angebot beauftragen/ablehnen, Auftrag stornieren/abschließen, Nachtrag genehmigen/ablehnen | ja | **nein** | nein | nein |
   | Rechnungen dem Auftrag zuordnen/neu erfassen | ja | **nein** | ja | nein |
   | Zahlungen (Buchungen) Rechnungen zuordnen | ja | nein | ja | nein |
   | Protokolle schreiben und abschließen | ja | **ja** (vor Ort) | nein | nein |
   | Lesen der Akte | alle angemeldeten Konten innerhalb ihrer Portfolios | | | |

   Begründung: Die Technik arbeitet vor Ort (Arbeitsstand, Termine, Angebote einholen, Abnahme protokollieren), vergibt aber kein Geld; Vergabe und Nachtragsentscheidung bleiben bei Eigentümer/Verwaltung, Rechnungen und Zahlungen bei der Buchhaltung.
9. **Portfoliogrenze:** Sichtbarkeit folgt dem Fremdschlüssel zur Akte (→ Objekt → Portfolio), bei Zahlungen Rechnung und Buchung. Kontakte bleiben gemeinsames Adressbuch (Verweis ohne Fremdschlüssel, damit ein gemeinsamer Handwerker die Sichtbarkeit nicht bestimmt).

## Technik

| Ebene | Umsetzung |
| --- | --- |
| Schema | `backend/db/maintenance_project_models.py`: `maintenance_work_packages`, `maintenance_dependencies` (eindeutig, kein Selbstbezug), `maintenance_participants`, `maintenance_quotes`, `maintenance_orders` (eindeutig je Angebot), `maintenance_change_orders`, `maintenance_order_invoices` (eindeutig je Rechnung), `invoice_payments`, `maintenance_protocols` (Trigger gegen UPDATE finaler Zeilen; Check „final ⇒ Dokument und Hash“), `maintenance_appointments`, `maintenance_case_documents`. Geld `NUMERIC(12,2)`. Keine bestehende Tabelle geändert. |
| Migration | `b6d4f1a8c2e7_maintenance_projects.py`: geschützt (vorhandene Tabellen aus `create_all` werden übernommen, nur Trigger/Indizes ergänzt); Downgrade verweigert, solange eine Zeile existiert. Leere DB: `create_all` + Trigger + Stempel (`schema_state.initialise_empty`); bestehende DB nur über `python -m backend.upgrade`. |
| Domäne | `domain/project_graph.py` (Kreissuche per BFS ohne Rekursionsgrenze, topologische Reihenfolge, Planabweichungen), `domain/project_costs.py` (Kostenableitung in Cent). |
| Dienst | `services/maintenance_projects.py`: jede Änderung in einer Arbeitseinheit (eigene Session, SQLite `BEGIN IMMEDIATE`, PostgreSQL `FOR UPDATE` auf der Akte bzw. Buchung → Rechnung, Konto gesperrt und Rechte geprüft bis zum Commit, Portfolio-Zaun beim Commit). `services/maintenance_rows.py`: gleicher Zugriff auf SQL- und Speicher-Store (Speicher mit Undo). `services/memory_cascade.py`: ON-DELETE-Regeln im Speicher-Store. PDF: `maintenance_protocol_render.py`; Manifestprüfung: `maintenance_protocol_validation.py` (auch in `verify_document_versions`). |
| API | `routers/maintenance_projects.py` unter `/api/v1/maintenance/{id}/…`: `project`, `costs`, `transition`, `work-packages`, `dependencies`, `participants`, `appointments`, `quotes` (+`accept`/`reject`), `orders/{id}/cancel|complete|change-orders|invoices`, `change-orders/{id}/approve|reject`, `invoice-links`, `invoice-candidates` (seitenweise), `protocols` (+`finalize`, `pdf`), `documents`; `/api/v1/invoices/{id}/payments` (+`candidates`, seitenweise). Alle Handler synchron (Threadpool, keine DB-Arbeit auf der Eventschleife). Protokoll-PDF auch unter `/uploads/maintenance-protocols/<Dokument>.pdf`, immer aus dem geprüften Archiv. |
| Bestands-API | `routers/maintenance.py`: gleiche Pfade, Modelle und Statuscodes; Schreiben über den Dienst (Verlauf, Abschluss-Sperre nur bei Projektdaten). |
| Snapshot | Neue Tabellen sind Felder des Speicher-Stores und damit automatisch in Export/Import/Wiederherstellung (Referenzprüfung über Fremdschlüssel). |
| Oberfläche | `features/maintenanceProject/*`, Route `/maintenance/:id` (Titel in der Liste verlinkt): Kopf mit Status und Statusaktionen (gesperrt mit Begründung), Kennzahlen Budget/beauftragt/abgerechnet/bezahlt, Reiter Übersicht · Arbeitspakete & Abhängigkeiten · Termine · Angebote/Aufträge/Nachträge · Rechnungen & Kosten · Protokolle · Dokumente. Schaltflächen nach den Rechten der Rolle (`abilities` der Akte). Rechnungs- und Buchungsauswahl seitenweise mit Suche. Protokoll-PDF über die Sitzung (Blob) im vorhandenen PDF-Viewer. Texte de/en/es (`text.js`). |

## Nachweise

- Backend, neue Tests: `test_maintenance_projects.py` (18, Speicher und SQLite): Kreise direkt/indirekt/lang (2000er-Kette), Abhängigkeitsregeln, Planabweichung, Angebot→Auftrag→Nachtrag→Rechnung→Zahlung mit Kostenabgleich gegen Rechnungen/Buchungen inkl. Storno, eine Buchung für zwei Akten einmal gezählt, Statusablauf/Verlauf, Kompatibilität der Bestands-API, Protokoll-Unveränderlichkeit (API 409, SQL-Trigger, Abweichungserkennung), Rechtematrix Technik/Buchhaltung/Nur-Lesen, Rechteprüfung im Schreibvorgang, eingeschränktes Konto, Snapshot-Export/-Import, seitenweise Auswahl. `test_migrations.py` +2 (Upgrade/Downgrade-Verweigerung/Downgrade/erneutes Upgrade, `create_all`-Übernahme mit Trigger). `test_maintenance_projects_postgres.py` (4, echtes PostgreSQL 16): Migration rund, Ablauf in Cent mit Archiv-Prüfung `verify_document_versions`, Trigger, parallele Gegenabhängigkeiten A→B/B→A (genau eine gewinnt, 3 Runden), parallele Überzuordnung einer Buchung, eingeschränkte Schreibvorgänge mit Zeilensperren.
- Gesamtläufe: siehe Abschlussbericht im CHANGELOG/Commit (Speicher und SQL, jeweils mit `IMMO_TEST_POSTGRES_ADMIN_URL`), `ruff check backend`, `mypy` 2.4.0 ohne Befund.
- Frontend: `MaintenanceProject.test.jsx` (7): Reiter/Kennzahlen/Sperren, Kreismeldung im Dialog, Technikrechte, Nur-Lesen, Protokollabschluss mit gleichem Befehlsschlüssel nach verlorener Antwort, Zahlungszuordnung über seitenweise Auswahl, Textparität de/en/es. Gesamtlauf 267/267 (48 Dateien), ESLint und Build ohne Fehler.
- Echter Browser (Chromium headless, synthetische Daten, isolierte SQLite-Instanz): alle 7 Reiter bei 360 × 780 und 1280 × 900 ohne horizontalen Überlauf, keine Konsolenfehler; Kreisablehnung über HTTP 409 mit Pfadangabe; archiviertes PDF über `/uploads/maintenance-protocols/…` 200 und visuell geprüft (Angaben, Foto mit Hash, Inhaltsprüfsumme, Unterschriftszeilen).

## Bewusst offen

- Rechnungsstatus (`open`/`paid`) wird nicht automatisch aus Zahlungszuordnungen gesetzt; die Akte zeigt Abweichungen als Hinweis. Eine allgemeine Rechnungsprüfung außerhalb der Akte (P1/P2 D/K) nutzt `invoice_payments` noch nicht.
- Änderungen an Rechnung/Buchung nach der Zuordnung (Objektwechsel, Betrag kleiner) werden nicht gesperrt, sondern in der Ableitung gedeckelt und als Hinweis gezeigt.
- Kein Gantt/kritischer Pfad, keine Kapazitätsplanung, keine Mängelverfolgung als eigene Objekte (Mängel stehen im Protokoll; Nacharbeit als neues Arbeitspaket).
- Löschen einer finalen Protokollzeile verhindert die Anwendung, nicht die Datenbank (sonst wären Wiederherstellung/Testbereinigung blockiert); das PDF-Original selbst ist datenbankseitig gegen Ändern und Löschen geschützt.
- Fotos werden in das PDF eingebettet (max. 24 je Protokoll, 1400 px); die Fotodateien selbst sind keine archivierten Originale.
- Benachrichtigungen (z. B. Fristen von Mängeln, Bindefrist von Angeboten) und E-Mail-Versand an Handwerker sind nicht angebunden.
- Kontakte ohne Fremdschlüssel: ein gelöschter Kontakt erscheint als „Kontakt gelöscht“; Angebote/Aufträge behalten den Anbieternamen.
