# Vollmatrix-ImmoManager PRO – evidenzbasierte Fehler-Triage vom 16.10.2026

**Status: Entwicklungs-/Testinfrastruktur-Checkpoint, keine Gesamtfreigabe.**
Zweig `pro/stage-full-matrix-20261016` aus
`57ab0a561904feefde50cffc5b1cd10407002d31`.
Kein Anwenderdatenzugriff, keine Änderung des zentralen Git-Checkouts,
keine Befehle auf Ports 8000/8765 und keine echten Fremdprovider.
Alle Prüfdateien und Uploads liegen im eigenen isolierten Worktree.

## Ausgangsdaten – nicht beschönigt

Unveränderte Erstaufnahme unter
`pro-stage-interfaces-teha-platform-20261016/artifacts/pro-tests/merged-57ab0a56-full-memory-memory-1e9de119f699418ca16482d3a4288229`:
**2612 bestanden, 54 fehlgeschlagen, 114 übersprungen (2780 Fälle)**;
tatsächlich gemessene Zeilenabdeckung **83,63 %** (41505 von 49628
instrumentierten Zeilen). Die Abdeckung erfüllt rechnerisch die
80-%-Schwelle; der Gesamtlauf bleibt **rot**. Diesen Lauf nicht
als Backend-/Release-Abnahme darstellen.

Aus dem tatsächlich gespeicherten Pytest-JUnit (54 Fehler,
jeder Fall einmal gezählt) ergab die folgende erste, deterministische
Ursachenklassifizierung:

| Kategorie | Fälle | Behandlung |
|---|---:|---|
| Überlange/fehlerhafte Windows-QA-Pfade beim Schreiben geschützter Dokumentoriginale | 12 | Isolierten Test-Runtime-Pfad verkürzt; produktiven Datenspeicher nicht gelockert |
| Bestehendes create_all-Tabellenschema kollidiert mit neuen Alembic-Migrationen | 10 | **Weiter blockiert.** Additive Migrationen und alte Historie nicht vorschnell umgeschrieben |
| Veraltete Test-HTTP/Auth-Kontrakte gegen geschützte Benachrichtigungs-/Aktenendpunkte | 8 | Gezielte Endpunkt- und Rechte-Gegenproben notwendig, Authschutz nicht lockern |
| Rückmigration absichtlich durch Originalschutz verweigert | 7 | Altfall zu eigenem alten Schemahead isolieren; nicht zum Zweck grüner Tests Originalguards entfernen |
| Fehlendes optionales `fints`-Paket in der Gesamtprüfumgebung | 1 | Eigenständige `fints==5.0.1`-QA-Umgebung liegt in einem anderen Stage-Worktree vor; nicht als Livebankkontakt umetikettieren |
| Nicht lesbarer älterer Ciphertext/Archivschlüssel | 1 | Mit originalgetreuen, archivierten Testschlüsseln gegenprüfen; nicht durch leere Antwort als erfolgreich behaupten |
| Sonstige Fachkontrakte / Legacy-Testannahmen / nicht kategorisierte Fehler | 15 | Einzeln reproduzieren, insbesondere Portfolio-Isolation, Bankimportauthentifizierung, Dateirouting und Benachrichtigungs-Quittungen |
| **Summe** | **54** | Noch kein Gesamt-Go |

Dies ist eine **Triage nach Fehlermeldung**, noch kein Beweis für die
endgültige Root-Cause in jedem einzelnen Test.

## Aktuell korrigierte unabhängige Testgrenze

`scripts/run_pro_matrix.py` bewahrt vollständige, menschenlesbare
JUnit-/Logdateien unter `artifacts/pro-tests/<label>-<backend>-<uuid>`.
Den tatsächlichen `DATA_DIR`, `UPLOADS_DIR`, `BACKUP_DIR`,
Schlüsselring und die Wegwerf-SQLite-Datenbank legt es jetzt unter
`artifacts/r/<12-stelliges-uuid>` ab. Auf Windows wurden lange
Protokoll- und Fotopfade über die Win32-Pfadgrenze hinaus verlängert;
bei `os.link` entstand dadurch `FileNotFoundError` noch
**vor** der eigentlichen Datei- oder HTTP-Invariante.

Die neue Grenze bleibt exakt **innerhalb des eigenen
Worktrees**, benutzt für jeden Lauf neue zufällige Pfade und
greift weder auf die Anwenderinstallation noch auf globale
Temp-Speicher zu. Runtime und Prüflogs bleiben getrennt; die
`input.json`-Evidenz enthält Commit, Quelldateihashes, die
Runtimeadresse und künftig zusätzlich den **SHA256 des Teststarters**.
Es wurden keine fremden Verzeichnisse geleert.

Erneut nachgewiesen:
- `artifacts/pro-tests/short-windows-upload-memory-48a103d0ee9145e683b6c45f21c87f93`:
  **2/2** der ursprünglich `WinError 3`-roten Upload-/
  Handoverfälle nach Pfadkorrektur erfolgreich.
- `artifacts/pro-tests/short-handover-suite-memory-34829341fad243c48510dd7e501e17b5`:
  **15 bestanden, 2 umgebungsspezifisch übersprungen**;
  `artifacts/pro-tests/short-handover-suite-sql-976b7bb8e89641dea239e25d80ba5518`:
  **17 SQLite bestanden, 0 Skips**.

## Sicherheitsverträge nicht durch Testlockerung umgangen

Zwei **alte** Testannahmen waren nach dem S3-/Dateischutz
inkorrekt: Ein Windows-Traversal-Key wurde früher still in einen
sicheren Ersatzpfad umgeschrieben, und beliebige S3-Bucketnamen
konnten als lokale Dateischlüssel gelesen werden. Der aktuelle
Produktcode **verweigert beides**. Die aktualisierten Tests
verifizieren deshalb eine explizite Verweigerung für einen
fremden S3-Bucket und Windows-`..\`-Traversal; zusätzlich belegen
sie den erfolgreichen Abruf eines Originalkeys unter der
**genau autorisierten** künstlichen S3-Bucketidentität. Kein
echter S3-Endpunkt wurde angesprochen.
- `artifacts/pro-tests/storage-policy-contract-memory-73c3da5b166b420c8357a7260b9ffa53`:
  **14/14** bestanden, 0 Skip; der entsprechende SQLite-Lauf
  ist separat nachzuweisen.

## Weitere offensichtliche rote Gesamt-UI-Gates

Erster React/Vitest-Gesamtlauf im verbundenen Schnittstellenzweig:
**617 bestanden, 38 fehlgeschlagen, 24 betroffene Dateien**.
Nach getrennten Benachrichtigungs-/Nachrichten-/Mockkorrekturen
in `pro-stage-frontend-compat-20261016` wurden
**627 bestanden, 30 fehlgeschlagen, 19 betroffene Dateien**
(657 Tests einschließlich zwei neuer Notification-Inbox-Verträge).
**29 der 30** wurden als einzelne 5-Sekunden-Testtimeouts
ausgewiesen; der verbleibende E-Mail-Fall ist gesondert zu prüfen.
Deswegen läuft jetzt ein Wiederholungstest mit `--maxWorkers=2`,
`--testTimeout=15000` **ohne** Lockerung von Produktassertions;
dessen Ergebnis darf nicht im Voraus behauptet werden.

### Noch ausstehende Gesamtfreigabe

In diesem Arbeitspaket ist die beschleunigte Hauptmigration
nicht verändert: Besonders die neu ergänzten
`communication_items`-Tabellen lassen sich bei einer
unversionierten, bereits durch `Base.metadata.create_all`
angelegten Testdatenbank derzeit nicht konfliktfrei
als Alembic-Migrationsstand übernehmen. Ein unsicheres
`stamp head` ohne vollständige Spalten-, Index-, Trigger-
und Datenverifikation wäre eine gefährliche Scheinreparatur.
Diese **10 roten Altbestandsfälle** bleiben ein eigener
Integrationsblocker. Legacy-API-Tests für verbotene
unautorisierte Bankimporte oder Benachrichtigungsmarkierungen
sind nur durch vollständige neue Rechte-/Idempotenz-
Gegenproben sinnvoll zu modernisieren, nicht durch
Wegschalten der Authprüfung.

Der vollständige Backend-Coverage-/native-PG-/Frontend-/Restore-
Gesamtlauf muss auf dem später **vollständig kombinierten**
Git-Hash wiederholt werden; getrennte grüne Unterläufe sind
keine Releasefreigabe.


## Fortsetzung: strukturell sichere Migrationen und tatsächlich reproduzierte UI-Abnahme

Die früher als „weiter blockiert“ markierte vollständige
`Base.metadata.create_all()`-Übernahme wurde in **dieser noch
nicht integrierten Arbeitskopie** nachvollziehbar repariert.
Ein zusätzlicher Vergleich von ORM-Schema und echter Alembic-
Neuanlage zeigte dabei **13 ORM-exklusive und einen
migrationsspezifischen Index sowie 85 SQL-DDL-Unterschiede**.
Deshalb wurde ausdrücklich **kein pauschales `stamp head`**
implementiert.

Stattdessen prüft der neue rein lesende
`backend/db/migrations/adopt_existing.py` vorhandene additive
Tabellenfamilien vor ihrer Übernahme auf:

- alle Tabellen der jeweiligen Familie vorhanden, keine Teilfamilie,
- identische Spalten, SQL-Typen, Primary Keys und NOT-NULL-Regeln,
- Indizes, Eindeutigkeits- und CHECK-Constraints,
- zugehörige FK-Spalten, Referenzziele und Löschregeln.

Die additive `communication`-, `daily`-, `inbox epoch`-,
`session/number`-, `TEHA`- und
`platform`-Übernahme nutzt diese Prüfung im nur bei vollständig
vorhandenem Schema aufgerufenen Zweig. Im Normalfall
*ohne* diese Tabellen führen die alten Alembic-Migrationen ihre
originalen `CREATE TABLE`-/Indexschritte weiterhin aus.
Nach einer sicheren Übernahme werden die gespeicherten
Communication-/TEHA-Invarianten weiterhin über ihre
immutablen SQL-Guards hergestellt.

Wegen der bewusst minimalen Fremdschlüssel-Deklaration der
historischen TEHA-Migration (`VARCHAR` ohne Länge)
erfolgt die Abnahme vorhandener Tabellen gegen die
**aktuellen kanonischen TEHA-ORM-Modelle**
(`VARCHAR(36)` an den referenzierten IDs) – nicht gegen
den unvollständigen Migrationsstub. Andere Typabweichungen
werden verweigert.

Neuer Nachweis unter
`artifacts/pro-tests/current-unversioned-safe-adoption-sql-5b0c4964f2ae4e9b9f643673a177afec`:
**4/4 SQLite-Tests bestanden** (inklusive vollständiger
unversionierter Testdatenbank, Ausgangsdatenerhalt und Merge-Head).
Sechs weitere Negativ-/Positivfälle
`artifacts/pro-tests/adoption-guard-negative-sql-dbeb389c41aa4b86a11fcd15118cc34f`:
**6/6 SQLite bestanden**, insbesondere fehlende Indexsignatur,
zusätzliche Spalte, nur teilweise vorhandene Familie und
direkt abgebrochener irreversibler Rückbau.

**Zusätzlicher Sicherheitsfund:** Der alte leere SQLite-
Create-All-Test versuchte nach Upgrade einen Downgrade bis in
die dunning-Migration. Die unveränderte TEHA-Migration
verweigert diesen Rückbau aber absichtlich erst mitten im
Upgradegraphen, nachdem SQLite-DLL bereits verändert sein kann.
Daher verweigert die kombinierte
`e1f0a1b2c315`-Merge-Revision den *gesamten*
irreversiblen Downgrade nun **vor der allerersten Schemaänderung** –
auch auf leerer Testdatenbank. Die Dunning-Altprüfung akzeptiert
keinen kaputten Teilzustand mehr. Die dunning-eigene
historische Downgradefähigkeit wird weiterhin separat
auf ihrem tatsächlichen damaligen Head geprüft.

**Herkunft/Integrationshinweis:** Dies sind additive
Fail-closed-Änderungen an mehreren alten Migrationsskripten
*in einem eigenen ungepushten Entwicklungszweig*. Die bereits
an Anwenderdatenbanken ausgeführten Revisionen werden
nicht nachträglich erneut ausgeführt. Eine Freigabe
erfordert Code-/Migrationsreview und einen erneuten
Upgradetest einer echten historischen Backupkopie.
Kein Hauptcheckout oder Live-Datenbankbestand wurde geändert.

**Frontend-Nachtrag:** Im unabhängigen
`pro/stage-frontend-compat-20261016` wurde der anfängliche
rote Gesamtlauf (38 bzw. 30 Fehler) durch getrennte
Komponentenversionierung, URL-gebundene Testmocks,
DTO-Fail-closed-Verhalten und reduzierte parallele
Vitest-Arbeiter abgearbeitet. Auf
`artifacts/pro-tests/frontend-committed-9f34d128-b34341b9f7244a4fac86ecdcd3a2335a/vitest.log`
wurden **657/657 Frontendtests aus 104 Testdateien** nach
separatem Commit reproduziert (237 Sekunden). Der Frontendstand
ist noch **nicht** mit dem Full-Matrix-Backendstand vereinigt.

Der vollständige ältere Backend-Coveragelauf mit
54 roten Fällen wird nicht überschrieben, um die
neueren, kleinen grünen Untergruppen zu schönen.
Die danach gestartete `migration-suite-after-adoption`
ist eine eigene Regression; ein offenes Ergebnis
wird bis zum tatsächlichen Exit nicht als erfolgreich angegeben.
