# Wohnungsgeberbestätigung – Frontend-Plan und Handoff

Stand: 02.10.2026  
Branch: `assist/housing-confirmation-ui`  
Worktree: `C:\Users\matth\Documents\Codex\2026-10-01\wi\work\housing-confirmation-ui`  
Basis: `e83790cd2731ec3ab62a5a38efefeb9367a46093`

Dieser UI-Plan wurde **vor Sourceänderungen** erstellt. Maßgeblich ist
`docs/WOHNUNGSGEBERBESTAETIGUNG_PLAN_20261002.md`.

## Ownership und Grenzen

Frontend-Ownership dieses Branches:

- neue Housing-Confirmation-Komponente,
- eigener API-/DTO-Client **erst nach realem Backend-Handoff**,
- eigene CSS- und DE/EN/ES-Texte,
- minimale Einstiegspunkte in `Contracts.jsx` bzw. `ContractLifecycle.jsx`,
- minimaler Einzugseinstieg in `TenancyWorkflows.jsx` / `TenancyChangeFile.jsx`,
- gezielte UI-/Command-/Scope-/Unknown-Reply-Tests.

Nicht in diesem Branch:

- Backend, Schema, Migrationen oder DocumentVersion-Originalerzeugung,
- Root-E2E/Recovery/PDF-QA,
- globales Layout oder `index.css`,
- Auth-/History-Architekturänderungen,
- öffentlicher PDF-Link, Portalübertragung oder Behördenversand,
- automatische Erledigung eines Mieterwechsel-Nachweisschritts,
- Persistenz personenbezogener Entwürfe in `localStorage`.

## Tatsächlich geprüfte vorhandene UI-Patterns

### Vertrags-Einstieg

`Contracts.jsx` öffnet für einen konkreten Vertrag bereits `ContractLifecycle`.
Der Lifecycle-Dialog ist deshalb der kleinste fachlich passende Vertrags-Einstieg.
Die Tabellen-/Cursorarchitektur der Vertragsseite bleibt unangetastet.

`ContractLifecycle.jsx` besitzt bereits:

- Actor-Key aus User-ID, Rolle, Write-Permissions und Portfolio-Grants,
- render-/instance-gebundene private Zustände,
- Request-Abort über eigene Controller-Sets,
- 401/403/404-Forget-Logik,
- Focus-Trap, Escape, Overlay-Close und Rückkehr zum auslösenden Button,
- verständliche Unknown-/Conflict-/Reload-Patterns.

Der Housing-Einstieg soll diese Modalhülle nicht duplizieren. Bevorzugt wird eine
kleine zusätzliche Lifecycle-Aktion, die ein eigenständiges Housing-Dialogmodul
öffnet und den ursprünglichen Opener für Focus-Rückkehr erhält.

### Einzug/Mieterwechsel

`TenancyWorkflows.jsx` und `TenancyChangeFile.jsx` sind bereits modular.
Der Housing-Einstieg gehört nur zu Einzugsfällen:

- `move_in` und `turnover` mit `next_contract_id`,
- kein Einstieg aus reinem `move_out`,
- der Vertrag wird ausdrücklich als neuer/einziehender Vertrag gebunden,
- tatsächliches Einzugsdatum bleibt ein eigenes Housing-Feld und wird **nicht**
  aus Übergabe oder Vertragsbeginn übernommen.

Das bestehende Evidence-System darf ein später gespeichertes
`housing_confirmation`-DocumentVersion-Original normal verknüpfen. Die
Housing-Komponente ruft aber **keine** Workflow-Step-Completion automatisch auf.

### PDF/Blob

`useProtectedFile.js` lädt geschützte Dateien per authentifiziertem Blob,
prüft PDF-/Bild-Magic-Bytes, erzeugt/revoziert Object-URLs und bricht bei
Referenzwechseln laufende Requests ab.

Für Housing soll kein öffentlicher URL erzeugt oder behauptet werden. Nach
Backendvertrag wird entweder:

1. der vorhandene Document-/Version-Downloadpfad verwendet, oder
2. ein expliziter geschützter Housing-PDF-Downloadpfad des Backends verwendet,

aber ausschließlich so, wie es der Backend-Handoff tatsächlich dokumentiert.

### Modal/Fokus/Close

`ContractLifecycle` und `FormModal` zeigen die etablierten Regeln:

- erster erreichbarer Control erhält Fokus,
- Tab bleibt im Modal,
- Escape schließt nur wenn nicht busy,
- Fokus kehrt zum Auslöser zurück,
- Overlay-Close nur bei sicherem Zustand,
- laufende Requests werden beim Unmount abgebrochen.

Housing benötigt zusätzlich eine **eigene Close-Warnung bei personenbezogenen
ungespeicherten Änderungen**. Diese wird nicht über die generische
FormDraft/localStorage-Infrastruktur implementiert.

## Geplanter Housing-UI-Zustand

Die Fachkomponente bleibt während des Dialoglebens gemountet. Privater Zustand:

- frisch autorisierte Source-Daten zum exakten Vertrag,
- Formularwerte,
- explizit hinzugefügte Personennamen,
- Vorschau/Review,
- gespeicherte Bestätigungen/Korrekturen,
- eingefrorener Unknown-Success-Command,
- Requestcontroller,
- aktuelle Actor-/Portfolio-/Contract-Bindung.

Jede Änderung an fachlichen Eingaben entwertet die Vorschau. Folgende Änderungen
dürfen nie still eine alte Vorschau wiederverwenden:

- Wohnungsgebername/-anschrift,
- Eigentümergleichheit/Eigentümername,
- tatsächliches Einzugsdatum,
- Ausstellungsdatum,
- Wohnungsanschrift/Wohnungsbezeichnung,
- ausstellende Person/Rolle,
- Personenliste,
- Bestätigungen zur tatsächlichen Belegung und Ausstellungsbefugnis,
- Korrekturbezug.

## Geplante Formularabschnitte

### 1. Wohnung

- natürliche Objekt-/Einheits-/Vertragsnamen aus der autorisierten Source,
- vollständige Wohnungsanschrift,
- optionale Wohnungsbezeichnung,
- tatsächliches Einzugsdatum als eigenes Pflichtfeld,
- Vertragsbeginn/Übergabe nur als **gekennzeichnete Referenzinformation**, niemals
  als automatisch übernommenes tatsächliches Einzugsdatum.

### 2. Wohnungsgeber

- Name,
- Anschrift,
- keine geratenen Werte bei fehlender Quelle.

### 3. Eigentümer

- explizite Auswahl „Wohnungsgeber ist Eigentümer“,
- bei Abweichung Eigentümername als Pflichtfeld,
- keine automatische Gleichsetzung ohne bewusste Auswahl.

### 4. Einziehende Personen

- geordnete, nicht leere Liste vollständiger Namen,
- beliebig viele Zeilen ohne UI-Hardcap,
- Hinzufügen/Entfernen per Tastatur erreichbar,
- Hauptmietername nur als deutlich gekennzeichneter Vorschlag,
- Übernahme ausschließlich durch explizite Benutzeraktion,
- Namen werden nicht in Vor-/Nachname zerlegt.

### 5. Ausstellung

- Ausstellungsdatum,
- ausstellende Person,
- Rolle `Wohnungsgeber` oder `beauftragte Person`,
- zwei explizite Bestätigungen:
  - tatsächliche Belegung/Einzug ist geprüft,
  - ausstellende Person ist zur Ausstellung befugt.

## Vorschau, Freigabe, Historie und Korrektur

Geplanter Ablauf:

1. Source frisch laden.
2. Formular aus erlaubten Source-Vorschlägen vorbereiten.
3. Benutzer ergänzt/prüft alle Fachangaben.
4. Zustandsfreie Servervorschau anfordern.
5. Vorschau klar als **vorläufig** anzeigen; PDF-Preview darf nicht als gespeicherter
   Behördenbeleg bezeichnet werden.
6. Jede Eingabeänderung verwirft die Vorschau.
7. Benutzer bestätigt tatsächliche Belegung und Ausstellungsbefugnis ausdrücklich.
8. Exakt die geprüfte Fassung speichern/freigeben.
9. Gespeichertes unveränderliches Original per geschütztem Download öffnen.
10. Historische Bestätigungen mit Datum und Korrekturbezug wiederfinden.
11. Korrektur startet eine neue Fassung mit explizitem Bezug; Altbeleg bleibt sichtbar.

Ein gespeicherter Beleg ist kein Nachweis einer Behördenübertragung und keine
elektronische Unterschrift.

## Unknown Success, Scope und private Daten

Wie beim ausgereiften Mieterwechsel:

- Netzwerkfehler/5xx -> exakt eingefrorener Command bleibt wiederholbar,
- keine stille Neuberechnung von Hash, Source-Revisionen oder Formularwerten,
- 409/412 -> bewusst neu prüfen, keine stille Replay-Aktualisierung,
- 401/403/404 -> private Source, Formularanzeige, Preview und Retry sofort vergessen,
- User-/Role-/Portfolio-/Contract-ID-Wechsel -> alter privater Inhalt bereits
  **render-synchron neutral**, bevor der neue Effect läuft,
- alle Requests der alten Bindung werden abgebrochen.

Keine Namens- oder Formulardaten landen in `localStorage`.

## Backendvertrag – bewusst noch offen

Zum Zeitpunkt dieses Plan-Commits existiert
`work\housing-confirmation-backend\docs\WOHNUNGSGEBERBESTAETIGUNG_BACKEND_HANDOFF.md`
noch nicht.

Daher werden in diesem Plan **keine endgültigen Endpointnamen oder Responseformen
erfunden**. Der finale API-Client wird erst geschrieben, nachdem der echte Handoff
gelesen und gegen die dortige Typen-/Router-Source geprüft wurde.

Vor finalem Clientcode werden mindestens abgeglichen:

- Source-DTO und Source-Revisionen,
- Preview-Request/-Response und Hashfelder,
- Save/Publish-Command inklusive Idempotenz/CAS,
- Liste/History/Korrektur,
- PDF-/Originaldownload,
- Actions/Rechte,
- Cursor-/Paginationformen,
- Fehler-/Unknown-Success-Semantik.

## Mock-/Testkonzept bis zum Backend-Handoff

Noch ohne erfundene HTTP-Pfade können rein fachliche UI-Komponenten und Adapter-
Grenzen getestet werden:

- 2+ Personen sowie 40+ Namen ohne UI-Hardcap,
- Hauptmieter-Vorschlag wird nicht automatisch Person,
- tatsächlicher Einzug bleibt unabhängig von Vertrag/Übergabe,
- Eigentümer abweichend / gleich,
- Preview invalidiert bei jeder relevanten Änderung,
- Close-Warnung bei Dirty-Daten,
- Unknown-Command bleibt byte-/objektgleich für Exact Retry,
- Actor-/Role-/Portfolio-/Contract-Wechsel neutralisiert private Anzeige render-synchron,
- 401/403/404 forget,
- Request-Abort,
- Korrekturbezug bleibt explizit,
- 320/360/1440 ohne horizontales Überlaufen,
- Focus-Trap, Escape und Rückkehr zum Auslöser.

Nach Backend-Handoff kommen feldgenaue API-Vertragstests hinzu.

## Geplante minimale Integrationspunkte

1. **ContractLifecycle**  
   Kleine Aktion „Wohnungsgeberbestätigung“ für den aktuell gebundenen Vertrag;
   keine Änderung der Vertragslisten-/Lifecycle-API.

2. **TenancyChangeFile**  
   Nur bei `move_in|turnover` und vorhandenem `next_contract_id` ein
   „Wohnungsgeberbestätigung vorbereiten/öffnen“-Einstieg. Keine automatische
   Step-Completion.

3. **EvidenceLinkDialog / bestehende Dokumentauswahl**  
   Kein Sonderpfad nötig, sofern der Backendbeleg als reguläres
   `housing_confirmation`-Document/DocumentVersion im bestehenden Dokumentbestand
   erscheint. Der gespeicherte Originalbeleg kann dann wie jedes andere
   `document_version` verknüpft werden.

## Ausstehender externer Blocker

Vor finalem API-/Integrationcode: echten Backend-Handoff lesen und eventuelle
Frontendabhängigkeiten/Lücken hier dokumentieren.

## Endpointfreie UI-Basis implementiert

Nach dem Plan-Commit wurde bewusst noch **ohne Backend-URLs/DTO-Annahmen** eine
adapterbasierte Fachbasis umgesetzt:

- `HousingConfirmationDialog.jsx`
- `HousingConfirmation.css`
- `housingConfirmationModel.js`
- `housingConfirmationText.js`
- `useHousingConfirmationCommand.js`

Der Dialog erwartet ein internes Service-Interface. Dieses Interface ist keine
Behauptung über Backend-Routen; die spätere `housingConfirmationApi.js`-Schicht
muss nach dem Backend-Handoff die echten DTOs auf dieses View-Modell abbilden.

Bereits implementiert und geprüft:

- natürliche Vertrags-/Objekt-/Einheitsanzeige aus autorisierter Source,
- tatsächlicher Einzug bleibt leer und unabhängig von Vertragsbeginn/Übergabe,
- Hauptmieter erscheint nur als Vorschlag und wird erst per Klick ergänzt,
- Personenliste ohne UI-Hardcap; gleichnamige tatsächliche Personen bleiben erlaubt,
- Wohnungsgeber/Eigentümer/Ausstellung als getrennte kompakte Abschnitte,
- explizite Bestätigung tatsächlicher Belegung und Ausstellungsbefugnis,
- Preview-Entwertung bei jeder Formularänderung,
- Historie/Korrektur als adapterbasierter UI-Pfad,
- kein Behördenversand-/Signaturversprechen,
- Dirty-Close-Warnung ohne lokale Persistenz,
- eigener Focus-Trap/Escape/Opener-Focus,
- Actor-/Portfolio-/Contract-Binding,
- 401/403/404-Forget und Request-Abort,
- Unknown-Success mit tief eingefrorenem exaktem Retry.

Gezielte Zwischenprüfung:

- `HousingConfirmationModel.test.js`
- `HousingConfirmationCommand.test.jsx`
- `HousingConfirmationDialog.test.jsx`

Ergebnis: **3 Testdateien / 9 Tests bestanden**.

Gezielter ESLint über Feature und diese Tests mit `--max-warnings=0`:
**bestanden, keine Warnung**.

Der konkrete Backend-Handoff war zu diesem Zeitpunkt weiterhin nicht verfügbar;
deshalb existiert noch kein endgültiger API-Client und noch keine Vertrags-/Workflow-
Integration gegen erfundene Endpoints.

## Finaler Backendabgleich und Implementierungsstand

Der verbindliche Backend-Handoff wurde nach seiner tatsächlichen Verfügbarkeit read-only gelesen:

- Backend-Worktree: `work\housing-confirmation`
- Backend-Commit: `b11f9f92d5c157b1c6ed579d79a85e684086cc54`
- Basis: `679c8de9a97074f513bf611f7c636d40f2002fea`
- Handoff: `docs/WOHNUNGSGEBERBESTAETIGUNG_BACKEND_HANDOFF_20261002.md`
- zusätzlich geprüft:
  - `backend/services/housing_confirmation_types.py`
  - `backend/routers/housing_confirmations.py`
  - öffentliche Responseformen in `backend/services/housing_confirmation.py`.

Keine Backenddatei wurde in diesem UI-Worktree verändert.

### Tatsächlich gebundener HTTP-Vertrag

Prefix:

`/contracts/{contract_id}/housing-confirmations`

Verwendete Routen:

- `GET /source`
- `POST /preview`
- `POST /`
- `GET /?after=&limit=`
- `GET /{document_id}/download`

Der Backend-Endpunkt `POST /preview-pdf` bleibt für Roots PDF-QA verfügbar. Die
Produktoberfläche verwendet für die fachliche Prüfung den strukturierten
`/preview`-Review und öffnet nach Freigabe das verifizierte unveränderliche
Original über den geschützten Download. Es wird kein öffentlicher PDF-Link erzeugt.

### Exakte Requestprojektion

`CertificateData` wird ausschließlich mit den echten Backendfeldern erzeugt:

- `housing_provider_name`
- `housing_provider_address`
- `owner_same_as_provider`
- `owner_name`
- `move_in_date`
- `issue_date`
- `apartment_address`
- `apartment_label`
- `issuer_name`
- `issuer_role`
- `residents`

UI-interne Bezeichnungen wie `dwelling_address`, `owner_relation` oder
Personenzeilen-Keys verlassen die Komponente nicht.

`PreviewRequest`:

- `data`
- exakt die frisch gelesenen `source_etags`
- optional `correction_of: {document_id, version_id}`.

`SaveRequest` ergänzt exakt:

- `idempotency_key`
- `review_hash`
- `confirmed_actual_move_in: true`
- `confirmed_authority: true`
- `confirmed_residents: true`.

Der Client erzeugt keinen SaveRequest, solange eine dieser drei Bestätigungen
nicht ausdrücklich gesetzt ist.

### Source und Vorschläge

Der echte `GET /source`-Snapshot wird in ein reines View-Modell projiziert.
Natürlich lesbar angezeigt werden Vertragsnummer, Objektname und Einheitslabel.

Nur vom Server belegte Vorschläge werden angeboten:

- Wohnungsgebername/-anschrift aus exakt gebundener veröffentlichter Wizardquelle,
- Eigentümername aus Portfolio,
- Wohnungsanschrift/-bezeichnung aus Objekt/Einheit,
- Hauptmietername als **Vorschlag**.

Der Hauptmieter wird erst nach ausdrücklichem Klick der Personenliste hinzugefügt.
Weitere Personen sind freie vollständige Namen ohne UI-Hardcap und ohne
Deduplizierung.

`actual_move_in_date` aus der Source bleibt `null`. Das UI setzt das tatsächliche
Einzugsdatum nicht aus Vertragsbeginn oder Übergabe. Ein Übergabetermin aus der
Mieterwechselakte wird ausschließlich als deutlich bezeichnete Referenz angezeigt.

### Preview und Recovery

Jede fachliche Änderung an CertificateData verwirft die Preview sofort.

Die drei Save-Bestätigungen gehören laut Backendvertrag nicht zum PreviewRequest.
Sie können deshalb nach der Prüfung gesetzt werden, ohne den geprüften Reviewhash
unnötig zu verwerfen.

409/412 bereits beim Preview:

- Formular bleibt erhalten,
- Preview wird verworfen,
- UI zeigt bewusst „Quelldaten haben sich geändert“,
- erst „Aktuelle Quellen neu prüfen“ lädt Source/ETags neu,
- kein stilles Replay.

409/412 beim Publish verwenden denselben bewussten Review-Reload-Pfad des
eingefrorenen Commandflows.

Netzwerk/5xx:

- vollständiger SaveRequest wird vor Versand tief geklont und eingefroren,
- gleicher Payloadobjekt-/Idempotenz-/Reviewzustand wird bei
  „Unverändert erneut senden“ wiederverwendet,
- Eingaben/Preview werden während Unknown nicht ersetzt.

401/403/404:

- Source, Formularanzeige, Preview, History und Retry werden vergessen,
- laufende Requests werden abgebrochen.

Contract-/User-/Role-/Portfolio-Wechsel:

- private Anzeige wird render-synchron über den Binding-Key neutralisiert,
- der vorherige Name/Inhalt bleibt nicht bis zum nächsten Effect sichtbar.

Es wird kein Housing-Entwurf und kein Personenname in `localStorage` geschrieben.

### Historie, Korrekturen und PDF

History verwendet die echte opake `after`-Cursorliste, maximal die angeforderte
Seite.

Jeder gespeicherte Eintrag wird als vollständiges Backend-`CertificateData`
validiert. Korrektur startet mit den archivierten Fachwerten, aber ohne alte
Freigabebestätigungen und mit exakt
`{document_id, version_id}` als Korrekturbezug.

Das gespeicherte Original wird ausschließlich über

`GET /contracts/{contract_id}/housing-confirmations/{document_id}/download`

per bestehendem authentifiziertem Blobclient geladen. Vor `window.open` prüft
der Featureclient die PDF-Magic-Bytes; die Object-URL wird wieder freigegeben.
Kein Portal-/Behördenlink wird behauptet.

### Rechte

Lesen/Preview bleiben serverautorisiert und portfolio-gebunden.

Der Freigabebutton wird im UI nur aktiviert, wenn der bestehende Rechtehelper
gleichzeitig Schreiben auf `/contracts` **und** `/documents` bestätigt.
Der Backendserver prüft die Rechte bei jeder Mutation erneut.

### Produkt-Einstiege

**Vertrag / ContractLifecycle**

Der bestehende Lifecycle-Dialog erhält genau eine zusätzliche Aktion
„Wohnungsgeberbestätigung“. Die Vertragslisten-/Lifecycle-API wurde nicht geändert.
Der Housing-Dialog erhält die exakte Contract-ID und seinen eigenen Opener für
Tastatur-/Focus-Rückkehr.

**Mieterwechsel / Einzug**

`TenancyChangeFile` zeigt den Einstieg nur bei:

- `mode=move_in|turnover`,
- vorhandenem `next_contract_id`.

Reines `move_out` zeigt keinen Housing-Einstieg.

Die Seite öffnet denselben Housing-Dialog mit dem neuen Vertrag. Ein vorhandener
`move_in_handover_date` wird nur als Referenzhinweis übergeben. Housing-Publish:

- verknüpft keinen Evidence-Link automatisch,
- markiert keinen Workflow-Step automatisch erledigt,
- beendet keine Wechselakte automatisch.

Da das Ergebnis ein reguläres `housing_confirmation`-DocumentVersion-Original
ist, kann es anschließend über die bestehende Dokumentauswahl bewusst als
`document_version`-Evidence verknüpft werden.

### Dialog und Bedienung

Der eigene Dialog übernimmt die etablierten Produktpatterns:

- Focus-Trap und Escape,
- Focus-Rückkehr zum auslösenden Button,
- Request-Abort,
- Close-Warnung bei personenbezogenen Dirty-Daten oder ungeklärtem Unknown,
- kompakte Abschnitte Wohnung / Wohnungsgeber / Eigentümer / Personen / Ausstellung,
- 320/360-Stacking ohne globale Layoutänderung,
- DE/EN/ES-Texte,
- keine elektronische Unterschrifts- oder Behördenübermittlungsbehauptung.

## Tatsächlich ausgeführte Frontend-Gates

### Housing + direkte Integrationen

Serieller Gate über Housing, ContractLifecycle und TenancyChangeFile:

**6 Testdateien / 61 Tests bestanden**.

Enthalten sind u. a.:

- exakte `CertificateData`-/PreviewRequest-/SaveRequest-Projektion,
- alle drei `confirmed_*`-Bestätigungen,
- 45 Personennamen und doppelte reale Namen ohne UI-Hardcap,
- tatsächlicher Einzug bleibt manuell,
- Hauptmieter nur nach explizitem Hinzufügen,
- Preview-Invaliderung,
- Bestätigungen verwerfen Preview nicht,
- Preview-412 mit erhaltenem Formular und bewusstem Source-Reload,
- Unknown-Success Exact Retry,
- 401/403/404-Forget-Pfad,
- render-synchrone Contract-/Actor-/Role-/Portfolio-Neutralisierung,
- geschützter PDF-Download,
- History/Korrektur mit `document_id/version_id`,
- Dirty-Close-Warnung,
- ContractLifecycle-Einstieg,
- Einzugseinstieg nur für neuen Vertrag; kein `move_out`-Einstieg.

### Housing + vollständiger bestehender Mieterwechsel-Gate

Seriell mit `--maxWorkers=1`:

**15 Testdateien / 105 Tests bestanden**.

Damit bleiben insbesondere Mieterwechsel-CAS, Stable Keys, Referenzsuche,
Lost-Reply-ExactRetry, Step-/Evidence-Commands und kompakte Vorbereitung grün.

### ESLint

ESLint über gesamtes `features/housingConfirmation`, die geänderten
Contract-/Workflow-Einstiege und deren Tests mit `--max-warnings=0`:

**bestanden, keine Warnung**.

Der erste Lintbefehl enthielt versehentlich eine CSS-Datei; ESLint meldete nur
„File ignored“ als Warnung. Der korrigierte JS/JSX-Lauf war vollständig grün.

### Produktionsbuild

`npm.cmd run build`

**bestanden**, Vite 8.1.0, **679 Module transformiert**.

## Bewusst bei Root

Root registriert den Backendrouter und übernimmt weiterhin:

- echten zusammengesetzten Browserlauf,
- Edge/SQLite/Recovery/Privacy-Gates,
- PDF-Text-/Mehrseiten-/visuelle QA,
- 320/360/1440-Browserabnahme.

Dieser UI-Branch behauptet diese Root-Gates nicht selbst.
