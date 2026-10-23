# ImmoManager Pro – QoL: Sammelaktionen und Fehlerbericht (17.10.2026)

**Isolierter Entwicklungsstand**, nicht ausgerollt. Nur die gemeinsamen Frontend-Komponenten für Tabellen und die zugehörigen Sprachdateien werden geändert.

## Bedienung

- Nach einer Sammelaktion zeigt der Fehlerbericht weiterhin die konkret fehlgeschlagenen Einträge mit ihren serverseitigen Fehlermeldungen.
- Bei **mehr als fünf Fehlern** gibt es nun `Alle N Fehler anzeigen` und `Weniger Fehler anzeigen` mit `aria-expanded`. Niemand muss sich auf die bisher abgeschnittenen ersten fünf Fehlermeldungen verlassen.
- Der Bericht lässt sich **auch dann schließen, wenn noch fehlgeschlagene Einträge ausgewählt sind**. Das Schließen verwirft keine Auswahl, führt keine Aktion aus und markiert keine fehlgeschlagene Aktion als erfolgreich.
- Eine neue Sammelaktion startet mit einer eingeklappten Fehlerliste. Die bisherigen strikten Einzelrechte, Bestätigung, sequenzielle Ausführung, Sicherung vor Wiederholung und Auswahl nur für die betroffenen sichtbaren Zeilen bleiben unverändert.
- Beschriftungen in Deutsch, Englisch und Spanisch liegen im offiziellen `i18n/*.json`-Katalog vor.

## Tatsächlicher Nachweis

- `npm.cmd run test -- src/test/DataTableBulk.test.jsx src/test/translations.test.js --maxWorkers=1 --no-file-parallelism`: **13/13 Tests bestanden**, darunter 25 synthetisch fehlgeschlagene Einzelaktionen, vollständiges Aufklappen und unabhängiges Schließen des Berichts.
- `npm.cmd run lint`: bestanden.
- `npm.cmd run build`: bestanden; bekannte nicht blockierende Warnung `INEFFECTIVE_DYNAMIC_IMPORT` für `NotificationInbox.jsx` unverändert.
- Keine Backend-Tests, kein nativer Browser-/Screenreader-Test, kein Provider- oder Produktivdeployment. Die fünf bereits offenen Backend-Migrationsdateien bleiben außerhalb dieses Commits.

## Weiter offen

Vor einer Releaseentscheidung bleiben die vollständige unabhängige Browser- und Betriebssystemabnahme, reale Schnittstellenverträge und die PostgreSQL-/Migrationsabnahme separat offen.
