# Native Fixture-Savepoints: zusätzlicher Quellenhandoff

Nur eigener Checkout `work/dashboard-notification-timestamps`; Rootsupport,
Produktauth, Writer/Registry/API/DDL/CI unverändert. Keine Imports/Collection/
Runtime-/Tests-/Serverstarts. git diff --check sauber.

Eigene Übernahmefolge:

1. `6224644`: tatsächlicher enger Vorcodeplan nach zwei Root-SetupERROR15,29s.
2. `5409f37`: erfolgreicher Savepoint/Release und wirklicher Budgetreset konkretisiert.
3. `47ff629`: zwei vorbereitete native Core-/ORM-Regressionen, nur eigene Testdatei.
4. Dieser separate Handoffcommit.

Datei `backend/tests/test_notification_inbox_pg_fixture_savepoints.py`, Blob
`4bde68c92b315575e2c224ee263e0eb0ee31d01d`.
Abhängigkeit ist tatsächlicher korrigierter Root-PGsupport1fce39f, inklusive
nativeHostaddress und enger compiled.RollbackToSavepointClause-Ausnahme vor
zusätzlichem set_config. Der Roothelper fehlt im älteren eigenen Checkout
weiterhin absichtlich; kein Nachbau und kein hier ausgeführter Import.

Reale eigene Minimalfamilie, je Core/ORM zwei echte23505-Duplicates in typisierten
Savepoints. Driver muss unmittelbar vorRollback INERROR und nachRollback INTRANS
melden. Äußere Roottransaktion bleibt identisch/aktiv; normale folgende DML und
erfolgreicher zusätzlicher Savepoint/Release bleiben möglich. Commit erhält
genau die vier tatsächlichen davor/danachRows. Keine Auth/App/Storageimports,
keine vermeintlich positive SQLUser-/Sid-/Capabilityabnahme aus Minimalmetadata.

Budgets werden zusätzlich wirklich überprüft: auf derselben eigenen DBAPI-
Connection beide Settings auf30000ms setzen, tatsächliche pg_settings direkt
bestätigen; nächste gewöhnliche SQLAlchemyquery muss wieder positive≤5000ms
statement_timeout/≤1500mslock_timeout ergeben. Keine GUC-Textdarstellungsannahme
oder bloße Startupdefaults als Ersatz. Cursor/Events/Sessions/Lease finally
schließen, Poolcheckout0 und aufgezeichnete eigene nativeHandles geschlossen;
zentrale UUIDschema-OID/Ownercleanup bleibt erhalten.

Noch **kein** PASS/Timing aus dieser eigenen Regression. Exakte spätere Nodes:

- `backend/tests/test_notification_inbox_pg_fixture_savepoints.py::test_native_duplicate_savepoints_keep_outer_transaction_usable[core]`
- `backend/tests/test_notification_inbox_pg_fixture_savepoints.py::test_native_duplicate_savepoints_keep_outer_transaction_usable[orm]`

Nur Root koordiniert Ausführung, vorgeschlagen hard90s zusammen, je tatsächlicher
zentraler30sNode/8sCleanuprahmen. Explizite dedizierte URL5432/58112, keine Skip-
oder ambientDATABASE_URL-Quelle. Danach keine eigene Nativefollowup-Arbeit.

Root meldet separat tatsächliche2Sid und6Grant/Property/Dispatch-Reihenfolgen
grün nach1fce39f; ursprünglicher GET-Parentrepro FAIL, Produkt103482a danach
echter PASS. Diese Rootprüfungen gehören dem PG-/GETpaket, nicht diesem noch
unausgeführten Fixturezusatz. Frühere zwei SetupERROR bleiben als solche erhalten.
