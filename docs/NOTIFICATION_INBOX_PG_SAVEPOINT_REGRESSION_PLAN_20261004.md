# PG-Fixture-Savepointverträglichkeit: abgegrenzter Vorcodeplan

Eigener vorhandener Checkout `work/dashboard-notification-timestamps`.
Root-Sid2-Lauf: zwei SetupERROR in15,29s, keine Raceabnahme. Root hat den
Quellenfehler konkret diagnostiziert: nach regulärem23505 im AuthSetup-Savepoint
verweigert die abortierte PGtransaktion zusätzliches set_config vor dessen
ROLLBACK TO SAVEPOINT. Produktauth bleibt unverändert. Root owns die zentrale
Supportkorrektur; kein eigener Start/Import/Collection/Test/Serverprozess.

Gelesene tatsächliche Quellen: Rootauth.SQLUserStore.create umZeile797
fängt IntegrityError nach session.begin_nested/flush regulär. Zentraler Support
notification_inbox_pg_proposal_support.before_sql setzt sonst vor jedem Statement
statement_timeout/lock_timeout über zusätzlichen DBAPIcursor. Root hat ausschließlich
RollbackToSavepointClause im compiled.statement vor dieser Zusatz-SQL ausgenommen.
after_sql prüft weiterhin die wirkliche Deadline. Nicht jede Rawsql mit Wort
ROLLBACK freistellen; diese Regression gilt für tatsächlich typisierte SQLAlchemy-
Errorrecovery. Auch SAVEPOINT/RELEASE und folgende normale DML behalten Budgets.

## Eigene neue additive Quelle

`backend/tests/test_notification_inbox_pg_fixture_savepoints.py`.
Nur pytest/SQLAlchemy/psycopg2 und vorhandener korrigierter Root-PGsupport,
keine Auth/App/Models/Storage-/Capabilityimports. Reale dedizierte URL muss
explizit vorliegen; Root-/CIloopbacktargets, UUIDschema/OID/Owner/nativeHandle-
Deadlinecleanup unverändert über tatsächliches postgres_proposal_database.
Supportdatei wird im eigenen älteren Checkout nicht nachgebaut/editiert/importiert.

Eine reine eigene Minimaldeclarativetabelle savepoint_fixture_marker mit
id-Primarykey/payload bildet genau den echten Duplicate-Key-/Abortedtx-/
Rollbackmechanismus nach. Keine Produktmetadata-/Migrations-/Auth-/Sidabnahme
aus dieser Minimalfamilie behaupten; tatsächlicher SQLUsercreate wird bereits
von Root-Sidfixture beim Nachlauf ausgeführt.

Zwei vorbereitete native Nodes, explizite ids core/orm:
test_native_duplicate_savepoints_keep_outer_transaction_usable[core/orm].

1. Erste Markerrow(id1) committed anlegen. Äußere neue wirkliche Transaktion
   schreibt davor(id2). Zweimal echten id1-Duplicate innerhalb tatsächlichem
   Connection.begin_nested bzw.Session.begin_nested/flush auslösen und jeweils
   ausschließlich IntegrityError mit realem pgcode23505 fangen.
2. Eigenes enges Engine-Event zeichnet tatsächlichen compiled
   RollbackToSavepointClause und nativeDBAPI-Transaktionsstatus vor/nach SQL auf:
   INERROR vorRollback, INTRANS nachRollback. Keine Status-/Cursor-/Authmocks,
   kein ersetztes Budgetcallback, keine rawRollback als Ersatz.
3. Eigene Roottransaktion bleibt identisch/aktiv, kein verbleibender Savepoint;
   natives SELECT und weitere DML(id3,id4) funktionieren. Beide echten erwarteten
   Savepointfehler verhindern weder späteren normalen Commit noch vorherige
   outerDML. Nach Commit tatsächliche vier Rows über neue Lease exakt prüfen.
4. Tatsächliche pg_settings zeigen nach Errorrecovery weiterhin positive
   statement_timeout≤5000ms und lock_timeout≤1500ms. Quelle darf nicht für
   gewöhnliche Statements sämtliche Budgetinstrumentierung deaktivieren.
5. Eigene Sessions/Connectionleases/Events finally schließen, Poolcheckout0;
   zentrale tatsächliche Handle-/Schema-OID/Ownercleanup behalten. Ein Folge-
   25P02/fehlender typisierter Rollback/falsche Row/Deadline/Leck ist Fehler,
   nie Skip oder positiver Auth-/Racebeleg.

## Späterer Gate und ehrliche Grenze

Nur Quellenvorbereitung. Root darf später exakt beideNodes in eigenem Slot
seriell ausführen, vorgeschlagen hard90s gesamt (je tatsächlicher zentraler
30sNode+8sCleanuprahmen). Kein eigener Nativefollowup in diesem Auftrag;
Root integriert die zusätzliche Regression und owns weitere Inboxkomposition.
Zwei vorbereitete Fälle sind keine zwei tatsächlichen PASS. Die früheren
zwei SetupERROR werden nicht nachträglich als ausgeführte Sid-Races gezählt.

Präzisierung noch vor Testsourcecommit: zusätzlich ein erfolgreicher typisierter
Savepoint/Release ohne weitere Rowmutation, damit das enge Rollback-Skip nicht
als Abschalten sämtlicher Transactioninstrumentierung missverstanden wird.
Vor der abschließenden normalen Budgetabfrage beide GUCs nur auf der wirklichen
eigenen Connection über festen direkten DBAPIset_config auf30000ms setzen.
Die folgende gewöhnliche SQLAlchemyquery muss tatsächlich wieder≤5000/1500ms
liefern; damit beweisen nicht bloß Startupdefaults die Budgets. NativeCursor
immer schließen, keine Deadline-/Auth-/Statusmockfunktion als Ersatz.
