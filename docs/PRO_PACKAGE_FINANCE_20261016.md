# Finanzpakete 1–3 – Entwicklungsübergabe vom 16.10.2026

Arbeitsordner ausschließlich `pro-finish-finance-20261016`, Zweig `pro/finish-finance-20261016`, Ausgang `c16e097003c872972074e403a94d15d63cfb4b59`. Keine Commits, Pushes, Migrationen fremder Daten, Live-Aufrufe oder Anbieteraktionen. Änderungen liegen zur Prüfung im Arbeitsbaum. Dies ist eine Entwicklungsübergabe, keine unabhängige Integrations-/Releasefreigabe.

## Fachlicher Vertrag und Bedienung

- Auf dem Dashboard öffnet **Finanzplanung und Leistungsperioden** den deutschen Berichtsarbeitsplatz. Leistungsperiodenergebnis v2, 3/6/12 Monate Liquidität einschließlich Restmonat, Stichtag, Objekt, Zahlungstag, Ausfallquote, Rückstandsannahme, Leerstand und zusätzliche geplante Zahlungen. Basis und Szenario werden getrennt gerechnet. Speichern erzeugt eine unveränderliche private Definitionsfassung. Erneutes Öffnen berechnet mit aktuellen berechtigten Quellen. JSON/CSV/PDF verwenden dieselbe versionierte Definition; ein Ergebnishash verhindert den unbemerkten Export anderer Zahlen nach Quellenänderung.
- Die Forderungstabelle zeigt **Belegbarer Rest** und **Rest / Ausgleich**. Dort stehen datierte Belege, Quellverweise, Stichtagswahl und begründete Zuordnung einer vorhandenen Zahlung oder eines vorhandenen Guthabens. Eine Zuordnung kann datiert und begründet zurückgenommen werden. Rollen ohne Schreibrecht können den Rest lesen.
- Rechnungen besitzen optionale **Leistung von/bis**. Beide Daten sind gemeinsam erforderlich; entschiedene Rechnungsprüfungen schützen sie wie die übrigen Rechnungsfakten. Quellen öffnen bestehende Rechnungsprüfung, Vertragsliste, Buchungsdetail, Kautionsakte oder Abrechnungsperiode.

### Kanonischer Forderungsrest

`backend/services/receivable_residuals.py` ist der gemeinsame Leservertrag für gespeicherte Forderungen. `receivable_settlements` enthält ausschließlich Zuordnungs-/Rücknahmeverweise auf vorhandene `bookings` oder negative vorhandene `receivables`. Es werden weder Zahlungen erfunden noch eine zweite Kasse oder ein unabhängiges Buchungsjournal aufgebaut. Mietzuordnungen bleiben in `payment_allocations`; ihr automatisch zugeordneter Betrag erhält nur den verbleibenden Anteil derselben Buchung.

Abgeschlossene Kautionsausgleiche werden direkt aus `deposit_settlements`/`deposit_settlement_items` gelesen. Entwürfe zahlen nichts. Ausgleich 100 − Zahlung 40 − Kaution 20 = Rest 40 wird in Forderungsalter, Zusammenfassung, Mahnakte, Kautionsvorschlägen und Forderungsoberfläche aus demselben Vertrag abgeleitet. Eine spätere vollständige Rücklastschrift der 40 stellt den Rest auf 80; frühere Stichtage bleiben 40.

Die zeitliche Auswertung je Buchung trennt Zahlungsausgleich, spätere Teilrücklastschrift und spätere Rücknahme. Bei einer gemischten Zahlung 100 mit Mietanteil 60/Forderungsanteil 40 gibt eine Rücklastschrift 40 entsprechend 24/16 zurück. Eine anschließende Zuordnung verwendet nur tatsächlich verbliebenes Geld. Guthabenverrechnung und deren Rücknahme verändern beide Forderungsreste; sie erzeugen keine Bankbewegung.

Alte `partial`-Zeilen ohne belegbaren Teilbetrag bleiben unverändert. `unresolved_legacy=true` macht die fehlende Deutung sichtbar; der ursprüngliche Betrag bleibt als obere bekannte Forderungsgröße erhalten. Diese Unsicherheit wird weder als Zahlung noch als sichere Mahnforderung oder prognostizierter Eingang behandelt. Undatierte alte Abschlussstatus erhalten `undated_legacy_closed`; es wird kein historischer Zahlungszeitpunkt erfunden. Eine automatische Rekonstruktion solcher Altzahlungen gibt es ausdrücklich nicht.

### Leistungsperiodenergebnis v2

Separater Versionsname `performance-period-v2`, keine Umdefinition von `/reports/period-result`, `/reports/cashflow` oder der bisherigen statistischen Prognose. Ganze Kalendermonate; Tages-Teilzeiträume werden mit 422 abgelehnt. Basis: Sollwarmmiete einschließlich vereinbarter Vorauszahlungen; die letzte finalisierte Nebenkostenabrechnungsdifferenz korrigiert diese Vorauszahlungen im Leistungszeitraum. Eine finalisierte Korrektur ersetzt ihre Vorgängerfassung im Ergebnis; Originale werden nicht verändert.

Rechnungsaufwand verwendet den ausdrücklichen Leistungszeitraum, sonst den bereits gespeicherten Objektvertrags-Leistungszeitraum. Fehlen beide, wird das Rechnungsdatum mit sichtbarem Hinweis verwendet. Monatsanteile werden mit Dezimal-/Centverteilung tagesgewichtet aufgeteilt. Freigaben/Gutschriften werden aus der bestehenden Rechnungsprüfung übernommen. Dieselbe Rechnung wird durch Projekt-/Objektvertragsverknüpfung und Zahlung nicht mehrfach zum Aufwand. Projektorte und gewichtete Objektvertragsstandorte bestimmen Objekt-/Einheitsanteile. Nicht mit einem Leistungsbeleg verknüpfte sonstige Bankbewegungen bleiben ausdrücklich gekennzeichnete Buchungsdatum-Quellen.

Manuelle allgemeine Forderungen werden nicht ungeprüft als zusätzliche Mieterträge zum Miet-Soll addiert: sie können bereits enthaltene Mieten duplizieren. Ihr Rest ist dennoch vollständig im kanonischen Ausgleichsvertrag enthalten. Eigenständige, nicht belegverknüpfte Kostenpositionen einer Betriebskostenabrechnung werden nicht zusätzlich zu Rechnung/Bankbewegung als zweiter Aufwand addiert. Eine automatische Leistungsidentifikation anhand gleicher Texte/Beträge findet nicht statt.

### Liquidität v2

Stichtag bedeutet Tagesende; tatsächliche Buchungen bis einschließlich Stichtag sind im Anfangssaldo enthalten. Der erste Monatsabschnitt beginnt am Folgetag, danach folgen insgesamt 3/6/12 Kalendermonate einschließlich Restmonat. Bekannte Mietverläufe, noch offene geplante Mietanpassungen, Vertragsende, bereits bezahlte Miete, Zahlungstag, Ausfall-/Leerstandsannahmen und ausdrücklich angenommene Rückstandseinzüge werden berücksichtigt. Fällige Rechnungsreste, tarifliche Objektvertragsabschläge und zukünftige Buchungen ergänzen die Quellen. Eine konkrete reguläre Objektvertragsrechnung ersetzt die entsprechende Tarifannahme; Teilzahlungen kürzen nur ihren Anteil der Erwartung. Zusätzliche Szenarioflüsse haben eine eigene eindeutige Identität.

Verschiedene Währungen werden nicht umgerechnet oder zusammengezählt: gemischte Auswahl wird abgewiesen, eine einzelne Währung bleibt explizit erhalten. Eine Zahlung mit anderer Währung als die Forderung wird nicht zugeordnet. Projektaufträge ohne gespeicherten finanziellen Zahlungstermin werden nicht in ein erfundenes Fälligkeitsdatum verwandelt; solche Zusatzpläne müssen ausdrücklich erfasst werden.

## Öffentliche Anschlussstellen für Bank-/Steuer-/Importpakete

- `residual(store, receivable, as_of)` → Centbeträge als Dezimalstrings, Währung, Stichtag, Revision, Altbestandskennzeichen, datierte Evidenz mit Quelllink und Zuordnungen. `ResidualReader` gruppiert einen Berichtsgraphen innerhalb einer Berechnung; kein benutzerübergreifender Cache.
- `dated_evidence(store, contract_id)` → stabile `(receivable_id, date, Decimal amount, kind, source_id)`-Zeilen, einschließlich Kaution, Guthaben, Rücklastschrift und Rücknahme. Zahlungsempfang wird dadurch nicht nochmals gebucht.
- `allocate(store, receivable_id, SettlementCommand, actor_id)` und `reverse(...)` sind die atomaren Schreibhooks. Immer vorhandene Buchungs-/Forderungs-ID verwenden. Für HTTP-Aufrufer immer den aktuellen Actor mitgeben. Ein Import darf erst die vorhandene Buchung erzeugen und anschließend ausdrücklich deren Zuordnung beauftragen; keine erfundene Zahlung für einen alten Partialstatus.
- `cash_reserved(store, booking_ids)` liefert beanspruchte Anteile der Original- **und** Stornobuchungen; Miet-/Lieferantenzuordnungen müssen dieses gemeinsame Budget erhalten. `booking_payment_capacity(..., as_of=...)` ergänzt die bestehende Lieferantenkapazität um datierte und bereits anderweitig reservierte Anteile.
- `finance_reports.compute(store, ReportDefinition)` liefert Version, vollständige Definition, Definitions-/Ergebnishash, Währung, angewandte Grenzen, Monate und Quellen. Für Steuerabfluss weiterhin die vorhandenen Cashquellen verwenden; ein Leistungsperiodenergebnis ist kein steuerlicher Zahlungsnachweis.
- `snapshot_problems(plan, existing)` prüft die vollständige resultierende Importstruktur auf passende Eltern, doppelte/ungültige Rücknahmen und Betragsbudgets. Der vorhandene Snapshotimport ruft diesen zusätzlichen Validator auf; sein übriger Ablauf wurde nicht ersetzt.

Additive API unter `/api/v1`: `GET|POST /reports/v2/preview` (GET für lesende Rollen; GET-Parameter `definition` ist die JSON-Definition), `POST|GET /reports/v2/saved`, `GET /reports/v2/saved/{id}`; Ausgabeparameter `format=json|csv|pdf`, optional `expected_result_hash` bei Vorschau/Export. Ferner `GET /receivables/{id}/residual?as_of=...`, `POST /receivables/{id}/settlements`, `POST /receivables/{id}/settlements/{settlement_id}/reverse`. Bestehende Zusammenfassung/Forderungsalter akzeptieren zusätzlich `as_of`.

## Transaktion, Rechte, Originalschutz, Wiederanlauf

Die neuen Schreibbefehle verwenden die vorhandene Unit of Work (`maintenance_projects.work` / Archivtransaktion): SQLite-Writetransaktion bzw. PostgreSQL-Eltern-/Quellzeilensperren, vorhandene Konto-/Rollenprüfung und Commit-Fence; in Memory derselbe Archivlock und Undo-Journal. Gemeinsame Elternreihenfolge wie die Kautionsakte. Erwartete Revision enthält Forderungsfakten und ihren Evidenzstand. Ein verlorener Erfolg kann mit demselben Actor/Schlüssel und identischer Nutzlast wiederholt werden; abweichende Nutzlast oder veraltete Revision führt zu 409. Betrag-/Identitätsänderungen oder Löschung referenzierter Quellen werden abgewehrt. Nur neue Storno-/Rücknahmeevidenz ändert den Rest.

Private Berichtsdefinitionen werden immer nach aktuellem Benutzer gefiltert. Sichtbarkeit aller Definitionsquellen wird beim Öffnen erneut geprüft. Die vorhandene Portfolio-Middleware bleibt erhalten; zusätzliche Schlussprüfungen verhindern Ausgabe nach zwischenzeitlichem Rechteentzug. Neue UI-Aufrufe laufen über `api` und `captureSession`, ohne separate Fetch-/Auth-Wege. Eingaben und Wiederholungsschlüssel bleiben nach Fehler erhalten; bewusst geänderte Eingabe erhält einen neuen Schlüssel. Keine Dokument-/Originalbytes werden durch die Finanzfunktionen bearbeitet. Das Kautionsorakel prüft die Originalbytes vor/nach Storno.

## Migration und Wiederherstellung

Graph: `b82d5fa03147 → c61e9a2f034b → d73f2b9a041c → e160a1b2c302`.

`e160a1b2c302_financial_sources.py` fügt zwei nullable Invoice-Datumsfelder und zwei Tabellen (`receivable_settlements`, `saved_finance_reports`) mit Indizes/Fremdschlüsseln/Betrags- und Quellconstraints hinzu. Kein Rewrite vorhandener Beträge, Status, Dokumente oder historischer Revisionen. `create_all`-Adoption wird geprüft. Der Selbstverweis einer Rücknahme verwendet `NO ACTION`: Einzel-Löschung der referenzierten Quelle scheitert, die bestehende vollständige Geschäftsdatenwiederherstellung kann die gesamte Verweismenge in einem DELETE entfernen. Destruktives Downgrade wird abgewiesen; Rückweg ist der gesicherte passende Programm-/Datenstand.

Snapshotformat 9 transportiert kanonische Geschäftszuordnungen und validiert sie vor dem Schreiben. Private Benutzer-Berichtsdefinitionen werden nicht in einen Geschäftsdatenexport ohne Benutzeridentitäten umgebunden; sie bleiben im vollständigen SQL-Installationsbackup erhalten. Neue Tabellen liegen in derselben Datenbank und erfordern keine zusätzliche Datei-/Secretablage. Keine neuen Abhängigkeiten, keine Änderung der vorgegebenen Pythonumgebung und kein `npm ci` behauptet; Frontendprüfungen nutzen die isolierte vorhandene Referenzkopie.

Bei Integration die gemeinsamen Änderungen in Modellen, DB-Registry, `maintenance_rows`, `routing`, `portfolio_scope`, Snapshotformat/-Validator, Kapazitätsberechnung und Quellnavigation zusammen übernehmen. Andere Paketköpfe erst im Koordinatorzweig über eine neue Merge-Revision verbinden. Keine alte veröffentlichte Revision umschreiben.

## Prüfstand und verbleibende Abnahme

Alle Backendläufe verwenden den vorgegebenen Pythonpfad und `scripts/run_pro_matrix.py` mit eigenen Labels/Runtimeverzeichnissen; kein xdist. Ein einzelner Regressionstest erzeugt absichtlich zwei konkurrierende Requests, um das gemeinsame Budget zu prüfen. Keine Gesamtsuite, PG-, Live- oder Browserinstallation wurde gestartet.

Zwischenstände (keine Freigabe späterer Änderungen):

- `finance-first-memory-*`: 28 bestanden; 7 Setupfehler wegen zunächst unvollständiger Typannotation der neuen Speichersammlung. Korrigiert.
- `finance-v2-oracles-memory-*`: 8 bestanden, 1 falscher Zugriff des neuen Tests auf den bestehenden Tenant-Account-Vertrag. Korrigiert auf `totals.paid`.
- `finance-v2-sql-first-*`: 8 bestanden, 1 Replayformatfehler (UTC/Centdarstellung). Normalisiert.
- `finance-deposit-oracle-memory-*`: 10 bestanden, einschließlich echter Kautionsfinalisierung, datierter Mahnung und Originalbytes.
- `finance-deposit-sql-final-*`: 44 bestanden, 1 bedingter Skip, vor den späteren Rücknahme-/Szenarioergänzungen.
- `finance-expanded-memory-*`: 17 bestanden, 1 Testwerkzeugfehler wegen nicht installiertem `pypdf`; auf bereits vorhandenes `pdfplumber` umgestellt, keine Installation.
- `finance-expanded-sql-*`: 13 bestanden, 6 Setup-/Cleanupfehler durch den ursprünglichen RESTRICT-Selbstverweis. Auf NO ACTION mit erhaltenem Einzelreferenzschutz korrigiert.
- `finance-contract-final-memory-*`: 31 bestanden (Forderungs-/Szenarioorakel, Migration, Dunning-Regeln); später wurde der gemischte Teilrücklastschriftfall zusätzlich präzisiert.
- `finance-timeline-sql-*`: 31 bestanden, 1 Testfehler: SQL-Kontovertrag erwartet bei Änderung der Portfolio-IDs zusätzlich `portfolio_access`. Test verwendet nun den tatsächlich beobachteten Vertrag.
- Neue UI-Datei zunächst 3/3 bestanden. Breiterer gezielter UI-Lauf: 4/8 bestanden, vier vorhandene Tabellen-/Cachetests liefen in ihren unveränderten 5-Sekunden-Timeout. Einzelgegenprobe folgt; Zeitgrenzen/Assertions bleiben unverändert.
- Ruff der neuen Kernmodule und gezieltes mypy zuletzt erfolgreich; abschließende Ergebnisse und genaue Runtime-IDs werden unten ergänzt.

Synthetische PDF aus `finance-expanded-sql-sql-798d868ba33747099b1cb69c0625f939/finance-v2-sample.pdf`: beide Seiten mit vorhandenem PDFium gerendert und visuell angesehen, keine Überlappung/Abschneidung; die zwischenzeitlich noch offene Zeitraumanzeige wurde anschließend an die tatsächlich angewandten Grenzen angeschlossen. Finale repräsentative PDF wird erneut geprüft.

Vom Koordinator ausdrücklich reserviert und hier nicht als bestanden behauptet: unabhängige native PostgreSQL-Verbindungen, gemeinsame Multiworker-/Grantwechselabnahme, 320/360/1440-Browser/Fokus, großer Bestandsbenchmark der neuen Berichte und vollständiger isolierter Installationsbackup/Start-Restore. Die neuen Migrations- und Snapshotregressionen ersetzen diese Gates nicht. Keine externen Dienstzugänge erforderlich; ungeklärte Altteilzahlungen benötigen echte lokale Originalbelege statt einer erfundenen Zahlungsrekonstruktion.

### Abschließende Ergebnisse

Wird nach Ende der laufenden gezielten Gegenproben ergänzt. Eine funktionale oder externe Vollabnahme wird vor deren Ergebnis nicht behauptet.
