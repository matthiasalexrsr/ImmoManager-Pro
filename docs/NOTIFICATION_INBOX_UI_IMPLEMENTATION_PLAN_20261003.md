# Notification Inbox UI – Implementierungspräzisierung

Stand: 03.10.2026

Diese Datei präzisiert die bereits zentral geprüfte NotificationBell-
Vorcodeanalyse für ein **unverdrahtetes Frontend-Unterpaket**. Sie ändert
weder die globale NotificationBell noch Backend-/Sharedsource.

## Fester additive Clientvertrag

Der neue Client verwendet ausschließlich den vorgeschlagenen Inboxvertrag.

### GET /notifications/inbox

Query:

- status, im Bell-Paket zunächst fest `unread`
- after optional
- limit, Default 10

Keine Offsetpagination und kein FakeTotal.

Response:

```text
{
  items: NotificationInboxItem[],
  full_count: integer,
  unread_count: integer,
  has_more: boolean,
  next_cursor: string | null,
  snapshot_token: string,
  actions: {
    mark_all_read: boolean
  }
}
```

Für `status=unread` erwartet der Client:

- `full_count == unread_count`
- beide Counts dürfen größer als `items.length` sein
- `has_more=true` verlangt einen opaken `next_cursor`
- `has_more=false` verlangt `next_cursor=null`.

Folgeseiten müssen denselben `snapshot_token`, `full_count` und
`unread_count` wie Seite 1 liefern. Item-IDs dürfen sich nicht wiederholen.

### NotificationInboxItem

Erlaubte Felder:

- id
- notification_type
- title
- content
- severity
- entity_type null|string
- entity_id null|string
- created_at
- read_at null|string
- actions.mark_read boolean

Die UI leitet **keine** persönliche Read-Berechtigung aus Rolle oder
`write_permissions` ab. Maßgeblich ist ausschließlich
`item.actions.mark_read`.

### POST /notifications/inbox/{id}/read

Kein allgemeines Notification-PATCH im neuen Paket.

Mindestresponse:

```text
{
  item: NotificationInboxItem,
  unread_count: integer
}
```

Auch ein Readonly-Actor darf die Aktion ausführen, wenn der Server
`actions.mark_read=true` geliefert hat.

Nach Erfolg wird die Inbox frisch geladen; der Badge wird nicht lokal um eins
verringert.

### POST /notifications/inbox/mark-all-read

Request:

```text
{
  snapshot_token: string,
  idempotency_key: uuid
}
```

Response:

```text
{
  marked_count: integer,
  unread_count: integer,
  snapshot_token: string
}
```

Die UI sendet **einen** Command. Keine Schleife über sichtbare Items.

Bei verlorenem Netzwerk-/5xx-Ausgang wird genau derselbe eingefrorene Command
mit demselben Idempotenzschlüssel erneut angeboten. Bei 409 wird nicht still
mit einem neuen Snapshot wiederholt.

## Frisches /auth/me-Gate

Jede Veröffentlichung privater Inboxdaten läuft durch:

1. aktuellen Render-Principal bestimmen,
2. alten aktiven Request aborten,
3. sichtbaren Inboxzustand sofort neutral/loading setzen,
4. `GET /auth/me`,
5. frischen Principal aus der Antwort bilden,
6. stimmt er nicht mit dem Render-Principal überein:
   - `AuthContext.updateUser(freshUser)`
   - keine Inboxantwort unter der alten Bindung laden/veröffentlichen,
7. nur bei identischer Bindung `GET /notifications/inbox`,
8. vor Veröffentlichung erneut Generation, Principal und Serviceidentität
   prüfen.

Principal-Key enthält:

- user.id
- role
- portfolio_access
- portfolio_access_origin
- sortierte portfolio_ids
- sortierte write_permissions

`write_permissions` ist nur Bestandteil der Actorbindung. Es steuert **nicht**
die persönlichen Read-Actions.

## Render-synchrone Neutralisierung

Hook-State trägt seine Bindung mit:

- principal
- service identity

Wenn die aktuelle Renderbindung davon abweicht, gibt der Hook sofort einen
neutralen Zustand zurück, noch bevor der neue Effect läuft.

Damit kann beim Actor-/Grantwechsel kein alter Badge, Titel oder Inhalt einen
Render lang sichtbar bleiben.

## Hookzustände

Mindestens:

- idle
- loading
- ready
- error
- unknown_mark_all

Ready enthält:

- items
- fullCount
- unreadCount
- hasMore
- nextCursor
- snapshotToken
- page actions

Error enthält **keine** alten privaten Items/Counts.

### Fehler

401/403/404:

- private Daten neutral
- Zustand access/error
- keine alten Titel/Counts.

Netzwerk/5xx:

- Zustand unavailable/error
- kein Fake-0
- kein letzter Erfolg
- Retry lädt frisch über /auth/me.

Abort:

- kein Fehlerzustand
- keine Late Completion.

## Cursorseiten

`loadMore`:

- führt erneut das /auth/me-Gate aus,
- verwendet `after=next_cursor`,
- erwartet denselben Snapshot,
- hängt nur disjunkte Items an,
- hält Counts aus dem Serververtrag unverändert.

Es wird kein vollständiger Stockbestand geladen.

## Mark-read

Button wird nur für `actions.mark_read=true` gerendert.

Ablauf:

1. frisches /auth/me
2. persönlicher Read-Command
3. Response validieren
4. gesamte Inbox frisch über /auth/me neu laden

Keine lokale Count-Schätzung.

## Mark-all

Button wird nur für `page.actions.mark_all_read=true` gerendert.

Unknown:

- sichtbare alte Inbox wird nicht als aktuell weitergeführt
- eingefrorener Command bleibt intern erhalten
- UI bietet „Unverändert erneut senden“.

Konflikt 409:

- kein Exact Retry
- UI fordert frisches Laden an.

## Unterkomponenten

Neu, aber global noch unbenutzt:

- `features/notificationInbox/notificationInboxApi.js`
- `features/notificationInbox/notificationInboxModel.js`
- `features/notificationInbox/useNotificationInbox.js`
- `features/notificationInbox/NotificationInboxPanel.jsx`
- `features/notificationInbox/NotificationInbox.css`
- lokale DE/EN/ES-Copy

`NotificationBell.jsx` bleibt unverändert.

## Reine Tests in diesem Paket

Erlaubt:

- Validator-/Modeltests
- Hooktests mit gemocktem Service
- reine Komponentenrender-/Keyboardtests
- gezielter ESLint / Syntaxchecks

Nicht in diesem Slot:

- Browser
- Produktionsbuild
- Backend
- DB
- Recovery
- globale Bell-Aktivierung

## Abnahmegrenzen

Dieses Paket beweist ausschließlich, dass das Frontend den geplanten Vertrag
korrekt konsumieren kann.

Es beweist **nicht**, dass die neuen Endpoints existieren oder serverseitig
korrekt implementiert sind. Root aktiviert die globale Glocke erst nach
zentraler Backendimplementierung und gemeinsamer Rechte-/Browserabnahme.

## Präzisierung: fortsetzbares Mark-all bleibt Backendvertrag

Der parallele Domainentwurf kann Mark-all als fortsetzbare Aktion bzw. Job modellieren. Dieses Frontendpaket erfindet dafür **keinen** Job-Endpunkt, keine Pollingroute und keinen clientseitigen Snapshot aus Datum/UUID.

Für den vorliegenden vorgeschlagenen Defaultvertrag gilt:

- `snapshot_token` kommt ausschließlich aus `GET /notifications/inbox` und wird opak behandelt;
- `idempotency_key` identifiziert nur den Mutationcommand und ist kein Snapshot;
- der Default-API-Adapter akzeptiert bei Mark-all nur den ausdrücklich dokumentierten terminalen Response mit `marked_count`, `unread_count` und serverseitigem `snapshot_token`;
- eine andere/fortsetzbare Response wird **nicht** als Erfolg interpretiert, sondern als noch nicht abgestimmter Backendvertrag behandelt;
- Hook und Komponente sprechen Mark-all ausschließlich über die injizierbare Servicegrenze an. Sobald der Backend-Handoff einen Job-/Continuation-DTO festlegt, wird nur diese Adaptergrenze erweitert; die UI erfindet bis dahin keine Zustandsmaschine oder Pollingroute.

Auch für Readonly gilt weiterhin: persönliche `mark_read`-/`mark_all_read`-Fähigkeit kommt ausschließlich aus den serverseitigen `actions`, nicht aus allgemeinen Fach-`write_permissions`.
