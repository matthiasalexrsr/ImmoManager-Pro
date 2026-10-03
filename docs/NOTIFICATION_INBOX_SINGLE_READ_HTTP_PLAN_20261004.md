# Persönlicher Einzelread: tatsächlicher HTTP-Vertrag

## Grundlage und Ziel

Der zentrale Writer hat echte SQLite- und unabhängige PostgreSQL-Sid-/Grant-/
Parent-/Dispatch-/Receipt-/Timeoutprüfungen bestanden. Die gemeinsame native
CHECK-Prüfung ist verdrahtet;25Raw-/Recovery-/Gapfälle bestehen auf544393f.
Keine globale L2/M2-/Start-/Restorefreigabe. Die Route wird zunächst nur im
eigenen echten Auth-HTTP-Test montiert; Live- und globale Router bleiben gleich.

## Vertrag vor Umsetzung

POST /api/v1/notifications/inbox/{notification_id}/read mit leerem JSONobjekt.
Zusätzliche Felder, etwa actor_id, werden422 abgelehnt. Actor und Session kommen
ausschließlich aus tatsächlicher Auth und dem signierten Accesscredential.
Antwort exakt notification_id/read_at; natürlicher Compositekey erhält den
ersten Lesebeleg bei Wiederholung. Keine globale Notificationstatusänderung.
Legacytokens behalten den lesenden GET, Einzelread benötigt echten Sid/v1.

GET kann Kandidatenaktionen nur bei echtem Sid/v1 und unterstütztem Subject
anzeigen: bekannte Portfolio-/Property-/Unitfences oder tatsächlich berechtigt
unverknüpfte bzw. unrestricted Rows. PureHint ist keine Schreibberechtigung;
der Writer prüft alle tatsächlichen Voraussetzungen erneut vor Speicherung.
Unsupported Selectedsubjects bleiben ohne Button, statt einen vorhersehbar
fehlgeschlagenen Workflow anzubieten. Keine globale Mark-all-Aktion.

RBAC erhält ausschließlich für diesen exakt passenden POST-Pfad eine Ausnahme
vom Fachschreibrecht. Auch readonly darf seinen eigenen Lesestand speichern.
Alle anderen Notification-Schreibpfade bleiben geschützt. Auth/Sid/Scope und
Commitcapability werden nicht umgangen. Audit klassifiziert den persönlichen
Read als notification_read_states/read mit tatsächlicher Notification-ID.
Private no-store-Header, vorhandene CheckedPublication und scopebindung gelten.

Prüfung: echte moderne SQLUser/Sid-HTTP-Anmeldung, readonly eigenerRead,
Wiederholung, andererActor, unveränderterGlobalstatus, Bodyfälschung, Foreign-
Notice, Legacyreauth, Sidrevocation, fehlendeFamilie, readonly Fachwrite-
Verweigerung sowie unterstützt/nichtunterstützt Kandidatenmetadaten.
