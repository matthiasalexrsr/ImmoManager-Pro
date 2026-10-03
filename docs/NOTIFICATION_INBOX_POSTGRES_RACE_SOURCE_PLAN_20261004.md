# Persönliche Inbox: unabhängige PG-Races vor Code festgelegt

Abgegrenzter Quellenauftrag von Root, eigener bestehender Checkout
`work/dashboard-notification-timestamps`. Keine Shared-/Auth-/Capability-/
Registry-/Migrationsänderung, keine Imports/Collection/Runtime/Tests/Serverstarts.
Neue Quelle ausschließlich
`backend/tests/test_notification_inbox_postgres_read_races.py`, danach Handoff.

Root hat26Hint+17Fixtureguards PASS0,76s und3prereg PASS8,52s ausgeführt;
INTERNAL real in e3f399d registriert. Root tatsächliche erste8 SQLitefälle
PASS24,08s undweitere24 PASS74,47s; mit zwei frühen Negativfällen34 unterschiedliche
aktuelle Fälle komponiert. Kein hier ausgeführter Gate und kein daraus bereits
abgenommener PG-/Linearisation-/HTTPwrite. Writerstand68aeffd unverändert.

## Tatsächliche Abhängigkeiten und Target-/Cleanupvertrag

Root fcfbd34/a5569d8
`backend/tests/notification_inbox_pg_proposal_support.py` vollständig gelesen.
Wiederverwenden: dedicated_url, postgres_proposal_database, _engine, _close,
remaining, NODE_SECONDS30 undCLEANUP_SECONDS8. Keine zusätzliche Queue oder
eigene schwächere URL-/Namespaceprüfung. Nur explizites
TEST_SERVER_DATABASE_URL, synthetisches immo_ci/immo_ci auf localhost/127.0.0.1
und CI5432 oder Root58112; beliebige URLqueryparameter abweisen. Keine Skip-/
fallback-/ambientDATABASE_URL-Quelle. Root korrigiert den bewiesenen inet-
Addressguard von ::text (127.0.0.1/32) auf pg_catalog.host(inet_server_addr());
die neue Quelle verlangt dessen korrigierten tatsächlichen Helperstand.

Der zentrale Support erzeugt/prüft UUIDschema, OID/Owner, Deadline/SQL-/Connect-
Budgets und tatsächliche DBAPIhandles. Derselbe wirkliche Schema-/DB-/User-/
Server-/Porttarget gilt für getrennte eigene Engines: Reader/business, Accounts,
Sidfactory, Property/Dispatchmutator und Observer. Je pool_size1 reicht nur mit
folgender Reihenfolge: Actor-/Auth-/Sididentityproben des Readers zuerst beenden,
bevor der Mutator seine Factoryconnection dauerhaft hält. Keine künstliche
Poolgrößenmutation oder Factorylambda. Tatsächliche sessionmaker/SQLUserStore,
reale moderne login_pair-Sids, zwei ausgewählte/read-only Actors und Owner.

Fixture ist explizites create_all in einem eigenen Schema, kein M2-Migrations-
oder globaler Registrybeleg. DocumentVersion-FKmetadata konkret registrieren.
Positive Quellen verlangen Root-INTERNAL, setzen es nicht. Centralhelper bleibt
abhängige Rootquelle; im alten eigenen Checkout nicht eigenmächtig nachbauen.

## Acht echte Reihenfolgen und konkrete Mutationen

Parameternamen: family=sid/grant/property/dispatch, order=change_first/read_first.

- Sid: tatsächliches auth_sessions.revoke_from_token auf dem wirklichen
  Readercredential, keine ersetzte Authgetter-/Sidfunktion.
- Grant: tatsächliches SQLUserStore.update durch tatsächlichen Owner:
  reader-a selected von p-one nach p-two. Management-/Grantwriters unverändert.
- Propertyparent: tatsächliches SQLAlchemyStore.update_property durch Owner
  mit wirklichem request_authority-Context, bestehende Parent-/Measurementfences;
  property-one vonp-one nachp-two, unit-one bleibt tatsächlich dessen Kind.
  Diese normale Produktwriter-Race belegt Gesamtlinearisation einschließlich
  vorgelagertem Managementlock, keinen isolierten Propertylock ohne diesen.
- Missing restrictive Dispatch: tatsächliche neue OperationalDispatchORM-Zeile
  für das geprüfte Notificationtarget innerhalb bestehender
  operational_schedule._transaction(captured=None). Echte vorhandene native
  Operationalfence und gespeicherte target_role=verwalter. Explizite synthetische
  Rowmutation unter diesem vorhandenen Ticktransactionvertrag; nicht behaupten,
  dass ein normaler Tick einem beliebigen Usernotice nachträglich eine solche
  Dispatchzeile zuordnet. Kein fiktiver allgemeiner Parentbeleg.

change_first: Reader aus tatsächlichem SQLAccount startet und hält vor der
ersten auth_setup-FORUPDATE-Query an, **nach** eigenen Identityproben. Mutator
führt tatsächlichen Produkt-/nativen Fenceweg aus; eigener eng begrenzter
Session-before_commit-Hook flushed seine echte DML und pausiert vor Commit.
Reader weiterlaufen lassen; reale pg_blocking_pids(readerPID) muss mutatorPID
enthalten. Erst dann Mutator freigeben. Reader verweigert401(Sid),403(geänderter
captured Grant),404(neuer Propertyscope/Dispatchrole), ohne Readpaar.

read_first: eigene Stageübergangsinstrumentierung ruft unverändertes echtes
stage_read mit ausschließlich wirklicher Wrappercapability auf, prüft tatsächliche
erste Read-DML und pausiert danach. Mutator beginnt auf unabhängiger native
Connection; pg_blocking_pids(mutatorPID) muss readerPID enthalten. Erst dann
Readercommit freigeben, anschließend Mutatorcommit. Kein Handler-/Event-/Bool-
Fakestatus ersetzt diesen serverseitigen Blockingbeleg.

Observer liest nur pg_catalog-Metadaten der tatsächlich eigenen PIDs, niemals
SQLquerytexte/Credentials/private/public-Fachdaten. Reader-/Mutator-/Observer-
PIDs müssen verschieden sein. Events steuern Reihenfolge; jedes Warten ist
bounded bis echter Deadline. Keine sleep-basierte Vermutung von Blockierung.

## Replays, Timeout und reale Bereinigung

Nach read_first bleibt genau das geordnete persönliche Paar mit unverändertem
ersten read_at bestehen. Neues tatsächliches Requestscope und alter moderne
Credential nach gewonnener Restriktion verweigern Wiederholung; dieses 401/404
ist kein rückwirkender Rollback des geordneten ersten Reads.

Zusätzlicher eigener receipt_insert_once-Fall ruft Wrapper wiederholt mit
wirklicher Nativeauth auf und fordert denselben ersten read_at, je Actor genau
ein Paar und unabhängige persönliche Reads. Kein erfundener Commandreceipt.

Zusätzlicher eigener lock_timeout_cleanup-Fall hält auth_setup über tatsächliche
native Managementfence auf unabhängiger Connection. Reader muss wirklichen
409-Timeout statt Erfolg liefern, kein Paar/keine gültige Capability behalten.
Blocker rückrollen, tatsächlichen Reader erneut erfolgreich ausführen. Pools/
eigene Session/Registry/nativeHandles/idle-in-transaction-Zustände anhand
wirklicher eigenen Verbindungen prüfen. Support begrenzt fixtureQuerylocks auf
höchstens1,5s und SQL auf5s; das ist kein genauer 1s-Produkt-Timingbeleg, weil
der Support pro Statement eigene Sessionbudgetinstrumentierung setzt.

Threadcleanup: beide Gateevents in finally freigeben, ownThreads bounded join,
bei Deadline nur aufgezeichnete eigene DBAPIhandles canceln und wieder joinen;
kein Dienst-/PID-/Serverkill. Alle eigenen Sessions schließen, extraOwnedEngines
über _close, dann zentrale UUIDschema-OID/Ownercleanup. Lebender Thread, Pool-
checkout, nichtgeschlossener nativeHandle oder fehlende eigene Schemabereinigung
ist Fehler, niemals Skip/PASS.

## Späterer tatsächlicher Gatevorschlag

Zehn vorbereitete PGparameterfälle, keine Ausführung in diesem Auftrag. Zuerst
genau Sid change_first/read_first seriell, hard90s für zwei Nodes einschließlich
je30sNode+8sCleanup. Danach weitere sechsRaces, Receipt undTimeoutcleanup in
eigenem Rootslot, vorgeschlagen hard330s gesamt. Vor jedem Gate echter Freeze,
genaue Nodes, dedizierter Rootserver und keine parallele native Last. Tatsächliche
Dauer/Fixture-/Produktfehler/Timeouts werden erst nach Ausführung berichtet.

## Zusätzlich vor Code: GET-Publikationsrepro mit echter Parentänderung

Rootauftrag nach unabhängiger Quellenprüfung: list_inbox hält den bestehenden
RepeatableSnapshot für Eligibility/Counts/Seite; dessen zwei frische SQLAccount-
Prüfpunkte vergleichen Principal/Origin/Grants, aber lesen die Itemparents nicht
außerhalb dieses früheren Fachdatenbestands erneut. Dies ist ein offener
Quellenverdacht, ausdrücklich noch kein ausgeführter Leak-/FAILnachweis.

Zusätzlicher elfter Node
test_postgres_live_get_rechecks_published_parent_after_actual_owner_move:
produktlist_inbox unverändert mit wirklichem selected Reader starten. Eigenes
after_cursor_execute-Event hält nach der tatsächlichen bounded Notification-
Contentprojektion an. Unabhängiger wirklicher Ownerwriter verschiebt
property-one vonp-one nachp-two über SQLAlchemyStore.update_property und
committed. Actor/Origin/Grants aus SQLUserStore vorher/nachher bleiben identisch;
NativeReader-/Propertywriter-PIDs müssen verschieden sein. Danach GET fortsetzen.

Geforderte sichere Publikation: tatsächlicher403/409-Konflikt oder wirklich leere
Livepage mit full_count/unread_count0, weil das einzige Target jetzt außerhalb
des unveränderten Readscopes liegt. Eine unveränderte ScopeDTO allein ist kein
Parentrecheck. Es wird weder _fresh_principal noch eine Authgetterfunktion
ersetzt. Reader/Writer/Pool/Schema finallyCleanup wie oben; optional erster
separater tatsächlicher Rootgate hard45s (30sNode/8sCleanup). Ein unerwarteter
503/Fixturefehler ist kein positiver Scopebeleg. Mit diesem Zusatz elf nur
vorbereitete Parameterfälle, noch keinerlei Runtimeausführung.

Rootactualsupportquery3c96be9 ist inzwischen gelesen: ausschließlich
pg_catalog.host(pg_catalog.inet_server_addr()) an der früher fehlerhaften
Addressdarstellung. Diese zentrale Korrektur ist echte Quellabhängigkeit.
