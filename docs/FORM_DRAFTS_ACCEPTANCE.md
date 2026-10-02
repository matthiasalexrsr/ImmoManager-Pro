# Persönliche Formularentwürfe: vollständige API und PostgreSQL-Abnahme

Die zusätzlichen G40-Prüfungen ergänzen `test_form_drafts.py` und
`test_form_draft_migration.py`. Die bestehenden Tests bleiben erhalten.
`test_form_drafts_http.py` verwendet die tatsächliche `build_api_v1()`-Routenliste
mit DBSession-, Concurrency-, PortfolioScope- und RBAC-Middleware sowie wirklichem
Login. Die SQL-Installation entsteht durch die vollständige Alembic-Kette;
`create_all()` oder nachträgliche Kompatibilitäts-Hooks verdecken keine Lücken.

Diese Abnahme prüft:

- Ein ursprünglicher Bearbeitungsstand mit Mikrosekunden bleibt im privaten
  Entwurf erhalten. Auch ein neuer GET und eine aktuelle Liste ersetzen ihn
  nicht. Nach einer Änderung in einer anderen angemeldeten Sitzung schlägt ein
  Business-PATCH mit diesem ursprünglichen If-Match mit 412 fehl. Erst eine
  ausdrückliche Übernahme der aktuellen Revision erlaubt den nächsten Write.
- Zwei zugriffsberechtigte Benutzer haben unterschiedliche private Entwürfe
  für dieselbe Immobilie. Ein fremdes `owner_id` öffnet weder GET, PUT noch
  DELETE; auch Eigentümer können diese privaten Werte nicht über diese API
  lesen. Die genaue Own-Route-Ausnahme öffnet keine Benutzerverwaltung.
- Aktuelle Portfolio-, Rollen- und Aktivierungsänderungen werden mit dem
  bestehenden Sitzungstoken erneut geprüft. Abgelehnte Zugriffe erreichen
  weder Verschlüsselung noch Entschlüsselung und verändern keinen Entwurf.

`test_form_drafts_postgres.py` benötigt ausdrücklich
`TEST_SERVER_DATABASE_URL` zu einem **wegwerfbaren PostgreSQL-Testdienst**.
Fehlt die Variable, werden diese Fälle sichtbar übersprungen. Eine andere
Datenbankart wird abgelehnt. Jeder Test erzeugt ein neues `immo_drafts_<UUID>`-
Schema, migriert es bis zum tatsächlichen Alembic-Head (bei Einführung x1),
prüft die Versionszeile und den Entwurfsindex und entfernt nur sein eigenes
Schema nach dem Test. Zwei getrennte Engines und verschiedene
`pg_backend_pid()` belegen unabhängige SQL-Verbindungen.

Die PostgreSQL-Fälle ergänzen atomare Erstanlage und CAS-Änderung unter
gleichzeitigen Tab-Writes: genau ein Erfolg und ein `409 DRAFT_CONFLICT`.
Andere Entwurfsidentitäten bleiben speicherbar. Sie prüfen außerdem den
vollständigen Mikrosekunden-/Business-Konfliktfluss, unabhängig entzogene
Rechte trotz eines vorher geladenen ORM-Datensatzes, nachträglich verschobene
Immobilien und tatsächlich verschlüsselte PostgreSQL-Zeilen. Ein in die
Entwurfsidentität eines anderen Benutzers kopierter Ciphertext liefert einen
sicheren 503 und wird bei erneutem Speichern nicht überschrieben.

Ein zusätzlicher PostgreSQL-Fall prüft den tatsächlichen `clear_all()`-Einstieg
gegen einen bereits begonnenen Autosave. `pg_blocking_pids()` muss nachweisen,
dass die Wartungsverbindung auf die laufende Writer-Verbindung wartet, bevor
der Erhaltungsguard passiert. Nach dem Autosave-Commit wird das Zurücksetzen
abgelehnt; Ciphertext und Immobilien bleiben erhalten. Voraussetzung ist die
integrierte Management-/Tabellensperre aus dem Recovery-Guard-Paket a8f9f1e.

Für den CI-PostgreSQL-Schritt ist der **ganze neue Dateiname** aufzunehmen,
anstatt nur den älteren einzelnen PostgreSQL-Test aus der Core-Datei auszuwählen:

```sh
python -m pytest backend/tests/test_form_drafts_postgres.py -q --tb=short
```

Der normale Testlauf erfasst alle neuen Memory-/SQLite-HTTP-Fälle automatisch.
Eine fokussierte gemeinsame Abnahme lautet:

```sh
python -m pytest backend/tests/test_form_drafts.py \
  backend/tests/test_form_draft_migration.py \
  backend/tests/test_form_drafts_http.py \
  backend/tests/test_form_drafts_postgres.py -q --tb=short
```

`TEST_STORE_BACKEND=sql`, `SQLITE_PERSISTENT_STORE=true` und
`ALLOW_INMEMORY_FALLBACK=false` wählen den tatsächlichen SQL-Prozessmodus.
Ohne `DATABASE_URL` erstellt die bestehende Testkonfiguration hierfür ihre
eigene temporäre SQLite-Datenbank. Ein lokaler grüner SQLite-Lauf bestätigt
keinen PostgreSQL-Lauf; dessen Ergebnis muss separat aus dem konfigurierten
Testdienst/CI gemeldet werden.
# Explicit save during background storage

The Save action remains available while a background draft write is in flight.
The explicit action waits for that real response, uses its returned draft
revision to persist the submission marker, and only then invokes the business
write. This prevents a short disabled-button interval from swallowing a mouse
click. Loading, unresolved prior work, conflicts and uncertain business outcomes
continue to require review before a business write.

The unit regression holds the autosave response while changing values and
clicking Save. The native browser regression holds only a real SQLite autosave
response at 320 px, asserts no early business write, and checks exactly one
persisted write plus draft cleanup. It runs with the preceding two-editor CAS
suite to retain the shared-server acceptance scenario.
