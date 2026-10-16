# Handover-Vollständigkeitsprüfung – verbliebene Lücken (16.10.2026)

## Prüfregel und Geltungsbereich

Abgleich mit `CHATGPT_PRO_HANDOVER_20261015.md` (Abschnitte
„Schnittstellen und übrige Umsetzungspakete“ und „Abschlusskriterien“).
Die auf DESKTOP-O008GV9 tatsächlich lesbaren Gitstände, Testlogs,
Frontendbuilds und eigens wiederhergestellten QA-Installationen wurden
zusätzlich geprüft. **Grüne Einzeltests sind niemals automatische
Integrations-/Auslieferungsfreigaben.** Für einen unabhängigen
Quellworker steht ein vorhandener Commit nicht stellvertretend
für uncommittete spätere Änderungen. Laufende Benutzerinstallationen,
zentrale Git-Hauptkopie und echte Geschäftsaktionen blieben unangetastet.

## Blockierende Gesamtvertragslücken – P0

| Vertrag | Belegter Entwicklungsstand | Was genau fehlt |
|---|---|---|
| Linearer Gesamt-Migrationsgraph | Bank/Finanzen `1a716c4c`, TEHA `d35057c0`, Channels `2da46904`, API/Plugin `f1a2917e` sind in **unterschiedlichen** Worktrees; Steuer und Dokumente jeweils mit uncommitteten Änderungen | TEHA/Channels/Plattform/Steuer/Dokument/übrige Zweige in **einem** linearen oder explizit gemergten Alembic-Graphen mit Altbestandsupgrade, geschütztem Downgrade, Backup und nativer PostgreSQL-Abnahme nachweisen. Der Kanalmigrations-Merge-Schreibaufruf wurde von der Tool-Sicherheitsprüfung blockiert und nicht umgangen. |
| Alle privaten Quellen in einem Vollrestore | Separate Verschlüsselungs-/Originalnachweise für Connection, Bank, Steuer, Kommunikation, TEHA, Channels, Plugins; lokaler Plattform-Restore nach `f1a2917e` erfolgreich | **Eine** wiederhergestellte Testinstallation mit gleichzeitig befüllten *sämtlichen* neuen Domain-Tabellen, Dateien, Schlüsseln, Pluginpaketen und Berechtigungen, ohne ursprüngliche Umgebung, danach komplette Browser-/Fachabnahme. |
| Eine autoritative Konfiguration | Private `integration_connections` und ältere `integration_manager`-Konfiguration existieren getrennt | Kontrollierte Legacy-Datenübernahme, eindeutige Konfigurationsautorität, CAS/Secret-Referenzen und kompatible `/api/v1/integrations`-Routen mit Rollback; keinen zweiten produktiven Schreibpfad still aktivieren. |
| Parallele Fach-/Sicherheitsmatrix | Isolierte Memory-/SQLite-/PostgreSQL-Gegenproben, Rechtegrenzen, Claims, Cursor und Restore je Paket | Rechteentzug vor Commit und während Netzwerk-I/O, Leases nach Workerwechsel, verlorene Belege, Rotation und alle Fachinvarianten über **gemeinsame** Domaintransaktionen nachweisen; voller Auth-/Backend-Coverage- und CI-Lauf auf exaktem **kombiniertem** Commit fehlt. |
| Große Bestände und Betrieb | Connectiontests >10.000 Events und 10.033 Runs, einzelne andere Import- und Lastproben | Vollständiger 100k- und 1m-Fachbestandslauf mit unabhängigen Summen/Seiten, fünf Rollen und konkurrierenden Workern; CPU/RAM/SQL-Pläne, laufende Jobs, Wiederanlauf und Backupdauer nachweisen. |
| Konkrete externe Antwort-/Zielorakel | TEHA, FinTS, IS24/OpenImmo, WhatsApp, SMTP/IMAP, Aktenwerk, DATEV, WISO und S3 haben unterschiedliche **synthetische** Vertrags-/Protokolltests | Autorisierte echte und kontrollierte Anbieter-/Zielsystemtests je Verbindung. Annahme, Übertragung, Zustellung, Zahlung, Import und Zielbuchung **nicht** gleichsetzen. Fehlende Fremdsysteme einzeln dokumentieren, alle unabhängigen Teile weiterentwickeln. |

## Schnittstellen: fachliche offene Abnahmen – P1

| Schnittstelle | Bereits implementiert/gezielt getestet | Fehlender Beleg oder Funktion |
|---|---|---|
| Gemeinsamer Integration-/API-Katalog | `pro/interfaces-20261015` `4a9dc388`, 47 native PG ohne Skip, verschlüsselte Chunks, >10k Cursor, konfigurations-/aktengebundene Vorschau, Wiederholungssperren | Echte Anbieter-Manifeste mit Feld-/Einheiten-/Pagingmatrix, eindeutige Legacy-Umschaltung, Anbieterstatus nach unklarem Ergebnis, durchgängige Browser- und native Abnahme im kombinierten Stand. |
| TEHA | `d35057c0` (sauber), 222 Memory/224 SQLite/5 native PG plus private Vollrestoreproben, Originalbyte-/Hash-/Mapping-Receipt | Heutiger lesender `kunden.socs.ws`-Portalabgleich mit autorisierter Sitzung, neues beobachtetes Versionsschema, echte Kosten-/Nutzer-/Auftragsrückübertragung und dokumentierter externer Abschlussstatus. |
| Bankimporte und CAMT/FinTS | Getrennte Bank-/Finanzzweige, 61 synthetische Bank-SQLtests und bibliotheksbasierter FinTS-Offlinevertrag; lokale Buchung/Reversal/Saldo-Verknüpfung | Aktuelle bankkonkrete Originalfiles, unabhängige Saldenorakel und laufende Bank-TAN-/Reauth-Sitzung; Betrags-/Referenzkontrolle und keine Doppelzahlung bei unklarem Auftragsausgang, Zielabnahme. |
| DATEV / WISO 2026 | Eigene Steuerstage: 98 SQL bestanden/1 umgebungsspezifischer Skip; XML/CSV-/Steuerbelege und Vollarchivproben | Tatsächlicher DATEV-Empfang und WISO Windows 2026 mit Feld-/Storno-/AfA- und Summenvergleich; neutraler CSV/JSON-Export ist kein Erfolgsbeleg. |
| SMTP/IMAP und interne Threads | Kommunikationscheckpoint `4971386d`, 93 integrierte SQLtests und 37 gezielte Frontendfälle; getrennte interne Draft-/Late-Response-Boundaries | Autorisierte kontrollierte SMTP-/IMAP-Gegenstelle mit echten Anhangbytes/TLS, DATA-Abbruch, verlorener Bestätigung, Workerwechsel, eindeutiger Reply-Zuordnung, vollständige kombinierte Auth-/Restoreabnahme. |
| WhatsApp, Deutsche Post, Portale und Aktenwerk | Kanalcheckpoint `2da46904` (sauber), 64 Memoryprotokolltests, 49 gezielte Frontendtests, 2 eigene Archiv-/Manipulationsprüfungen | Gemeinsamer Alembic-/SQL-/nativer Test der Channel-Familie blockiert; tatsächliche autorisierte Template-Zustellung und Webhook; echte gekaufte INTERNETMARKE nur bei Nutzerauftrag; IS24-Create/Update/Deactivate + Bildbeleg, FTPS und tatsächliche Veröffentlichung getrennt; echter Aktenwerk-Consumer mit Exchange-ID- und SHA-Bestätigung. |
| API/MCP, Plugin und S3 | Plattform-Codecommit `f1a2917e`, nach Commit **19/19 SQLite und 11/11 native PostgreSQL** sowie echter Playwright-Restorebrowser bei 320/360/1440 px; Ruff/Mypy für 535 Quelldateien | Standardisierte Freigabematrix für weitere Aktionen; Plugins sind vertrauenswürdiger Python-Code und ausdrücklich **keine Sandbox**; echter optionaler S3-/MinIO-Endpunkt mit Auth-/Restore-/Fehler-/Rotationsbeleg; Vollmatrix noch nicht in dem endgültig kombinierten Code. |

## Noch nicht begonnene bzw. nicht übernommene Pakete – P1/P2

Die zugewiesenen Worktrees `pro-finish-ownership-20261016`,
`pro-finish-billing-20261016`, `pro-finish-plans-20261016`,
`pro-finish-operations-20261016` und
`pro-finish-portal-20261016` waren beim Audit auf ihrem
jeweiligen Ausgangscommit **sauber, ohne neue Änderungen und ohne neue
Testlaufordner**. Das beweist nicht, dass es in der existierenden
Produktbasis keine entsprechenden Funktionen gibt. Es beweist aber,
dass die im Handover beauftragte *zusätzliche Umsetzung und Abnahme*
in diesen zugewiesenen Paketen bisher **nicht geliefert** wurde.

Deshalb bleiben fachlich vor allem offen:

- Kauf/Verkauf/Immobilienübergabe: zwei vermietete Einheiten,
  Vertrags-/Kautions-/Forderungs-/Umlagestichtag und Käuferexport
  ohne überschreibbare Originale.
- Perioden-/Betriebskostenabrechnung und Bewohner-/Zählerlücken
  sowie Widerspruchs-, Korrektur- und Abschlusswege.
- Projekt-/Fristen-/Mieterwechsel-/Fachplan-Workflows mit
  persistenten Workerleases und idempotenter Nachführung.
- Mieterportal und begrenzte Offlineerfassung mit
  revisions-/vertragszeitbezogener Identitätszuordnung.
- Dokumenteditor-/OCR-Werkzeuge: unabhängige vollständige
  Browser-/Dokumenten- und Restoreprüfung für lange DOCX/PDF,
  Handschrift/Signatur, parallele Bearbeitung, Rechteentzug.
  Dokumentstage noch uncommittet.
- Neue Einstellungs- und Benachrichtigungsabnahme über Rollen,
  Neustart, Sitzungswechsel, Browsergrößen und aktuellen CI-Commit.
  Die Haupt-Integrationskopie `pro-full-handover-20261016`
  hat derzeit weiterhin **73** uncommittete Änderungen.

## Heute konkret entdeckte und korrigierte Gegenbeispiele

1. Plugin-Manifest-Schema nahm unter ungültigen Typen/duplizierten
   Pflichtfeldern unspezifische Fehler statt einer vollständig
   validierten Deklaration an; Negativtests hinzugefügt.
2. Unbekannter WebSocket-Scope am Plugin-Mount blieb unbeantwortet;
   jetzt expliziter Close/Policy-Verweigerung, Regression grün.
3. Memory-Audit-Rollback konnte ursprünglich einen späteren
   fremden Append entfernen. Jetzt Zielobjekt-Identität unter
   gemeinsamem Lock, paralleler Negativtest bestanden.
4. Der autonome Restore-Test nutzte ein unerlaubtes Ziel außerhalb
   der Test-Ownership-Grenze. Statt Sicherheitsgrenzen abzuschwächen,
   benutzt er einen neuen zufälligen eigenen `artifacts/`-Pfad.
5. Ein vermeintlich grüner UI-Test zeigte nur Ladeindikator/
   Einführungsdialog. Jetzt wartet Playwright auf Dashboard und
   echten Pluginbereich, getrennte anonyme/authentifizierte Clients
   und nachgewiesene Buttongeometrie.
6. Ein tatsächlich abgeschnittenes Bedienelement
   „Wiederherstellungsprobe starten“ bei 320 px wurde durch
   mobile Umordnung korrigiert. Browserproben bei 320/360/1440
   sind visuell gegengeprüft.
7. In der Channelstage wurde zudem das echte Post-Receipt-
   JSON-Problem korrigiert und der WhatsApp-Kanal erst auf
   ausdrückliches Öffnen des richtigen Threads geladen.

## Fortsetzungsreihenfolge

1. Bereits geprüfte Einzelcheckpoint-Committests nachziehen und
   alle Arbeitsstände mit Hash, Log, Status und Schranken dokumentieren.
2. Alle ausstehenden Fachpakete unabhängig implementieren;
   externe Zugänge nur für kontrollierte echte Abnahme benutzen,
   kein unbewilligter Versand/Portokauf/Bankauftrag.
3. Danach Schnittstellen-/Domain-Migrationen und Legacy-
   Konfigurationsbrücke **einmal** in eigenem sauberem Gesamtzweig
   zusammenführen; Tool-Sicherheitsblocker nicht umgehen.
4. Vollständige Memory-/SQLite-/native PostgreSQL-Matrix,
   revidierte 100k-/1m-Stresstests, echte Browser- und
   Dokumentabnahme und kompletter Vollrestore ohne alte Umgebung
   auf dem **exakten finalen Git-Hash**.
5. Erst nach externer Belegliste und grüner Gesamt-CI die
   Integrationsfreigabe an Codex; Anwenderinstallationen selbst
   nicht verändern.

**In keinem der genannten Zweige wird eine Releasefreigabe behauptet.**
