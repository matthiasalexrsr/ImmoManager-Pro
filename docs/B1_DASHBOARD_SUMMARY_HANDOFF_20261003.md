# B1 Dashboard: Quellenübergabe und tatsächlicher Nachweis

Basis: freigegebenes Root `79ea761`, eigener Merge `c98e259`, Vor-Code-Vertrag `c924cf1`. Dieses Paket besitzt ausschließlich die Dashboard-Statsquelle, ihren Router, synthetische Tests und diese Dokumente. Kein Schemahead, keine DDLrevision, private Installation oder gemeinsame Authority-/App-/Settings-/Frontendquelle wurde geändert.

## API für die zentrale Integration

`backend.services.dashboard_summary.DashboardQuery` validiert `as_of`, `preview_limit` (5, Bereich 1–20) sowie die drei getrennten Cursorparameter `tasks_after`, `notifications_after`, `contracts_after`. `dashboard_summary(store, query)` liefert alle historischen flachen Integerfelder und die additive Struktur des [Vor-Code-Plans](B1_DASHBOARD_SUMMARY_IMPLEMENTATION_PLAN_20261003.md).

`GET /dashboard/stats` nimmt diese Queryparameter und verwendet die vorhandene `CheckedPublicationRoute`. Keine lokale Auth-/Token-/Signaturlösung. Cursor verwenden bestehende Workflowfunktionen und binden Benutzer, Rolle, Portfoliozugriff, Familie, Stichtag, Vorschaugröße und Ordnung; echte Tokenrotation innerhalb derselben gültigen Sitzungsfamilie verändert diese Bindung nicht.

SQL zählt die vollständige sichtbare Menge in einer Aggregatabfrage und projiziert drei getrennte Hinweisfamilien mit jeweils `LIMIT preview_limit + 1`. Der bestehende Snapshothelfer verwendet SQLite-BEGIN bzw. PostgreSQL REPEATABLE READ/READ ONLY. Weder Stocklisten noch autoflush, Commit oder Schemaänderung sind Teil dieser Quelle. Fehlende Dokumente, Wartungsregeln und Grundpräsenz verwenden EXISTS/NOT EXISTS ohne vervielfachende Joins. Benachrichtigungszahlen und Hinweise übernehmen die vorhandene E-Zielrollenregel mit einem eindeutigen Dispatchbezug.

Die vier Fachabfragen schließen die bestehenden zusätzlichen Benutzer-/Scope-/Sitzungsprüfungen nicht ein. Daraus wird keine pauschale Vier-Abfragen-Garantie für den gesamten authentifizierten HTTPrequest abgeleitet.

`occupancy.occupied` umfasst occupied und rented; `rented` ist eine separat ausgewiesene Teilmenge. Die bisherige flache `occupied_units` bleibt occupied-only. `billing_presence` benennt ausdrücklich `basic_presence_checks` und `complete_preflight=false`; sie ersetzt keine tatsächliche komplette Abrechnungsvorprüfung. Cash-, Forecast-, OwnerFinance- und Jobformeln wurden nicht kopiert oder geändert.

## Bestätigte Minigates

Interpreter ist die gemeinsame isolierte Projekt-Venv. Alle Aufrufe setzen ausschließlich synthetische Schlüssel, wählen Memory als globalen Testbackend und lassen `DATABASE_URL` für das eigene temporäre Conftest-Verzeichnis frei. Zusätzliche SQLitefixtures sind eigene temporäre Dateien. Ein eigener gestarteter Subprozess erhält jeweils einen festen Timeout; keine PID wird geraten oder ein fremder Prozess beendet.

1. Exakte historische Quelle `git show 79ea761:backend/routers/dashboard.py`, unter eigener Modulidentität mit denselben isolierten echten Stores ausgeführt: `test_counts_apply_the_existing_notification_target_role_rule[memory]` und `[sqlite]` scheiterten tatsächlich mit `assert 3 == 2`, **2 FAILED in 13,13 s**. Das ist der reproduzierte Ausgangsbefund, kein positiver Testlauf.
2. Dieselben beiden tatsächlichen Produktfälle: **2 PASS in 9,43 s**. Die Prüfung vergleicht außerdem die bestehende E-Meldungsliste und schließt ein tatsächlich fremdes Portfolio aus.
3. `test_full_counts_and_occupancy_reach_late_rows`, Memory/SQLite jeweils mit 101, 1.001 und 10.001 zusätzlichen Einheiten: **6 PASS in 16,92 s**, unabhängige Zustandsverteilung und vollständige Count-/Belegungssumme.

Die jeweiligen Testselektionen:

```text
python -m pytest backend/tests/test_dashboard_summary.py::test_counts_apply_the_existing_notification_target_role_rule -q --no-cov --tb=short
python -m pytest backend/tests/test_dashboard_summary.py::test_full_counts_and_occupancy_reach_late_rows -q --no-cov --tb=short
```

Nur die erste Selektion wird für die Negativbaseline mit `B1_DASHBOARD_BASELINE=79ea761` wiederholt. Anschließend ist dieses Merkmal entfernt. Harte Prozessbudgets 30/30/45 s wurden eingehalten, keine Skips. Quelle und Fixtures blieben während jedes Laufes unverändert.

## Noch ausstehende Abnahme

Die getrennt vereinbarten nächsten Läufe umfassen 14 übrige Servicefälle plus 18 echte HTTPcredentials-Fälle (120 s), anschließend 7 PostgreSQLfälle (90 s). Diese Abschnitte werden erst nach tatsächlichem Ende um Ergebnisse ergänzt. Lint und Typprüfung der fünf eigenen Pythondateien sind grün; das ersetzt keine Laufzeitabnahme.

Die unveränderten ersten acht Counterfälle werden nicht nochmals selektiert:

```text
python -m pytest
  backend/tests/test_dashboard_summary.py::test_task_keysets_visit_all_equal_and_null_dates_with_full_total
  backend/tests/test_dashboard_summary.py::test_contract_window_and_notification_keysets_cover_boundaries_and_equal_times
  backend/tests/test_dashboard_summary.py::test_counts_and_hints_do_not_materialize_stock_or_autoflush
  backend/tests/test_dashboard_summary.py::test_summary_cursor_and_fresh_scope_cannot_be_replayed
  backend/tests/test_dashboard_summary.py::test_native_source_error_is_not_zero_or_empty
  backend/tests/test_dashboard_summary.py::test_native_sqlite_refuses_schema_and_data_writes_during_summary
  backend/tests/test_dashboard_summary.py::test_presence_stays_explicit_and_escalations_are_not_multiplied
  backend/tests/test_dashboard_summary.py::test_earliest_as_of_does_not_overflow_the_memory_rule_cutoff
  backend/tests/test_dashboard_summary_authority.py
  -q --no-cov --tb=short

python -m pytest backend/tests/test_dashboard_summary_postgres.py -q --no-cov --tb=short
```

Der PostgreSQLlauf erhält ausdrücklich die freigegebene dedizierte Testserver-URL; jede Fixture erzeugt und entfernt ausschließlich ihr eigenes UUIDschema. Der kombinierte PG-Keysetfall prüft alle drei Hinweisfamilien, einschließlich Datumsgleichständen, NULL-Aufgaben und den beiden inklusiven Vertragsfenstergrenzen.

## Präzise Grenzen

Memory liest unter dem bestehenden gemeinsamen `payments._memory_lock`. Bei Basis `79ea761` nehmen jedoch nicht alle tatsächlichen `InMemoryStore.create_*`-Methoden diesen Lock, beispielsweise `create_task`, `create_unit`, `create_property` und `create_notification`. Einige Updates sind durch `_version_mutation → memory_write → tenant_privacy._memory_privacy_lock` geschützt. Dieses Paket verändert Shared/Storage nicht. Vollständige Kohärenz gegen alle parallelen Create-/Write-Aufrufe ist damit ausdrücklich noch nicht bewiesen; Root wurde über die notwendige zentrale Komposition informiert.

Die Antwort begrenzt Hintzeilen und projizierte Felder; das ist keine feste Byteobergrenze für vorhandene freie Titeltexte. Live-Keysets sind keine über mehrere Requests eingefrorenen historischen Bestände. Zähler und Vorschau benötigen innerhalb eines SQLrequests denselben Read-Snapshot; andere Finanzreports sind nicht Teil dieser Snapshotgarantie.

Browser, Dashboardfrontend, Gesamtsuche/IBAN, 100.000-/1-Mio.-Messungen, zehn gleichzeitige Nutzer und die gesamte B-/A–L-Abnahme bleiben eigene offene Pakete. Keine entsprechende Freigabe wird aus diesen Backendnachweisen abgeleitet.
