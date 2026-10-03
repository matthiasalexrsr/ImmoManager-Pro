# B: Quellenplan für globale Suche und Dashboard

Stand: 03.10.2026. Reine Quellenanalyse und Vorschlag vor Produktcode. Geprüfte Rootbasis `ff4b1a5`, im eigenen Checkout komponiert als `da6767d`; Root arbeitet unabhängig an noch nicht übernommenen Widerspruchsentwürfen. Diese Analyse schreibt keine Rootdateien, verändert weder Produkt noch Schema und startet keine Prüfung. Der vorangegangene gemeinsame Legacy-/Startup-/Runnernachweis ist separat in `L_COMMON_LEGACY_STARTUP_RUNNER_ACCEPTANCE_20261003.md` dokumentiert (`29dfd10`).

## 1. Tatsächlicher Ausgangspunkt

Der freigegebene Gesamtplan verlangt vollständige Listen/Suche/Kennzahlen, unmittelbare Rechteprüfung, keine falschen Leerbestände oder Altdaten und Browsernachweise bei 320/360/1440 Pixeln. Grundlage sind der Gesamtplan, `P0_GLOBAL_SEARCH_PLAN_20261003.md`, dessen Handoff sowie die aktuellen Quellen. Die älteren Statusangaben in der Roadmap ersetzen den Quellstand nicht.

| Quelle | Tatsächliches Verhalten | Konsequenz für B |
|---|---|---|
| `services/global_search.py:29,56,73` | 16 registrierte Familien, minimale SQL-Projektion mit `LIMIT`, Unicode-Casefold und literalen `%/_/\\`, stabiler Familienrang und Byte-ID absteigend; Memory hält nur die benötigten Treffer | Bestehende vollständige Keywordseiten weiterverwenden. Kein Ersatz durch eine neue Gesamtliste |
| `services/global_search.py:95` | Signierter Cursor bindet Suchtext, Seitengröße, Benutzer, Rolle und Portfoliozuweisungen; Frischeprüfung vor/nach Lesen | Registryversion und Erweiterungen gezielt prüfen. Kein zweiter Cursor-/Signaturdienst |
| `routers/search.py:19,22` | JSON-Veröffentlichungsfence vorhanden; semantischer Indexaufbau materialisiert fünf vollständige Familien | Semantik bleibt Empfehlung; Aufbau benötigt eigenes begrenztes Betriebspaket |
| `routers/dashboard.py:164` | 13 vollständige `store.list_*()`-Aufrufe, danach Pythonzählungen und wiederholte Mengenvergleiche | Vollständigkeit ist derzeit durch Vollmaterialisierung erkauft; serverseitige Aggregate und begrenzte Vorschauen einsetzen |
| `repositories/base.py:202`, `repositories/tenant_repo.py:84` | Domänenlisten verwenden `list_all()`, nicht das separat vorhandene `_list_paginated(limit=100)` | In diesen Dashboardzählungen ist **kein 100-Cap belegt**. Nicht aufgrund des Listennamens einen Abschneidefehler behaupten |
| `pages/Dashboard.jsx:23,48,104`, `api.js:412` | Belegung lädt `/units` mit `getAll()` in 1.000er Offsetseiten und hält alle Einheiten im Browser | Ebenfalls kein belegter 100-Cap; Antwort-/Browserarbeit wächst mit dem Bestand und verändert sich zwischen Offsetseiten |
| `services/unit_inventory.py:223` | Vorhandene vollständige, scoped Aggregation einschließlich occupied/rented, vacant, reserved | Belegungssemantik übernehmen, zusätzliche Bestandskopie vermeiden |
| `routers/reports.py:73,140`, `services/financial_cash.py:156,237` | Cashflow/Kategorien verwenden dieselbe exakte Buchungsquelle, Belegstand und Ausschlussregeln; SQL liest begrenzte Blöcke | Fachlich weiterverwenden. Keine zweite Buchungs-/Zahlungssumme erzeugen. Gruppenantworten wachsen weiterhin mit Kategorie-/Objektzahl |
| `routers/reports.py:114,163,194` | Aging, auslaufende Verträge und Wartung erhalten vollständige Listen; Vertragsreport liefert alle Zeilen, Dashboard zeigt davon fünf | Vollständige Kennzahlen von begrenzten Arbeitshinweisen trennen |
| `routers/dashboard.py:109`, `routers/billing.py:385` | Dashboard prüft nur Kosten-/Vertrags-/Schlüsselpräsenz; echte Abrechnungsprüfung umfasst unter anderem historische Basis, Medien, Leerstand und Vorauszahlungen | Präsenzzählung darf nicht als vollständiger fachlicher Preflight gelten |

Vorhandene Suchtests beweisen bereits 10.001 Immobilien in Memory/SQLite und PostgreSQL, Unicode/Literalzeichen, Familienwechsel, Cursorbindung und Rechteentzug. Sie sind Ausgangsnachweise, keine neue B-Abnahme auf diesem Snapshot. `test_dashboard_stats.py` enthält derzeit einen kleinen Workflowbestand; die UI prüft Quellfehler/Retry, andere Einheitenstatus und Rollenaktionen, aber keine vollständige Dashboardabnahme oberhalb 100/1.000/10.000.

## 2. Konkrete fachliche und Authority-Lücken

1. **IBAN-Suchparität:** `global_search._joined()` castet `accounts.iban` zu String und durchsucht den gespeicherten Ciphertext. `AccountORM.iban` ist `EncryptedIBAN`; Memory durchsucht den Klartext. Der Cursor enthält zudem den Suchbegriff im signierten, lesbaren Payload. Das ist ein nachvollziehbarer Sourcebefund, noch kein ausgeführter Negativtest. Vorhandene Fingerprints und Keyring weiterverwenden; keine Verschlüsselungsneulösung oder Datenmigration.
2. **Benachrichtigungszahlen:** Die Liste filtert zusätzlich `operational_schedule.notification_visible(..., user.role)`. Dashboard zählt dieselben Meldungen ohne diese Zielrollenregel. `operational_dispatches.notification_id` ist nativ eindeutig. Zähler und Vorschau müssen dieselbe Regel verwenden, sonst verrät die Kennzahl rollenfremde Meldungen und stimmt nicht zur Liste.
3. **Veröffentlichung:** Search/Inventory verwenden `CheckedPublicationRoute`, Dashboard/alte Reports gewöhnliche `APIRouter`. Die zentrale Middleware prüft ausgewählte Portfolios vor erfolgreichen Headers nochmals; eine identische zusätzliche Sitzungs-/Rollenprüfung für alle Benutzer bietet bereits `CheckedPublicationRoute`. Diese vorhandene API verwenden, nicht lokal neu erfinden.
4. **UI-Rechtewechsel:** `SearchBar` verwirft Ergebnisse synchron über einen Principal-Key. Dashboard konsumiert nur Rollenflags, sein Quellenhook bindet nicht an Benutzer/Portfoliozuweisungen. Der vorhandene `ProtectedRoute` navigiert bei Wechsel der Sessionfamilie bereits vollständig neu; diesen funktionierenden Schutz erhalten. Der noch fehlende gezielte Fall ist eine aktualisierte Rechte-/Portfolioidentität im weiter montierten Dashboard.
5. **Kennzahlbedeutung:** `occupied_units` zählt bisher nur occupied, UI/Inventory auch rented; open_maintenance zählt nur open, Überfälligkeit mehrere offene Status. Forderungs-Statuszählungen sind keine Restbetragberechnung. Eine gemeinsame Begriffsdefinition ist erforderlich; Altzustände werden angezeigt, nicht automatisch berichtigt.

## 3. Gemeinsamer Authority-Vertrag

Jede HTTP-Abfrage erhält die frisch geprüfte serverseitige Identität und `AccessScope`. Unauthentifizierter interner Aufruf bleibt ausdrücklich intern; eine HTTP-Route darf fehlende Benutzerbindung nicht als Installationsrecht interpretieren.

- SQL/Core/Alias-/EXISTS-Quellen erhalten ausdrücklich `scoped_clause(table, scope=captured)` für Subjekt **und** verknüpfte Eltern. Eine Portfolioauswahl engt bestehende Rechte ein. Ein unbekannter oder unsichtbarer Parent wird nicht durch einen weiter gefassten Count ersetzt.
- Memory verwendet dieselbe Sichtbarkeitsregel unter dem vorhandenen `_memory_lock`. Es werden keine zusätzlichen Vollbestands-Pydanticlisten aufgebaut.
- Vor dem Lesen und unmittelbar vor JSON-Veröffentlichung werden aktuelle Rolle/Aktivierung/Grants und tatsächliche Sitzung über die vorhandenen zentralen Helfer geprüft. Keine neue Anmeldeablage, kein zweiter SQLite-Schreiber beim Lesen. Abbruch liefert 401/403 ohne vorbereitete private Kennzahlen.
- Zielrollen der Benachrichtigungen gelten zusätzlich zum Portfoliofilter. SQL nutzt den eindeutigen Dispatchbezug als gemeinsame EXISTS-/Join-Regel; Memory dieselbe Regel mit vorhandener Dispatchidentität. Kein `notification_visible()`-SQL-Aufruf pro Zeile.
- UI bindet Quellen, Retry und Seitencursor an denselben kanonischen Principal wie SearchBar. Wechsel verwirft alle privaten Ergebnisse synchron, bricht Requests ab und ignoriert späte Antworten. 401/403 leert betroffene private Daten; 503 bleibt ein expliziter Fehler. Audit bleibt rollen- und installationsgebunden.
- Kein Cache wird allein nach URL, Suchtext oder Portfolio benannt. Ein zunächst nicht benötigter Cache wird nicht vorsorglich eingeführt.

Root besitzt zentrale Auth-/App-/Dependencies-Komposition. Dashboard-/Searchquellen dürfen vorhandene APIs nutzen; eine Änderung am zentralen Vertrag wird vorher als eigener Hookvorschlag übergeben. Die gemischten Reportrouter enthalten außerdem schreibende und Streamingrouten: keinen pauschalen JSONwrapper als vermeintlichen Streamschutz installieren. Nur betroffene JSONrouten gezielt integrieren; CSV behält echte Chunk-/Abschlussprüfungen.

## 4. Cursor und vollständige Suchquellen

Keyword `/search/page` behält seine explizite Vollständigkeit über **registrierte Felder und Familien**. `count` ist Seitenanzahl, kein behauptetes Gesamttrefferzählwerk. Semantische Empfehlungen werden nicht in dieselbe Vollständigkeitsbehauptung gemischt.

Vorschlag: vorhandenen signierten Cursor um eine explizite Registry-/Sortier-/Projektionsversion binden. Bisherige Rangfolge bleibt erhalten; neue Familien werden angehängt. Eine veränderte Registry oder Suchsemantik verwirft alte Seiten verständlich mit 422. Die Position bleibt `(source_rank, bytewise_id)`; keine Offsetseiten, willkürlichen Servercaps oder zufälligen UUIDs als Zeitanker.

Der Cursor bindet Normalform des Textes, aktive Familien/Filter, Seitengröße und Sortierung sowie Benutzer/Rolle/Grants. Sitzung wird pro Request geprüft; Tokenrotation innerhalb derselben Sessionfamilie darf Seiten nicht künstlich ungültig machen. Eine Sitzung darf keine fremde Benutzerbindung übernehmen. Cursorpayload ist signiert, **nicht verschlüsselt**: als privates Artefakt behandeln, weder Querystrings noch Cursor/Suchbegriffe in allgemeine Logs oder persistente UIpräferenzen schreiben.

Live-Seiten versprechen stabile Ordnung eines unveränderten Bestands, keinen historischen Snapshot über Requests. Ein Lösch-/Einfüge-/Umhängungsfall wird ausdrücklich geprüft und dokumentiert; ein echter eingefrorener Export nutzt seinen vorhandenen Snapshot/Quellhash. Ein scheinbarer Highwater über UUID oder updated_at wäre kein Vollständigkeitsbeweis.

Vor Code entsteht ein Registryvertrag je Familie: tatsächliche Felder, sichere Anzeige, Zielroute, Parent-/Rollenregel, Ordnung und native Probe. Die bestehenden 16 Familien bleiben vollständig. Erste konkrete Ergänzungskandidaten aus vorhandenen Produktquellen:

| Familie | Vorhandene sinnvolle Felder/Bezüge | Anschluss |
|---|---|---|
| Portfolio | name | `/portfolios`; direkter Scope |
| Forderung | description, due_date, status; sichtbarer contract_number | bestehende Forderungsansicht; Subjekt-/Vertragscope |
| Monatssoll | month, status; sichtbarer contract_number | bestehende Mietsollliste; Subjekt-/Vertragscope |
| Abrechnungsperiode | label, revision_notes, Zeitraum; sichtbarer Immobilienname | bestehende Abrechnung; kein Durchsuchen privater Originalpayloads |
| Zähler | serial_number, location, supplier, contract_number, meter_type | vorhandenes Zählerinventory; Einheiten-/Elternscope |

Kalender-/Übergabe-/Abrechnungsoriginalmetadaten werden mit ihrem Owner in denselben Vertrag aufgenommen, sofern eine sichere Zielroute besteht. Schlüssel, Sessions, Outboxempfänger/-texte, private Entwurfspayloads und Betriebsjournale werden nicht durch generisches Metadatenenumerieren zu Suchquellen. Referenzfelder eines Kindes benötigen eigene SQLprojektion und identische Memory-Semantik; fehlende Eltern sind keine still übersprungene Erfolgsquelle.

IBAN: zuerst tatsächliche Memory-/SQLite-/PG-Negativprobe. Eine vollständige normalisierte IBAN kann den vorhandenen `iban_fingerprint` mit bestehendem Indexkey verwenden. Ein Fingerprint beweist **keine Teiltextsuche**. Für die bereits versprochene allgemeine Teiltextsemantik ist ein Accountadapter nötig: scoped IDblöcke in derselben Ordnung, result-seitige Entschlüsselung durch vorhandenen Typ/Keyring, Textprüfung im begrenzten Block, nur sichere Trefferprojektion. Bis Seite gefüllt oder Familie vollständig erschöpft ist, darf ein Blockbudget keinen Trefferbestand abschneiden. Timeout/Schlüsselfehler wird als Fehler geliefert, niemals als leer/vollständig. Keine Klartextparameter/-IBAN in Diagnoseausgaben; Cursor-Sensibilität beachten. Hash-/Fingerprintfastpath darf gemischte Namens-/Banksuche nicht ausschließen.

Für das semantische Reindex ist ein eigenes L/E-Anschlussdesign erforderlich: begrenzte Projektionen, fortsetzbarer Aufbau, atomische Veröffentlichung eines vollständigen Indexstands, Erhalt des bisherigen Index bei Abbruch und aktuelle Sichtbarkeitsprüfung jedes Vorschlags. Der derzeitige Vollaufbau ist keine begrenzte Lösung. Dieses Betriebspaket wird nicht mit einer Suchseitenkorrektur versteckt erweitert.

## 5. Kennzahlen und begrenzte Arbeitshinweise

Erster konkreter Produktbaustein nach Zuteilung: neuer reiner `services/dashboard_summary.py`, kleine getrennte Dashboardrouterintegration und Principal-gebundener UIquellenhook. `/dashboard/stats` behält die vorhandenen flachen Felder als kompatiblen Vertrag; additive strukturierte Belegung und klare Quellenbasis ersetzen das Browser-`getAll('/units')`. Kein neuer Schemahead.

SQL zählt vollständig serverseitig: bedingte Aggregate pro Familie, skalare Counts in einem gemeinsamen SELECT bzw. nachgewiesen konsistenter Read-Transaction, keine ORM-/Pydanticmaterialisierung des Bestands. Fehlende Vertragsdokumente nutzen scoped NOT EXISTS; Eskalationskandidaten scoped EXISTS über aktive Regeln, sodass eine Meldung trotz mehrerer Regeln nur einmal zählt. Native DATE-/NULL-/Boolbedingungen und tatsächliche Altstatussemantik müssen Memory entsprechen. Kein `SUM` über einen Join, der Zahlungen oder Dokumente vervielfacht.

Memory berechnet identische Werte unter einem gemeinsamen Leselock; nur nötige skalare Werte/Relationen lesen. Durch neue Lookups dürfen keine quadratischen Vollbestandssuchen oder unnötigen vollständigen Modelkopien entstehen. Ein nativer SQLfehler bleibt ein Fehler; `COALESCE(...,0)` behandelt nur tatsächlich leere erfolgreiche Mengen.

| Kennzahl | Verbindliche Bedeutung/Quelle |
|---|---|
| Bestand | sichtbare Datensätze, einschließlich historischer unbekannter Status; Counts niemals aus einer Vorschauseite |
| Belegung | gespeicherter Einheitenstatus: occupied/rented, vacant, reserved, other; Summe exakt total; aktueller Vertragsbeleg ist eine getrennte Kennzahl |
| Aufgaben/Meldungen | vorhandene Statusregel und aktueller Scope, Meldungen zusätzlich bestehende Zielrolle; Gesamtcount und begrenzte Vorschau getrennt |
| Vertragsdokumente fehlen | bisherige Vertragszuordnung explizit benennen; keine Aussage über geprüfte Originaldatei/inhaltliche Vollständigkeit erfinden |
| Überfälligkeit | ein mitgelieferter `as_of` pro Antwort, fachlich bestehende Fälligkeit; kein Zeitwechsel innerhalb einer Antwort |
| Cashflow/Kategorien/Prognose | vorhandene `financial_cash`-/Forecastquelle und exakte Dezimalfelder, gleiche Filter/Belegbasis; keine Summierung von Bankbuchung plus verknüpftem Zahlungsbeleg |
| Offene Beträge/Aging | bestehende `_open_obligations`-/`payment_total`-Regeln, Restbetrag je Sollziel einmal; keine Summierung bloßer Statuszahlen |
| Wartungskosten | Schätzung ausdrücklich als Schätzung, kein tatsächlich bezahlter Cashflow; exakte Berechnung gesondert verifizieren |
| Abrechnungsbereitschaft | vollständig geprüfter fachlicher Stand oder ausdrücklich ungeprüft/veraltet; einfache Präsenzprüfung ist nur Präsenzprüfung |

Legacy-Statuscounts nicht still umdefinieren. Additive belegte Zusammenfassungen beseitigen occupied/rented-Differenz, nennen ihre Basis und lassen abweichende Altzustände sichtbar. UI verwendet exakte Geldfelder zur Anzeige und Prüfung; Floatdarstellung dient nur Diagrammen. Keine künstliche Gesamtsummengrenze.

Für Aufgaben, Meldungen und auslaufende Verträge reicht eine begrenzte Vorschau (initial fünf). Sie liefert getrennten vollständigen Totalcount, `has_more`, stabilen Cursor und passende gefilterte Zielansicht. Enddatum/due_date plus byteweise ID mit definierter NULLordnung verhindern verlorene Gleichstände. Meldungen werden schon vor LIMIT nach Rolle gefiltert. Die UI lädt nie alle Verträge, um fünf auslaufende anzuzeigen.

Cashflow/Kategorien dürfen nicht mehrfach identische Gesamtquellen scannen, nur um zwei Diagramme zu zeichnen. Anschluss an D: eine gemeinsame Antwort mit exakten Totals und begrenzten Kategorien/Standorten; übrige Gruppen bleiben blätterbar. Keine neue Berechnung neben `financial_cash`; deren vorhandener `source_hash` bindet Belegseiten. Die aktuelle vollständige Gruppenmaterialisierung ist als separate Kostengrenze zu messen, nicht wegen begrenzter Belegblöcke als konstant zu behaupten.

Abrechnungsanschluss an C/Domain: denselben tatsächlichen periodischen Preflight nutzen, zunächst rein lesende gemeinsame Extraktion der vorhandenen Regel. Für große Mengen ein fortsetzbarer Prüfdurchlauf über alle sichtbaren Perioden, mit eigenem Quellstand und nachvollziehbar geprüft/ungeprüft/veraltet; dafür vorhandenen Job-/Prüfjournalvertrag erst mit E/Root abstimmen. Ohne vollständigen Durchlauf keine globale Zahl „0 Blocker“. Ändern sich historische/Medien-/Bewohner-/Originalquellen, verliert ein alter Beleg seine Aktualität. Keine eigenen Finanz-/Originaljournale, neue DDLrevision oder Domainformel. Bis zum geprüften Anschluss zeigt die UI bestehende Präsenzbefunde als solche und bietet die echte periodische Prüfung.

Panels bleiben separat retrybar. `as_of` ist Fachstichtag, `loaded_at` Abrufzeit; mehrere unabhängige Quellen dürfen nicht als ein atomarer Datenbanksnapshot beschriftet werden. Jede Summe/Prozentzahl besitzt einen klaren Nenner und passende Drilldownfilter. Fehler oder unvollständiger Prüfstand erzeugen einen sichtbaren Zustand, keine Null oder Erfolgsmeldung.

## 6. Konkrete Anti-100-Abnahme vor B-Handoff

Alle folgenden Fälle sind **geplant**, hier nicht ausgeführt. Nur synthetische Daten und eigene UUID-PostgreSQL-Schemas; keine private Installation. NodeIDs und Testbudgets werden vor jedem koordinierten Einzelgate gemeldet. Bereits grüne P0-/Inventorystandards werden gezielt wiederverwendet, nicht pauschal ein zweites Mal breit geprüft.

1. **Keywordfamilien:** Für jede registrierte Familie mindestens 101 relevante Treffer zwischen mehr irrelevanten/unsichtbaren Zeilen; späte Treffer an Position 100/101, 1.000/1.001 und 10.000/10.001. Alle Seiten exakt einmal und in zugesagter Familien-/Byteordnung erreichen, insbesondere Familienübergänge und gleichlautende Texte. Die bestehenden Immobilien-10.001-Proben reichen nicht als Nachweis aller Adapter.
2. **Echte Feldparität:** Memory, SQLite und tatsächlich ausgeführtes PostgreSQL mit Straße/STRASSE, Nicht-ASCII-Namen, literalen `%/_/\\`, NULLfeldern, zusammengesetzten Feldern, unveränderten verschlüsselten Test-IBANs und fehlenden Eltern. IBANvoll-/Teiltreffer hinter vielen Nichttreffern; falscher Testkey führt zu verständlichem Fehler ohne Klartext/Schlüssel/SQLparameter im Fehlertext. Diese Probe nutzt ausschließlich neu erzeugte Testschlüssel.
3. **Registry-/Cursorvertrag:** falscher Text/Filter/Limit/Familie/Benutzer/Scope, manipulierte/abgelaufene/überlange Position, Registrywechsel, gleiche Familie bei regulärer Tokenrotation. Kein Replay mit fremder Bindung. Live-Einfügen/Löschen/Umhängen ausdrücklich gemäß dokumentierter Semantik; keine behauptete historische Vollständigkeit.
4. **Dashboardbestand:** Pro gezählter Familie mindestens 101/1.001 Zeilen, insgesamt zusätzliche 10.001-Spätpositionen. Unabhängige synthetische Erwartungswerte; alle Statusgruppen summieren zur vollständigen sichtbaren Menge. Spät fehlendes Vertragsdokument, mehrere Dokumente pro Vertrag, viele Eskalationsregeln für denselben Fall, unknown/rented/NULLzustände und Fälligkeit am Stichtag.
5. **Zähler gleich Liste:** fremdes Portfolio, rollenfremder Dispatch, unlinked Installationsdatensatz, gemeinsam erreichbarer Tenant und später umgehängter Parent. Benachrichtigungstotal exakt zur sichtbaren Liste. Unerreichbare Parents ändern weder sichtbare Counts noch Suchdetails. Count-/Previewquellen verwenden dieselben Bedingungen.
6. **Authority vor Veröffentlichung:** tatsächliche Sessionrevokation, Rollen-/Aktivierungs-/Grantwechsel und Parentumhängung nach Lesen vor Headers. Ausgewählte und all-Portfolio-Actors prüfen, statt nur initialem Grantfall. Kein privater vorbereiteter JSONpayload wird gesendet. SQL liest ohne Flush/DDL/Bestandskorrektur, inklusive pending ORMänderung und nativer DDLverweigerung.
7. **Begrenzte Arbeit:** `list_*`, `list_all`, Browser-`getAll` für geänderte Summarypfade als Tripwire; native SQLobserver prüfen minimale Projektion, LIMIT für Vorschauen, serverseitige Aggregate und Queryzahl unabhängig vom Bestand. Keine N+1-Zielrollen-/Parentchecks. Antwortgröße für Totals/Vorschau wächst nicht mit Zeilenzahl. Ein vollständiger Aggregate-SCAN ist Kostenarbeit, kein materialisierter Antwortbestand.
8. **Fachwerte/Quellen:** Centfälle, Teilzahlung/Überzahlung/Storno, verknüpfte Bankbuchung und Zahlungsbeleg, Null-/Negativewerte und Ablaufdaten. Exakte Summen/Drilldown/CSV stimmen mit den bestehenden autoritativen Quellen überein. Ein historischer Medien-/Bewohnerblocker darf nicht durch eine positive Präsenzprüfung grün werden; geänderter Quellenstand macht einen alten vollständigen Prüflauf stale.
9. **UIzustände:** tatsächliche mindestens 101 Treffer und >1.000 Einheitenzählung bei 320/360/1440 Pixeln, Keyboardpagination/Tabfokus und erhaltene gefilterte Drilldowns. 503 auf Folgeseite behält Filter/Cursor für Retry; kein falscher Leerbestand. Rollen-/Portfolioänderung verwirft angezeigte private Daten synchron, auch bei verspäteter alter Antwort. Große Zähler nicht durch fünf Vorschauzeilen ersetzen.
10. **Großbestand:** gesondert 100.000 und danach 1 Mio. Finanzzeilen, 20 Jahre, zehn Benutzer auf dokumentierter Hardware. Kalt-/Warmlauf, SQLplan, Rows/Bytes, Roundtrips, Spitzen-RSS/Browserheap und p50/p95 messen. Unicode-Contains kann trotz LIMIT voll scannen; ohne gemessenen Plan keine Index-/Latenzbehauptung. DDL-/Indexbedarf erst danach Root melden, keine eigene Revision erzeugen.

Gezielte bestehende Quellen für die neuen Tests: `test_global_search_pages.py`, `test_global_search_postgres.py`, `test_unit_inventory.py`, `test_financial_cash.py`, Portfolio-HTTPfixture sowie `DashboardHome.test.jsx`/`SearchBar.test.jsx`. Neue Dashboardnative-/Publicationfälle ergänzen diese, statt reine SQL-/Implementierungsnachbauten als Beweis zu verwenden. Ein fehlendes PGenv oder SKIP zählt nicht als PGnachweis.

## 7. Vorgeschlagene getrennte Umsetzung und Ownership

1. Sourcevertrag und kleine tatsächliche Negativproben für IBAN, Zielrollenzähler und Dashboardpublication; gemeinsam festgelegte unveränderte Quelle, ein Gateprozess. Dieser Plan selbst liefert keine roten/grünen Testbehauptungen.
2. B1 vollständige serverseitige Count-/Belegungsquelle samt vorhandener Authorityintegration; separat kleine Tests, dann gezielte PostgreSQL-/UIkomposition. Keine Produktänderung vor Rootzuteilung.
3. B2 Principalgebundene UI, begrenzte Vorschauen und präzise Retry-/Drilldownwerte. Vorhandene Audit-/Sessionfamilienregeln erhalten. Mobile echte Browserprobe koordinieren.
4. B3 Registry-/IBANadapter und geprüfte zusätzliche Familien, vorhandene Keywordseite erweitern; keine Änderung der ursprünglichen Reihenfolge oder Suchsemantik ohne Cursorversion. Semantischer Aufbau als getrennte L/E-Operation.
5. B4 echte periodische Prüf-/Finanzquellenkomposition mit C/D/E-Owner; anschließend gezielte Großbestandsabnahme. Kein vorzeitiges Gesamt-B- oder A–L-grün.

Mögliche eigene Quellen: reiner Dashboard-Query-/Summarydienst, gezielte Tests und Dokumente. Dashboardrouter/UI/Searchadapter nur nach ausdrücklicher Zuteilung; Root behält App/Dependencies/SharedAuthority/Settings/CI. C bleibt Owner der Abrechnungsfachregel und historischer Proofs, D der Finanzquelle, E von Job-/Dispatchverträgen. Keine neue DDLrevision, kein Wartungs-/Produktstart, keine echte Migration oder Root-/Main-/Preview-Cherrypicks in diesem Analysepaket.
