# Verbindungsgrundlage – ausdrücklich laufende Entwicklung

Dieses Dokument ist ein Wiederaufnahmepunkt, keine Paket- oder Auslieferungsfreigabe. Der letzte vollständig erfolgreiche veröffentlichte CI-Stand bleibt b264cf81ac08dd2bfe3741b71d632f0d5ebbd97b (Nachrichten/Auth, Lauf 38815280138). Nachfolgende Änderungen an der Verbindungsgrundlage sind davon nicht abgedeckt.

## Geschriebene Arbeitsbestandteile

- backend/db/integration_connection_models.py: Verbindungen, versionierte Geheimnisreferenzen, externe Zuordnungen, Aktionsläufe, verschlüsselte Antwortblöcke und Ereignisse.
- Neue, noch nicht veröffentlichte additive Migration d73f2b9a041c auf c61e9a2f034b. Sie wurde nicht auf Anwenderdaten angewendet.
- backend/services/integrations/connection_storage.py, connection_types.py, connections.py und connection_runs.py: aktuelle Rechte, CAS, Wiederholungsschlüssel, explizite Vorbereitung/Ausführung, geschützte Konfiguration und fortsetzbare lesende Abschnitte.
- backend/routers/integration_connections.py und frontend/src/pages/IntegrationConnections.jsx samt Styles, Routen und Navigation: Verbindungsverwaltung, gespeicherte Vorschau und Vorgangshistorie.
- Regressionen test_connection_framework.py, test_connection_smtp_transport.py und IntegrationConnections.test.jsx. Maßgeblich sind deren tatsächliche Ergebnisdateien und geprüfte Source-Hashes, nicht ein früheres grünes Ergebnis vor späteren Änderungen.

Die frühere Provideroberfläche wurde nicht durch eine neue unabhängige App ersetzt. Historische Konfigurationsübernahme ist noch gesperrt, solange keine verifizierte eindeutige Umschaltung des bisherigen Konfigurationswegs vorliegt.

## Bekannte noch zu prüfende beziehungsweise zu vervollständigende Punkte

1. Alte Konfiguration und neue Standardverbindung dürfen keine konkurrierenden Autoritäten werden. Die Legacy-Brücke ist nicht implementiert und darf nicht durch bloßes Setzen eines Flags freigegeben werden.
2. Der gesonderte Schreibaufruf für connection_evidence.py wurde vom Tool blockiert. Eine solche Erweiterung ist nicht als implementierter Nachweis zu behandeln und darf nicht über einen alternativen Schreibweg nachgebildet werden.
3. Ergebnisabgleich bei unklarem externem Ausgang, abgelaufene beziehungsweise übernommene Versuche, tatsächliche Quelloriginale und vollständige wiederherstellbare Ergebnismanifeste benötigen noch ihre getrennte Abnahme. Aktuell angenommene interne Providerergebnisse beweisen keine externe Zustellung.
4. Die aktuelle neue Oberfläche benötigt weiterhin ihre echte Browser-/Screenshotabnahme. Bestehende erfolgreiche Nachrichten-Screenshots sind kein Nachweis für die Verbindungsseite.
5. Neue persistente Verbindungsdaten und Geheimnisversionen benötigen einen eigenen vollständigen Restore-Nachweis. Die vorhandene Nachrichten-Restoreprobe deckt dieses neue Paket nicht ab.
6. Neue Migration, OpenAPI-Vertrag, Rollen, gleichzeitige Konfiguration, zwei native PostgreSQL-Verbindungen und mehr als 10.000 Vorgänge gemeinsam prüfen. Keine Assertions, Timeouts oder CI-Gates lockern.

## Wichtige tatsächliche Hilfsverträge

DocumentVersions.Unit hat im vorhandenen Code den Konstruktor Unit(store, db, user, archive=None), nicht die zeitweise angenommene Dataclass-Signatur. Die private Receipt-Einheit verwendet entsprechend die benannten Argumente store, db, user, archive und die Rolle receipt_only; sie besitzt keine fingierte Eigentümerberechtigung. Eine zusätzliche Regression prüft diesen Vertrag ausdrücklich.

useModalDialog ist ein benannter React-Hook mit (ref, onClose) und liefert kein Objekt zurück. Der Dialog reicht seine eigene Ref hinein. Beschreibungstexte werden über aria-describedby getrennt vom Feldnamen zugeordnet. Sichtbare Konfigurationsdefaults müssen tatsächlich im gespeicherten Befehl enthalten sein.

## Prüforte

Ergebnisverzeichnisse unter artifacts/pro-tests mit Präfixen connections-wired, connections-http-sql, connections-bound-receipts, connection-real-smtp und connection-frontend-* enthalten die jeweiligen Läufe. Ein vorhandener Ergebnistext ohne passende Source-Hashes ist keine Aussage über spätere Änderungen. Ein nicht abgeschlossener Prozess ist kein bestandener Test.

Die synthetische SMTP-Prüfung besitzt ein eigenes Loopback-TLS-Zertifikat und akzeptiert nur EHLO/HELO, NOOP und QUIT. Sie darf keine Nachricht annehmen und keine realen Zugangsdaten verwenden.

## Weiterarbeit

Zunächst diesen Stand anhand der tatsächlichen Dateien und Ergebnisse abgleichen; unklare Toolausgaben nicht als Erfolg interpretieren. Danach die noch offenen Framework-Verträge schließen oder den gesperrten Teil genau abgrenzen und die unabhängigen Handoverpakete weiterentwickeln. Die vollständige Gesamtaufgabe bleibt unverändert bestehen. Codex übernimmt erst nach unabhängiger Prüfung Zusammenführung und Auslieferung.
