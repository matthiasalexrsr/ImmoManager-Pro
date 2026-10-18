# Alltag mit ein bis zwei Benutzern: Aktenzugriff und Bedienung

Dieses Paket baut auf `29e52733a47c006a53aa772b4a7cc8ce9c534e86` auf. Nach der Priorisierung des Anwenders stehen tägliche Benutzbarkeit, Übersicht und verlässliche Aktionen im Vordergrund. Die weitere Optimierung des zuvor gemessenen Zehn-Benutzer-Lastfalls wird zurückgestellt. Die fachlichen Finanzberechnungen, Datenbankmigrationen und Schnittstellenverträge werden durch dieses Paket nicht geändert.

## Änderungen

- **Akten von jeder Seite öffnen:** Der neue Knopf „Akten“ in der Kopfzeile und `Alt+O` öffnen dieselben persönlichen Favoriten und zuletzt geöffneten Akten wie die Arbeitszentrale. Typ, Name und passende Symbole helfen beim Wiederfinden. Weitere Seiten sind erreichbar. Ladefehler haben eine Wiederholungsaktion; sie werden nicht als leerer Bestand ausgegeben. Parteien öffnen ihre vorhandene Informationskarte. Escape, Fokusbegrenzung und Fokusrückgabe funktionieren auch beim Wechsel zwischen den beiden Dialogen. Der Dienst prüft weiterhin den angemeldeten Benutzer und seine aktuellen Objektrechte; die Oberfläche führt keinen gemeinsamen Benutzer-Cache ein.
- **Merkbare Immobilienakten:** Gewählter Bereich und die Teilansichten „Aktive Verträge“ beziehungsweise „Offene Wartung“ stehen in der URL. Neuladen, Direktlinks und Browser-Zurück erhalten den Bereich. Bestehende Hinweisparameter bleiben erhalten. Kennzahlen setzen Bereich und Filter in einem gemeinsamen Navigationsschritt. Die Reiter sind mit Pfeiltasten, Pos1 und Ende bedienbar und besitzen benannte Inhaltsbereiche.
- **Ruhigerer Aktenkopf:** Name, Anschrift und Aktionen stehen zuerst. Die bisher leere große Fotoablage ist in einem eigenen aufklappbaren Fotobereich untergebracht; die Einheitenakte verwendet denselben Ablauf.
- **Fehlende Flächen sind sichtbar:** Eine nicht erfasste Fläche erscheint als unbekannt. Unvollständige Flächenangaben werden benannt; daraus wird kein scheinbar verlässlicher Preis je m² berechnet. Reine Mengen-Spalten ohne einen einzigen erfassten Wert bilden keine künstliche Nullsumme.
- **Verlässliche Belegungsinformationen:** Mieterliste, Parteienkarte, Immobilien- und Einheitenakte berücksichtigen Beginn und tatsächliches Ende eines Vertrags. Eine Kündigung beendet die Anzeige als laufende Vermietung erst nach dem letzten Vertragstag. Zukünftige, frühere und entworfene Verträge bleiben unterscheidbar. Mehrere laufende Verträge einer Partei werden nicht mehr still überschrieben: „+ weitere“ öffnet alle Verträge. Auch weitere Einheiten bleiben über die Suche auffindbar. E-Mail und Telefon sind direkt bedienbare Kontaktlinks. Fehlgeschlagene Namensabfragen in der Immobilienakte werden ausdrücklich angezeigt.
- **Fotowerkzeuge:** Tastaturbedienbare Dateiauswahl, sequentielle Mehrfachübernahme, Fortschrittsanzeige und sichtbare Fehler mit Dateinamen. Nach einem Teilerfolg werden die tatsächlich gespeicherten Fotos neu geladen. Eine möglicherweise bereits erfolgreiche Übertragung wird nicht automatisch wiederholt. Beim Schließen der Akte beginnt kein weiterer vorgemerkter Upload. Fotos lassen sich mit dem bestehenden Dateibetrachter vergrößern. Lesende Benutzer erhalten Vorschau ohne Upload-/Löschknöpfe; der Server behält die maßgebliche Rechteprüfung.
- **Bestätigungen:** Abbrechen erhält zuerst den Fokus. Escape und Tab betreffen den obersten Dialog; anschließend kehrt der Fokus zur auslösenden Aktion zurück. Gleichzeitig angefragte Bestätigungen werden einzeln bearbeitet, statt einen noch offenen Rückgabewert zu überschreiben. Abmelden oder Schließen des Providers verwirft offene Bestätigungen mit einem negativen Ergebnis.
- **Tabellenkorrekturen:** Ein Link oder Knopf innerhalb einer klickbaren Zeile führt ausschließlich seine eigene Aktion aus. Dadurch entstehen keine doppelten Verlaufseinträge beim Öffnen einer Einheit. Normale Zeilenklicks und die Markierung des zuletzt bearbeiteten Eintrags bleiben erhalten. Nicht monetäre Summen können ausdrücklich `sum: 'number'` mit `formatTotal` verwenden; Flächensummen erscheinen in m². Bestehende Geldsummen bleiben centbasiert.

## Prüfung

Die ergänzten Regressionen prüfen insbesondere inklusive Vertragsgrenzen, zukünftige und gekündigte Mietverhältnisse, mehrere Einheiten einer Partei, tatsächlichen Browser-Zurück-Verlauf, gekoppelte URL-Filter, Tastaturreiter, langsame persönliche Aktenantworten nach Benutzerwechsel, vollständige Cursorseiten, Foto-Teilerfolg, fehlgeschlagenes Löschen, geschlossene Upload-Kontexte und gestapelte Bestätigungen. Vorhandene Tests für geschützte Dokumentübertragungen behalten ihre Sitzungs- und Unmount-Prüfungen; ihr Auth-Test-Double enthält jetzt zusätzlich den tatsächlichen Foto-Rechte-Hook.

Der zusätzliche Linux-Browserlauf fand beim unmittelbaren Pfeiltastendruck nach einem Reiterklick einen Timingfehler: Die URL-Auswahl konnte noch den vorherigen Reiter nennen. Die Tastatursteuerung geht jetzt vom tatsächlich fokussierten Reiter aus. Eine Regression hält die ausgewählte Eigenschaft absichtlich unverändert und prüft mehrere unmittelbar aufeinanderfolgende Tastenschritte; eine Erhöhung des Zeitbudgets verdeckt den Fehler nicht.

`scripts/run_daily_browser_qa.py --suite qol` erzeugt eine neue synthetische Installation und führt `scripts/qol_browser_qa.mjs` aus. Die sechs zusammenhängenden Browserfälle umfassen Aktennavigation, Vertragszuordnung, Schnellzugriff, Foto-Teilerfolg, zwei getrennte Benutzerkonten mit Leserechten sowie 320-/360-Pixel-Ansichten. Ergebnisse, Fehler und Bilder werden aufbewahrt; der Testserver wird anschließend beendet. Die neue Suite läuft auch im bestehenden nativen Dokument-/Browser-CI-Job. Die reguläre Einstellung-/Benachrichtigungs-Suite bleibt als Standard erhalten.

Für dieses Paket ist keine zusätzliche Migration erforderlich. Tests verwenden synthetische Daten; reale Mieterdaten und veröffentlichte Originale werden dabei nicht verändert. Ein GitHub-Quellstand oder ein gebautes Frontend allein stellt keine Umstellung der vorhandenen Windows-Installation dar. Der jeweilige Abnahmebericht nennt den tatsächlich geprüften und gegebenenfalls installierten Stand.

## Fortsetzung: Auswertungen und Datengrundlagen am 18. Oktober 2026

Auf Wunsch des Anwenders ist die weitere WISO-/TEHA-Entwicklung zurückgestellt.
Die nicht ausgelieferten Schnittstellenentwürfe wurden im lokalen Git-Stash
`48967f5d942b6aca406b6b40b70dea9137669ebd` erhalten. Die bisherigen geprüften
Funktionen des Ausgangsstands `3531af5a` bleiben bestehen. Dieses Alltagspaket
enthält ausschließlich Bedienung, Auswertungen und belegte Fehlerkorrekturen.

- `/reports` ist ein eigener Bereich in der Finanznavigation, der globalen
  Seitensuche und den persönlichen Seitenfavoriten. Das Dashboard und die
  Immobilien-/Einheitenakten verlinken denselben Arbeitsbereich. Objektbezüge
  verwenden IDs und bleiben mit Zeitraum und Berichtsart in der URL erhalten.
- Zahlungsübersicht, Periodenergebnis und Liquiditätsplanung nennen ihre
  jeweilige Grundlage. Portfolio-, Immobilien- und Einheitenauswahl hängen
  zusammen; ein Elternwechsel entfernt unpassende Kind- und Leerstandsauswahlen.
  Stichtagsjahr, Vorjahr und zwölf Monate lassen sich direkt auswählen.
- Die Zahlungsübersicht verwendet dieselbe centgenaue Buchungsrechnung wie die
  bestehende API. `cash-v2` ergänzt nachvollziehbare Quellen, Dezimalstrings,
  Definitions-/Ergebnishash und wiederverwendbare Berichtsfassungen. SQL filtert
  die tatsächlichen Quellbuchungen vor ihrer Materialisierung. Es entstehen
  keine zusätzlichen Finanzereignisse oder konkurrierenden Buchungstabellen.
- Die Ergebnistabelle zeigt auch sonstige Einnahmen. Kennzahlen und Monate
  führen zu ihren Vorgängen; Leistungsquellen besitzen einen ausdrücklich
  berechneten `contribution`-Bezug. Quellensuche durchsucht den gesamten
  zurückgegebenen Bericht; seine Anzeige ist seitenweise fortsetzbar.
- JSON, CSV und PDF verlangen denselben Ergebnisstand. Änderungen an Quellen
  führen zum überprüfbaren Konflikt, statt andere Zahlen still zu exportieren.
  Unvollständige Antworten und fehlgeschlagene Abfragen erzeugen keine
  scheinbar erfolgreichen Nullberichte. Späte Antworten einer geschlossenen
  Ansicht werden verworfen; fehlgeschlagene Eingaben und unklare
  Speicherungskommandos behalten ihren Wiederanlaufweg.
- Widersprüchliche sichtbare Portfolio-/Objekt-/Einheitsfilter ergeben 422.
  Leistungsberichte prüfen auch implizite Jahresgrenzen. Eine zukünftige
  Rechnungszahlung außerhalb des Planungshorizonts unterdrückt keine Zahlung
  innerhalb der Prognose mehr. Hinweise beziehen sich auf beitragende Quellen.
  Unterschiedliche Kontowährungen werden nicht unter einer gemeinsamen
  Immobilienwährung summiert.
- Rechnungen aus der Immobilienakte verwenden einen exakten Objektfilter,
  einschließlich Kennzahlen und gespeicherter Ansichten. Ein Steuersatz oder
  eingegebener Betrag von null wird erhalten; nur fehlende Beträge werden
  ergänzt. Unbekannte Mietbeträge bleiben unbekannt. Zwischensummen tragen
  einen Vollständigkeitshinweis; Jahresplan und €/m² benötigen vollständige
  Grundlagen. Heizkostenvorauszahlung und Kaution unterscheiden null von leer.

Die Änderungen erweitern vorhandene Modelle und Rechenpfade additiv; eine
Datenbankmigration ist nicht erforderlich. Neue Regressionen halten die
Gegenbeispiele auf Memory und SQLite sowie in den echten React-Seiten fest.
Der bestehende Alltags-Browserlauf prüft zusätzlich den vollständigen
Auswertungsablauf, Centbeträge, Belegsprünge, CSV/PDF, Leserechte und
320-/360-Pixel-Ansichten. Prüfberichte nennen ihren tatsächlichen Quellstand;
die Auslieferungsabnahme liegt beim jeweiligen Release im Sicherungsordner.

Die neue Zahlungsansicht erhält keine künstliche Gesamtzahlbegrenzung. Ein
globaler Bericht liefert weiterhin alle zugehörigen Quellen in einer Antwort;
serverseitige Quellpagination und fortsetzbare sehr große Exporte sind damit
noch nicht allgemein umgesetzt. Dieses Paket behauptet keine neue Abnahme
einer Million Finanzzeilen und keine steuerliche Vollständigkeit des
Periodenergebnisses.
