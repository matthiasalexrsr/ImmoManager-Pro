# Vertragsarbeitsplatz: begrenzte, autorisierte Serverseiten

Basis: Root-Union `37dcc66`. Dieses Paket verändert ausschließlich neue
Backenddateien und diese Übergabe. `Contracts.jsx`, bestehende CRUD-/Lifecycle-
APIs, Startup, Settings, Datenbanken und Preview bleiben unverändert.

## Problem und Schnittstelle

`frontend/src/pages/Contracts.jsx` lädt Verträge und Referenzlisten über die
bisherigen ersten Seiten und filtert lokal. Ein vorhandener Vertrag oder dessen
Anzeigenamen nach diesen Seiten kann dadurch im Arbeitsplatz fehlen. Der
bestehende `services/contract_list.py` behebt bereits den 10.000-vor-Datumsfilter-
Fehler der Legacy-Liste; er ersetzt noch keinen vollständigen Arbeitsplatz.

Neuer, ausdrücklich lesender Endpunkt: `GET /api/v1/contracts/workspace/page`.
Nur mit normaler Anmeldung und dem jeweils aktuellen Portfoliozugriff.

| Parameter | Bedeutung |
| --- | --- |
| `search` | Enthält-Suche in Vertragsnummer, Immobilienname, Einheitslabel und Mietername; Python-Unicode-`casefold`, keine Interpretation von `%`, `_` oder SQL |
| `property_id`, `unit_id`, `tenant_id` | Exakte vorhandene IDs; keine neue Längen-/ASCII-Grenze für Bestands-IDs |
| `status` | `active`, `terminated`, `expired`, `draft` |
| `date_from` | Vertragsbeginn `>=` Datum, ISO `YYYY-MM-DD` |
| `date_to` | Vertragsende `<=` Datum; offene Enden ausgeschlossen, wie in der bestehenden API |
| `view` | `all` (Standard), `ending_soon` (aktiv; Ende nach Bezugsdatum und bis einschließlich +90 Tage), `no_deposit` (Betrag NULL oder 0) |
| `sort_by` | `contract_number` (Standard), `start_date`, `end_date`, `status`, `property_name`, `unit_label`, `tenant_name`, `deposit_amount` |
| `sort_order` | `asc` (Standard), `desc` |
| `page_size` | Positive technische Übertragungsgröße, Standard 100, bis zum konfigurierten Seitenbudget |
| `cursor` | Unverändert aus `next_cursor`; alle anderen Parameter müssen gleich bleiben |

Antwort: `items`, `next_cursor` (oder NULL), `has_more`, `reference_date`.
Jedes Item enthält den bisherigen vollständigen `Contract` und zusätzlich
`property_name`, `unit_label`, `tenant_name`, `unit_cold_rent`, `edit_etag`.
Die vier Kontextwerte können NULL sein. Es werden keine vollständigen
Mieter-/Immobilien-/Einheitssammlungen, Mailadressen oder Telefonnummern
angehängt. `unit_cold_rent` ist die aktuelle Einheitsangabe und **kein Nachweis
der wirksamen historischen Mietforderung/G08-Preisversion**.

`edit_etag` ist die bestehende starke `concurrency.etag("contracts", id,
updated_at)` mit ursprünglicher UTC-Mikrosekundenrevision. Der Editor übernimmt
diesen Wert unverändert in sein normales `If-Match`; ein nachträgliches
Listen-Refresh darf die ursprüngliche Bearbeitungsrevision nicht überschreiben.

Kein Gesamt-COUNT und keine behaupteten vollständigen Bestandskennzahlen.
Eine spätere UI muss Suche/Filter/Sortierung an den Server senden und über
`next_cursor` weiterblättern. Anzeigenamen stammen aus dem Item, nicht aus den
ersten 100 Referenzoptionen. Anlage-/Änderungsoptionen brauchen weiterhin
ihren eigenen autorisierten Lookup; diese Antwort ist keine Gesamtliste davon.

## Grenzen und Sicherheit

SQL wendet Filter und frische explizite Vertrags-/Parent-Scope-Prädikate vor
`LIMIT page_size+1` an. Anzeigenamen entstehen nur aus den genau gebundenen
autorisierten Parents; eine fremde/falsch gebundene Einheit erweitert die
sichtbare Vertragsmenge nicht. Die Abfrage verwendet Core-Spalten und
`no_autoflush`, keine alten ORM-Identity-Cache-Werte. Die Memory-Referenz hält
den bereits vorhandenen reentranten Fachschreiblock durch Auswahl,
Parent-/Scopeprüfung und begrenztes `nsmallest`.

Sortierung ist in allen Speichern NULL-last, bei Text UTF-8/byteweise
(`BINARY`/`C`), mit gleichgerichteter ID als eindeutigem Tie-Breaker. Jede Seite
ist eine kohärente aktuelle Leseabfrage; die Seitenfolge ist kein eingefrorener
Export. Neue Einträge vor dem Cursor erscheinen beim Neu-Laden; spätere
Einträge können in Folgeseiten auftauchen. Änderungen können Einträge bewegen.

Version-1-HMAC-Cursor bindet genaue Query, Sortierung, Seitengröße, Actor,
Rolle, Grants und das erste UTC-Bezugsdatum. `ending_soon` wandert beim
Seitenwechsel über Mitternacht nicht. Laufzeit pro Cursor: eine Stunde;
weiterblättern erzeugt den nächsten Cursor. Manipulation, Ablauf und geänderte
Filter liefern behebbare HTTP 400 mit `error.code` sowie
`details[0].clear_code`/`recovery="restart_page"`; kein automatisches
Weiterblättern mit falschen Filtern. Frischer Rollen-/Grantentzug innerhalb
einer Anfrage liefert 403. Antwortheader: `Cache-Control: private, no-store`,
`Vary: Authorization`.

Unicode-Suche ist exakt Python-`casefold`, ohne Akzententfernung oder
Kompositionsnormalisierung: Ä/ä, Ö/ö, ß/SS/ẞ, Endsigma und Ligaturen verhalten
sich in Memory, SQLite und PostgreSQL gleich. SQLite registriert bei einer
Suchabfrage die reine eigene `immo_contract_casefold`-Funktion auf der
ausgeliehenen Connection. Kein Schließen/Commit, kein SQL/DDL, kein Override
von `lower`, kein globaler Datenumbau. PostgreSQL faltet per `translate` und
iterativ erzeugtem `replace` mit derselben gebundenen Unicode-Mappingtabelle,
unabhängig von DB-Locale/ILIKE. Die enthaltene Suche darf autorisierte Daten
scannen; eine Indexbeschleunigung dieser beliebigen Teilstrings wird nicht
behauptet. DTOs/übertragene Referenzdaten bleiben begrenzt. PostgreSQL-
Ausführung muss der echte CI-Gate mit UTF-8-Datenbank belegen.

Es gibt **keine Gesamtbestands-/Jahres-/Namens-/Vertragsnummerngrenze**.
Seiten- und Querybudgets dienen der einzelnen Anfrage; sie sind konfigurierbar,
und es gibt keine zusätzliche willkürliche 5000-Obergrenze. Bei zu langem
Suchtext meldet HTTP 422 das konfigurierte Budget und die Möglichkeit eines
kürzeren Teilstrings; gespeicherte Werte werden niemals abgeschnitten.

## Notwendige Root-Hooks

1. In `backend/routing.py` neues `contract_workspace` importieren und
   `api_v1.include_router(contract_workspace.router, dependencies=_auth_dep)`
   **vor** `contracts.router` registrieren. Existierende Lifecycle-Routen
   bewahren. Der neue Router setzt bewusst keine zweite parallele Authschicht.
2. In `backend/config.py` Settings ergänzen: `contract_workspace_page_max_size`
   Standard 500 und `contract_workspace_search_max_chars` Standard 200,
   jeweils Integer mit `gt=0`, **ohne** künstliche `le`-Obergrenze.
   Env: `CONTRACT_WORKSPACE_PAGE_MAX_SIZE`, `CONTRACT_WORKSPACE_SEARCH_MAX_CHARS`.
   Service/Query enthalten dieselben Defaults, solange Root-Hooks fehlen.
3. Vier neue Runtime-Module in den CI-Mypy-Gate aufnehmen: Service, Search,
   Types und Router. Ruff behandelt sie bereits bei normaler Backendprüfung.
4. `backend/tests/test_contract_workspace_postgres.py` in den echten PG-Gate
   mit `TEST_SERVER_DATABASE_URL` aufnehmen. Bestehendes isoliertes,
   tatsächlich Alembic-upgegradetes UUID-Schema-Fixture wird wiederverwendet.
   Keine Migration, Model-/Session-/Schema-Registrierung oder UDF-Startup-
   Änderung erforderlich.

Die HTTP-Regression bindet den neuen Router vorübergehend in das echte
`build_api_v1` ein, einschließlich Auth-, Scope-, Session- und CAS-Middleware.
Das ist ein Integrationstest und ersetzt den Root-Produktionshook nicht.

## Tatsächliche Abnahme

Synthetische Memory-/SQLite-Inventare mit mehr als 10.000 alten Verträgen und
über 100 Referenzen reproduzieren zuerst die bisher fehlende erste Seite.
Die neue API findet den späten Datums-/Texttreffer und alle richtigen Namen,
mit einer SQL-Abfrage und höchstens `page_size+1` DTO-Materialisierungen.
Es gibt keine langsamen 10.000 HTTP-Anlagen und keine echten Kundendaten.

Weitere Fälle: alle Sortierungen, NULL/ties und Unicode-/lange Legacy-IDs,
verdeckte Portfolios/kaputte Parentbindung, gelöschte Cursorgrenze und parallele
Anlage, Query-/Actor-/Grant-/Signaturbindung, expliziter Cursorablauf,
Mitternacht, konfiguriertes Budget 6000 ohne Produktdeckel, volle lange Namen
mit konfiguriertem Suchbudget, echter A/B-Memory-Schreiblock,
`no_autoflush` trotz offener Schreibobjekte und echte HTTP-Seiten-ETag →
erfolgreiches PATCH → veraltetes PATCH 412.

Die frühere native SQLite-`ilike`-Unicodevariante war bei „ÜBER Größe“ rot;
die regressionsgeschützte Faltung prüft jetzt sämtliche vier Suchfelder.
Der reine PG-Compiler-/Mappingtest beweist SQL-Bindung und denselben
Faltungsalgorithmus, **keine tatsächliche PostgreSQL-Ausführung**.

Lokale Befehle (separate Prozess-Storeflags, keine Mainänderung):

```powershell
python -m pytest backend/tests/test_contract_workspace.py `
  backend/tests/test_contract_workspace_search.py `
  backend/tests/test_contract_workspace_postgres.py `
  backend/tests/test_contract_date_filter.py `
  backend/tests/test_portfolio_access_http.py -q --tb=short
python -m mypy --follow-imports=silent backend/services/contract_workspace.py `
  backend/services/contract_workspace_search.py backend/services/contract_workspace_types.py `
  backend/routers/contract_workspace.py
```

Final: SQL-Prozess mit allen oben genannten Dateien **121 bestanden / 8
explizite Skips**, Exit 0; Memory-Prozess mit beiden neuen normalen Testdateien
**77 bestanden / 1 expliziter Skip**, Exit 0. Sieben SQL-Lauf-Skips sind die
dedizierten PG-Fälle, einer die Memory-Variante des SQL-no-autoflush-Gates.
Ruff für alle sieben Pythondateien und Mypy für alle vier Runtime-Module grün.
Enger unabhängiger lesender Peerreview ohne konkreten Blocker; keine fremde
Ausführung wird daraus abgeleitet. Der eigene Commit steht im Agent-Handoff.
Ohne dedizierten PostgreSQL-Server überspringt das PG-File ausdrücklich;
es wird kein lokaler PG-Erfolg behauptet.
