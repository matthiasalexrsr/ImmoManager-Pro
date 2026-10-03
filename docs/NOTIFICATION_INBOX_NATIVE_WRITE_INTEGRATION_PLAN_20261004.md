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
