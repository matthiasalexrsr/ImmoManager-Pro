# Paket B: tatsächliche Historienabnahme

## Ergebnis

Root-Source `609c77d`, Schema weiterhin K2. Die Historie verwendet vollständige
berechtigte SQL-Counts, begrenzte Cursorseiten, Unicode-Suche, exakte Fachfilter
und vollständigen CSV. Die Oberfläche zeigt echte gespeicherte Feldnamen und
Bearbeiterkennungen, vollständige alte/neue Werte und Änderungsgründe.
Benutzerzeitraum wird aus Ortszeit in UTC übertragen; historische naive
UTC-Werte werden ausdrücklich als UTC interpretiert und in Ortszeit angezeigt.
Mobile Einträge passen als Karten einschließlich offener langer Werte in die
Akte. Leerbestand, fehlende Angaben, Ladefehler und Rechteänderungen haben
unterschiedliche Zustände. Erneute Autoritätsprüfung und Abbruch alter Antworten
gelten für Öffnen, Fokus, Navigation, Aktualisieren und Export.

Vorcodeplan: `B_HISTORY_INVENTORY_PLAN_20261003.md`. Backendquellen `d3f5424`,
UTC-Bindkorrektur `d336b4a`, Oberfläche/Runner/CI `460f812`, tatsächliche
Mobilkorrekturen `3856469` und `609c77d`. Alle Gates benutzen eigene
synthetische Daten; keine private Datenbank, Vorschau oder Portalaktion.

## Tatsächlich ausgeführte Prüfungen

| Gate | Belegtes Ergebnis und Grenze |
| --- | --- |
| Memory/SQLite/SQL-HTTP | Erster Lauf 7 PASS/2 FAIL in32,71s, hard180: neue Vary-Assertion übersah legitimes zusätzliches Origin. Gezielt korrigierte Folge 5 PASS in18,31s, hard90, einschließlich beiden echten SQL-HTTP-Fällen, historischer SQLite-NULL-Zeit und UTC-Überläufen. 12 unterschiedliche positive Fälle komponiert, keine vollständige12er-Grünwiederholung. |
| PostgreSQL16.15 | Auf d3f5424 2 PASS/1 FAIL in34,50s, hard90: 10002er-Stock/CSV und Scope grün; Zeitintervalle zeigen echten UTC-Writerfehler. Danach echte Fehlerregression, tatsächlicher Repositorywriter unter Berlin/NewYork sowie SQLite/Memory-Zeitfälle: 5 PASS in19,23s, hard90. Kein Skip und keine Behauptung einer vollständig wiederholten PG-Suite. |
| Reiner Bindtyp | 8 PASS in0,57s, hard30; Offset/naiv/None, DDL-Kompilierung für SQLite/PG, UTC-Überlauf. Kompilierte DDL-Gleichheit ersetzt keine tatsächliche Schema-/Recovery-Gesamtabnahme. |
| UI-Verhalten | Nach Testablaufkorrektur und Export-Query-Abbruchschutz kompletter7er-Gate PASS in2,58s. Ladefehler/Retry, verspätete Antworten, Actor-/Grantwechsel, vollständige Details und Exportfilter. |
| Native Edge, 460f812 | Build725 und frische Migration bisK2 grün; 1 FAIL nach6,7s wegen mobilem gesamten Dokumentüberlauf. Export/Revoke noch nicht erreicht. Gesicherter Fehlerbeleg bleibt erhalten. |
| Native Edge, 3856469 | Genau derselbe Gesamtfall 1 PASS nach47,0s, Playwright48,4s. Tatsächliches 10002er-CSV, eindeutige IDs, Formelschutz, Cursorfolge, Suchpositionen101/1001/10001 und Rechteentzug. Layoutzusatzprüfung fand danach noch1080px breite mobile Karten hinter dem Scrollcontainer. |
| Native Edge, 609c77d | Genau derselbe Gesamtfall plus strenge tatsächliche Karten-/Detailgrenzen 1 PASS; Ausgabe1,1min Fall/1,2min Playwright, normalExit0. Kein harter Gesamtrunner-Zeitbeleg: Metadaten-/Start-/Fallbudgets sind getrennt. Ganze Dokumentbreiten320/360/1440; mobile Tabelle265/305px und offene Werte239/279px innerhalb der Akte. |

Backend-XMLs liegen unter `artifacts/B_HISTORY_SQLITE_MEMORY_HTTP_20261003.xml`,
`B_HISTORY_FOCUSED_FOLLOWUP_20261003.xml`, `B_HISTORY_PG_20261003.xml`,
`B_HISTORY_TIME_FOLLOWUP_20261003.xml`. Native Browserbelege sind getrennt unter
`artifacts/B_HISTORY_BROWSER_460f812_FAILED`, `...3856469_PASSED` und
`...609c77d_PASSED` gesichert. Vier Aufnahmen des ersten grünen Durchlaufs und
drei unskalierte echte Bildauszüge des abschließenden Durchlaufs wurden
tatsächlich angesehen. Keine Behauptung, alle Traceframes visuell geprüft zu
haben. Finales JSON belegt10002 eindeutige Originalkennungen und nach echtem
Grantentzug0 sichtbare Änderungen für denselben SQL-Benutzer. Die physische
mobile Tabelle und offene Wertedefinition werden zusätzlich gemessen.

Der eigene PostgreSQL-Server auf127.0.0.1:58112 wurde per tatsächlichem
pg_ctl-fast-Stop normal beendet; sein eigener Startprozess ist geschlossen.
Alle drei Browserrunner schließen ihre eigenen Testprozesse und temporären
Installationen normal in finally. Kein privater Dienst wurde beendet.

## Verbleibende Grenzen

- Neue Historienwrites binden aware Zeitwerte verlustfrei als UTC-naiv. Alte
  potenziell durch PostgreSQL-Sessionzeitzonen verschobene Werte bleiben
  unverändert und benötigen eine belegte historische Zuordnung.
- Die alte vollständige Entitätshistorie bleibt kompatibel und noch
  unpaginiert. Die neue UI verwendet sie nicht.
- Livecursor frieren die Gesamtmitgliedschaft nicht ein. Der vollständige
  SQL-CSV hat seinen tatsächlichen Snapshot; Memory-CSV ist pro Batch live.
- Ein gemessener Zeit-/ID-Index und100000-/Millionen-/Zehnbenutzer-Leistungs-
  abnahme stehen aus.10002 synthetische Zeilen sind kein20-Jahres-Nachweis.
- Die allgemeine atomare Erzeugung von Feldhistorie gehört weiterhin Paket L.
- Die alte globale Benachrichtigungsglocke ist im Browser weiterhin sichtbar;
  ihr persönlicher vollständig berechtigter Ersatz wird getrennt vorbereitet.
- CI enthält verbindliche History-PG-/Browserregistrierung. Remote-CI und die
  vollständige gemeinsame Releasefreigabe wurden dadurch nicht ausgeführt.
- Dieser Rootstand ist noch nicht an die private laufende Release126-Vorschau
  ausgeliefert. K2 ist unverändert; L2 bleibt TEHA vorbehalten.
