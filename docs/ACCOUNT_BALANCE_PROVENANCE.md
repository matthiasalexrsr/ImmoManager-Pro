# Kontosaldo aus gespeicherten Quellen

Die Aufbereitung ist eine lesende Rechenprüfung: **Anfangsbestand + gespeicherte Bankbuchungen**. Sie bestätigt keinen Bankstand und verändert weder Kontowerte noch Belege. `Account.balance` bleibt ein frei gepflegter, undatierter Vergleichswert. Die Differenz bedeutet „berechnet minus Vergleich“. Anfangsbestand und Vergleichswert besitzen kein Bezugsdatum; deshalb entsteht auch mit Stichtag keine nachgewiesene historische Bankabstimmung.

Alle gespeicherten Buchungen des Kontos zählen genau einmal, einschließlich `open`, `matched`, `booked`, `confirmed` und unbekannter Klassifikationen. Diese Status sind kein gemeinsamer Stornovertrag. Zahlungszuordnungen, Forderungen, Guthaben oder deren Stornos werden nicht nochmals addiert bzw. vom gespeicherten Cashbetrag abgezogen. Ein tatsächlicher Geldabfluss benötigt eine gespeicherte negative Bankbuchung.

## API und Nachweis

- `GET /api/v1/accounts/{id}/balance-summary?as_of=YYYY-MM-DD`: optionaler inklusiver Buchungsstichtag; ohne Parameter zählen alle gespeicherten Buchungsdaten, auch zukünftige.
- `GET /api/v1/accounts/{id}/balance-sources?kind=bookings|issues&source_hash=…&cursor=…&page_size=25&as_of=YYYY-MM-DD`: belegbare, begrenzte Quellenseiten. Seitengröße 1–500; der signierte, einstündige Cursor bindet Konto, Zeitraum, Ansicht, Benutzer und Portfoliofreigaben. Seine Position bezeichnet die Quellenseite, nicht einen SQL-OFFSET.

Geldfelder heißen `*_cents` und sind vorzeichenbehaftete Integerstrings oder `null`. Summen verwenden Integerarithmetik. Einzelquellen müssen endlich und centgenau innerhalb der bestehenden `Numeric(12,2)`-Feldkapazität sein; die aggregierte Summe besitzt keine künstliche Konten-/Buchungsgrenze. Nicht reparierbare oder verlorene Originalpräzision wird nicht erfunden. SQLite- und PostgreSQL-Leseabfragen projizieren die gespeicherten Beträge als Text, bevor ORM-Numeric-Konvertierung sie runden könnte.

Der Nachweis enthält `source_hash`, `snapshot_started_at`, erstes/letztes Buchungsdatum, Buchungszahl und fünf feste Statusgruppen (`other` fasst weitere Klassifikationen zusammen). Die SHA-256-Prüfsumme identifiziert die gelesenen Daten; sie ist weder Bankbeleg noch digitale Signatur. Statusgruppen zeigen ihre Anzahl und exakte Summe. Eine ungültige Quelle macht ihre Statussumme und die gesamte Buchungssumme unbekannt. Ein ungültiger Anfangsbestand oder Buchungsbetrag sperrt den berechneten Saldo; ein ungültiger Vergleichswert sperrt ausschließlich Vergleich und Differenz.

`issues_count` zählt alle Befunde, `issues_sample` enthält höchstens 20. Alle weiteren Befunde bleiben über `kind=issues` erreichbar. Befunde enthalten Quell-ID, Feld, Fehlercode, eine gekürzte Wertvorschau und den Reparaturweg. Nach Änderungen muss die Aufbereitung bewusst neu geladen werden (`balance_source_changed`, HTTP 409); eine veraltete Seite wird nicht mit frischen Summen vermischt. Fehlende/ungültige Werte werden niemals als Nullsaldo dargestellt.

## Konsistenz und Zugriff

SQL liest Kontowerte und kontoabhängige Buchungen in einer eigenen SQLite-Transaktion bzw. PostgreSQL-`REPEATABLE READ`-Transaktion. Buchungen werden mit Datum/byteweiser-ID-Keysets in Batches gelesen; weder globales Buchungspreload noch `COUNT` oder wachsende SQL-OFFSETs sind erforderlich. Snapshotidentitäten werden vor Veröffentlichung nochmals in begrenzten Batches gegen aktuelle Kontozuordnung und Freigaben geprüft. Der Snapshot wird bei Erfolg oder Fehler zurückgerollt und geschlossen; keine DML-Mutation findet statt. Memory hält den gemeinsamen Finanz-RLock während des gesamten Lesens.

Direkte Konto-IDs und sämtliche Quellen sind serverseitig portfolioabhängig. Verdeckte Querbezüge verhindern eine unvollständige „erfolgreiche“ Berechnung mit HTTP 403. Fremde Konten liefern 404. Grants werden vor, während und vor Abschluss neu gelesen; während der Verarbeitung geänderte Kontozuordnungen verhindern die Veröffentlichung. Antworten werden nicht gecacht (`Cache-Control: no-store`).

Die Kontenoberfläche öffnet die Prüfung auf Abruf für ein ausgewähltes Konto und zeigt Quelle, Zeitraum, Klassifikationen, Differenz und alle Befunde. Sie berechnet keine Salden für alle Konten im Hintergrund. Die Buchungsnavigation setzt einen tatsächlich angewendeten `account_id`-Filter auf der ersten serverseitigen Seite. Bestehende Kontenpflege, Rollenrechte und ursprüngliche Editrevisionen bleiben erhalten.

`account_updated_at` liefert die ursprüngliche Kontorevision für eine bewusste Korrektur beider Betragsfelder. Die eingeschränkte Korrektur verwendet die bestehende Konto-PATCH-Route mit ursprünglichem If-Match, verlangt zwei gültige Centbeträge und schreibt keine erfundenen Konto-/Bankdaten. Sie funktioniert auch bei nicht endlichen Altbeträgen, ohne zuvor ein vollständiges Konto-GET serialisieren zu müssen. Zwischenzeitliche Änderungen erzeugen den bestehenden Entwurfskonflikt; der Entwurf bleibt erhalten.

## Verifikation

Regressionsfälle verwenden echte Memory-/SQLite-Speicherung, unabhängige SQL-Schreiber, direkte HTTP-IDs, Grantentzug, nachträglich verschobene Quellzeilen, signierte Seitenbindungen, feincentsige Altwerte sowie reale Zahlungszuordnung und deren Storno. Der dedizierte PostgreSQL-Fall verwendet bei `TEST_SERVER_DATABASE_URL` ein zufälliges eigenes Schema und unabhängig schreibende Verbindungen; ohne Dienst wird er ausdrücklich übersprungen. UI-Prüfungen decken unbekannte statt erfundene Summen, Fehler/Retry, Quelländerungen, Stichtag, Cursor und überholte Antworten ab. Reine BigInt-Anzeigefälle oberhalb der JavaScript-Safe-Integer-Grenze erweitern nicht die SQL-Einzelfeldkapazität.
