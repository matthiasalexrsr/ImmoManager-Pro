# Inbox: Veröffentlichung nach einer parallelen Objektverschiebung

## Tatsächlicher Gegenbeleg vor Produktänderung

Root1fce39f, echte unabhängige PostgreSQL-Verbindungen, SQLUserStore/Ownerwriter,
unveränderte Actor-/Origin-/Grantbindung: Nach der tatsächlichen begrenzten
Seitenprojektion wurde property-one von p-one nach p-two verschoben. list_inbox
lieferte dennoch notice einschließlich Inhalt aus dem alten RepeatableReadbestand.
Ein tatsächlicher FAIL27,22s, Hard45s/Exit1. Die Verbindungen und das eigene
UUIDschema wurden regulär geschlossen. Artefakt:
artifacts/NOTIFICATION_INBOX_PG_GET_PARENT_PRECORRECTION_1fce39f_20261004.xml.

## Korrektur vor Umsetzung

Nach Abschluss des ersten Readsnapshots wird auf derselben echten Zielbindung
ein zweiter eigener konsistenter Readsnapshot geöffnet. Actorbindung, Schema,
vollständige Counts und dieselbe begrenzte limit+1-Seite werden erneut geprüft.
Nur wenn Principal, Counts und Seitenprojektion übereinstimmen, wird ausgegeben.
Änderungen ergeben409/inbox_changed; keine alten Daten im Fehler, keine blinde
Wiederholung und keine Bearbeitung fremder Callertransaktionen. Damit besitzt
die ausgegebene Seite einen aktuellen zweiten konsistenten Prüfzeitpunkt.
Keine Behauptung dauerhaft unveränderlicher Daten nach HTTP-Ausgabe.

Die zweite Projektion bleibt seitenbegrenzt. Die Anzahlen werden erneut durch
Aggregatabfragen auf dem berechtigten Bestand berechnet; kein Gesamtstockladen,
keine neuen Locks, DDL oder DML. Der Cursor bleibt live und ist kein Snapshotbeleg.
Prüfung: tatsächlicher PG-Parentgegenbeleg, bestehende SQLite-Count-/Cursorfälle,
gezielte tatsächliche HTTP-Ausgabe. Globale Router/Bell bleiben bis zur
gemeinsamen Schema-/Start-/Recoverykomposition unverändert.
