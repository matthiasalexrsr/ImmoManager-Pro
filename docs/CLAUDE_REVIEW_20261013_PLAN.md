# Prüfung und Korrektur des Claude-Stands vom 12. Oktober

Ausgang: `origin/claude/dreamy-gauss-nmaxhn`, Commit `c3e1759d`. Enthält die Codex-Übergabe `cbb1e04e`. Eigener Reviewbranch `codex/claude-review-20261013`, isolierter Checkout `work/claude-review-20261013`.

## Prüfbereiche und Zuständigkeiten

1. Zentrale Integration: vollständige Memory-/SQLite-Prüfungen, echter PostgreSQL-Server, UI-Gesamtlauf, Migration/Start, Abrechnungsschutz, CI mit verbindlicher PostgreSQL-Prüfung, unabhängiger Review und Dokumentation.
2. Astra Ultra: Rechnungsprüfung, Mahnung und Kaution, insbesondere Quellbelege, Idempotenz, Stand am Stichtag, Fremd-IDs, Teilverrechnung und Zahlungszuordnungen.
3. Astra Ultra: Portfolio-/Dateiberechtigungen, Schreiben bis Commit, HTTP-Authentifizierung, Suche, dauerhafte Jobs, Schlüssel und Sicherungen.
4. Astra Ultra: Projekte, Dienstleistungsverträge, Übergabeprotokolle und Wohnungsgeberbestätigung, einschließlich Oberfläche und konkurrierenden Antworten.

Gemeinsame Dateien werden koordiniert. Kein Test darf die laufende Vorschau oder reale Verwaltungsdaten verwenden. Externe Fachübermittlungen sind nicht Teil der Prüfung. Bestehende Änderungen und historische Originale bleiben erhalten.

## Reihenfolge und Abnahme

- Aktuellen zusammengeführten Branch bestimmen; neuere Snapshotzweige auf nicht integrierte fachliche Änderungen prüfen.
- Pinned Python-Umgebung und npm-Lock frisch installieren. Bestehende Tests zunächst als Basis ausführen; Fehlschläge mit unveränderten Gegenproben diagnostizieren.
- Konkrete Gegenbeispiele als Regression festhalten, dann bounded Korrektur. Keine pauschalen Testlockerungen oder Ausnahmen für fehlerhaftes Produktverhalten.
- Fachkorrekturen in beiden Stores prüfen. Schreibrennen und Migrationen zusätzlich auf PostgreSQL mit getrennten Verbindungen; übersprungene erforderliche Tests zählen nicht als Abnahme.
- Gemeinsame Frontendtests, ESLint, Python-Lint/Typprüfung und Produktionsbuild nach den Korrekturen.
- Isolierte Browser-/HTTP-Abnahme relevanter Aktionen, danach nachvollziehbarer Prüfbericht und gesicherter Gitstand.

## Bereits nachgewiesene Korrekturbedarfe

- Kosten lassen sich über PUT/PATCH aus einem Entwurf in eine finalisierte/zugestellte/bestrittene/korrigierte Abrechnungsperiode verschieben; Quellprüfung allein reicht nicht. PATCH umgeht außerdem die Herkunftsrechnungsprüfung.
- Kautionspositionen werden über frei eingereichte IDs global upserted; fremde Positionen und doppelte IDs benötigen eine explizite Ablehnung.
- Mahnstände müssen echte zukünftige Zahlungen ausschließen, bei Veröffentlichung aber inzwischen erfolgte Zahlungen berücksichtigen.
- Portfoliofence muss implizites Flush sowie Core UPDATE/DELETE erfassen. Doppelte Authorization-Header dürfen nicht zu unterschiedlicher Identität in Middleware und Route führen.
- PostgreSQL-Werkzeugargumente dürfen keine Datenbankpasswörter enthalten; SQLAlchemy `URL.set(password=None)` entfernt kein bestehendes Passwort.
- Projektdokumentauswahl darf nach lokaler Filterung nicht mit der Anzahl sichtbarer statt abgefragter Zeilen weiterblättern.
- Dienstleistungs-/Projektrechnungen müssen Stornos und gemeinsam verbrauchte Buchungsbeträge berücksichtigen.

Dieser Plan dokumentiert die laufende Prüfung. Endgültige Ergebnisse, weitere bestätigte Befunde und Grenzen werden im separaten Abnahmebericht festgehalten.
