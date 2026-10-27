# Daily-Paket – Übergabe am 16.10.2026

## Stand und Grenzen

Arbeitsverzeichnis: `C:\Users\matth\Documents\Codex\2026-10-01\wi\work\pro-finish-daily-20261016`.
Branch: `pro/finish-daily-20261016`; Ausgang: `c16e097003c872972074e403a94d15d63cfb4b59`.
Alle Änderungen sind uncommitted zur Coordinator-Inspektion. Keine anderen Checkouts, Liveinstallationen, Ports 8000/8765, produktiven Daten, privaten Konfigurationen oder Geheimnisse wurden verwendet. Keine externen Geschäftsaktionen, neuen Abhängigkeiten, Commits, Pushes oder Releases. Die vorhandene Pythonumgebung wurde nicht verändert. Frontendprüfungen nutzen die bereitgestellte isolierte node_modules-Kopie; daraus folgt **kein npm-ci-Nachweis**.

**Dies ist ein substanziell implementierter, lokal geprüfter Teilstand, keine vollständige Paket-/Integrations-/Releaseabnahme.** Die unten genannten Implementierungslücken sind nicht bloß externe Nachweise.

## Benachrichtigungen

- Fachlicher Hinweis und persönliche Quittung sind getrennt. `notifications.status/read_at` bleiben als Legacywerte unverändert. Ohne persönliche Quittung beginnt jeder Benutzer ungelesen; aus historischen globalen Statuswerten werden weder Leser noch frühere Lesezeiten erfunden. Die API liefert `legacy_status/legacy_read_at` ausdrücklich getrennt.
- `GET /notifications/inbox`: persönliche paginierte Historie, Archiv-, Dringlichkeits- und Quellfilter, vollständiger serverseitiger Ungelesenzähler. Folgeabrufe können den Snapshot mitgeben; eine veränderte Historie ergibt 409 statt still übersprungener Zeilen.
- `GET /notifications/{id}/source`: bestehender `workspace_contexts.resolve_context` anhand tatsächlichem Typ/ID und aktuellen Rechten. Keine Titelheuristik. Glocke, vollständige Liste, Messages-Teilbereich, Arbeitszentrale und Deep Links verwenden denselben Service/isolierte Komponenten.
- `POST /notifications/{id}/receipt`: erwartete persönliche Revision, Idempotenzschlüssel, `landed` mit Zielidentität/Quellrevision oder `reopen`. Für die Bestätigung werden SQL-Hinweis und Quelle gesperrt. Unpassende/geänderte/gelöschte/unzugängliche Quellen quittieren nicht. Unique-Konflikte ergeben 409; SQL-Persistenzfehler 503 mit wiederholbarem Befehl. Keine erfolgreiche Ersatzantwort nach Speicherfehler.
- `POST /notifications/all/receipt`: atomare Quittung des **vollständigen berechtigten** Eingangs, durch Snapshot gebunden. Nicht nur geladene zehn Einträge. Andere Tabs, neue Hinweise oder geänderte Quellen erzeugen einen Konflikt. Wiederholungen eines bestätigten Befehls erzeugen kein weiteres Ergebnis. A quittiert niemals B.
- Leser erhalten nur die persönliche Receiptberechtigung. Der frühere breite persönliche Regex für beliebige Änderungen an gemeinsamen Hinweisen entfällt. Alte PATCH-Status/read_at-Befehle und `/read` werden explizit abgewiesen. Die kompatible Listenroute liefert persönliche Statuswerte; fachliche Erzeugung/Deduplizierung bleibt auf dem gemeinsamen Hinweis.
- Hauptzieltypen öffnen bestehende Akten/Listen mit `focus_id`/`notice_id`: Aufgabe, Forderung, Partei, Mietvertrag, Immobilie, Einheit, Rechnung, Objektvertrag, Instandhaltung und Abrechnung. `NotificationArrival` quittiert erst einen tatsächlich dargestellten Datensatz mit passender Revision. Native Links behalten Maus, Enter, Modifikatortasten und neue Tabs. Escape gibt den Fokus an die Glocke zurück.
- Weitere Typen verwenden eine berechtigte Quellansicht mit Link zur vollständigen Akte. Unaufgelöste Altverweise zeigen einen erklärten Fallback. Offline-/Navigationsfehler verlieren keinen Hinweis. Ein nach verlorener Antwort offener Receiptbefehl bleibt im privaten Tabpuffer wiederholbar. Archivierung löscht nichts.

## Einstellungen und Verbraucher

- Durchsuchbarer Katalog über dem **bestehenden** `user_preferences`-Speicher und der bestehenden Server-`settings`-Autorität. Keine zweite installationsweite Konfigurationsdatei. Persönliche Erweiterungsfelder liegen unter demselben Facadenvertrag in der revisionsgebundenen Metadatenzeile, nicht in einer konkurrierenden Konfiguration.
- Effektiver Wert, Herkunft, Geltung, Änderbarkeit und Neustartbedarf sind sichtbar. Persönlich > Objekt > global > Standard. Objekt-/Globalvorgaben werden für Erinnerungsvorlauf und Standardfälligkeit angeboten, mit aktuellen Verwaltungs-/Objektrechten; globale Änderungen benötigen Zugriff auf alle Bestände.
- Vorhandene SQL-Präferenzzeilen gelten mit allen alten Feldern als explizit. Neue/zusätzliche Felder führen explizite Schlüssel separat, damit Zurücksetzen tatsächlich die darunterliegende Vorgabe übernimmt. Alte Werte werden nicht überschrieben oder rückwirkend auf Belege angewendet.
- `GET/PUT /auth/users/me/settings`, `GET /auth/users/me/settings/effective`: Validierung, CAS, Idempotenz, aktueller Benutzer ausschließlich aus Auth. Der alte `/preferences`-Weg bleibt auf derselben Autorität und validiert ebenfalls; neue Clients verwenden den expliziten Commandvertrag. Alte Clients ohne Wiederholungsschlüssel besitzen weiterhin keinen garantierten Crash-Replayvertrag über getrennte Requests.
- Einstellungsänderung, Commandreceipt und **vorhandenes `audit_logs`-Journal** schreiben im selben Commit. Audit enthält Autor, Zeitpunkt, Vorherwert, Befehl und Ergebnis. Globale Regelhistorie bleibt nach Kontolöschung erhalten; die persönlichen Commandreceipts ersetzen das permanente Journal nicht.
- Durchsuchte/ungefilterte Eingaben, erwartete Revision und Wiederholungsschlüssel bleiben im privaten Tabpuffer erhalten. Konflikte behalten die eigene Eingabe und bieten Vergleich mit dem aktuellen Wert. Fehler werden angezeigt; keine Fire-and-forget-Erfolgsanzeige.
- `date_format`: gemeinsame Datums- und Zeitformatierung. `locale`: bestehendes i18n/Zahlenformat, inklusive Spracheinstellung aus der Topbar. Theme, Sidebar und Tabellenlänge behalten ihre vorhandenen Verbraucher.
- `default_due_day`: Vorbelegung **neuer manueller Forderungsentwürfe**, keine Änderung bestehender Forderungen, Sollstellungen oder Finanzquellen. `reminder_days`: expliziter Vorlauffilter realer Vorgänge der Arbeitszentrale. Beide berücksichtigen berechtigten Objektkontext über die effektive Facade.
- Zusätzlich wirksam: persönliche Startseite (validierte interne Routenauswahl), normale/kompakte Tabellendichte sowie E-Mail-Ruhezeiten in der bestehenden Installationszeitzone Europe/Berlin.
- `email_notifications` und Ruhezeiten steuern konkrete persönliche `email_eligible`-Werte und die serverseitige `email_allowed`-Policy. Keine In-App-Hinweise werden dadurch versteckt. **Der tatsächliche Outboxaufruf dieser Policy fehlt noch im Kommunikationspaket.** Hier wird weder geplant noch gesendet.
- Quellwährung und Betrag bleiben erhalten. Die bisherige persönliche Währungspräferenz besitzt noch keinen allgemeinen Fachverbraucher und wird deshalb im Katalog nur angezeigt. Kein scheinbar wirksamer CHF/USD-Schalter etikettiert alte EUR-Belege um; keine Umrechnung wird behauptet.
- Bestehende Benutzer-/Objektgrants, Backup/Wiederherstellung/Betrieb, Updates und Entwicklungskomponenten bleiben eingebunden. MFA benutzt die vorhandenen Auth-Endpunkte. Geheimnisse werden nicht neu gelesen/gespeichert/gelöscht: maskierter Verweis auf die vorhandene Integrationsverwaltung. Leere Felder im Katalog können kein Secret löschen.
- Serverwerte kommen schreibgeschützt aus den laufenden `settings`; vorhandene Umgebungsvariablen werden als Herkunft benannt, Neustartpflicht ist sichtbar. Es gibt keine bequemen neuen Produktions-/Sicherheitsschalter.
- Kartenmindestbreite der Arbeitszentrale und responsive Titel wurden angepasst. Der Katalog belegt die volle verfügbare Einstellungsbreite. Die CSS-/Komponententests sind kein visueller Browsernachweis.

## Migration, Daten und Integrationsstellen

Graph: `c61e9a2f034b -> d73f2b9a041c -> e160a1b2c305`.

Die neue additive Migration erstellt ausschließlich:

1. `daily_user_state`: Besitzer/Schlüssel/Revision/Payload/Zeit; persönliche Receipts und Präferenzmetadaten.
2. `daily_commands`: Besitzer/Wiederholungsschlüssel/Fingerprint/Ergebnis/Zeit.
3. `daily_setting_rules`: Scope/Schlüssel/Revision/Payload/Zeit; versionierte fachliche Standardvorgaben.

Bestehende Tabellen/Legacywerte/Originaldateien werden nicht umgeschrieben. Persönliche SQL-Zeilen und Commands folgen der Benutzer-FK-CASCADE; Fachvorgaben und das vorhandene permanente Auditjournal bleiben unabhängig vom Ersteller erhalten. Interne Tabellen sind im Scope-Register ausgewiesen; ihre Services prüfen Besitzer bzw. Verwaltungs- und Objektberechtigung ausdrücklich. Keine öffentliche generische Tabellen-API wurde ergänzt. Vollbackup übernimmt alle Tabellen durch den bestehenden Datenbanksnapshot; der Restoretest prüft persönliche Zeilen, Commandreceipt, Objektregel, Präferenz und bytegleiches Original nach Wiederöffnung.

Kein automatischer Downgrade. Rückweg nur durch vollständiges isoliertes Restore und passenden Programmstand. Coordinator muss die unabhängigen Paketheads durch eine neue Merge-Revision verbinden. Keine Änderung am Verbindungsstorage, an `connection_evidence.py` oder an Finanzquellen.

Gemeinsame Integrationsstellen: `backend/db/__init__.py`, `backend/services/portfolio_scope.py`, `backend/permissions.py`, Router `auth.py`/`notifications.py`, `frontend/src/App.jsx`, `DataTable.jsx`, Präferenz-/i18n-Verbindung und die Landingmarker in vorhandenen Akten. Messages ändert ausschließlich den Notificationteil und entfernt dessen alten Lade-/Lesestatusweg; Gesprächshook und Gesprächsverträge bleiben erhalten. Konflikte mit dem Kommunikationsworker an dieser Datei müssen entsprechend eng aufgelöst werden.

## Fokussierte Prüfungen

Alle Backendläufe mit dem vorgegebenen Python und `scripts/run_pro_matrix.py`, eigenem UUID-Laufverzeichnis, Memory bzw. isolierter SQLite und deaktivierten Schedulern. Keine kompletten Backend-/Frontend-Suiten, keine nativen PG-/Browseraggregate. Maximal ein Testworker.

- Memory, finaler Backendstand: **22 bestanden**. `artifacts/pro-tests/daily-memory-audit-final-memory-bf8452589d8d427797e82633179c423d/{input.json,result.json,junit.xml,pytest.log}`.
- SQLite, finaler Backendstand: **22 bestanden**. `artifacts/pro-tests/daily-sql-audit-final-sql-8582087f8f1447438c2f0b00401f7d39/{input.json,result.json,junit.xml,pytest.log}`.
- Frontend, letzter Stand: **19 bestanden**, `artifacts/daily-frontend-accepted-local.json`. Vier Dateien: `DailyWorkflows`, `SettingsCatalogue`, `PreferencesContext`, `format`.
- Ruff fuer alle geaenderten/neuen Backendmodule und beide fokussierten Testdateien bestanden. Mypy Linux fuer die sechs betroffenen Laufzeitmodule bestanden. ESLint fuer geaenderte Frontendquellen und den abschliessenden Bell-/Testlauf bestanden, ohne Fehler oder Warnungen. `git diff --check` bestanden.
- Exakte Hashes des uncommitteten Quellstands: `artifacts/daily-final-source-hashes.json`. Backendmatrix-Inputdateien enthalten ebenfalls Quellhashes. Frühere grüne Ergebnisse gelten nicht als Prüfung späterer Änderungen.

Regressionsorakel umfassen 28 Hinweise trotz Zehnerseite, zwei unabhängige Benutzer, drei Rollen mit Quellen-/Rechteentzug, CAS und geänderte Replaybefehle, Quellenänderung/Löschung, komplette und einzelne Transaktionsabbrüche, Vererbung/Reset, Legacyautorität, ungültige Eingaben, Neustart über neue SQL-Session, E-Mail-/Ruhezeitgrenzen mit unabhängig berechneten UTC/Berlinzeiten, globale Auditgeschichte nach Benutzerlöschung, additive Migration, Vollbackup/Restore und bytegleiches Original. Frontend prüft späte Altbenutzerantwort, tatsächliche Format-/Dichteverbraucher, verlorene Antworten mit gleichem Command, ungeladene/unpassende/geänderte Quellen, native Links, Escapefokus sowie Eingabepuffer durch Filterung und Remount.

Nachvollziehbare Erstfehler (nicht nachträglich grün genannt):

- `daily-first-memory-244153d95c9947e888d9da6d6fc8272b`: 1/7 fehlgeschlagen wegen falschem read_at-Fixturevertrag; korrigiert auf beobachtetes Patchmodell.
- `daily-sql-first-sql-0bbdf3029cf34e709032a96828055189`: 1/7 fehlgeschlagen; Legacy-PATCH-Sperre saß im Vorlagenhandler und wurde im richtigen Handler platziert.
- `daily-sql-final-sql-8a05c74d446a4878bb54913f2e154f6e`: 1/18 fehlgeschlagen; bestehender Generatorregressionstest rief den absichtlich abgeschafften globalen Readcontroller auf. Er prüft jetzt echten persönlichen Read-all **und** unveränderte globale Statuswerte; das Deduplizierungsorakel bleibt erhalten und ist verstärkt.
- `artifacts/daily-settings-focused.json`: 1/4 fehlgeschlagen; verlorener Eingabepuffer bei Filterung. Synchrones Puffern korrigiert; Wiederholungs-/Abschlussläufe grün.

## Tatsächliche Restarbeit und Fremdpaket-Hooks

- Kommunikationsworker muss vor Planung und vor Versand persönlicher Hinweis-E-Mails `settings_catalogue.email_allowed(store, recipient_user_id, severity, moment=None)` und die aktuellen Quellrechte prüfen. Die Funktion plant/sendet nichts und eröffnet keine zweite Outbox. Fachnachrichten/Mahnbriefe dürfen nicht versehentlich durch eine persönliche Hinweispräferenz unterdrückt werden. Tatsächliche Outbox-/Zustellabnahme fehlt.
- Erinnerungs-/Jobworker kann `settings_catalogue.effective_values(store, actor_id, property_id)` verwenden. Vorlauf ändert keine fachlichen Fristen. Gemeinsame Erzeugung bleibt dedupliziert, Kanalauswahl ist empfängerbezogen. Weitergehende Kalender-/Providerjobanbindung gehört den jeweiligen Paketen und ist hier nicht erfolgt.
- Nicht jeder existierende Zieltyp hat bereits einen Marker in seiner vollständigen Fachoberfläche; diese Typen verwenden die Quellansicht plus weiteren Aktenlink. Eine durchgehend direkte vollständige Fachansicht aller Typen ist damit noch nicht fertig.
- Der vollständige geforderte Einstellungsumfang ist **noch nicht fertig**: zusätzliche wirksame Nummernkreis-, Briefkopf-/Signatur-/Kostenregel-, Import-/Pluginprofile und Sitzungsinventare sind nicht implementiert. Bestehende Funktionen sind auffindbar verlinkt; Verlinkung wird nicht als Umsetzung fehlender Controls ausgegeben. Persönliche Währungspräferenz hat noch keinen allgemeinen Fachverbraucher.
- Tatsächliche Browser-/Focus-/Screenshotabnahme bei 320/360/1440 und langen deutschen Titeln, native unabhängige PG-Parallelitäts-/Upgradeprüfungen sowie teure Integrations-/Releasegates liegen laut Auftrag beim Coordinator und wurden nicht ausgeführt. Es gibt keinen visuellen Fertigstellungsnachweis und keinen Produktionsbuildnachweis dieses Pakets.
