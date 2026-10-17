# ImmoManager Pro – integrierte Schnittstellen-/Frontend-/Zählerprüfung

**17.10.2026 – technischer Entwicklungscheckpoint, keine Auslieferungsfreigabe.**

## Unveränderte Grenzen

Neuer isolierter Worktree `pro-stage-integrated-ui-billing-20261017`,
Entwicklungszweig `pro/stage-integrated-ui-billing-20261017`.
Die Ursprünge `pro/stage-full-matrix-20261016` (Backend,
FinTS-Prüfvertrag, Migration) und
`pro/stage-frontend-compat-20261016` (Nachrichtensicherheit,
persönliche Benachrichtigungen, 657 Komponentenfälle) sowie
`pro/stage-billing-coverage-20261016` (historische
Messabdeckung) wurden mit echten Git-Merge-Commits vereinigt.
Kein Rebase, Reset, Cherry-Pick nicht geprüfter Quellen oder
Überschreiben fremder Worktrees. Der zentrale Checkout
`claude-review-20261013` blieb bei `04021da5` sauber;
laufende Installationen 8000/8765, echte Anbieter, produktive
Daten und Schlüssel blieben unangetastet.

Der **gemeinsame Produktcode-Commit** aller unten tatsächlich
geprüften Komponenten lautet:

`12ac71e76afebb25e2ed29fce188ce19a3a3c15e`

Das ist der exakte Git-Head für Backend, Frontend, TEHA,
FinTS, Verbindungsevidenz, portable Plugin- und
Zählerprüfungen. Spätere reine Dokumentationscommits ersetzen
diesen Hash nicht in älteren Testergebnissen.

## Wirklich durchgeführte kombinierte QA

- Vollständiges Frontend: `artifacts/pro-tests/merged-frontend-12ac71e7-51948c9bafcb47529e20a67e868eae1b`.
  **657/657 Tests in 104 Testdateien**, Exit 0; erstmals im
  gemeinsamen Backend-/UI-/Abrechnungsstand. Reproduzierbarer
  Aufruf `npm run test -- --maxWorkers=2 --testTimeout=15000
  --reporter=dot`. Keine Produktassertions gelöscht.
  Frisches `npm ci --ignore-scripts` mit Sperrdatei,
  **ESLint und Vite-Produktionsbuild bestanden**.
- Vollständige statische Backendprüfung:
  `python -m ruff check backend scripts/run_pro_matrix.py`
  sowie `python -m mypy --platform linux backend` erfolgreich
  für **563 Backend-Quelldateien**.
- FinTS 5.0.1 optional frisch und nur in
  `artifacts/pro-tools/fints-libs` aus
  `requirements-bank.txt` installiert. Die
  gemeinsam benutzte Review-Pythonumgebung wurde nicht
  geändert. Der Teststarter muss das optionale
  Library-Verzeichnis **ausdrücklich** einbinden;
  seine Prüfnachweise enthalten Versions- und Codehashes.
  Keine TAN und kein Bankserver kontaktiert.
- `artifacts/pro-tests/combined-main-recovery-sql-sql-657a2701ff134258964757453d26caae`:
  **6/6 SQLite** (authentische Offline-FinTS-Library,
  zwei korrekt abgegrenzte historische Migrationen,
  drei fachliche Messabdeckungsgegenproben).
- `artifacts/pro-tests/merged-platform-restore-sql-sql-8b39c05b83e4461683d28d3e1216fc9b`:
  **1/1 SQLite**. Vollbackup erstellt, unabhängig neu
  eingespielt, bei der neu gestarteten Anwendung angemeldet
  und Originaldaten mit Rechteprüfung über HTTP gelesen.
- `artifacts/pro-native/1e580698cfca45b58024fb4fa78f53cc` und
  `artifacts/pro-tests/owned-native-native-b3c08de21fbe4459a3d29df319e75d51`:
  **19/19 native PostgreSQL** ohne Skip. Auth-/TEHA-
  Publish-/Rights-/Replayfälle, Plugin/S3/portable Migration
  und Messabdeckung; der eigene Testserver ist
  **vollständig beendet**.
- Echter Playwright-Check auf einer **frischen, separat
  wiederhergestellten** synthetischen Testinstallation:
  `artifacts/restored-browser-ruqt3vas/result.json`,
  `browser_verified`, `stopped=true`.
  Login, authentifizierter SHA256-Originaldownload,
  verweigerter anonymer Download, fertig geladenes
  Dashboard und Plugin-/Speichereinstellungen bei
  **320, 360 und 1440 Pixeln**. Die Screenshots wurden
  zusätzlich visuell überprüft. Ein Anbieter wurde
  dabei nicht aufgerufen.

## Originalfehler aus der Backend-Gesamtsuite

Der frühere Gesamtcheck bei `329cda33` war
**2.670 passed / 3 failed / 114 skipped**
bei **84,29 % gemessener Zeilenabdeckung**. Die drei
fehlgeschlagenen Fälle wurden nun mit echte isolierte
`fints==5.0.1` und den historischen, **einzeln
reversiblen** Migrationsrevisionen statt eines
unsicheren Downgrades über moderne geschützte
Sicherungsfamilien repariert. Gezielte Nachläufe:
Memory 3/3, SQLite 3/3; kombinierter Code 6/6 SQLite.
Keine produktive Downgrade-/Originalschutzregel
wurde entfernt.

Der **gesamte** Memory-/Coverage-Lauf auf genau
`12ac71e7` wurde gestartet:
`artifacts/pro-tests/merged-12ac71e7-full-backend-memory-dd8ea92a7d0e4ed585706c87cec0a603`.
Sein Endergebnis ist **in diesem Dokument ausdrücklich
noch nicht belegt**, bis `result.json`, `junit.xml`,
`coverage.xml` und Quell-Hashkette vollständig vorliegen.
Memory-Skips betreffen insbesondere PostgreSQL-spezifische
Szenarien; sie sind keine übergangene native Freigabe.

## Weiter offen – keine Systemfreigabe

1. **Ein** endgültiger Gesamt-Migrationsgraph und Vollrestore
   mit *sämtlichen* Domänen inkl. separatem Kanal-/Portalzweig,
   Dokumentwerkbank, Betrieb, DATEV, TEHA und allen
   historischen Quellakten fehlen noch. Ein
   zuvor blockierter Kanal-Migrations-Schreibaufruf
   wurde nicht umgangen.
2. Alte globale IntegrationManager-Konfiguration und private
   `integration_connections` haben noch keine einzige
   belegbar autoritative Umschalt-/Migrationsgrenze.
3. Echte kontrollierte Zielsysteme/Provider (TEHA,
   Bank/TAN, WhatsApp, IS24/Immowelt/FTPS, Postkauf,
   Aktenwerk, DATEV/WISO, SMTP/IMAP und S3) benötigen
   separate Livevertrags-, Reauth-, Timeout- und
   Ergebnisabgleiche. Synthetische oder Mockbelege
   sind **keine** erfolgreichen Außenaktionen.
4. Weitere ursprünglich beauftragte Fachpakete
   Eigentümerwechsel/Verkauf, Mieterportal/Offline,
   Fachpläne, vollständige Abrechnung/Widerspruch
   und Betriebsautomatisierung fehlen als End-to-End-
   Abnahme weiterhin. Die Zählerlücke allein erfüllt
   Paket 4 nicht.
5. Komplette Gesamtmatrix für SQLite, native
   PostgreSQL, 100k-/1m-Bestände, parallele Jobs,
   Browserrollen und vollständige Gesamt-CI sind
   nach einer **finalen gemeinsamen Integration**
   erst erneut abzunehmen.

**Keine Abnahme und keine Auslieferung der
laufenden Anwenderinstallationen.**
