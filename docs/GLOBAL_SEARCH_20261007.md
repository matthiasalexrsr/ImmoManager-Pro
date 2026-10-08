# Globale Suche: serverseitig, vollständig gezählt, seitenweise

Stand 7. Oktober 2026, Branch `claude/global-search-pagination` (Basis `claude/dreamy-gauss-nmaxhn`). Umsetzung des Pakets „P1 B: Suche und vollständige Daten“ aus Abschnitt 9 der Übergabe (`CLAUDE_HANDOFF_20261007.md`).

## Vorher

`GET /search` lud für 16 Typen den kompletten Bestand (`store.list_*()`), filterte in Python und brach nach zehn Treffern je Typ bzw. 50 insgesamt ab. Eine Gesamtzahl oder Folgeseiten gab es nicht. Einige Felder existierten im Modell gar nicht (Buchung `description`, Interessent `name`, Kategorie `description`, Dokument `doc_type`) und wurden still übergangen.

## Regel

- Ein Treffer enthält den Suchbegriff (getrimmt, klein geschrieben) als **wörtliche** Teilzeichenkette. Durchsucht werden die Suchfelder des Typs, mit einem Leerzeichen verbunden, leere Felder als „“. Deshalb findet „Johanna Winkelmann“ Vor- und Nachname zusammen.
- `%`, `_` und `\` im Suchbegriff sind gewöhnliche Zeichen, keine Platzhalter.
- Reihenfolge je Typ: nach `id`. Das ist stabil, auch wenn zwischen zwei Seiten Datensätze dazukommen (Keyset statt Offset: keine Dubletten, keine Lücken für bestehende Treffer).
- `total` ist die exakte Zahl der Treffer, die **dieses Konto** sehen darf.

## API

| Aufruf | Antwort |
| --- | --- |
| `GET /search?q=…&limit=10` | Übersicht: bis zu `limit` Treffer je Typ in `results`, je Typ mit Treffern ein Eintrag in `groups` (`entity_type`, `total`, `has_more`, `next_cursor`). Semantische Umsortierung wie bisher (nur hier). |
| `GET /search?q=…&type=tenant&limit=100&cursor=…` | Eine Seite eines Typs (`limit` höchstens 100) mit `total`, `has_more`, `next_cursor`. |
| `GET /search/export?q=…&type=…` | Alle Treffer eines Typs als CSV (`;`, UTF-8 mit BOM, Zellen mit `= + - @` werden entschärft). |

`query`, `count`, `results` und `semantic` bleiben unverändert, die Suchleiste ohne neue Felder funktioniert weiter. Der Cursor ist undurchsichtig und an den Typ gebunden; ein fremder oder kaputter Cursor ergibt 400.

## Technik

| Ebene | Umsetzung |
| --- | --- |
| Dienst | `backend/services/global_search.py`: Typliste (Tabelle, Suchfelder, Anzeige), Treffer-Ausdruck, Keyset-Seite (`limit+1` zeigt „mehr“), Zählung, Export in Blöcken zu 1.000. |
| SQL | Je Typ eine `SELECT … WHERE lower(coalesce(a,'')‖' '‖…) LIKE :p ESCAPE '\' AND id > :cursor ORDER BY id LIMIT n+1` und ein `count(*)` über dieselbe Bedingung, beides über die Session. Die Portfolio-Grenze hängt `portfolio_scope` automatisch an jede SELECT-Anweisung, auch an die Zählung. |
| Speicher-Store | Gleiche Bedingung und Reihenfolge in Python über die bereits begrenzten Sammlungen. |
| Event-Loop | Endpunkte sind synchrone `def` und laufen im Threadpool. Der Export liest vollständig innerhalb der Anfrage (Sitzung und Zugriffsbereich gelten noch) und puffert ab 1 MiB auf Platte; ausgeliefert wird danach in 64-KiB-Blöcken. |
| Oberfläche | `SearchBar.jsx`: Gruppenkopf „10 von 1.234“, Schaltfläche „Weitere laden“ (25 je Klick) hängt die nächste Seite an. Texte de/en/es. |

## Nachweis

`backend/tests/test_global_search.py` läuft für Speicher-Store und SQLite (und über die konfigurierte Datenbank für die HTTP-Fälle):

- 100/101 und 1.000/1.001 Treffer bei Seitengröße 100: alle Seiten vollständig, ohne Dubletten, sortiert, richtige Seitenzahl, `total` exakt, `has_more` korrekt; bei genau 100 kein überzähliger Cursor.
- 10.050 Treffer: 101 Seiten, Export liefert dieselbe Folge.
- Platzhalter `%`, `_`, `\` werden wörtlich gesucht.
- Ein eingeschränktes Konto sieht in Übersicht, Typseiten, Gesamtzahlen und CSV-Export nur sein Portfolio; das Eigentümerkonto sieht beide.
- Jedes Suchfeld existiert als Tabellenspalte und als Modellfeld.

## Grenzen

- `LIKE '%…%'` nutzt keinen B-Baum-Index: Jede Abfrage liest die Tabelle des Typs (bei 10.000 Zeilen in SQLite im Millisekundenbereich). Für sehr große Bestände auf PostgreSQL wäre ein `pg_trgm`-GIN-Index auf den Suchausdruck der nächste Schritt.
- Groß-/Kleinschreibung: Auf SQLite registriert der Dienst eine Python-Funktion `immo_lower`, damit Umlaute wie im Speicher-Store gefaltet werden (SQLites eigenes `lower()` kennt nur ASCII). Auf PostgreSQL gilt `lower()` der Datenbank-Locale; Sonderfälle wie `ẞ`/`İ` können von Python abweichen.
- PostgreSQL 16 geprüft: alle 16 Typen laufen (auch Betragsspalten), Portfoliogrenze und `%`-Escaping halten (`test_portfolio_scope_postgres.py`).
- Die semantische Umsortierung gilt nur für die Übersicht; „Weitere laden“ liefert Schlüsselworttreffer in `id`-Reihenfolge.
- Die Übersicht stellt je Typ zwei Abfragen (Seite und Zählung), bei 16 Typen also 32.
