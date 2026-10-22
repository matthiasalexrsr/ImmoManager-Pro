# Aufbau und Erweiterung von ImmoManager Pro

Stand 14.10.2026 (Version 2.0.0). Dieses Dokument beschreibt, wie die Anwendung aufgebaut ist und wie man sie erweitert, ohne Bestehendes zu brechen. Es gilt vor allen älteren Plänen im Wurzelverzeichnis. Welche Dokumente aktuell sind, steht in [docs/README.md](README.md).

## Schichten

```
Browser (React/Vite, frontend/src)
  └─ /api/v1 (FastAPI, backend/routing.py)
       ├─ Abhängigkeiten je Anfrage: Anmeldung, Plausibilität + veraltete Stände (409), Portfoliobereich
       ├─ Router (backend/routers/*)          dünn: Anfrage prüfen, Dienst aufrufen, Fehler übersetzen
       ├─ Dienste (backend/services/*)        Abläufe über mehrere Datensätze, Transaktionen, Dateien
       ├─ Fachlogik (backend/domain/*)        reine Berechnung ohne Speicher (Miete, Abrechnung, Mahnung, Geld)
       └─ Speicher (Store)                    InMemoryStore (backend/storage.py) oder SQLAlchemyStore
                                              (backend/repositories/sql_store.py) mit derselben Schnittstelle
            └─ Datenbank: SQLite (Desktop) oder PostgreSQL; Schema nur über Alembic (backend/db/migrations)
```

Beide Speicher sind gleichwertig: Jeder Backend-Test läuft in CI mit `TEST_STORE_BACKEND=memory` und `=sql`, dazu kommt ein PostgreSQL-Lauf ohne übersprungene Tests.

**Datum und Zeit:** „Heute“ ist das Kalenderdatum der Installation in Europe/Berlin: `backend/domain/clock.local_today()`. Der Tag eines gespeicherten Zeitpunkts (`…_at`, in UTC) kommt aus `local_date()`. `date.today()`, `datetime.now().date()` und `<…>_at.date()` lässt `test_clock.py` nicht zu; vom Nutzer eingegebene Uhrzeiten wie `scheduled_at` sind davon ausgenommen.

## Wo liegt was

| Bereich | Ort | Hinweis |
| --- | --- | --- |
| Datenmodell (API) | `backend/models*.py` | Pydantic: `XCreate` (anlegen, auch für PUT und den zusammengeführten PATCH), `XPatch`, `X` (gelesen) |
| Datenmodell (DB) | `backend/db/orm_models.py`, `backend/db/*_models.py` | Spalten und Constraints; Trigger für unveränderliche Originale |
| Migrationen | `backend/db/migrations/versions` | eine Kette; jede Migration ist „guarded“ (siehe unten) |
| Rechte | `backend/permissions.py`, `frontend/src/utils/permissions.js` | Schreibbereiche je Rolle; die Oberfläche blendet aus, der Server entscheidet |
| Portfoliobereich | `backend/services/portfolio_scope.py` | eingeschränkte Konten sehen nur ihre Portfolios, auch in Summen und Berichten |
| Plausibilität | `backend/services/plausibility.py` | prüft Eingaben vor dem Speichern (400 mit deutschem Satz) |
| Veraltete Stände | `backend/services/record_revisions.py` | Formulare senden `updated_at`; wer über eine neuere Änderung speichert, bekommt 409 |
| Löschschutz | `backend/services/deletion_guard.py` | `_DEPENDENTS`: was an einem Datensatz hängt, verhindert das Löschen mit Begründung |
| Geld | `backend/domain/money.py` | Decimal, kaufmännisch auf Cent; nie mit float rechnen |
| Mietkonto | `backend/services/rent_ledger.py`, `payment_allocations.py` | Forderungen und Zahlungen je Vertrag inkl. Übernahme aus dem Vorsystem |
| Hintergrundjobs | `backend/services/jobs` | dauerhaft, mit Lease; jeder Termin höchstens einmal |
| Schnittstellen | `backend/services/integrations` | Provider mit Konfigurationsfeldern, Aktionen und Protokoll; Geheimnisse verschlüsselt |
| Sicherung, Upgrade | `backend/ops.py`, `backend/upgrade.py`, `backend/services/full_backup.py` | siehe [Betrieb](OPERATIONS_BACKUP_SECRETS_20261008.md) |
| Seiten | `frontend/src/pages`, `frontend/src/features/<bereich>` | Navigation in `components/navigation.js`, Routen in `App.jsx` |
| Bausteine | `frontend/src/components` | `DataTable`, `FormModal`, `EntityLink`, `StatusBadge`, `SetupChecklist` … |
| Texte | `i18n/de-DE.json`, `en-US.json`, `es-ES.json` | ein Test verlangt jeden verwendeten Schlüssel in allen drei Sprachen |

## Rezepte

### Ein neues Feld an einer bestehenden Entität
1. **ORM-Spalte** in `backend/db/orm_models.py`, nullable oder mit Server-Default.
2. **Migration** in `backend/db/migrations/versions`. `down_revision` ist der bisherige Kopf (`alembic heads`). Vorbild: `981b2631e1e8_contract_ledger_takeover.py`.
   - Spalten nur anlegen, wenn sie fehlen: Datenbanken aus `create_all` haben sie schon.
   - Der Downgrade verweigert sich, solange Daten in den Spalten stehen.
   - Unter SQLite die Spalte mit `ALTER TABLE … DROP COLUMN` entfernen, nicht per Batch-Neuaufbau, sonst gehen Trigger verloren.
   - Indizes und Constraints gehören ebenso in die Migration wie Spalten. Neue Installationen bekommen ihr Schema aus `create_all`, bestehende aus den Migrationen. `backend/tests/test_schema_parity.py` vergleicht beide Wege (Tabellen, Spalten, Indizes, Fremdschlüssel, Trigger), unter PostgreSQL auch im PostgreSQL-Gate.
   - Die neue Revision zusätzlich in `ORM_ADOPTION_TARGETS` (`backend/db/migrations/env.py`) eintragen. Sonst scheitert das Upgrade alter Desktop-Datenbanken ohne Versionsstand (ein Test meldet es).
   - Ein neues Modul `backend/db/*_models.py` braucht seinen Import in `schema_state.initialise_empty`. Der Paritätstest baut die neue Installation in einem eigenen Prozess und bemerkt eine fehlende Tabelle.
3. **Pydantic-Felder** in `XCreate` und `XPatch` eintragen. Prüfungen über mehrere Felder gehören als `model_validator` in `XCreate`, denn PATCH prüft den zusammengeführten Datensatz.
4. Beide Stores übernehmen Felder automatisch, Snapshots (Export und Import) ebenfalls. Ein Roundtrip-Test sichert das ab.
5. **Formularfeld** in der Seite (`fields` der `FormModal`).
6. **Tests:**
   - fachlich in Memory und SQL;
   - Migration auf, Downgrade verweigert, Downgrade ohne Daten (`backend/tests/test_migrations.py`).

### Eine neue Liste oder Seite
1. **Router** in `backend/routers/<name>.py`, registriert in `backend/routing.py` mit `_auth_dep`.
2. **Schreibbereich** in `backend/permissions.py` (`WRITE_AREAS`) eintragen. Ohne Eintrag darf außer Eigentümer und Verwalter niemand schreiben.
3. **Store-Methoden** in beiden Stores (`list_x`, `get_x`, `create_x`, `update_x`, `delete_x`). Was am Datensatz hängt, kommt in `_DEPENDENTS`.
4. **Portfoliobereich:** Der Datensatz braucht einen Weg zum Portfolio (Fremdschlüssel). Sonst sieht ihn ein eingeschränktes Konto nicht, oder er rutscht durch. `test_portfolio_scope_http.py` vergleicht alle Lese-Endpunkte automatisch. Antworten müssen deshalb bei gleichen Daten gleich sein (keine frischen Zeitstempel).
5. **Seite** mit `DataTable` und `FormModal`, für einfache Listen reicht `CrudPage`. Dazu den Eintrag in `navigation.js`, die Route in `App.jsx` und die Texte in allen drei Sprachdateien.

### Eine neue Schnittstelle
- **Provider** in `backend/services/integrations/<name>_provider.py`, mit Manifest, Konfigurationsfeldern (`secret: True` für Zugangsdaten) und Aktionen. Optional `config_errors(config)` für eigene Prüfungen. Registrierung in `IntegrationManager.seed_defaults`. Vorbild: `aktenwerk_provider.py`.
- **Ausführung:** Eigene Abläufe laufen über `integration_manager.execute(...)`. Das prüft „aktiv und eingerichtet“, schreibt das Protokoll und gibt die entschlüsselte Konfiguration nur an die Arbeitsfunktion weiter.
- **Grundsatz:** Nichts wird automatisch nach außen gesendet. Jede Übergabe braucht einen ausdrücklichen Klick.

### Etwas, das Mietkonten berührt
- **Forderungen eines Vertrags:** `account_receivables(store, contract, bis)` (`services/rent_ledger.py`).
- **Zahlungen:** `contract_payments(...)` (`services/payment_allocations.py`).
- Beide berücksichtigen Übernahmetag, Saldo, Stornos und Kautionsanteile. Nie selbst ab Vertragsbeginn rechnen. Ausnahme sind Berichte über die Soll-Miete je Monat (`report_service.rent_due_by_month`).

### Ein Bericht, der Geld zusammenzählt
- **Eigentümerfilter:** `FinanceFilter.owner_contact_id` (auch `none` für den Teil ohne Eigentümer). Eine `OwnerView(store, flt)` je Berechnung anlegen und jeden Betrag damit nehmen:
  - `view.booking(b)` für eine Buchung;
  - `view.part(betrag, objekt, einheit, tag)` für einen Betrag eines Tages;
  - `view.period(...)` bzw. `view.contract_period(...)` für einen Betrag eines Zeitraums.
- Ohne Eigentümer liefert sie den ganzen Betrag. Nie selbst nach Anteilen rechnen; `services/ownership.py` regelt Vorrang (Einheit vor Objekt, Fläche), Wechsel und Cent-Rest.
- Ein Test sollte zeigen, dass die Eigentümer zusammen den Bericht ohne Filter ergeben (Vorbild: `test_owner_reports.py`).
- Eröffnungssalden über `flt.opening_accounts(store)`: mit Eigentümer die Konten mit diesem Kontoinhaber, mit `none` die ohne.
- Eine eingefrorene Quelle (Brief, Export) nimmt die Eigentümer nur auf, wenn welche erfasst sind (`ownership.timeline`), damit ältere Quellen und Prüfsummen gleich bleiben.

## Oberflächen-Bausteine

**`DataTable`**
- Spalten mit:
  - `link` / `subLink` (Verweis auf einen anderen Datensatz);
  - `sum: true` (Summenzeile);
  - `filterType`;
  - `render(value, row)`.
- Weitere Eigenschaften:
  - `bulkActions` (Mehrfachauswahl);
  - `onAdd(prefill)` (Neu, auch per Alt+N und `?neu=1`) mit `addLabel` und `hideAddButton`;
  - `settingsKey` (gemerkte Einstellungen);
  - `emptyText`.
- Leere Listen bieten von selbst den ersten Eintrag an.

**`FormModal`**
- Felder mit `required`, `default`, `options` (auch als Funktion der Werte), `section`, `hint`, `emptyHint`, `noToday`.
- Eine Pflichtauswahl mit genau einer Möglichkeit wird vorausgewählt.
- Fehlt die Voraussetzung ganz, verlinkt das Formular dorthin, wo man sie anlegt (`utils/prerequisites.js`).
- `repeatKeep` aktiviert „Speichern & weiteren“.

**Neu-Formular aus einer anderen Seite öffnen**
- `newEntryLink('/units', { property_id })` aus `utils/newEntry.js`.
- Die Zielseite übernimmt die Werte in ihrem `onAdd(prefill)`.

**Verweise**
- `EntityLink` / `entityHref` (`utils/entityLinks.js`).
- `PartyLink` öffnet die Parteiakte eines Mieters.

## Vor jedem Push

```bash
ruff check backend && python -m mypy backend
pytest backend/tests -q                                   # Memory
TEST_STORE_BACKEND=sql pytest backend/tests -q            # SQLite
cd frontend && npm run lint && npx vitest run && npm run build
```

CI führt das alles aus, dazu PostgreSQL ohne übersprungene Tests und einen E2E-Rauchtest. Größere Abläufe prüft `tools/xstress` (fünf simulierte Jahre gegen einen echten Server).

## Release und Update

Version in `pyproject.toml`, Release-Hinweise in `docs/RELEASE_NOTES.md`, danach den Tag `v<version>` pushen. Alles Weitere steht im README unter „Releases and updates“. Schemaänderungen erreichen eine Installation nur über den ausdrücklichen Upgrade-Schritt mit Vollbackup davor. Der Start lehnt eine veraltete Datenbank ab, statt sie still zu ändern.
