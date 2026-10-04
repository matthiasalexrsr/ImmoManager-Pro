# Adapterhistorie – Runtime/Recovery Resume-Addendum

Stand 03.10.2026. Fortsetzung des vorhandenen Dirty-Checkouts
`work/integration-history-runtime`, HEAD
`4eb7d0af868bf692adf6a479057797723b1e035a`. Alle vorhandenen Änderungen
werden erhalten; Root/Main/Preview bleiben unberührt.

Vor weiterer Codearbeit gelesen: Runtime-/Recovery-Plan, aktuelles
`recovery_history.py`, Settings-, Startup-, Transfer-, Reset-, Full-Recovery-
und Session-Restore-Hooks sowie die bereits angelegten Runtime-Gates.

## Verbindliche Grenzen

1. Die History bleibt dieselbe echte SQL-Familie auf `DATABASE_URL`, auch
   wenn die Fachdaten bewusst im MemoryStore laufen. Kein RAM-Historyfallback
   und keine private Produktdatenbank als Testfallback.
2. Retention prüft nur echte Run/Event/Chunk-Fakten. Technische Heads und
   minimale Clearbelege dürfen Business-Subset-/Reset nicht dauerhaft sperren
   und werden von Domain-`clear_all` nicht gelöscht.
3. **SQLite:** gemeinsamen Historywriter zuerst erwerben, danach MemoryAuth und
   Domainlock; die Historybarriere bleibt bis nach tatsächlicher
   Memory-Veröffentlichung/äußerem SQL-Commit gehalten. Dadurch entsteht keine
   Writer→Account/Account→Writer-Inversion.
4. **PostgreSQL:** Account-/Managementcarrier vor Historyhead bzw.
   Retentionfence; der Reset-/Importpfad hält die passende Callertransaktion und
   darf fremdes Pending-DML weder flushen noch committen.
5. Vollrecovery validiert die unveränderte History mit der **archivierten**
   Schlüssel-/Budgetkonfiguration vor Rebasing, Claimreset, Sessionentzug und
   neuer Sicherheitskonfiguration. Fehlende ganze Legacyfamilie bleibt
   kompatibel; teilweise Familie, falscher Schlüssel/AAD oder beschädigte
   Chunks fail-closed.
6. Gestartete, nicht terminal bestätigte externe Aktionen werden beim Restore
   nur als ungewiss normalisiert. Kein Provideraufruf, kein automatischer Replay
   und keine erfundene Nicht-Ausführung.
7. Keine neue Migration: d2 ist Core, e2 Billing folgt separat. Dieser Checkout
   ändert keine History-Coretabellen.
8. Der native Plattform-Agent arbeitet parallel am DDL-freien Startup. Die
   vorhandenen `db/session.py`/`dependencies.py`-Startupänderungen dieses
   Checkouts werden nicht eigenmächtig auf eine konkurrierende Architektur
   umgebaut; eventuelle Überlappung wird im Handoff explizit benannt.

## Abnahme

- eigene Memory-, SQLite- und echte PostgreSQL-Gates mit zufälligen
  PostgreSQL-Schemas;
- Writer/Auth-/Resetreihenfolge ereignisgesteuert, keine Sleeps als Beweis;
- Subset Export/Replace, SQL/Memory clear, Pending-DML;
- verschlüsseltes Vollbackup/Restore, falscher Key/AAD/Budget, Legacy ohne
  Familie, begonnener Lauf → ungewiss;
- Sessionrestore: Historyproof vor Sicherheits-DML und gemeinsamer Rollback bei
  spätem Fehler;
- Ruff, konfigurierte Typprüfung, `git diff --check`.

Startup-DDL wird wegen des parallelen Plattformpakets als Integrationskonflikt
markiert, nicht still als endgültige Rootlösung behauptet.
