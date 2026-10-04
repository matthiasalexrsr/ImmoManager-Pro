# Vollständige globale Suche – Integrationsnachweis

Root-Basis: `5e636e0`. Die laufende Vorschau Release126 ist davon weiterhin getrennt.

## Ergebnis

`GET /api/v1/search/page` liefert vollständige, begrenzte Stichwortseiten aus den
16 bisher durchsuchten Fachbereichen. Die tatsächlichen Kontakt-, Interessenten-
und Anschriftfelder werden verwendet. Unicode-Casefold und wörtliche `%`, `_`
und Backslashes funktionieren gleich in Memory, SQLite und PostgreSQL.

SQL lädt nur die Trefferprojektion einer Seite. Memory verwendet einen
begrenzten Heap unter der gemeinsamen Datensperre. Cursor sind an Suchbegriff,
Seitengröße und Benutzer-/Portfolio-Rechte gebunden. Die aktuelle Berechtigung
wird vor und nach der Abfrage sowie unmittelbar vor Veröffentlichung geprüft.
Quellenfehler werden nicht zu vermeintlich leeren Treffern umgewandelt.

Die Suchleiste bietet Folgeseiten, vorherige Seiten und einen gezielten Retry.
Ein Konto-/Rechtewechsel verwirft alte Inhalte synchron; verspätete Antworten
werden ignoriert. Paging und Retry geben den Fokus vor Zustandswechseln zurück
in die Suche. Der echte Browser hat hierbei einen Fehler aufgedeckt: Das
Deaktivieren des fokussierten Seitenbuttons schloss vorher das Suchfeld und
brach die angeforderte Seite ab. Dieser Fehler ist behoben und nachgeprüft.

## Ausgeführte Prüfungen

- Memory/SQLite/HTTP-Suche einschließlich bestehender semantischer
  Rechteprüfung: **12 bestanden** (33,82s).
- PostgreSQL16 über eigene UUID-Schemas und echte SQL-Benutzerkonten:
  **3 bestanden, keine übersprungenen Fälle** (43,93s). Alle 10.001 Treffer
  in21 begrenzten Seiten; SQL-Projektionen/LIMIT, Unicode und Übergang zwischen
  Fachbereichen; Rechteentzug und unzulässiger Cursor-Replay.
- Frontend: **10 bestanden** (4,68s), ESLint erfolgreich.
- Tatsächlicher Edge-Browser mit explizit migrierter, isolierter SQLite-Datenbank:
  **1 bestanden** (14,9s inklusive Browserstart).101 echte Immobilien in drei
  Seiten,503 auf Folgeseite, Retry exakt desselben Cursors, Tastaturauswahl und
  Ansichten1440/360/320. Screenshots1440 und320 zusätzlich visuell geprüft.
- Produktionsbuild, Ruff, Mypy unter Python3.11 und `git diff --check` erfolgreich.
- Die PostgreSQL-Fälle gehören zur verbindlichen CI-Auswahl mit Skip-Verbot.

## Kompatibilität und offene Arbeit

`/api/v1/search` behält die bisherigen Schlüssel und optional die semantische
Empfehlungsrangfolge. Die Antwort kennzeichnet diese ausdrücklich als
`recommendations`; vollständige Stichwortseiten sind unabhängig erreichbar.
Das bestehende semantische Reindexieren lädt weiterhin den Indexbestand;
dessen fortsetzbare Überarbeitung bleibt Bestandteil von PaketB/L.

Die Seiten bilden einen lebenden Bestand ab. Sie versprechen keinen über
mehrere Requests eingefrorenen historischen Snapshot. Neue Fachmodule müssen
ihre Quellen gezielt in die Suche aufnehmen. Dashboardaggregate, übrige
Bestandslisten und die gesamte gemeinsame Releaseabnahme sind noch offen.
