# NotificationBell – Vorcodeanalyse und sicherer Inbox-Vertrag

Stand: 03.10.2026  
Checkout: `work/financial-workspace-browser-qa`  
Branch: `assist/financial-workspace-browser-qa`

Dieses Dokument ist eine **reine Vorcodeanalyse**. Es wurden keine
NotificationBell-, Auth-, API-, Dashboard-, Backend- oder Sharedsource-Dateien
geändert und kein Browser-/Build-/Backend-/DB-Lauf gestartet.

## Ausgangsbefund

Im echten B2-Rechteentzug wurde ein stale Badge `10` in der globalen
NotificationBell beobachtet, während Dashboarddaten bereits korrekt verborgen
waren.

Die aktuelle Rootquelle
`frontend/src/components/NotificationBell.jsx` bestätigt vier Ursachen:

1. `GET /notifications?status=unread&limit=10` lädt nur die erste Seite.
2. `unreadCount = items.length` macht die ersten maximal zehn Datensätze zum
   angeblichen Gesamtcount.
3. Fetchfehler loggen nur eine Warnung. Vorherige Items und Badge bleiben als
   alter „Erfolg“ sichtbar.
4. `markAllRead` iteriert ausschließlich über die aktuell geladenen maximal
   zehn Items.

Zusätzlich:

- laufende Fetches werden weder bei Unmount noch bei neuer Abfrage abgebrochen;
- die Glocke ist nicht an einen Actor-/Grant-Key gebunden;
- das 60-Sekunden-Intervall ist die einzige regelmäßige Aktualisierung;
- Öffnen, Window-Focus oder Visibility-Änderung erzwingen keine frische
  Autoritätsprüfung.

## Tatsächlich geprüfte Auth-/API-Mechanismen

### AuthContext

`AuthContext` hält den frisch von `/auth/me` geladenen User inklusive Rolle,
Portfoliozugriff und Write-Permissions.

### Sessionwechsel

`api.watchSessionChange(...)` beobachtet:

- Access-/Refresh-Tokenänderungen im Storage,
- `immomanager-session-change`.

`ProtectedRoute` reagiert darauf mit:

- sofortigem `clearUser()`,
- Navigation zu Login oder Full Reload,
- anschließend frischem `GET /auth/me`.

Damit werden **Actor-/Sessionwechsel** bereits zentral sicher neutralisiert.

### Was nicht existiert

Es gibt **kein** allgemeines Frontendevent für einen serverseitigen
Rollen-/Portfolio-Grantwechsel innerhalb derselben noch gültigen Session.

Ein solcher Rechteentzug wird erst bei einer neuen autorisierten Anfrage sichtbar.
Darum darf die NotificationBell nicht darauf vertrauen, dass sich ihr
`AuthContext.user` vor dem nächsten Inbox-Request ändert.

### API-Fehler

Der gemeinsame API-Client liefert strukturierte Fehler mit `statusCode`.

- 401 invalidiert nur das tatsächlich verwendete aktuelle Tokenpaar und führt
  bei notwendigem Logout zu Login.
- 403/404 bleiben normale autorisierte Ressourcenfehler.
- Netzwerkfehler sind als `isNetwork` markiert.
- AbortError wird unverändert durchgereicht.

Für private Glockendaten bedeutet das:

- 401/403/404 dürfen nie einen alten Badge/Listenzustand als aktuellen Erfolg
  stehen lassen;
- Netzwerk/5xx dürfen ebenfalls nicht als „alter Erfolg“ dargestellt werden;
  der Zustand ist dann **unbekannt/nicht verfügbar**, nicht `0` und nicht der
  vorherige Count.

## Tatsächlich geprüfte Notification-Sichtbarkeit

### Legacy Notifications-Router

Aktuell:

`GET /notifications?skip=&limit=&status=`

liefert `list[Notification]`.

Er filtert:

- über den Store/Portfolio-Scope,
- zusätzlich über `notification_visible(...)` für Dispatch-Zielrollen,
- anschließend per Status/Typ/Severity,
- dann über `skip:skip+limit`.

Er liefert **keinen**:

- vollständigen Count,
- opaken Cursor,
- Snapshot-/Sourcehash,
- atomischen „alle gelesen“-Command.

### Dashboard ist die Referenzsemantik

`dashboard_summary.py` besitzt bereits die richtige Kombination:

1. `scoped_clause(notifications, scope)`
2. Dispatch-/Rollenregel über `_notification_clause(...)`
3. vollständiges `unread_notifications`-Count
4. stabile Notification-Seite
5. opake Cursorbindung mit:
   - Actor-ID
   - Rolle
   - unrestricted
   - Portfolio-Hash
   - Seitengröße
   - Sortierdefinition

Der Inbox-Vertrag darf **keine parallele Sichtbarkeitsfamilie** implementieren.
Die vorhandene Dashboard-/Portfolio-Scope-Prädikatlogik muss geteilt bzw.
extrahiert und wiederverwendet werden.

## Aktuelle Read-Semantik – wichtige Grenze

`Notification.status` und `read_at` liegen heute **global am
Notification-Datensatz**.

Es existiert kein per-user Read-State.

Daraus folgt:

- Ein Bell-Fix darf nicht behaupten, bereits eine persönliche Benutzer-Inbox mit
  unabhängigen gelesen/ungelesen-Zuständen zu besitzen.
- Ein serverseitiges „alle gelesen“ in diesem Paket behält die heutige globale
  Notification-Read-Semantik.
- Falls zukünftig per-user Read-State gewünscht ist, benötigt das ein eigenes
  Modell/Migration/API-Paket und darf nicht still in die Bell eingebaut werden.

## Empfohlener additiver Inbox-Vertrag

Die folgenden Namen sind ein **Planvorschlag**, keine heute vorhandenen
Endpoints.

### GET /notifications/inbox

Zweck:

- kleine globale Bell-Inbox,
- nur aktuell autorisierte ungelesene Notifications,
- vollständiger Badgecount,
- begrenzte Seite.

Query:

- `after: string | null` – opaker Cursor
- `source_hash: string | null` – bei Folgeseiten verpflichtend
- `page_size` – bounded, Default für Bell 10; Serverbudget begrenzt

Kein `skip`.

### NotificationInboxPage

Vorgeschlagene Response:

```text
{
  items: NotificationInboxItem[],
  unread_count: integer,
  has_more: boolean,
  next_cursor: string | null,
  source_hash: sha256,
  scope_hash: sha256
}
```

`NotificationInboxItem` enthält nur die Bell-Felder:

- id
- title
- content
- severity
- notification_type
- entity_type
- entity_id
- created_at

Kein unbeschränkter privater Entity-Snapshot.

### unread_count

`unread_count` ist die **vollständige Anzahl aller aktuell sichtbaren
ungelesenen Notifications**, nicht `items.length`.

Es gilt dieselbe Sichtbarkeit wie Dashboard:

- aktueller Portfolio-/Resource-Scope,
- aktuelle Dispatch-/Rollenregel,
- Status `unread`.

Count und Seite entstehen aus derselben konsistenten Sicht.

Keine Bestandsobergrenze.

### Reihenfolge

Stabil und deterministisch:

- `created_at DESC`
- danach bytewise `id DESC`

Die Bell zeigt damit die neuesten Notifications zuerst.

### source_hash

Hash über die aktuell sichtbare ungelesene Menge und relevante sichtbare
Notificationfelder.

Zweck:

- Folgeseite erkennt zwischenzeitlich geänderten Inboxbestand,
- Mark-all kann exakt an den vom Benutzer gesehenen Bestand gebunden werden.

Bei Folgeseite mit altem Hash:

- 409 „Benachrichtigungen haben sich geändert. Bitte neu laden.“
- kein Teilresultat als aktuell veröffentlichen.

### scope_hash

Opaque Hash aus der frisch serverseitig geprüften Autoritätsbindung, mindestens:

- Actor-ID
- Rolle
- unrestricted
- sortierte Portfolio-Grants

Keine Grants im Klartext in der Response.

Cursor bindet an:

- Actor-/Scope-Hash
- Status = unread
- page_size
- source_hash
- Sortierdefinition

Ein Cursor eines alten Actors/Scopes ist damit nicht wiederverwendbar.

## Server-Command „alle gelesen“

Das heutige Client-Loop über zehn IDs ist nicht korrekt.

Vorgeschlagen:

`POST /notifications/inbox/read-all`

Request:

```text
{
  idempotency_key: uuid,
  expected_source_hash: sha256
}
```

Semantik:

1. frische Auth-/Portfolio-/Rollenprüfung;
2. aktuellen sichtbaren ungelesenen Inboxbestand bestimmen;
3. wenn Hash nicht dem erwarteten Snapshot entspricht: 409, **keine Writes**;
4. alle Notifications dieses exakten autorisierten Snapshots atomisch auf
   heutigen globalen `read`-Status setzen;
5. keine später hinzugekommenen Notifications markieren;
6. Idempotency-Receipt ermöglicht Exact Retry nach verlorener Antwort;
7. Replay prüft Auth/Scope frisch, bevor ein alter Receipt zurückgegeben wird.

Response:

```text
{
  updated_count: integer,
  unread_count: integer,
  source_hash: sha256,
  scope_hash: sha256
}
```

`unread_count` ist der echte Zustand nach dem Command; er muss nicht zwingend
null sein, falls inzwischen neue Notifications entstanden sind.

## Einzelne Notification als gelesen

Der bestehende `POST /notifications/{id}/read` kann prinzipiell weiterverwendet
werden, sollte aber serverseitig dieselben aktuellen Scope-/Dispatchregeln und
die `communication`-Writeberechtigung erzwingen.

Heute schützt primär die UI über `useWriteAccess('/notifications')`; der
neue sichere Vertrag darf Mutationserlaubnis nicht nur dem Client überlassen.

Nach erfolgreichem Einzel-Read:

- keine lokale `unreadCount--`-Schätzung,
- Inboxseite/count frisch serverseitig laden.

## Geplante sichere Bell-Bedienung

### Renderbindung

NotificationBell erhält `useAuth()` und bildet einen Principal-Key aus:

- User-ID
- Rolle
- Portfoliozugriff
- Portfolio-IDs
- Write-Permissions

Bei einer abweichenden Renderbindung:

- Items sofort neutral,
- Badge sofort neutral,
- geöffnetes privates Dropdown schließen,
- alte Requests aborten.

Kein alter Actorname/Count darf bis zum Effect sichtbar bleiben.

### Gleiche Session, serverseitiger Grantwechsel

Weil heute kein globales Grant-Change-Event existiert, führt die Bell eine
frische Inboxprüfung aus bei:

- Mount,
- Öffnen der Bell,
- `window.focus`,
- `visibilitychange` auf sichtbar,
- bestehendem periodischem Intervall.

Eine solche autoritätssensitive Prüfung darf den alten privaten Count nicht als
sicher aktuellen Wert weiteranzeigen.

Während der frischen Prüfung:

- Badge nicht mit altem Wert darstellen;
- bei geöffneter Bell neutralen „wird geprüft“-Zustand zeigen.

### Fehlerzustände

#### 401/403/404

Sofort:

- Items löschen,
- Badge löschen,
- Dropdown schließen oder neutralen Zugriff-geändert-Zustand zeigen,
- laufende alte Requests aborten.

Keine Retryanzeige mit alten privaten Items.

#### Netzwerk / 5xx

- alten Badge/Items **nicht** weiter als aktuell zeigen;
- Zustand = „Benachrichtigungen derzeit nicht verfügbar“;
- manuelle Retry-Aktion im Dropdown;
- nicht als `0 ungelesen` darstellen.

#### Abort

- kein Fehlertext;
- alte Completion ignorieren;
- neuer Request besitzt Generation/Ticket.

### Paging

Bell lädt initial nur `page_size=10`, Badge kommt aus `unread_count`.

„Weitere laden“:

- verwendet `next_cursor + source_hash`,
- ersetzt nicht den vollständigen Count,
- speichert nur die tatsächlich geladenen bounded Seiten,
- keine unbeschränkte Stockliste.

Optional kann der Dropdown bei kleinem Bell-Design nur Seite 1 darstellen; dann
muss trotzdem der Badge aus `unread_count` kommen. Mark-all bleibt vollständig
serverseitig.

### Mark-all UI

Button nur wenn:

- Inbox frisch und erfolgreich geladen,
- `unread_count > 0`,
- aktueller User serverseitig zur Communication-Mutation berechtigt.

Während Command:

- Button busy,
- kein paralleler Mark-all.

Unknown/Lost Reply:

- exakt derselbe `idempotency_key + expected_source_hash` erneut senden;
- keine neue Hashannahme erzeugen.

409:

- Inbox neu laden,
- Benutzer entscheidet erneut über Mark-all.

## Warum Dashboard nicht einfach kopiert wird

Dashboard ist die **Semantikreferenz**, aber die Bell soll nicht den kompletten
Dashboard-Summary-Endpunkt pollen.

Stattdessen:

- Scope-/Notification-Prädikate und Cursorbindung gemeinsam nutzen,
- dedizierte kleine Inbox-Projektion für Bell-Count/Page,
- keine zweite Rechte- oder Countlogik.

## Tests für ein späteres Implementierungspaket

Noch nicht ausgeführt, nur geplant:

### Backend

- >10 sichtbare ungelesene Notifications: Seite 10, `unread_count` vollständig.
- >eine Cursorseite: disjunkte IDs, stabiler Sort, kein Bestandscap.
- Grantentzug zwischen Seite 1/2: alter Cursor 403/422/409 gemäß Vertrag, keine
  Daten des alten Scopes.
- Dispatch-Rollenfilter identisch zu Dashboard.
- Portfolio-/entity-bound Notification verschwindet nach Grantentzug aus Count
  und Seite.
- ungebundene Notification folgt bestehender Resource-Grant-Semantik.
- Mark-all bearbeitet >10 vollständig.
- Mark-all mit altem Hash: 409, keine Teilwrites.
- verlorene Mark-all-Antwort + Exact Retry: gleicher Receipt, keine späteren
  Notifications zusätzlich markieren.
- readonly / fehlende communication-Writeberechtigung: Mutation 403.

### Frontend

- Badge 37 bei 10 geladenen Items.
- Fetch 403 nach vorherigem Badge 10: Badge/Items sofort neutral.
- Netzwerk/5xx: kein alter Badge als Erfolg.
- Actor-/Principalwechsel: erster Render bereits neutral.
- Requestabbruch verhindert Late Completion.
- Focus/Visibility/Open triggert frische Autoritätsprüfung.
- Mark-all ruft genau einen serverseitigen Command auf, keine 10er-Schleife.
- Sourcehash-409 zeigt Reload statt lokaler Countkorrektur.
- Tastatur: Bell, Items, Retry, Mark-all erreichbar; Escape schließt.
- 320/360: Badge/Dropdown ohne horizontales Überlaufen.

## Nicht Bestandteil dieser Analyse

- keine Änderung an Root-Dashboardfamilie,
- keine Änderung an NotificationBell,
- keine Backendimplementation,
- keine Migration für per-user Read-State,
- keine Browser-/Build-/DB-/Recovery-Prüfung,
- keine privaten Daten oder Secrets.

## Empfohlene Aufteilung für Umsetzung

1. Backend: gemeinsame Notification-Visibility-Hilfe aus Dashboard/Operational-
   Schedule extrahieren und Inbox-/Mark-all-Vertrag implementieren.
2. Frontend: Bell an Principal/Abort/Inbox-DTO binden.
3. Root: Rechteentzug-B2 + >10-Badge + Mark-all + Errorzustände gemeinsam
   browserprüfen.

Ohne den serverseitigen vollständigen Count und atomischen Mark-all-Command ist
ein reiner Bell-Frontendfix bewusst **nicht** als vollständig korrekt anzusehen.
