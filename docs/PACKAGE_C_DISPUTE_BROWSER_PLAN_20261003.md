# Paket C – eigener Browser-Vorcodeplan, 03.10.2026

Dieser Plan ist ein separater Commit **vor** neuen Browserquellen. Der eigene
UI-Handoff ist `05c0a2c`; Root behält Billingwiring, spezielle Draftpolicy,
Backend-/Startup-/Recoverykomposition und die Freigabe schwerer Gates.
Während PlatformCommonLegacy läuft: nur Quellen-/Planarbeit, kein Browser,
Python-/PG-/Nativeprozess und kein zweiter Browserstart.

## Tatsächliche Voraussetzungen

Ausgeführt wird später genau ein eigener koordinierter Lauf über den vorhandenen
`frontend/e2e/run.mjs` und `playwright.config.mjs`: Produktionsbuild, frische
temporäre SQLiteDB, tatsächliches vollständiges Alembichead, echte
`SQLAlchemyStore`-Health mit `database_connected=true`, ein Worker, keine Retries.
Der Runner besitzt seine eigenen Ports/Daten und beendet nur seinen eigenen
Backendbaum. Keine PrivatanwenderDB, kein öffentlicher PGschema, keine Liveprovider.

`IMMO_E2E_PYTHON` bleibt
`C:/Users/matth/Documents/Codex/2026-10-01/wi/outputs/ImmoManager-Pro/.venv/Scripts/python.exe`,
`IMMO_E2E_CHANNEL=msedge`. Root meldet vorher eine saubere integrierte Basis mit
wirklicher StatementChoicequelle, pending-sicherem Sharedhook, bestandenem
specialDraftpolicy-Nachweis und tatsächlich verdrahtetem Workspace. Keine
uncommittete Rootquelle kopieren. Eigene neue `billing-disputes.pw.mjs` und
gegebenenfalls ein rein synthetischer eigener Fixturehelper; shared Runner,
Billingbackend und SharedDraftquellen bleiben unangetastet.

Auth erfolgt über den echten isolierten Demologin oder echte neu angelegte
Testaccounts und reale JWTs. `demoFixtures.mjs` setzt die tatsächlichen
Accountpräferenzen vor React auf Deutsch. Keine gefälschte Authantwort und
keine künstliche `/auth/users/me/form-drafts`-Antwort. Dieser Endpunkt wird in
jedem Reload-/Pendingnachweis über die echte native Datenhaltung benutzt.

## Synthetische native Originale

Eigene UUID-Präfixe/Objekte: Portfolio, Immobilie, konkrete Einheiten/Mietparteien/
Verträge, echte Abrechnungsperiode und Kosten. Finalisierung über vorhandene
`generate` → `submit-review` → `finalize`-Routen. Tatsächlich geleistete
synthetische Vorauszahlungen gegebenenfalls über den bereits bewährten
`billingPaidFixture.mjs`, keine erfundenen Advancefelder in fertigen Statements.
Keine internen DBpatches von Hashes/Revisionen/Originalen oder umgangene Trigger.
Im Basisszenario wenige vollständige Statements; NativeChoice-Paging über die
25er Grenze ist bereits Domain-HTTPgate, kein künstlicher Bestandsdeckel.

Anlage: echte `/files/upload`-Bytes und `/documents`-Metadata mit tatsächlicher
Objekt-/Vertrags-/Einheitenzuordnung. Original über `version-source` prüfen und
`versions/archive-original` mit tatsächlichem ETag, Hash, Head, UUID, Kommentar
und `confirmed=true` veröffentlichen. Bei der 25er Versionsgrenze 26 kleine
echte Versionen über bestehende multipart `POST /documents/{id}/versions`,
je aktuellem ETag/Head und eigenem idempotenten Veröffentlichungsbefehl. Kleine
synthetische Texte, keine Nutzerdateien. Genau die gespeicherte archivierte
Version wird später durch den C-Picker ausgewählt und im Journal manifestiert.

## Vier zielgerichtete Browserfälle

1. **OriginalVersionPick und wirklich verlorener erfolgreicher Open-POST.**
   Finale Originalquelle über die reale bounded Statementwahl und exact GET
   prüfen/übernehmen; tatsächliche Positionsindizes und archivierte Version
   auf der zweiten 25er Historyseite wählen. Grund/Eingang vollständig prüfen.
   C-Preview muss echte Manifestgröße/Hash/Originalname zurückliefern. Einziger
   Faultinjektionspunkt: den tatsächlichen Open-POST mit `route.fetch()` wirklich
   in SQLite bestätigen (201/Receipt), danach nur dessen Browserantwort
   verlieren lassen. Requestbody vor/bei Verlust aufzeichnen. Native Aktenliste
   und Originaljournal zeigen bereits eine Akte/ein Ereignis, keine angenommene
   Speicherung. Reload, dieselbe Periode öffnen, echten encryptedDraft restore.
   Nach mindestens 850 ms tatsächlicher DraftGET weiterhin pending; gesperrte
   Eingaben, keine neue UUID/Vorschau/Discard/Resume. Bewusst exactRetry:
   vollständige Nutzlast einschließlich UUID/Revision/Previewhash gleich,
   gleicher Receipt/Event/Case, weiterhin genau ein Originalereignis, danach
   echter Draftcleanup. Kein Fake201 und kein im Browser erfundener Draft.

2. **Echter konkurrierender Aktenbefehl und Originalstandübernahme.**
   Bestehende Akte öffnen, Notiz eingeben und bei Revision N tatsächlich
   previewen. Ein unabhängig bestätigter echter APIbefehl mit neuer UUID und
   eigener Vorschau erzeugt N+1. Der UIbefehl behält ursprüngliche UUID,
   Eingaben und Revision N. Tatsächliche Antwort/Route protokollieren; kein
   automatisch aktualisierter erwarteter Stand. Aktuelle Akte anschließend
   lesen und ausdrücklich übernehmen, neue Vorschau prüfen. Tatsächliches
   neues Ereignis darf nur aus dieser ausdrücklichen Folge entstehen.
   Die bestehende Domain liefert dafür **409**, nicht 412. Wenn die neue
   specialDraftpolicy einen stale prepare bereits 409 ablehnt, wird dieser
   reale Pfad transparent beschrieben; kein Domain409 behauptet, falls noch
   kein DomainPOST ausgeführt wurde. Prüfung insbesondere, dass gespeicherte
   alte Review-/Commandenvelopes zum idempotenten Replay zulässig bleiben.

3. **Wirklicher Grant-/Scopeentzug mit numerischem Fehler und Hide.**
   Native zweite Sitzung als tatsächlich berechtigter ausgewählter Testmanager
   zeigt eine geprüfte Vorschau. Über echten Adminaccount wird derselbe
   Account serverseitig readonly oder einer anderen Portfoliomenge zugeordnet.
   Bestehenden Actor/JWT in der offenen Sitzung behalten; gespeicherten
   Draftprepare beziehungsweise protected read erneut auslösen. Tatsächlicher
   403 nach Schreibgrantentzug beziehungsweise authentischer 404 nach
   verborgenem Portfolio wird getrennt protokolliert. Original-/Form-/Review-
   Inhalte verschwinden, kein Domainbefehl nach verweigertem prepare. APIproof
   bestätigt die tatsächliche Bestandssicherheit. Kein `route.fulfill(403)` als
   Nativebeweis. Rascher Periodenwechsel/verspätete Antwort bleibt außerhalb
   ihres ursprünglichen UI-Kontexts; vorhandene Actor-/Grantunitgates ergänzen
   den Browsernachweis, ersetzen ihn aber nicht.

4. **Echte Aktenaktionen, Originalevent, Korrektur und Originaldownload.**
   Native Notiz/Prüfung/Rücknahme/Wiederaufnahme/Abschluss anhand wirklichen
   Zustands prüfen; Timeline/Originalevent bleiben append-only. Berichtigung
   nach exact Originalevent-GET mit dessen ID als `corrects_event_id`, keine
   Mutation des alten Grunds/Datums/Manifests. Echte Korrektur über vorhandenes
   `POST /billing/periods/{id}/revisions`, Generate/Review/Finalize; ausgewähltes
   Statement gehört zur tatsächlichen späteren Periode und belegten Quellenkette.
   Case-bound Choice + Einzelstatementdetail, Domainpreview und bestätigter
   correction_link erhalten ID/Revision/Hash; keine bloß nachträglich gesetzte
   FK. Originalversionsdownload im Browser speichern; Bytes, Länge, SHA256,
   Dateiname gegen tatsächliches Manifest/ursprüngliche synthetische Bytes.
   Keine automatische Forderung/Erstattung/Zustellung durch Journalaktionen;
   echte finanzielle Ursprungsfelder und Statuspfade separat vergleichen.

## Responsive, Tastatur und ehrliche Gates

In diesem einen Lauf bei 1440/360/320 Original-/Eingabe-/Reviewansichten
fotografieren; `documentElement.scrollWidth<=innerWidth`, native Labels und
Tastaturaktionen/Fokus prüfen. Eigene horizontale Positionstabelle darf intern
scrollen, der Seitenkörper bleibt begrenzt. Screenshots anschließend tatsächlich
ansehen. Konsolenfehler, fehlende Originalquellen, Lese503 und gefälschte
Leerstände sind Gatefehler. Bounded Requests samt page_size/limit/Selected und
echte Manifest-/Receipt-/Draftproofs als knappe Testartefakte protokollieren.

412 wird auf den tatsächlich vorhandenen C-Routen nicht erzeugt:
`billing_disputes.conflict()` ist ausdrücklich 409. Die UI unterstützt numerische
412 einschließlich Eingabenerhalt bereits durch echte Hook-/UIcontroller mit
synthetischem HTTPfehler; daraus wird kein Native412-Browserpass. Eine spätere
wirkliche Vertragsänderung muss Root erst separat autorisieren/belegen.

Dieser Plan hat noch keine Browserfälle ausgeführt. Slot, Nativebasis und Wiring
sind Voraussetzungen; ein laufender Fremdgate wird nicht parallelisiert. Nach
Sourceimplementierung zunächst nur Syntax-/Collectionprüfung ohne App-/DBstart;
später genau ein abgestimmter Browserlauf, weitere Nachläufe ausschließlich für
konkrete neue Fehler. Handoff nennt tatsächliche Fälle/Zeit/Skips und Grenzen,
kein Gesamtabschluss der Roadmap A–L.
