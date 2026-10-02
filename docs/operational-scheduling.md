# Wiederkehrende Aufgaben, Kalenderfristen und Eskalationen

Aufgaben, Kalender und Eskalationsregeln bieten einen gemeinsamen manuellen
„Operativen Lauf“. Er erzeugt lokale Aufgaben, Kalendertermine und
Benachrichtigungen. Er verschickt keine E-Mails und keine externen Nachrichten.
Das Ergebnis nennt nur tatsächlich neu erzeugte Datensätze sowie übersprungene
ungültige Altregeln. Wiederholte erfolgreiche Läufe werden ebenfalls protokolliert.

## Wiederholungen

Unterstützt wird ein bewusst begrenztes Regelformat:
`FREQ=DAILY|WEEKLY|MONTHLY|YEARLY`, optional `INTERVAL`, `COUNT` und `UNTIL`.
`RRULE:` als Präfix und `UNTIL=YYYYMMDD` oder `YYYY-MM-DD` sind erlaubt.
Unbekannte, doppelte oder ungültige Bestandteile werden abgewiesen. Dies ist keine
vollständige RFC-5545-Implementierung; beispielsweise ist `BYDAY` nicht unterstützt.

Das ursprüngliche Fälligkeitsdatum einer Aufgabe bzw. Datum eines Kalendertermins
ist der unveränderliche Serienanker. Eine Monatsserie ab 31. Januar erzeugt den
28./29. Februar und danach den 31. März. Ein späteres Verschieben einer Instanz
oder des ursprünglichen Termins ändert diesen Anker nicht. Für einen anderen
Anker ist eine neue Vorlage erforderlich.

Bestehende Aufgaben behalten ihre bisherige `COUNT`-Bedeutung: `COUNT=3` erlaubt
drei Folgeaufgaben; `COUNT=0` ist unbegrenzt. Bei den neuen Kalenderplänen zählt
`COUNT` den ursprünglichen Termin mit, daher erzeugt `COUNT=3` zwei Folgetermine
und `COUNT=0` ist ungültig. Ein `UNTIL` ist einschließlich seines Datums gültig.

Standardmäßig wird für eine Aufgabe höchstens eine offene Folgeaufgabe erzeugt.
Erst nach ihrer Erledigung wird die nächste fällige Instanz erzeugt. Der manuelle
Lauf kann ausdrücklich alle fälligen Aufgaben im ausgewählten Nachholzeitraum
erzeugen. Kalenderpläne haben einen eigenen Aktiv-Schalter und werden in diesem
Zeitraum vollständig nachgeholt. Eine gelöschte, verschobene oder erledigte
Instanz behält ihre ursprüngliche Identität und wird nicht erneut erzeugt.
Vorhandene alte Folgeaufgaben werden anhand ihres Fälligkeitsdatums übernommen.

## Fristen und Eskalationen

Der gemeinsame Lauf übernimmt offene Aufgabenfristen, Wartungsfristen und
Wartungstermine innerhalb des ausgewählten Zeitraums in den Kalender. Ein
Vertragsende wird innerhalb des Vorschauhorizonts als Termin und Meldung
angelegt. Die abgeleiteten Termine dokumentieren den Friststand zum Zeitpunkt
der Erstellung. Sie bleiben historische Meilensteine; geänderte Quellfristen
können einen neuen Termin erzeugen. Bewusst gelöschte Termine werden nicht
automatisch wiederhergestellt.

Eskalationen unterstützen Aufgaben, Instandhaltung, Forderungen und gebuchte
Monatsforderungen. Als Bedingung dienen `due_date` bzw. bei Instandhaltung auch
`appointment_at`, ergänzt um 0–3660 überfällige Tage. Die implementierte Aktion
ist `notify`. Automatische Neuzuweisung und Prioritätsänderung werden als
ununterstützte Aktionen abgewiesen, statt einen Erfolg vorzutäuschen.

Für offene Beträge wird der tatsächlich verbleibende Betrag nach Teilzahlungen
und Stornos verwendet. Eine vollständig bezahlte Forderung archiviert die
automatisch erzeugte Meldung. Wird ihre Zahlung storniert, wird dieselbe Meldung
mit dem aktuellen Restbetrag wieder aktiviert. Vom Benutzer selbst archivierte
oder gelöschte Meldungen bleiben archiviert bzw. gelöscht. Einmal erzeugte
Meldungen werden über Regel, Quellobjekt und ursprüngliche Frist dedupliziert.

Die optionale Zielrolle bestimmt die Sichtbarkeit einer Eskalationsmeldung;
Eigentümer sehen alle Meldungen. Ohne Zielrolle bleibt die Meldung für die
zugelassenen Konten der Installation sichtbar. Die Rollenprüfung gilt auch für
direktes Lesen, Bearbeiten, Als-gelesen-Markieren und Löschen über die API.
Dies ist keine Mandanten- oder Portfolio-Abgrenzung.

## Grenzen und Persistenz

`POST /api/v1/tasks/operational-tick` akzeptiert beispielsweise:

```json
{
  "as_of": "2026-03-31",
  "lookback_days": 366,
  "max_items": 500,
  "days_ahead": 90,
  "full_catch_up": false
}
```

Die Grenzen sind 1–3660 Nachholtage, 1–5000 neue Datensätze pro Lauf und
1–365 Vorschautage. Zusätzlich sind die geprüften Kandidaten und die Laufzeit
begrenzt. Bei Überschreitung wird der gesamte Lauf zurückgerollt; es wird weder
ein Teilergebnis veröffentlicht noch ein erfolgreicher Lauf protokolliert.
Für ältere Lücken müssen ausdrücklich kleinere, vergangene Stichtage gewählt
werden. Ein begrenzter Nachholzeitraum behauptet keine vollständige historische
Aufarbeitung außerhalb seines Fensters.

SQL-Betrieb speichert Serienanker, Instanzidentitäten, Benachrichtigungsidentitäten
und Laufhistorie in fünf `operational_*`-Tabellen. Eine atomar aktualisierte
Sperrzeile ordnet konkurrierende Läufe auch über unabhängige Prozesse hinweg;
Geschäftsdatensätze und Identitäten werden gemeinsam committed. Die Produktion
muss SQLite oder PostgreSQL verwenden. Der explizite In-Memory-Modus besitzt nur
prozesslokale Identitäten und ist nicht neustartfest.

`GET /api/v1/tasks/operational-ticks` liefert die letzten 20 erfolgreichen Läufe
(höchstens 100), `GET /api/v1/tasks/operational-status` den tatsächlichen Zustand
des optionalen Workers. Kalenderpläne werden über
`GET /api/v1/calendar/schedules` und `PUT /api/v1/calendar/{id}/schedule`
verwaltet. Die bisherigen Generierungs-Endpunkte bleiben bestehen und verwenden
dieselbe Idempotenzlogik.

## Ausdrücklicher Serverbetrieb

Der Worker ist standardmäßig deaktiviert. Die App-Lifespan-Integration erstellt
`OperationalScheduler` mit den validierten Einstellungen und ruft `start()` und
`stop()` auf. Vorgesehene Umgebungsvariablen sind
`OPERATIONAL_SCHEDULER_ENABLED=false`,
`OPERATIONAL_SCHEDULER_INTERVAL_SECONDS=300`,
`OPERATIONAL_SCHEDULER_MAX_ITEMS=500` und
`OPERATIONAL_SCHEDULER_LOOKBACK_DAYS=366`.
Die Oberfläche zeigt den tatsächlichen laufenden/deaktivierten Zustand;
eine reine UI-Einstellung startet keinen Worker. Workerfehler werden protokolliert
und führen nicht zu einer erfolgreichen Laufhistorie.

Migration `j1a2b3c4d5e6` folgt auf `i2a2b3c4d5e6`. Die Registrierung der neuen ORM-
Modelle muss vor `create_all` bzw. Alembic-Metadaten erfolgen; der lokale additive
Schema-Hook ist `ensure_operational_schema(connection)`. Ein Downgrade mit
vorhandener operativer Historie wird vor dem Entfernen irgendeiner Tabelle
verweigert. Für einen Rückstand mit Daten ist eine geprüfte vollständige
Wiederherstellung erforderlich.

## Nachweis

Die fokussierten Tests prüfen ursprünglichen Monatsanker, Zählergrenzen,
gelöschte Instanzen, Rollback, zwei echte unabhängige SQLite-Prozesse, neue
Sessions, Zahlungen/Stornos, Zielrollen und HTTP-Rechte. PostgreSQL-Prüfungen
nutzen ausschließlich `TEST_SERVER_DATABASE_URL` und ein eigenes erzeugtes
Schema; ohne diese Variable werden sie ausdrücklich übersprungen.
`frontend/e2e/operational.pw.mjs` verwendet den echten, frisch migrierten
SQL-Backend-Runner und prüft Erledigung im Aufgabenformular, Wiederholung,
Kalenderplanung und Persistenz nach Reload.
