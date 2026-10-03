# Paket C – tatsächliche native Browserabnahme

Eigener Checkout `work/billing-dispute-ui`, Branch `assist/billing-dispute-ui`,
03.10.2026. Vorcodeplan `c386438`, Quellenhandoff `ad7a93e`. Die vier geplanten
unterschiedlichen Fälle sind tatsächlich belegt: **drei PASS im gemeinsamen
Lauf plus ein korrigierter PASS im einzelnen Nachlauf**. Es wird kein erneuter
vollständig grüner Viererlauf nach den letzten lokalen Änderungen behauptet.

## Tatsächliche Basis und Isolation

Sauberes Root `84cfd9f` wurde über Dependency-Merge `6593106` übernommen; davor
sauberes `79ea761` über `3e13f1b`. Beide Merges sind bereits integrierte
Fremdquellen und sollen nicht als eigene Produktänderung zurück übernommen werden.
Der gemeinsame fachliche Lauf verwendete `5d85a45`, der letzte gezielte Lauf
unverändert `2c81a26`. Alle Sourceänderungen erfolgten zwischen beendeten Läufen.

Vorhandener Runner, tatsächlicher Produktionsbuild, frische eigene temporäre
SQLiteDB, vollständiges tatsächliches Alembichead bis k2, echter
`SQLAlchemyStore` mit `database_connected=true`, Edge, ein Worker, null Retries.
Freigegebener Pythonpfad unter `outputs/ImmoManager-Pro/.venv/Scripts/python.exe`.
Jeder Lauf besaß seinen eigenen Backendbaum/Port/Datenordner und beendete ihn
vollständig. Kein privater Preview, Nutzerdatenbestand, PGpublic-Schema,
Liveprovider oder parallel gestarteter App-/Buildprozess.

Domain beendete seine Memory/Visual/SQLite/PG-Prozesse ausdrücklich vor dem
Erstlauf. Zwischen mobilem Fehler und einzelnem Nachlauf nutzte Root seinen
angekündigten Container-Testslot; erst nach dessen Ende/erneuter Freigabe
startete der letzte Browser. Der schwere Slot ist wieder ausdrücklich frei;
keine eigenen Native-/Browser-/Buildprozesse oder Execsessions laufen mehr.

Diese Basis enthält die geprüfte echte C-Draftpolicy und Owner-/Pending-
Expirykorrektur. Domains spätere Utility-PDF-Quellen sind hier nicht übernommen;
die Browserfälle benutzen tatsächliche archivierte Dokumentoriginale und
ersetzen keine Utility-PDF-Route.

## Ehrliche Lauf- und Fehlerfolge

| Lauf / Source | Tatsächliches Ergebnis | Ursache und Folge |
| --- | --- | --- |
| `96928` / `d5c21ad` | vier Setup-FAIL, fachliche Fälle nicht erreicht | Eigener Helper nutzte irrtümlich `/auth/users/me`; tatsächliche Route ist `/auth/me`. SPA-Fallback gab HTML200. `5a023fa` korrigiert Route und prüft zusätzlich den echten JSON-Antworttyp. |
| `33238` / `5a023fa` | vier Zeilenselektor-FAIL | Tatsächliche native Fixtures, Finalisierung, Archive und Choice wurden erfolgreich angelegt. Der gemeinsame Helper suchte den nicht dargestellten Periodenlabel in der bestehenden Tabelle. `5d85a45` verwendet die tatsächlich gerenderte eindeutige Immobilienzelle und bestätigt anschließend die genaue Periodenüberschrift. |
| `22361` / `5d85a45` | drei PASS / ein FAIL, Playwrightanzeige 1,5 min | Fälle 1/2/3: 17,9 / 10,7 / 20,9 s. Fall 4 erfüllte fachliche Assertions einschließlich Originaldownload, scheiterte nach 35,9 s an tatsächlicher Seitenüberbreite bei 320; 1440/360 waren bestanden. |
| `25338` / `2c81a26` | **genau Fall 4 PASS**, Exit 0 | 33,3 s im Fall, Playwrightgesamt 35,8 s, keine Skips. Unveränderte Breitenassertion jetzt bei 1440/360/320 grün. Keine Wiederholung der drei grünen Fälle. |

## Vier tatsächliche fachliche Nachweise

1. **Originalversion und verlorener bestätigter Open.** 26 tatsächliche kleine
   Archiveversionen; ursprüngliche Version 1 auf zweiter 25er Historyseite,
   Positionsindex 0 und unverändertes Manifest. Einziges Fault-Injectionziel:
   echter Open-POST wurde mit `route.fetch()` nativ 201 bestätigt, danach nur
   seine Browserantwort abgebrochen. Echter Akten-/Journalbestand zeigte bereits
   genau ein Originalereignis. Tatsächlicher encryptedDraft blieb pending;
   Reload/Restore plus 850 ms behielten command_json/review_json exakt.
   Bewusster Retry behielt volle Nutzlast/UUID/Revision/Previewhash, erhielt
   denselben Receipt und erzeugte kein zweites Ereignis. Echter Draftcleanup.
2. **Echter konkurrierender Aktenkopf.** Native eigene Vorschau bei Revision 1,
   unabhängiger tatsächlicher Notizbefehl erzeugte Revision 2, ursprünglicher
   UI-POST erhielt echten Domain409. Grund/Datum/UUID/alte Revision erhalten;
   Vorschau blieb bis ausdrücklicher Standübernahme deaktiviert. Übernahme per
   Tastatur und neue Vorschau führten erst dann zu Revision 3. Keine erfundene
   neue Kennung. C besitzt keinen nativen 412-Pfad; bestehende numerische
   UI-/Hook412-Regressionsfälle bleiben getrennte Evidenz.
3. **Native Rechte- und Scopegrenze.** Eigener ausgewählter Manager mit echtem
   JWT; tatsächliche readonly-Änderung führte zu Draftprepare403 und blendete
   C-Form/Review aus, bevor ein Domainbefehl gesendet wurde. Wiederfreigabe
   erlaubte Restore des tatsächlich gespeicherten Reviews. Anschließender
   tatsächlicher Portfolioentzug verweigerte den vorbereiteten Originaldownload
   mit 404 und verbarg C-Originale. Native geschützte Periodenabfrage ebenfalls
   404; Admin-Bestandskontrolle bestätigte null Aktenbefehle. Keine gefälschte
   Auth-, Draft-, 403-/404- oder Receiptantwort. Der Hide-Nachweis betrifft den
   eigenen C-Workspace; der schon vorhandene Legacy-Abrechnungsbestand wird
   durch diesen Slice nicht als vollständig refaktoriert behauptet.
4. **Aktionen, Original und echte Korrekturlinie.** Notiz, Prüfung, Rücknahme,
   Wiederaufnahme, Abschluss und erneute Wiederaufnahme tatsächlich bestätigt.
   Exact Originalevent-GET, eigenständige Berichtigung mit dessen ID; früherer
   Grund/Datum unverändert. Reale spätere Abrechnungsrevision über tatsächliche
   Generate/Review/Finalizefolge; case-bound Choice und Einzelstatement aus
   deren tatsächlicher späterer Periode, native Vorschau/correction_link mit
   Originalhash. Belegte frühere Person bleibt trotz aktueller Namensänderung
   aus dem eingefrorenen Original. 27 echte Ereignisse: Chronikseiten 25 und 2,
   Rückweg zur ersten Seite. Browserdownload stimmt nach Dateiname, 87 Bytes,
   vollständigen Bytes und SHA256 mit echtem Archivmanifest überein.
   Finanz-/Zustellfelder bleiben durch die Journalaktionen unverändert.

## Tatsächlich gesehene Bilder und lokale Korrekturen

Alle 24 akzeptierten Proofbilder wurden mit dem Bildwerkzeug tatsächlich
angesehen: vier Ansichtsgruppen × 1440/360/320 × Gesamtseite/Viewport. Dazu das
konkrete frühere 320px-Fehlerbild. Gruppen: früher Open-Review, Scopehide,
abschließend korrigierter FrozenParty-Review und aktuelle Akte/Chronik.
Die lesbaren Viewports ergänzen die sehr langen Gesamtbilder; interne Tabellen
dürfen scrollen, der Seitenkörper bleibt in der tatsächlichen Breite.

Das Fehlerbild belegte einen eigenen Aktenlistenbutton mit langem Statement-
UUID und übernommenem globalem nowrap. `7b95251` lässt ausschließlich eigene
C-Buttons bei schmalen Screens innerhalb ihrer Breite umbrechen. Gemeinsame
DataTable/Layoutquellen und die Breitenassertion wurden nicht verändert.

Die erste Bildsichtung entdeckte zusätzlich einen wirklichen Anzeigefehler:
native Previewbinding liefert party_binding/original_snapshot.original_party,
aber kein nur am Case-GET ergänztes party_binding_note. Der eigene Fallback
zeigte deshalb oberhalb der richtig eingefrorenen Person fälschlich einen
historischen Fehlhinweis. `2c81a26` verwendet das bereits validierte Original
für die Caption; bei Legacyquellen bleibt ihre tatsächliche Grenze sichtbar.
Neue Bilder und native Vorschauen im einzelnen Fall 4 bestätigen die Korrektur.
Die früheren Reviewbilder bleiben als Fehlerbeleg erhalten und werden nicht
nachträglich als korrigierte Anzeige ausgegeben. Zwei tatsächliche Paintframes
vor Bildern vermeiden die zuvor kurzzeitig unvollständig gezeichnete Ansicht.

Gezielter neuer gemeinsamer Hook/UI-Fall für die native Shape ohne Case-Note:
**ein PASS**, elf andere Fälle durch `-t` bewusst nicht ausgewählt; 32,62 s
Gesamtumgebung, 783 ms Test. Scoped ESLint und diffcheck grün. Root berichtete
vor diesem eigenen Nativegate separat 54 Controller/Form/Statements-PASS und
22 Model/Read/OriginalChoice-PASS; diese werden nicht als eigener Nachlauf gezählt.

## Saubere Übernahme und Artefakte

Nach der bereits übernommenen Quelle zusätzlich in Reihenfolge:

- `d5c21ad`: lesbare Viewportbilder zusätzlich zur Gesamtseite.
- `5a023fa`: tatsächlicher Current-user-Pfad und JSON-Antworttyp im eigenen Helper.
- `5d85a45`: tatsächliche Tabellenzeile und exakte Periodendetailüberschrift.
- `7b95251`: ausschließlich lokaler C-Buttonumbruch.
- `2c81a26`: FrozenParty-Caption, gezielter Regressionstest, native Captionproofs.

Drei-PASS-Lauf samt unveränderten Bildern und Backendlog:
`work/billing-dispute-ui-three-pass-artifacts/`. Frühe Setup-/Selektorlogs:
`work/billing-dispute-ui-initial-browser.log` und
`work/billing-dispute-ui-row-selector-browser.log`. Einzelner letzter PASS:
`work/billing-dispute-ui/frontend/test-results/` und dessen Playwrightreport.
JSON-Request-/Receiptproofs werden vom vorhandenen HTMLreport als Attachments
eingebettet; die früheren erfolgreichen Browserassertions und Backendlogs
bleiben die belegten Nachweise. Originalbytes und Bilder liegen lokal getrennt
von Produktquellen; kein sensitives Nutzeroriginal.

Offen bleiben Root-Übernahme/Komposition, spätere Utility-PDF-Gesamtkomposition,
weitere Planpakete und vollständige A–L-/Releaseabnahme. Kein Gesamtabschluss
oder Live-Verfügbarkeitsclaim durch diesen eigenen C-Browserhandoff.
