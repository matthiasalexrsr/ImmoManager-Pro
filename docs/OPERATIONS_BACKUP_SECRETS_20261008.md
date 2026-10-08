# Betrieb: explizites Upgrade, Vollbackup, Wiederherstellungsprobe, Geheimnisse

Stand 8. Oktober 2026, Branch `claude/ops-secrets-backup` (auf `claude/dreamy-gauss-nmaxhn`, `8578a66`). Umsetzung der Pakete „P1 I: Geheimnisse/Integrationen“ (Teil Geheimnisse, Schlüssel, Vollbackup) und „P1 L: Betrieb“ aus Abschnitt 9 von `CLAUDE_HANDOFF_20261007.md`. **Keine neue Migration**: Alembic-Head bleibt `b8e3d5f7a2c4`.

## Regel

1. **Der normale Start ändert kein bestehendes Schema.** Eine leere Datenbank wird angelegt und auf den Head gestempelt. Eine Datenbank auf dem Head startet. Jede andere Datenbank wird mit einer klaren Meldung und dem Befehl abgewiesen: älterer Stand, ohne Versionsstand (alte Desktop-Installation) oder neuerer Stand. Der Speicher-Fallback (`ALLOW_INMEMORY_FALLBACK`) verdeckt das nie.
2. **Schemaänderungen laufen nur über das explizite Upgrade** `python -m backend.upgrade` (Windows-Paket: `ImmoManager-Pro.exe upgrade`). Es legt **vorher ein geprüftes Vollbackup** an. Scheitert das Backup, bleibt das Schema unverändert. Es gibt kein automatisches Downgrade.
3. **Geheimnisse liegen nie im Klartext auf der Platte**, soweit das Programm sie verwaltet (Integrationskonfiguration). Die API zeigt sie nie, sondern nur `***`. Fehlt der Schlüssel, werden Änderungen gesperrt. Es wird nichts zurückgesetzt und kein Ersatzschlüssel erfunden.
4. **Ein Vollbackup ist vollständig und prüfbar.** Es enthält Datenbank, Anhänge, Konfiguration und Schlüssel in einem Archiv, mit SHA-256 je Datei. Ein Archiv gilt erst nach erfolgreicher Prüfung als vorhanden. Wiederhergestellt wird nie über laufende Daten, sondern in ein neues Verzeichnis.
5. **Jeden Monat beweist eine isolierte Wiederherstellungsprobe**, dass die Sicherung tatsächlich zurückgespielt werden kann.

## Technik

### Startwächter und explizites Upgrade

| Stelle | Vorher | Jetzt |
| --- | --- | --- |
| `backend/dependencies.py` → `db/session.create_tables()` | Bei **jedem** Import `create_all` (ergänzte fehlende Tabellen, nie Spalten), `adopt_legacy_access`, Archiv-Trigger | `db/schema_state.ensure_current()`: leer → `create_all` + Trigger + `alembic stamp head`; Head → Start; sonst `SchemaUpgradeRequired` (wird auch bei `ALLOW_INMEMORY_FALLBACK=true` durchgereicht) |
| `app.py` Lifespan | `AUTO_MIGRATE=true` → `alembic upgrade head` im Serverprozess, Fehler nur geloggt | entfernt; `AUTO_MIGRATE` wird ignoriert (Hinweis im Log) |
| `routers/admin_runtime.restore_backup` (.db) | danach `ensure_archive/access/job_schema` (nur Tabellen) | Revision der Sicherung vorher prüfen (neuer/fremd → 400, nichts ersetzt); nach der Sicherheitskopie bei Bedarf `run_migrations` auf die Datei; scheitert das, wird der vorherige Stand zurückgespielt |
| `migrations/env.py` | URL aus `DATABASE_URL` oder `alembic.ini` | URL vom Aufrufer (`config.attributes["database_url"]`), sonst `DATABASE_URL`, sonst ini; eigene Verbindung ohne App-Pragmas; Übernahme unversionierter DBs auch bei leerer `alembic_version` |
| Desktop-Launcher `python -m backend` / `.exe` | importierte die App direkt | `run_upgrade_step()` vor dem Import: nur bei Bedarf Vollbackup + Upgrade; leere DB → normaler Start; `--no-upgrade` überspringt; Unterbefehle `upgrade …` und `ops …` |
| `docker-entrypoint.sh` | `alembic upgrade head` | `python -m backend.upgrade` (überspringbar mit `IMMO_SKIP_UPGRADE=true`) |
| `scripts/update.sh` | `alembic upgrade head` | `python -m backend.upgrade`; außerdem `pip … -c constraints.txt`, `npm ci` |
| `updater.py` | Alembic im laufenden Prozess mit `alembic.ini` (konfigurierte Logging neu) | Unterprozess `python -m backend.upgrade` mit dem neuen Code; DB-Schnappschuss und Rücksprung per Online-Backup-API statt Dateikopie |

Zustände (`schema_state.SchemaStatus.state`): `empty`, `current`, `outdated`, `unversioned`, `newer`. Rückgabecodes des Upgrades: 0 erledigt bzw. nichts zu tun, 2 Backup fehlgeschlagen (Schema unverändert), 3 Upgrade fehlgeschlagen (das Pre-Upgrade-Archiv existiert), 4 Datenbank neuer als das Programm, 5 Upgrade nötig (nur `--check`).

Entscheidung **Abweisen statt Wartungsmodus**: Ein Nur-Lese-Betrieb auf einem Schema, das der Code nicht kennt, kann trotzdem an fehlenden Spalten scheitern. Der Desktop-Launcher, Docker und das Update-Skript führen das Upgrade ohnehin aus. Abweisen ist deshalb eindeutig und folgenlos.

### Geheimnisse (`backend/services/secret_box.py`)

- AES-256-GCM (`cryptography` 49.0.0, jetzt exakt gepinnt), 96-Bit-Zufallsnonce. Format `enc:v1:<Schlüssel-ID>:<base64url(nonce‖chiffre‖tag)>`. Als Associated Data dient `integrations/<id>/<feld>`, ein kopierter Wert entschlüsselt in einem anderen Feld also nicht.
- Schlüsselring `<DATA_DIR>/secrets/keyring.json` (Format `immomanager-keyring` v1, aktiver Schlüssel plus ältere). Er entsteht erst beim ersten gespeicherten Geheimnis, atomar geschrieben, Datei 0600 und Verzeichnis 0700 (POSIX). Unter Windows liegt er im benutzereigenen `%LOCALAPPDATA%`. Alternativ setzt `SECRET_KEYS` Schlüssel aus der Umgebung (base64url, 32 Byte, kommagetrennt, der erste ist aktiv). Diese Schlüssel schreibt das Programm nie auf die Platte.
- `IntegrationManager` (Konfiguration: `integrations.json`): im Speicher Klartext, auf der Platte versiegelt. Beim Laden werden vorhandene Klartextgeheimnisse sofort versiegelt, atomar und ohne Verlust. Gelingt das nicht, bleiben sie bis zum nächsten Speichern im Klartext; das wird protokolliert und in der Übersicht gezeigt. Fehlende oder unbekannte Schlüssel und manipulierte Werte führen zu `persistence_error`, gesperrten Änderungen und einer klaren 503-Meldung. Die Datei bleibt unverändert.
- Rotation: `python -m backend.ops rotate-key` legt einen neuen aktiven Schlüssel an, versiegelt alle Werte neu und behält die alten Schlüssel zum Lesen.
- Das Integrationsjournal (`integrations.json.history.sqlite3`) enthielt schon vorher keine Geheimnisse, Werte sind dort `***`. Es ist im Vollbackup enthalten.

### Vollbackup (`backend/services/full_backup.py`)

Archiv `<BACKUP_DIR>/full/immomanager-full-<UTC>Z-<anlass>-<zufall>.zip` (ZIP64) plus `.sha256` (sha256sum-Format):

| Eintrag | Inhalt |
| --- | --- |
| `manifest.json` | Format/Version, Anlass, Zeit, App-Version, Code-Head, DB-Revision, Zeilenzahlen je Tabelle, Uploads, Schlüssel-IDs (benötigt/enthalten/fehlend), SHA-256 + Größe jeder Datei |
| `database/immo_manager.sqlite3` | SQLite: Online-Backup-API (konsistent bei laufendem WAL-Betrieb), `quick_check` |
| `database/postgres.dump` | PostgreSQL: `pg_dump --format=custom` mit `--snapshot` einer `REPEATABLE READ`-Transaktion, Zeilenzahlen aus demselben Snapshot. Ohne `pg_dump` wird klar abgelehnt („pg_dump nicht gefunden … PG_BIN_DIR setzen“). |
| `uploads/…` | alle regulären Dateien des Upload-Verzeichnisses (keine Symlinks) |
| `config/integrations.json`, `config/integrations-journal.sqlite3` | Integrationskonfiguration (Geheimnisse als Chiffrat), Journal (Online-Backup) |
| `secrets/keyring.json`, `config/env` | Schlüsselring und `<DATA_DIR>/.env`, nur ohne `BACKUP_PASSPHRASE` |
| `secrets/secrets.enc` | mit `BACKUP_PASSPHRASE`: Schlüsselring und `.env`, mit scrypt (n=2^15, r=8, p=1) und AES-256-GCM versiegelt; Klartext-Hashes stehen im Manifest |

Ablauf: Sperrdatei (eine Sicherung bzw. Probe gleichzeitig), Arbeitsverzeichnis, Archiv als `.partial` schreiben, `fsync`, Hash bilden, **vollständige Prüfung**, umbenennen, `.sha256` schreiben. Danach optional die Kopie ins zweite Ziel: dort ebenfalls als `.partial`, Hash der Kopie gegen den Original-Hash, umbenennen. Zum Schluss die Aufbewahrung auf beiden Zielen. Jedes Ergebnis landet im Betriebsprotokoll `<BACKUP_DIR>/full/ops-log.jsonl`, Fehler eingeschlossen.

Prüfung (`verify_archive`): Archiv-Hash gegen `.sha256` und gegen den protokollierten Wert. Weiter Hash und Größe jeder Datei laut Manifest, keine Datei außerhalb des Manifests, keine unsicheren Pfade (`..`, absolut, `\`), keine doppelten Einträge. Das Manifest muss das passende Format haben.

Aufbewahrung: die jeweils neueste Sicherung je lokalem Tag für 14 Tage mit Sicherung, je Monat für 6 Monate und die 3 neuesten vor Upgrades. Die neueste Sicherung bleibt immer erhalten. Einstellbar über `BACKUP_KEEP_DAILY`, `BACKUP_KEEP_MONTHLY` und `BACKUP_KEEP_PRE_UPGRADE`. Die Tage zählen Sicherungstage, nicht Kalendertage. Ein Desktop, der nur gelegentlich läuft, behält also 14 Stände.

### Wiederherstellungsprobe und Wiederherstellung

- Probe (`restore_probe`): Archiv prüfen, in `<BACKUP_DIR>/full/.probe-<zufall>` entpacken und jede Datei erneut hashen. SQLite schreibgeschützt öffnen und `integrity_check` ausführen. Revision und Zeilenzahlen gegen das Manifest abgleichen, archivierte Originale beweisen (`verify_archived_originals`). Ist die Sicherung älter als der Code, wird das Upgrade **an der Probe-Kopie** getestet. Die versiegelten Integrationsgeheimnisse werden mit den archivierten Schlüsseln entschlüsselt, mit Passphrase nach deren Entschlüsselung. Zum Schluss wird das Verzeichnis gelöscht (`probe_dir_removed`).
- PostgreSQL-Probe: `pg_restore --list`. Mit `RESTORE_PROBE_POSTGRES_URL` (Wegwerf-Server mit `CREATE DATABASE`) zusätzlich: eigene Datenbank anlegen, `pg_restore`, Revision, Zeilenzahlen und Originale prüfen, Datenbank wieder löschen.
- Wiederherstellung (`python -m backend.ops restore <archiv> --target <neues Verzeichnis>`): erst prüfen, dann als Datenverzeichnis auslegen: `immo_manager.db`, `uploads/`, `integrations.json` und Journal, `secrets/keyring.json` (0600). Dazu `.env` **ohne Pfadangaben** (`DATA_DIR`, `UPLOADS_DIR`, …, bei SQLite auch `DATABASE_URL`) und das Original als `.env.from-backup`. Bei PostgreSQL wird `postgres.dump` abgelegt, optional per `--pg-target-url` in eine **leere** Datenbank eingespielt. Ein nicht leeres Ziel wird abgelehnt.

### Zeitplan (dauerhafter Job-Kern)

`services/jobs/scheduler.ops_periodic()` gilt nur mit SQL-Store und `BACKUP_SCHEDULE_ENABLED=true`:

- `ops.full_backup` täglich `BACKUP_DAILY_AT` (Standard 01:30 Europe/Berlin), höchstens 3 Versuche
- `ops.restore_probe` monatlich am `RESTORE_PROBE_DAY` (Standard 1.) um `RESTORE_PROBE_AT` (03:30), auf den Monatsletzten begrenzt, höchstens 3 Versuche

Wie bei den übrigen Jobs gilt ein Lauf je lokalem Termin. Nach einer Ausfallzeit, etwa wenn der Desktop nachts aus ist, läuft der verpasste Termin gleich nach dem Start. Lange Kopien halten die Lease per Heartbeat, gedrosselt auf alle 15 s. `MonthlyAt` ist neu in `services/jobs/schedule.py` und so sommerzeitfest wie `DailyAt`.

### Betriebsübersicht

- `GET /api/v1/admin/operations`: Schemazustand, letzte bzw. letzte erfolgreiche Sicherung und Probe, Archive mit Größe, Anlass, Hash und Ablage im zweiten Ziel. Dazu Ziele, Aufbewahrung, Zeitplan, Schlüsselstatus (aktive ID, Quelle, Zahl versiegelter und unversiegelter Werte, IDs in Gebrauch, nie Werte), die letzten Job-Läufe, Fehler und Hinweiscodes. Die Hinweiscodes sind `no_second_target`, `second_target_failed`, `no_backup`, `backup_stale` (>36 h), `last_backup_failed`, `no_probe`, `probe_stale` (>35 Tage), `last_probe_failed`, `keys_unprotected`, `keys_not_in_backup`, `plaintext_secrets`, `secrets_error`, `schema_not_current` und `schedule_disabled`.
- `POST /api/v1/admin/operations/backup` und `POST /api/v1/admin/operations/restore-probe`: Vollbackup bzw. Probe sofort. Ohne Datenbank (Speicher-Modus) antworten beide mit 409.
- Rechte: Rolle Eigentümer oder Verwalter. Zusätzlich ist der Installationsbereich nötig: Eingeschränkte Portfolio-Konten erhalten 403, über die Middleware für `/admin` und über `require_installation_scope()` im Endpunkt.
- UI: Einstellungen → System → Panel „Betrieb: Vollbackup & Wiederherstellungsprobe“ (`frontend/src/pages/settings/OperationsSection.jsx`), Texte in de/en/es (`settings.operations.*`).

### Reproduzierbare Abhängigkeiten

- `requirements.txt` / `backend/requirements.txt`: alle direkten Abhängigkeiten exakt, neu sind `cryptography==49.0.0` und `psycopg2-binary==2.9.13`. `constraints.txt` pinnt den gesamten transitiven Baum (41 Pakete, geprüft mit Python 3.11.15). Installation mit `pip install -r requirements.txt -c constraints.txt`. CI, Docker, `start_windows.ps1`, `install.*`, `build.*`, `update.sh` und der Windows-Paket-Workflow nutzen das. CI-Werkzeuge sind gepinnt (`ruff==0.15.20`, `mypy==2.4.0`, `pytest-cov==7.1.0`, `pdfplumber==0.11.10`); `pip-audit` bleibt absichtlich aktuell. `backend/requirements-dev.txt` widersprach sich bei pytest (9.0.2 gegen 9.0.3) und ist bereinigt.
- Frontend: `package-lock.json` war schon vorhanden; alle Installationspfade nutzen jetzt `npm ci`. Node 24.21.0 wie in CI.
- Docker: `python:3.11.15-slim-bookworm@sha256:d29f48a3…`, `postgres:16.15-alpine@sha256:721873c3…`. Das App-Image enthält `postgresql-client-16` aus PGDG (bookworm liefert 15, und `pg_dump` 15 lehnt einen 16er-Server ab). Volume `appdata:/app/data` mit `DATA_DIR=/app/data`; vorher lagen Uploads im Container und gingen beim Neuaufbau verloren.
- **Neu bauen:** (1) Pin in `requirements.txt` ändern, frische venv, `pip install -r requirements.txt` ohne `-c`, beide Testmodi ausführen. (2) Aus dieser venv die Abhängigkeitshülle von `requirements.txt` als `constraints.txt` schreiben, beide Dateien committen. (3) Für Docker den Digest neu holen, z. B. `docker buildx imagetools inspect python:3.11.X-slim-bookworm`, und Tag und Digest im `Dockerfile` bzw. in `docker-compose.yml` ersetzen. (4) Frontend: `npm install <paket>@<version>`, `npm ci && npm test && npm run build`, Lockfile committen.

## Nachweise (8. Oktober 2026, Linux, Python 3.11.15, PostgreSQL 16 lokal)

| Prüfung | Ergebnis |
| --- | --- |
| Backend Speicher-Modus + PostgreSQL (`IMMO_TEST_POSTGRES_ADMIN_URL`) mit Coverage | 1472 bestanden, 8 übersprungen, Coverage 88,86 % |
| Backend SQL-Modus (`TEST_STORE_BACKEND=sql`) + PostgreSQL mit Coverage | 1471 bestanden, 9 übersprungen, Coverage 87,14 % |
| `ruff check backend` | sauber |
| `python -m mypy backend` (2.4.0) | keine Fehler, 272 Dateien |
| Frontend `npx vitest run` | 45 Dateien, 251 Tests bestanden |
| CLI-Rauchtest (frische Datenverzeichnisse) | `upgrade --check`, `upgrade`, `ops backup`, `verify`, `probe`, `status`, `restore` erfolgreich |
| `npm run lint`, `npm run build` | sauber bzw. gebaut |
| Ausgangslage vor der Änderung | Speicher 1418 bestanden / 21 übersprungen; SQL+PG 1430 / 9 |

Neue Tests: `backend/tests/test_operations_backup.py` (Speicher- und SQL-Modus), `backend/tests/test_operations_postgres.py` (echter PostgreSQL-Server), `frontend/src/test/OperationsSection.test.jsx`. Angepasst wurden `test_portfolio_access.py` (Erststart nach Update und alte Sicherung laufen jetzt über das explizite Upgrade) sowie `test_admin_backup.py` (WAL-Regression auf echter App-Datenbank; fremde oder neuere Sicherung werden abgewiesen, bevor etwas ersetzt wird).

Abgedeckt sind:

- Verschlüsselung: Rundlauf mit Schlüssel-ID und Feldbindung, Dateirechte 0600/0700. Rotation mit erneutem Versiegeln. Klartext wird beim Laden ohne Verlust verschlüsselt. Maskierung in API und Übersicht, das maskierte Zurücksenden behält das Geheimnis. Fehlender Schlüssel ergibt Fehler, Sperre, unveränderte Datei und keinen erfundenen Schlüssel; die 503 nennt den Grund ohne Wert. Manipuliertes Chiffrat sperrt. `SECRET_KEYS` schreibt keine Datei. Passphrase-Umschlag.
- Vollbackup: alle Bestandteile, Manifest und Hashes, Prüfung bestanden. Erkannt werden ersetzte Upload-Inhalte, zusätzliche Dateien, Pfad-Traversal, gekippte Bytes (`.sha256`) und ein falscher protokollierter Hash.
- Probe: Zeilenzahlen, Revision, Uploads, Entschlüsselung, Probe-Verzeichnis gelöscht, Protokoll. Eine manipulierte Sicherung lässt die Probe scheitern und wird protokolliert. Mit Passphrase: ohne Passphrase nur ein Hinweis, mit Passphrase entschlüsselt. Bei einer älteren Revision wird das Upgrade an der Probe-Kopie getestet, die Originaldatei bleibt unverändert.
- Wiederherstellung in ein neues Verzeichnis: Uploads, Schlüssel und `.env` ohne Pfade; das Geheimnis ist mit dem wiederhergestellten Schlüssel lesbar; ein nicht leeres Ziel wird abgelehnt.
- Zweites Ziel: verifizierte Kopie bzw. gemeldeter Fehler bei behaltenem Primärarchiv. Fehlerprotokoll, Sperre gegen gleichzeitige Läufe, fehlendes `pg_dump`.
- Aufbewahrung über 280 Tage plus Pre-Upgrade-Stände: genau 14 + 4 + 3 Archive bleiben, Prüfsummendateien werden mit gelöscht.
- Zeitplan: 10-Minuten-Ticks über vier Tage ergeben genau einen Backup-Lauf je Berliner Tag und eine Probe je Monat. Ohne Datenbank oder abgeschaltet gibt es keine Ops-Jobs. Der Monatstermin ist begrenzt und sommerzeitfest. Die echten Handler sichern und proben, und am selben Tag bzw. Monat folgt kein zweiter Lauf.
- Upgrade: Der Start weist veraltete, unversionierte und neuere Datenbanken ab, ohne das Schema zu ändern. Das gilt auch per Unterprozess-Import mit `ALLOW_INMEMORY_FALLBACK=true`. `--check` liefert 5. Das Upgrade erstellt das Pre-Upgrade-Archiv mit der alten Revision, Protokolleintrag inklusive, und ein zweiter Lauf tut nichts. Scheitert das Backup, findet kein Upgrade statt (Code 2). Eine neuere Datenbank wird nie angefasst (Code 4). Eine alte unversionierte Desktop-Datenbank wird übernommen, Konten erhalten `legacy_all`. Der Launcher-Schritt überlässt eine leere DB dem Start. Eine beim Start frisch angelegte DB hat dieselben Tabellen und Spalten wie eine migrierte.
- PostgreSQL: Vollbackup per Snapshot-`pg_dump`, Zeilenzahlen, Probe auf eigener Wegwerf-DB, die danach gelöscht ist. Ohne Probe-Server nur Dump-Prüfung mit Hinweis. Wiederherstellung per `pg_restore` in eine leere DB, eine nicht leere wird abgelehnt. Der Start weist eine veraltete DB ab, das Upgrade sichert vorher.
- API: eingeschränktes Portfolio-Konto und Leserolle erhalten 403 (GET und beide POST). Direkter Funktionsaufruf im eingeschränkten Bereich ergibt 403. Eigentümer: 200. Im SQL-Modus Sicherung und Probe über die API, Übersicht ohne Geheimnis.

## Bewusst offen

- **Alte verschlüsselte Journal- und Secretpakete** der historischen Zweige (andere Maschine) lagen nicht vor und sind **nicht geprüft**. Das neue Format ist versioniert (`enc:v1`, Schlüsselring `immomanager-keyring` v1, Archiv `immomanager-full-backup` v1). Ein späterer Import alter Pakete braucht einen eigenen Leser, der deren Schlüsselquelle ausdrücklich angibt. Die Werte werden dann über den `IntegrationManager` neu versiegelt.
- **Fachliche Abnahme der Integrationsaktionen, Felder und Ergebnisstatus** (zweiter Teil von P1 I) war nicht Teil dieser Runde.
- Weitere Geheimnisse außerhalb der Integrationskonfiguration sind nicht verschlüsselt: `.env` (`JWT_SECRET_KEY`, `DATABASE_URL`, ggf. `UPDATE_GITHUB_TOKEN`, `BACKUP_PASSPHRASE`), TOTP-Geheimnisse in `users.totp_secret` und IBANs (`iban_encryption.py` ist weiterhin unbenutzt und leitet seinen Schlüssel aus dem JWT-Geheimnis ab). Der Schutz der `.env` beruht auf Dateirechten. Im Archiv ist sie nur mit Passphrase versiegelt.
- Ohne `BACKUP_PASSPHRASE` liegen Schlüssel und Chiffrat im selben Archiv. Das Archiv ist dann so schutzbedürftig wie die Daten selbst; die Übersicht warnt (`keys_unprotected`). Die Passphrase steht, wenn gesetzt, in der `.env` der Installation. Sie schützt Kopien im zweiten Ziel, nicht den Rechner selbst.
- Unter Windows setzt das Programm keine eigenen ACLs auf die Schlüsseldatei. Es verlässt sich auf das benutzereigene `%LOCALAPPDATA%`.
- Das Manifest ist per SHA-256 gegen Beschädigung geschützt, gegen gezielte Fälschung nur über den im Betriebsprotokoll und in `.sha256` festgehaltenen Archiv-Hash. Eine Signatur fehlt.
- Uploads, die während einer Sicherung geschrieben werden, können fehlen oder hinzukommen. Die Datenbank ist konsistent, die Dateiliste ist ein Momentbild. Hochgeladene Dateien werden normalerweise nicht verändert.
- Das Zählen aller Zeilen (SQLite und PostgreSQL) kostet bei sehr großen Datenbanken Zeit. Archive über ~10 GB sind nicht gemessen; der Nachweis für eine Million Zeilen aus der Härtung gilt nicht automatisch für Sicherung und Probe.
- PostgreSQL-Probe ohne `RESTORE_PROBE_POSTGRES_URL` prüft nur die Lesbarkeit des Dumps. Docker-Build und Windows-Paket-Workflow (Probestart plus `upgrade --check`, `ops backup`, `ops probe` aus dem Paket) wurden hier **nicht ausgeführt** (kein Docker-Daemon, kein Windows-Runner). Die Paketversion von `postgresql-client-16` und PyInstaller sind nicht exakt gepinnt. Hashes (`--require-hashes`) fehlen in `constraints.txt`.
- Mehrere Server-Prozesse mit verschiedenen `BACKUP_DIR` würden je eigenes Protokoll führen. Die Sperre gilt je Backup-Verzeichnis.

## Runbook

### Sicherung

- Automatisch: läuft im Programm täglich (01:30 Europe/Berlin oder nach dem Start, wenn der Termin verpasst wurde). Kontrolle: Einstellungen → System → „Betrieb“. Grün heißt: letzte Sicherung erfolgreich, Probe < 35 Tage, keine Hinweise.
- Sofort: Knopf „Vollbackup jetzt“, oder `python -m backend.ops backup` bzw. `ImmoManager-Pro.exe ops backup`.
- Bei ausgeschaltetem Desktop zusätzlich nachts per Aufgabenplanung: `python scripts\backup_scheduler.py schedule` (ruft `python -m backend ops backup --data-dir …` auf).
- Zweites Ziel einrichten (dringend empfohlen): `BACKUP_SECOND_TARGET=\\nas\backup\immomanager` (Windows) bzw. gemountetes Verzeichnis (Docker: als Volume einbinden und den Pfad setzen). Jede Kopie wird per SHA-256 geprüft; Fehler erscheinen als `second_target_failed`.
- Ein Archiv prüfen: `python -m backend.ops verify <archivname-oder-pfad>`. Ohne Programm genügt der Hash-Vergleich mit `sha256sum -c <archiv>.sha256` bzw. PowerShell `Get-FileHash <archiv> -Algorithm SHA256`.
- PostgreSQL: `pg_dump` in gleicher oder neuerer Hauptversion als der Server muss erreichbar sein (`PG_BIN_DIR`). Für echte Probe `RESTORE_PROBE_POSTGRES_URL` auf einen Wegwerf-Server setzen.

### Wiederherstellung

1. Programm bzw. Dienst stoppen.
2. Archiv wählen und prüfen: `python -m backend.ops verify <archiv>`.
3. In ein **neues** Verzeichnis wiederherstellen: `python -m backend.ops restore <archiv> --target D:\ImmoManagerPro-restore` (Windows-Paket: `ImmoManager-Pro.exe ops restore …`). Mit Passphrase: `set IMMO_RESTORE_PASS=…` und `--passphrase-env IMMO_RESTORE_PASS`, oder Eingabe am Prompt.
4. `.env` im Zielverzeichnis prüfen (Pfade sind entfernt; Original in `.env.from-backup`). Bei PostgreSQL: leere Datenbank anlegen und `--pg-target-url` nutzen oder `pg_restore --no-owner --dbname <url> postgres.dump`.
5. Programm mit dem neuen Datenverzeichnis starten (`start.bat -DataDir D:\ImmoManagerPro-restore` bzw. `--data-dir`), oder die Verzeichnisse bei gestopptem Programm tauschen. Der Launcher führt das Upgrade aus, falls die Sicherung älter ist (vorher wieder ein Vollbackup).
6. Anmeldung, Dokumente und Integrationen prüfen. Erscheint „Schlüssel … fehlt“, liegt der passende `secrets/keyring.json` nicht im Datenverzeichnis.

Einzelne ältere `.db`-Sicherungen (`backups/backup_*.db`) lassen sich weiter über Einstellungen bzw. `/admin/restore` einspielen. Eine Sicherheitskopie entsteht vorher; ältere Stände werden danach ausdrücklich hochgezogen, neuere oder fremde abgewiesen.

### Schlüsselverwahrung

- Der Schlüssel liegt in `<Datenverzeichnis>\secrets\keyring.json`. Ohne ihn sind gespeicherte Integrationspasswörter (z. B. SMTP) nicht lesbar; die übrigen Daten sind davon unabhängig.
- Er ist in jedem Vollbackup enthalten. Empfehlung: `BACKUP_PASSPHRASE` setzen und die Passphrase **getrennt** aufbewahren, im Passwortmanager und auf Papier im Umschlag. Ohne Passphrase sind Archive so schutzwürdig wie der Schlüssel.
- Zusätzlich einmalig nach Einrichtung und nach jeder Rotation eine Kopie von `keyring.json` getrennt sichern, etwa auf einem verschlüsselten USB-Stick.
- Mit `SECRET_KEYS` (z. B. Docker-Secret) ist der Schlüssel nicht im Archiv, sofern er nicht in der gesicherten `.env` steht. Die Übersicht meldet das (`keys_not_in_backup`).
- Rotation: `python -m backend.ops rotate-key`, danach „Vollbackup jetzt“. Alte Schlüssel erst entfernen, wenn `key_ids_in_use` in der Übersicht nur noch den neuen zeigt **und** keine aufzubewahrende Sicherung sie mehr braucht.
- Schlüssel verloren: Integrationsgeheimnisse neu eingeben, nachdem `integrations.json` bewusst gesichert und die betroffenen Felder dort entfernt wurden. Das Programm setzt nie selbst zurück.

### Upgrade

- **Desktop/Windows**: neue Version installieren oder entpacken und wie gewohnt starten. Der Launcher prüft den Stand. Bei Bedarf meldet er „Vollbackup vor dem Upgrade …“, danach „Upgrade abgeschlossen“. Scheitert ein Schritt, startet das Programm nicht; die Daten sind unverändert bzw. das Archiv liegt in `backups\full`. Nur prüfen: `ImmoManager-Pro.exe upgrade --check`.
- **Server/Quellinstallation**: Dienst stoppen, `git pull`, `pip install -r requirements.txt -c constraints.txt`, `python -m backend.upgrade`, starten (oder `scripts/update.sh`).
- **Docker**: `docker compose build && docker compose up -d`. Der Entrypoint führt `python -m backend.upgrade` aus (Backup per `pg_dump` in `/app/data/backups/full`). Bei Fehlern startet der Container nicht; Logs: `docker compose logs app`.
- Meldung „Datenbank stammt aus einer neueren Programmversion“: das Programm aktualisieren oder eine Sicherung passender Version einspielen. Es gibt kein automatisches Downgrade.
- Notfall ohne Sicherung (nur wenn eine geprüfte Sicherung anderswo existiert): `python -m backend.upgrade --no-backup`.
