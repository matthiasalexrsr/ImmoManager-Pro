# WISO-Hausverwalter: beobachteter XML-Export

Stand: 1. Oktober 2026. Ziel des Nutzers ist WISO Steuer für Windows. Dieses Programm ist hier nach Nutzerangabe aktuell nicht installiert. Die folgenden Nachweise stammen vom tatsächlich installierten und aktualisierten **WISO Hausverwalter 365, Produktversion 21.02.1530**, ausschließlich aus dessen synthetischem Musterbestand. Ein Verbraucherimport und eine vollständige Kompatibilität sind damit nicht nachgewiesen.

## Reproduzierbare Originale

Die XML-Dateien wurden über die Herstelleroberfläche „Export für Steuererklärung (Anlage V)“ erzeugt, anschließend unverändert lokal gelesen und anhand ihres SHA-256 erneut geprüft. Dateinamenzeiten und tatsächliche XML-Erstellzeiten können abweichen.

| Fall | Exportjahr | Bytes | SHA-256 | XML-Erstellzeit |
| --- | --- | ---: | --- | --- |
| Beide Musterobjekte, AfA-Werte null | 2026 | 4572 | `aa80c1780cca793440ae9b5a1ff18c33bcbef6a7dd249a49d1234b6b735b7c12` | `214502` |
| Dieselben Objektmetadaten, AfA-Werte null | 2025 | 5094 | `7e786f35295a5a9b61747ca90cb7fb8d85f56d8e11f325c58a64b01b16119598` | `220045` |
| Erstes Musterobjekt, Eingabe 2,50 % und 1.234,56 EUR | 2026 | 3437 | `aaaaa253466d08747a4463fbd505fad2c85dd5d135733ce938e094aa1d749b8b` | `221539` |

Die privaten Arbeitsoriginale und vollständigen Strukturberichte werden nicht mit dem Quellcode veröffentlicht. Ihre Prüfsummen dienen der lokalen Wiederholbarkeit.

## Beobachteter Aufbau

Die Wurzel heißt `Elster` und hat keinen semantischen Namespace. Die deklarierten Präfixe `xsi` und `xsd` werden in diesen Beispielen nicht verwendet. Unter `DatenTeil/Nutzdatenblock` enthält ein `Nutzdatenheader` mit Version `101` den Hersteller, die Produktversion und das Exportjahr. Die Nutzdaten enthalten `Jahressteuererklaerung` mit Version `101`, einen `Vorsatz` und je ausgewähltem Objekt einen `Vordruck` mit `name="V"` und fortlaufender `lfdNr`.

Die tatsächlich vorhandenen Felder verwenden `nr`, `index` und `wert`. Ein Vergleich über `(Vordruck.name, Vordruck.lfdNr, Feld.nr, Feld.index)` unterscheidet echte Feldänderungen von verschobenen Geschwisterpositionen. Mehrdeutige Schlüssel bleiben als Listen erhalten und werden nicht still zusammengeführt.

Der Vergleich 2025 → 2026 enthält beim ersten Objekt 36 → 34 Felder: zwei entfernt, 17 geändert, 17 unverändert. Beim zweiten Objekt sind es 23 → 17: sechs entfernt, sechs geändert, elf unverändert. Es wurden keine neuen Feldschlüssel und keine Mehrdeutigkeiten beobachtet. Die vier vorhandenen `HV365_`-Metadatenfelder je Objekt bleiben unverändert. Aus diesen Jahresunterschieden folgt keine allgemeine Steuerbedeutung oder garantierte Formatstabilität.

## Gezielter AfA-Fall 2026

Für das erste Objekt wurden in der Herstelleroberfläche gemeinsam 2,50 % und 1.234,56 EUR eingetragen. Nur dieses Objekt wurde exportiert. Sein Vergleich mit dem ersten Vordruck der 2026-Baseline ergibt:

| Beobachtung | Feldnummer | Index | `wert` |
| --- | --- | --- | --- |
| Neues Feld, numerisch passend zur eingegebenen Rate | `0703418` | `1` | `2.5` |
| Neues Feld, numerisch passend zum eingegebenen Betrag | `0703422` | `1` | `1234,56` |

Alle 34 zuvor vorhandenen Felder dieses Vordrucks haben unveränderte Attributwerte; kein bestehender Schlüssel wurde entfernt. Prozent- und Geldwerte verwenden hier unterschiedliche Dezimaltrennzeichen. Beide Parameter wurden gemeinsam geändert; ein unabhängig isolierter Einzelfeldvertrag ist damit noch nicht bewiesen. Für 2025 liegt kein entsprechender AfA-Änderungsfall vor.

## Implementierter Prüfbaustein und verbleibende Abnahme

`tools/buhl_xml_probe.py` verarbeitet bereitgestellte Bytes ohne Datei-/Netzwerkzugriffe. Die Probe erzeugt semantische Signaturen und deterministische Strukturunterschiede, behält Originalhash und bedeutungstragende Texte bei, behandelt Namespaces über ihre URI und weist Deklarationen von DTD/Entitäten zurück. Die Regressionen prüfen unter anderem Kodierungen, gemischte Textinhalte, wiederholte Geschwister, mehr als 10.000 Felder und tiefe Dokumente. Sie erzeugt keine steuerliche Zuordnung und keinen behaupteten importierbaren Buhl-Datensatz.

Für einen freigegebenen Adapter fehlen weiterhin: vollständig belegte jahresabhängige fachliche Feldzuordnungen, die Prüfung weiterer Zahlen-/Objektfälle und ein tatsächlicher Import in die passende WISO-Steuer-Windowsversion mit anschließendem Wertevergleich. Die Jahressteuerprojektion des ImmoManagers bietet bis dahin ausdrücklich herstellerneutrale, nachvollziehbare CSV-/JSON-Dateien aus gespeicherten Quellen.

Der offizielle Hersteller beschreibt den XML-Exportweg im [Handbuch 2027](https://www.buhl.de/wp-content/uploads/2026/08/wiso-hausverwalter-handbuch-2027.pdf), Seite 107. Die hier dokumentierten Feldnummern und Zahlenformate sind ausschließlich Beobachtungen der lokalen Originale, kein veröffentlichtes Herstellerschema.
