# Adapterhistorie – Manager/HTTP-Folgeplan

Stand: 03.10.2026. Fortsetzung des bereits vorhandenen Dirty-Checkouts
`work/integration-history`, HEAD
`edd1716d275b62b4747de36517122ab0587eb872`.

Vor weiteren Änderungen gelesen: `ADAPTER_HISTORY_PLAN_20261002.md`,
`ADAPTER_HISTORY_RUNTIME_RECOVERY_IMPLEMENTATION_20261002.md`, aktueller
Manager/Router/HistoryStore/HistoryPolicy, die bestehenden Coretests und
`work/integration-history-auth-fences-green.log` (**3 passed**). Die vier
History-Corecommits sind laut Root bereits separat integriert; dieser Checkout
liefert deshalb ausschließlich additive Manager-/HTTP-/Fence-Folgeänderungen.
Keine Root/Main/Preview-Datei und keine Runtime/Recovery-Datei dieses Pakets
wird hier verändert.

## Konkrete Fortsetzungsgrenzen

1. **Manager verwendet nur das persistente Journal.** Kein Rückfall auf den
   alten 200er-RAM-Puffer. Produktionsaufrufe ohne konfiguriertes Journal
   scheitern explizit. Unitfixtures dürfen nur einen ausdrücklich injizierten
   synthetischen Store verwenden.
2. **Accepted vor Provider-I/O, started direkt vor Provider-I/O.**
   Persistenzfehler vor `provider.run` bedeutet null Provideraufrufe.
   Providerexceptions werden als ungewisser Ausgang erfasst, ohne Exceptiontext
   oder automatische Wiederholung.
3. **Rechte werden frisch geprüft.** Authenticated HistoryActor bleibt an
   Actor+unrestricted installation scope gebunden. SQLite-Historywrites erwerben
   den echten SQL-Writer **vor** dem Memory-Accountmutex und halten das danach
   erworbene Mutex bis nach dem tatsächlichen äußeren Commit. PostgreSQL hält
   Accountcarrier/Management-Serialisierung vor dem Historyhead.
4. **HTTP bleibt installationsadministrativ.** Historyseite erhält Cursor,
   Statusfilter und Projektion; Einzelrun-GET bleibt hinter derselben
   CheckedPublicationRoute. HistoryError wird als typisierter HTTP-Fehler
   projiziert, nicht als unkontrollierter 500 oder Providertext.
5. **Redaktion ist rekursiv.** Mailpayload bleibt absichtlich leer.
   Config-/Request-/Responsewerte werden über die vorhandene
   private-json/schema-observation Policy verarbeitet. Maskierte Secretwerte
   dürfen gespeicherte Credentials nicht überschreiben.
6. **Keine stillen Bestandsgrenzen.** Manager-List/Detail/Metrics/Clear
   delegieren an das SQL-Journal; die Core-Keyset-/Budgetregeln bleiben
   unverändert. Kein neues Limit, keine TTL und kein COUNT/preload werden hier
   eingeführt.

## Abnahme dieses Folgecommits

- bestehende Manager-/Router-/Private-Boundary-Tests;
- native Accountfence-Tests erneut;
- Core-Historytests auf SQLite und verfügbarem
  `TEST_SERVER_DATABASE_URL` PostgreSQL;
- konkrete HTTP-Gates für Cursor/Detail/typed error und Auth;
- Providerfehler/Revokation ohne unkontrollierten externen Retry;
- Ruff, konfigurierte Mypy-Prüfung und `git diff --check`.

Runtime/Startup/Recovery/Reset bleiben bis zum separaten zweiten Checkout
`work/integration-history-runtime` unangetastet.
