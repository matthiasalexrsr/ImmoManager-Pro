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
