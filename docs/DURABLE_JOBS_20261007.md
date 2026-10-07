# Dauerhafte Jobs: fortsetzbar, verteilt, sommerzeitfest

Stand 7. Oktober 2026, Branch `claude/durable-jobs-core` (auf `claude/dreamy-gauss-nmaxhn`, `ae31057`). Umsetzung des Pakets „P1 E: Jobs/Betriebspläne“ aus Abschnitt 9 der Übergabe (`CLAUDE_HANDOFF_20261007.md`), Teil **Kern und Scheduler**. Müllpläne, ICS-Ausnahmen und Ablesepläne sind ausdrücklich nicht Teil dieser Runde.

## Ausgangslage (prozesslokaler Zustand)

| Stelle | Zustand vorher | Jetzt |
| --- | --- | --- |
| Serienaufgaben (`routers/tasks.py`) | `RLock` nur im eigenen Prozess; zwei Server-Prozesse konnten dieselbe Folgeaufgabe doppelt anlegen. Lief nur auf Knopfdruck. | Vorkommensbuch mit eindeutigem Schlüssel, zusätzlich täglicher Job. Die Sperre bleibt als Bremse innerhalb eines Prozesses. |
| Eskalationslauf (`routers/escalation.py`) | Nur auf Knopfdruck. Wiederholungen unterdrückt der `Notifier`. | Zusätzlich täglicher Job. |
| Scheduler (`app.py`) | Nur eine asyncio-Schleife für die Auth-Bereinigung (Daten im Speicher). | Zweite Schleife `services/jobs/scheduler.run_forever`. Die DB-Arbeit läuft per `asyncio.to_thread`, nie im Event-Loop. |
| `task_queue.py`, `/task-status` | Status im Speicher, 1 h Aufbewahrung | **Unverändert prozesslokal** (siehe „Bewusst offen“). |
| `concurrency.one_at_a_time`, Caches | Prozesslokale Sperren gegen gleichzeitige Rechenlast | Unverändert. Diese Sperren bremsen nur, sie sichern keine Korrektheit über Prozesse hinweg. |
| Auth-Sperrlisten, Registrierungs-Limiter | Im Speicher | Unverändert (zustandsbedingt prozesslokal). |

## Datenmodell (Migration `b8e3d5f7a2c4` nach `a7c2e9f4b1d3`)

- `job_runs`: ein Lauf je `idempotency_key` (eindeutig). Felder: `kind`, `scope` (nur `installation`, per CHECK), `status` (`queued`/`running`/`succeeded`/`failed`), `payload`, `checkpoint`, `progress`, `attempts`/`max_attempts`, `available_at` (Wartezeit bei Wiederholung), Lease (`lease_owner`, `lease_token`, `lease_expires_at`, `heartbeat_at`), `last_error`.
- `job_occurrences`: Vorkommensbuch. Der Primärschlüssel ist (`rule_key`, `rule_version`, `occurrence_key`) und dient als Duplikatschutz. `status` ist `created` oder `skipped`.
- SQLite ohne Alembic: `create_all` legt beide Tabellen an (`backend/db/job_models.py`, über `backend/db/__init__.py` registriert). Eine Wiederherstellung aus einer älteren Sicherung ergänzt sie (`ensure_job_schema`).
- Downgrade wird verweigert, solange Läufe `queued` oder `running` sind. Danach werden beide Tabellen entfernt, das Vorkommensbuch eingeschlossen.

## Ablauf

1. **Einplanen:** Jeder Prozess tickt alle `JOB_SCHEDULER_INTERVAL_SECONDS` (Standard 60 s). Für jeden periodischen Job wird der jüngste fällige Termin eingeplant, Schlüssel `art@lokales-datum`. Mehrere Worker erzeugen so genau einen Lauf je Termin. Verpasste Termine werden zusammengefasst: Nach einem Ausfall läuft nur der jüngste, und der Job holt fachlich selbst nach.
   - `tasks.recurring` täglich 05:00 Europe/Berlin
   - `escalation.run` täglich 06:15 Europe/Berlin
2. **Beanspruchen:** PostgreSQL nutzt `SELECT … FOR UPDATE SKIP LOCKED`, SQLite eine einzige bedingte `UPDATE`-Anweisung (ein Schreiber, Bedingung erneut geprüft). Jede Beanspruchung erhält ein zufälliges Fencing-Token. Abgelaufene Leases (Absturz, Neustart) sind wieder beanspruchbar. Ein Lauf, der `max_attempts` Mal unter seiner Lease gestorben ist, wird als `failed` aufgegeben.
3. **Abschnittsweise arbeiten:** Ein Handler bearbeitet einen begrenzten Abschnitt in `ctx.unit()`. Fachliche Schreibvorgänge, Vorkommensbuch und Checkpoint werden in **einer** Transaktion festgeschrieben, zusammen mit einer per Token abgesicherten Aktualisierung des Laufs, die zugleich die Lease verlängert (Heartbeat). Wurde der Lauf inzwischen übernommen, wird der ganze Abschnitt zurückgerollt (`LeaseLost`). Nach einem Neustart setzt der Lauf am letzten Checkpoint fort.
4. **Fehler:** Wiederholung mit Wartezeit (30 s, verdoppelt, höchstens 1 h), nach `max_attempts` (Standard 5) `failed` mit `last_error`.
5. **Beenden:** Beim Herunterfahren wird ein Stopp-Signal gesetzt. Der laufende Job hört nach seinem aktuellen Abschnitt auf, und die Lease läuft ab.

## Serienaufgaben nachholen

- Vorkommen sind Kalendertage in **Europe/Berlin**. Auch der Stichtag „heute“ (Job und Endpunkt ohne `as_of`) ist das Berliner Datum, nicht UTC und nicht die Serverzeit.
- **Regelversion** ist ein Hash aus normalisierter Regel und Ankerdatum. Eine geänderte Regel setzt nach dem letzten Vorkommen fort, das irgendeine frühere Version verarbeitet hat. Die Historie wird weder wiederholt noch umgeschrieben. Im Vorkommensbuch stehen beide Versionen.
- Abschnitte umfassen höchstens 500 Vorkommen (`recurring.CHUNK`). Auch der Besuch einer bereits erledigten Serie zählt mit, damit Abschnitte begrenzt bleiben. Innerhalb einer Serie ist das Vorkommensbuch selbst der Checkpoint.
- Modus `RECURRING_CATCH_UP`:
  - `latest` (Standard): Nur das jüngste fällige Vorkommen wird zur Aufgabe, und nur, wenn keine Folgeaufgabe der Serie offen ist. Ältere werden als `skipped` protokolliert. Eine lange ruhende Tagesserie erzeugt also keine Flut von Aufgaben.
  - `all`: Jedes fällige Vorkommen wird zur Aufgabe.
- Der Endpunkt `POST /tasks/generate-recurring` behält sein bisheriges Verhalten (eine Folgeaufgabe je Aufruf, offene Folgeaufgaben blockieren). Er schreibt jedoch in dasselbe Vorkommensbuch: Kein Prozess legt dasselbe Datum zweimal an. Ein vom Benutzer gelöschtes, bereits verarbeitetes Vorkommen wird **nicht** neu erzeugt.

## Sommerzeit

`DailyAt` rechnet mit `zoneinfo` (`fold=0`). Ein Termin existiert genau einmal je lokalem Tag:

- Frühjahr (29.03.2026): 02:30 gibt es nicht, der Termin läuft um 03:30 MESZ (01:30 UTC).
- Herbst (25.10.2026): 02:30 kommt zweimal vor. Es gilt der erste Durchgang (00:30 UTC). Die wiederholte Stunde erzeugt keinen zweiten Termin.

Der Schlüssel ist das lokale Datum, nie der UTC-Zeitpunkt. Für Windows ohne Zeitzonendatenbank ist `tzdata` als Abhängigkeit aufgenommen.

## Portfolio-Grenze

Jobs laufen als Installation, ohne Konto. `JobRunner` setzt dafür ausdrücklich `scope_context(None)`, auch wenn er aus einem Thread mit aktivem Anfragebereich aufgerufen wird. `job_runs` und `job_occurrences` stehen in `portfolio_scope.INTERNAL`: Sie werden nie an ein Portfolio gebunden und nie gefiltert. Es gibt keinen HTTP-Endpunkt, der sie einem eingeschränkten Konto zeigt. Der Speicher-Modus verwendet `MemoryJobStore` und `MemoryLedger` mit derselben Schnittstelle.

## Einstellungen

| Variable | Standard | Bedeutung |
| --- | --- | --- |
| `JOB_SCHEDULER_ENABLED` | `true` | Scheduler im Prozess starten (Tests: `false` in `conftest.py`) |
| `JOB_SCHEDULER_INTERVAL_SECONDS` | `60` | Abstand der Ticks |
| `RECURRING_CATCH_UP` | `latest` | `latest` oder `all` |

## Nachweise

`backend/tests/test_durable_jobs.py` läuft in den Modi SQL (SQLite-Datei, WAL) und Speicher:

- Neustart mitten im Lauf: zwei Abschnitte, dann „Absturz“. Die Lease hält einen zweiten Worker ab. Nach Ablauf übernimmt er und setzt am Checkpoint fort: 59 Aufgaben, keine doppelt, keine fehlend, 2 Versuche.
- Übernommene Lease: Der alte Worker kann nichts mehr festschreiben, sein Abschnitt wird zurückgerollt (SQL).
- Mehrere Worker: 4 Threads planen 40 Läufe gleichzeitig ein, 6 Worker arbeiten sie ab. Jeder Lauf läuft genau einmal, jedes der 50 gemeinsamen Vorkommen wird genau einmal verbucht. 8 Läufe für dieselbe Serie mit 4 Workern ergeben 364 eindeutige Aufgaben. Dasselbe gegen echtes PostgreSQL 16 (`IMMO_TEST_POSTGRES_ADMIN_URL`).
- 10.957 nachzuholende Vorkommen (1990–2020, täglich): Modus `all` mit Abschnitten zu 2.000, Absturz nach dem ersten Abschnitt, genau 10.957 Aufgaben. Modus `latest`: 10.957 Buchungen, eine Aufgabe.
- Sommerzeit in beiden Richtungen, Ticks alle 10 Minuten über vier Tage: je Tag und Job genau ein Lauf. Berliner Datum gegen UTC-Datum.
- Regelwechsel wöchentlich → monatlich: Historie bleibt, Fortsetzung danach, zwei Versionen im Buch.
- Endpunkt und Job teilen das Buch. Wiederholung mit Wartezeit, Aufgabe nach `max_attempts`, Installationsbereich innerhalb einer eingeschränkten Anfrage, Lifespan-Tick außerhalb des Event-Loops.
- `test_migrations.py`: Upgrade, Primärschlüssel als Duplikatschutz, CHECK auf `scope`, verweigerter Downgrade bei offenem Lauf, Downgrade und erneutes Upgrade.

## Bewusst offen

- `task_queue.py` und `/task-status` bleiben prozesslokal. Langlaufende Anfragen (Export, Import) sind noch nicht auf `job_runs` umgestellt, und hinter einem Load-Balancer findet ein zweiter Worker deren Status nicht.
- Der Eskalationsjob ist ein einzelner Abschnitt. Benachrichtigungen werden einzeln festgeschrieben, und Wiederholungen verhindert der `Notifier` über Typ, Bezug und Text, nicht das Vorkommensbuch.
- Im Speicher-Modus lassen sich fachliche Änderungen eines Abschnitts bei verlorener Lease nicht zurückrollen. Der Modus ist einprozessig, und das Buch verhindert Doppelungen.
- Die Lease-Zeiten beruhen auf den Uhren der Worker. Starke Uhrabweichung zwischen Rechnern verkürzt oder verlängert die Übernahmefrist effektiv.
- Fertige Läufe und Buchungen werden nicht automatisch bereinigt (Wachstum etwa 2 Läufe pro Tag plus 1 Buchung je Serienvorkommen).
- Es gibt keine Bedienoberfläche oder API für Läufe (Status, manueller Neustart eines `failed`-Laufs).
- Monats- und Jahresregeln behalten die bestehende Kappung auf den 28. Tag.
- Müllpläne, ICS-Ausnahmen und Ablesepläne mit Belegabschluss sollen auf diesem Kern aufbauen (eigene `rule_key`-Präfixe, Vorkommen als lokales Datum).
