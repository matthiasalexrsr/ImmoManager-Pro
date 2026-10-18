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
  Ansicht oder einer inzwischen geänderten URL-Auswahl werden verworfen,
  einschließlich später Exportantworten und Fehlermeldungen. Eine neue
  Auswahl kann sofort erneut berechnet werden; fehlgeschlagene Eingaben und unklare
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

## Persönlicher KI-Arbeitsbereich am 18. Oktober 2026

`/assistant` ergänzt einen privaten Chatbereich mit eigenen Unterhaltungen,
Verlaufseiten, Archiv, Modellwahl, geschützten Dateianhängen, Bild- und
Dokumentvorschau sowie wiederaufnehmbaren Nachrichteneingaben. Die bestehende
Auswertungsseite und sämtliche Fachformulare bleiben unabhängig davon nutzbar.

Es gibt drei ausdrücklich getrennte Betriebsarten:

- **Lokale Analyse:** ausgewählte Akten, lokale Dokumentextraktion,
  regelbasierte Hinweise und die vorhandene geprüfte Finanzrechnung. Kein
  Anbieteraufruf, kein Konto und kein Modelldownload. Dieser Modus ersetzt
  keinen freien Dialog mit einem Sprachmodell.
- **ChatGPT:** Anmeldung über den offiziellen Codex-App-Server mit einem
  eigenen ChatGPT-Konto. Die Anwendung zeigt den Geräte-Anmeldeweg und
  verwendet keine API-Schlüssel. Konto, verfügbare Modelle und Kontingente
  bestimmen den tatsächlichen Zugang. Die Gerätecode-Anmeldung muss gemäß
  [offizieller Anleitung](https://learn.chatgpt.com/docs/auth#preferred-device-code-authentication-beta)
  in den ChatGPT-Sicherheitseinstellungen beziehungsweise den
  Workspaceberechtigungen freigegeben sein.
- **Claude:** Anmeldung über den offiziellen Claude-Code-Client mit dem
  eigenen Claude-Konto. Bei einem Server ohne lokalen Browser kann der
  freigegebene Anmeldelink auf dem Benutzerrechner geöffnet und ein einmaliger
  Anmeldecode direkt an die laufende Anmeldung übergeben werden.

Die Kontoclients laufen in temporären privaten Profilen je Anwendungskonto.
Globale Codex-/Claude-Profile werden nicht übernommen. Dauerhaft gespeicherte
Anmeldungen und Chatpayloads sind verschlüsselt; der vollständige
Sicherungsschlüssel gehört zur vorhandenen Vollbackupstrategie. Der normale
Uploadpfad liefert private KI-Dateien und Konto-Vaults niemals aus. Beim
Abbruch werden ausschließlich die selbst gestarteten Prozessbäume beendet.

Nur ausdrücklich ausgewählte Immobilien, Einheiten, Parteien, Kontakte,
Dokumente und Dateien gelangen in ein Anfragepaket. Finanzberichte erfordern
zusätzlich eine ausdrücklich ausgewählte Berichtsimmobilie oder -einheit.
Berechnungen verwenden `finance_reports.compute`; Beträge, Filter, Stichtag
und Ergebnishash bleiben nachvollziehbar. Nach einer Finanzdatenänderung
während der Antwort wird sie als veraltet gekennzeichnet und eine
Entwurfsübernahme verweigert.
Aktenrechte werden vor Verarbeitung, Speicherung und Entwurfsübergabe erneut
geprüft. Den Kontoclients werden kein Store, keine API-Anmeldedaten und keine
produktiven Datenpfade übergeben. Schreibwerkzeuge, Shell, Plugins und
zusätzliche Konten sind für Modellläufe deaktiviert; Codex erhält zusätzlich
einen auf das temporäre Arbeitsverzeichnis eingeschränkten Lesebereich.

Aufgaben-, Gesprächsnotiz- und Rechnungsvorschläge besitzen ein striktes
Schema, ausgewählte Quellen und eine bestätigte Prüffassung. Die Übernahme
speichert einen persönlichen Entwurf und öffnet das bestehende Fachformular.
Erst dessen normale Speicheraktion legt den fachlichen Eintrag an. Rechnungen
benötigen einen Dokumentbeleg und passende Dezimalbeträge; ein Modelltext
erzeugt weder eine Buchung noch eine Freigabe oder einen Versand.

Dateigrößen pro Anhang folgen standardmäßig `MAX_UPLOAD_SIZE_BYTES` (50 MiB).
`ASSISTANT_MAX_ATTACHMENT_BYTES` und `ASSISTANT_REQUEST_ATTACHMENT_BYTES`
konfigurieren Verarbeitungspakete auf dem Server. Die Oberfläche nennt die
tatsächliche Dateigröße. Text-, PDF- und DOCX-Auszüge sowie Modellkontext haben
ausdrücklich benannte Verarbeitungsbudgets; die gespeicherten Originale und
die vollständig seitenweise erreichbare Chathistorie bleiben erhalten.
Finanz-Gesamtwerte werden vollständig berechnet; bei mehr als 200 Belegen
wird die Auswahl der an das Modell übertragenen Belege sichtbar benannt.

Offizielle Clients können über `ASSISTANT_CODEX_CLI` beziehungsweise
`ASSISTANT_CLAUDE_CLI` als absolute Serverpfade konfiguriert werden. Windows
erkennt unterstützte lokal installierte native Clients; für andere Server
ist deren Installation getrennt von der Anwendung erforderlich. Die
Oberfläche zeigt einen fehlenden Client als nicht verfügbar an. Lokale
Analysen und Statistiken funktionieren weiterhin.

Die Schemaerweiterung `f019a1b2c001` ist additiv. Vorhandene ungestempelte
Installationen werden geprüft übernommen; eine unvollständige neue
Tabellenfamilie wird nicht still als korrekt gestempelt. Downgrade verweigert
das Verwerfen vorhandener privater KI-Daten. Prüfberichte unterscheiden
synthetische Transportantworten, native Clientstatusprüfungen ohne Konto,
lokale Browserabläufe und tatsächlich authentifizierte Anbieterantworten.
Eine native Statusprüfung mit leerem Profil ist kein Nachweis einer echten
ChatGPT-/Claude-Anmeldung oder einer erfolgreichen Modellantwort.
