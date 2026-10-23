# ImmoManager Pro – QoL/UI: sichere Sammelarchivierung und Tastaturzeilen (17.10.2026)

**Entwicklungsprüfung im isolierten Zweig `pro/full-handover-20261016`, keine Freigabe der laufenden Anwenderinstallationen.** Das zentrale Integrator-Checkout `claude-review-20261013` bleibt unverändert (`04021da5`); fünf bereits vorgefundene Backend-Migrations-/Finanztestdateien sind nicht Bestandteil dieses Pakets.

## Benachrichtigungen: verständliche, explizite Sammelbestätigung

Die gemeinsame `NotificationInbox` zeigte zwar den zu erwartenden Gesamtumfang, führte `Alle berechtigten Hinweise gelesen archivieren` aber **mit einem einzelnen Klick** aus. Das konnte auch Hinweise erfassen, die aufgrund von Dringlichkeits-/Quellenfiltern oder Pagination gerade gar nicht auf dem Bildschirm waren.

- Nach der ersten Aktion erscheint jetzt eine klar benannte, Tastaturbedienung unterstützende **Sammelbestätigung** mit exaktem `unread_count`. Ein deutlicher Satz wiederholt, dass **alle derzeit berechtigten ungelesenen Hinweise unabhängig von Filtern und sichtbarer Seite** betroffen sind.
- Der Fokus beginnt sicher auf **Abbrechen**; Escape und Abbrechen führen ohne API-POST zum Auslöser zurück. Die Bestätigungsaktion verwendet ausdrücklich den eingefrorenen `snapshot` der angezeigten Vorschau.
- Ändern sich während der Bestätigung `snapshot` oder Gesamtzahl, wird die Aktion blockiert und eine verständliche Fehlermeldung angezeigt. Die serverseitige Snapshot-/Berechtigungssperre greift weiterhin zusätzlich.
- Die `useNotificationInbox`-Funktion erhält eine sofortige `useRef`-Sperre gegen Doppelklicks, weil ein bloßes React-`busy`-State-Update zu spät für zwei Klicks in derselben Ereignisrunde sein kann. Ein abgelehnter Versand bleibt sichtbar und die nächste bewusste Wiederholung nutzt weiterhin die **ursprüngliche Idempotenzkennung**.
- Der Singular wird als `Einen Hinweis jetzt archivieren` angezeigt, statt `1 Hinweise`. Der Ablauf funktioniert im kompakten Glockenbereich und in der vollständigen persönlichen Inbox.

## Tabellen: barrierearme Zeileninteraktion

`DataTable` öffnete viele Objekte, Dokumentvorschauen, Übergabeprotokolle und Wartungsfälle per Klick auf die ganze Zeile; diese Aktion war aber von der Tastatur nicht erreichbar.

- Nur Zeilen mit tatsächlichem `onRowClick` werden mit `tabIndex=0`, zugänglichem Namen (`Eintrag öffnen: …`) und sichtbarem Fokus versehen.
- **Enter und Leertaste** auf der fokussierten Zeile führen denselben Öffnungsvorgang wie ein gewöhnlicher Klick aus; reine Lesetabellen bekommen **keine zusätzlichen Tabstopps**.
- Interaktive Inhalte **in** der Zeile (z. B. Personenlinks, andere Fachlinks, Auswahlkästchen und Zeilenaktionen) werden nicht versehentlich als Ganzzeilen-Öffnung behandelt. Bestehende Rechte-/CRUD-/Navigationsemantik bleibt erhalten.
- Der neue Labeltext ist in den zentralen Sprachkatalogen **Deutsch, Englisch und Spanisch** und in den eingebauten Fallbacks hinterlegt; die vorhandene vollständige Key-Coverage-Prüfung schützt ihn.
- CSS verwendet die bestehenden Theme-Variablen und `:focus-visible`, ohne zusätzliche bewegte Effekte.

## Prüfpunkte

1. Vor der jeweiligen Änderung reproduzierten die neuen gezielten Tests die fehlende Sammelbestätigung bzw. die nicht erreichbaren Tabellenzeilen.
2. Gezielt nach den Produktänderungen bestanden **50 Tests aus acht vorhandenen/neuen Testdateien** (inklusive Tabellen-Mehrfachaktionen, Server-Paginierung, Quelllinks, persönlicher Inbox, KPI-Quelle und Übersetzungskatalogen).
3. Nach den Ergänzungen um Escape, veralteten Server-Snapshot und Singular bestanden **21 Tests aus vier betroffenen UI-Suiten**. Dabei prüfte ein besonderer Test auch eine tatsächliche neue Serverantwort während eines noch offenen Bestätigungsdialogs; beim temporären Datenreload wird die alte DOM-Gruppe bewusst nicht mehr als aktueller Beleg interpretiert.
4. `npm.cmd run lint`: **Exitcode 0**.
5. `npm.cmd run build`: **Exitcode 0**, Vite 8.1.0, **734 Module**. Bestehende nicht blockierende Dynamic-Import-/React-Testwarnungen sind getrennt zu betrachten.

**Vollständige Frontend-Gesamtmatrix nach dem letzten Produktedit:** `npm.cmd run test -- --maxWorkers=1 --no-file-parallelism` ergab **709 von 709 Tests in 108 von 108 Dateien bestanden**, **0 Skips, 0 Assertionsfehler**, Exitcode 0. Start 20:00:26 Uhr lokale Zeit, Dauer 267,01 Sekunden. Es gab weiterhin nicht blockierende React-`act`-/Listenschlüsselwarnungen und erwartbare jsdom-`scrollTo`-Meldungen in älteren Tests.

Die vollständige Matrix enthält die fünf neuen Sammelbestätigungs-Regressionstests und drei Tastaturzeilentests sowie die bestehenden Finanz-, Beleg-, Dokument-, Formular-, Such-, Kommunikations- und Integrationsoberflächen.

## Weiterhin offen

Die Änderungen sind keine neue fachliche Rollen- oder Mandantenfreigabe und ersetzen weder unabhängige Screenreader-/Browser-/Mobilgeräte-Abnahme noch native Backend-/PostgreSQL-/Anbieterintegrationstests. Es wurden **keine** produktiven Daten, Ports, Installationen oder Anbieter-Endpunkte berührt.
