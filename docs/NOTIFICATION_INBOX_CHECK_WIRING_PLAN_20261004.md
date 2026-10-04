# Tatsächliche CHECK-Prüfung im gemeinsamen Inboxvalidator

## Ergebnisse vor der Verdrahtung

SQLite-/PG16-Parserpaket: erster tatsächlicher Run93PASS/3SetupFAIL3,07s;
drei Fixture-Columnklauseln waren hinter einer Tabellenconstraint ungültig.
Nur die Test-DDL wurde korrigiert05a0531. Danach96PASS1,92s/Hard30s/Exit0.
Hieraus folgt keine echte PostgreSQL-Verbindungsprüfung.

Eigenständiges natives PG16-Paket auf1fef35c: neun tatsächliche Connection-
Guardfälle plus zwei tatsächliche Core-/ORM-Savepointfälle,11PASS7,21s,
Hard120s/Exit0. Tatsächliche M2 Operations, READ ONLY, CHECK-Verstöße,
fehlende/OR/falsche Feld-/NOT VALID/falsche Funktions-/Relations-/Schema-/
Tempbindungen geprüft. Eigener ServerPID27052 regulär beendet, keine
Piddatei und kein Listener58112. Das ist keine globale Head-/Upgradeprüfung.

Gemeinsamer alter Validator: fünf tatsächliche Raw-Gegenfälle mit --runxfail
ausgeführt,5FAIL1,79s/Hard30s/Exit1. Alle fünf schwachen bzw. fehlenden CHECKs
wurden noch akzeptiert. Artefakte:
artifacts/NOTIFICATION_INBOX_IDENTITY_GAP_PREWIRING_20261004.xml und
artifacts/NOTIFICATION_INBOX_PG_GUARDS_SAVEPOINTS_1fef35c_20261004.xml.

## Enger Integrationsplan vor Änderung

Nach vorhandener Spalten-/PK-/FK-Prüfung muss die tatsächliche Verbindung ihren
nativen SQLite- oder PG16-CHECK-Adapter bestehen. Nur völlig abwesende Familien
bleiben false, vorhandene ungültige Familien werden mit festem Fehler abgelehnt.
Keine Datenreparatur, neue Tabelle, Transaktion oder Runtimeimport. Der Caller
behält seine Verbindung und Deadline. Die fünf bekannten xfails werden echte
Regressionen. Danach gemeinsame PureRaw-/Recovery-/Gapprüfung und tatsächliche
SQLite-Service-/HTTPfälle sowie mindestens echter PG-Schreib- und GETpfad.
L2/M2 bleiben unveröffentlichte Vorschläge; globale Start-/Release-/Recovery-
Familienprofile müssen gesondert komponiert und geprüft werden.
