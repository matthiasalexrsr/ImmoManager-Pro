# Begrenzte Tests für Release-Härtung

Diese Prüfungen starten eigene Prozesse mit neuen synthetischen Datenordnern und freien Loopback-Ports. Sie verbinden sich nicht mit einer laufenden Installation und verwenden insbesondere nicht Port 8765. Unter Windows gehören die gestarteten Prozesse zu eigenen Jobs und starten ohne Konsolenfenster; unter POSIX werden eigene Prozessgruppen verwendet.

```text
python scripts/release_stress.py --output artifacts/release-hardening/parallel --workers 4 --scale-tasks 512 --operations 640 --assistant-runs 12 --soak-seconds 30 --require-clean-source
python scripts/release_stress_ai_corpus.py --output artifacts/release-hardening/ai-corpus --repetitions 3 --require-clean-source
python -m tools.xstress.run --units 120 --years 5 --skip ui --out artifacts/release-hardening/xstress
```

Jedes Zielverzeichnis muss neu sein. Die beiden neuen Skripte schreiben jeweils `report.json` und `report.md` direkt unter `--output`. Ein bestandener Lauf liefert Exitcode 0; ein unerwarteter Zustand oder fehlgeschlagener Erwartungsabgleich liefert 1. Ungültige Argumente und ein bereits vorhandenes Ziel werden vor dem Test mit 2 abgewiesen. Ein abgebrochener KI-Korpus wird als fehlgeschlagen dokumentiert, soweit sein neu angelegter eigener Ausgabeordner verfügbar ist. Vorhandene Belege werden nicht überschrieben.

Das CI-Flag `--require-clean-source` verlangt bereits vor der Last einen sauberen Checkout.
Beide Berichte erfassen `source_before` und `source_after` mit Commit, Basis-Tree,
Git-Änderungsliste sowie SHA256 sämtlicher von Git erfassten und nicht ignorierten
unversionierten Dateien. Große Dateien werden gestreamt gehasht. Nur ein fachlich
bestandener Lauf mit unverändertem Head, identischen Dateihashes und sauberem Checkout
vorher und nachher erhält `release_eligible: true`. Eine Endänderung macht den Gate-Lauf
mit Exit 1 ungültig; der funktionale `workload_status` bleibt getrennt sichtbar.
Ohne das Flag sind Engineering-Proben im gemeinsamen Arbeitsbaum möglich, werden aber
bei uncommitteten oder veränderten Quellen niemals zu einer Commitfreigabe.
Diese Eignung betrifft nur den quellengebundenen Stresstest, nicht die zusätzlichen
Signatur-, Upgrade-, Sicherheits- und echten Modellqualitätsentscheidungen.

Die Backend-Laufzeit wird benötigt, insbesondere `httpx`, `psutil`, Pillow, `pypdf`, `python-docx` und Reportlab. Qt, Playwright, ein Anbieter-Login und eine Live-Inferenz sind für diese beiden Skripte nicht erforderlich. Die externe UI-Abnahme bleibt eine eigene Prüfung. Die speziellen Regressionen liegen in `backend/tests/test_release_stress_harness.py`; der bestehende Langzeitharness hat seine eigenen Tests unter `tools/xstress`.

## Parallele BW-Demo, Parser und Warteschlange

`release_stress.py` startet die tatsächlich befüllte eigene Baden-Württemberg-Demo mit SQLite. Vier getrennte Benutzer erhalten ausdrücklich ausgewählte Testportfolios. Der Test erweitert den Bestand um 512 Aufgaben, führt 640 gemischte Operationen und anschließend 30 Sekunden Mischbetrieb aus. Gemessen werden tatsächliche parallele Anfragen, Statusverteilungen, unerwartete Antworten und p50/p95/Maximum nach dem beobachteten nächsten Rang. Erfolgreich bestätigte Schreibvorgänge werden anhand ihrer IDs, Inhalte und unabhängiger SQLite-Zählung nach einem regulären und einem harten Neustart geprüft. Auch Datenbankintegrität und Demo-Identität werden verglichen.

Die lokale Warteschlange führt echte Aufträge aus. Dokumentfälle umfassen UTF-8, PDF, DOCX mit Haupttext/Tabelle/Kopf-/Fußzeile, PNG und einen Text mit 1.120.000 Bytes. Originaldownloads und SHA256, erwartete Textstellen und die ausdrücklich angezeigte Begrenzung des langen Textes werden geprüft. Leere Dateien, binärer Text sowie beschädigte PDF-/Bilddateien müssen mit den erwarteten Fehlerstatus abgewiesen werden. Der PNG-Fall erwartet ausdrücklich keine lokale OCR.

Ein ausschließlich im markierten Testserver vorhandener Eingriff verzögert lokale Aufträge mit `[STRESS-HOLD]` um eine Sekunde und erzeugt mit `[STRESS-UNKNOWN]` einen kontrollierten unsicheren Ausgang. Damit werden laufender Abbruch, verspätete Antwort, Wiederholung desselben Kommandos, gleichzeitig eingereichte identische Kommandos, veraltete Revisionen, enger gewordene Quellenfreigabe und Quelländerungen während der Ausführung geprüft. Ein unsicherer Ausgang darf keine fertige Antwort werden und wird nicht automatisch erneut ausgeführt. Reguläre lokale Regeln und Parser werden daneben unverändert verwendet. Der API-Ratenbegrenzer ist nur für diese eigene Lastfixture deaktiviert; das ist keine Prüfung seiner Wirksamkeit.

Der Standardlauf ist auf 600 Sekunden, 1.536 MiB gemessenen eigenen Prozess-RSS, 256 MiB Datenordner und 300 CPU-Sekunden begrenzt. RSS und CPU umfassen den Lastgenerator selbst und seine tatsächlich gestarteten Nachkommen; Disk bezieht sich auf den eigenen Ausgabeordner. Die Prozessgruppe wird nur bei eigenen Ressourcenverletzungen geschlossen. Die Messung ist eine Stichprobe und kein zusätzlicher harter Kernel-RAM-Grenzwert. Die genaue Konfiguration und Ressourcenstichproben stehen im JSON. Übliche Dauer: etwa zwei bis fünf Minuten; die tatsächlich gemessene Dauer ist maßgeblich.

Der harte Neustart dieses Skripts erfolgt nach bestätigten Schreibvorgängen. Absturz mitten im Schreiben, Archiv-Wiederherstellung und Migration werden gesondert durch `tools.xstress` geprüft. Auf dem lokalen Entwicklungsrechner kann der bestehende finanzielle Langlauf ressourcenschonend mit mindestens 60 Einheiten und drei Jahren parallel zu anderen Prüfungen laufen; das vollständige CI-Gate verwendet 120 Einheiten und fünf Jahre. Seine erzeugte Welt und das unabhängige Kontrollbuch sind eine zweite synthetische Fixture, nicht der BW-Demobestand.

## Deterministischer KI-Zuverlässigkeitskorpus

`release_stress_ai_corpus.py` führt den echten Claude-Protokolladapter mit eigens erzeugten lokalen Python-Kindprozessen aus. Diese Prozesse simulieren ausschließlich dokumentierte JSONL-Antworten und Fehler; sie laden keine Kontodaten und kontaktieren keinen Dienst. Die Fälle prüfen Erfolg, beschädigtes oder fehlendes Ergebnis, leere Antwort, unzulässige Werkzeuge, Nichtnull-Exit, Timeout, Abbruch, widersprüchliche Sitzung sowie doppelte Start-/Ergebnisnachrichten. Jeder gestartete Kindprozess muss anschließend beendet sein. Das Zeitbudget des simulierten Anbieterturns ist für die Timeoutfälle ausdrücklich auf eine Sekunde verkürzt.

Daneben werden 40 deutsche Rechnungen gegen tatsächliche lokale Zahlenregeln geprüft, mit Dezimal-/Tausendertrennzeichen und Steuersätzen 0, 7 und 19 Prozent. Die Sollwerte werden unabhängig mit `Decimal` erzeugt. Zwanzig Zuordnungsfälle dürfen eine außerhalb der ausgewählten Fakten liegende Einheit nicht übernehmen. Die Fehlerquote bezieht sich jeweils auf diesen begrenzten deterministischen Katalog und seine Wiederholungen; sie ist keine geschätzte Fehlerwahrscheinlichkeit im Kundenbetrieb.

Die kontrollierten Anbieterantworten belegen Transport- und Anwendungsgrenzen, keine echte Modellqualität, allgemeine inhaltliche Quellentreue oder deutsche Sprachqualität. Ein tatsächlicher deutscher Hugging-Face-Modellbenchmark wird nur als ausgeführt bezeichnet, wenn Laufzeit und Modell wirklich vorhanden und genutzt sind. Ohne diese Voraussetzungen bleibt er im Bericht ausdrücklich `not_executed` und als eigene Release-Qualitätslücke dokumentiert. Die Skripte laden keine Modelle oder optionalen ML-Pakete nach.

Die eigenen Profile, Datenbanken, Uploads und rohen Serverprotokolle bleiben beim Lauf zur Diagnose erhalten. Für ein Belegpaket sind die zusammengefassten Berichte und eine geprüfte ausdrückliche Dateiliste zu verwenden; private Profile werden nicht pauschal kopiert.
