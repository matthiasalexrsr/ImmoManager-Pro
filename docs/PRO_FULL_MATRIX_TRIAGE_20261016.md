# Vollmatrix-ImmoManager PRO – evidenzbasierte Fehler-Triage vom 16.10.2026

**Status: Entwicklungs-/Testinfrastruktur-Checkpoint, keine Gesamtfreigabe.**
Eigener QA-Zweig `pro/stage-qa-evidence-20261016` aus
`57ab0a561904feefde50cffc5b1cd10407002d31`.
Die anfänglichen Diagnosearbeiten im parallelen
`pro/stage-full-matrix-20261016` wurden ausschließlich
für die vier QA-Dateien und dieses Dokument byteidentisch in
einen unabhängigen Zweig übertragen. Dort inzwischen separat
entstandene Schemaadoptionsänderungen wurden **nicht**
überschrieben oder als Bestandteil dieses Checkpoints ausgegeben.
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
Runtimeadresse und den **SHA256 des Teststarters**. Bei CP1252-Terminals
werden nicht darstellbare Unicode-Diagnosezeichen als Escape ausgegeben,
damit die tatsächliche Pytest-Fehlerursache und `result.json` nicht
durch einen Sekundärfehler beim Logausdruck verloren gehen. Die
vollständige originale Diagnose bleibt in UTF-8 im `pytest.log`.
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
- Erste Gegenproben im isolierten Ausgangszweig:
  `artifacts/pro-tests/storage-policy-contract-memory-73c3da5b166b420c8357a7260b9ffa53`
  und `artifacts/pro-tests/storage-policy-contract-sql-3f442d05e6a642f0923c3d44483fea64`:
  jeweils **14/14** bestanden, 0 Skip.
  Die QA-Evidence-Kopie wiederholt dies unter
  `artifacts/pro-tests/qa-evidence-memory-memory-d153dd94078b4ae3b6f2dc5f0108a070`
  mit **15/15**, einschließlich eines echten synthetischen
  Handover-Fotouploads nach der Windows-Pfadkorrektur.

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


## Belegte Nachprüfung im unabhängigen QA-Evidence-Zweig

`artifacts/pro-tests/qa-evidence-sql-sql-0aba6e6ca208419bb4a4bdd4146ed4fd`:
**16/16 SQLite bestanden**, 0 Skip. Dieser Lauf benutzt
die aktuelle, bytegleich übertragene Teststarterversion und prüft
autorisierte S3-Bucketidentität, Windows-Traversal-Verweigerung,
geschützten Fotoupload **und** die folgenden Portfolio-Grenzen.

Ein bisheriger globaler GET-Endpunktvergleich verlangte,
dass die persönlichen Connection-, Kommunikations-, TEHA- und
Benachrichtigungsdaten eines eingeschränkten Mitarbeiters
denen des völlig **anderen** Eigentümerkontos entsprechen.
Das ist kein gültiges Datenschutzorakel. Stattdessen werden
dieselben angemeldeten Mitarbeiter-Receipts und -Prüfsummen
*vor und nach dem Entfernen des fremden Portfolios* verglichen.
Portfolio-gebundene Geschäftszahlen werden weiterhin zusätzlich
gegen die unabhängige Eigentümerinstallation verglichen.
Dies ist eine **strengere Nutzeridentitätsprüfung**, kein
globaler Read-Freibrief: Ändert sich eine private oder fachliche
Antwort durch die fremde Datenmenge, bleibt der Test rot.
Die isolierte Memory-Gegenprobe
`restricted-portfolio-parity-memory-fa54bdae840744f1ba04d1a9ddfebd8b`
bestand **1/1**, die SQL-Gegenprobe ist zusätzlich Teil
des obigen **16/16**-Laufs.

Die private QA-Fork-Arbeitskopie enthält **keine** der separat
laufenden Adoption-/Upgrade-Umschreibungen. Solange diese
nicht versioniert, gegen bestehende Nutzeroriginale
getestet und operatorseitig mit Restorepfad freigegeben sind,
bleiben die dokumentierten Legacy-Migrationsblocker offen.
