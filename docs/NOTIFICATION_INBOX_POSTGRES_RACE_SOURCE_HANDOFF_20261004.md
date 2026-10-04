# Native PG-Reihenfolgen und GET-Parentrepro: Quellenhandoff

Eigener Checkout `work/dashboard-notification-timestamps`, clean Produkt-/
Testsource1691557; ausschließlich neue eigene Plan-/Test-/Handoffquellen.
Root/Main/Preview, Writer/Auth/Registry/Router/Recovery/Schema/Migrations unverändert.
Kein eigener Import-/Lint-/Collection-/Test-/DB-/App-/CLI-/PG-/Serverstart.
`git diff --check` sauber. Sämtliche elf Fälle **vorbereitet, nicht ausgeführt**.

## Übernahmefolge

1. `2826de0`: konkreter Vorcodeplan, tatsächliche Writer-/Fence-/PGfixturepfade.
2. `b8b80d9`: ergänzter GET-Publikationsrepro ausdrücklich vor dessen Code.
3. `cfb77ce`: neue `backend/tests/test_notification_inbox_postgres_read_races.py`,
   elf vorbereitete Parameterfälle, nur Testcode.
4. `1691557`: explizite stabile IDs der acht Raceparameter, keine Assertionänderung.
5. Dieser separate Dokumentationscommit.

Testblob am1691557: `af98be9d55f960e662e25abcbd8a2e5963fd3913`.
Abhängige echte Rootquellen: registriertes INTERNAL e3f399d, unveränderter
Produktwriter68aeffd, zentraler PGsupport fcfbd34/a5569d8 mit tatsächlicher
Addresskorrektur3c96be9. Die Roothelperdatei wurde im älteren eigenen Checkout
weder nachgebaut noch importiert; tatsächliche Ausführung erfolgt erst nach
Rootkomposition. Eigene Create-all-Fixture ist kein M2-/Upgrade-/Recoverybeleg.

## Tatsächliche neue Quellenbedingungen

Explizite TEST_SERVER_DATABASE_URL ausschließlich synthetisches immo_ci/immo_ci
localhost/127.0.0.1 auf Root58112 oder CI5432, ohne Queryparameter/Skip/fallback.
Bestehender Helper prüft echte Nativeaddress/Server/User/DB/Port/UUIDschema und
trackedDBAPIhandles. Zusätzliche Engines verwenden unverändertes _engine/_close
im selben wirklichen Schema. Keine private/public-Fachtabelle oder Serviceaktion.

Je pool_size1 für Business, Accounts, Sid, Mutation und Observer. change_first
Reader stoppt erst nach eigenen Auth-/Sididentityproben vor auth_setup-FORUPDATE;
dadurch ist ein später gehaltener Factorypool kein Ersatz für Rowlockblockierung.
Reale SQLUserStore/sessionmaker/login_pair-Sids und native Scope-/Credential-
Contexts, keine Authgetter-/Actorlambda-/Capabilityfakes und keine INTERNALmocks.

change_first hält tatsächliche MutatordML vor Commit; Reader muss serverseitig
an dessen wirklichem PID blockiert sein. read_first hält echte erste Read-DML
mit wirklicher issued Wrappercapability; Mutator muss serverseitig am ReaderPID
blockiert sein. pg_blocking_pids ist Pflichtassertion, Event/Pending allein reicht
nicht. Native Reader-/Mutator-/Observer-PIDs sind verschieden. Nach Restriktion
wird tatsächliche Mutation gelesen, Readpaar/noRead und reauthentisierte Replay-
Verweigerung geprüft. Ein geordneter erster Read bleibt erhalten.

Mutatoren: echter revoke_from_token; echter SQLUserStore.update durch Owner;
echter SQLAlchemyStore.update_property durch Owner/request_authority; fehlender
restrictive Dispatch als ausdrückliche synthetische native Rowmutation unter
bestehendem operational_schedule._transaction(captured=None). Letzteres behauptet
keine neue fachliche Tickzuordnung zu beliebigen Usernotifications. Normale Grant-
und Propertywriter können bereits am Managementlock blockieren; diese Fälle
belegen später Gesamtlinearisation und keinen isolierten Parent-/Grantlock ohne
vorgelagerten Managementlock. Dispatchfall verwendet tatsächliche Operationalfence.

Additional Receiptfall: gleicher erster read_at bei Wiederholung, je tatsächlichem
Actor genau ein Paar, keine erfundenen Commandbelege. Timeoutfall: reale native
Managementblockade →409, keine Read-DML/issuedProofs, Blockerrollback →wirklicher
erfolgreicher Retry. Keine genaue 1s-Laufzeitbehauptung: der bestehende Support
setzt pro Statement zusätzliche Fixturebudgets (max1,5sLock/5sSQL).

Thread-/Connectioncleanup ist als echte Assertion vorbereitet: Gateevents finally
freigeben, boundedjoin, gegebenenfalls nur tatsächliche recordedOwnHandles canceln,
kein Server-/Servicekill. Registry leer, Pools ohne Checkouts, nur tatsächliche
eigene PIDs ohne idle-in-transaction, tracked nativeHandles nach Cleanup geschlossen.
Zentrale Namespacecleanup prüft OID/Owner und entfernt ausschließlich eigenes Schema.

## Getrennter lesender Parent-Publikationsverdacht

Quellenbefund `notification_inbox.py`: _snapshot umfasst Counts/Itemeligibility;
zweiter _fresh_principal vergleicht echte Account-/Origin-/Grants erneut, aber
keine bereits ausgewählten Itemparents außerhalb dieses alten Fachdatenbestands.
Der vorbereitete GETcase hält unverändertes list_inbox nach tatsächlicher bounded
Contentprojektion an, verschiebt Property über echten Ownerwriter und fordert
identische tatsächliche Actor/Origin/Grants. Danach nur403/409-Konflikt oder leere
Livepage/counts0 erlaubt. Kein 503-/Fixturefehler als positiver Scopebeleg.
Diese Quelle ist **noch kein ausgeführter Scopeleak-/FAILnachweis** und gehört
zu GETpublikation, nicht zur positiven Single-read-Capabilityabnahme.

## Exakte Rootauswahl, noch kein nativer Slot freigegeben

Gemeinsamer Präfix:
`backend/tests/test_notification_inbox_postgres_read_races.py::`

Zuerst zwei tatsächliche Sidnodes seriell, vorgeschlagen hard90s gesamt:

- `test_postgres_independent_read_restriction_orders[sid-change-first]`
- `test_postgres_independent_read_restriction_orders[sid-read-first]`

Weitere sechs tatsächliche Races separat, vorgeschlagen hard240s:

- `test_postgres_independent_read_restriction_orders[grant-change-first]`
- `test_postgres_independent_read_restriction_orders[grant-read-first]`
- `test_postgres_independent_read_restriction_orders[property-change-first]`
- `test_postgres_independent_read_restriction_orders[property-read-first]`
- `test_postgres_independent_read_restriction_orders[dispatch-change-first]`
- `test_postgres_independent_read_restriction_orders[dispatch-read-first]`

Zwei Receipt-/Timeoutnodes separat, vorgeschlagen hard90s:

- `test_postgres_native_receipt_is_insert_once_per_real_actor`
- `test_postgres_real_lock_timeout_cleans_own_unit_and_retry_succeeds`

Ein GETrepro separat, vorgeschlagen hard45s:

- `test_postgres_live_get_rechecks_published_parent_after_actual_owner_move`

Jeder Node tatsächlicher eigener30sFixture-/8sCleanuprahmen. Kein eigener
Collector zur ID-/Countbestätigung gestartet. Root koordiniert tatsächliche
Serverquelle/Freeze/Slots; Ergebnisse, Quellefehler versus Fixture-/Infrafehler,
Dauer und normale Schließung erst nach wirklicher Ausführung berichten.

Rootvorherige26Hint+17Fixtureguards,3prereg und8+24SQLitefälle sind separat
belegt und werden hier nicht erneut gezählt. Kein PG-/HTTP-/Browser-/Migration-/
Recovery-/TEHAproof aus vorbereiteten Sources oder SQLitekomposition ableiten.
