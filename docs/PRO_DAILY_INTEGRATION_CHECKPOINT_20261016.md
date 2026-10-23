# Tagesfunktionen – integrierter Entwicklungscheckpoint, nicht abgenommen

## Umfang und tatsächlicher Stand

Benutzerbezogener Benachrichtigungseingang, Quellenrouting, persönliche Lesebelege/Archivierung/Wiederöffnen, korrekte SQL-Zähler und Tuple-Cursor sowie vollständiges `read_all` sind zusammengeführt. Alte globale Statuswerte bleiben als historische Quelldaten erhalten und werden keinem erfundenen Leser zugeordnet. Ein vollständiger Eingang kann auch jenseits 10.000 Hinweisen atomar bestätigt werden; Einzelabfragen bleiben begrenzt. Berechtigungswechsel und verlorene Antworten bleiben Gegenproben.

Die Einstellungszentrale verwendet die bestehenden Preferences, getrennte versionierte Objekt-/Globalregeln und wirksame Anzeige-/Fälligkeits-/Erinnerungsvorgaben. Hinzugekommen sind eine tokenfreie Sitzungsfamilienübersicht, ausdrücklicher Widerruf, interne Vertragsnummernreservierung und dokumentierte Entwurfsvorgaben. Der Login registriert Access-/Refresh-Token derselben Familie; ältere Tokens ohne Familienkennung werden nicht nachträglich einem erfundenen Gerät zugeordnet. Ungültige signierte Token-Felder werden vor dem Familienzugriff validiert und neutral mit 401 abgewiesen; Datenbankfehler bleiben 503.

Neue Gegenproben prüfen den tatsächlichen Login, fremde Sitzungen, Widerruf von Access und Refresh, unbeteiligte Anmeldung, Legacykompatibilität, fehlgeschlagene Transaktion und identische Wiederholung, Nummernfolge/Reservierung ohne Anlage fachlicher Geldereignisse sowie die tatsächlich gespeicherten Entwurfsvorgaben.

## Ausgeführte Diagnostik

- `daily-integration-diagnostic-memory-37feea2c78834f2fb5770d3319e250d2`: **44 bestanden, 1 fehlgeschlagen**, kein Skip, 59,34 Sekunden. Roter Fall: Memory-Audit-Rollback nach einem späteren fremden Eintrag.
- `daily-integration-diagnostic-sql-90e546a15a464de3b82025796e3c4c91`: **43 bestanden, 2 fehlgeschlagen**, kein Skip, 72,67 Sekunden. Derselbe ausdrücklich auch hier ausgeführte Memory-Audit-Fall sowie eine fehlerhafte Testvorbereitung des Portfolio-Wechsels.
- Die Portfolio-Testvorbereitung verwendete `auth.update_user(...portfolio_ids...)` ohne die laut tatsächlichem HTTP-Vertrag zwingend gemeinsame Zugriffsart. Das SQL-Backend schrieb deshalb keine andere Zuweisung. Der Test verwendet jetzt den echten autorisierten Administrations-PATCH, prüft dessen Erfolg und die tatsächlich gelesenen neuen Grants, BEVOR er die unveränderten 409-Erwartungen ausführt.
- `inbox-real-rights-sql-78dbe0a3c15d417fa9dfbe83c6262dc4`: **3 bestanden**, kein Skip, 15,39 Sekunden. Enthält 10.037 gleiche Zeitstempel, begrenzte SQL-Abfragen, korrekte vollständige Zähler/Bestätigung, tatsächlichen Rechtewechsel und Wiederholung nach Umbenennung/Wiederöffnen.

Alle Läufe sind isoliert und halten ihre tatsächlichen Arbeitsbaumhashes unter `artifacts/pro-tests/` fest. Die jeweils sichtbare Starlette/httpx-Deprecation-Warnung blieb bestehen. Ein neuer Gesamtlauf wird nicht aus diesen selektiven Prüfungen abgeleitet.

## Tatsächlich verbleibende Hindernisse

Ein kombinierter Toolaufruf für Audit-Rollback-/Memory-Sitzungsnacharbeit, die tatsächliche Bankprofil-UI-Anbindung und die drei verbleibenden Mypy-Variablentrennungen wurde von der Tool-Sicherheitsprüfung blockiert und NICHT ausgeführt. Diese Aktionen wurden nicht über ein anderes Werkzeug oder eine andere Befehlsdarstellung erneut versucht.

Deshalb bleibt die Audit-Gegenprobe im regulären Testsatz bewusst rot: Die vorbereitete Sperre/Identitätsrücknahme ist nicht in `audit.py`/`document_versions.Unit` angewandt. Das ist eine reale offene Implementierung, keine externe Anbieterabnahme. Ebenfalls offen bleibt die nicht angewandte zusätzliche Memory-Sitzungssynchronisation. Der letzte tatsächliche Mypy-Lauf meldet noch drei Typfehler in `notification_inbox.py`; die SQL-Ausdrücke laufen in den genannten echten Tests, dennoch ist das Typgate NICHT grün.

Das gespeicherte Bankimportprofil hat einen bestätigten API-Vertrag und einen UI-Helfer, aber noch keinen Verbraucher im echten Bankformular. Das Benachrichtigungs-E-Mail-Policy-API sendet nichts und ist noch nicht mit einer tatsächlichen automatischen Empfängerauswahl/Outbox verbunden. Diese beiden Punkte werden nicht als abgeschlossene Funktionen ausgegeben. Die vollständige Einstellungen-/Sitzungs-/Deep-Link-Browserabnahme, native PostgreSQL-Gegenprobe, saubere Frontendneuinstallation und gemeinsame Endmatrix bleiben offen.

Der Entwicklungscheckpoint erhält den aktuellen Code und die roten Gegenproben für nachvollziehbare Weiterarbeit an unabhängigen Paketen. Er ist keine Integrations-, Migrations- oder Auslieferungsfreigabe und hat die beiden Anwenderinstallationen nicht verändert.
