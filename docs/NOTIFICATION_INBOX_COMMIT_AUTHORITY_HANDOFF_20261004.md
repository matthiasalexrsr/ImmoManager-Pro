# Persönlicher Einzelread: Quellenhandoff, keine native Schreibfreigabe

Eigener Checkout `work/dashboard-notification-timestamps`, Branch
`assist/dashboard-notification-timestamps`. Nur eigene neue Quellen, Tests und
Dokumentation geändert. Keine Shared-/Auth-/Router-/Registry-/Recovery-/DDL-/
Migration-/UIquelle, keine Root-/Main-/Previewänderung.

## Saubere eigene Übernahmefolge

| Commit | Inhalt |
| --- | --- |
| `8928db5` | Vorcodevertrag, vollständig gelesener Root-/Plattformlockreview |
| `3be4603` | Eigene physische Lease und genaue Witness-Lockfolge präzisiert |
| `b449e6f` | Physischer Rollback bei verworfenem Connection-Commit vor Produktcommit festgelegt |
| `16f55f0` | Reiner perItem-Candidate und 26 vorbereitete reine Parameterfälle |
| `906a7ce` | Eigener geschlossener nativer Single-read-Writer und nominelle Capability |
| `f98244e` | Tatsächliche SQLUser-/Sid-/fileSQLite-Testquellen, 35 vorbereitete Parameterfälle |

Diese Quellen wurden ausschließlich gelesen und statisch geprüft; `git diff
--check` ist sauber. **Keine** Pythonimports, Lint-/Test-/Collection-/DB-/App-/
CLI-/PG-/Browserausführung in diesem Auftrag. Kein PASS/Timing/Runtimeclaim aus
vorbereiteten Fällen. Der Root-PG-/SQLite-Zeitnachweis gehört dem separaten
UTCwriterpaket92adf0d und wird hier nicht als Schreibbeleg beansprucht.

## Konkrete Schnittstelle und Transaktionsgrenze

`notification_inbox_commit_authority.commit_notification_read(store, id,
access_token=...)` committed ausschließlich seine eigene neue Session auf einer
eigenen frischen Connection-Lease des tatsächlichen Enginebinds. Der interne
Keywordparameter stammt später nur aus dem wirklichen HTTPheader; alternativ
der tatsächliche request_authority-Context. Kein Actor-/Scope-/Belegfeld aus
JSON, keine LegacySid, kein zweiter auth touch/revoked Writer. Das Rawtoken
bleibt lokale Aufrufvariable, nicht Registry/Session.info/DB/Fehlerdetail.

Nominale Capability entsteht allein im Wrapper und wird mit tatsächlicher
Objektidentität in dessen privater Registry geprüft: ownSession/SessionTransaction/
nativeConnection/RootTransaction/Thread/Actor/Sid/Principal/Operation/Target und
konkrete Witnesses. Genau zwei bestehende stage_read-Prüfpunkte; kein zweites
Staging, Targetwechsel, Savepoint, ended/replayed/failedUnit. Öffentliches
Konstruktor-/Subclass-/object.__new__-Forge, ScopeDTO, Lambda oder Bool scheitert.
stage_read selbst besitzt weiterhin weder Commit noch Rollback.

SQLite BEGIN IMMEDIATE vor Snapshot, busy_timeout500ms nur auf eigener Lease,
Wiederherstellung der tatsächlichen alten Einstellung vor Poolrückgabe. PG
READ COMMITTED, lock_timeout1s/statement_timeout5s. Factories müssen über echte
Connections denselben Auth-/Sid-/Fachtarget belegen. Fremde aktive oder dirty
scoped Sessions werden weder übernommen noch geschlossen. Bestehende
auth_setup/User/Sid/Access/operational_lock schützen native Auth und auch noch
fehlende restrictive Dispatchzeilen; fehlende Singletons503 ohne Seed.

Frische tatsächliche Principal-/Origin-/Grant-/Sid-/Expiry-/Notification-/
Dispatch-/Parentprüfung nach Warteabschnitten und nach Flush unmittelbar vor
Commit. Session-before_commit und physischer Connection-commit bleiben bis
zum finalen Übergang geschlossen. Auch an der tatsächlichen Commitgrenze
wird Ablauf geprüft. Fehlercleanup rollt die eigene DBAPItransaktion zusätzlich
zur Session zurück, falls ein verworfener Connection-Commit deren logisches
RootTransactionobjekt schon deaktiviert hat. Diese Semantik ist erst durch
die vorbereiteten nativen Faultfälle zu belegen.

## Tatsächliche Anfangszweige und ehrliche weitere Arbeit

Unrestricted wird frisch aus SQLUserStore abgeleitet und folgt exakt der
vorhandenen `_eligibility`: keine Subjectparents relevant. Alle Subjects,
unknown/missing/partial/null eingeschlossen. Owner ignoriert Dispatchrolle;
alle anderen All-scope-Rollen brauchen ihre echte Dispatch-/Missingrowfence.

Selected zunächst zentrale Aliasziele Portfolio/Property/Unit und unlinked mit
konkretem positivem Resourcegrant. Zentrale `_parents`, RESOURCE_ALIASES,
csv_parents/scoped_clause bleiben die tatsächliche Discoverygrundlage.
Measurementboundary vor Portfolio→Property/Unit; vorhandenes lock_location,
positive User-/Resourcegrantrowlocks, tatsächlichen Zielpfad danach nachlesen.
Keine globale Parent-/Tenant-/Resourcehistorie oder Installationsstocklocks.

Andere selected CSV-/Tenant-/Contract-/Task-/Finance-/Meter-/Documentzweige
bleiben vorläufig offene fachliche Folgearbeit und geschlossen503. Der
vorbereitete echte Taskfall belegt seine lesende Eligibility zuerst und fordert
danach explizit fehlende Writerfence, statt Sichtbarkeit wegzudefinieren.

## Rootanschluss weiterhin erforderlich

1. Tatsächliche Readpaarfamilie zentral als INTERNAL klassifizieren und frühe
   Metadaten-/Migration-/Recovery-/Privacykomposition übernehmen. Der Wrapper
   verlangt echte Registrierung und Schemaform; ohne Anschluss503 vor DML.
   Keine Fixture verändert INTERNAL oder ersetzt den Scopeinterceptor.
2. Schema-/HTTPanschluss bleibt Root-/Plattformownership. Inaktive Routerquelle
   darf echten Bearerheader nur intern an den Wrapper geben; Scope entsteht aus
   der tatsächlichen bestehenden nativen Authkomposition. Kein Callback zum
   fremden Schreiben und kein Notificationproof für TEHA.
3. Globale list_inbox(read_actions_enabled=True) **nicht** aktivieren. Der neue
   reine notification_read_subject_hint ist nur Candidate nach tatsächlicher
   Eligibility, mit tatsächlich verifiziertem unrestricted und zentralem
   Aliasmapping. Selected unlinked braucht trotzdem den echten Resourcegrant.
   Der heutige öffentliche ItemDTO enthält keinen globalen Notificationstatus;
   bei späterer perItemkomposition aktive interne Projektion/Eligibility nutzen,
   persönliche read_at nicht als globalen Status- oder Authoritybeleg deuten.
4. Vor HTTPwritefreigabe echte SQLite-/PG-Races in beiden Reihenfolgen für
   Sidrevoke/Expiry, User/Management/Grants/Origin, Locationrelocation und fehlenden
   restrictive Dispatchinsert. Source-/DTO-/Hinttests ersetzen diese nicht.

## Kleinstmögliche spätere Gates, erst nach Rootfreigabe

Reiner Candidate: `test_notification_inbox_read_support.py`, 26 vorbereitete
Fälle, ein Prozess `--noconftest`, vorgeschlagen hard20s. Keine DB/Authimports
in dieser Datei oder dem Hintmodul.

Vor zentraler INTERNALregistrierung ausschließlich diese drei eigenen Nodes:

- `test_wrapper_rejects_legacy_sid_and_wrong_real_actor_before_read_dml`
- `test_nominal_constructor_subclass_and_unregistered_forges_are_denied`
- `test_pre_registration_is_closed_before_native_read_dml`

Native fileSQLite-/actualSQLUserfixtures, vorgeschlagen hard45s für diese drei.
Der letzte Node verlangt ausdrücklich fehlende echte Registrierung und gehört
nach Rootanschluss **nicht** mehr zur positiven Auswahl; kein künstliches
Entfernen der Registrierung für einen grünen Test.

Nach realem Rootanschluss zuerst kleinster tatsächlicher Grund-/Commitgate,
acht Parameterfälle, vorgeschlagen hard90s:

- unrestricted `[unknown]` (Owner und tatsächlicher All-reader,
  insert-once und persönliche Unabhängigkeit)
- selected `[unit]` und `[unlinked]`
- tatsächlicher All-scope-Dispatch/Ownerbypass
- eigene Session versus dirty caller
- `test_closed_commit_boundaries_roll_back_actual_first_read_dml`
  `[session_commit]`, `[connection_commit]`, `[savepoint]`

Die sieben unrestricted Parameter haben explizite stabile ids; die übrigen
Failure-/Subjectnamen stammen aus einparametrigen Stringquellen. Kein eigener
Collectionstart zur Bestätigung in diesem Quellenauftrag.

Der gesamte vorbereitete native Quellbestand zählt35 Parameterfälle; nach Registrierung34,
einschließlich acht tatsächlicher Sameconnection-Rollbackänderungen. Die Auswahl
mit zwei zuvor schon ausgeführten prereg-Negativfällen ergibt keine neue
Racesumme. Restliche gezielte native Auswahl nach tatsächlichem Erstgatebudget
separat abstimmen; keine PG-/HTTP-/Browserstarts implizit freigegeben.

Die Sameconnection-Änderungsfälle sind bewusste eigene Stage-Failureinjections
nach wirklichem DML und eigener wirklicher Capability. Sie beweisen später
Rollback/Finalrecheck, **keine** unabhängige Verbindung oder Linearisationrace.
Neue PG-Zweiverbindungsfälle werden Rootseitig separat benötigt. Pools/ownSession/
Capabilityregistry/SQLitetimeout müssen nach allen tatsächlichen Gates geschlossen
beziehungsweise wiederhergestellt sein; vorbereitete Assertions sind kein schon
erfolgter Schließungsnachweis.
