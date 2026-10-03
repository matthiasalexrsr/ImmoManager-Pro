# PostgreSQL-Fixture und regulärer Savepoint-Rollback

## Tatsächlicher Befund vor der Änderung

Root74b6ae3: Die beiden Sid-Reihenfolgefälle endeten mit zwei Setupfehlern
nach15,29s, Hard90s/Exit1. Kein Race- oder Scopeergebnis.
SQLUserStore.create legt den vorhandenen AuthSetupmarker bewusst in einem
Savepoint erneut an und behandelt den erwarteten IntegrityError. Der zentrale
PG-Testhelper führt vor jedem Statement set_config aus. Vor dem tatsächlichen
ROLLBACK TO SAVEPOINT schlägt dieses zusätzliche SQL in der abortierten
Transaktion fehl und verhindert die reguläre Fehlerbehandlung.

## Enger Korrekturplan

Der Fixturelistener erkennt ausschließlich das tatsächliche kompilierte
SQLAlchemy-RollbackToSavepointClause und führt davor kein zusätzliches SQL aus.
Keine Produktänderung an Auth, Schema, Writer oder Zugriff. Kein allgemeines
Überspringen fehlerhafter Statements und keine Lockerung der Zielbindung.
Der native Rollback besitzt weiterhin die bestehenden Serverbudgets und den
äußeren begrenzten Prozessrahmen. Danach gelten alle normalen Statementbudgets.
Die zwei echten Sid-Fälle werden erneut ausgeführt; erst dann der getrennte
GET-Parentgegenbeleg. Erwartete Duplicate-Constraints sind kein Produktfehler.

Artefakt des ersten tatsächlichen Fehlers:
artifacts/NOTIFICATION_INBOX_PG_SID_RACES_74b6ae3_20261004.xml.
