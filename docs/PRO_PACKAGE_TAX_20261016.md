# Steuerexport-Paket – Entwicklungs-Handoff

Arbeitskopie: `pro-finish-tax-20261016`, Zweig `pro/finish-tax-20261016`, Ausgang `c16e097003c872972074e403a94d15d63cfb4b59`. Keine Commits, Pushes, Installationen, Provideraktionen oder Zugriffe auf 8000/8765. Alle Änderungen bleiben zur Koordinatorprüfung uncommitted. Stand: lokale Implementierung und Pakettests; **keine vollständige Erfüllung des gesamten DATEV/WISO-Auftrags und keine Integrations-/Releasefreigabe**.

## Implementierte Benutzerwege

- Neue Seite `/tax-exports`, Navigation unter Finanzen. Deutsche Formulare für Portfolio, unveränderliche Profilfassungen, Konten-/Kategorienzuordnungen, Berater, Mandant, Kontenrahmen, Kontenlänge, Sach-/Personenkonten, Festschreibung, Zeitraum und Objektfilter.
- Neutrale Jahressteuerbasis auf **heutigen `bookings`**. Rechnungen, Sollstellungen und `payment_allocations` werden nicht erneut als Zahlungen addiert. Versionierte fachliche Klassifizierung in Einnahme, Ausgabe oder begründet ausgeschlossen; Originalobjektbezug oder explizite Cent-Aufteilungen mit Geldsummenprüfung. Interne Überträge benötigen Gegenbelege auf einem anderen Konto, Erstattungen/Korrekturen explizite Begründung und Quellbezug.
- Vorschau mit Quellanzahl, exakten Cent-Summen, fehlenden Angaben, offenen/nach Stichtag liegenden Buchungen und fachlichen Begründungen. Alle Quellen sind über `/source-page` erreichbar, nicht nur die 20 Musterzeilen. Jahresfassungen brauchen den geprüften `preview_hash`; geänderte Quellen ergeben 409. Eine Jahreswurzel je Portfolio/Jahr und genau ein Nachfolger je Fassung; Revision mit Begründung und Delta.
- Unveränderliche Jahresquellen, JSONL, neutraler Zahlungs-CSV und Steuerzeilen-CSV; vollständige, geprüfte ZIP-Ausgabe. Keine automatische AfA, Eigentümerquote, Steuerrechts- oder WISO-Formularzuordnung.
- DATEV EXTF 700, Datenkategorie 21, Formatversion 13, strikt CP1252, EUR und Kalenderjahr 2000–2099. Ausschließlich explizit geprüfte nicht automatische Konten **ohne Umsatzsteuerautomatik**. Keine geratenen BU-/USt-Schlüssel. Vollständige Ausgabe über mehrere Jahre und Dateien mit jeweils maximal 99.999 Datensätzen.
- Soll/Haben aus dem tatsächlichen Buchungsvorzeichen. Stornos übernehmen das **Gegenkonto des Originals**, haben umgekehrte Geldrichtung und behalten Original-ID plus vollständige Originalquellangaben im JSONL. Die ursprüngliche Zuordnung, Datum, Vorzeichen, Status und Betrag werden geprüft. Ein Storno wird nicht als neue unabhängige Ausgabe kontiert.
- DATEV-ZIP-Originale werden vollständig in 64-KiB-Blöcken mit dem **aktuellen `SecretBox`** gespeichert. Kontext `datev:<Export-ID>:<Sequenz>`. Jeder Download entschlüsselt die gespeicherten Bytes, prüft Reihenfolge, Gesamtgröße, SHA-256 und ZIP-Integrität **vor HTTP-Headern**. Spätere Buchungsänderungen erzeugen bei einem neuen Auftrag einen neuen Export und verändern kein altes Original.
- Jahresquellen sind mit Kontext `annual-tax:<Jahresfassung-ID>:<Sequenz>` verschlüsselt. Manifest, Request, Profil und Quellen werden auf Identität/Hash/Beträge geprüft. Profile und Historie sind vollständig paginiert. Neutrale ZIPs sind deterministisch aus der gespeicherten Fassung abgeleitet.
- Wiederholungsschlüssel pro Akteur und Befehl; abweichender Inhalt mit demselben Schlüssel ergibt 409. Profilnachfolger verwenden die vorherige Versions-ID als CAS. Frontend behält unsichere Befehle für Wiederholung mit identischem Schlüssel und kann Eingaben unter der bestehenden privaten Workspace-Identität lokal wiederherstellen. Nach erfolgreichem DATEV-Auftrag erzeugt eine bewusst neue Prüfung einen neuen Auftrag.
- Rollenprüfung über bestehendes `/reports`-Recht, aktuelle Account-Sperre, heutige Portfolio-/Objektrechte und erneute Scope-Prüfungen. Auch historische Downloads prüfen noch existierende heutige Buchungsquellen; gelöschte Quellen bleiben mit ihrer gespeicherten Portfolioherkunft nachweisbar. Entzug beendet den Download, ohne eine erfolgreiche Nullausgabe zu erzeugen.
- SQLite hält die bestehende Schreibsperre bis zur Veröffentlichung, Memory verwendet die vorhandene Archiv-/Buchungssperre. PostgreSQL-Code hält für die Veröffentlichung SHARE-Sperren auf `bookings`, `accounts`, `categories`, `properties`; das ist eine konservative Quelleinfrierung mit möglicher Schreibwartezeit. Native Mehrprozess-/Performanceprüfung dieses Wegs bleibt beim Koordinator.
- Fehler/Abbruch vor Commit hinterlassen weder halbe Jahresbelege noch halbe DATEV-Archive; derselbe Auftrag kann nach Wiederanlauf erneut ausgeführt werden. HTTP-Disconnects schließen Datei und temporären Arbeitsbereich. Es werden keine vorhandenen Uploadbytes geschrieben.

## Aktuelle API und gemeinsame Integrationsstellen

`/api/v1/reports/datev`: `GET /options`, `GET/POST /profiles`, `POST /preview`, `GET /exports`, `GET /exports/{id}/download`.

`/api/v1/reports/annual-tax`: `GET /options`, `GET/POST /profiles`, `GET /profiles/{id}`, `POST /preflight`, `POST /source-page`, `GET/POST /projections`, `GET /projections/{id}`, `GET /projections/{id}/sources`, `GET /projections/{id}/download`.

Leseseiten verwenden `offset/limit` mit vollständiger Zählung und stabiler Reihenfolge. Quellseiten prüfen den vollständigen Quellhash; eine veränderte Vorschau wird in der UI verworfen. Es gibt keine künstliche Gesamtbestandsgrenze. Memory ist wie im vorhandenen Anwendungskontrakt prozessgebunden; dauerhafte Persistenz und Wiederherstellung sind SQL-Funktionen.

Gemeinsame Dateien: `backend/db/__init__.py`, `backend/routing.py`, `backend/storage.py`, `backend/repositories/sql_store.py`, `backend/services/full_backup.py`, `backend/services/data_snapshot.py`, `backend/routers/admin.py`, `backend/routers/data_exchange.py`, `backend/routers/reports.py`, `frontend/src/App.jsx`, `frontend/src/components/navigation.js`.

Historische URL `/reports/datev-export` bleibt als kompatibler **neutraler** neunspaltiger CSV erreichbar; Dateiname jetzt `Buchungen_neutral.csv`. Sie behauptet keine EXTF-Kompatibilität. Bestehender Test wurde gezielt auf diese fachlich notwendige Kennzeichnung geändert und um die Ablehnung des EXTF-Namens ergänzt.

## Migration, Sicherung und Rückweg

Einzige neue Migration:

```text
… -> c61e9a2f034b -> d73f2b9a041c -> e160a1b2c303
```

Neue Tabellen: `datev_profiles`, `datev_exports`, `datev_export_blocks`, `annual_tax_profiles`, `annual_tax_projections`, `annual_tax_sources`. Keine zweite Geld- oder Zahlungszuordnungsbuchhaltung. Portfolio-/Profil-/Versions-FKs verwenden RESTRICT; Unique Constraints schützen Wiederholungen und lineare Nachfolger. Vorhandene Tabellenwerte werden nicht umgeschrieben. Die neue Revision unterstützt auch eine zuvor über `create_all` adoptierte Datenbank und prüft bestehende Spaltendefinitionen/Indizes. Historische Migrationsgraphen wurden nicht übernommen.

Vor Merge mit anderen Paketköpfen braucht der Koordinator seine eigene Merge-Revision und die vereinbarten gemeinsamen Upgradepfade. Downgrade wird vor der ersten Tabellenmutation verweigert, sobald Steuerbelege vorhanden sind. Rückweg: vollständiges Backup in eine getrennte Installation wiederherstellen; keine belegten Tabellen löschen.

Vollbackup nimmt neue SQL-Tabellen automatisch mit. Zusätzlich werden benötigte Steuer-Schlüssel-IDs im Datenbanksnapshot ermittelt. Die SQLite-Restoreprobe prüft mit den **wiederhergestellten** Schlüsseln auch Steuerquellhashes, Quellanzahl, Reihenfolge, unabhängige Geldsummen und ursprüngliche DATEV-ZIP-Bytes. Ein isolierter vollständiger Restore einschließlich synthetischem Upload ist getestet.

`clear_all`, JSON-Teilbackup und ersetzender Teilimport werden bei vorhandenen Steuerbelegen verweigert. Auch ein vor den Steuerbelegen vorbereiteter Replace wird beim Anwenden erneut geprüft. Ein nicht destruktiver Merge bleibt möglich. Ein JSON-Export ohne Schlüssel und Steuerarchiv wird nicht als vollständige Sicherung ausgegeben; die API meldet 409 mit Hinweis auf Vollbackup.

Temporäre Dateien liegen unter dem zugehörigen `DATA_DIR/tax-work`. Eigene Spools tragen eine Format-/Pfad-/Dateisystemidentität und eine gehaltene OS-Dateisperre. Beim nächsten Export werden nach einem harten Prozessende nur nachweislich verwaiste eigene Spools entfernt; aktive, umbenannte oder unbekannte Verzeichnisse bleiben unangetastet. Ein echter isolierter Kindprozess mit `os._exit(17)` sowie parallele aktive Spools sind getestet. Im normalen Fehler-/Downloadpfad erfolgt sofortige Bereinigung. Bis zum nächsten Export können nach hartem Prozessende temporäre Klartextreste im bestehenden geschützten Datenverzeichnis liegen. Bestehende Dateiberechtigungen/Sicherheitseinstellungen wurden nicht verändert.

## Quellen- und Feldmatrix

Nur gezielt benötigter historischer SOURCE aus den ausdrücklich zugewiesenen Checkouts wurde gelesen. Kein Zugriff auf deren `.env`, Datenbanken oder Artefakte, keine Producer-/Consumer-Probes durch diesen Worker.

| Verfahren/Feld | Quelle | Jahr/Format | Implementierung und Grenze |
| --- | --- | --- | --- |
| DATEV EXTF-Kopf und 125 Spalten | `../datev-export/backend/services/datev_streaming.py`, Stand d7ba1808 | EXTF 700 / 21 / 13; Kalenderjahr 20xx | Portierter strikter Formatter und bestehende Negativfixtures. Kein tatsächlicher Zielimport behauptet. |
| Berater/Mandant/Sachkontenlänge/Kontenrahmen/Festschreibung | geprüfte unveränderliche Profilfassung | pro Exportjahr | Strikte Typen und Grenzen; keine Werte aus Kontennamen geraten. |
| Umsatz/Soll-Haben/Konto/Gegenkonto/Belegdatum/Text | heutige bestätigte `bookings`, explizite Kontierung | Buchungsjahr, EUR | CP1252 ohne Ersatzzeichen, Vorzeichen und Centbeträge geprüft. |
| Stornoreferenz und ursprüngliches Gegenkonto | heutiges `reverses_booking_id`, derselbe Quellsnapshot, heutiger `domain/booking_reversal.py` | eigenes Stornodatum | Originalkontierung und Quelldaten im Belegnachweis; keine erfundene Steuerautomatik. |
| Belegfeld 1 | explizite Profilwahl leer/interne vollständige Buchungs-ID | DATEV | Kein erfundener Rechnungsbezeichner. |
| Vorhandener `receipt_url` | unverändert in `sources.jsonl` | quellbezogen | **Kein verifizierter nativer DATEV-Beleglink**. DATEV-Feld 20 bleibt leer; interne Upload-URLs werden nicht als kompatibles DATEV-Beleglinkformat ausgegeben. |
| Neutrale steuerliche Behandlung/Formularbezeichnung/Objektaufteilung | Jahressteuer-SOURCE aus 12a537b3 und ba12d451, an heutige Buchungen angepasst | ausdrücklich gewähltes Fachjahr, inklusive 2026 | Nutzergeprüfte Klassifizierung, keine gesetzliche oder herstellerspezifische Feldnummer. |
| WISO/Buhl XML-Producerfelder | `../buhl-probe/tools/buhl_xml_probe.py` und `../buhl-probe/backend/tests/test_buhl_xml_probe.py`, Stand 0ac0538b | dort nur generische synthetische `Envelope`-XMLs | **Keine belegten Herstellerfelder enthalten. Keine Feldnummer und kein WISO-2026-Serializer implementiert.** |

## Tatsächlich offene Implementierung und externe Abnahme

1. **WISO-2026-Herstellerproduktion ist eine echte Implementierungslücke.** Die erlaubten historischen Quellen belegen keinen Buhl-Formular-/Feld-/Indexvertrag für Fachjahr 2026. Es gibt daher weder erfundene Kennziffern noch einen als WISO bezeichneten neutralen Export. Benötigt werden die vom Koordinator separat beauftragten kontrollierten synthetischen Producerexporte: Programm-/Build-/Fachjahrnachweis, bytegleich archivierter Basisexport und pro Fachfeld genau kontrollierte Änderung mit dokumentierter Objekt-/Formular-/Indexbedeutung. Danach müssen die belegten Felder samt Originalevidenz in ein versioniertes Herstellerprofil und einen tatsächlichen Serializer aufgenommen werden. Die fehlende WISO-Steuer-Consumerinstallation ist **nicht** die Erklärung für diese lokale Lücke.
2. **Leasing-/Checkpoint-Hintergrundjobs fehlen für diese Exporte noch.** Die implementierten vollständigen Vorgänge sind synchron, atomar und wiederholbar; ein Prozessabbruch startet denselben Auftrag ohne halbes veröffentlichtes Ergebnis neu. Sie sind nicht als dauerhafte, ab einer Quellseite fortsetzbare Exportjobs am vorhandenen JobRunner angeschlossen. Deshalb ist die Anforderung „full export jobs“ noch nicht abgeschlossen.
3. Nativer DATEV-Beleglinkvertrag fehlt. Originale interne Links bleiben unverändert im Quellenbeleg; Feld 20 wird nicht unbelegt befüllt.
4. Externe DATEV-/Steuerberater-Zielimportabnahme: mehrere Konten/Jahre/Objekte, Cent-Summen, Soll/Haben, Einnahmen-/Ausgabenstornos, Umlaute, Datei-Aufteilung und tatsächliche Belegbezüge in der Zieloberfläche. Historische Formatfixtures sind dafür kein Ersatz.
5. WISO-Steuer-Windowsausgabe für **Fachjahr 2026** plus tatsächlicher Import und Feldvergleich ist zusätzlich externe Consumerabnahme. Mehrere Objekte, Aufteilungen, Erstattungen, Null-/Negativsummen und nur nachgewiesene AfA-Felder prüfen. Keine AfA-Automation zugesagt.
6. Native PG-Verbindungen/Lockwartezeiten, browserbasierte Prüfung bei 320/360/1440 Pixel und große Bestände gehören zu den separat koordinierten Gates. Sie wurden hier nicht ausgeführt. PostgreSQL-Restore ermittelt die Steuer-Schlüssel-IDs im Dump-Snapshot, hat aber noch keine angeschlossene semantische Steuerbelegprüfung mit Restore-Schlüsseln wie der SQLite-Pfad.

## Prüfungen und reproduzierbare Belege

Alle Backendläufe über den verlangten unveränderten Interpreter und `scripts/run_pro_matrix.py`, je Lauf eigener Label/Runtime. Kein gesamtes Backend-/Frontend-Suite-Gate, keine global installierten Pakete und keine neuen Abhängigkeiten. `frontend/node_modules` ist die isolierte Referenzkopie; **kein npm-ci-Nachweis**.

- `tax-port-first-memory-b200053d11ba405eb2d60ff0c52aafe0`: 62 bestanden, 2 Fehler (historisches, heute nicht vorhandenes `services.payments`), 1 SQL-spezifischer Skip. Zahlungsdoppelzählungstest danach auf tatsächliche `payment_allocations` angepasst, nicht durch erfundenes Altmodul ersetzt.
- `tax-port-retained-sql-0bd54e91892143efbebef23b79017b52`: 60 bestanden, 4 Fehler, 1 Skip. Der alte Barrier-Hook wartete innerhalb der jetzt geschützten Schreibtransaktion auf den zweiten Schreiber. Test startet die konkurrierenden Schreiber nun vor Sperreintritt; unveränderte Orakel: ein Ergebnis, identische Wiederholung oder 409, genau eine Jahresfassung.
- `tax-current-independent-memory-3c80a85644954f75b21b37400b2ab3cd`: 17 bestanden. Unabhängige aktuelle Money-/Byte-/Encoding-/CAS-/Korruptionsorakel, Memory und echte SQLite-Dateien.
- `tax-regression-current-memory-99be1079d12d4ea2870675c03c39b7ab`: 81 bestanden, 1 SQL-spezifischer Skip.
- `tax-migration-backup-sql-069184b3988b4fa990b33e818e97430a`: 2 bestanden, 1 Testfehler durch falsche Annahme zum Restore-Dateinamen. Aktueller Vertrag ist `immo_manager.db` im Restoreziel.
- `tax-restore-correct-path-sql-8914ae374ad341cf945d2afff2e9b1be`: 3 bestanden. Bestandsvergleich **aller** vorhandenen Tabellenzeilen vor/nach zugewiesener Migration, sichere Downgradeverweigerung, create_all-Adoption, Vollbackup/Restore mit Schlüsseln, Uploadoriginal und bytegleichem DATEV-ZIP sowie Korruptionsablehnung.
- `tax-sql-current-final-sql-c982fce6a115460fbcfccf8befe275d6`: 87 bestanden, 1 SQL-spezifischer Skip. Umfasst bestehende Porttests plus aktuelle HTTP-/Rechte-/Quellseitenfälle. Spätere Stornokontierungs-/Snapshotergänzungen sind separat zu prüfen.
- `tax-final-supplement-memory-07cd113ae70f4a758701c30e2c57c32e`: 30 bestanden. Unter anderem Stornogegenkonto, Abbruch bei zweitem verschlüsselten Exportblock, vollständiger Rollback und derselbe Wiederholungsauftrag, deterministischer neutraler Download, HTTP und Legacy-CSV-Kennzeichnung.
- Gezieltes mypy (`--platform linux --follow-imports=silent`), 14 neue Modelle/Services/Router: bestanden nach Korrektur einer Memory-/SQL-Variablenzuweisung. Gezieltes Ruff der neuen und angepassten Steuerdateien: bestanden.
- `artifacts/tax-frontend-tests.json`: 5 gezielte Komponententests bestanden, maxWorkers=1. Vollständige Quellseiten, verlorene Speicherantwort mit identischem Schlüssel, veränderte Quellen, Leserrolle und späte Antwort nach Sitzungswechsel. Erster UI-Lauf hatte einen fehlerhaften Mengenvergleich und machte zugleich die Darstellung negativer Kleinstbeträge sichtbar; Darstellung und unabhängiges Negativorakel wurden korrigiert. Gezieltes ESLint bestand.

- `tax-final-package-sql-81e47354ecd54ecc87fc01dac0146c98`: **99 bestanden, 1 SQL-spezifischer Skip**. Vollständiger fokussierter Steuerpaketlauf einschließlich Migration/Restore und gezielter Legacy-CSV-Regression, keine Gesamtsuite.
- `artifacts/tax-frontend-final.json`: 2 bestanden, 3 Fehler durch zeitüberschrittene asynchrone Testschritte. Anschließend wurden die gemockten React-Antworten im Test explizit mit `act` abgeglichen; keine Assertions, Rollen-/Sitzungsgrenzen oder Timeoutgrenzen gelockert.
- `artifacts/tax-frontend-react-flush.json`: **5/5 bestanden**, anschließend gezieltes ESLint erfolgreich. Enthält die aktuelle deutsche Seite einschließlich negativer Centbeträge, Objektfilter, privatem Eingabepuffer und aktuellen Formularen.
- `tax-crash-cleanup-final-memory-8a94947b33cb4766bff637a1d6f24a00`: **25 bestanden**. Neueste Ergänzung mit echter Hard-Exit-Spoolbereinigung sowie sämtlichen aktuellen unabhängigen Steuervertragsfällen in Memory und SQLite.
- `tax-final-migration-guards-sql-753edbf27ce749a8a69753ad78c7a94e`: **3 bestanden** nach Verschärfung der create_all-Adoption auf Primärschlüssel, eindeutige Auditbezüge, FKs, Spaltentypen/Nullbarkeit und Indizes.
- `tax-final-transfer-fence-memory-c78aa97aa4054429aa354c2362d6b6c4`: **2 bestanden** nach zusätzlicher Memory-Archiv-Sperre für den endgültigen Teilrestore. Prüft Memory und SQLite, einschließlich nach Vorbereitung entstandener Steuerprofile und nicht destruktivem Merge.
- Gezieltes mypy für die zusätzlichen Spool-/Sperrmodule ist ebenfalls erfolgreich. Die Linux-Typprüfung benötigte die tatsächlich plattformbezogene `sys.platform == 'win32'`-Verzweigung für `msvcrt`; keine Fehlerunterdrückung ergänzt.
- `tax-final-router-import-memory-80249a09366143d69ea1b00bd571ca72`: **1 bestanden** nach Ruff-Importsortierung der gemeinsamen Model-/Routerregistrierung. Importiert die tatsächliche Anwendung und prüft den erhaltenen neutralen Legacy-CSV-Vertrag.
- `artifacts/tax-frontend-reload-replay.json`: **5/5 bestanden**, gezieltes ESLint ebenfalls erfolgreich. Der verlorene Speicherantwort-Test ist zusätzlich verschärft: `beforeunload`, Unmount und neue Komponenteninstanz, wiederhergestellte Eingaben und derselbe Wiederholungsschlüssel. Das ist ein Komponenten-/Storage-Test, kein behaupteter echter Browsergate.

`input.json`, `result.json`, `junit.xml`, `pytest.log` in jedem Matrixverzeichnis enthalten Quellhashes, Ausgangscommit und tatsächliche Ergebnisse. Frühere Fehlerläufe bleiben Fehlerläufe und sind keine Prüfung späterer Änderungen. Die Zusatzläufe überschneiden sich in ihren Fällen; ihre Zahlen sind nicht als zusätzliche eindeutige Tests zur Paketmatrix zu addieren. Abschließendes `git diff --check` und gezieltes Ruff einschließlich gemeinsamer Integrationsdateien sind erfolgreich. Die teuren Paketläufe wurden nicht ohne fachlichen Anlass wiederholt.

## Integration

Vor Übernahme die genannten gemeinsamen Dateien mit anderen Paketen abgleichen. Neue Modelle/Services/Router und Frontendseite gemeinsam übernehmen, danach additive Migration samt Merge-Revision koordinieren. Keine zusätzlichen Runtimekonfigurationen, Pakete oder echten Anbieterzugänge erforderlich. Vor Anwenderupgrade Vollbackup einschließlich Schlüssel; ausschließlich in einer getrennten Kopie migrieren und Originale vergleichen. Dieses Paket ist wegen der oben ausdrücklich genannten Lücken **nicht als vollständiger WISO-/Job-/Zielimportabschluss** zu führen.
