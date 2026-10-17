# ImmoManager Pro – nachprüfbarer kombinierter Entwicklungsstand, 17.10.2026

**Nicht als Deployment-, Hauptbranch-Merge- oder Gesamt-Handover-Abnahme verwenden.**

## Baseline und Übernahme

Worktree: `work/pro-stage-acceptance-billing-20261017` auf
`pro/stage-acceptance-billing-20261017`.
Geprüfter Produktcodecommit: **`03d401c7b726a364a34c6536f8f6b2de8930270d`**.

Die gemeinsame Basis `57ab0a56` enthält verschlüsselte Connection-
und TEHA-Belege sowie die API-/Plugin-/S3- und Bank-/Finanz-/Steuer-/
Kommunikationsgrundlagen. Anschließend übernommen:

- `c5db7f39`: abgesicherte Altschema-Übernahme und persönlicher Eingang.
- `329cda33`: direkter SQL-Schreibdienst darf beim Start **nicht**
  die Anwendung importieren und dadurch einen explizit gebundenen
  SQL-Authstore ersetzen.
- `2421ad33`, `0dc5b546`, `6b2ecb2d`: geprüfte Frontend-
  Benachrichtigungs-/Threadgrenzen und gezielte asynchrone API-Orakel.
- `03d401c7`: Datenlücken zwischen ausgebauten und neu installierten
  Zählern verhindern die unbelegte Abrechnung. Überlappende Zähler
  erfordern eine ausdrückliche fachliche Prüfung.

Die Quelldateien des früheren Frontendzweigs wurden durch Git-Cherry-Picks
zusammengeführt, nicht durch Kopieren unklarer Artefakte. Der zentrale
Checkout `claude-review-20261013` blieb auf `04021da5` sauber.
Ports 8000/8765, reale Daten und externe Anbieter wurden nicht verändert.

## Tatsächlich bestandene Tests und deren Provenienz

| Code / Lauf | Prüfung | Resultat und Grenzen |
|---|---|---|
| `03d401c7`, `artifacts/pro-tests/complete-ui-03d401c7-df6c24543ce644bdb5a448437654ef00` | Frisches `npm ci --ignore-scripts`, ESLint, **gesamte** Vitestmatrix `--maxWorkers=2`, Vite-Build | **657/657** Tests in 104 Dateien bestanden; kein Testtimeout angehoben. Der erste Vergleichslauf mit unbegrenzten Workern und parallelen Python-Stressprüfungen hatte 649/657 mit acht 5-Sekunden-Timeouts. Dieselben fünf Testdateien bestanden bei begrenzter Parallelität mit 29/29. |
| `03d401c7`, `artifacts/pro-tests/integrated-billing-03d401c7-memory-951dd6e8a8a24e67ad2136a692236a1e` | Betriebskosten/Zählerwechsel mit Memory | **52/52**, kein Skip |
| `03d401c7`, `artifacts/pro-tests/integrated-billing-03d401c7-sql-9a2ac9d320744ec8a6b9f7f2b831f694` | Gleiche Fachorakel mit echtem SQLite | **52/52**, kein Skip |
| `03d401c7` | Gesamtes Backend `ruff check` und `mypy --platform linux` | beide erfolgreich, Mypy für **563 Quelldateien** |
| `329cda33`, `artifacts/pro-native/8fef5cc358b14eb2a5a71c9d90c07507` | Native PostgreSQL-Nachrichten-/Auth-/Request-Lock-Prüfung auf eigenem Testcluster | **17/17 ohne Skip**; Cluster danach beendet. Die Abrechnungskorrektur kam erst im nachfolgenden Commit hinzu, daher diesen PG-Lauf **nicht** als Ganzsystemtest von `03d401c7` ausgeben. |
| `329cda33`-Implementierung (vor dem Commit auf demselben Code mit getrennten SHA-Manifests), `artifacts/pro-tests/message-auth-request-release-{memory,sql}-...` im Worktree `pro-stage-full-matrix-20261016` | Auth-Revocation, Nachricht/Archiv-Wiederholung, Request-Read-Release und Dokumentversionen | **je 71 bestanden, 4 testbedingte Skips** mit Memory/SQLite |
| `329cda33`, `artifacts/pro-tests/complete-backend-329cda33-memory-dadc824d02694ff79054f40d13649041` | **gesamte** Backendmatrix einschließlich Coverage | **Beim Erstellen dieser Datei noch in Arbeit. Nicht als bestanden angeben.** Historische volle Matrix hatte 54 Fehler. |

Die Vitest-Konfiguration wurde nicht zum globalen Überschreiben von
Testzeitlimits oder zum Ignorieren eines Fehlers verändert. Das Backend-
Produktionsmodul importiert den Request-Read-Releaser nur dann, wenn die
Anwendungsabhängigkeiten ohnehin geladen sind. Bei echten HTTP-Routen
bleibt der kontrollierte Release-Pfad aktiv; direkte transaktionale
SQL-Dienste initialisieren nicht heimlich eine andere Authdatenbank.

## Was weiterhin ausdrücklich fehlt

1. Alle übrigen Handoverpakete in einem **einzigen** vollständig
   linearisierten Migrations- und Restorestand, einschließlich
   der bisher nicht bearbeiteten Verkauf/Eigentumsübergabe-,
   Fachplan-, Mieterportal- und Betriebsmodule.
2. Der gesonderte Channel-Checkpoint `2da46904` bleibt wegen eines
   Sicherheitsblocks beim gemeinsamen Alembic-Merge **nicht** in
   diesem getesteten Integrationsstand. Dies wurde nicht umgangen.
3. Ein einziger endgültiger Vollbackup-/Restore-Lauf, der
   sämtliche privaten Originale, Pluginpakete, Rollen/Grants und
   Anbieterversuche des späteren Gesamtsystems enthält.
4. Herstellerseitige **echte** Aktenwerk-, IS24-/OpenImmo-, TEHA-,
   FinTS-, WISO-/DATEV-, WhatsApp-/SMTP-, Post- und S3-/MinIO-
   Gegenstellenbelege. Offline-Mocks oder Protokolltests sind
   ausdrücklich kein Versand-/Import-/Zahlungsnachweis.
5. Große Gesamtbestände/Last- und Speicherprofile über alle
   Domänen, vollständige native PostgreSQL-/Browsertests und
   Github-CI **auf dem endgültigen, kombinierten Codecommit**.

Der Entwicklungszweig kann getrennt auf GitHub eingesehen werden.
**Keine Änderungen an den Anwenderinstallationen und keine Releasefreigabe.**
