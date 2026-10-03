# Notification Inbox UI – Phase-A-Addendum

Stand: 03.10.2026

Dieses Addendum wurde vor den verbleibenden Phase-A-Sourcekorrekturen
geschrieben. Maßgeblich sind die tatsächlich gelesenen Root-Typen und der
SQL-Inboxservice in:

- `backend/services/notification_inbox_types.py`
- `backend/services/notification_inbox.py`
- `backend/services/notification_inbox_validation.py`
- `backend/db/notification_inbox_models.py`

Die globale `NotificationBell.jsx` bleibt in diesem Paket unverändert und
unverdrahtet.

## Phase A – tatsächlicher Page-DTO

`InboxPage`:

- `items: NotificationInboxItem[]`
- `full_count: int >= 0`
- `unread_count: int >= 0`
- `has_more: bool`
- `next_cursor: string|null`
- `snapshot_token: null`
- `consistency: "live"`
- `actions.mark_all_read: false`

Folgerungen:

- Phase A besitzt **keinen** Snapshot für Mark-all.
- Der Client darf `snapshot_token` nicht als String verlangen.
- `expectedConsistency` muss tatsächlich geprüft werden.
- Mark-all wird in Phase A weder gerendert noch als API-/Hookaktion angeboten.
- `items.length` ist niemals Badge-/FullCount-Ersatz.

## Counts bei live consistency

Für `status=unread`:

- `full_count == unread_count`
- alle Items müssen `read_at == null` haben.

Für `status=read`:

- `full_count` zählt die gelesenen Filtertreffer dieser Pagequery,
- `unread_count` ist der vollständige persönliche Ungelesencount,
- `unread_count` darf deshalb größer als `full_count` sein,
- alle Items müssen `read_at != null` haben.

Für `status=all`:

- `unread_count <= full_count`.

Ändert sich bei einer Folgeseite unter `consistency:"live"` der Count, ist
das **kein Backendfehler**. Die UI kombiniert die alte und neue Seite nicht zu
einer scheinbar konsistenten Liste. Sie wechselt in einen eigenen
„Benachrichtigungen haben sich geändert“-Zustand und bietet frisches Laden der
ersten Seite an.

## Phase-A-Sortierung

Backendbindung:

`created_at DESC NULLS LAST, UTF8-byte-id DESC`

Anforderungen an den Clientvalidator:

- keine `localeCompare`-Reihenfolge,
- keine millisekundenreduzierende `Date.parse`-/`Date`-Sortierung,
- UTC-Mikrosekunden verlustfrei vergleichen,
- naive Backendzeit als UTC interpretieren,
- `created_at=null` zuletzt,
- ID-Vergleich byteweise über UTF-8,
- Reihenfolge innerhalb einer Page und an der Pagegrenze prüfen.

Beispiel bei gleicher Sekunde:

- `.123999 / a` steht vor
- `.123001 / z`

obwohl die ID `z` lexikalisch größer ist; Zeit hat Vorrang.

Bei identischem Mikrosekundenzeitpunkt entscheidet die UTF8-Byte-ID absteigend.

## Zeitdarstellung

`NotificationInboxItem.created_at` darf für Altbestand `null` sein.

Für sichtbare Zeitwerte gilt:

- Backend-naive Zeit = UTC,
- ein String ohne `Z`/Offset wird für die Darstellung ausdrücklich als UTC
  behandelt,
- kein `new Date(naiveString)` mit lokaler Zeitzoneninterpretation.

`null` wird als fehlende historische Zeit verständlich dargestellt.

## Single-read – tatsächliche Response

`NotificationReadResult`:

```
{
  "notification_id": "...",
  "read_at": "..."
}
```

Kein:

- `item`
- `unread_count`

Nach erfolgreichem Read lädt der Hook die Inbox ohnehin frisch. Der Client
schätzt deshalb weiterhin keinen Count lokal.

Read-Berechtigung:

- nur `item.actions.mark_read`
- kein allgemeines Fach-`write_permissions`-Gate
- Readonly ist erlaubt, wenn der Server die Action liefert.

## Phase B – ausdrücklich nur Zukunftsgrenze

Dieses Phase-A-Paket implementiert **keinen** Mark-all-Client.

Der bereits festgelegte Phase-B-Vertrag beginnt mit:

`POST /read-selections`

und einem serverseitigen Selection-DTO:

```
{
  "selection_id": "...",
  "snapshot_token": "...",
  "selected_count": 123,
  "captured_at": "...",
  "expires_at": "..."
}
```

Erst danach folgt ein **bestätigter Command**, dessen tatsächliche
Backendantwort ein `202`-Job-DTO ist.

Daraus folgt:

- kein `selection_token` aus einer Livepage,
- kein Snapshot aus Datum/UUID im Browser,
- kein terminaler synchroner Mark-all-Defaultresponse,
- keine erfundene Jobpollingroute,
- keine Mark-all-Schaltfläche in Phase A.

Wenn Root Phase B freigibt, wird der Client erst nach Lesen des echten
Selection-/Command-/Job-DTO erweitert.

## Phase-A-Hookzustände

Benötigt:

- `idle`
- `loading`
- `ready`
- `loading_more`
- `acting`
- `changed`
- `error`

`changed` ist ein Livekonsistenzzustand, kein Serverfehler.

`error` enthält niemals alte private Items/Counts.

## Fresh-auth und private Bindung

Unverändert:

- vor jeder privaten Publishoperation frisches `/auth/me`,
- Principal enthält Actor, Rolle, Portfoliozugriff/-origin, sortierte
  Portfolio-IDs und Write-Permissions als Bindungsdaten,
- Write-Permissions sind **keine** Inbox-Read-Autorisierung,
- Render mit anderer Principal-/Servicebindung gibt sofort neutralen State,
- alte Requests werden abgebrochen,
- Late Completion veröffentlicht nichts.

## Phase-A-Komponentengrenze

Die unverdrahtete `NotificationInboxPanel` zeigt:

- loading
- error/access/unavailable
- changed → „Benachrichtigungen haben sich geändert“ + neu laden
- empty
- exakten serverseitigen Ungelesencount
- bounded Items
- „Weitere laden“
- pro Item nur action-gesteuertes „Als gelesen markieren“.

Nicht vorhanden:

- Mark-all
- Unknown-Mark-all
- Exact-Retry-Mark-all
- Jobzustand.

## Leichte Belege dieses Pakets

Nur:

- Model-/DTO-Tests
- API-Vertragstests
- Hooktests mit injiziertem Service
- reine Komponentenrender-/Keyboardtests
- gezielter ESLint / statischer Sourcecheck.

Nicht starten:

- Browser
- Build
- Backend
- Datenbank
- PostgreSQL
- Recovery.
