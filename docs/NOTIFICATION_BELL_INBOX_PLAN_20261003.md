# NotificationBell – sichere Inbox-/Badge-Vorcodeanalyse

Stand: 03.10.2026
Worktree: `work/financial-workspace-browser-qa`
Scope dieses Dokuments: reine Sourceanalyse, **keine Sharedsourceänderung**.

## Ausgangsbefund aus Root B2

Der echte Rechteentzug-Browserfall zeigte einen stale Badgewert `10` in der
globalen Kopfzeile, während die Dashboarddaten bereits korrekt verborgen waren.

Die aktuelle `NotificationBell.jsx` erklärt den Befund vollständig:

- `GET /notifications?status=unread&limit=10`
- Badge = `items.length`
- Fehler behalten den letzten erfolgreichen `notifications`- und
  `unreadCount`-Zustand
- kein `AbortController`
- 60-s-Intervall ohne Principal-/Grantbindung
- `markAllRead` PATCHt nur die aktuell sichtbaren maximal 10 Einträge
- kein Cursor
- kein vollständiger serverseitiger Ungelesen-Count.

Damit ist `10` weder ein verlässlicher Gesamtcount noch nach einem
Scopefehler ein verlässlicher aktueller Zustand.

## Tatsächlich gelesene Frontend-Auth-/Fehlerpfade

### AuthContext

`AuthContext` hält:

- `user`
- `role`
- `writePermissions`
- `updateUser`
- `clearUser`.

Es gibt keinen eigenen globalen Grant-/Portfolio-Scope-Eventbus.

### Sessionwechsel

`api.watchSessionChange` beobachtet:

- LocalStorage-Tokenänderungen
- `immomanager-session-change`.

`ProtectedRoute` reagiert darauf mit:

- `clearUser()`
- Reload bei neuem Actor
- Login bei ungültiger Session.

Das schützt echte Token-/Actorwechsel.

### Gleicher Actor, neue Grants

Für denselben Benutzer mit geänderten Portfolio-Grants existiert kein
allgemeines `scope-change`-/`authorization-change`-Event.

`ProtectedRoute` lädt `/auth/me` bei seiner Sessionvalidierung, nicht
kontinuierlich bei jeder Grantänderung.

Andere private Komponenten lösen dieses Problem lokal, z. B.
`DashboardBoundary` mit einer frischen `/auth/me`-Prüfung.

### API-Fehler

- 401 versucht einmal Tokenrefresh; bleibt 401 bestehen, wird die aktuelle
  Session invalidiert und Login ausgelöst.
- 403/404 werden als normale API-Fehler an die Komponente geworfen.
- Netzwerkfehler nach Safe-GET-Retries werden ebenfalls geworfen.
- `AbortError` wird nicht automatisch wiederholt.

Folge für NotificationBell: Die Komponente muss 403/404 und Netzwerk/5xx
selbst sicher darstellen. Ein Fehler darf nicht wie ein alter Erfolg aussehen.

## Tatsächlich gelesener Notification-Backendstand

### Aktuelle Liste

`GET /notifications`

liefert `list[Notification]` mit:

- skip/limit
- status
- notification_type
- severity.

Der Router:

1. lädt zunächst `store.list_notifications()`,
2. filtert danach über `notification_visible(..., user.role)`,
3. filtert Status/Typ/Severity,
4. schneidet erst danach `skip:skip+limit`.

Es gibt:

- keinen Cursor,
- keinen FullCount,
- keinen serverseitigen Badgecount,
- keinen Inbox-Snapshot.

### Sichtbarkeit

`notification_visible` prüft aktuell nur den Operational-Dispatch-`target_role`:

- kein Target → sichtbar
- Owner → sichtbar
- gleiche Zielrolle → sichtbar.

Die Funktion prüft **keine Portfolio-Grants**.

### Notification-Modell

`Notification` besitzt u. a.:

- `notification_type`
- `title`
- `content`
- `severity`
- `entity_type`
- `entity_id`
- `status`
- `read_at`
- Zeitstempel.

Es gibt kein `portfolio_id` am Notification-Datensatz.

### Wichtige Mehrbenutzergrenze

`status` und `read_at` liegen aktuell direkt auf der Notification.

Damit ist „gelesen“ heute ein **globaler** Zustand des Datensatzes. Wenn zwei
Benutzer dieselbe Notification sehen dürfen, würde ein persönliches
„gelesen“ eines Benutzers den gemeinsamen Datensatz verändern.

Für eine echte persönliche globale Glocke darf der neue Inboxvertrag deshalb
nicht voraussetzen, dass `Notification.status` bereits ein per-user
Ungelesenstatus ist.

## Zielbild der Glocke

Die Glocke ist ein kompakter **persönlicher, aktuell autorisierter Inboxblick**:

- exakter ungelesener Gesamtcount
- erste bounded Seite
- weitere Seiten per Cursor
- keine Stockbegrenzung auf 10
- keine privaten Altwerte nach Actor-/Grantänderung
- Fehler ≠ leer
- „alle gelesen“ wirkt auf den vollständigen autorisierten Snapshot, nicht nur
  auf sichtbare Zeilen.

## Erforderlicher additiver Backendvertrag

Die folgenden Routen sind **Planvorschläge**, keine bereits existierenden
Endpoints.

### GET /notifications/inbox

Query:

- `status=unread|read|all`, Default `unread`
- optional `notification_type`
- optional `severity`
- `after` opaker Cursor
- `limit`, Default 10, mit serverseitigem Seitenbudget.

Response:

```
{
  "items": [NotificationInboxItem],
  "full_count": 137,
  "unread_count": 137,
  "has_more": true,
  "next_cursor": "...",
  "snapshot_token": "...",
  "actions": {
    "mark_all_read": true
  }
}
```

Semantik:

- `full_count` = exakte Anzahl aller Datensätze, die den aktuellen
  Inboxfiltern **und** dem aktuellen Actor/Scope entsprechen.
- `unread_count` = exakte Anzahl aller aktuell autorisierten ungelesenen
  Inboxeinträge, unabhängig von der Seite.
- Bei `status=unread` sind `full_count` und `unread_count` identisch.
- Der Badge verwendet ausschließlich `unread_count`.
- Niemals `items.length` als FakeTotal.

### NotificationInboxItem

Nur für die Glocke nötige öffentliche Felder:

- `id`
- `notification_type`
- `title`
- `content`
- `severity`
- `entity_type|null`
- `entity_id|null`
- `created_at`
- persönlicher `read_at|null`
- `actions.mark_read`.

Keine versteckten Domainobjekte oder vollständigen Entitypayloads.

## Persönlicher Read-State

Für die Inbox ist ein actor-gebundener Read-State nötig, z. B. logisch:

`(notification_id, user_id) -> read_at`

Die konkrete Persistenzform bleibt Backendownership, aber der Vertrag muss
garantieren:

- Benutzer A liest → Benutzer B bleibt unverändert
- `unread_count` ist pro Actor
- Mark-all ist pro Actor
- Löschen/Archivieren des gemeinsamen Notification-Datensatzes ist davon
  getrennt.

Der bestehende globale `Notification.status` darf nicht still als
per-user Inboxzustand umgedeutet werden.

## Portfolio-/Grant-Scope

Weil Notification kein `portfolio_id` besitzt, muss der Inboxservice die
Scopezugehörigkeit serverseitig über `entity_type/entity_id` auflösen.

Regeln:

1. Operational-`target_role` bleibt eine notwendige Sichtbarkeitsbedingung.
2. Bei portfoliofähigen Entitytypen wird die zugehörige Portfolio-ID über die
   Domainreferenz aufgelöst und gegen den **frischen** Actor-Scope geprüft.
3. Entity-spezifische Notification mit nicht sicher auflösbarer Referenz wird
   einem eingeschränkten Benutzer nicht angezeigt.
4. Bewusst globale Notification ohne Entitybezug darf nach Rollenregel
   sichtbar sein.
5. Direkter Zugriff auf eine nicht sichtbare Notification liefert 404, nicht
   Entity-/Scopeinformationen.

Damit zählt `unread_count` nur nach **vollständiger** Rollen- und
Portfolioprüfung.

## Cursor und Snapshot

Stabile Reihenfolge:

`created_at DESC, id DESC`.

Der opake Cursor bindet mindestens:

- User-ID
- Rolle
- `portfolio_access`
- `portfolio_access_origin`
- sortierte `portfolio_ids`
- Inboxfilter
- Seitengröße
- `snapshot_token`.

Keine Offsetpagination und keine feste Gesamtbestandsgrenze.

Der Snapshot verhindert:

- Duplikate zwischen Seiten
- Sprünge durch parallel neu eintreffende Notifications
- Mark-all gegen eine andere Inbox als die gerade geprüfte.

Bei geänderten Grants oder ungültigem Snapshot:

- Cursor nicht still weiterverwenden
- 409/422 mit neutraler Aufforderung „Benachrichtigungen neu laden“
- keine Altseite als aktuell ausgeben.

## Einzelnes „gelesen“

Bevorzugter additiver Command:

`POST /notifications/inbox/{id}/read`

Server:

- authentifiziert frisch
- prüft aktuelle Rollen-/Portfolio-Sichtbarkeit
- schreibt nur persönlichen Read-State
- idempotent.

Response mindestens:

```
{
  "item": NotificationInboxItem,
  "unread_count": 136
}
```

Alternativ kann die UI danach GET /inbox neu laden. Der Badge darf nicht lokal
nur `-1` rechnen, wenn Paralleländerungen möglich sind.

## „Alle als gelesen“

Die aktuelle Browser-Schleife über zehn sichtbare PATCHs muss entfallen.

Vorgeschlagener Command:

`POST /notifications/inbox/mark-all-read`

Request:

```
{
  "snapshot_token": "...",
  "idempotency_key": "..."
}
```

Semantik:

- markiert alle ungelesenen, aktuell autorisierten Einträge des **geprüften
  Snapshots** für genau diesen Actor
- keine später eingetroffene Notification wird versehentlich mitmarkiert
- Server revalidiert Scope/Role beim Command
- Replay mit gleichem Idempotenzschlüssel ist sicher.

Response:

```
{
  "marked_count": 137,
  "unread_count": 0,
  "snapshot_token": "new-or-current"
}
```

Falls nach dem Snapshot neue Notifications eingetroffen sind, darf
`unread_count` entsprechend größer als 0 sein.

## Sichere Frontend-Bindung

### Principal-Key

NotificationBell braucht eine eigene Renderbindung mindestens aus:

- `user.id`
- `user.role`
- `portfolio_access`
- `portfolio_access_origin`
- sortierten `portfolio_ids`
- sortierten `write_permissions`.

`useWriteAccess` allein reicht nicht, weil dessen Principal heute nur
User-ID + Rolle enthält.

### Render-synchrone Neutralisierung

State wird mit seinem Principal gespeichert.

Wenn Render-Principal != State-Principal:

- Badge sofort neutral
- Dropdowninhalt sofort neutral
- Dropdown schließen
- alter State nicht bis zum Effect weiter anzeigen.

Das entspricht den bereits etablierten privaten Workspacepatterns.

### Fresh-auth Publish-Gate

Weil es kein globales Same-Actor-Grantchange-Event gibt:

- Initial load, Dropdown-Open und Poll-Zyklus revalidieren zuerst
  `GET /auth/me`.
- Weichen frische Grants vom lokalen Principal ab:
  - alte Inbox sofort verwerfen
  - `AuthContext.updateUser(freshUser)`
  - erst unter neuem Principal Inbox laden/veröffentlichen.
- Eine Inboxantwort darf nur veröffentlicht werden, wenn die Bindung während
  des Requests unverändert geblieben ist.

Dies ist lokales Glockenverhalten und erfordert keinen neuen globalen
Dashboard-/App-Eventbus.

## Abort und Polling

Ein Controller pro aktiver Refreshgeneration:

- neuer Refresh abortet den vorherigen
- Principalwechsel abortet
- Unmount abortet
- Poll cleanup entfernt Timer
- Dropdown-Open kann sofort aktualisieren
- optional `visibilitychange`/Window-Focus nur als gezielter Refresh, nicht
  als zweiter paralleler Poller.

Keine Antwort einer alten Generation darf State veröffentlichen.

## Fehlerbedienung

### 401

API-Client übernimmt Sessioninvalidierung/Login.

Bell:

- private Inbox/Badge sofort neutral.

### 403 / 404

- private Inbox/Badge sofort vergessen
- Dropdown schließen oder neutralen „Zugriff geändert“-Zustand zeigen
- kein alter Count
- keine alten Titel/Inhalte.

### Netzwerk / 5xx

Nicht als leer und nicht als letzter Erfolg darstellen.

Sicherer Zustand:

- Badgezahl ausblenden
- private Liste nicht als aktuell rendern
- neutraler Text „Benachrichtigungen konnten nicht aktualisiert werden“
- expliziter Retry.

Kein Fake-`0`: Fehler ist ein eigener Zustand.

## Bounded UI

Die Glocke kann weiterhin zehn Einträge auf der ersten Seite zeigen.

Aber:

- Badge kommt vom exakten `unread_count`
- `has_more/next_cursor` erlaubt „Weitere laden“
- Seiten bleiben bounded
- keine 10er-Stockgrenze
- „Alle gelesen“ ist serverseitig vollständig.

## Tastatur/Fokus

Beibehalten bzw. präzisieren:

- Glockenbutton `aria-expanded`
- Escape schließt und Fokus zurück auf Glockenbutton
- Mark-read als echtes Button-/Menuitem-Verhalten statt klickbarem
  `div role=listitem`, sofern die spätere UI-Änderung erfolgt
- „Alle gelesen“, Retry und „Weitere laden“ tastaturerreichbar
- kein Mark-read allein durch Fokus.

## Vorgesehene kleine Tests nach Vertragsfreigabe

Frontend:

1. 17 ungelesene, Seite 10 → Badge 17, nicht 10.
2. 403 nach vorherigem Erfolg → alter Badge/Inhalt im selben Render weg.
3. Netzwerk/5xx → Fehlerzustand, weder alter Erfolg noch Fake-0.
4. Principal-/Grantwechsel → render-synchron neutral, alter Request abortiert.
5. frisches `/auth/me` mit neuem Portfolio-Scope → alter State nicht
   veröffentlicht.
6. Cursor Seite 1/2 ohne Duplikate.
7. Mark-all verwendet genau einen Servercommand, keine sichtbare 10er-Schleife.
8. Mark-all von Actor A verändert Actor B nicht.
9. neue Notification nach Snapshot bleibt nach Mark-all ungelesen.
10. Escape/Fokus/Keyboard.

Backendvertrag:

1. `unread_count` ist exact FullCount über >Seitenbudget.
2. Cursor bindet Scope/Filter/Limit/Snapshot.
3. Grantentzug macht alten Cursor ungültig.
4. Entityportfolio wird vollständig gescoped.
5. nicht auflösbare private Entitynotification leakt nicht.
6. per-user Read-State ist isoliert.
7. Mark-all verarbeitet >Seitengröße vollständig und idempotent.

## Nicht Teil dieses Vorcodepakets

- keine Änderung an `NotificationBell.jsx`
- keine Änderung an AuthContext/App/API/shared Hooks
- keine Backend-/Schema-/Routeränderung
- keine Dashboard-Neuerfindung
- kein Browser-/Build-/DB-/Recoverylauf
- keine privaten Daten oder Secrets.

Der nächste Implementierungsschritt sollte erst erfolgen, nachdem Root den
serverseitigen Inbox-/Read-State-Vertrag festgelegt hat.
