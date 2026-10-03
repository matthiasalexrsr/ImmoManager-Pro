# B1: vollständige Dashboardzahlen mit begrenzten Hinweisen

Vor-Code-Plan, 03.10.2026. Freigegebene Rootbasis `79ea761`, eigener komponierter Commit `c98e259`. Umsetzung ausschließlich `backend/services/dashboard_summary.py`, abgegrenztes `backend/routers/dashboard.py` und eigene synthetische Tests. Root/App/SharedAuthority/Settings/CI/Frontend, Suche/IBAN, Geldformeln, Forecast und Jobverträge bleiben Eigentum ihrer bisherigen Owner. Keine DDLrevision, Bestandskorrektur oder private Installation.

## Antwortvertrag

`GET /dashboard/stats` behält alle bisherigen flachen Integerfelder. Die Änderung an Benachrichtigungszahlen übernimmt ausdrücklich die bereits bestehende E-Zielrollenregel; das ist ein fachlicher Sichtbarkeitsfix, keine Änderung am E-Journal. Die bisherigen übrigen Statusdefinitionen werden nicht still umgedeutet.

Additiv:

- `as_of`: gemeinsamer ISO-Fachstichtag für Fälligkeit, Eskalation und 90-Tage-Vertragsfenster.
- `basis`: `dashboard-status-v1`; die vorhandenen Statuscounts sind keine Restbetrags-/Zahlungsberechnung.
- `occupancy`: `total`, `occupied`, `rented`, `vacant`, `reserved`, `other`, `basis=stored_unit_status`. `occupied` umfasst occupied **und** rented wie das vorhandene Unitinventory; `rented` ist die separat ausgewiesene Teilmenge. `occupied + vacant + reserved + other == total`. Die flache historische `occupied_units` bleibt occupied-only kompatibel.
- `billing_presence`: `periods_checked`, `blockers`, `warnings`, `basis=basic_presence_checks`, `complete_preflight=false`. Die alten `billing_preflight_*` bleiben kompatible Aliaswerte dieser ausdrücklich begrenzten Präsenzprüfung. Keine historische/Medien-/Leerstandsprüfung vortäuschen.
- `work_hints.tasks`, `.notifications`, `.expiring_contracts`: je `total`, `items`, `has_more`, `next_after`, `source_url`. Total zählt die vollständige sichtbare Menge unabhängig von Vorschauseite und Cursor. Jedes `items` ist auf die angeforderte Vorschaugröße begrenzt. Zugehörige Domainroute bleibt erreichbar; Folgeseiten sind über dieselbe Statsroute und ihren jeweiligen Cursorparameter erreichbar.

Die Items projizieren nur sichere Anzeige-/Routingfelder: Aufgaben id/title/due_date/priority, Meldungen id/title/severity/entity_type/entity_id, Verträge id/contract_number/end_date/days_remaining. Keine Beschreibung, Dokumentpayload, IBAN, Accountdetails, privaten Entwürfe oder Journalpayloads. IDs sind echte Ursprungsidentitäten, keine Listenindizes.

## Abfrage- und Cursorgrenzen

Query: optionaler `as_of`, `preview_limit` standardmäßig 5, Bereich 1–20; optionale `tasks_after`, `notifications_after`, `contracts_after` jeweils maximal 8.192 Zeichen. Das begrenzt einzelne Antworten, nicht den Bestand. Das Vertragsfenster beträgt für diesen Baustein ausdrücklich 90 Tage, einschließlich Stichtag und Fensterende. Ein unvertretbarer Datumsoverflow wird 422, nicht still gekürzt.

Die Grantliste wird über die bereits vorhandene kanonische `tenancy_workflow.digest`-Funktion vollständig gebunden. Damit wächst ein zurückgelieferter Cursor nicht über seine eigene akzeptierte Eingabelänge, wenn eine zulässige Benutzerzuweisung viele Portfolios umfasst. Das setzt keine maximale Anzahl von Grants und behauptet keine neue SQLkapazitätsmessung für große Grantlisten.

Hinweisordnung: Aufgaben nach Fälligkeit, Verträge nach Enddatum und Meldungen nach gespeichertem Erstellungszeitpunkt, jeweils aufsteigend; NULL zuletzt, danach byteweise ID aufsteigend. Alle Folgeseiten erreichen Gleichstände und NULLfälle. Cursor verwendet vorhandene Signatur-/Expiryfunktionen, bindet Version/Familie, Fachstichtag, Vorschaugröße, Ordnung und aktuelle Benutzer-/Rollen-/Portfolioidentität. Tokenrotation allein verändert diesen Vertrag nicht. Live-Seiten sind keine historisch eingefrorenen Bestände. Neue und manipulierte/fremde Cursor werden verständlich abgewiesen.

SQL: vorhandenen reinen Snapshothelfer aus `booking_export` verwenden (SQLite explizites lesendes BEGIN, PostgreSQL REPEATABLE READ/READ ONLY). Eine Aggregatabfrage liefert Counts/Statusverteilungen/Präsenzbefunde/Expiringtotal; höchstens drei zusätzliche SELECTs liefern je `preview_limit + 1` sichere Hinweiszeilen. Counts sind skalare serverseitige Aggregate, nie ORM-/Pydantic-Vollmaterialisierung. Alle verschachtelten Subjekt-/Elternquellen wenden explizit `scoped_clause(..., scope=captured)` an. Keine Session-Autoflushes, Commits oder Schreiblocks. Snapshot wird vor späterer HTTP-Veröffentlichungsprüfung geschlossen.

Fehlende Dokumente: scoped NOT EXISTS für Vertragszuordnung. Eskalationen: ein scoped EXISTS pro Fall über aktive Wartungsregeln statt vervielfachender Joins. Präsenz: dieselben bisherigen drei Befunde (überlappender aktiver Vertrag, Kostenpositionen, passender Schlüssel) und Nichtpositivkostenwarnung; eigene explizite Basis. Meldungen: eindeutiger vorhandener Dispatchbezug; kein/freier target_role, Eigentümer oder passender target_role ist sichtbar, genauso wie `notification_visible`. Keine N+1-Aufrufe.

Memory: dieselbe Query und Sichtbarkeit unter einem gemeinsamen vorhandenen `_memory_lock`; Counts vollständig, Hinweisheap höchstens `limit+1`. Hilfsrelationen speichern nur nötige IDs/primitive Datums-/Zählwerte, keine zusätzlichen vollständigen Modelle. Dokumentzuordnung, periodische Kostenpräsenz und aktive Vertragsintervalle erhalten geeignete Hilfsindizes, sodass der Baustein nicht jeden Bestand je Periode erneut durchsucht. Der Quellbestand wird weder abgeschrieben noch korrigiert.

Statisch festgestellte Integrationsgrenze: Bei Basis `79ea761` nehmen nicht alle `InMemoryStore.create_*`-Methoden den gemeinsamen Lock; unter anderem Aufgaben, Einheiten und Meldungen können parallel ohne diesen Lock angelegt werden. B1 verwendet den vorhandenen Lock und ändert Shared/Storage ausdrücklich nicht. Deshalb wird aus dem Leselock keine bereits bewiesene komplette Create/Write-Snapshotgarantie abgeleitet. Root wurde über die notwendige zentrale Komposition informiert; ein anderer lokaler Lock würde den Befund nicht lösen.

## Authority und Fehler

Vor und nach Lesen `current_scope`/`refresh_scope`; HTTPstatsrouter nutzt vorhandene `CheckedPublicationRoute` für tatsächliche Sitzungs-/Rollen-/Grantprüfung vor Headers. Fehlende HTTPbindung ist kein internes Installationsrecht. Direkte interne Tests/Domainaufrufe bleiben ausdrücklich intern. E-Zielrollen gelten zusätzlich zu Portfolio-/Elternsichtbarkeit. Private Cursor und Such-/Journalwerte werden nicht protokolliert.

Native SQLfehler propagieren als Fehler; keine catch-and-zero- oder Fehler-als-leer-Logik. Leere erfolgreiche Mengen liefern Nullcounts. Pending ORMänderungen werden nicht geflusht. Die Snapshotbasis wird nicht als Garantie über mehrere HTTPrequests oder mehrere bestehende Finanzreports dargestellt.

## Vorabnachweis und koordiniertes Gate

Zuerst eigene Tests schreiben. Die tatsächliche Negativbaseline führt die exakte unveränderte Dashboardquelle aus `79ea761` gegen dieselben synthetischen Memory/SQLitefixtures aus: rollenfremde Benachrichtigung erhöht derzeit den Zähler; strukturierte Belegung/fortsetzbare begrenzte Hinweise fehlen; vollständige Listenmaterialisierung findet statt. Keine bloße fehlende Importdatei als Produktnegativprobe anerkennen. Historische Quelldatei wird aus Git exakt entnommen, in Tests unter eigener Modulidentität geladen und an den echten isolierten Store gebunden; kein Rootcheckout verändert.

Dann Produktquelle und zielgerichtete native Fälle:

1. Memory/SQLite: vollständige Counts und unabhängige Erwartungswerte bei 101/1.001/10.001, späte Sonderzustände/fehlendes Dokument, Eskalationsdeduplikation, scoped Zielrollen, begrenzte Hinweise und Gleichstand-/NULL-Keysets.
2. Memory/SQLite: `list_all`/`list_*`-Tripwires, tatsächlich beobachtete SQLprojekte/LIMIT/Queryzahl, kein Flush/DDL bei pending Objekt/native Authorizer, native Sourcefehler bleibt Fehler.
3. Tatsächliches HTTP: Benutzerbindung, falscher/abgelaufener/fremder Cursor; Rechte-/Aktivierungs-/Sessionentzug nach Summary vor Veröffentlichung für selected und all-Portfolio. Vorhandene zentrale Fence unverändert verwenden.
4. PostgreSQL: dedizierte UUIDschemas, vollständige große Zähler/Keysets und echte SQLbenutzer-/Sitzungs-/Rechteprüfung, keine Skips als Nachweis. Quelle freeze; tatsächliche NodeIDs und Budget vorher an Root.

Keine schweren Tests während Root/Domain/UI-Slots. Negativbaseline/kurzer erster Gate, anschließende eigentliche Memory/SQLitefälle und echte PGfälle werden seriell abgestimmt. Browser und Gesamtrelease bleiben Root/UI-Abnahme; kein neues B- oder A–L-grün aus diesem Backendbaustein. Großbestand 100.000/1 Mio. bleibt gesonderte spätere Messung.
