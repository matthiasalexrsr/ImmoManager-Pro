# Fortsetzung: Nachrichtenzuordnung und native Sitzungsprüfung

## Implementierter Benutzerweg

In Nachrichten → Konversationen bleibt die Auswahl bei der bewusst gewählten Konversation. Jeder Leseversuch besitzt Abbruchsignal, Requestgeneration und Sitzungskontrolle. Ein alter Inhalt wird beim Wechsel sofort entfernt; Ladefehler erscheinen mit einer Wiederholungsaktion statt als angeblicher Leerbestand. Antworttexte und ausstehende Sendebestätigungen sind an den Thread gebunden. Ein später bestätigtes Senden aus A verändert weder Auswahl noch neuen Entwurf in B. Auch ein nach dem Senden erneut bearbeiteter Text in A wird nicht gelöscht.

Die Oberfläche liest neueste Nachrichten in begrenzten SQL-Keysetseiten. Innerhalb einer Seite gilt zeitliche Lesereihenfolge; „Ältere Nachrichten“, „Neuere Nachrichten“ und „Aktualisieren“ halten den gesamten Bestand erreichbar. Die vollständige berechtigte Anzahl kommt vom Server, nicht aus den hundert angezeigten Zeilen. Identische Zeitstempel werden anhand der stabilen Nachrichten-ID aufgelöst. Eine Aktualisierung zeigt neue Einträge; dies ist eine lebende Ansicht, kein eingefrorener Export.

Ein neuer GUI-Sendebefehl enthält Thread-ID, dessen Quellrevision und einen Wiederholungsschlüssel. Nachricht, Zähler/Threadrevision und Receipt werden im bestehenden fachlichen Transaktionsrahmen zusammen gespeichert. Nach verlorener Erfolgsantwort gleicht „Speicherung abgleichen“ exakt denselben Befehl ab. Ein anderer Text mit altem Schlüssel wird abgelehnt; eine inzwischen entfernte bestätigte Nachricht wird nicht wieder angelegt. Der echte Benutzername stammt vom serverseitig geprüften Konto, nicht aus einem behaupteten Absenderfeld.

Leser sehen keine Erstell-/Sendeaktion. Seiten, Schreiben und Wiederholung prüfen die Thread-/Dateirechte. Ein Sitzungswechsel räumt Auswahl, Nachrichten, Listen und Entwürfe der früheren Sitzung aus. Im Browser werden 1440, 360 und 320 Pixel, tatsächliche Tastaturbedienung und Fokus geprüft. Die Bilder wurden zusätzlich angesehen: Ein zunächst zu schmales mobiles Antwortfeld wurde durch ein eigenes responsives Raster korrigiert und mit Mindestmaßen erneut geprüft.

## Vertrag und Grenzen

- Neue lesende Route: `GET /api/v1/messages/threads/{thread_id}/page?limit=100&cursor=…`; erlaubte Seitengröße 1–250. Rückgabe: `items`, `next_cursor`, `has_more`, vollständiges `total`, aktueller `thread` und Sortiervertrag.
- Bestehende POST-Route bleibt erhalten. `idempotency_key` und `base_revision` müssen zusammen vorkommen. Der alte Antwortdatentyp bleibt unverändert; Kontrollfelder werden nicht als Nachricht gespeichert.
- Bestehende nicht mit einem Schlüssel versehene v1-Aufrufe behalten ihren bisherigen Kompatibilitätsweg. Für sie wird keine nachträglich erfundene Wiederholungs- oder CAS-Garantie behauptet. Der neue GUI-Antwortweg verwendet immer die kontrollierte Variante.
- Die Threadwechsel-Entwürfe und offenen GUI-Befehlsschlüssel liegen in dieser Komponente im Arbeitsspeicher. Diese Änderung allein behauptet keine neue browserübergreifende oder absturzfeste Nachrichten-Outbox. Die allgemeine Kommunikations-/Outbox-Erweiterung bleibt ein eigenes Handoverpaket.
- Es findet kein E-Mail-, WhatsApp- oder sonstiger externer Versand statt. Ein intern gespeicherter Beitrag ist keine externe Zustellbestätigung.
- Neue additive Migration `c61e9a2f034b` folgt auf `b82d5fa03147`. Sie ergänzt ausschließlich `ix_messages_thread_sent_id(thread_id, sent_at, id)`, erhält Zeilen/Feldwerte und prüft eine bereits identisch vorhandene Indexdefinition. Keine veröffentlichten Migrationen wurden geändert.
- Dauerhafte Wiederholungsbelege verwenden die vorhandene `business_qol_commands`-Tabelle. Der Receipt speichert nur die Nachrichtenidentität, nicht eine zweite Kopie des privaten Textes. Das Vollbackup enthält dadurch automatisch Nachricht, Rechte, Receipt und Index.

## Commits

1. Frühere Basis: `fe561d0a7cdbcdc4ee7b4adc1a23a1598450f5a7` (Sitzungswiderruf) und `ae44ab930fd1d1379ae546759d65d2ca47563cf2` (Pfad-/Body-Abgleich).
2. `eb70b53c0ec8424220560fbb87b3f73fcfc92b16`: Nachrichtenworkflow, additive Indexmigration, GUI, gezielte Backend-/Frontend-/Recovery-Regressionen.
3. `b264cf81ac08dd2bfe3741b71d632f0d5ebbd97b`: zwei native Authprozessprüfungen, isolierte Prüfstarter, echte Browserabnahme; unveränderte CI-Gates gelten zusätzlich für `pro/**`.

Die beiden neuen Commits stehen auf dem eigenen Zweig `pro/interfaces-20261015`. Ein Push dieses Zweiges ist erfolgt; kein Tag, kein Merge, keine Releaseveröffentlichung und keine Umstellung einer laufenden Installation. CI-Lauf `38815280138` prüft den genauen Commit `b264cf81`; beim Schreiben dieses Dokuments läuft er noch und wird nicht als bestanden ausgegeben.

## Aussagekräftige Nachweise

Alle folgenden Verzeichnisse liegen im eigenen Checkout. Frühere rote Prüfungen bleiben erhalten. Die Läufe vor dem Commit haben einen aufgezeichneten Arbeitsstand mit Dateihashes; sie werden nicht als ursprünglich auf einem späteren Commit gestartete Prüfungen umbenannt.

| Prüfung | Ergebnis / Artefakt |
| --- | --- |
| Sechs ursprüngliche rote Frontendfälle nach Implementierung | 6/6; `artifacts/pro-tests/messages-first.json` |
| Erweiterte Nachrichtenkomponente | Alle 15 Fälle in den vollständigen und gezielten Frontendläufen bestanden |
| Memory, erste Nachrichtenprüfung | 15 bestanden; `messages-complete-memory-6678b6ae0a3b42378ac4c6c0d4d6e608` |
| SQLite, korrigierter Stand | 15 bestanden, keine Skips; `messages-sql-corrected-sql-1aff2dd6113141bf8cd46372b11a93ba` |
| Native PostgreSQL-Nachrichtenprüfung | 15 bestanden, keine Skips; `owned-native-native-2c8591e20b584dc09bfc34a3e9acc6ca` |
| Native Auth- und Nachrichten-Gatefamilien | 3 äußere Fälle bestanden, keine Skips, davon ein Kindlauf mit allen 15 Nachrichtenfällen; `artifacts/pro-native/dd79791f13ad4b80bebb3990330217b2` |
| Vollbackup und isolierte Nachrichtenwiederherstellung | 1 bestanden; `message-recovery-memory-b3ae7edb2790436f9da57e3a29e82174` |
| Echte Browserprüfung, korrigiertes Layout | 11/11, keine Browserfehler; `artifacts/message-browser/messages-1bg8nub8/checks/results.json` und drei Screenshots |
| Tatsächlich sauberes npm ci im eigenen Frontend | Exitcode 0; `frontend-c4c7366e1ebe40ffb5d92ad780dc5161`; Lockdatei vor/nach identisch |
| Frontend lint / Produktionsbuild | Beide Exitcode 0 im vollständigen Lauf `frontend-5a2e91c9a68a498eb9e8e309e7112953` |
| Backend Ruff und Mypy | Bestanden; Mypy prüfte 425 Quelldateien |

Die Größenprüfung enthält **10.057 Nachrichten mit demselben sent_at**, vollständige unabhängige ID-/Textorakel, eindeutige Cursor und begrenzte SQL-Abfragen. Die native Konkurrenzprüfung fordert zwei verschiedene PostgreSQL-Backend-PIDs. Die Authprüfung lässt zwei getrennte Betriebssystemprozesse zuerst denselben gültigen Refresh-Token prüfen und erst danach gleichzeitig widerrufen: genau ein Prozess gewinnt. Zwei weitere neue Prozesse müssen den gespeicherten Widerruf erkennen. Die Testserver werden nach jedem Lauf beendet; das vorhandene Testcluster bleibt unverändert.

Die Restoreprüfung entfernt den ursprünglichen Laufpfad vor dem erneuten Öffnen. Aus dem Archiv bleiben Anmeldung, tatsächliche Anhangbytes, Schlüsselmaterial, Thread, einmaliger Beitrag und Receipt erhalten. Die erneute identische Bestätigung erzeugt weiterhin genau einen Beitrag. Dies ist der Wiederherstellungsnachweis für dieses Paket, nicht die vorgezogene Behauptung, das gesamte portable Installationspaket sei bereits umgesetzt.

## Sichtbar gebliebene Fehlversuche

- Der erste SQLite-Nachrichtenlauf hatte drei Fehler. Tatsächlich uneinheitliche UTC-/Naivzeit-Ausgaben bei Wiederholung wurden korrigiert. Der Rechteentzugstest hatte außerdem nur eine neue ID-Liste, aber nicht den erforderlichen Modus an den internen SQL-Accountstore übergeben; er gibt jetzt beides an und prüft die tatsächlich entzogenenen Grants vor der unveränderten 404-Assertion.
- Der erste vollständige Frontendlauf mit Standardparallelität: **555 bestanden / 34 fehlgeschlagen**. Der zweite mit zwei Workern: **587 bestanden / 2 fehlgeschlagen**. Die zwei verbliebenen Fälle sind bestehende Cache-/Parteienfälle mit Laufzeit um fünf Sekunden. Kein Testtimeout, keine Assertion und kein Gate wurde herabgesetzt. Ein unveränderter diagnostischer Dreidateienlauf mit begrenzter Parallelität bestand 32/32. Das ersetzt nicht den noch ausstehenden grünen Gesamtlauf.
- Die erste Browserfassung bestand ihre elf Ablaufprüfungen, zeigte aber bei visueller Kontrolle ein zu schmales mobiles Antwortfeld. Die aktualisierte Fassung fordert zusätzlich mindestens 200 Pixel Breite und 100 Pixel Höhe sowie den korrekten Sidebar-Zähler; die neuen Bilder sind geprüft.
- Ein weiterer Browserversuch scheiterte im Prüfer selbst an einem bereits behandelten Playwright-Routeobjekt bei simulierter Verbindungsunterbrechung. Die korrigierte Simulation speichert zunächst wirklich auf dem Server und verliert danach nur die Erfolgsantwort am Prüfproxy. Erst der anschließend vollständig bestandene Lauf wird als aktueller Nachweis verwendet.

## Reproduzierbare Prüfungen

Aus dem eigenen Checkout mit der vorhandenen Python-Prüfumgebung:

```text
python scripts/run_pro_matrix.py --backend memory --label message-current backend/tests/test_message_workflow.py backend/tests/test_message_thread_boundary.py backend/tests/test_message_recovery.py backend/tests/test_auth_failclosed.py
python scripts/run_pro_matrix.py --backend sql --label message-current backend/tests/test_message_workflow.py backend/tests/test_message_thread_boundary.py
python scripts/run_pro_native.py --binaries <geprüftes-postgres-bin-Verzeichnis> --mode auth-message
python scripts/run_pro_native.py --binaries <geprüftes-postgres-bin-Verzeichnis> --mode full-gate
python scripts/run_pro_frontend.py --max-workers 2
python scripts/run_message_browser_qa.py --playwright <absoluter-geprüfter-playwright-local.mjs-Pfad>
```

Die Starter besitzen eigene Datenpfade, eigene Datenbanken und eindeutige Ergebnisdateien. `run_pro_native` legt ein neues passwortgeschütztes Loopbackcluster an; es ändert weder ein fremdes Cluster noch dessen Zugangsregeln. `run_pro_frontend` verändert keine Lockdatei. Der Browserstarter besitzt ausschließlich synthetische Bestände und eigene Ports; 8000 und 8765 werden verweigert.

## Fortsetzung / Integration

Der Gesamtauftrag läuft weiter. Als Nächstes folgen gemeinsamer Verbindungs-/Mapping-/Run-/Receipt-Vertrag und robuste Importwege. Die Fortschrittsmatrix bleibt in `PRO_IMPLEMENTATION_PROGRESS_20261015.md`; die übrigen Handoverpakete werden durch diese Nachrichtennacharbeit nicht als erledigt markiert.

Für Codex sind zusätzlich zur bisherigen Authänderung `backend/routers/messages.py`, `backend/db/orm_models.py`, die neue Migration und `frontend/src/pages/Messages.jsx` mögliche Konfliktstellen. Vor Übernahme aktuelle zentrale Änderungen vergleichen, alle Gates auf dem kombinierten Stand erneut ausführen, Backup vor expliziter Migration anlegen und den Frontendbuild ausdrücklich neu erzeugen. Integration und Auslieferung bleiben getrennt von diesem Entwicklungszweig.
