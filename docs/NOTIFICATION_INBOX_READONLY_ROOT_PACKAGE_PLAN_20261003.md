# Phase-A Inbox: additive Root-Anschlussquellen

## Freigabe und Ausgangspunkt

Dieses Paket basiert auf dem sauberen Root `febf902`, im eigenen Checkout
`work/encrypted-runtime-factory`, Branch `assist/notification-inbox-readonly`.
Der bisherige Factorybranch bleibt erhalten. Der Merge `00c8d3b` übernimmt die
Root-Factory einschließlich ihrer ergänzten festen Handlungsmeldung bytegleich.
Root bleibt unverändert. Maßgeblich ist
`NOTIFICATION_INBOX_ROOT_COMPOSITION_PLAN_20261003.md`.

Vorcodeplan: kein Runtimeimport, keine App, HTTP-, SQLite-, PostgreSQL-, Browser-,
Build- oder Testausführung. Dieses Paket enthält vorbereitete Quellen und Tests;
es behauptet keine neue native Abnahme.

## HTTP-Vertrag vor Implementierung

Die neue eigene Routerdatei stellt ausschließlich `GET /notifications/inbox`
bereit. Sie verwendet den tatsächlichen `require_auth` wie `/auth/me`, den
tatsächlichen `get_store` als Dependency und `CheckedPublicationRoute` für die
abschließende Veröffentlichungsprüfung. Das UserRead aus der echten Auth-
Dependency muss dieselbe aktuelle PortfolioScope erzeugen, die der SQL-Service
frisch aus der tatsächlichen SQLUserStore desselben Datenbankbestands überprüft.
Dieses DTO ist keine Schreibberechtigung.

Ein HTTP-Querymodell erbt den bestehenden strikten `InboxQuery`-Vertrag und
erlaubt nur für `limit` das Parsen des HTTP-Strings. Danach wird wieder der
unveränderte strikte Domainquery konstruiert. Default 10, maximal 100 Zeilen pro
Seite; die Grenze betrifft die Ausgabe, niemals die Gesamtzahl. Extra-Felder,
Actor-, Authority-, Action- oder Snapshotparameter sind verboten. Filter und
Cursorgrenzen bleiben die bestehenden Domainwerte.

Der Handler ruft ausschließlich die tatsächliche `list_inbox` mit
`read_actions_enabled=False` auf. Vollständige persönliche Counts, Live-Keyset,
same-database Auth, Scope und target_role kommen aus dieser Quelle. Keine
Bestandsliste, Ersatzcounts, lokalen Permissiongetter oder Memory-Fallbacks.
`actions.mark_read` und `actions.mark_all_read` bleiben false. Kein POST, PATCH
oder sonstiger Readcommand; keine CommitAuthorityquelle.

Erfolg und eigene 503-Antworten tragen private/no-store und Vary Authorization.
Nur die beiden festen Domain-503-Codes für fehlende/defekte Familie oder
ungeeignete Persistenz werden in ein festes HTTP-Envelope übersetzt, damit der
zentrale bestehende HTTPException-Handler sie nicht stringifiziert. Keine
Exceptionwerte, Pfade, Datenbanknamen, Schlüssel oder Provideraktionen in der
Antwort. Andere Fehler behalten die zentrale Behandlung.

Root muss den Router vor dem bestehenden Notifications-Router einhängen:
dessen `/{notification_id}` kann sonst `/inbox` aufnehmen. Der neue Router hat
bereits den vollständigen Prefix, daher keine doppelte `/notifications`-Ebene.

## Reservierte Familie und Migration

Root hat ausdrücklich `m2a2b3c4d5e6` mit `down_revision=l2a2b3c4d5e6` reserviert.
Die tatsächliche L2-Datei aus TEHA `150aa66` nennt exakt diese L2-Revision und
K2 als Vorgänger. L2 ist noch nicht in der febf902-Basis enthalten. Die neue
M2-Datei bleibt deshalb in `backend/db/migrations/proposals/`, außerhalb der
Alembic versions-Autodiscovery. Root aktiviert L2/M2 gemeinsam nach seiner
L2-Recoveryreview; dieses Paket verändert keinen aktiven Schemahead.

Die Vorlage erstellt nur `notification_read_states`: zusammengesetzter PK
actor_id/notification_id, nichtleere Stringidentitäten, native CASCADE-FKs zu
users/notifications und erforderlicher timezone-loser DateTime read_at. Kein
Default, Backfill oder Übernehmen des globalen Notification.read_at. Native
SQLite und PostgreSQL sind die unterstützten Ziele. Bestehende Familie wird
nicht gestempelt, ergänzt oder ersetzt. Downgrade verweigert jede vorhandene
Readzeile, bevor es die leere geprüfte Familie entfernt.

Die bestehenden Notification-/Dispatch-Zeitdefaults bleiben unverändert. Der
offene Domain-Nachweis für tatsächliches PostgreSQL func.now ist keine
Freigabe zu einer Timestampmigration oder Altzeitkorrektur.

## Recovery- und Structuralvalidator-Vorschlag

Die vorhandene reine `validate_notification_inbox_database(connection,
deadline=...)` ist die einzige Prüflogik. Eine eigene reine Anschlussfunktion
delegiert zu ihr, ohne Auth-, Settings-, ORM-, Store- oder Appimport. Vollständig
fehlende Familie liefert false; eine vorhandene beschädigte Familie oder ein
fehlender tatsächlicher User-/Notificationparent bricht ab. Keine DDL/DML,
Reparatur, Löschung, Sessionrotation oder Globalread-Umdeutung.

Root ordnet das false-Ergebnis ausschließlich einem vollständig nachgewiesenen
Vor-M2-Archivprofil zu. M2/current verlangt die Familie. Der Adapter entscheidet
keinen Schemahead und erteilt kein allgemeines allow_missing. Die Prüfung muss
auf derselben bereits geöffneten Archiv-/Zielconnection vor Recoverymutationen
erfolgen. Persönliche Readzeilen und erste read_at-Werte bleiben im vollständigen
Archivcontainer erhalten.

## Exakte Root-Anschlussliste außerhalb dieses Pakets

1. L2/M2 aktivieren, danach zentrale erwartete Revision/Schemahead aktualisieren;
   keinen Runtime-DDL-Pfad oder Startup-create_all in Produktion einführen.
2. Modellfamilie vor Schema-/Fullcontainer-Metadatenauswertung registrieren;
   Routerserviceimport registriert ORM-Metadata ebenfalls und darf die zentrale
   Reihenfolge nicht zufällig bestimmen.
3. `notification_read_states` in die zentrale INTERNAL-Klassifikation aufnehmen:
   zusammengesetzter PK ohne id, persönliche Actorbindung, kein generischer
   Portfolio-/CRUD- oder exportierter fremder Readbestand. INTERNAL allein ist
   keine Exportberechtigung.
4. Structuralvalidator und Fullbackup-/Restore-Prüfung eng nach Profil einhängen;
   vollständige frühere Familieabsenz erlauben, Partialfamilien niemals.
5. Nur aktuelle Zielreferenzkataloge nach tatsächlicher M2-Migration erzeugen;
   eingefrorene historische 126-Kataloge bleiben bytegleich. Native Constraints,
   CASCADE, Tabellenpolitik und vollständige Archivdaten bleiben geprüft.
6. Router vor dem alten Notifications-Parameterpfad montieren. Root-owned
   Startup-, Registry-, Auth-, portfolio_scope-, Recovery- und CI-Dateien bleiben
   hier unverändert.

## Vorbereitete spätere Abnahme

Eigene vorbereitete HTTPfälle verwenden reale Auth/UserStore, echte SQL-Seiten,
same-database Scope und tatsächliche get_store-Bindung in synthetischen Temp-
Installationen. Sie prüfen Querystringlimit, vollständige persönliche Counts
über 100, getrennte Benutzerreads, feste false-Aktionen, keine Bestandsliste,
Memory-/Fremddatenbank-/fehlendeFamilie-503, private Antworten und fehlende
Writeendpunkte. Keine Dependency-Overrides für Auth oder ersetzte Permission-
Getter. Ein echter Grantwechsel vor Veröffentlichung muss die Antwort verweigern.

Migrationstests führen die Vorlage später mit tatsächlichem Alembic Operations-
Kontext aus, prüfen native FKs und Composite-PK, bytegleiche globale Notification-
Werte, CASCADE, Wiederanlegeverweigerung und verlustfreien Downgradeabbruch.
Reine Recoverytests prüfen Altabsenz, vollständige persönliche Fakten, echte
Orphans/defekte Shape, Deadline und ausschließlich lesende Prüfstatements.

Diese Tests werden jetzt nur vorbereitet. Root koordiniert später einzeln HTTP,
SQLite, PostgreSQL, aktuelle Schemahead-/Fullcontainer-Komposition sowie pure
Importgrenzen. Offene CommitAuthority und positive Readschreibaktivierung bleiben
ein getrenntes Paket; kein Phase-A/L-/A-L-Gesamtclaim.
