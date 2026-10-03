# NotificationBell â€“ sichere Inbox-/Badge-Vorcodeanalyse

Stand: 03.10.2026
Worktree: `work/financial-workspace-browser-qa`
Scope dieses Dokuments: reine Sourceanalyse, **keine SharedsourceÃ¤nderung**.

## Ausgangsbefund aus Root B2

Der echte Rechteentzug-Browserfall zeigte einen stale Badgewert `10` in der
globalen Kopfzeile, wÃ¤hrend die Dashboarddaten bereits korrekt verborgen waren.

Die aktuelle `NotificationBell.jsx` erklÃ¤rt den Befund vollstÃ¤ndig:

- `GET /notifications?status=unread&limit=10`
- Badge = `items.length`
- Fehler behalten den letzten erfolgreichen `notifications`- und
  `unreadCount`-Zustand
- kein `AbortController`
- 60-s-Intervall ohne Principal-/Grantbindung
- `markAllRead` PATCHt nur die aktuell sichtbaren maximal 10 EintrÃ¤ge
- kein Cursor
- kein vollstÃ¤ndiger serverseitiger Ungelesen-Count.

Damit ist `10` weder ein verlÃ¤sslicher Gesamtcount noch nach einem
Scopefehler ein verlÃ¤sslicher aktueller Zustand.

## TatsÃ¤chlich gelesene Frontend-Auth-/Fehlerpfade

### AuthContext

`AuthContext` hÃ¤lt:

- `user`
- `role`
- `writePermissions`
- `updateUser`
- `clearUser`.

Es gibt keinen eigenen globalen Grant-/Portfolio-Scope-Eventbus.

### Sessionwechsel

`api.watchSessionChange` beobachtet:

- LocalStorage-TokenÃ¤nderungen
- `immomanager-session-change`.

`ProtectedRoute` reagiert darauf mit:

- `clearUser()`
- Reload bei neuem Actor
- Login bei ungÃ¼ltiger Session.

Das schÃ¼tzt echte Token-/Actorwechsel.

### Gleicher Actor, neue Grants

FÃ¼r denselben Benutzer mit geÃ¤nderten Portfolio-Grants existiert kein
allgemeines `scope-change`-/`authorization-change`-Event.

`ProtectedRoute` lÃ¤dt `/auth/me` bei seiner Sessionvalidierung, nicht
kontinuierlich bei jeder GrantÃ¤nderung.

Andere private Komponenten lÃ¶sen dieses Problem lokal, z. B.
`DashboardBoundary` mit einer frischen `/auth/me`-PrÃ¼fung.

### API-Fehler

- 401 versucht einmal Tokenrefresh; bleibt 401 bestehen, wird die aktuelle
  Session invalidiert und Login ausgelÃ¶st.
- 403/404 werden als normale API-Fehler an die Komponente geworfen.
- Netzwerkfehler nach Safe-GET-Retries werden ebenfalls geworfen.
- `AbortError` wird nicht automatisch wiederholt.

Folge fÃ¼r NotificationBell: Die Komponente muss 403/404 und Netzwerk/5xx
selbst sicher darstellen. Ein Fehler darf nicht wie ein alter Erfolg aussehen.

## TatsÃ¤chlich gelesener Notification-Backendstand

### Aktuelle Liste

`GET /notifications`

liefert `list[Notification]` mit:

- skip/limit
- status
- notification_type
- severity.

Der Router:

1. lÃ¤dt zunÃ¤chst `store.list_notifications()`,
2. filtert danach Ã¼ber `notification_visible(..., user.role)`,
3. filtert Status/Typ/Severity,
4. schneidet erst danach `skip:skip+limit`.

Es gibt:

- keinen Cursor,
- keinen FullCount,
- keinen serverseitigen Badgecount,
- keinen Inbox-Snapshot.

### Sichtbarkeit

`notification_visible` prÃ¼ft aktuell nur den Operational-Dispatch-`target_role`:

- kein Target â†’ sichtbar
- Owner â†’ sichtbar
- gleiche Zielrolle â†’ sichtbar.

Die Funktion prÃ¼ft **keine Portfolio-Grants**.

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

Damit ist â€žgelesenâ€œ heute ein **globaler** Zustand des Datensatzes. Wenn zwei
Benutzer dieselbe Notification sehen dÃ¼rfen, wÃ¼rde ein persÃ¶nliches
â€žgelesenâ€œ eines Benutzers den gemeinsamen Datensatz verÃ¤ndern.

FÃ¼r eine echte persÃ¶nliche globale Glocke darf der neue Inboxvertrag deshalb
nicht voraussetzen, dass `Notification.status` bereits ein per-user
Ungelesenstatus ist.

## Zielbild der Glocke

Die Glocke ist ein kompakter **persÃ¶nlicher, aktuell autorisierter Inboxblick**:

- exakter ungelesener Gesamtcount
- erste bounded Seite
- weitere Seiten per Cursor
- keine Stockbegrenzung auf 10
- keine privaten Altwerte nach Actor-/GrantÃ¤nderung
- Fehler â‰  leer
- â€žalle gelesenâ€œ wirkt auf den vollstÃ¤ndigen autorisierten Snapshot, nicht nur
  auf sichtbare Zeilen.

## Erforderlicher additiver Backendvertrag

Die folgenden Routen sind **PlanvorschlÃ¤ge**, keine bereits existierenden
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

- `full_count` = exakte Anzahl aller DatensÃ¤tze, die den aktuellen
  Inboxfiltern **und** dem aktuellen Actor/Scope entsprechen.
- `unread_count` = exakte Anzahl aller aktuell autorisierten ungelesenen
  InboxeintrÃ¤ge, unabhÃ¤ngig von der Seite.
- Bei `status=unread` sind `full_count` und `unread_count` identisch.
- Der Badge verwendet ausschlieÃŸlich `unread_count`.
- Niemals `items.length` als FakeTotal.

### NotificationInboxItem

Nur fÃ¼r die Glocke nÃ¶tige Ã¶ffentliche Felder:

- `id`
- `notification_type`
- `title`
- `content`
- `severity`
- `entity_type|null`
- `entity_id|null`
- `created_at`
- persÃ¶nlicher `read_at|null`
- `actions.mark_read`.

Keine versteckten Domainobjekte oder vollstÃ¤ndigen Entitypayloads.

## PersÃ¶nlicher Read-State

FÃ¼r die Inbox ist ein actor-gebundener Read-State nÃ¶tig, z. B. logisch:

`(notification_id, user_id) -> read_at`

Die konkrete Persistenzform bleibt Backendownership, aber der Vertrag muss
garantieren:

- Benutzer A liest â†’ Benutzer B bleibt unverÃ¤ndert
- `unread_count` ist pro Actor
- Mark-all ist pro Actor
- LÃ¶schen/Archivieren des gemeinsamen Notification-Datensatzes ist davon
  getrennt.

Der bestehende globale `Notification.status` darf nicht still als
per-user Inboxzustand umgedeutet werden.

## Portfolio-/Grant-Scope

Weil Notification kein `portfolio_id` besitzt, muss der Inboxservice die
ScopezugehÃ¶rigkeit serverseitig Ã¼ber `entity_type/entity_id` auflÃ¶sen.

Regeln:

1. Operational-`target_role` bleibt eine notwendige Sichtbarkeitsbedingung.
2. Bei portfoliofÃ¤higen Entitytypen wird die zugehÃ¶rige Portfolio-ID Ã¼ber die
   Domainreferenz aufgelÃ¶st und gegen den **frischen** Actor-Scope geprÃ¼ft.
3. Entity-spezifische Notification mit nicht sicher auflÃ¶sbarer Referenz wird
   einem eingeschrÃ¤nkten Benutzer nicht angezeigt.
4. Bewusst globale Notification ohne Entitybezug darf nach Rollenregel
   sichtbar sein.
5. Direkter Zugriff auf eine nicht sichtbare Notification liefert 404, nicht
   Entity-/Scopeinformationen.

Damit zÃ¤hlt `unread_count` nur nach **vollstÃ¤ndiger** Rollen- und
PortfolioprÃ¼fung.

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
- SeitengrÃ¶ÃŸe
- `snapshot_token`.

Keine Offsetpagination und keine feste Gesamtbestandsgrenze.

Der Snapshot verhindert:

- Duplikate zwischen Seiten
- SprÃ¼nge durch parallel neu eintreffende Notifications
- Mark-all gegen eine andere Inbox als die gerade geprÃ¼fte.

Bei geÃ¤nderten Grants oder ungÃ¼ltigem Snapshot:

- Cursor nicht still weiterverwenden
- 409/422 mit neutraler Aufforderung â€žBenachrichtigungen neu ladenâ€œ
- keine Altseite als aktuell ausgeben.

## Einzelnes â€žgelesenâ€œ

Bevorzugter additiver Command:

`POST /notifications/inbox/{id}/read`

Server:

- authentifiziert frisch
- prÃ¼ft aktuelle Rollen-/Portfolio-Sichtbarkeit
- schreibt nur persÃ¶nlichen Read-State
- idempotent.

Response mindestens:

```
{
  "item": NotificationInboxItem,
  "unread_count": 136
}
```

Alternativ kann die UI danach GET /inbox neu laden. Der Badge darf nicht lokal
nur `-1` rechnen, wenn ParallelÃ¤nderungen mÃ¶glich sind.

## â€žAlle als gelesenâ€œ

Die aktuelle Browser-Schleife Ã¼ber zehn sichtbare PATCHs muss entfallen.

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

- markiert alle ungelesenen, aktuell autorisierten EintrÃ¤ge des **geprÃ¼ften
  Snapshots** fÃ¼r genau diesen Actor
- keine spÃ¤ter eingetroffene Notification wird versehentlich mitmarkiert
- Server revalidiert Scope/Role beim Command
- Replay mit gleichem IdempotenzschlÃ¼ssel ist sicher.

Response:

```
{
  "marked_count": 137,
  "unread_count": 0,
  "snapshot_token": "new-or-current"
}
```

Falls nach dem Snapshot neue Notifications eingetroffen sind, darf
`unread_count` entsprechend grÃ¶ÃŸer als 0 sein.

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
User-ID + Rolle enthÃ¤lt.

### Render-synchrone Neutralisierung

State wird mit seinem Principal gespeichert.

Wenn Render-Principal != State-Principal:

- Badge sofort neutral
- Dropdowninhalt sofort neutral
- Dropdown schlieÃŸen
- alter State nicht bis zum Effect weiter anzeigen.

Das entspricht den bereits etablierten privaten Workspacepatterns.

### Fresh-auth Publish-Gate

Weil es kein globales Same-Actor-Grantchange-Event gibt:

- Initial load, Dropdown-Open und Poll-Zyklus revalidieren zuerst
  `GET /auth/me`.
- Weichen frische Grants vom lokalen Principal ab:
  - alte Inbox sofort verwerfen
  - `AuthContext.updateUser(freshUser)`
  - erst unter neuem Principal Inbox laden/verÃ¶ffentlichen.
- Eine Inboxantwort darf nur verÃ¶ffentlicht werden, wenn die Bindung wÃ¤hrend
  des Requests unverÃ¤ndert geblieben ist.

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

Keine Antwort einer alten Generation darf State verÃ¶ffentlichen.

## Fehlerbedienung

### 401

API-Client Ã¼bernimmt Sessioninvalidierung/Login.

Bell:

- private Inbox/Badge sofort neutral.

### 403 / 404

- private Inbox/Badge sofort vergessen
- Dropdown schlieÃŸen oder neutralen â€žZugriff geÃ¤ndertâ€œ-Zustand zeigen
- kein alter Count
- keine alten Titel/Inhalte.

### Netzwerk / 5xx

Nicht als leer und nicht als letzter Erfolg darstellen.

Sicherer Zustand:

- Badgezahl ausblenden
- private Liste nicht als aktuell rendern
- neutraler Text â€žBenachrichtigungen konnten nicht aktualisiert werdenâ€œ
- expliziter Retry.

Kein Fake-`0`: Fehler ist ein eigener Zustand.

## Bounded UI

Die Glocke kann weiterhin zehn EintrÃ¤ge auf der ersten Seite zeigen.

Aber:

- Badge kommt vom exakten `unread_count`
- `has_more/next_cursor` erlaubt â€žWeitere ladenâ€œ
- Seiten bleiben bounded
- keine 10er-Stockgrenze
- â€žAlle gelesenâ€œ ist serverseitig vollstÃ¤ndig.

## Tastatur/Fokus

Beibehalten bzw. prÃ¤zisieren:

- Glockenbutton `aria-expanded`
- Escape schlieÃŸt und Fokus zurÃ¼ck auf Glockenbutton
- Mark-read als echtes Button-/Menuitem-Verhalten statt klickbarem
  `div role=listitem`, sofern die spÃ¤tere UI-Ã„nderung erfolgt
- â€žAlle gelesenâ€œ, Retry und â€žWeitere ladenâ€œ tastaturerreichbar
- kein Mark-read allein durch Fokus.

## Vorgesehene kleine Tests nach Vertragsfreigabe

Frontend:

1. 17 ungelesene, Seite 10 â†’ Badge 17, nicht 10.
2. 403 nach vorherigem Erfolg â†’ alter Badge/Inhalt im selben Render weg.
3. Netzwerk/5xx â†’ Fehlerzustand, weder alter Erfolg noch Fake-0.
4. Principal-/Grantwechsel â†’ render-synchron neutral, alter Request abortiert.
5. frisches `/auth/me` mit neuem Portfolio-Scope â†’ alter State nicht
   verÃ¶ffentlicht.
6. Cursor Seite 1/2 ohne Duplikate.
7. Mark-all verwendet genau einen Servercommand, keine sichtbare 10er-Schleife.
8. Mark-all von Actor A verÃ¤ndert Actor B nicht.
9. neue Notification nach Snapshot bleibt nach Mark-all ungelesen.
10. Escape/Fokus/Keyboard.

Backendvertrag:

1. `unread_count` ist exact FullCount Ã¼ber >Seitenbudget.
2. Cursor bindet Scope/Filter/Limit/Snapshot.
3. Grantentzug macht alten Cursor ungÃ¼ltig.
4. Entityportfolio wird vollstÃ¤ndig gescoped.
5. nicht auflÃ¶sbare private Entitynotification leakt nicht.
6. per-user Read-State ist isoliert.
7. Mark-all verarbeitet >SeitengrÃ¶ÃŸe vollstÃ¤ndig und idempotent.

## Nicht Teil dieses Vorcodepakets

- keine Ã„nderung an `NotificationBell.jsx`
- keine Ã„nderung an AuthContext/App/API/shared Hooks
- keine Backend-/Schema-/RouterÃ¤nderung
- keine Dashboard-Neuerfindung
- kein Browser-/Build-/DB-/Recoverylauf
- keine privaten Daten oder Secrets.

Der nÃ¤chste Implementierungsschritt sollte erst erfolgen, nachdem Root den
serverseitigen Inbox-/Read-State-Vertrag festgelegt hat.
