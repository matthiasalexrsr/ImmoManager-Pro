# Billing Dimensions UI – Detailplan und Handoff

Stand: 03.10.2026  
Branch: `assist/billing-dimensions-ui`  
Worktree: `C:\Users\matth\Documents\Codex\2026-10-01\wi\work\billing-dimensions-ui`  
Basis: `3b891879e26a2fb8ff5f35ccd58ce98d38430707`

Dieser Plan wurde vor Frontend-Sourceänderungen erstellt.

## Verbindliche Grundlage

Gelesen und für dieses Paket maßgeblich:

- `docs/IMPLEMENTATION_ROADMAP_20261003.md`
- `backend/models.py`
  - `AllocationKeyCreate`
  - `AllocationKeyPatch`
  - `MeterCreate`
  - `MeterPatch`
- `backend/services/billing_consumption.py`
- bestehende Router
  - `/billing/allocation-keys`
  - `/meters`
- aktuelle UI
  - `frontend/src/pages/AllocationKeys.jsx`
  - `frontend/src/pages/Meters.jsx`
  - bestehendes `FormModal`, `useFinanceData`, `useWriteAccess`
  - bestehende Finance-/Meter-Tests.

## Echte E2-Felder

### AllocationKey

`AllocationKeyCreate` / `AllocationKeyPatch` besitzen:

- `consumption_medium: string | null`
- `consumption_unit: string | null`

Backendvalidierung:

- `null` bedeutet ungeklärt/fehlend und ist speicherbar,
- ein nicht-null String wird getrimmt,
- leerer String ist ungültig,
- der Verbrauchsservice blockiert Verbrauchsabrechnung, wenn bei
  `key_type=consumption` Medium oder Einheit fehlen.

Es wird nichts aus Name, Beschreibung oder Kostenkategorie geraten.

### Meter

`MeterCreate` / `MeterPatch` besitzen:

- `measurement_unit: string | null`

Auch hier:

- `null` bedeutet ungeklärt,
- leerer nicht-null String ist ungültig,
- die Einheit wird **nicht** aus `meter_type` abgeleitet.

Der Verbrauchsservice verlangt exakte Gleichheit zwischen
`meter.measurement_unit` und `allocation_key.consumption_unit`.
Es findet keine stillschweigende Umrechnung statt.

## Fachliche Semantik im bestehenden Verbrauchsservice

`billing_consumption.py` ordnet Verbrauch ausschließlich über:

- Verbrauchsschlüssel `consumption_medium`,
- Zähler `meter_type`,
- identische Einheit zwischen Schlüssel und Zähler.

Damit gilt für dieses UI-Paket:

- Medium ist eine bewusste fachliche Zuordnung.
- Maßeinheit ist eine bewusste Originalangabe.
- Zählertyp und Medium dürfen technisch identische Codes verwenden, werden aber
  im UI nicht still voneinander abgeleitet.
- unbekannte historische Werte bleiben editierbare Originalwerte.
- keine Einheit wird umgerechnet oder normalisiert.
- alte gespeicherte Werte werden bei Öffnen/Speichern nicht automatisch ersetzt.

## Bestehende Endpoints bleiben unverändert

Allocation Keys:

- `GET /billing/allocation-keys`
- `POST /billing/allocation-keys`
- `PUT /billing/allocation-keys/{id}`
- vorhandenes PATCH/Delete bleiben unberührt.

Meters:

- `GET /meters`
- `POST /meters`
- `PUT /meters/{id}`
- vorhandenes PATCH/Delete bleiben unberührt.

Die aktuelle Meters-Seite lädt außerdem weiterhin
`/meters/readings/all` vollständig über das vorhandene bounded `getAll`-
Paging. Dieses Paket erfindet **keinen** neuen Ablese-/Historienendpoint.

Der parallel entwickelte g2-Messhistorienvertrag wird nicht vorweggenommen.

## Geplante Bedienung

### Verbrauchsschlüssel

Tabelle ergänzt zwei sichtbare Dimensionen:

- Medium
- Maßeinheit

Für `key_type=consumption`:

- fehlendes Medium/Einheit wird klar als „Ungeklärt“ bzw. „Pflichtangabe fehlt“
  gekennzeichnet;
- im Formular sind beide Felder sichtbar und fachlich erklärt;
- der Save wird clientseitig mit konkreter Erklärung gestoppt, wenn Medium oder
  Einheit fehlen;
- Eingaben bleiben im Modal erhalten.

Für andere Schlüsseltypen:

- vorhandene historische Dimensionen werden nicht automatisch gelöscht;
- neue Dimensionen werden nicht erfunden;
- Anzeige kennzeichnet sie als für diesen Schlüsseltyp nicht abrechnungswirksam.

### Zähler

Tabelle/Formular ergänzt:

- tatsächliche Maßeinheit.

`measurement_unit=null` wird sichtbar als „Ungeklärt“ dargestellt.
Das UI blockiert die Zähleranlage nicht allein deshalb; der Backendservice darf
solche Zähler weiterhin als ungeklärt speichern und später als
Abrechnungsblocker melden.

Ablesungen zeigen die am Zähler hinterlegte Maßeinheit als Kontext.
Bei unbekannter Einheit wird dies ausdrücklich sichtbar.

### Natürliche Bezeichnungen und freie Werte

Bekannte Codes werden menschenlesbar dargestellt, z. B.:

Medien:
- `cold_water` → Kaltwasser
- `hot_water` → Warmwasser
- `heating` → Heizwärme / Heizung
- `electricity` → Strom
- `gas` → Gas

Häufige Einheiten:
- `m³`
- `kWh`
- `MWh`
- `GJ`
- `l`
- `Wh`

Die Felder bleiben **freie Textfelder**. Dadurch können vorhandene oder neue
fachlich gültige Werte eingegeben werden, ohne dass ein Dropdown fremde
Bestandswerte zerstört.

Unbekannte historische Codes werden nie als „ungültig“ versteckt. Sie erscheinen
als „Individuell: <Originalwert>“ und bleiben bearbeitbar.

## Fehler- und Mehrbenutzerverhalten

### Actor-/Grantwechsel

Die beiden betroffenen Seiten werden an einen Principal-Key aus aktuellem
Benutzer/Role/Portfolio-Grants gebunden. Bei Änderung wird nur der jeweilige
Seiteninhalt neu gemountet:

- alte Listen verschwinden sofort,
- offene Modale/Formwerte des alten Actors verschwinden,
- laufende `useFinanceData`-Requests werden über den bestehenden Unmount-Abort
  beendet,
- neue Daten werden unter der neuen Berechtigung geladen.

Keine Änderung an globalem DataStore/Auth ist erforderlich.

### Behebbarer Mutationsfehler

Die bestehende `FormModal`-Semantik bleibt erhalten:

- Savefehler schließen das Modal nicht,
- Benutzereingaben bleiben sichtbar,
- derselbe Benutzer kann korrigieren oder erneut speichern,
- ein erfolgreicher Write wird bei anschließend fehlgeschlagenem Refresh nicht
  automatisch wiederholt.

Für den Verbrauchsschlüssel ergänzt die UI eine lokale Vorabprüfung mit klarer
Meldung; sie verändert keine Serverdaten.

## Responsive und Bedienbarkeit

Nur lokal begrenztes Billing-Dimensions-CSS:

- Dimensionswerte umbrechen bei 320/360 px,
- Warn-/Statuschips ziehen keine Tabellenbreite künstlich auf,
- Formularhinweise sind lesbar,
- Buttons/Felder bleiben tastaturerreichbar,
- 1440 px behält die bestehende dichte Tabellenstruktur.

Kein `index.css`, kein globales Layout.

## Geplante Tests

### Allocation Keys

- Tabelle zeigt Medium/Einheit.
- Verbrauchsschlüssel ohne Zuordnung zeigt klaren ungeklärten Pflichtzustand.
- Create/Edit sendet exakt `consumption_medium` und `consumption_unit`.
- fehlende Verbrauchsdimension blockiert Save und bewahrt Eingabe.
- Nicht-Verbrauchsschlüssel löscht vorhandene historische Dimensionen nicht.
- unbekannte freie Werte bleiben unverändert.

### Meters

- Tabelle/Formular zeigt `measurement_unit`.
- kein Ableiten aus `meter_type`.
- `null` bleibt ungeklärt.
- unbekannte/freie Einheit bleibt unverändert.
- Ableseansicht zeigt Einheitenkontext.
- bestehender komplette `/meters/readings/all`-Pfad bleibt unverändert.

### Actor-/Fehlerverhalten

- Principalwechsel entfernt alte private Listendarstellung synchron durch
  Remount und startet neue Loads.
- offener Formzustand des alten Actors wird nicht übernommen.
- Savefehler lässt Eingaben/Modal erhalten.
- erfolgreicher Write + fehlerhafter Refresh wiederholt den Write nicht.

### Gates

- gezielte Billing-Dimensionstests,
- bestehende `FinancePages.test.jsx` / relevante Meter-Smokes,
- ESLint der geänderten JS/JSX-Dateien,
- Produktionsbuild,
- `git diff --check`.

Root übernimmt echte Browser-QA 320/360/1440 und spätere g2-Komposition.

## Explizit nicht in diesem Paket

- kein Backend,
- kein neuer Meter-/Reading-Endpoint,
- keine g2-Historienmodelle,
- keine automatische Migration alter Werte,
- keine stillen Einheitenumrechnungen,
- kein Main/Preview/Root-Write,
- keine Root-E2E-Dateien,
- keine globalen Layoutänderungen.

## Abschlussnachweis der bereits ausgeführten Gates

Dieser Nachtrag dokumentiert ausschließlich die Prüfungen der bereits abgeschlossenen Source-Runde zu `1f3df03`. Für diesen Dokumentationscommit wurden **keine** neuen Browser-, Test-, Lint- oder Buildprozesse gestartet, damit Roots laufende gemeinsame Recovery-Abnahme nicht gestört wird.

Tatsächlich ausgeführt und vor dem sauberen Sourcecommit abgeschlossen wurden:

- gezielte Frontendtests für `BillingDimensions.test.js` und die angepassten `FinancePages.test.jsx`-Fälle einschließlich AllocationKey-/Meter-Dimensionen, fehlender Verbrauchsbindung, freien historischen Werten, fehlender Zählereinheit, unverändertem All-Readings-Pfad, behebbaren Savefehlern und Actorwechsel;
- gezielter ESLint über die geänderten Billing-Dimensions-Helfer, `AllocationKeys.jsx`, `Meters.jsx` und die zugehörigen Tests;
- Produktionsbuild des Frontends;
- `git diff --check` vor dem Sourcecommit.

Der Sourcecommit `1f3df03` wurde danach mit sauberem Worktree hinterlassen. Echte 320/360/1440-Browser-QA, gemeinsame Recovery-Abnahme und spätere g2-Komposition bleiben bei Root bzw. den dafür zugewiesenen nativen Agenten.
