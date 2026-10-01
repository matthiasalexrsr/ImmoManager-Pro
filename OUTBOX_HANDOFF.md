# G26: dauerhafter manueller SMTP-Ausgang

Der neue Bildschirm `/outbox` speichert einen ausdrücklich geprüften Einzel-Empfänger, Absender, Betreff und vollständigen Nachrichtentext. Speichern sendet nichts. Ein gesonderter bestätigter Versand reserviert genau einen Versuch. Es gibt keinen Hintergrundworker, kein automatisches Recovery und keine automatische Wiederholung. Die vorhandenen SMTP-Konfigurations-/Testmail-Abläufe bleiben kompatibel.

## Gelieferte Integration und Umfang der Mieterauskunft

- `backend.db.outbox_models.OutboxMessageORM` ist vor `create_all` in `db/session.py` und im Alembic-Environment registriert; alle drei Tabellen gehören damit zu `Base.metadata`.
- `ensure_outbox_schema(connection)` ist im additiven Bootstrap aufgerufen. Der Helper erstellt fehlende Tabellen wiederholbar ohne historische Daten umzuschreiben. Produktiv Alembic `r1a2b3c4d5e6` verwenden, eindeutig auf `q1a2b3c4d5e6`.
- `backend.routers.outbox.router` ist unter `/api/v1` registriert. Der Router besitzt `/messages/outbox`; das bestehende capability-Mapping `messages → communication` gilt ohne neue Sonderberechtigung.
- Installation-weite Business-JSON-Teilrestores scheitern bei vorhandenen Outbox-Daten vor jeder Mutation durch die bestehende allgemeine Prüfung unexportierter Tabellen. Der SQL-`clear_all`-Guard verweigert nun auch den gewöhnlichen Reset mit 409, sobald Prüfstände, Ereignisse oder Befehle existieren. Die Regression erfasst SQL-DML: keine einzelne Änderung beginnt. Vollarchive bewahren alle drei registrierten Tabellen. Leere Journale blockieren bestehende Resetabläufe nicht.
- Persönliche Empfänger/Absender/Inhalte stehen im unveränderlichen `snapshot_json` und `wire`; `actor_id` ist vertrauenswürdiger Akteur, `reviewed_by` eine eingegebene Prüfungsreferenz. Alle Tabellen tragen direkte `portfolio_id`; Ereignis/Befehl referenziert zusätzlich `outbox_messages.id`. Keine FK auf Benutzer, damit dessen spätere Verwaltung den Beleg nicht löscht.
- `backend/tests/test_outbox_postgres.py` ist als eigener zusätzlicher Schritt im dedizierten PG-Job integriert. Die vorhandene Fixture verwendet ausschließlich ein neu erzeugtes UUID-Schema. Ohne explizite `TEST_SERVER_DATABASE_URL` werden zwei Gates sichtbar übersprungen.

Die Outbox besitzt keine ausdrückliche Mieter-/Vertrags-FK. Deshalb weist der integrierte Mieterauskunftsgraph alle drei Tabellen in `scope.not_covered` aus; Details stehen in `docs/TENANT_PRIVACY.md`. Eine gemeinsame oder später geänderte E-Mail-Adresse belegt keine eindeutige historische Zugehörigkeit. Automatisches Abgleichen von Empfängern oder Nachrichtentexten könnte Daten anderer Personen offenlegen und gehört nicht zum freigegebenen Auskunftsumfang. Persönliche Inhalte in Prüfständen, MIME, Ereignisbegründungen und Befehlen benötigen eine gesonderte autorisierte Prüfung. Die begrenzte Profil-Anonymisierung verändert diese Journale nicht und nennt sie als Ausschluss. Eine spätere ausdrückliche Mieterzuordnung benötigt ein eigenes Datenmodell; sie darf fehlende historische Beziehungen nicht erfinden. Portfolio- und Nachrichten-FKs sind zusätzlich `RESTRICT`.

Memory hat keinen Outbox-Sidecar, keinen SMTP-Worker und keinen eigenen Engine-Disposalhook. Der SQL-Pfad nutzt ausschließlich die vorhandene Anfrage-Session/deren Cleanup. Tatsächliche frische App-Prozesse prüfen den produktiven SQL-Start, Ersteinrichtung, registrierte HTTP-Routen, Prüfstandpersistenz beim erneuten App-Lifespan und vollständig freigegebene Poolverbindungen; der frische Memory-Prozess belegt 503. Die Tests konfigurieren ausschließlich private temporäre Verzeichnisse, synthetische Schlüssel und `.invalid`-Adressen, ohne geerbte Appkonfiguration oder Versand.

## Dauerhafte Bedeutung und Transaktionen

`outbox_messages` enthält eine unveränderliche JSON-Prüfung samt SHA256 und exakt vorbereitete MIME-Bytes samt SHA256, stabiler Message-ID, Date und MIME-Boundary. Netzwerkfehler und bewusste Wiederfreigaben verändern diese Bytes nicht. Ein Inhaltswechsel benötigt einen neuen geprüften Entwurf. Die Sender-Konfiguration wird beim Speichern ausdrücklich abgeglichen; geänderter Transport wird vor DATA erneut geprüft. Anmeldedaten bleiben ausschließlich in der vorhandenen privaten SMTP-Konfiguration und im flüchtigen Worker-Kontext.

`outbox_events` enthält append-only Ereignisse für jede Revision (zusätzliche Unique-Constraint Nachricht+Revision). `outbox_commands` enthält actor-gebundene Idempotenzreferenz, Befehlsinhalt, Ergebnis und ggf. Claimtoken. Identischer Replay erzeugt keinen neuen Transport; widersprüchliche Referenz 409, veraltete Revision 412. Ein paralleler Replay eines noch laufenden Versuchs kann den aktuellen `claimed`-Stand zurückgeben; dies ist kein Versand-Erfolgsbeleg.

Jeder Claim verwendet Revision-CAS, eindeutigen Token, Besitzer und eine Lease von 90 Sekunden. Bei Schreibfehlern oder Rechteentzug vor Commit wird die Transaktion zurückgerollt. Separate SQL-Sessions teilen die Datenbank-CAS und die Unique-Constraints, keinen Python-Mutex. Rechte werden vor Claim, vor Transport und im DATA-Checkpoint neu gelesen.

Der bestehende Spawn-Worker baut DNS/TLS/AUTH/MAIL/RCPT innerhalb seines Watchdogs auf und wartet vor DATA auf eine ausdrückliche Nachricht vom Elternprozess. Dieser persistiert zunächst `phase=data` samt Event, prüft nochmals Rechte und Transport-Konfiguration und commitet. Erst danach erhält das Kind GO. Ein Absturz zwischen Commit und GO bleibt konservativ unklar, obwohl unter Umständen kein DATA übertragen wurde.

Nach bereits autorisiertem Transport wird ausschließlich dessen exaktes Job-/Owner-/Claimtoken-/Revision-Ergebnis intern journalisiert, auch wenn die Rechte inzwischen entzogen wurden. Dieser schmale Abschluss darf keine neue Quelle, Empfängerabfrage, Reservierung oder Netzwerkentscheidung ausführen. Die HTTP-Antwort bleibt nach Entzug 403. Keine allgemeine privilegierte Benutzer-Worker-Schleife.

## Klärung und technische Grenzen

Lesen versendet und repariert nichts. Nach abgelaufener Lease führt nur ein bestätigter `/recover`-Befehl vor DATA nach `ready`, nach möglicher DATA-Annahme nach `unknown`. Ein `unknown`-Stand ist für weitere Sendebefehle gesperrt. Mit nichtleerer Begründung kann ein berechtigter Benutzer die Annahme/Fehlannahme dokumentieren oder einen neuen Versuch bewusst freigeben. Wiederfreigabe sendet ebenfalls noch nichts; anschließend ist ein weiterer gesonderter Sendebefehl nötig. Ein Doppelversand bleibt bei unbekannter Annahme möglich und wird vor der Entscheidung angezeigt.

`sent` bedeutet SMTP-Relay-Annahme oder dokumentierte menschliche Klärung, keine bestätigte Zustellung. Diese Unterscheidung entspricht [RFC 5321 §4.2.5 und §6.1](https://www.rfc-editor.org/rfc/rfc5321.html#section-4.2.5). Der getrennte Envelope/DATA-Ablauf verwendet die vorhandenen [smtplib Low-Level-Methoden](https://docs.python.org/3/library/smtplib.html#smtp-objects).

Transportbudgets sind die bestehenden technischen Grenzen: vollständige MIME-Nachricht höchstens 1 MiB, konfigurierbarer Gesamt-Watchdog 1–60 Sekunden, vier gleichzeitige Worker je Prozess. TLS-Zertifikatsprüfung bleibt aktiv; keine Klartextauthentifizierung. Einzelne konventionelle ASCII-Mailboxen; internationale Texte werden als MIME kodiert, keine SMTPUTF8-Envelopes. Im neuen Ablauf keine Anhänge oder Mehrfachempfänger. Es gibt keine Begrenzung der Journalgröße, Anzahl von Versuchen oder nutzbarer Portfoliojahre. Listen und Ereignisse werden über SQL-Seiten vollständig lesbar gemacht. Übersize ergibt 422 mit Anpassungs-/Aufteilhinweis; weder Kürzen noch unbekannter pauschaler Versandfehler.

Nach SMTP-Annahme und Ausfall des Ergebniscommits bleibt der dauerhafte DATA-Claim bestehen. Replay desselben Sendebefehls sendet nichts; nach Leaseablauf ist eine manuelle Klärung erforderlich. Ein restauriertes vollständiges Journal hat dieselben Regeln; keine aus einem Backup abgeleitete automatische Versandfreigabe.

## API

- `GET /messages/outbox/configuration`: nur öffentlicher Absender, aktiv/konfiguriert, Transportbudget. Keine Hosts oder Credentials.
- `GET /messages/outbox?portfolio_id=…&offset=…&limit=…` und `GET /{id}`: scoped Journal/Prüfstand.
- `POST /messages/outbox`: geprüften Stand mit `idempotency_key`, `portfolio_id`, `recipient`, `sender_address`, `sender_name`, `subject`, `body_text`, `reviewed_by`, `review_confirmed:true` speichern.
- `POST /{id}/send` und `/recover`: `idempotency_key`, `expected_revision`, `confirmed:true`.
- `POST /{id}/decision`: zusätzlich `action` = `retry|mark_sent|mark_failed|cancel` und nichtleere `note`; cancel nur bei ready, retry bei failed/unknown, Markierungen nur bei unknown.
- `GET /{id}/events?offset=…&limit=…`: dauerhaftes Versuchs-/Entscheidungsjournal mit UTC-Zeitstempeln.

Schreibrollen: Eigentümer, Verwalter, Buchhaltung und Techniker wie die vorhandene Kommunikationsberechtigung. Readonly liest und erhält auf Schreibbefehle 403. Der Memory-Backend darf keine vermeintlich dauerhafte Outbox anbieten: 503 vor jeder Reservierung.

## Verifikation

Die neuen Tests verwenden private synthetische SQLite-WAL-Dateien, separate Sessions, echten Spawn-Hardexit und tatsächliche ASGI-Verbindungsabbrüche. Die Transporttests verwenden ausschließlich synthetische TLS-Loopback-Server und unveränderte Zertifikatsprüfung; keine externen Mails. Die bestehenden SMTP- und Integrationsregressionen prüfen Kompatibilität zusätzlich. Frische echte Alembic-Kette, additiver Bootstrap und leerer Roundtrip sowie befüllter Downgrade-Schutz sind enthalten.

Frontend prüft DE/EN/ES, keine automatische Sendefolge, Vorschau ohne HTML-Ausführung, Bestätigung/Doppelklick, Idempotenzreferenz, Fehlerdetails, Erhalt von Entwurf/Begründung, Rechteentzug und erneute Prüfung bei Text-/Absenderänderung. Der erste Vollsuite-Lauf traf einen bestehenden 1001-Referenzen-Testtimeout unter paralleler Last; derselbe komplette Stand bestand 578/578 mit zwei Vitest-Workern ohne Produkt-/Fremdteständerung. Die letzte eigene UI-Ergänzung wird separat erneut geprüft. Integration/E2E und echte PostgreSQL-Ausführung bleiben Root-Releasegates; lokal ohne Service wird keine PG-Freigabe behauptet.

Der frühere Fehler beim Beginn einer berechtigten 403-Antwort ist durch den Root-Middlewarefix `751b77d` behoben. `test_real_scoped_http_revocation_after_data_keeps_factual_result_and_returns_403` besteht jetzt tatsächlich: unveränderter Ergebnisbeleg, genau ein Transport und HTTP 403 nach dem Entzug. Der abschließende gemeinsame Backendlauf bestand mit 93 Tests und zwei ausdrücklich übersprungenen PG-Gates, einschließlich sieben zusätzlicher Integrationsfälle für Start, Bootstrap, Reset und Memory sowie bestehender SMTP-/Integrations-/Batchregressionen. Der vollständige bestehende CI-Mypy-Aufruf besteht mit 44 Quelldateien; der Batch-Reset verwendet dafür konkret typisierte SQLAlchemy-Tabellen statt blanket ignores. Die 15 eigenen neuesten UI-Regressionsfälle sowie Ruff, Frontend-Lint und Build bestanden. Die CI-YAML wurde mit dem vorhandenen js-yaml-Parser geprüft. Ohne lokalen PostgreSQL-Service wird keine tatsächliche PG-Ausführung behauptet.
