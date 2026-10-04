# Adapterhistorie – Manager/HTTP/Fence Handoff

Basis: `edd1716d275b62b4747de36517122ab0587eb872`  
Branch/Checkout: `assist/integration-history` / `work/integration-history`

Dieser Folgebaustein übernimmt **nicht** den bereits versionierten History-Core
(Migration d2, Tabellen, Crypto, Cursor, Restore-Normalisierung). Er bindet den
bestehenden IntegrationManager und den HTTP-Router an genau diesen persistenten
Core und vervollständigt die Account-/Writer-Grenzen. Root/Main/Preview und
Runtime/Recovery wurden nicht verändert.

## Produktänderungen

- Der alte Manager-RAM-Puffer und die 200er-Abschneidung sind entfernt.
  `run`, Historyliste, Detail, Metrics und Clear delegieren an den
  SQL-HistoryStore. Ohne konfiguriertes produktives Journal gibt es keinen
  stillen RAM-Fallback.
- Vor jedem angenommenen Lauf werden Request/Config rekursiv über die vorhandene
  Private-JSON-/Schema-Policy beobachtet. Email-Payload bleibt absichtlich
  vollständig ausgelassen. Maskierte `***`-Secrets überschreiben gespeicherte
  Credentials auch in verschachtelten Strukturen nicht.
- `accepted` wird vor externem Provider-I/O persistiert;
  `execution_started` unmittelbar vor dem Provideraufruf. Persistenz- oder
  Rechtefehler davor starten keinen Provider.
- Freie Providerexceptions werden weder geloggt noch als sichere
  Nicht-Ausführung behauptet. Der Lauf endet als
  `outcome_uncertain`, `retry_automatically=False`; es gibt keinen
  automatischen Replay.
- Nicht vollständig beobachtbare Providerantworten werden als
  `observation_failed` statt als erfolgreicher Vollbeleg gespeichert.
- Router: History-Keysetseite mit Cursor/State/Projection, autorisierter
  Einzelrun-GET und typisierte `HistoryError`-HTTP-Projektion. Die bestehende
  installationsweite Owner/All-Manager-Grenze und CheckedPublicationRoute
  bleiben erhalten.
- SQLite-Historywrites erwerben `BEGIN IMMEDIATE` vor dem Memory-Accountmutex
  und halten das anschließend erworbene Mutex bis nach dem **äußeren echten
  Commit**. Dadurch wartet ein Historywriter nicht mit gehaltenem Accountmutex
  auf einen SQLitewriter, der dieses Mutex zum Abschluss benötigt.
- PostgreSQL-authenticated writes serialisieren über den realen
  `auth_setup`-Carrier vor der Historyhead-Mutation. Ein fehlender Carrier
  wird nicht automatisch repariert.

## Tests

Ausgeführt mit
`TEST_SERVER_DATABASE_URL=postgresql://immo_ci@127.0.0.1:58112/immo_ci`.
Die Core-Fixtures verwenden für PostgreSQL ausschließlich zufällige eigene
Schemas.

- `pytest backend/tests/test_integration_manager.py -q -rs --tb=short`
  → **10 passed** (SQLite + echtes PostgreSQL für jeden Managerfall).
- `pytest backend/tests/test_integrations_router.py -vv -x --tb=short`
  → **4 passed**, 1 bestehende Starlette-TestClient-Deprecation-Warnung.
  Das sind echte HTTP-Aufrufe inklusive Run/History/Metrics/Clear.
- `pytest backend/tests/test_integration_history_account_fences.py -q -rs --tb=short`
  → **5 passed**. Enthalten: reale SQLite Writer→Account-Reihenfolge,
  SQLite/PG SQL-auth-Management-Revoke bis nach Commit sowie
  fehlender Accountcarrier fail-closed.
- Das vorhandene native Greenlog
  `work/integration-history-auth-fences-green.log` dokumentiert zusätzlich
  den vorherigen isolierten Stand **3 passed**.

Ein zusammengezogener Mehrdateienlauf wurde wegen externer Testdienst-
Parallelität nach mehreren bereits grünen Fällen beendet; er wird ausdrücklich
nicht als Gate gezählt. Die oben genannten Suiten wurden jeweils abgeschlossen.

Statisch auf den geänderten Runtimequellen:
- Ruff: **grün** nach Importformatierung.
- Mypy: **Success: no issues found in 4 source files**.
- `git diff --check`: **grün** nach Entfernung einer zusätzlichen EOF-Leerzeile.

## Nicht in diesem Commit

Keine Startup-/Recovery-/Reset-Hooks, keine neue Migration, keine UI-/AI-,
Bank-, Workflow- oder Providertransportänderung. Kein Liveprovider wurde
aufgerufen. Der getrennte Checkout `work/integration-history-runtime` übernimmt
als nächstes ausschließlich Runtime/Recovery/Reset.
