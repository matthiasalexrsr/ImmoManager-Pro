# Offline-Recovery und Retention: konkreter Arbeitsplan

Ausgangssnapshot `c27ebf28af266d9f02dbe0abb65b25675d20591b`, isolierter Branch
`assist/operational-recovery-guards`. Keine Liveauth, neue Runtime-Registrierung,
Migration-Rechain oder UI-Änderung in diesem Paket.

1. Einen rein lesenden `tenancy_workflow_validation` für die sieben Workflow-
   Tabellen erstellen. Vollständig alte Bilder ohne Familie bleiben kompatibel;
   eine teilweise Familie oder fehlende Spalten scheitert vor DML. Zeilen werden
   gestreamt, vollständige Einzelakten/-vorlagen dürfen keine 100/10.000-Grenze
   verlieren. Prüfen: Scope-Eltern, veröffentlichte Vorlagen und iterative DAGs,
   eingefrorene Startdaten/SHA-256, Schrittidentitäten und Originaltermine,
   Taskursprung/-projektion, abgeschlossene Fakten, Belegbindung und Beleg-SHA,
   Befehlsoperation/-subjekt/-antwort. Keine aktuellen Benutzerrechte anwenden.
2. Beide optionalen Familien in Schema-/Backupprüfung und Dateiverweisvalidierung
   aufnehmen. Neue Tabellen dürfen alte vollständige Bilder nicht pauschal
   ablehnen; halbe Familien werden nicht mittels `create_all` nachgebessert.
3. Vor jedem Offline-Sicherheits-DML alle Workflow-/Jobjournale validieren.
   Jobclaims danach innerhalb derselben caller-owned Transaktion mittels
   bestehendem `reset_restored_job_claims` entkräften. Spätere Fehler bei Sessions,
   Schlüsselprüfung oder Konfiguration müssen Fences/Claims ebenfalls rollbacken.
4. Einen eng begrenzten Retentionguard für Transfer/Reset liefern. Beide Familien
   gehören nicht zum generischen Business-JSON-Subset: deren vorhandene Fakten
   verlangen vollständige Offline-Recovery. SQL prüft begrenztes `EXISTS`/`LIMIT 1`
   und unter dem bestehenden Writer-Protokoll erneut; Memory prüft beide Familien
   unter der bestehenden gemeinsamen Sperre. Root hat ergänzend genau die
   `clear_all`-Hooks in Memory/SQL übertragen; andere Mutationspfade bleiben bei
   Root. PostgreSQL nimmt Account, dann Domaineltern vor Familientabellen und
   verweigert besetzte Tabellen mit NOWAIT innerhalb eines Caller-Savepoints.
5. Privacy-Memory-Staging serialisiert neue Workflow-/Job-ORM-Zeilen ausdrücklich,
   sodass unveränderte Belege nicht durch SQLAlchemy-Objektidentität einen falschen
   Konflikt auslösen. Retained Belege werden bei Profilanonymisierung erhalten.
   Fehlende fachliche DSGVO-Exportabdeckung wird konkret dokumentiert.
6. Reale SQLite-Bilder prüfen: vollständig alt, leer vollständig neu, jede halbe
   Familie, gültige echte Akte/Tasks/Belege, manipulierte Eltern/Hashes/Originale,
   Jobclaimreset, ursprünglicher Bestand unverändert bei Validierungsfehler und
   vollständiges Rollback bei späterem Fehler. Encrypted-Archive-Roundtrip sowie
   gezielte vorhandene Recovery/Transfer/Privacy-Gates ausführen. Genuine-PG-Gates
   nur mit eigenem zufälligem Schema im dedizierten lokalen Testdienst.

Belegte Prüfgrenze: Workflowbefehle speichern `request_sha256`, jedoch keine
ursprüngliche Anfrage. Der Validator kann deren Form und belegte Antwortbindung
prüfen, den Requesthash aber ohne gespeicherte Anfrage nicht neu berechnen.
Authentifizierte Vollarchive sichern den äußeren Bytebestand; diese Grenze darf
nicht als vollständig rekonstruierter Workflow-Befehlsverlauf ausgegeben werden.

Unabhängiger Review ergänzt drei konkrete Regressionen: Native PostgreSQL-
Parent/Child-Race mit SQL-Store und Memory-Auth; zulässige spätere Contractparty-
Korrektur ohne Umschreiben historischer Startdaten; manipulierte unveränderliche
Commandantworten samt Start-/Terminalactor. Historische mutable Antworten werden
gegen ihre verfügbaren unveränderlichen Fakten geprüft, nicht gegen heutige
Status-/Revisions-/Fristwerte.
