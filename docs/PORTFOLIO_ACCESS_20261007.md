# Portfolio-Zugriff: wer welche Bestände sieht und ändert

Stand 7. Oktober 2026, Branch `claude/dreamy-gauss-nmaxhn`. Umsetzung des Pakets „P0/P1 Zugriff“ aus Abschnitt 9 der Übergabe (`CLAUDE_HANDOFF_20261007.md`). Grundlage ist das historische Paket aus `release-root-final-20261004` (`portfolio_scope.py`, `access_models.py`, Migration `o1a2b3c4d5e6`). Übernommen wurden nur Kern und Datenmodell, an den heutigen Stand angepasst. Die alten Abhängigkeiten (Vorgänge, Kommunikationszentrum, Betriebsjournale) sind nicht mitgekommen.

## Regel

- Die **Rolle** bestimmt weiterhin, *was* ein Konto ändern darf (`may_write`).
- Der **Portfolio-Zugriff** bestimmt, *welche Daten* es sieht und ändern kann: `all` (alle Portfolios) oder `selected` (eine Liste).
- Eigentümer haben immer `all`. Nur Eigentümer weisen Portfolios zu, in Einstellungen → Benutzer → „Portfolios“.
- Neue Konten aus der Benutzerverwaltung sehen nichts, bis der Eigentümer zuweist. Der Dialog öffnet sich direkt nach dem Anlegen.
- Bestehende Konten behalten beim Update ihren bisherigen Vollzugriff (`all`, Herkunft `legacy_all`). Das gilt bei der Migration, beim ersten Start mit `create_all` (SQLite) und bei der Wiederherstellung einer älteren Datenbanksicherung. **Es wird also niemandem still etwas entzogen.**
- Eine geänderte Zuweisung gilt sofort, auch für bereits ausgegebene Tokens: Jede Anfrage liest das Konto frisch vom Server.

## Sichtbarkeit

Ein Datensatz ist sichtbar, wenn alle Elterndatensätze, auf die er verweist, sichtbar sind, bis hinunter zum Portfolio. Die Eltern ergeben sich aus den Fremdschlüsseln, den Textverweisen (`contract_id`, `property_id`, …) und `entity_type/entity_id`. Mieter werden über ihre Verträge sichtbar.

Datensätze **ohne** Elternverweis (zum Beispiel Kontakte):

- Legt ein eingeschränktes Konto sie an, werden sie in derselben Transaktion an dessen Portfolios gebunden (`resource_portfolio_grants`).
- Ältere, ungebundene Datensätze gehören der Installation und sind nur mit Vollzugriff sichtbar.

Globale Definitionen (Steuersätze, Benachrichtigungsvorlagen, Eskalationsregeln) sind für alle lesbar und nur mit Vollzugriff änderbar.

Ohne Vollzugriff gesperrt (403): Verwaltung der ganzen Installation (`/admin`, `/audit`, `/integrations`, `/updates`, `/data`, `/diagnostics`, `/dev-notes`, `/autotest`, `/task-status`, Eskalationslauf, Serienaufgaben erzeugen) sowie der Neuaufbau des Suchindex.

## Technik

| Ebene | Umsetzung |
| --- | --- |
| Anfrage | `PortfolioScopeMiddleware` (äußerste Schicht, reines ASGI): liest das Konto im Threadpool, nie im Event-Loop. Ein ausdrücklicher Authorization-Header fällt nie auf den Datei-Cookie zurück. Vor einer erfolgreichen Antwort wird die Zuweisung erneut geprüft. |
| SQL lesen | Jede SELECT-Anweisung im Baum erhält die Grenze ihrer eigenen Tabellen: Listen, Spaltenabfragen der Repositories, Zählungen (`query.count()` liest aus einer Unterabfrage), Unterabfragen und CTEs. Dazu kommen Loader-Kriterien für Beziehungs-Ladevorgänge. Intern bereits begrenzte Abfragen werden markiert und nicht doppelt begrenzt. |
| SQL schreiben | `before_flush` prüft jeden Elternverweis neuer und geänderter Datensätze. `before_commit` liest die Kontozeile in derselben Transaktion (PostgreSQL: `FOR SHARE`) und verweigert den Commit, wenn die Zuweisung inzwischen geändert wurde. |
| Speicher-Store | Sammlungen werden für eingeschränkte Anfragen als gefilterte Ansichten ausgegeben (`ScopedCollection`). |
| Dateien | `/uploads/…`, `/files/download`, OCR und Analyse prüfen den Datensatz, zu dem die Datei gehört. Entwürfe ohne Datensatz sind an die Portfolios des Hochladenden gebunden. Wohnungsgeberbestätigungen laufen über die Vertragsprüfung. |
| Caches | Die geteilten Ergebnis- und Tabellencaches (`backend/concurrency.py`) sind nach Zugriffsbereich getrennt. |
| Suche | Treffer, die nur der installationsweite semantische Index liefert, werden einzeln gegen das Konto geprüft. |

## Gefundene und behobene Lücken

1. Die prozessweiten Caches waren nicht nach Konto getrennt. Ein eingeschränktes Konto hätte Buchungen bekommen können, die ein Eigentümer geladen hatte, und umgekehrt.
2. Die schnellen Listenabfragen lesen Tabellenspalten statt ORM-Klassen. Der reine ORM-Filter griff dort nicht.
3. Zählungen über Unterabfragen zeigten auf dem Dashboard die Zahlen aller Portfolios.
4. Die semantische Suche ergänzte Treffer aus dem globalen Index. Einen Neuaufbau konnte jedes Konto auslösen.
5. Die Wiederherstellung einer Datenbanksicherung von vor dem Update hätte alle Mitarbeiterkonten ausgesperrt.

## Nachweise

| Prüfung | Ergebnis |
| --- | --- |
| Backend gesamt, Speicher-Store | 1362 bestanden (drei Läufe nach den letzten Änderungen). Ein vorheriger Lauf hatte einen einzelnen Fehlschlag, der sich nicht wiederholte und nicht mehr zuzuordnen war. |
| Backend gesamt, SQLite | 1361 bestanden |
| PostgreSQL 16 | Filter, direkte IDs, Entzug zwischen Flush und Commit (abgewiesen, nichts gespeichert), Bindung neuer Kontakte; zusammen mit den Archivtests 7/7 |
| Lecktest Listen | Alle 62 lesenden Endpunkte ohne Pfadparameter: keine IDs oder Namen des fremden Portfolios. Gegenprobe mit Vollzugriff: 10 Treffer. |
| Lecktest IDs | 424 Aufrufe aller lesenden Endpunkte mit Pfadparametern und IDs des fremden Portfolios: keiner öffnet etwas. Gegenprobe mit Vollzugriff: 10. |
| Differenztest Kennzahlen | Jede Antwort des eingeschränkten Kontos entspricht der Antwort, die der Eigentümer ohne das fremde Portfolio bekäme (Speicher und SQLite). |
| Testversion (15 Objekte, 7379 Buchungen) | Konto auf „Privatbestand Reiser“ beschränkt: 6 von 15 Objekten, 2144 Buchungen (alle aus dem Portfolio), fremdes Objekt und fremde Datei 404, Protokoll 403. Antwortzeiten 22–51 ms statt 12–42 ms. |
| Browser (Chromium) | Zuweisung im Dialog, Spalte „Portfolios“, eingeschränkte Anmeldung, Integrationsseite mit verständlichem Hinweis, 360 px ohne seitliches Scrollen, keine Konsolenfehler |

## Bewusst offen

- **Snapshot-Export/-Import (JSON)** überträgt weder Konten noch die Bindungen ungebundener Datensätze. Nach einem Import sind solche Datensätze für eingeschränkte Konten unsichtbar, bis sie neu zugewiesen werden. Das ist sicher, aber unvollständig.
- **Kontakte** ohne Bindung (Bestand vor dem Update) sehen nur Konten mit Vollzugriff. Ob Handwerkerkontakte installationsweit lesbar sein sollen, ist eine fachliche Entscheidung.
- **Hintergrundjobs** (Mahnläufe, Benachrichtigungen) laufen ohne Konto als Installation. Ihre Ergebnisse werden beim Lesen gefiltert.
- **Navigation:** Seiten der Installationsverwaltung bleiben in der Navigation eingeschränkter Konten sichtbar und melden beim Öffnen „benötigt Zugriff auf alle Portfolios“.
- Die Prüfung ist eine Anwendungsgrenze, keine Row-Level-Security der Datenbank. Eigene Engine-Verbindungen außerhalb der Session müssen `scoped_clause()` ausdrücklich verwenden. Heute gibt es keine solchen Lesepfade für Fachdaten.
- Das ist kein Mieterportal. Mieterzugänge bräuchten vertragsgebundene Rechte (Übergabe §9, P2).
