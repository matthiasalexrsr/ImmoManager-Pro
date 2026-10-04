# Phase-A Inbox: Quellenhandoff an Root

## Saubere eigene Reihe und tatsächlicher Nachweisstand

- Basismerge `00c8d3b`: sauberer Root `febf902` in den vorhandenen eigenen
  Factorycheckout. Der frühere Factorybranch bleibt erhalten. Ein add/add-
  Konflikt wurde durch die bytegleiche Root-Factory gelöst.
- Vorcodeplan `0f523a3`.
- Abgegrenztes Quellen-/Testpaket `9822439`: ausschließlich sechs neue Dateien.

Root übernimmt nur die abgegrenzten Plan-/Produkt-/Handoffcommits, nicht den
Basismerge. Checkout `work/encrypted-runtime-factory`, eigener Branch
`assist/notification-inbox-readonly`. Root wurde nicht verändert.

Tatsächlich vorgenommen: Quellenlektüre, reservierte Revisionsprüfung am
TEHA-Gitobjekt `150aa66`, Diffprüfung und `git diff --cached --check` ohne Befund.
Keine Python-, Ruff-, Mypy-, Import-, Test-, App-, HTTP-, SQLite-, PostgreSQL-,
Browser- oder Buildausführung. Kein neuer nativer Erfolg. Es sind 28 Fälle
vorbereitet: 9 HTTP, 6 SQLite-/5 PostgreSQL-Migrationsfälle, 8 Recovery-/Importfälle.
Diese Zahl stammt aus den geschriebenen Funktionen/Parametern, nicht aus einer
ausgeführten Collection. Syntax-/Importsicherheit bleibt tatsächlich ungeprüft.

## Exakte APIs

`backend.routers.notification_inbox.router` hat bereits den Prefix
`/notifications/inbox` und genau einen GET mit response_model `InboxPage`.
HTTP `?limit=11` wird durch `InboxHTTPQuery` in einen Integer überführt, danach
in den unveränderten strikten `InboxQuery`. Extra-Autoritätsfelder sind verboten.
Actual `require_auth`, actual `get_store` und `CheckedPublicationRoute`; keine
lokale Capability und kein eigener Auth-Getter. Der Handler vergleicht außerdem
das echte UserRead mit der aktuellen Scope und ruft ausschließlich actual
`list_inbox(store, domain_query, read_actions_enabled=False)` auf.

Migrationsvorlage:
`backend/db/migrations/proposals/m2a2b3c4d5e6_personal_notification_reads.py`.
`revision=m2a2b3c4d5e6`, `down_revision=l2a2b3c4d5e6`, von Root ausdrücklich
reserviert. Die Datei ist außerhalb versions und ändert keinen entdeckten Head.
Upgrade erstellt nur die neue Familie, verweigert vorhandene/defekte Familie und
fehlende Eltern; kein Stamp, Backfill oder Schemaabgleich. Downgrade prüft Shape
und verweigert jede vorhandene Zeile, auch korrupte/orphan historische Fakten.
Keine Modellimporte in dieser Migration und keine Mutation fremder Base-Metadata.

Reiner vorgeschlagener Anschluss:
`validate_notification_inbox_recovery(connection, *, deadline=None) -> bool`
aus `backend.services.notification_inbox_recovery`. Delegiert vollständig an
den vorhandenen `validate_notification_inbox_database`. Keine zweite Prüflogik,
kein Runtime-/ORM-/Settingsimport, keine Transaktionseröffnung, DDL oder DML.
False ist nur eine Familienabsenz-Beobachtung. Root muss das alte Profil selbst
beweisen und für M2/current true verlangen. Fehler bleiben die vorhandenen
festen `InboxIntegrityError`-Codes.

## Root-Komposition, bevor irgendetwas aktiviert wird

1. `backend/routing.py`: Modul aufnehmen, Inbox vor dem vorhandenen
   `api_v1.include_router(notifications.router, ...)` einhängen. Kein zweiter
   `/notifications`-Prefix. `backend/routers/__init__.py` nur koordiniert ergänzen.
   Die eigene HTTPfixture montiert beide Router genau in dieser Reihenfolge.
2. Tatsächliche L2-Quelle zuerst integrieren/reviewen. Erst danach die reservierte
   M2-Datei in versions übernehmen. Aktiven Schemahead, zentrale Migration-
   Registrierung und Installer-/Maintenancevertrag zusammen aktualisieren.
   Die Quelle `febf902` hat noch K2; reine M2-Dateipräsenz in proposals ist keine
   L2/M2-Migration und kein Startnachweis.
3. `backend/db/session.py`, `backend/db/migrations/env.py` und zentrale
   Modellregistrierung: Familie vor Schema- und Archiv-Metadataauswertung
   explizit registrieren. Neue Router-/Serviceimports registrieren die ORM-Tabelle
   ebenfalls; Produktionsstart darf niemals durch Importreihenfolge die Tabelle
   erzeugen oder das fehlende physische Schema automatisch korrigieren.
4. `backend/services/portfolio_scope.py`: `notification_read_states` in INTERNAL
   aufnehmen. Die Tabelle hat keinen id-Einzel-PK, gehört einem tatsächlichen
   Actor/Notificationpaar und benötigt keine generische Portfolio-CRUD-Freigabe.
   INTERNAL ist kein Recht zum Export fremder persönlicher Reads. Globale Daten-
   exports/Privacyadapters und vollständiger Transfer bleiben separat geprüft.
5. `backend/db/runtime_schema.py`: vorhandene M2-Familie rein lesend nachweisen,
   inklusive nativer Constraints; bei fehlender/defekter Familie konkrete
   Wartungsanweisung. Kein Startup-DDL/Stamp/Repair.
6. `backend/services/full_recovery.py::_database_info` und tatsächliche
   Restorekomposition: Validator auf derselben konsistenten unveränderten
   Connection vor Mutationen verwenden. Whole-family-Absenz nur bei vollständig
   nachgewiesenem Vor-M2-Profil. Incomplete shape oder orphan/ungültiger Readzeit
   nie durch optional tables verdecken. Die Base-Metadata-Schleife muss ebenso
   diese enge Profileinstufung berücksichtigen. Fehler als feste Recoverymeldung.
7. `backend/legacy_sqlite_upgrade/release126_profiles.json`: ausschließlich
   aktuelle Zielreferenzen nach tatsächlich ausgeführter L2/M2-Kette neu
   erzeugen. Historische 126-Referenzkataloge bytegleich belassen. Gegen vollständige
   Originalfakten validiertes Fullbackup vor einer realen Schemaänderung bleibt
   Pflicht; hier wurde keine echte Installation benutzt oder geändert.

## Konkrete Grenzen vor der nächsten Abnahme

Der Domain-Structuralvalidator prüft tatsächlich PK, Nullability, String-/naive
DateTime-Typen und beide nativen CASCADE-FKs. Er prüft **nicht** den nativen
`ck_notification_read_identity`-Ausdruck. Ein positives Recoveryadapterergebnis
ist daher kein vollständiger nativer Guard-Katalognachweis. Die Migration erzeugt
genau den vorhandenen ORM-CHECK. Vor Aktivierung muss Root den tatsächlichen
CHECK-Katalogvertrag ergänzen/komponieren; vorbereitet sind native Blank-ID-
Insertverweigerungen mit vorhandenen echten Eltern, damit FKfehler den Beleg
nicht ersetzen. PostgreSQL-reflektierte Casts/Parenthesen sind kein Textgleichheits-
Beleg; die Tests prüfen Namen und native Wirkung sowie Shape beim down/up.

Die HTTPfixture verwendet echte SQLUserStore/require_auth/PortfolioScopeMiddleware
und signed legacy-compatible Access-JWTs aus actual create_access_token. Sie
ersetzt keine Auth-Dependency und keinen Permissiongetter. Sie ist kein Login-,
Sid-Rotations-/Commit- oder ManagedLifetimebeleg. Bestehende Auth-Sid-Heartbeats
gehören zur zentralen Auth-Lebensdauer; der Inboxhandler schreibt keine Readfacts.
Die Fixture benutzt einen kleinen echten FastAPIrouteraufbau, nicht Root-App-
Coldstart; zentrale Registry und Startupkomposition brauchen ihren eigenen Gate.

Feste private/no-store Header gelten für eigene Erfolgs-/503-Antworten und den
eigenen Scopefehler. Zentrale Auth-/Query-/Publicationfehler nutzen weiter die
bestehenden Handler. Eine zentrale NoStorevereinheitlichung ist kein Teil dieses
Routerpakets. Die bestehende globale Notificationread-API bleibt außerhalb des
neuen persönlichen Pfads; sie ist kein persönlicher Readcommand dieses Pakets.

Beide Aktionen bleiben false. Kein `stage_read`-HTTPaufruf, keine CommitAuthority,
keine positive Schreibaktivierung. Native PostgreSQL Notification-/Dispatch-
func.now-Timestamps sind weiterhin Domain/Root vorbehalten; keine Zeitdefaults
oder historische Zeitwerte wurden hier verändert. Vollcontainer-Reopen und
current-vs-pre-M2 Archivprofile sind noch nicht durch dieses Paket geprüft.

## Vorbereitete NodeIDs für späteren koordinierten Lauf

HTTPdatei `backend/tests/test_notification_inbox_readonly_http.py`, neun Funktionen:

- `test_http_real_me_store_binding_personal_counts_and_false_actions`
- `test_http_scope_target_role_and_exact_filter_counts`
- `test_http_query_rejects_request_authority_and_invalid_limits`
- `test_http_cursor_is_actor_bound_and_grants_are_checked_at_publication`
- `test_http_missing_family_is_fixed_private_503_not_an_empty_page`
- `test_http_memory_store_has_no_sql_or_stock_fallback`
- `test_http_memory_accounts_cannot_authorize_a_sql_inbox`
- `test_http_actual_auth_in_a_different_database_fails_closed`
- `test_http_no_read_write_endpoints_or_readstate_side_effects`

Migrationdatei `backend/tests/test_notification_inbox_migration_proposal.py`:
folgende fünf Funktionen je mit `[sqlite]` und `[postgresql]`:

- `test_native_proposal_exact_shape_and_empty_down_up`
- `test_native_proposal_rejects_existing_family_without_repair`
- `test_native_personal_evidence_is_not_global_read_backfill_and_blocks_downgrade`
- `test_native_personal_pair_uniqueness_and_both_parent_cascades`
- `test_native_required_read_fields_and_identity_guard`

Dazu `test_sqlite_downgrade_preserves_even_orphan_read_evidence`. PostgreSQL
benötigt explizites disposable `TEST_SERVER_DATABASE_URL`, benutzt ausschließlich
ein eigenes UUIDschema und verweigert fehlende Umgebung ohne Skip. Kein Test
benutzt eine bereits vorhandene Anwendungsschema-/Datenbankinstanz.

Recoverydatei `backend/tests/test_notification_inbox_recovery_proposal.py`:

- `test_recovery_hook_preserves_actual_personal_and_global_facts_and_transaction`
- `test_recovery_hook_absence_is_only_an_observation_and_partial_family_refuses`
- `test_recovery_hook_refuses_bad_facts_without_repair` (vier Parametervarianten)
- `test_recovery_hook_deadline_refuses_without_mutation`
- `test_recovery_hook_import_rejects_runtime_and_orm_modules` (ein vorbereiteter
  frischer bounded Childprozess, 15 s; jetzt nicht gestartet)

Spätere Dateiläufe: Interpreter aus der gemeinsamen outputs-Venv, pytest mit
exakt obiger Datei; Migration zunächst `-k sqlite`, PostgreSQL später getrennt
`-k postgresql`. Root legt native Slots und harte Gesamtbudgets vor Ausführung
fest. Ein einfacher Operationslauf ersetzt keinen tatsächlichen vollständigen
L2→M2-Alembic-Head-/DDLfreienStart-/Fullbackup-/Restore-Gate. Kein A–L-Gesamtclaim.

## Tatsächliche unabhängige Rootprüfungen auf 72c0756

Root hat die übernommenen Quellen anschließend getrennt ausgeführt. Die
oben dokumentierte reine Quellenübergabe bleibt als Herkunft erhalten.

| Gate | Tatsächliches Ergebnis | Harte Prozessgrenze |
|---|---|---|
| Readonly-HTTP, eigene SQLite-/SQLUserStore-Instanz | 9 PASS, 44,95 s, Exit 0 | 120 s |
| Reiner Recoveryadapter einschließlich frischem Importprozess | 8 PASS, 1,13 s, Exit 0 | 30 s |
| SQLite-Migrationsvorlage über Alembic Operations | 6 PASS, 1,46 s, Exit 0 | 60 s |

Die fünf PostgreSQL-Migrationsfälle wurden im SQLite-Lauf ausdrücklich
abgewählt; sie sind weder bestanden noch übersprungen. Alle Prüfprozesse
sind beendet. Berichte: `artifacts/NOTIFICATION_INBOX_READONLY_HTTP_72c0756.xml`,
`artifacts/NOTIFICATION_INBOX_RAW_RECOVERY_72c0756.xml` und
`artifacts/NOTIFICATION_INBOX_M2_SQLITE_OPERATIONS_72c0756.xml`.

Der HTTP-Gate verwendet den kleinen tatsächlichen Routeraufbau, nicht den
Produktions-Appstart. Die Migration liegt weiterhin außerhalb `versions`;
kein Schemahead, Registry-, INTERNAL- oder Restoreanschluss wurde aktiviert.
Kein Login-/Sid-Racebeleg und kein positiver persönlicher Schreibzugriff.
Der vollständige L2→M2-Upgrade-/Start-/Wiederherstellungsnachweis bleibt offen.
Ein Starlette-TestClient- und sieben SQLite-Datetime-Adapterhinweise sind
DeprecationWarnings; sie ersetzen keinen Produktfehler und bleiben sichtbar.
