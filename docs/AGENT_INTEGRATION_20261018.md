# Übernahme der Assistenzarbeiten – 18. Oktober 2026

Dieser Nachweis gehört zu `codex/pro-integration-20261016`, Ausgangspunkt
`b808c5af847225bf9c2d7aa4712df6309fac114f`. Er ersetzt keine Prüfprotokolle
älterer Entwicklungsstände. Die bisherige GitHub-Prüfung dieses Ausgangspunkts
ist vollständig grün: Run `38945664622`, alle neun Jobs erfolgreich.

## Auswahl und Herkunft

Die jüngsten 18 PRO-Entwicklungsverzeichnisse wurden inventarisiert. Der lokale
Nachweis `artifacts/agent-inventory-20261018/inventory.json` enthält ihre Branches,
Commitstände und SHA-256-Werte der 23 geänderten Quelldateien und Übergaben.
Die Quellverzeichnisse wurden ausschließlich gelesen. Ältere Agentenpakete
bleiben durch das bisherige Inventar und die Integrationshistorie dokumentiert.

| Quelle | Übernommener Nutzen | Übernahme |
|---|---|---|
| `pro-qol-integration-qa-20261017`, `03f6d171` bis `fa558fab` | Globale Bestätigungen, Tastaturbedienung, Meldungen, Filter, natürliche Sortierung, CSV, Mehrfachfehler, Formulare und Entwurfswiederaufnahme | Einzelne Commits mit `cherry-pick -x`, Konflikte fachlich aufgelöst |
| Dieselbe Quelle, `adffb873` und `5b9f05e4` | Asynchrone React-Prüfungen ohne unvollständige Erwartungen, ergänzende Browsernachweise | Tests und ursprüngliche Nachweise erhalten; eigene Gesamtprüfung erforderlich |
| `pro-stage-backup-truth-ui-20261017`, `cbebe963` | Ersteinrichtung behauptet keinen unbeobachteten täglichen Sicherungslauf | `d36fc7d6`, einschließlich zwei Gegenproben |
| `pro-stage-combined-billing-20261017`, `fbe835a6` | Fehlende Messtage bei Zählerwechseln verhindern eine unbemerkte Abrechnungsfreigabe | `42aab9be`, einschließlich drei Gegenproben |
| `pro-stage-api-catalog-20261017`, uncommitteter Entwurf | Verwaltungsdiagnosen nur einmal öffentlich registrieren; OpenAPI-Katalog eindeutig halten | `3f45ec8e`, vorab am unveränderten Integrationsstand reproduziert |

Die zusammengeführte Oberfläche erhält die bereits vorhandenen Aktenfavoriten,
den persönlichen Schnellzugriff, den Browser-Verlauf, barrierearme Aktenreiter,
die Vorschau von Benachrichtigungs-E-Mails und korrekt formatierte Geld-/Flächensummen.
Insbesondere wurde die stärkere gemeinsame Dialogverwaltung beibehalten:
überlappende Bestätigungen bleiben getrennt, Abmeldung verwirft offene Zusagen,
und Escape schließt nicht versehentlich eine darunterliegende Akte.

## Sichtbares Verhalten

- Formulare behalten Eingaben nach gescheitertem Speichern. Passende
  Backend-Feldfehler erscheinen am Eingabefeld; eine Tastaturaktion führt
  zum ersten fehlerhaften Feld. Geheime oder fremde Fehlerpfade werden nicht
  ungeprüft als Feldmeldungen übernommen.
- Wiedergefundene Entwürfe werden erst nach erneuter Berechtigungsprüfung
  angeboten. Wiederaufnahme setzt den Fokus in die Eingaben. Endgültiges
  Verwerfen verlangt eine zweite ausdrückliche Entscheidung.
- Tabellen zeigen aktive Such-/Spaltenfilter als einzeln entfernbare Angaben.
  Der Endtag eines Datumsbereichs ist eingeschlossen. Nummerierte Namen werden
  natürlich sortiert; fehlende oder ungültige Werte bleiben von echten Nullwerten
  unterscheidbar. Mindestens eine Spalte bleibt sichtbar.
- CSV-Exporte behalten ihre vollständige Datenquelle. Veraltete private
  Exportantworten nach Sitzungs-/Kontextwechsel werden nicht heruntergeladen.
- Bei Mehrfachaktionen bleiben fehlgeschlagene Einträge ausgewählt. Sämtliche
  Fehler lassen sich einsehen; das Schließen des Berichts entfernt die Auswahl
  für einen gezielten erneuten Versuch nicht.
- Sammelarchivierung im persönlichen Eingang zeigt Umfang und bestätigten
  Snapshot. Abbrechen oder Escape schreibt keinen Empfangsbeleg. Fachliche
  Quellvorgänge werden durch persönliche Empfangsbestätigungen nicht verändert.
- Die Meldungsanzeige pausiert während des Lesens mit Maus oder Tastatur.
  Ein zusätzlich gefundener Fehler bei gleichzeitigem Maus-/Tastaturfokus
  wurde unabhängig reproduziert und korrigiert: Beide Pausegründe müssen
  beendet sein, bevor die Restanzeigezeit weiterläuft.

## Bewusst nicht überschrieben

- Die neueren PostgreSQL-Sicherungs-/Wiederherstellungsprüfungen und der aktuelle
  Migrationspfad bleiben maßgeblich. Der native Reparaturentwurf baut auf einem
  anderen `adopt_existing.py`-Pfad und historischen Migrationsänderungen auf.
  Ein Überschreiben würde bereits abgenommene Integrationsarbeit ersetzen.
- Die unterschiedlichen Entwürfe zur Ablehnung von Abrechnungswidersprüchen
  besitzen mittlerweile Migrationen und Tests. Sie bauen jedoch auf
  `e1f0a1b2c315` auf; der aktuelle gemeinsame Migrationskopf ist `f016a1b2c001`.
  Diese fachliche Erweiterung benötigt eine eigene Anpassung, Datenübernahme
  und Prüfung der Originalerhaltung. Sie wird nicht als fertig integrierte
  Funktion ausgegeben.
- Ältere zusammengefasste Stände und ihre Testergebniszahlen werden nicht über
  den neueren Hauptstand kopiert. Die zweite QoL-Prüfquelle enthält weitgehend
  dieselben Änderungen und wird als zusätzlicher Nachweis berücksichtigt.
- Für WISO-Zielimport, TEHA-Schreibaktionen und andere echte Anbieteraktionen
  entsteht durch diese lokale Übernahme keine zusätzliche externe Freigabe.

## Prüfung des gemeinsamen Stands

Die neuen Regressionen wurden vor dem jeweiligen Fix fehlgeschlagen und danach
erfolgreich ausgeführt: doppelte OpenAPI-Registrierung und überlappende
Meldungspausen. Die gezielte erste UI-Matrix bestand 107 Tests in zwölf Dateien.
Der Browserprüfer `scripts/qol_browser_qa.mjs` wurde um echte Anwendungsabläufe
für Tabellen, Teilfehler, Formulardatenerhalt, Entwurfswiederaufnahme und
Sammelarchivierung ergänzt. Er verwendet eine eigene frische Testinstallation,
synthetische Daten und gesperrte Live-Ports 8000/8765.

Die endgültigen Prüfergebnisse und der genaue freigegebene Commit werden nach
Abschluss in diesem Nachweis ergänzt. Alte Browser-/PDF-/CI-Ergebnisse werden
nicht als Nachweis für ungetestete neue Änderungen verwendet.
