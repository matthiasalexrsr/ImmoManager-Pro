# Ergänzungsvorschlag: echte Backend-Browser-E2E

Stand: 1. Oktober 2026. Fachliche Referenz dieses Vorschlags ist `21c67d1`.
Der während der UI-Arbeit entstandene Browser-Commit `f39863b` wurde gelesen,
aber nicht in diesen Worktree integriert. Seine beiden echten SQL-/Browser-
Workflows sind die Basis, keine zweite konkurrierende Testinfrastruktur.

## Bereits im Browser-Worktree vorhanden

`frontend/e2e/run.mjs` startet einen eigenen FastAPI-Prozess mit temporärer
SQLite-Datenbank, isolierten Laufzeitpfaden, eigenem JWT-Secret und Demo-Seeding.
Es prüft SQLAlchemyStore und DB-Verbindung. `workflows.pw.mjs` führt echte UI-
Anmeldung, eine Teilzahlung mit Historie/Reload und eine Abrechnungsperiode vom
blockierten Preflight bis zu generierten, nach Reload vorhandenen Einzelabrechnungen
aus. Keine HTTP-Antworten werden dabei simuliert. Ein Worker, keine Retries und
390-px-Prüfungen sind bereits konfiguriert. Diese Feststellung beruht auf dem
Quellcode des Browser-Agenten; meine eigene Finanzseiten-Browsermatrix nutzt Mocks.

Die folgenden Erweiterungen sind ein Vorschlag, noch nicht von mir implementiert
oder gegen ein laufendes Fachbackend ausgeführt. CI, Pakete und Runner bleiben
im Besitz des Browser-/Root-Agenten.

## 1. Reproduzierbare isolierte Fachfixture

Die vorhandenen Demo-Smokes beibehalten. Zusätzlich eine kleine deterministische
Fixture anlegen, statt Summen und Vertragsauswahl von wechselnden Demo-Daten oder
der aktuellen Monatsgrenze abhängig zu machen. Pro Szenario eigene Immobilie,
eindeutige IDs/Bezeichnungen und feste Datumswerte verwenden.
Vorgeschlagene Daten: Abrechnungsjahr 2025, zwei aktive Verträge ab 01.01.2025,
Einheiten 60/40 m², monatliche Nebenkostenvorauszahlungen 10,00/5,00 €, Heizkosten-
vorauszahlung jeweils 0. Flächenschlüssel `area_sqm`, Kosten Wasser 500,00 € und
Müll 300,00 €. Für Vertrag 1 eine Januar-Sollstellung: Kaltmiete 90,30 € plus
Nebenkosten 10,00 € = 100,30 €. Keine zusätzliche Bankbuchung desselben Geldeingangs.

Stammdaten dürfen über echte HTTP-API-Aufrufe vorbereitet werden; mindestens ein
Vertrag soll über das sichtbare Vertragsformular erstellt und seine Immobilie,
Einheit, Mieter, Vertragsnummer und Startdatum anschließend per GET geprüft werden.
APIRequestContext eignet sich für diese Vorbereitung und die Persistenzprüfungen
nach einer UI-Aktion [2]. Anmeldung selbst bleibt ein Browser-Formularablauf.

Wichtig: `/auth/register` erzeugt auf diesem Stand keinen Eigentümer, auch nicht
für den ersten Benutzer. Öffentliche Selbstregistrierung erlaubt nur readonly/
techniker. Das vorhandene isolierte Demo-Seeding liefert den Test-Eigentümer.
Für eine leere Fachfixture darf ein eigener Owner-Bootstrap ausschließlich in der
frisch erzeugten Test-DB erfolgen, mit normalem Passwort-Hashing und SQL-Userstore.
Kein `require_auth`-Override, kein vorab gesetztes Browser-JWT, kein echter Account.

## 2. Goldener Browserablauf und exakte Invarianten

| Schritt | UI und echte API | Erfolgskriterium |
|---|---|---|
| Anmeldung | `/login`, danach `/api/v1/auth/me` | Richtiger Testnutzer und Eigentümerrolle; keine Token-Injektion |
| Vertrag | Formular unter `/contracts`; POST/GET `/contracts` | IDs passen exakt zur Fixture; Vertrag über Reload vorhanden |
| Teilzahlung | Mietübersicht: 40,10 €, Datum 15.01.2025, eindeutige Notiz | POST `/rent-charges/{id}/payments` liefert 201; bezahlt 40,10 €, offen 60,20 €, Status partial, ein Beleg |
| Restzahlung | Weitere 60,20 € über denselben UI-Ablauf | Bezahlt 100,30 €, offen 0,00 €, Status paid, genau zwei Belege |
| Leere Abrechnung | Zeitraum anlegen, Detail öffnen | `NO_COST_ITEMS` sichtbar, Generieren deaktiviert |
| Kosten und Prüfung | Beide Kosten über Formular erfassen | Neuer Preflight hat keine Blocker; keine alte Prüfung weiterverwenden |
| Generierung | POST `/billing/periods/{id}/generate` aus der UI | Zwei Einzelabrechnungen, Kostenanteile 480,00/320,00 €, Summe 800,00 €, zwei Kostenzeilen je Abrechnung |
| Vorauszahlungen | UI-Zeilen und GET `/billing/statements?billing_period_id=...` | Vorauszahlungen 120,00/60,00 €, Salden 360,00/260,00 € |
| Abschluss | Zur Prüfung, danach Finalisieren | Periode und beide Einzelabrechnungen finalized; Bearbeitung gesperrt |
| Forderungen | Forderungen erzeugen | Zwei Posten 360,00/260,00 €, `statement_id` jeweils korrekt, keine Mietzahlung doppelt zählen |
| Zustellung | Als zugestellt markieren | Beide Einzelabrechnungen delivered; IDs und Beträge bleiben stabil |
| Korrektur | Korrekturgrund eingeben, neuen Entwurf öffnen | Neue Perioden-ID, kopierte Kosten, Original unverändert; keine rückwirkende Änderung bezahlter Posten |

Bei Beträgen in Tests Cent-Integers oder Decimal-Vergleich verwenden, nicht nur
Text-Snapshots. Jeden Schreibaufruf vor dem Klick mit `waitForResponse` abonnieren,
HTTP-Status prüfen und anschließend sichtbaren Zustand UND einen echten GET prüfen.
Bei Reload müssen Beleg-/Abrechnungs-IDs gleich bleiben. Ein neuer Browserkontext
mit erneuter Anmeldung darf ebenfalls keine Daten verlieren.

Ein eigener Persistenztest stoppt und startet ausschließlich den eigenen Backend-
Prozess mit derselben Test-DB und demselben JWT-Secret. Danach erneut anmelden und
Zahlungsbelege, Salden, Periodenstatus und Einzelabrechnungs-IDs vergleichen.
Ein Page-Reload allein belegt keinen erfolgreichen Datenbank-Neustart.

## 3. Negative Prüfungen, die fachliche Fehler nicht verdecken

Nach der ersten Teilzahlung: gleicher Idempotency-Key und identische Payload
nochmals per echter API -> derselbe Beleg, kein zusätzlicher Saldo. Gleicher Key
mit anderem Betrag und Überzahlung 60,21 € müssen abgewiesen werden und dürfen
keinen Beleg/Saldo ändern. Die genauen Statuscodes mit dem integrierten Payment-
Commit abgleichen (auf 21c67d1: fachlicher Konflikt 409; negative/Subcent-Werte 422).
Readonly-Testnutzer: Historie per GET lesbar, Zahlungs-POST 403. Ein abgemeldeter
Browser erhält keinen Zugriff auf geschützte Daten. Keine Rollenprüfung umgehen.
Finalisierte Perioden dürfen keine Kostenbearbeitung/Neugenerierung zulassen.
Bei PDF-Downloads Content-Type, nichtleere Bytes und `%PDF-` prüfen; ein
`text/plain`-Fallback ist kein erfolgreicher PDF-Test.

**Offener Prüfpunkt für den Backend-Agenten:** Auf Basis 21c67d1 ruft
`billing.create_receivables_from_period` bei jedem Aufruf erneut `create_receivable`
auf. Der gelesene SQL-Finanzrepository-Pfad enthält dort keinen Duplikatcheck.
Ein Test sollte daher zwei Aufrufe ausführen und genau einen Posten je
`statement_id` verlangen. Das ist ein Quellcodebefund, kein hier ausgeführter
Backend-Reproduktionstest; vor Integration mit dem aktuellen Finanz-Commit prüfen.
Den Test nicht still abschwächen, falls er einen bestehenden Defekt aufdeckt.

Ebenso fachlich wichtig: `generate_utility_statements` berechnet auf 21c67d1
Vorauszahlungen als `(unit.service_charge_advance + unit.heating_advance) * Monate`.
Es liest dafür nicht die tatsächlichen Payment-Belege. Die obigen 120,00/60,00 €
beschreiben den aktuellen Implementierungsvertrag, nicht nachgewiesene Ist-Zahlungen.
Soll die Abrechnung tatsächlich gezahlte Vorschüsse berücksichtigen, benötigt das
eine separate fachliche Entscheidung und Backend-Änderung; nicht per UI-Test
behaupten, dass Mietzahlungsbelege diese Abrechnung schon steuern.

## 4. CI-Ausbau ohne eine zweite Infrastruktur

`f39863b` integrieren und dessen Runner erweitern, statt zusätzliche Paket-/CI-
Varianten einzuführen. Die Lockdatei bestimmt Playwright/Browser-Version. Ein
Worker bleibt zunächst sinnvoll [1]; vorhandene `retries: 0` beibehalten.
Zusätzlich zur lokalen Tabelleninitialisierung eine leere DB mit
`python -m alembic upgrade head` migrieren, bevor der Fachfixture-Server startet.
`DATABASE_URL`, DATA_DIR, UPLOADS_DIR, BACKUP_DIR, LOG_FILE und Integrationszustand
müssen dieselben frischen absoluten Testpfade verwenden; Memory-Fallback, AI und
externe Plugins bleiben aus. Nicht auf einen schon laufenden Preview ausweichen.
Bei späterer Umstellung auf Playwright `webServer` ist `reuseExistingServer: false`
für CI ausdrücklich zu setzen [3]. Kein globales `clear_all` gegen einen Server,
keine produktiven Zugangsdaten, kein gemeinsam genutzter Benutzer-/Dateispeicher.

Vorgeschlagene neue Specs: `contract-create.pw.mjs`, `payment-lifecycle.pw.mjs`,
`billing-finalize.pw.mjs`, `billing-receivables-idempotency.pw.mjs` und ein
separater Restart-Test im Runner. Die derzeitigen Demo-Smokes bleiben erhalten.
Die Seiten-Paginierungsfälle mit 1.001 Datensätzen anschließend als eigene
Integrationstests ergänzen; Stammdaten dafür effizient per echter API/isoliertem
SQL-Fixtureaufbau vorbereiten, nicht durch 1.001 manuelle Browserformulare.

Golden-Path-Tests: keinerlei `route.fulfill` für Geschäftsendpunkte. Gezielt
injizierte 503-/Netzfehler gehören in eine separat benannte Resilienz-Suite.
CI-Artefakte: Trace bei Fehler, Desktop/Mobil-Screenshot, Backend-Log und relevante
synthetische Datensatz-IDs. Auth-Header/Secrets nicht in öffentliche Artefakte
kopieren; Reports enthalten ausschließlich synthetische Fachinformationen.
PostgreSQL und Server-Restart sind gesonderte Gates, nicht durch SQLite-Reload
als bereits geprüft ausweisen.

## Quellen

Repository: backend/routers/{auth,billing,rent_charges,receivables}.py,
backend/repositories/finance_repo.py, backend/config.py, backend/paths.py,
backend/db/migrations/env.py; fachliche Ausgangstests test_billing_workflow.py
und test_payments.py. Browser-Agent: f39863b, frontend/e2e/*.

[1] https://playwright.dev/docs/ci (Worker, Browserinstallation und CI)
[2] https://playwright.dev/docs/api-testing (Setup und echte API-Nachprüfungen)
[3] https://playwright.dev/docs/test-webserver (isolierter Serverstart)
