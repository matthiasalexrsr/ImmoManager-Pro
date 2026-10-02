# Geprüfter CSV- und MT940-Bankimport

Der lokale Dateiimport erstellt ausschließlich offene Bankbuchungen. Er bucht
keine Forderungszahlung, verändert keine Zuordnung und löst keine Banküberweisung
aus. Zahlungen und Matching bleiben ausdrücklich bestätigte Folgeaktionen.

## Dateivertrag

`POST /api/v1/bookings/imports` nimmt Multipart `account_id`, `mapping` (JSON)
und `file` entgegen. Das aktuell freigegebene Konto wird serverseitig geprüft.
Die Originalbytes werden in 64-KiB-Datenbankchunks mit SHA-256 gesichert; kein
Dateipfad und kein externer Dienst ist erforderlich. Vorschauzeilen, Fehler,
Zuordnungsversion und Hash bleiben gespeichert. Bei SQL überstehen sie Neustarts;
der explizite Memory-Referenzbetrieb meldet `persistent:false`.

CSV-Zuordnung Version 1:

```json
{"version":1,"format":"csv","encoding":"utf-8-sig","delimiter":";",
 "date_column":"date","amount_column":"amount","text_column":"text",
 "date_format":"%Y-%m-%d","decimal_separator":"legacy",
 "thousands_separator":null,"reference_column":null,"currency":"EUR"}
```

Datumsformat (`%Y-%m-%d`, `%d.%m.%Y`, `%m/%d/%Y`), Kodierung (UTF-8 mit optionalem
BOM, UTF-16 mit BOM, Windows-1252), Trennzeichen und Betragsformat werden explizit
gewählt. `legacy` akzeptiert jeweils Punkt oder Komma, niemals mehrdeutige
gemischte Trennzeichen. Tausendergruppen erfordern ein ausdrücklich separates
Trennzeichen. Beträge bleiben Decimal-/Integer-Centwerte; keine Rundung von
Bruchteilen eines Cents und keine Float-Summierung. Nullbeträge und die Kapazität
der vorhandenen `NUMERIC(12,2)`-Geldspalte werden vor Veröffentlichung geprüft.
Explizite Gruppierungen unterstützen Punkt, Komma, normales Leerzeichen,
geschütztes Leerzeichen U+00A0 und schmales geschütztes Leerzeichen U+202F.
`parse_amount_cents` beweist die reine Integer-Konvertierung auch oberhalb der
Datenbankkapazität; der Buchungsimport meldet dafür einen gespeicherten,
korrigierbaren Kapazitätsfehler statt Rundung oder Abschneiden. Die separat
geprüften Assistenten-Fälle liegen als reproduzierbare Testfixtures im Projekt.
Die bestehende Buchung besitzt keine Fremdwährungsspalte: Der Import erlaubt EUR
und lehnt eine andere MT940-Währung konkret ab, statt sie als EUR umzudeuten.

MT940 nutzt `mt-940` 5.1.1 (BSD-3-Clause, keine Laufzeitabhängigkeiten) zur
Konvertierung jedes einzelnen physischen `:61:`-Felds. Das Produkt verarbeitet
die Datei inkrementell und umgeht das dokumentierte Zusammenfassen von
Transaktionen in vollständigen Parserkollektionen. `RC` ist negativ, `RD` positiv;
ein vorhandenes Buchungsdatum wird samt Jahreswechsel aufgelöst, sonst gilt das
Valutadatum. `:86:`-/`NS`-Text bleibt erhalten. Konto (`:25:`) muss zur gespeicherten
IBAN passen; `:20:`, `:28C:`, Eröffnungs- und Schlusssalden sind erforderlich.
Eröffnung plus exakte Transaktionscents muss dem Abschluss entsprechen. Mehrere
Auszüge bzw. vollständige Zwischenseiten können in einer Datei stehen. Eine
unbekannte Dialekt-/Kontonummernnotation liefert einen gespeicherten Fehler,
keine stillschweigende Auslassung. CSV-Zuordnung bzw. bankseitiger Export ist
dann die korrigierbare Alternative. Keine pauschale Bankformatkompatibilität.

Primärquellen: [Bibliothek und Lizenz](https://github.com/wolph/mt940),
[Gruppierungsgrenzen](https://mt940.readthedocs.io/en/latest/statements.html),
[Tag-Konvertierung und Options](https://mt940.readthedocs.io/en/latest/mt940.tags.html).

## Vorschau, Freigabe und Wiederholung

`GET /bookings/imports?account_id=…` blättert gespeicherte Importe des verfügbaren
Kontos. `GET /bookings/imports/{id}` liest den aktuellen Zustand.
`GET /bookings/imports/{id}/preview?page_size=100` liefert `items`, `has_more`,
`next_cursor`; `errors_only=true` blättert sämtliche Fehler. Der signierte Cursor
bindet Import, Vorschauhash, Größe, Filter und aktuellen Principal/Scope. Ein
ungültiger oder anders gebundener Cursor gibt einen verständlichen Code mit
`restart_preview` zurück; kein automatischer Wechsel auf eine andere Vorschau.

`POST /bookings/imports/{id}/confirm` erfordert den angezeigten `revision` und
`preview_hash`. Erst dann erscheinen Buchungen und unveränderliche Herkunfts-
Receipts in **einer** Transaktion. Chunkweise INSERTs begrenzen den RAM-Verbrauch,
haben aber keine separaten Veröffentlichungs-Commits. Auch ein später SQL-Fehler
oder Rechteentzug rollt sämtliche Buchungen, Receipts und Revision zurück.
Kontolock, Revisions-CAS und UNIQUE-Fingerprint schützen unabhängige Prozesse;
nach Warten auf den Lock wird der Job erneut geladen. Fertige Bestätigungen
sind sichere Wiederholungen und liefern `replay:true`.
SQLite startet hierfür vor dem ersten Journal-Read ausdrücklich `BEGIN IMMEDIATE`.
Dies schützt auch führende `WITH … UPDATE`-Accountprädikate, die der Legacytreiber
sonst nicht als Schreibtransaktion erkennt. Deren unbekannter `rowcount` wird auf
derselben Verbindung über `changes()` bestimmt. Lesende Vorschauen sperren keine
Writer. PostgreSQL behält seinen zeilenweisen Accountlock.

Originaldatei, Konto und Mappinghash identifizieren einen gespeicherten Import.
Ohne ausdrückliche Bank-ID identifiziert **Datei-SHA plus Quellordinal und Konto**
die Transaktion. Gleiche Datum-/Betrag-/Textzeilen bleiben getrennt. Zwei andere
Dateien mit solchen Werten werden niemals heuristisch verschluckt. Eine
übereinstimmende SHA wiederholt ausschließlich denselben Kontofileimport.

Eine ausdrücklich gewählte CSV-Referenzspalte muss eine eindeutige Bank-ID sein.
`reference_namespace` unterscheidet deren Herkunft. Eine im CSV doppelte ID ist
ein Vorschaufehler; eine bereits veröffentlichte ID mit identischem Inhalt ein
nachvollziehbares Duplikat. Abweichender Inhalt derselben ID blockiert die
Veröffentlichung. MT940 bindet Referenzen an Auszugreferenz und Auszugnummer;
wiederholte Bankreferenzen erhalten eigene Vorkommensindizes. Ohne Bankreferenz
bleibt jede physische Transaktionsposition erhalten. Dies ist ein dokumentierter
Datei-/Auszug-Identitätsvertrag, keine aus Betrag/Text erfundene Bankidentität.

`GET /bookings/imports/{id}/receipts?after=0&page_size=100` liefert alle erzeugten
Booking-IDs durch technische Seiten (`items`, `has_more`, `next_after`). Die
Originalprovenanz bleibt erhalten, auch wenn eine unzugeordnete Buchung später
bearbeitet oder entfernt wird. Eine Wiederholung legt sie dann nicht erneut an.

`GET /bookings/imports/{id}/source` lädt die Originalbytes als Attachment mit
SHA-256-Header, festem Octet-Stream-MIME und `nosniff` herunter. Vor Responsebeginn
werden Originalhash und aktuelle Kontoberechtigung geprüft. Der Stream liest
höchstens 64 KiB pro Schritt und prüft Scope und aktuellen Account in einer
frischen, danach geschlossenen SQL-Session für jeden Chunk. Berechtigungsverlust
bricht den Stream ab. Keine Transaktion oder ContextVar bleibt über ein Yield
offen; Tokens stehen ausschließlich im Authorization-Header. Die Oberfläche
bietet den Originaldownload auch für berechtigte Readonly-Konten an.
Browser mit File System Access API können die Originaldatei direkt als Stream
speichern; dabei puffert die Oberfläche keinen vollständigen Blob. Der normale
Download bleibt als kompatibler Weg verfügbar und erhält den Originalnamen.
Ein abgebrochener Stream wird sichtbar gemeldet und nicht automatisch als
vollständiger Download wiederholt.

Rolle und Bestandsrechte werden beim Eingang, jedem bestätigten Chunk und direkt
vor dem Commit serverfrisch geprüft; das gegenwärtige Konto wird erneut gelesen
und gesperrt. Kontowechsel des Portfolios nach Vorschau verweigert Bestätigung.
Ein weiterhin berechtigter Owner kann einen gespeicherten Import übernehmen.
Kein Zugriff wird aus einer alten Client-Rolle oder Vorschau abgeleitet.
MT940 bindet zusätzlich die beim Prüfen verwendete kanonische Kontoverbindung als
`mapping.account_binding_hash`. Eine IBAN-Änderung vor Veröffentlichung verlangt
eine neue Prüfung; die öffentliche Zusammenfassung enthält keine Klartext-IBAN.
Importlisten filtern die noch gültige Portfolio-/Accountbindung.

## Kompatibilität und technische Kapazität

Der alte JSON-/Direktaufruf `/reports/bookings/import` akzeptiert weiterhin
`account_id`, `csv_content` mit `date;amount;text`. Er benutzt denselben atomaren
Dienst: eine einzige ungültige Zeile bedeutet `imported:0`, vollständige Prüfung
und keinen Teilbestand. Zählwerte betreffen den vollständigen Import. Detail-
Arrays enthalten ausdrücklich eine Seite mit Fortsetzungsangaben und Import-ID;
alle Fehler und Booking-IDs bleiben über die neuen Seiten abrufbar. Das alte
JSON-Protokoll liefert bereits einen vollständigen String an FastAPI; der
Adapter erzeugt keine weitere vollständige Bytekopie und keine globale Zeilen-
liste. Große Dateien sollen den Multipart-Dateipfad verwenden.

`BANK_IMPORT_PAGE_MAX_SIZE` (Default 500, validierte Spanne 25…5000) steuert
technische Seiten/SQL-Chunks; `BANK_IMPORT_FIELD_MAX_CHARS` (Default 100000,
validierte Spanne 1024…100000000) begrenzt einzelne Felder. CSV-Records sind auf
das Achtfache der gewählten Feldkapazität begrenzt. Ein Kapazitätsfehler nennt
die korrigierbare Dateizuordnung bzw. Serverkapazität. Es gibt keine Grenze für
Gesamtzeilen, Bestände oder Jahre. SQL braucht keine globale COUNT-Abfrage und
materialisiert nicht alle Datensätze im Browser oder Server-RAM.

## Root-Integration und Nachweise

Die unten beschriebenen Registrierungen und Erhaltungshooks sind im gemeinsamen
Produktpfad integriert. `test_bank_import_application.py` verwendet die echten
Router, Authentifizierung, Portfolioscopes und Fehlerhandler für Memory und SQL:
Geschäfts-JSON-Export/-Ersatz, Reset und Konto-/Portfoliolöschung behalten bei
einem 409 die Originalbytes und Receipts. Ein fremdes Konto bleibt ein 404.
Additive Geschäftsdaten-Merges erhalten das Journal; Memory-Staging nutzt unter
dem bestehenden RLock getrennte Deepcopy-Memos, die nur die Journalengine teilen.
Ein fehlgeschlagener Merge verändert weder Geschäftsdaten noch Originaldatei.
Die Hooks gelten auch für direkte Store-/Repository-Cascades. Vollständige
Recovery ist der angebotene Sicherungspfad für diese Herkunftsnachweise.

- Neue u1-Revision `u1a2b3c4d5e6` folgt ausdrücklich auf `t1a2b3c4d5e6`; die
  vorherigen Outbox-/Tax-/Historienrevisionen bleiben Voraussetzungen.
- `BankImportORM` bzw. `BANK_IMPORT_TABLES` vor `create_all` und Alembic-Metadaten
  registrieren; `ensure_bank_import_schema(connection)` im expliziten Bootstrap.
- Router `backend.routers.bank_imports` vor generischen Booking-ID-Routen
  registrieren. Er verwendet die bestehende `/bookings`-Finance-Berechtigung.
- Root-Settings übernehmen die zwei Kapazitäten oben. Leeren eines Teststores
  muss die vier Sidecars in umgekehrter Reihenfolge behandeln; Memory-Journal
  `_bank_import_engine` disponieren. Offene Daten-/Full-Recovery-Backups erhalten
  SQL-Originalchunks; der ältere Geschäfts-JSON-Export darf Importprovenanz
  keinesfalls stillschweigend verlieren (bestehende failclosed-Tabelleguards).
- `backend.services.bank_import_guards` liefert Root explizite Hooks:
  `guard_bank_import_reset(store)` vor destruktivem Reset/Subset-Ersatz,
  `guard_bank_import_business_transfer(store, operation='export'|'replace'|'merge')`
  vor Geschäfts-JSON-Operationen und `guard_bank_import_account_delete(store, id)`
  sowie `guard_bank_import_portfolio_delete(store, id)` nach Scopeprüfung vor
  Löschung/Cascade. Der Portfoliohook folgt der **aktuellen** Accountzuordnung,
  nicht dem historischen Snapshot; Memory liest distinct Account-IDs in Seiten
  à 100. Sie prüfen begrenzt `LIMIT 1`, ändern keine Daten
  und geben konkrete 409 mit Erhalt-/Recoveryhinweis. Memory-Journals dürfen nicht
  blind mit SQLAlchemy-Engine deepcopy kopiert werden. Additives SQL-Merge ist
  erlaubt und behält die Originaljournals/Account-IDs; ein Memory-Merge benötigt
  Roots Memo-/RLock-Erhaltungsprotokoll und `memory_journal_preserved=True`.
  Explizite interne
  Test-/Initialisierungsbereinigung ist hiervon zu trennen.
- Standard-Gates: `test_bank_imports.py`, `test_bank_imports_http.py`; echter
  PostgreSQL-Gate `test_bank_imports_postgres.py` nur über dedizierte
  `TEST_SERVER_DATABASE_URL`/eigenes UUID-Schema. Kein behaupteter lokaler PG-Pass.
- `python scripts/bank_import_benchmark.py --rows 100000 --output report.json`
  erstellt ausschließlich synthetische Dateien/SQLite in seinem eigenen Temp-
  Verzeichnis. EXPLAIN muss den Import/Ordinal-Keysetindex benutzen. Report misst
  Zeiten und `tracemalloc`-Python-Spitzen, ausdrücklich **keinen** Prozess-RSS.
  Der optionale Record-Parameter ist keine Geschäftsgrenze und kein 1m-Loop in
  der normalen Testsuite.
