# Paket C – Browserquellen und kleine Abrechnungsanbindung

Stand 03.10.2026, eigener Checkout `work/billing-dispute-ui`, Branch
`assist/billing-dispute-ui`. Vorcodeplan `c386438` bleibt verbindlich. Dies ist
ein Quellenhandoff; es wurden noch keine nativen Browserfälle ausgeführt.

## Saubere Basis und getrennte Übernahme

Eigene UI-Quellen und bestehende Nachweise sind in
`PACKAGE_C_DISPUTE_UI_HANDOFF_20261003.md` beschrieben. Die ausschließlich
saubere Rootquelle `79ea761` ist als Dependency-Merge `3e13f1b` in den eigenen
Checkout übernommen. Dieser Merge enthält bereits integrierte Fremdquellen;
Root soll ihn nicht erneut als eigenen Produktpatch übernehmen.

Root besitzt weiterhin Backendpolicy, CommonDraft, Recovery, Registry und CI.
Keine uncommitteten Rootquellen wurden kopiert. Root meldet zum sauberen
specialDraft-Paket 15 echte Fälle (je fünf Memory, migrierte SQLite und PG) plus
sechs gewöhnliche Draftfälle; das ist getrennte Backend-Evidenz, kein eigener
Browsernachweis. Der zusätzlich angekündigte Core-DELETE-Nachweis nach
vollständigem Grantentzug/readonly und dessen saubere Übernahme stehen vor
unserem späteren Browsergate. Der hier vorbereitete Scopefall versucht keine
nachträgliche Entschlüsselung oder Löschung des entzogenen Drafts.

## Kleine Statements-Anbindung

- `33cd82b`: eigener abgegrenzter `Statements.jsx`-Patch und seine Grenztests.
  Für `finalized`, `delivered`, `disputed`, `corrected` wird der tatsächliche
  `BillingDisputeWorkspace` in bestehende Periodendetails eingebunden. Auch
  berechtigte readonly-Akteure erhalten dessen geschützte Leseansichten.
  Der alte reason-only-Widerspruchsprompt, sein Handler, Zustand, Button und
  unreviewed POST sind vollständig entfernt. Der echte Korrekturprompt bleibt.
- `f3a2c1c`: ausschließlich die readonly-Testaktion korrekt abwarten. Der
  DataTable-Testdouble bildet nun den tatsächlich vorhandenen `onRowClick` ab;
  die gemeinsame DataTable-Quelle wurde nicht verändert.

Ausgeführt: zuerst 26 PASS / ein neuer readonly-Testdouble-Fall FAIL; danach
der korrigierte readonly-Fall einzeln PASS ohne React-act-Warnung. Damit sind
27 unterschiedliche vorhandene/neue Statementsfälle belegt, nicht als ein
einziger vollständig grüner 27er Lauf behauptet. Der bestehende achtfache
Legacy-Datenlader und sonstige B-Inventararbeit bleiben außerhalb dieses Slice.

## Vier vorbereitete echte Browserfälle

Reiner Browserquellencommit: `dabc05a` (zwei neue eigene Dateien).

`frontend/e2e/billingDisputeFixture.mjs` erzeugt ausschließlich eigene UUID-
Objekte, echte synthetische gezahlte Vorauszahlungen und finalisierte Quellen
über tatsächliche HTTP-Routen. Reale Dateiarchive werden ausdrücklich mit
ETag/Head/Hash und Zustimmung veröffentlicht. Keine internen DBpatches,
gefälschte Auth-/Draft-/Previewantworten oder Load-all-Auswahlhilfen.

`frontend/e2e/billing-disputes.pw.mjs` enthält genau vier Fälle:

1. Reale zweite 25er Versionenseite, ursprüngliche archivierte Anlage,
   Positionsbezug und tatsächlicher bestätigter Open-POST mit verlorener
   Antwort. Nur nach echtem `route.fetch()`-201 wird die Übermittlung
   unterbrochen. Native Akte/Journal/Draft beweisen Speicherung; Reload und
   mindestens 850 ms erhalten pending und unveränderte JSON-Strings.
   Bewusster Replay sendet dieselbe UUID/Revision/Previewhash/Nutzlast, erhält
   denselben Receipt und erzeugt genau ein Originalereignis. Echter Draftcleanup.
2. Echter paralleler Notizbefehl erhöht den Kopfstand. Der UI-POST erhält
   tatsächlichen Domain409; Grund/Datum/UUID/alte erwartete Revision bleiben.
   Erst ausdrückliche aktuelle Standübernahme per Tastatur und neue Vorschau
   ermöglichen den folgenden bestätigten Befehl. Keine native 412-Behauptung.
3. Eigener wirklicher Manageraccount mit realem JWT. Tatsächliche readonly-
   Herabstufung verursacht Draftprepare403 und Hide vor einem Domainwrite.
   Nach Wiederfreigabe wird der tatsächlich gespeicherte Review wiederhergestellt;
   tatsächlicher Portfolioentzug verweigert den bereits vorbereiteten
   Originaldownload404. Native Bestandskontrolle beweist null Aktenbefehle.
4. Notiz/Prüfung/Rücknahme/Wiederaufnahme/Abschluss, exact Originalevent-
   Berichtigung und reale spätere Abrechnungsrevision mit case-bound Choice,
   Einzelstatement-GET, Preview und correction_link. Originalereignis und
   belegte frühere Person bleiben erhalten trotz aktueller Namensänderung.
   27 echte Ereignisse beweisen beide Chronikseiten; Originaldownload wird
   nach Dateiname/Bytes/Länge/SHA256 geprüft. Journalaktionen ändern die
   geprüften Finanz-/Zustellfelder nicht automatisch.

Die Fälle fotografieren tatsächliche Review-/Scope-/Originalansichten bei
1440/360/320 und prüfen die Seitenbreite. Die Bilder müssen nach einem wirklichen
Lauf noch angesehen werden; es existiert bislang kein visueller PASS.

## Tatsächlich ausgeführte kleine Quellenchecks

- Node-Syntaxprüfung beider neuer Dateien: PASS.
- ESLint genau dieser beiden Dateien: PASS.
- Playwright `--list` mit ausschließlich lokaler URL-Umgebungsvariable:
  **vier Tests in einer Datei erkannt**, Exit 0. Kein App-/DB-/Browserstart.

Nach sauberem Core-Nachweis und ausdrücklicher Slotfreigabe: genau ein Lauf
über den bestehenden Runner mit `npm run test:e2e -- e2e/billing-disputes.pw.mjs`,
`IMMO_E2E_CHANNEL=msedge` und dem bereits freigegebenen Pythonpfad. Der Runner
besitzt Produktionsbuild, eigene temporäre SQLiteDB, tatsächliches Alembichead,
SQLAlchemy-Health, einen Browserworker und null Retries. Keine gleichzeitigen
Appstarts mit Root, Domain oder externer Finanz-QA. Weitere Nachläufe nur nach
konkreten neuen Fehlern und erneuter Abstimmung.

Offen: tatsächliche Browserausführung, Screenshotprüfung, gemeinsame Root-
Komposition und Freigabe. Kein Live-/Gesamtabschluss von Paket C oder Roadmap A–L.
