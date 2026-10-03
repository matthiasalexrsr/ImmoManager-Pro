# Persönlicher Einzelread: konkret freigegebener Vorcodevertrag

03.10.2026; eigener Checkout `work/dashboard-notification-timestamps`.
Rootauftrag und vollständig gelesener zentraler Vertrag:
`docs/NOTIFICATION_INBOX_ROOT_COMPOSITION_PLAN_20261003.md` am Rootstand8703b60,
insbesondere unabhängiger Plattform-Lockreview ab dessen Zeile90.
Kein eigener Runtime-/Import-/Test-/App-/DB-/PG-/Browserstart.

## Eigene neue Quellen und Schnittstellen

- `backend/services/notification_inbox_commit_authority.py`: tatsächlicher
  nomineller Beleg und geschlossener own-Session-Wrapper, keine Yield-/Callback-
  Writeunit für fremde Fachaktionen.
- `backend/services/notification_inbox_read_support.py`: reine unverbindliche
  Subjectformhinweise für spätere perItem-UI-Metadaten. Keine Auth/DB/Storeimports,
  keine Capability und keine pauschale Handlungserlaubnis.
- `backend/tests/test_notification_inbox_commit_authority.py`: vorbereitete
  tatsächliche fileSQLite-/SQLUser-/Sidquellen und Negativ-/Rollbackfälle.
- `backend/tests/test_notification_inbox_read_support.py`: reine Formhinweise;
  tatsächliche Capability bleibt davon unabhängig.

```python
def commit_notification_read(store, notification_id: str, *, access_token=None
                             ) -> NotificationReadResult: ...
class NotificationReadCommitAuthority: ...
def require_notification_read_authority(db: Session, notification_id: str,
                                       proof: NotificationReadCommitAuthority
                                       ) -> InboxPrincipal: ...
def notification_read_subject_hint(*, status: str, unrestricted: bool,
                                  entity_type: str | None, entity_id: str | None,
                                  resource_aliases: Mapping[str, str]) -> bool: ...
```

Optionales access_token ist ausschließlich interner Rootheader-/Domainparameter;
sonst tatsächlicher request_authority-Context. Kein Request-DTO-Feld für Actor,
Scope oder Beleg. Rawcredential bleibt nur lokale Aufrufvariable: nicht in
Capability, Registry, Session.info, DB, Logs oder Fehlerdetail übernehmen.
Nur decode_signed_token, moderne accessSid/session_version1, niemals touch,
decode_token oder is_token_revoked/zweiter Authwriter. Refreshgeneration ist
nicht session_version. Fehlende/legacySid verlangt erneute Anmeldung.

## Native Auth- und Transactiongrenze

Wrapper verlangt tatsächlichen SQLUserStore und eigenen neuen Session auf dem
echten Enginebind; kein fremder Connection-/SessionTransactionbind. Aktueller
Scope muss vorhanden sein und dem tatsächlichen gesperrten Actor entsprechen.
Account- und Sidfactory müssen jeweils über wirkliche Connections dieselbe
physische SQLitehauptdatei bzw. PG-Server-/Database-/Schemasignatur besitzen.
Keine Memory-/Legacy-/Crossdbfallbacks.

SQLite BEGIN IMMEDIATE vor jedem Auth-/Fachsnapshot; kurz begrenzter eigener
busy_timeout mit Wiederherstellung. PG READ COMMITTED, lock_timeout1s und
statement_timeout5s vor erstem contended Lock. Tatsächliche Reihenfolge:
**vorhandener auth_setup → User → Sid → Access → vorhandener operational_lock →
Measurementboundary → Portfolio → Property/Unit → konkrete positive Grantzeugen →
Notification/Dispatch**.
Fehlende Singletons/Familien:503, niemals seed/DDL/Repair. Managementlock lebt
bis Commit; Rotation User→Sid und Revoke/Touch Sid-only bleiben kompatibel.

Signedclaims nach jedem wartenden Auth-/Parentlockabschnitt und nach Flush
erneut prüfen. Native aktiver User, vollständiger Principal/Origin/Grants und
Sid-user/revoked_at/expires_at werden in der gehaltenen tatsächlichen Connection
nachgelesen. Ende unmittelbar vor Commit, danach keine Fachaktion. Ablauf auch
unmittelbar an der physischen Commitgrenze prüfen.

Nomineller Beleg nur innerhalb Wrapper durch private identitätsgeprüfte Registry:
exakte Session, SessionTransaction, native Connection/Transaction, Thread,
Actor/Sid/Principal, operation=notification_inbox.mark_read/1, Notification-ID
und tatsächlich erworbene Witnesses. Öffentlich konstruierte Klasse, subclass,
object.__new__-Forge, bool, Lambda, kopierter ScopeDTO, andere/ended/failed/
nested Transaktion oder Targetwechsel akzeptiert niemand. Beleg erlaubt exakt
die zwei vorhandenen stage_read-Prüfpunkte, keine zweite Stageoperation.
Session-before_commit und Connection-commit sind bis expliziter Finalprüfung
geschlossen; eigenes Savepoint-/Endereignis invalidiert den Beleg. Wrapper
committed/rollt nur seine eigene Session zurück; stage_read bleibt unverändert.

## Exakte Subject-/Scopefences

Bestehende `_eligibility` verwendet bei tatsächlichem principal.unrestricted
keinen Parent-/Pairpredicate. Daher alle Subjects einschließlich Tenant/Task/
Contract/Unknown/Broken für **frisch SQL-verifiziertes unrestricted** zulässig:
auth/User/Sid/Operational-/Notification-/Dispatchlocks halten exakt denselben
akzeptierten Readvertrag. Owner ignoriert Dispatchrolle, andere All-scope-Rollen
brauchen deren weiterhin tatsächliche Row-/Missingrowfence. Kein Parentbypass
für selected. Dies wurde nach Sourcevergleich ausdrücklich von Root akzeptiert.

Für selected zunächst tatsächlich unlinked oder zentrale Aliasziele
portfolios/properties/units. Discovery nutzt zentralen RESOURCE_ALIASES,
`portfolio_scope._parents`, csv_parents und dieselbe scoped_clause; keine
erratene zweite Parent-/CSVsichtbarkeit. Polymorphe/CSV-/Tenant-/Contract-/
Finanz-/Meter-/Document-/Taskzweige in selected bleiben **vorläufig offene
Folgearbeit**, geschlossen503 statt fiktiv generischer Parentfähigkeit.

Positive Portfolio-/Usergrant-/Resourcegrantzeugen einzeln aus dem konkreten
Zielpfad laden und native halten. Bei Property/Unit bestehendes
lock_measurement_property vor Property→Unit-lock_location verwenden; Portfolio
und positive Scopezeugen ebenfalls native halten. Keine Property-/Tenant-/
Installationstocklists sperren. Nach wartenden Locks tatsächliche Parentfelder
und Notificationbindung erneut lesen; geänderter Pfad Konflikt/unsichtbar404.
Targetstatus und Dispatchrole aus tatsächlichen Rows nachhalten. operational_lock
schützt auch noch nicht vorhandene restrictive Dispatchzeilen des Tickwriters.

## Zentrale noch offene Komposition

Eigene Wrapperprüfungen verlangen echte Readpairschemaform und tatsächliche
INTERNAL-Klassifikation von notification_read_states vor DML. Root owns deren
Registrierung; kein eigenmächtiges Setzen/Mocken von INTERNAL oder Abschalten
des Session-Scopeinterceptors. Ohne Anschluss ehrlicher503.
Keine globale actions.flagtrue-/HTTP-/Middleware-/Migration-/Auth-/Recovery-
Änderung. PerItem-Hint ist nur struktureller Candidate nach bereits berechtigtem
Read; Root muss echten aktuellen Scope, Readeligibility und tatsächlich
abgenommenen Writeranschluss komponieren. Ein Hint stellt nie einen Beleg aus.
TEHA braucht eigenen Capabilityvertrag; Notificationbeleg bleibt ausschließlich
der persönlichen Notificationoperation zugeordnet.

## Quellenabnahme und später benötigte Nativegates

Vorbereiten: nominelle Forges/legacySid/ScopeActor/Crossdb/fehlende Singletons,
Missing-INTERNAL ohne DML, positive insert-once für unrestricted Subjects und
selected Unit/unlinked, geänderte Target-/Parent-/Dispatchbindung, verfrühter
Commit/Savepoint und vollständiger Rollback nach tatsächlichem Read-DML.
Keine Authgetter-/Actorlambda-Mocks; Failureinjection darf nur eigene Stage-
Übergänge treffen. Positive Fälle brauchen die tatsächliche zentrale INTERNAL-
Komposition, keinen Fixturebool als Ersatz. Bestehende Pure-/Sourcegates werden
nicht wiederholt oder als neue Writeabnahme umbenannt.

Root koordiniert später echte SQLite/PG-Zweiverbindungsraces für Sid/Expiry,
Management/Grant/Origin, Locationparent und restrictive Dispatchinsert in
beiden Reihenfolgen. Erst danach HTTP und perItem-Aktion aktivieren. Eigene
Gates in diesem Auftrag ausdrücklich nicht genehmigt; Budgets im Handoff.

## Quellenpräzisierung vor erstem Produktcommit, 04.10.2026

Der Wrapper least ausdrücklich seine eigene neue Engineconnection, ohne
vorhandene native Transaktion, und bindet nur seine eigene neue Session daran.
Session beginnt die native Roottransaktion und committed sie selbst. Die Lease
bleibt bis zur Bereinigung offen: SQLitebusy_timeout auf derselben tatsächlichen
DBAPIconnection nach Transaktionsende zurücksetzen, erst dann in den Pool
zurückgeben. Keine fremde Connection oder aktive/verschmutzte scoped Authsession
übernehmen, schließen oder zurückrollen. Account-/Sididentityproben schließen
nur nachweislich neue inaktive Sessions über deren tatsächliche jeweilige Factory.
SQLiteframe prüft zusätzlich den tatsächlichen DBAPI-in_transaction-Status.
Bei fehlgeschlagener Operation wird auch die eigene physische DBAPItransaktion
explizit zurückgerollt: ein verweigerter Connection-Commit kann dessen
SQLAlchemy-RootTransaction bereits deaktivieren, obwohl DBAPI noch nicht
committed hat. Der Cleanup darf diesen Rest weder im Pool lassen noch als
erfolgreichen Read behandeln. Dies bleibt eine Quellenanforderung, kein bereits
ausgeführter nativer Rollbacknachweis.

Die positiven User-/Resourcegrantzeugen werden nach ihren konkreten
Portfolio-/Locationparents gesperrt; auth_setup/User sind schon gehalten und
schützen normale Accountgrantwrites. Das hält die FK-/Locationfolge konsistent.
Selected Locationänderung beim vorhandenen lock_location ergibt409/404 und
keinen aus einer alten Pfadannahme erteilten Read. Unrestricted erwirbt keine
irrelevanten Scopeparentlocks. Der reine Hint liefert für aktive unrestricted
Rows auch unbekannte, gebrochene und unvollständige Subjectpaare als Candidate;
er wird ausschließlich nach tatsächlicher Readeligibility verwendet.
