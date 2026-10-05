# Extrem-Stresstest

Simuliert fünf Jahre Hausverwaltung mit echten Benutzern und Rollen gegen einen echten
Server (uvicorn + SQLite). Ziel ist es, Fehler, falsche Ergebnisse, Lücken und
Rechteprobleme sicher zu finden. Jede Zahl, die die App anzeigt, wird gegen ein
unabhängiges Kontrollbuch geprüft.

```bash
python -m tools.xstress.run --quick       # 15 Einheiten, 1 Jahr, ca. 10 min (prüft den Test selbst)
python -m tools.xstress.run               # 120 Einheiten, 5 Jahre, ca. 30–60 min
python -m tools.xstress.run --units 300 --years 5 --seed 7 --out /tmp/xstress
python -m tools.xstress.run --skip ui     # ohne Browser-Durchlauf
```

Ergebnis: `stress-results/report.md` (lesbar) und `stress-results/findings.json`.

Für den Browser-Durchlauf werden `frontend/dist` (`npm run build`) und Playwright gebraucht.
`XSTRESS_NODE_PATH` zeigt auf ein `node_modules` mit Playwright, `CHROMIUM` auf den Browser.

## Phasen

| Phase | Was passiert | Wer |
|---|---|---|
| Aufbau | Portfolios, Konten (Bank und Barkasse), Kategorien, Immobilien, Einheiten, Zähler; Mietverhältnisse, die vor dem Zeitraum begannen | Eigentümer, Verwalter, Hausmeister |
| 60 Monate | Einzüge (auch zum 16.) mit Kaution und Übergabe, Kündigungen, Auszüge mit Kautionsrückzahlung und Abzügen, Leerstand | Verwalter, Hausmeister, Buchhaltung |
| | Index-, Staffel- und Vergleichsmieterhöhungen: sofort angewendet, später angewendet oder abgelehnt | Verwalter |
| | Mietzahlungen nach Mieterverhalten: pünktlich, spät, teilweise, Rückstand mit Nachzahlung, Überzahlung, Rücklastschrift, quartalsweise, Zahlendreher, bar, Zahlungsstopp vor Auszug, eine Überweisung für Wohnung und Stellplatz | Buchhaltung |
| | Quartalsweiser Bankimport (CSV) ohne Mieter, danach Zuordnung von Hand; 10 % bleiben offen | Buchhaltung |
| | Betriebskosten, Grundsteuer, Versicherung, Verwaltung; Wartungsfälle mit Rechnungen | Buchhaltung, Hausmeister |
| | Jährliche Nebenkostenabrechnung je Haus (Schlüssel, Kostenpositionen, Erzeugen, Abschließen, Forderungen) und Anpassung der Vorauszahlung bei hoher Nachzahlung | Verwalter |
| | Jährliche Zählerablesung, vereinzelt mit Ablesefehler | Hausmeister |
| | Mahnlauf zweimal im Jahr; der Steuerberater liest Berichte und versucht jeden Monat eine Buchung (muss scheitern) | Verwalter, Steuerberater |
| Prüfungen | Alle 6 Monate und am Ende: Mieterkonten (Soll, gezahlt, Aufteilung), aktuelle Mieten, Mietverläufe, Dashboard, Belegung, Summe aller Buchungen, Berichte, Prüfliste | – |
| Speichern/Laden | Jedes Jahresende: Neustart, Export → Import in eine frische Installation, doppelter Import. In der Mitte und am Ende zusätzlich: Backup → Änderung → Restore, Migration auf einer Kopie, harter Absturz mitten im Schreiben. In der Mitte: Stromausfall (Server hart beendet) | Eigentümer |
| Fehldaten | Rund 90 unplausible oder fehlerhafte Eingaben (negative Mieten, Datum 1900/2100, Brutto ≠ Netto + MwSt, Kaution über drei Mieten, Kappungsgrenze, Nullbytes, 5000 Zeichen, deutsches Zahlenformat, falsche Zugehörigkeiten, kaputte Importdateien …) auf einer Kopie | Verwalter |
| Rechte und Gleichzeitigkeit | Rechte-Matrix für fünf Rollen, Rollenanhebung, deaktivierte Benutzer, Passwort-Reset, Kontosperre; gleichzeitige Änderungen, 40 parallele Zahlungen, doppeltes Anwenden einer Mietanpassung, Doppelklick auf Speichern, 30 s Lesen unter Last | alle |
| Oberfläche | Jede Seite für Eigentümer, Buchhaltung, Hausmeister und Steuerberater: JS-Fehler, Serverfehler, verweigerte Anfragen, Rohtexte, Ladezeiten, Bearbeiten-Knöpfe für Nur-Lesen | alle |

Die Daten sind bewusst unvollständig: etwa 15 % der Häuser ohne PLZ oder Baujahr,
12 % der Einheiten ohne Fläche oder Personenzahl, 15 % der Mieter ohne E-Mail oder IBAN,
6 % der Verträge ohne Kaution. Einheitentypen mischen deutsche Wörter und englische Codes.

## Befundklassen

| Klasse | Bedeutung |
|---|---|
| KRITISCH | Serverfehler (5xx), keine Antwort, Datenverlust oder veränderte Daten nach Speichern/Laden |
| FALSCH | Ergebnis weicht vom unabhängigen Kontrollbuch oder von einer anderen Ansicht ab |
| LÜCKE | Unplausible oder ungültige Eingabe wird ohne Ablehnung angenommen, oder Fachliches fehlt |
| RECHTE | Eine Rolle darf mehr (oder weniger), als eine Hausverwaltung erwarten würde |
| LANGSAM | Aufruf über 2 s, Seite über 4 s, Last-p95 über 2 s |
| HINWEIS | Auffällig, aber nicht falsch (z. B. Warnung fehlt, Fehlermeldung nur auf Englisch) |

## Das Kontrollbuch (`ledger.py`)

Rechnet unabhängig vom App-Code nach den fachlichen Regeln: Miete je Kalendermonat,
Teilmonate taggenau (Cent je Bestandteil kaufmännisch gerundet), Mietänderungen ab dem
Gültig-ab-Datum, Vorauszahlungen je Nutzungszeitraum, Zahlungen je Mieter.

## Dateien

| Datei | Inhalt |
|---|---|
| `world.py` | Die simulierte Welt (deterministisch je Seed) |
| `core.py` | Testserver, Clients je Benutzer, Befunde, Bericht |
| `timeline.py` | Die 60 Monate |
| `ledger.py` | Das Kontrollbuch |
| `invariants.py` | Prüfungen und Fingerabdruck für Speichern/Laden |
| `saveload.py` | Neustart, Absturz, Export/Import, Backup/Restore, Migration, kaputte Dateien |
| `bad_input.py` | Katalog der Fehldaten |
| `roles.py` | Rechte-Matrix und Gleichzeitigkeit |
| `ui.js` | Browser-Durchlauf je Benutzer |
| `run.py` | Ablauf und Aufruf |
