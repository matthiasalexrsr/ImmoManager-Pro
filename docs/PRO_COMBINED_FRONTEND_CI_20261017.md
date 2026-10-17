# Gemeinsame Frontend-, Backend- und Abrechnungsintegration – 17.10.2026

**Entwicklungscheckpoint, keine Freigabe.** Arbeitszweig
`pro/stage-billing-combined-20261017`, entstanden als
`c36f5e89` (Frontend `b209025a` sauber über Backend
`cc099121`) plus additive Cherry-Pick-Übernahme
`00975e5e` (Messabdeckung, neuer Stand `312660a0`).

Die zentrale Referenz `claude-review-20261013` blieb
bei `04021da5` unverändert. Keine laufenden Installationen
(8000/8765), Benutzerdateien, externen Bankverbindungen oder
Fremdprovider wurden zum Test benutzt.

## Was hinzugekommen ist

- Der vollständige, separat mit 657 Tests abgenommene Frontendstand
  wurde ohne Konflikt auf den aktuellen Backendstand übernommen.
  Fehlende/defekte Benachrichtigungsantworten erzeugen dort einen
  sichtbaren wiederholbaren Fehler, keine leere Erfolgsliste.
  Nachrichtenthreads, späte Antworten und Entwürfe benutzen wieder
  die tatsächlich vorhandenen Cursor-/Quittungs-APIs.
- `utility_billing._consumption_shares` erkennt jetzt eine echte
  Lücke zwischen Ausbau und Wiedereinbau von Zählern als
  `METER_SERVICE_GAP`-Blocker. Absichtlich parallele Messstellen
  werden unterscheidbar zur Entscheidung gemeldet, nicht
  automatisch als Ersatz gefälscht.
- Die CI-Datei `.github/workflows/ci.yml` hatte **zwei
  reproduzierbare Umgebungsdefizite**: Im Backend-Job fehlte die
  echte, für einen verpflichtenden Test benötigte Bibliothek
  `fints==5.0.1`; der Frontendjob startete alle 657 Tests
  unbeschränkt mit fünf Sekunden Standardtimeout, während
  der grüne vollständige Regressionstest mit zwei Workern
  und 15 Sekunden Timeout nachgewiesen worden war.
  Jetzt installiert jeder Memory-/SQLite-Job das optionale
  `requirements-bank.txt`-Dependency-Set in einen separaten
  Testpfad und lässt es nur im Testlauf über `PYTHONPATH`
  zu. Keine Änderung der Grund-Runtimeabhängigkeiten.
  Das Frontend führt die volle, unveränderte Auswahl mit
  `--maxWorkers=2 --testTimeout=15000 --reporter=dot` aus.
- Der native PostgreSQL-Gate `check_postgres.py`, die
  Produktivoriginale, Auth-/Scope-Prüfungen, Browserabnahme
  und das Deployment-Gate der CI wurden **nicht aufgeweicht**.

## Nachweise nach tatsächlichem Codehash

- Exakter zusammengeführter Frontend-/Backendstand
  `c36f5e8970eb525b11692ee81501f0fb4ac8f054`:
  `artifacts/pro-tests/combined-full-frontend-1fc6e3f796bc4bebbdf24a521beab424`,
  `npm ci --ignore-scripts`, ESLint, Vite-Produktionsbuild
  und **104/104 Dateien, 657/657 Tests bestanden**. Die Vite-Warnung
  zum gemischten statischen/dynamischen NotificationInbox-Import
  war nicht buildblockierend; der Build schloss mit Exitcode 0.
- Derselbe Code plus Meterwechselcheckpoint
  `312660a0592e26fdacee88119bb4ca7a5f26d579`:
  `artifacts/pro-tests/billing-joined-312660a0-memory-e99b7b5403aa460e971bef85455935c7`
  **52/52 Memory** und
  `artifacts/pro-tests/billing-joined-312660a0-sql-c824f51b0503463092fd233bd235f625`
  **52/52 SQLite**, jeweils ohne Skip.
- Ruff gesamtes Backend und Mypy `--platform linux`
  **563 Quelldateien ohne Fehler**.
- `artifacts/pro-tests/ci-fints-library-memory-a88936e81801405e9dfacc17ce8bc84d`:
  **1/1** echter `fints==5.0.1`-Wire-/TAN-Vertrag, vollständig
  offline, keine Netzbank. Die isolierten Paket-METADATA-Bytes
  stimmen mit dem bewährten Paketverzeichnis überein
  (SHA256 `9C781C920864658CFEF0C734AA68EF7872C0F41AF0EE7B235E25D7A6F2D718D8`).
- Die CI-Datei wurde mit `js-yaml` aus dem **frisch installierten**
  unveränderten Frontend-Dependency-Set geparst; geprüft wurden
  die vier Jobverträge, konkrete Worker-/Timeout-Parameter
  und die gesetzte optionale Testbibliothek.

## Was damit ausdrücklich NICHT nachgewiesen ist

Der vollständig aktuelle Backend-/Coverage-Lauf für den
zusammengeführten Code wurde separat gestartet:
`artifacts/pro-tests/combined-c36f5e89-fullmemory-memory-512cb0c54a6a4f9393fefb5494e8c341`.
Er wurde **nicht** als Erfolg in dieses Dokument hineingeschrieben,
bevor JUnit/Exitcode und die Skips tatsächlich vorliegen.
Auch der native PostgreSQL-Gesamtlauf, der vollständige
SQLite-Backendlauf, der echte GitHub-CI-Lauf nach Push und
Browser/Restore mit einem einheitlichen Vollbestand
**auf dem finalen Mergehash** fehlen noch.

Weder die unabhängig entwickelten Eigentümerwechsel-,
Mieterportal-, Marketing-/Kanal-, Dokument-/Abrechnungs-,
Planungs- und Operationspakete noch echte autorisierte
TEHA-, Bank-, DATEV-, WISO-, Post-, WhatsApp-, Portal-
oder Aktenwerk-Gegenstellen sind durch diese
Zusammenführung fertig abgenommen. Kein Auslieferungs-Go.
