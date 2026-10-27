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

Die abschließende Nachsicht enthält 19 Verzeichnisse. Das inzwischen neu
angelegte `pro-media-expose-rent-ui-20261018` basiert noch auf dem vorhandenen
QoL-Stand und besitzt zum Auswahlzeitpunkt keine neuen Medien-/Exposé-Arbeiten.
Es enthält jedoch den zusätzlichen fertigen Formular-Commit `5eb9bd3c`, der
gezielt übernommen wird. Beide Inventarstände bleiben getrennt erhalten:
`inventory-at-selection.json` und `inventory-at-final.json`.

| Quelle | Übernommener Nutzen | Übernahme |
|---|---|---|
| `pro-qol-integration-qa-20261017`, `03f6d171` bis `fa558fab` | Globale Bestätigungen, Tastaturbedienung, Meldungen, Filter, natürliche Sortierung, CSV, Mehrfachfehler, Formulare und Entwurfswiederaufnahme | Einzelne Commits mit `cherry-pick -x`, Konflikte fachlich aufgelöst |
| Dieselbe Quelle, `adffb873` und `5b9f05e4` | Asynchrone React-Prüfungen ohne unvollständige Erwartungen, ergänzende Browsernachweise | Tests und ursprüngliche Nachweise erhalten; eigene Gesamtprüfung erforderlich |
| `pro-stage-backup-truth-ui-20261017`, `cbebe963` | Ersteinrichtung behauptet keinen unbeobachteten täglichen Sicherungslauf | `d36fc7d6`, einschließlich zwei Gegenproben |
| `pro-stage-combined-billing-20261017`, `fbe835a6` | Fehlende Messtage bei Zählerwechseln verhindern eine unbemerkte Abrechnungsfreigabe | `42aab9be`, einschließlich drei Gegenproben |
| `pro-stage-api-catalog-20261017`, uncommitteter Entwurf | Verwaltungsdiagnosen nur einmal öffentlich registrieren; OpenAPI-Katalog eindeutig halten | `3f45ec8e`, vorab am unveränderten Integrationsstand reproduziert |
| `pro-media-expose-rent-ui-20261018`, `5eb9bd3c` | Escape und Fokus bei Entwurfsrückfragen; gemeinsam zugängliche Feldhinweise und Fehler | `c2e1f3f3`, 55 gezielte Formularprüfungen erfolgreich, echter Browserablauf erweitert |

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
- Die zusätzliche Sichtprüfung fand eine gestalterisch unvollständige
  Eingangsseite und den irreführenden Seitentitel „Dashboard“. Der Eingang hat
  jetzt einen eigenen Navigationseintrag und Seitentitel, eine einheitliche
  Filterleiste, lesbare Einträge und einen gestalteten leeren Zustand. Archiv,
  Fehler, Wiederholung und Seitenwechsel bleiben erreichbar; schmale Ansichten
  werden im echten Browser geprüft.
- Die Meldungsanzeige pausiert während des Lesens mit Maus oder Tastatur.
  Ein zusätzlich gefundener Fehler bei gleichzeitigem Maus-/Tastaturfokus
  wurde unabhängig reproduziert und korrigiert: Beide Pausegründe müssen
  beendet sein, bevor die Restanzeigezeit weiterläuft.
- Ein zusätzlicher Edge-Browserfall fand beim Wechsel auf 320 Pixel eine
  kurzfristige Dokumentbreite von 599 Pixeln. Die globale Regel für reduzierte
  Bewegung aktivierte mit einer universellen Dauer von 0,01 ms auch zuvor
  nicht vorhandene Größenübergänge. `transition: none` und `animation: none`
  berücksichtigen diese Einstellung jetzt unmittelbar. Ein eigener DOM-Probe-
  Nachweis ermittelt danach sowohl unmittelbar als auch nach dem Umschalten
  exakt 320 Pixel ohne überstehende Elemente. Der Browserfall wartet zusätzlich
  auf die tatsächlich angezeigten Mobilsteuerelemente und prüft weiterhin
  die vollständige Dokumentbreite.

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

Die erste vollständige lokale Frontend-Prüfung des zusammengeführten Codes
bestand **775 Tests in 119 Dateien**, die SQLite-Fachmatrix **164 Tests ohne
übersprungene Fälle**. ESLint, Ruff und Produktionsbuild sind erfolgreich.
Die gezielte Gegenprobe zur überlappenden Meldungspause besteht sechs Tests.
Die spätere Änderung an `frontend/src/test/setup.js` ergänzt ausschließlich
die ausdrücklich fehlende jsdom-Scrollimplementierung als Spy; tatsächliche
Browserbewegungen werden weiterhin im Browser geprüft.

Der eigene Browserlauf in Chromium besteht **zehn zusammenhängende Fälle**;
keine JavaScript-Seitenfehler und keine externen Anfragen. Nachweise:
`artifacts/agent-qol-browser-final-20261018/daily-l9cpi6oh`, einschließlich
Abschlussbeleg über den beendeten eigenen Server. Geprüft wurden 1440, 360
und 320 Pixel sowie zwei getrennte Benutzer. Tabellen-, Formular- und
Mobilbilder wurden auch visuell geöffnet und geprüft.
Eine zusätzliche Erwartung wartet jetzt bei Mobilbildern auf das Ende beider
Aktenladevorgänge. Der ursprüngliche Fehlversuch bleibt als roter Nachweis
erhalten: Seine letzte Behauptung verwendete irrtümlich ein Objekt statt der
tatsächlichen Listenantwort; nach Korrektur besteht der gesamte Ablauf.

`scripts/run_daily_browser_qa.py --binary <Pfad im Checkout>` unterstützt nun
denselben Ablauf mit der tatsächlich gebauten Windows-Anwendung und zeichnet
deren SHA-256 auf. Beide Varianten erzeugen ausschließlich eine neue eigene
Testinstallation. Das Windows-Paket wird separat gebaut und geprüft; ein
Build allein bestätigt keine Auslieferung auf einer bestehenden Installation.

Der zusätzliche Windows-Build reproduzierte einen Pfadlängenfehler im langen
Ausgabeverzeichnis: Unnötig mitkopierte `__pycache__`-Dateien von Migrationen
besitzen noch längere Namen als die eigentlichen Quellen. Das Spec übernimmt
jetzt ausschließlich die maßgeblichen Quell-/Assetdateien dieser beiden
Projektverzeichnisse und schließt `.pyc`/`.pyo` sowie Cacheverzeichnisse aus.
Die Alembic-Quellen und Wizardvorlagen bleiben enthalten. Der fehlgeschlagene
Build wird als roter Nachweis erhalten; das vollständige Paket wird anschließend
erneut gebaut und als tatsächliche EXE im Browser geprüft.

Der längere Windows-Prüfpfad fand außerdem einen echten MAX_PATH-Fehler beim
Fotoupload. Die neue interne Pfadumsetzung verwendet erweiterte Win32-Pfade
ausschließlich für Dateisystemzugriffe. Öffentliche Dateischlüssel, URLs,
Traversierungsprüfung und Originalschutz bleiben erhalten. Lokaler Speicher
und private Dateiauslieferung verwenden dieselbe Umsetzung. Die Vollsicherung
erfasst lange Anhänge vollständig; Wiederherstellung, Referenzprüfung und
Aufräumen der eigenen Prüfverzeichnisse berücksichtigen diese Pfade ebenfalls.
Zwei ursprüngliche Speichergegenproben und eine Sicherungsgegenprobe wurden
vor der Korrektur unabhängig fehlgeschlagen. Anschließend sind 24 Speicher-/
Upload-/URL-Prüfungen und vier gezielte Sicherungs-/Langpfadprüfungen grün,
einschließlich Unveränderlichkeit, OCR-Korrektur, privatem HTTP-Download,
HEAD/Range, ZIP-Originalvergleich und vollständiger Wiederherstellungsprobe.
Die Windows-Diagnoseausgabe des Browserprüfers verwendet UTF-8, damit ein
Unicodezeichen im Fehlerbericht nicht die eigentliche Ursache verdeckt.

Die anschließende GitHub-Matrix prüft den eingefrorenen Push einschließlich
beider Python-Versionen und Storevarianten, PostgreSQL, Docker-Smoke,
Wiederherstellung und Dokument-/Browserabläufen. Ihr Ergebnis wird im lokalen
abschließenden Abnahmebericht und in der Übergabe mit genauer Run-ID benannt.
Ein noch laufender Job wird nicht als bestanden gezählt. Alte Browser-/PDF-/
CI-Ergebnisse werden nicht als Nachweis für ungetestete Änderungen verwendet.
