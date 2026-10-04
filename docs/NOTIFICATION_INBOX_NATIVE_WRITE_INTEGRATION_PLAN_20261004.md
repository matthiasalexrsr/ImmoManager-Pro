# Persönlicher Einzelread: unabhängige Rootkomposition

Vorcodeentscheidung nach b8e793c. Domain liefert eine eigene, tatsächliche
Session-/Sid-/Zieltransaktion; der DTO und eine fremde Session erteilen kein
Schreibrecht. Die zentrale Oberfläche und der HTTP-Write bleiben zunächst
unverdrahtet. Die aktive Migration ist weiterhin K2.

## Geordnete Übernahme und erste native Prüfungen

1. Nur die abgegrenzten Domain-Pläne, zwei neuen Services und ihre Tests
   übernehmen; kein alter Basismerge und keine Agentenbehauptung als Testbeleg.
2. Den reinen Kandidatenhinweis ohne Runtimekonfiguration prüfen. Das Ergebnis
   schaltet keine Aktion frei. Danach den tatsächlichen Pre-registration-Fall
   mit eigener SQLite-Datei, SQLUserStore und echten Sid-Token ausführen.
3. Erst nach diesem Beleg `notification_read_states` zentral als INTERNAL
   registrieren. Der Actor-/Notificationpaar-PK passt nicht zur generischen
   Portfolio-CRUD-Regel. INTERNAL wird ausschließlich durch den tatsächlichen
   privaten Writer benutzt, kein neues Export-/Clearrecht und kein Startup-DDL.
4. Zunächst einen positiven SQLite-Single-read mit Wiederholung und stabilem
   Erstzeitpunkt ausführen. Dann die übrigen vorbereiteten nativen SQLitefälle
   gezielt prüfen: Actortrennung, echte Scopes, Callerunabhängigkeit, fehlende
   Fences, Zielbindung, falsche Authdatenbank und reale Rollbacks nach DML.
5. Statische Prüfung und Tests sind getrennte Belege. Veraltete Assertions
   werden nur anhand tatsächlicher Produktantworten korrigiert. Keine erfundene
   Capability, kein Authgetter-/INTERNAL-Monkeypatch und kein Positivclaim aus
   einem vorzeitig beendeten Prozess.

Root setzt für jeden nativen Lauf explizite eigene Testpfade und Konfiguration,
entfernt bekannte Settingsvariablen der Umgebung und setzt eine harte
Prozessgrenze. Private Daten und die laufende Release126-Vorschau bleiben
außerhalb dieser synthetischen Prüfungen. Der Prozess und seine Pools werden
vollständig beendet, bevor der nächste native Gate beginnt.

## Voraussetzungen für öffentliche Aktivierung

Selected unterstützt zunächst ausdrücklich Portfolio/Property/Unit und echte
positiv gewährte unlinked Benachrichtigungen. Unrestricted folgt der vorhandenen
tatsächlichen Readeligibility für alle Subjects, einschließlich Owner-
Dispatchausnahme. Andere selected-Zweige benötigen ihre tatsächlichen Fences
und bleiben bis dahin geschlossen. Der per-item Kandidatenhinweis ersetzt
keinen dieser Nachweise.

Vor HTTP-/UIaktivierung folgen native unabhängige PostgreSQL-Verbindungen mit
beiden echten Reihenfolgen von Sid-/Accountgrant-/Eltern-/Dispatchänderungen,
danach verlorene Erfolgsantwort und tatsächlicher HTTP-/Browserablauf. Die
Schemaaktivierung verlangt separat eingefrorenes L2, M2-Katalogschutz,
vollständige Registry, expliziten Upgrade, DDLfreien Start sowie vollständige
Sicherung/Wiederherstellung. Ein einfacher Operationslauf ersetzt diese Kette
nicht. TEHA erhält eine eigene op-/zielgebundene Unit, keinen Notificationbeleg.

## Tatsächlich ausgeführte erste Gates

Auf613a7b9: 43 reine Kandidaten-/PG-Fixtureguardfälle PASS in0,76s,
hard30/Exit0; sie verbinden sich mit keiner Datenbank. Anschließend die drei
vorgesehenen echten SQLUser-/Sid-Preregistrierungsfälle PASS in8,52s,
hard45/Exit0. Alle Prozesse beendet. Legacytoken, falscher Actor,
unregistrierte nominale Fälschungen und die tatsächlich fehlende INTERNAL-
Registrierung verweigern Read-DML. Berichte liegen unter
`artifacts/NOTIFICATION_INBOX_PURE_HINT_FIXTURE_20261004.xml` und
`artifacts/NOTIFICATION_INBOX_NATIVE_PREREGISTRATION_613a7b9.xml`.

Danach wird nur die zentrale INTERNAL-Klassifikation ergänzt. Kein Router-
Write, Hintschalter, M2-Head, aktuelles Laufzeitschema oder Vorschauupdate wird
damit aktiviert. Der Preregistrierungstest gehört ab jetzt zum dokumentierten
vorherigen Zustand und wird nicht durch künstliches Entfernen des realen
Anschlusses wiederholt. Positive Transaktionsevidenz folgt erst im nächsten
gezielten Gate.

Die historische Preregistrierungsfunktion wird aus der aktiven Testsuite
entfernt: sie fordert ausdrücklich einen inzwischen überholten Rootzustand.
Quelle613a7b9 und tatsächlicher XMLbeleg bleiben nachvollziehbar; die aktuellen
Positivtests verlangen unverändert die echte zentrale Registrierung. So bleibt
die Gesamtsuite ausführbar, ohne eine fehlende Registrierung vorzutäuschen.

## Tatsächliche native SQLite-Transaktionsabnahme

Aufe3f399d: erste acht ausdrücklich ausgewählte Fälle PASS24,08s/hard90/Exit0;
weitere24 bislang ungeprüfte Fälle PASS74,47s/hard150/Exit0. Beide Prozesse
vollständig beendet. Mit den zwei weiterhin aktuellen Preregistrierungs-
Negativfällen sind34 verschiedene aktuelle Nativecases positiv komponiert,
kein wiederholter zusammenhängender34er-Lauf. Der historische fehlende-
Registrierungsfall ist ein zusätzlich vorher bewiesener Zustand.

Echte SQLUser-/Sid-/DBbindung, persönliche Actortrennung und insert-once,
ausdrücklich unterstützte Selectedparents, echte Unrestrictedeligibility,
Dispatch-/Ownerregel, unveränderte dirty Caller, fehlende Singletonfences,
fremde Authdatenbank, reale Rollbacks nach Read-DML und endgültige Ziel-/
Principalprüfung bestehen. SQLite BEGIN IMMEDIATE liegt vor Authsnapshots;
eigene Session/Pool/Capabilityregistry sind geschlossen und die tatsächlich
geleaste Connection erhält ihren ursprünglichen busy_timeout zurück.

Die acht Änderungen nach Stage sind tatsächliche Mutationen auf derselben
Connection; sie beweisen Abschlussprüfung und Rollback, keine unabhängige
Concurrencyrace. PostgreSQL mit wirklichen unabhängigen Verbindungen und
HTTP-/Browser-/Schema-/Vollrestorefreigabe bleiben getrennt offen. Berichte:
`artifacts/NOTIFICATION_INBOX_NATIVE_FIRST_COMMIT_e3f399d.xml` und
`artifacts/NOTIFICATION_INBOX_NATIVE_REMAINING_e3f399d.xml`.
