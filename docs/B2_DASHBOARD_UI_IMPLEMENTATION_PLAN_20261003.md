# B2: vollständige Dashboardübersicht mit klaren Zuständen und Objektkontext

Vor-Code-Plan und tatsächlicher Vertragsabgleich, 03.10.2026. Eigener Checkout
`work/bounded-dashboard-ui`, Branch `assist/bounded-dashboard-ui`, exakt ab
sauberem Rootcommit `5dc35efa424b75b73b5c02ca09499b0758269a72`. Der abgeschlossene
C-Checkout bleibt sauber erhalten. Dieser Commit enthält ausschließlich den
Plan; B1 ist noch nicht zur Produktkomposition freigegeben. Umsetzung beginnt
erst nach Rootübernahme der tatsächlich geprüften, sauberen B1-Basis.

Root hat den ersten Slice ausdrücklich bestätigt: drei vollständige,
fortsetzbare Hinweisgruppen über die vorhandene Summaryroute; höchstens ein
bewusst ausgewählter Detailkontext mit genauen Eltern; unveränderte B1-DTOs;
getrennte Finanzberichte ohne behaupteten gemeinsamen Snapshot. Keine weitere
Backendprojektion und keine Backendänderung während B1-Gates.

## Tatsächlich gelesene Grundlagen und Grenzen

- Gesamtrahmen `docs/IMPLEMENTATION_ROADMAP_20261003.md` vollständig gelesen:
  vollständige sichtbare Bestände, echte Fehler, Scope-/Revisionsschutz,
  320/360/1440 und Tastatur. B2 beendet weder ganz B noch A–L.
- Rootquelle: `Dashboard.jsx`/CSS, `DashboardHome.test.jsx`, vorhandener
  `e2e/dashboard.pw.mjs`, App-Routen, AuthContext/ProtectedRoute/APIclient,
  vorhandene private Read-/Principalpattern, NotificationBell, Tasks/Contracts,
  Unitworkspace und tatsächliche Einzel-GETs/Modelle.
- B1 read-only aus `work/legacy-sqlite-upgrade` bei HEAD `c924cf1`, einschließlich
  uncommitteter `dashboard.py`, `dashboard_summary.py`, Vorcodeplan und
  tatsächlicher Memory/SQLite-/Authority-/PG-Testquellen. Keine Quellen kopiert,
  keine Tests ausgeführt, keine lokale B1-Verfügbarkeit behauptet.
- Gelesene B1-Dateien SHA256: Router
  `a36b4ac06713d892ec5ab664e71afea116dca03ed2c8689b740d04f9a69f4b66`,
  Service `597d2b9928c1f4e34cb85c90b85a07615ab88bbc4679e0db62265cf0a80be16d`,
  Plan `81ea8c43642fa49cc3219f346ee3e8c0863a3b55d555647158a3d5fad36f7e32`.
  Dies kennzeichnet einen gelesenen Arbeitsstand, keinen freigegebenen Commit.
  Den tatsächlichen sauberen B1-Contract vor Code erneut abgleichen.

## Vorher und beabsichtigtes Verhalten

| Nachgewiesene aktuelle UI | B2-Verhalten |
| --- | --- |
| `/units` über `api.getAll` nur für Belegung und Leerstand | Ausschließlich vollständige `occupancy` aus Summary; kein Einheitengesamtbestand im Dashboardbrowser |
| Aufgaben und Meldungen getrennt geladen; bis fünf Zeilen, keine Fortsetzung | Sichere B1-Hinweisprojektionen, vollständiges `total`, explizite Vor-/Zurück-/Erstseite |
| Vollständiger `/reports/contracts-expiring?days=90`, anschließend `slice(0,5)` | Bereits serverseitig begrenzte `work_hints.expiring_contracts` mit echtem Cursor |
| Aufgaben werden nachträglich im Client sortiert | Unveränderte tatsächliche Serverordnung; ID-Gleichstände und NULL-Daten erhalten |
| Belegung und Bestandszahlen stammen aus verschiedenen Requests | `occupancy`, Statuscounts und alle drei Hinweisgruppen aus genau einer validierten Summaryantwort |
| Erfolgreich geladene Daten verschwinden bei jeder Aktualisierung; Fehlerstatus verliert numerischen HTTPstatus | Bewusstes Aktualisieren, gealterter letzter Stand und echte Fehler getrennt; Statuscode für Authorityentscheidungen erhalten |
| Hook kennt weder Actor-/Grantkey noch synchronen privaten Cachewechsel | Private Innenansicht an bestehenden `principalKey` binden; Kontext/Requests/Seitencursors beim Identitätswechsel verwerfen |
| Abrechnungsblocker werden als Vorprüfung bezeichnet | Klar begrenzte grundlegende Präsenzbefunde; keine bestandene Fachvorprüfung oder Abschlussfreigabe daraus ableiten |
| Aufgaben-/Vertragslink öffnet nur den jeweiligen allgemeinen Bestand | Bewusst ausgewählter Hinweis zeigt genaue vorhandene Aufgabe/Vertrag und dessen tatsächlich geprüfte Objektzuordnung |
| Historisches `DashboardWorkflow` mischt teilweise Statuszahlen und Geld und füllt Fehler mit Null | Diese aktuell nicht eingebundene Komponente nicht reaktivieren; keine neue Einrichtungsvollständigkeit aus Counts errechnen |

## Unveränderter B1-Vertrag für den ersten Slice

Tatsächlicher Weg: `GET /api/v1/dashboard/stats`. Frontendclient verwendet
`/dashboard/stats`; keine neue Route oder clientseitige Ersatzaggregation.

| Feld | Tatsächliche Bedeutung / UI-Verwendung |
| --- | --- |
| Bisherige flache nichtnegative Integerfelder | Vollständige sichtbare Status-/Bestandszahlen. Vorhandene Statusdefinitionen beibehalten, keine Geldbeträge daraus berechnen. |
| `basis=dashboard-status-v1` | Statusbasis; weder Restbetrag noch Zahlungseingang, keine erfundene Rechnungsabstimmung. |
| `as_of` | ISO-Fachstichtag für B1-Fälligkeit/Eskalation und inklusive 90-Tage-Vertragsfenster. Kein übergreifender Finanzstichtag. |
| `occupancy` | `total,occupied,rented,vacant,reserved,other,basis=stored_unit_status`. `occupied` umfasst occupied+rented; rented ist eine Teilmenge. |
| `billing_presence` | `periods_checked,blockers,warnings,basis=basic_presence_checks,complete_preflight=false`. Blocker zählt betroffene Perioden; Warnung ist kein weiterer Periodenzähler. |
| `work_hints.{tasks,notifications,expiring_contracts}` | Je `total,items,has_more,next_after,source_url`; vollständiges Total bleibt unabhängig von der Seite. |

Taskitem genau `id,title,due_date,priority`; Meldungsitem genau
`id,title,severity,entity_type,entity_id`; Vertragsitem genau
`id,contract_number,end_date,days_remaining`. Taskdatum und Meldungsreferenz
können NULL sein. Freie tatsächlich gespeicherte Prioritäts-/Schwerewerte als
Text erhalten, bekannte Werte übersetzen; keine neue Enumvalidierung erfinden.
Beschreibung, Content, IBAN, Accountdaten oder Journalpayload nicht ergänzen.

Query: `preview_limit` 1–20, erster UIwert 5; `as_of` optional; genau die drei
optionalen Cursorparameter `tasks_after`, `notifications_after`,
`contracts_after`. Cursor sind undurchsichtige serverseitig signierte Tokens,
keine Offsetzahlen. Sie binden Familie, Stichtag, Größe und aktuelle
Actor-/Rollen-/Portfoliogrants. Tokenrotation allein ist kein Grantwechsel.
Keine Portfolio-/Objektfilter an diese Route erfinden; sie zeigt den gesamten
für den aktuellen Zugang freigegebenen Bereich.

Sortierung laut Quelle: Datum aufsteigend, NULL zuletzt, danach byteweise ID.
Meldungen nach gespeichertem Erstellungszeitpunkt; dieser ist absichtlich kein
Anzeigefeld der sicheren Meldungsprojektion. Keine neue Meldungsdatumsanzeige
aus einem nicht gelieferten Feld. Vertragsfenster schließt den Stichtag und
Tag 90 ein und betrifft tatsächlich alle Vertragsstatus.

## Validierung ohne Fehler-als-Null oder Bestandsgrenze

Eigener reiner Parser prüft nur den tatsächlich benötigten bekannten Vertrag;
additive Felder bleiben möglich. Nichtnegative sichere JSONinteger, eindeutige
IDs innerhalb jeder Seite, richtige Feldtypen und echte ISO-Kalendertage.
Keine 100er-/1000er-/10.000er-Obergrenze für Totals. Fehlender/ungeeigneter
Vertrag ist ein sichtbarer Antwortfehler, kein Anlass zum Legacy-Load-all.

- `occupancy.total == unit_count` und
  `occupied + vacant + reserved + other == total`; `rented <= occupied`.
  Flaches `occupied_units` ist ausschließlich occupied und wird nicht als neue
  Gesamtbelegung gelesen. Gelieferte vorhandene Aliase widersprechen dem
  strukturierten Vertrag nicht.
- Belegungsquote nur bei total>0; 0/0 bleibt ein bestätigter Nullbestand mit
  nicht berechenbarer Quote. Vier exklusive Diagrammgruppen, rented nicht als
  zusätzliche fünfte Gruppe doppelt zählen.
- Präsenzbasis und `complete_preflight === false` explizit; vorhandene flache
  Aliaswerte stimmen mit derselben Summaryantwort überein.
- `items.length <= angeforderter preview_limit`; `has_more` ist boolesch.
  Weiter erfordert nichtleere Items und nichtleeres `next_after`; Ende erfordert
  `next_after === null`. Total nicht aus Items ableiten.
- Task-/Meldungstotal stimmt mit `open_tasks`/`unread_notifications` überein.
  Vertragsdaten und days_remaining stimmen mit dem gelieferten `as_of` und
  dem inklusiven 90-Tage-Fenster überein.
- Leere Folgeseite bei inzwischen verändertem Livebestand darf total>0 haben;
  sie bedeutet keine Bestandsleere. Keine eingefrorene Historie über mehrere
  Seiten versprechen.

## Zusammengehörige Requests, Seiten und Aktualisierung

Eine kontrollierte Summarylane besitzt immer genau einen aktuellen Request.
Erste Antwort wählt serverseitig `as_of`; alle Folgeseiten behalten diesen
Stichtag und dieselbe Vorschaugröße. Jeder Seitenschritt sendet die drei
aktuell beabsichtigten Familiencursor in einem Request. Alle drei Hinweise
und Zähler werden aus dieser einen erfolgreichen Antwort atomar veröffentlicht.
Kein Folgerequest darf versehentlich die anderen Panels auf deren erste Seite
zurücksetzen oder Counts einer anderen Antwort unbemerkt beimischen.

Nur explizite Nutzernavigation lädt eine weitere Seite. Ein sichtbarer
Zeilensatz je Familie; Cursorverläufe enthalten nur Tokens, keine angesammelten
Bestandszeilen. Keine automatische Schleife über alle Seiten, keine
Hintergrundhydration. "5 angezeigt · 121 insgesamt" plus tatsächliche Seite
statt behaupteter stabiler Zeilennummern bei beweglichen Keysets.

Seiten- und Cursorverlauf wird erst nach geprüfter Antwort übernommen. Während
Navigation bleiben die tatsächlich angezeigte alte Seite und ihre Labels
zusammengehörig; Busyhinweis und gesperrte Seitentasten vermeiden Doppelaktionen.
Bei Fehler bleibt die fehlgeschlagene beabsichtigte Query für bewussten Retry
erhalten, ohne sie als bereits erfolgreiche Seite auszugeben.

"Übersicht aktualisieren" verwirft alle Familiencursor und lädt erste Seiten
mit neuem serverseitigem Stichtag. Vorschaugrößenwechsel verwirft ebenfalls
alle alten Tokens. Aktueller Cursordecoder liefert 422 und Klartext, keine
`cursor_expired`/`cursor_filter_mismatch`-Codes. Bei einem 422 aus einer
Cursorquery sichtbar "Die Seite ist nicht mehr verfügbar" und ausdrücklicher
Erstseitenneustart; keine verdeckte Retryendlosschleife und kein Leerstand.

Getrennte Reports besitzen ihre eigenen Requests/Retry-/Ladezeiten. Bestehende
cashflow/aging/maintenance/forecast/finance-Werte und Formeln unverändert.
Belegung als sechste Auswertung nutzt Summary. Weitere Auswertungen können
erst bei Wahl des bestehenden Analyse-Tabs laden; benötigte Arbeitsquellen
aging und maintenance bleiben verfügbar, solange die bestehenden Prioritäten
sie verwenden. Adminaudit bleibt bewusst nach Aufklappen. Kein ungeprüfter
Wechsel einer Wartungszählung auf eine abweichende Statusdefinition.

## Echte Zustände und Datenschutzgrenze

| Zustand | Verhalten |
| --- | --- |
| Erstladen ohne Antwort | Ruhiger Busytext/Platzhalter; unbekannte Kennzahl `—`; keine Null, Einrichtungsempfehlung oder Entwarnung |
| Erfolgreiche leere Menge | Genaue Nullzahlen und fachbezogener Leertext ausschließlich aus validierter Antwort; 0/0 ohne Prozentbehauptung |
| Aktualisierung im selben unveränderten Principal | Vorherige Daten als "Stand … · wird aktualisiert" sichtbar; kein Zahlenflackern oder frischer Erfolgshinweis |
| Netzwerk/5xx/ungeeignete Antwort ohne vorherigen Erfolg | Sichtbarer Quellfehler mit Retry; unbekannte Werte; unabhängige erfolgreiche Reports dürfen erscheinen |
| Netzwerk/5xx nach Erfolg im selben Principal | Letzten Stand mit Ladezeit und sichtbarem Stale-/Fehlerhinweis erhalten; keine neue Entwarnung, kein bestätigter neuer Nullbestand |
| 422 einer Cursorquery | Letzte erfolgreiche Ansicht als älterer Stand, konkrete Navigationsstörung, bewusster Erstseitenneustart |
| Actor-/Rollen-/Grantwechsel oder Logout | Privatansicht synchron wechseln/remounten, Requests abbrechen, Werte/Reports/Audit/Kontext/Cursor verwerfen |
| 401/403 einer eigenen Quelle | Private Dashboarddaten unverzüglich verbergen; kein Stalerückfall auf vertrauliche Werte, kein stiller Retryloop |
| 404 eines ausgewählten geschützten Details/Elternkontexts | Zugehörigen Kontext vollständig verbergen, generischer Nichtverfügbarkeitstext ohne fremde Namen; explizites erneutes Prüfen erforderlich |

Bestehenden `principalKey(user)` verwenden (id, Rolle, portfolio_access/origin,
sortierte portfolio_ids/write_permissions); keinen parallelen Authkern,
Tokenparser oder Draftpersistenz bauen. Requestgeneration und AbortSignal
verhindern sowohl verspätete Veröffentlichung als auch denselben Renderframe
mit dem vorherigen Principal. React StrictMode/Unmount mitzudenken.

Root-App prüft `/auth/me` vor Erstauthentisierung und reagiert bereits auf
echten Sitzungs-/Actorwechsel. Eigene Übersichtsaktualisierung und Rückkehr in
einen länger offenen Arbeitsplatz sollen aktuelle Benutzerrechte über den
wirklich vorhandenen `/auth/me`-Weg abgleichen; Änderungen über bestehendes
`updateUser` übernehmen und private Innenansicht erst für den geprüften
Principal laden. Gemeinsame Auth-/APIquellen unverändert. Lokale Kenntnis
eines Grantwechsels und echte HTTPverweigerung sind Prüfzeitpunkte; keine
allwissende sofortige Erkennung beliebiger externer Änderungen behaupten.

"Keine offenen Punkte" und Einrichtungshinweise benötigen frische erfolgreiche
relevante Quellen. Fehlt eine Quelle oder ist sie stale, ausdrücklich
unvollständiger Stand. Erfolgreiches portfolio_count=0 bedeutet "In Ihrem
freigegebenen Bereich sind keine Portfolios sichtbar"; für Readonly/Selected
nicht behaupten, die gesamte Installation sei leer oder dieser Nutzer dürfe
ein neues Portfolio anlegen.

## Objektkontext aus echten Quellen, keine erfundenen Deep-Links

B1 liefert Task-/Vertragshinweisen aktuell keine property_id/unit_id oder
Objektnamen. Diese Information wird nicht aus Titeln geraten und nicht durch
vollständige Einheiten-/Immobilien-/Mieterlisten erzeugt. Rootentscheidung für
den ersten Slice: vorhandene Projektionen unverändert lassen.

Ein ausdrücklich gewählter Hinweis öffnet genau einen eigenen, lesenden
Inlinekontext. Aufgabe über `GET /tasks/{id}`, Vertrag über
`GET /contracts/{id}`. Exakte zurückgegebene ID und benötigte Feldtypen prüfen;
nur Anzeige-/Zuordnungsfelder weiterreichen, keine versteckten Beschreibungs-
oder Personendaten in allgemeinem Dashboardstate halten. Vertrags-/Aufgaben-
Datum oder Status kann sich seit Summary geändert haben: kenntlich machen,
keine stille Überschreibung der ursprünglichen Hinweiszeile.

Danach höchstens dessen genaue Einheit `GET /units/{unit_id}` und genaue
Immobilie `GET /properties/{property_id}`. Einheit muss zur ausgewiesenen
Immobilie gehören; widersprüchliche Zuordnung ist Fehler. Falls eine Aufgabe
nur unit_id besitzt, Immobilie ausschließlich aus diesem geprüften Unitparent
auflösen. Ohne beide Referenzen bestätigtes "Ohne Objektzuordnung". Höchstens
drei Einzelrequests für den bewusst gewählten Task-/Vertragskontext; keine
Requests pro Vorschauzeile. Bei schnellem A→B-Wechsel zuerst A verbergen/
abbrechen; verspätete A-Daten dürfen B nicht ergänzen.

Der Kontext verbindet Aufgabe/Vertragsnummer, Datum/Status, Immobilie und
Einheit. Keine gegenwärtige Mietpartei als historische Identität; für dieses
aktuelle Dashboard keine Tenant-Originalbindung behaupten. Prüfung/Anzeige
des Kontextes schreibt weder Status noch Abrechnung oder Meldungsjournal.

| Tatsächlicher Referenz-/Navigationsweg | Erlaubte UI |
| --- | --- |
| Meldung entity_type=property/unit mit echter entity_id | Bestehende `/properties/:id` bzw. `/units/:id` öffnen |
| Meldung task/contract mit echter entity_id | Gleichen bewusst ausgewählten genauen Inlinekontext verwenden |
| Andere bekannte entity_type mit vorhandener Bestandsseite | Ehrlich benannter Bestandslink, keine behauptete exakte Akte oder aktive Filterauswahl |
| Unbekannte/fehlende Meldungsreferenz | Lesbarer Hinweis ohne erfundenes Ziel |
| B1 `source_url=/tasks?status=open` | API-/Domainprovenienz. Tasks-UI liest diesen Queryfilter derzeit nicht; UIlink heißt "Aufgabenbestand", nicht "Alle offenen Aufgaben" |
| B1 `source_url=/notifications?status=unread` | Kein entsprechender App-Router. Vollständige Hinweise direkt im Dashboard traversieren; keinen Link zu einer erfundenen /notifications-Seite |
| B1 `source_url=/contracts` | Existierender allgemeiner Vertragsbestand; dort derzeit kein konkreter contract_id-/90-Tage-Deep-Linkvertrag |

Backend-source_url niemals ungeprüft als `<Link>`/Navigation übernehmen;
lokale bekannte Route/Referenztypen bestimmen das tatsächliche Ziel. Vorhandene
globale NotificationBell ist eigener Legacybereich (10 Zeilen, eigene
Badge-/Fehlerlogik) und wird nicht durch B2 als bereits vollständig umgestellt
behauptet oder parallel verändert.

## Ruhige professionelle Bedienung

Bestehende Darstellung weiterführen: klare Überschrift, zurückhaltende
Tealfarbe, etablierte helle/dunkle Tokens, wenig konkurrierende Hinweise,
gleichmäßige Abstände und gut lesbare Zahlen. Kein neuer Designframework,
globaler Theme-/Layoutumbau oder künstlicher Fortschrittsprozentsatz.

Vier zentrale Kennzahlen bleiben kompakt: Immobilien, belegte Einheiten,
kanonischer offener Betrag aus aging, Entwurfsperioden. Belegung heißt
"Belegte Einheiten"/"als belegt erfasst"; gespeicherter Status ist kein
bewiesener gegenwärtiger Mietvertrag. Kleine Grundlagenhinweise erklären
Präsenzprüfung, Statusbasis und getrennte Finanzbasis in verständlicher Sprache.

Arbeitszentrale: ausgewogene nächste Schritte und Schnellzugriff, darunter
drei gleichrangige Hinweisgruppen mit tatsächlich vollständigen Totals und
ruhiger kompakter Pagingzeile. Genau ein ausgewählter Kontext direkt beim
betroffenen Hinweis, eindeutiger Rückweg. Bestand und Einrichtung nachgeordnet;
sechs Auswertungen und Tabellen unter bestehendem Analyse-Tab, Audit geschützt
nach Aufklappen. Keine vorgetäuschte Vollständigkeit aus fünf Hinweiszeilen.

320/360/1440: eigene Grids minmax(0,1fr), lange Titel/Vertragsnummern und
Buttontexte umbrechen; interne Tabelle erhält benannten Tastaturscrollbereich,
der Seitenkörper bleibt innerhalb der Breite. Stale-, Paging- und Kontextzeile
dürfen nicht aus der Karte ragen. Keine ausgeblendeten realen Inhalte zur
Erfüllung einer Breitenassertion.

Tastatur: bestehender Tabvertrag Pfeile/Home/End; tatsächliche Button-/Link-
Semantik, sichtbarer Fokus; Pagingregion je Familienheading benennen;
Neuladen/Fehler status/alert sinnvoll ankündigen. Nach Kontextschluss Fokus
auf den auslösenden Hinweis, nach verschwundener Zeile auf den Gruppenheading.
Busykommunikation und deaktivierte Aktion konsistent, keine Toastflut.
de-DE/en-US/es-ES gleicher Feldsatz; Datums-/Zahlenformat localeabhängig.

## Abgegrenzte spätere Commits und Ownership

1. Dieser reine Vorcodeplan vor jeder Produktänderung.
2. Nach Root-B1-Freigabe eigener Parser/Query-/Snapshotstate mit zielgenauen
   Vertrag-/Race-/Scopezustandstests unter `features/dashboardHome/`.
3. Kleine Dashboard-Wiringänderung: getAll-Units und drei alte Hintquellen
   vollständig entfernen, B1-Kennzahlen/fortsetzbare Hinweise einsetzen;
   bestehende unabhängige Reports erhalten. Zugehöriger UItest-Slice.
4. Bewusst ausgewählter genauer Kontext, lokale Darstellung/CSS, schmale
   `dashboardHome`-Übersetzungen und echte Tastatur-/Stale-/Kontexttests.
5. Eigene tatsächliche Browserquellen nach kleinem Vorcode-/Fixtureabgleich;
   koordinierte Nativeausführung und ehrlicher Handoff getrennt.

Besitz nur neue Dashboardfeaturedateien, Dashboard.jsx/CSS, zugehörige eigene
Tests/e2e, enges Dashboard-i18n und eigene Dokumentation. Backendservice,
Router, Registry, Stores/Locks, DDL, Recovery/CI, gemeinsame FormModal/Drafts,
DataTable/Layout/Auth/API und sonstige Inventare unverändert. Root integriert;
keine Root/Main/Previewwrites oder uncommittete Backendkopie.

## Zielgerichtete spätere Nachweise, derzeit noch nicht ausgeführt

UI-Vertrag/Bedienung: benötigte Fälle paarweise bündeln, tatsächliche neue
Tests vor Fix gegen alte UI ausführen, kein synthetischer Importfehler als
Negativnachweis. Gezielt ein Worker; statische lokale Checks, keine sofortige
breite Suite. Bestehende DashboardHome-Checks erhalten/auf echte Quelle
umstellen; bisherige Behauptung getAll('/units') bewusst durch dessen Verbot
ersetzen. Andere RoleControls/Reportsprüfungen nur bei tatsächlicher Berührung.

- Vollständige Totals jenseits Vorschauseite, occupancy mit occupied+rented,
  weiteren Status und korrektem 0/0; keine APIgetAll-/Legacyhint-Requests.
- Dreifamilienpaging ohne Clientresort/Zeilenanhäufung; Cursor-/Stichtagbindung,
  atomare Queryantwort, Retry derselben fehlgeschlagenen Seite, echte 422-
  Neustartbedienung und bewegliche leere Folgeseite.
- Fehlende/widersprüchliche Shape sichtbar; frische Leere vs Erstfehler vs
  älterer Stand; unabhängiger Finanzfehler, keine doppelte Betragssumme.
- Superseded Responses, Unmount, A→B-Kontextwechsel, Actor-/Grantremount und
  numerische 401/403/404 verbergen private Daten; Readonlynavigation und
  Adminaudit erhalten. Aktuelle Authantwort mit eingeschränkten Grants.
- Ein ContextonClick statt N+1; konkrete IDs/Parentketten geprüft, fehlende
  Zuordnung ehrlich; source_url und nicht existierende Route niemals UIziel.
- Tastatur, übersetzte Basics, korrekte Präsenz-/Status-/Snapshotformulierungen,
  kein Leer-/Einrichtungsclaim aus fehlenden oder stale Quellen.

Geplantes Nativebrowserpaket erst nach Rootfreigabe von sauberem B1 und Slot:

1. Tatsächliche isolierte SQLDB, unabhängiger großer synthetischer Bestand über
   der alten Preview-/Listenmenge, fachlich verschiedene/späte Einheiten und
   mehr als fünf je Hinweisfamilie. Totals über echte API gegen bekannte
   Fixturewerte; letzte Hinweise einschließlich Datumsgleichstand/NULL über
   native Cursors erreichbar. Kein abgeschnittener /units?limit=1000-Vergleich.
2. Nativer ausgewählter Manager/Readonlyzugang, tatsächlicher Detailkontext und
   schnelle bewusste Auswahl; genaues Objekt/Unitziel. Echter Rollen-/Grant-
   entzug über synthetischen Account, frische /auth/me-/Summaryantwort und
   kein fortbestehender privater Kontext. Keine FakeAuth-/Summary-/403quelle.
3. Getrennte echte leere Fixture und gezieltes Transportfehler-/verlorene
   Summaryantwortscenario mit realem vorherigem Erfolg; frische Null vs Fehler
   vs Stale. Tatsächlichen Cursor durch echten Bindingwechsel ungültig machen;
   422-Neustart. Fault Injection als solche klar kennzeichnen.

Bei 320/360/1440 tatsächlich Screenshotgesamtseite und lesbaren Viewport
ansehen, Seitenbreite unverändert streng prüfen; Tastatur mindestens
Seitenschritt und Kontextöffnung/-schluss. NativeBuild und ein eigener
Backend-/Port-/Tempbereich über vorhandenen Runner, keine Parallel-Appstarts.
PG-/B1-, Finanz-/Recovery-/Releasekomposition bleibt Root; zusätzliche schwere
Gates vorher abstimmen. Keine Liveprovider-/Privatdaten und kein publicschema.
100.000/1 Mio./20 Jahre/10 Nutzer sind gesonderte spätere Messungen, keine
Leistungsbehauptung aus diesem UIpaket.

## Stand dieses Commits

Root hat den abgegrenzten Ansatz akzeptiert. Es fehlen der freigegebene saubere
B1-Produktcommit und danach Code-/UI-/Browsernachweise. Eigene neue Quelle ist
hier ausschließlich dieser Plan. Keine Build-, Python-, PG-, Browser- oder
UItests gestartet; kein schwerer Slot belegt. Keine neue Funktion als fertig
oder live ausgegeben.
