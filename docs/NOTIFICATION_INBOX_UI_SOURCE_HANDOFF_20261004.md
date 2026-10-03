# Notification Inbox Phase A – Source-Handoff

Stand: 04.10.2026  
Worktree: `work/financial-workspace-browser-qa`  
Branch: `assist/financial-workspace-browser-qa`

## Commits

Plan-/Vertragspräzisierungen dieses Zweigs:

- `0c0948e` – Plan notification inbox UI contract
- `dbb351d` – Clarify notification inbox action boundary
- `f70d3ed` – Document notification inbox Phase A
- `508382c` – Align notification inbox Phase A plan

Source:

- `1e2bc4ea00e73e3af86044338bd9c1479914802b`
  – Add notification inbox Phase A client

Die globale `NotificationBell.jsx` ist **nicht** verdrahtet oder verändert.

## Implementierter Phase-A-Client

Neu und unverdrahtet:

- `features/notificationInbox/notificationInboxModel.js`
- `features/notificationInbox/notificationInboxApi.js`
- `features/notificationInbox/useNotificationInbox.js`
- `features/notificationInbox/NotificationInboxPanel.jsx`
- `features/notificationInbox/notificationInboxText.js`
- `features/notificationInbox/NotificationInbox.css`

Tests:

- `NotificationInboxModel.test.js`
- `NotificationInboxApi.test.js`
- `NotificationInboxHook.test.jsx`
- `NotificationInboxPanel.test.jsx`

## Phase-A-Vertrag im Client

### Inbox

Vorgeschlagener additiver Endpoint:

`GET /notifications/inbox?status=unread&after=&limit=10`

Der Client erwartet in Phase A:

- `items`
- exakten `full_count`
- exakten `unread_count`
- `has_more`
- opaken `next_cursor|null`
- `consistency: "live"`
- `snapshot_token: null`
- `actions.mark_all_read: false`

Damit gibt es:

- kein FakeTotal aus `items.length`
- keinen erfundenen Snapshot
- kein Mark-all in Phase A
- bounded Cursorseiten.

Live-Seiten werden nur zusammengeführt, wenn:

- Count unverändert ist,
- Items disjunkt sind,
- serverseitige Sortierung über
  `created_at DESC NULLS LAST, id DESC nach UTF-8-Bytes`
  stabil bleibt.

Countänderung während Pagination führt zu einem neutralen
`changed`-Zustand mit explizitem Reload statt zu gemischten Seiten.

## NotificationInboxItem

Der Validator akzeptiert:

- `created_at: string|null`
- `read_at: string|null`

`created_at=null` bleibt ein valider historischer Live-Fall und wird in der
UI neutral als unbekanntes Datum dargestellt.

Nicht-null Zeitstempel werden als UTC-Mikrosekunden validiert.

Die Datumshilfe:

- unterstützt 1–6 Nachkommastellen,
- behandelt fehlende Zone als UTC,
- unterstützt explizite Offsets,
- validiert Offsetstunden 0–23 und Minuten 0–59,
- verwendet **nicht** `Date.UTC(year,...)` für die Kalenderkonstruktion und
  verschiebt daher Jahre `0000..0099` nicht künstlich nach 1900..1999,
- behält UTF-8-Bytevergleich für den ID-Tiebreaker.

## Persönliches Mark-read

Vorgeschlagener Endpoint:

`POST /notifications/inbox/{notification_id}/read`

Belegter Phase-A-Responsevertrag im Client:

```
{
  "notification_id": "...",
  "read_at": "..."
}
```

Der Client erwartet **kein** eingebettetes Notification-Item und keinen
`unread_count` in diesem Response.

Nach erfolgreichem Read lädt der Hook die Inbox über frisches
`/auth/me` erneut. Es gibt keine lokale Count-Schätzung.

Readonly darf den persönlichen Read-Command verwenden, wenn und nur wenn
`item.actions.mark_read=true` vom Backend geliefert wurde.
Allgemeine Fach-`write_permissions` steuern diese persönliche Aktion nicht.

## Fresh-auth und private Zustände

Jeder Publishpfad startet über `service.loadAuthority()` / `GET /auth/me`.

Principalbindung:

- User-ID
- Rolle
- `portfolio_access`
- `portfolio_access_origin`
- sortierte `portfolio_ids`
- sortierte `write_permissions`

Bei abweichender Renderbindung:

- alter Count sofort `null`
- alte Items sofort leer
- alter Request wird abgebrochen
- keine Late Completion darf unter neuer Bindung veröffentlichen.

Wenn frisches `/auth/me` andere Grants liefert:

- alter Inboxzustand wird nicht veröffentlicht,
- `AuthContext.updateUser(freshUser)` wird ausgelöst,
- neue Inbox lädt erst unter der neuen Bindung.

## Fehlerzustände

401/403/404:

- Access-Fehler
- kein alter Badge
- keine alten Titel/Inhalte.

Netzwerk/5xx:

- `unavailable`
- kein alter Erfolg
- kein Fake-0
- expliziter Retry.

409 / Live-Countänderung:

- `changed`
- keine gemischten Seiten
- expliziter Reload.

Abort:

- kein Fehlerzustand
- keine Late Completion.

## Mark-all / Phase B/C ausdrücklich offen

Dieses Sourcepaket implementiert **kein Mark-all**.

Insbesondere:

- kein Browserloop über sichtbare Items
- kein lokaler Snapshot aus Datum oder UUID
- kein Jobendpoint
- keine Pollingroute
- keine fortsetzbare Clientzustandsmaschine.

Der parallele Domainagent legt den genauen serverseitigen Vertrag für
fortsetzbares Mark-all fest.

Die vorhandene Servicegrenze kann später erweitert werden, aber nur gegen den
tatsächlich abgestimmten Backend-DTO. Ein unbekannter Job-/Continuation-Payload
darf nie als terminaler Erfolg interpretiert werden.

## Tatsächlich ausgeführte leichte Gates

Keine Browser-, Build-, Backend-, DB-, PostgreSQL- oder Recoveryprozesse.

Alle folgenden Läufe waren einzeln auf **20 Sekunden hart begrenzt**.

### Model

`NotificationInboxModel.test.js`

Ergebnis:

- **1 Datei bestanden**
- **6/6 Tests bestanden**
- Vitest-Dauer: **1,73 s**
- Wrapperprozess: **Exitcode 0**, vollständig beendet.

Enthält u. a.:

- FullCount > bounded Seite
- Live-null `created_at`
- Jahr 0099 ohne 1999-Verschiebung
- Offset `+23:59` gültig
- `+24:00` und Minuten `:60` ungültig
- stabile Live-Reihenfolge
- exakter Mark-read-Receipt.

### API

`NotificationInboxApi.test.js`

Ergebnis:

- **1 Datei bestanden**
- **3/3 Tests bestanden**
- Vitest-Dauer: **1,63 s**
- Wrapperprozess: **Exitcode 0**, vollständig beendet.

### Panel

`NotificationInboxPanel.test.jsx`

Ergebnis:

- **1 Datei bestanden**
- **5/5 Tests bestanden**
- Vitest-Dauer: **2,08 s**
- Wrapperprozess: **Exitcode 0**, vollständig beendet.

### Hook

`NotificationInboxHook.test.jsx`

Ergebnis:

- **1 Datei bestanden**
- **10/10 Tests bestanden**
- Vitest-Dauer: **2,63 s**
- Wrapperprozess: **Exitcode 0**, vollständig beendet.

Der frühere unvollständige Stream ohne Hook-Summary wurde ausdrücklich
**nicht** als PASS gewertet. Erst dieser spätere hart begrenzte Einzelrun ist
der gültige Hookbeleg.

### ESLint

Gezielter ESLint über:

- gesamtes `features/notificationInbox`
- alle vier Inbox-Testdateien
- `--max-warnings=0`

Ergebnis:

- **Exitcode 0**
- keine Ausgabe/Warnung
- Prozess vollständig beendet.

## Offene Grenzen für Root

Noch nicht bewiesen bzw. noch nicht implementiert:

1. die vorgeschlagenen `/notifications/inbox`-Endpoints existieren im zentralen
   Backend noch nicht als gemeinsam abgenommener Vertrag;
2. persönlicher per-user Read-State ist Backendownership;
3. Portfolio-/Entity-Scope der Inbox ist Backendownership;
4. fortsetzbares Mark-all / Jobmodell ist offen;
5. globale `NotificationBell` bleibt auf dem alten Pfad und wird bewusst noch
   nicht auf dieses Feature umgestellt;
6. kein Browser-/Rechteentzug-/Mehrbenutzer-End-to-End-Nachweis dieses neuen
   Inboxpakets;
7. kein Build-/Recovery-/SQLite-/PostgreSQL-Gate für dieses Paket.

Root sollte die globale Glocke erst aktivieren, wenn Backend Phase A
implementiert, die DTOs gegengeprüft und die gemeinsamen Rechte-/Browserfälle
bestanden sind.

## Aktuelle Verifikation nach Root-Vertragsbestätigung

Die Phase-A-Unterkomponente wurde nach erneuter Prüfung der Rootquellen unverändert bestätigt. Es waren **keine Sourcekorrekturen** erforderlich.

Bestätigt:

- `GET /notifications/inbox` wird ausschließlich über den unverdrahteten Feature-Client konsumiert;
- `full_count` / `unread_count` kommen ausschließlich vom Server und werden nie aus `items.length` geschätzt;
- Cursorseiten bleiben bounded und werden bei Live-Countänderung nicht still zusammengemischt;
- vor Initial-Load, Folgeseite und persönlichem Read erfolgt jeweils frisches `GET /auth/me`;
- Principalbindung enthält Actor, Rolle, Portfoliozugriff/-origin, sortierte Portfolio-IDs und Write-Permissions;
- bei abweichender Renderbindung ist Count/Itemzustand sofort neutral und der alte Request wird abgebrochen;
- 401/403/404, Netzwerk/5xx und ungültige Responses veröffentlichen keinen alten privaten Erfolg und keinen Fake-0;
- persönliches `mark_read` wird ausschließlich über `item.actions.mark_read` gesteuert. Ein Readonly-Actor ist damit zulässig, wenn der Backendaktionsvertrag dies ausdrücklich erlaubt; allgemeine Fach-`write_permissions` sind **keine** Read-Berechtigungsquelle;
- die globale `NotificationBell.jsx` bleibt unverändert und unverdrahtet;
- kein Browser-Allread-Loop und kein Mark-all-Client in Phase A.

### Tatsächlich erneut ausgeführte leichte Gates

`npm.cmd test -- NotificationInboxModel.test.js NotificationInboxApi.test.js NotificationInboxHook.test.jsx NotificationInboxPanel.test.jsx`

Ergebnis:

- **4 Testdateien bestanden**
- **24/24 Tests bestanden**
- Vitest-Dauer: **6,01 s**
- Prozess vollständig beendet
- **Exitcode 0**

Gezielter ESLint:

`npx.cmd eslint src/features/notificationInbox src/test/NotificationInboxModel.test.js src/test/NotificationInboxApi.test.js src/test/NotificationInboxHook.test.jsx src/test/NotificationInboxPanel.test.jsx --max-warnings=0`

Ergebnis:

- keine Ausgabe/Warnung
- Prozess vollständig beendet
- **Exitcode 0**

Weiterhin bewusst **nicht** ausgeführt bzw. aktiviert:

- globale NotificationBell-Umschaltung,
- Browser,
- Produktionsbuild,
- Backend,
- SQLite/PostgreSQL,
- Recovery.

Der vorhandene fremde untracked Plan `docs/PROPERTIES_SERVER_INVENTORY_UI_PLAN_20261004.md` wurde nicht verändert und nicht gestaged.
