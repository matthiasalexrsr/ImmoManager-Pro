# Prüfung und Fortführung des Claude-Stands vom 14. Oktober 2026

## Ausgangspunkt und Integration

Geprüft wird Claudes aktueller Remote-Stand `8d4abd4f` auf
`claude/dreamy-gauss-nmaxhn`. Er enthält die früher veröffentlichte Prüfung bis
`3909602b` sowie 17 zusätzliche Commits mit Tabellen-/Formularabläufen, Objektakten,
Übernahme laufender Mietverhältnisse, Aktenwerk-Austausch, Backup-Einstellungen und
Windows-Releasevorbereitung. Die lokale Prüfung vom 13. Oktober hatte zusätzlich
noch nicht veröffentlichte Verbesserungen an atomaren Buchungen, Cachegrenzen,
SQLite-Schreibzulassung, CSV-Feldschutz und mobilen Mietkennzahlen.

Merge `26ce2bce` erhält beide Entwicklungsstände. Claudes deutsche Tabellen-CSV
(Semikolon, Dezimalkomma, CRLF/BOM) verwendet nun ebenfalls den gemeinsamen Schutz
gegen Formelinhalte einschließlich Steuerzeichen und BOM in Texten sowie Köpfen.
Echte beziehungsweise streng geprüfte numerische Werte behalten ihr Vorzeichen.
Die veröffentlichten Migrationen `981b2631e1e8` und `7a2c8e4f1b90` behalten ihre
Identitäten; die reine Merge-Revision `d2e6c8a4f019` bildet den gemeinsamen Head.
Vorhandene Datenbanken beider Zweige können regulär auf diesen Head wechseln.

Implementierungsstand für die gestarteten Gesamtprüfungen: **`ac6e5ce3`**;
anschließender enger Windows-Schlüsseldateifix: **`0b455aeb`**.
Eigene Testdaten, Archive, Schlüssel und Testprozesse liegen in isolierten
synthetischen Verzeichnissen. Die Anwenderdatenbank wird dabei nicht migriert.

## Konkrete Korrekturen

- **Übernahmekonten:** Positive Alt-Rückstände erscheinen erst ab dem Übernahmetag.
  Erstattungen verbrauchen übernommenes Guthaben. Rückzahlungen/Rücklastschriften
  oberhalb der vorhandenen Zahlungen verschwinden nicht mehr, sondern bleiben als
  datierte Forderungen mit stabiler Buchungsidentität erhalten. Mehrere Zuordnungen
  derselben Buchung werden zuerst zusammengefasst. Monatsmiete und mehrere
  gleichdatierte Zusatzforderungen überschreiben sich nicht. Konto, Abrechnung,
  Monatsübersicht, Mahnung und Kautionsprüfung verwenden dieselbe fachliche Basis.
- **Suche:** Veraltete Antworten und frühere Folgeseiten können eine neuere Suche
  nicht mehr überschreiben. Gespeicherte Suchverläufe werden geprüft. Tastatur-
  navigation folgt der sichtbaren Reihenfolge; Suchkurzbefehle stören keine Dialoge.
- **Formulare:** Ein sofortiger zweiter Speicherversuch wird unterbunden. Während
  der Speicherung sind Eingaben geschützt. Explizites Verwerfen, Navigation zu
  Voraussetzungen und Browser-Schließen behandeln ungespeicherte Änderungen
  konsistent. „Speichern & weiteren“ bleibt auch nach dem allerersten Datensatz
  geöffnet und übernimmt nur dafür vorgesehene Felder.
- **Objektaktionen:** Neue Einträge werden nach den Rechten ihres jeweiligen
  Zielbereichs angeboten. Der Objektkontext bleibt erhalten. Sehr große numerische
  Vertragsreferenzen lassen die Nummernsuche nicht mehr in einer Endlosschleife hängen.
- **Tabellen:** Ein anderer Listenschlüssel startet mit seinen eigenen Einstellungen
  und erhält nicht die Filter/Auswahl der vorherigen Liste. Beschädigte gespeicherte
  Spalten- und Bereichswerte werden ignoriert. Sammelaktionen bleiben von der
  Bestätigung bis zum abgeschlossenen Neuladen gegen Überlappung gesperrt; ein
  zwischenzeitlich leerer Bestand darf ihren laufenden Zustand nicht aushängen.
  Gehaltene „Neu“-Anfragen können nicht von einer anderen Seite verbraucht werden.
- **Aktenwerk:** Filteränderungen verwerfen die alte Versandvorschau. Erfolgreiche
  Teilübertragungen bleiben sichtbar, wenn ein späterer Teil scheitert. Nicht lesbare
  Dateien führen zu einem eigenen Ergebnis. Fehlende Journalbestätigung wird
  angezeigt. Dokument und zugehöriger Buchungsbeleg nutzen eine gemeinsame
  kanonische Identität, statt denselben Beleg doppelt zu senden oder ihn fälschlich
  als fehlend abzulehnen. Fehlerhafte Serveradressen werden geprüft.
- **Belegrechte:** Berechtigte Buchungsbelege sind auch für eingeschränkte Benutzer
  lesbar. Dazu gehört zwingend die Gegenprüfung beim Schreiben: Ein bekannter fremder
  Dateipfad darf weder beim Anlegen noch beim Ändern einer Buchung angehängt und
  dadurch freigeschaltet werden. SQL- und Memory-Pfade werden getrennt geprüft.
- **Cache und Parallelbetrieb:** Die vorherige konservative Read-Guard-Erweiterung
  behandelte selbst bekannte SUM-/COUNT-/ROUND-/LOWER-Abfragen als unbekannte
  Schreibvorgänge und invalidierte andere Leser-Caches. Bekannte reine Built-ins
  und die app-eigene SQLite-Lowercase-Funktion sind jetzt ausdrücklich als Reads
  erkannt. Unbekannte/anders qualifizierte Funktionen, DML-CTEs, unbekanntes SQL
  und Locking-Reads bleiben geschützt; PostgreSQL-XID und gehaltene Sperren werden
  weiterhin vor der Verbindungsfreigabe geprüft.
- **Erste Schlüsselanlage unter Windows:** Ein im SQLite-Gesamtlauf sporadisch
  auftretender Fehler wurde mit einer echten gehaltenen leeren Windows-Sperrdatei
  deterministisch reproduziert. Der bisherige Initialisierungs-Bytewrite vor dem
  Sperren konnte mit dem anderen Worker kollidieren und `PermissionError` auslösen.
  Windows erlaubt das Sperren eines Bereichs jenseits des Dateiende; der unnötige
  vorgezogene Schreibzugriff entfällt. Identität und Aufbewahrung aller Schlüssel
  bleiben unverändert. Die neue Regression scheitert vor dem Fix und besteht danach.
  [Microsoft: Bytebereichssperren](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-lockfileex),
  [Python: msvcrt.locking](https://docs.python.org/3/library/msvcrt.html).

## Gezielt nachgewiesene Fälle

- Schema/Index/SQLite-Migrationen: **34 bestanden**; Upgrade von beiden vorhandenen
  Branch-Schemata mit Daten zusätzlich auf PostgreSQL: **2 bestanden**.
- Read-Connection- und Transaktionsschutz: **37 bestanden**, davon **14 native
  PostgreSQL-Fälle**. Reine Aggregate invalidieren weder während der Abfrage noch
  bei Freigabe einer Request-Verbindung die bestehenden Leser-Caches.
- Root-Tabellen/CSV/Neu-/Shell-Abläufe: **64 bestanden**. Die ursprünglichen
  Regressionen für Listenschlüssel und beschädigte Einstellungen scheiterten vor
  der Korrektur. Nach unabhängiger Durchsicht wurde zusätzlich der Lebenszyklus
  einer laufenden Sammelaktion abgesichert.
- Such-/Formular-/Wiederholung-/Objektaktionen: **51 bestanden**; anschließend
  **19 Formularfälle** erneut bestanden. Eigene statische Frontendprüfung sauber.
- Erweiterte Finanzintegration: Memory **116 bestanden, 2 backendabhängige Skips**.
  SQLite **38 bestanden**; eine korrigierte testseitige Erwartung zum Ausblenden
  bereits bezahlter Mahnforderungen anschließend einzeln bestanden. Diese
  abgestuften Ergebnisse ersetzen noch keinen vollständigen Endlauf.
- Aktenwerk/Update: Memory **50 bestanden**, SQLite **44 bestanden**; die letzten
  Rechte-/Aliasfälle nochmals in beiden Stores bestanden. Frontend **13 bestanden**.
  Backup-Zweitziele: **13 bestanden** (36 nicht ausgewählte Fälle).

## Abschließende gemeinsame Abnahme

Bereits vollständig abgeschlossen:

| Prüfung | Ergebnis |
| --- | --- |
| Gesamtes Frontend | **453 bestanden**, 71 Testdateien; Lint und Produktionsbuild erfolgreich |
| Verpflichtende PostgreSQL-Prüfung | **85 bestanden, 0 übersprungen**, 722,52 s; kein stiller Skip-Freigabepfad |
| Ruff / mypy | Backend und Werkzeuge sauber; **394 Backend-Dateien** typgeprüft |
| Lasttest-Werkzeugregressionen | **43 bestanden** |
| Echte Browser-Mietzahlung | **7/7 bestanden**, keine Seitenfehler; eigene Prozesse beendet |
| Echte Browser-Parteien-/Dokumentenakte | **14/14 bestanden**, keine JavaScript-/API-/Cleanupfehler; eigene Prozesse beendet |

Browser: Chromium **153.0.8010.12**, tatsächliche Desktop-/Mobilabläufe bei 1440,
360 und 320 Pixeln. PDF-Vorschau/-Download, historische Mietverträge, 26 Dokumente
über Folgeseiten, vollständiger CSV-Export, echte Einzel-/Mehrfachuploads,
Kontaktkarte, Tastatur-/Fokusverhalten und Nur-Lese-Aktionen wurden ausgeführt.
Kontrollbilder der Mietübersicht, Zahlungsmaske und Parteienakte wurden visuell
geprüft. Die Nur-Lese-Prüfung verwendet ausdrücklich lesenden Zugriff auf die
Portfolios dieses vollständig synthetischen Testservers; getrennte Backendtests
prüfen die Einschränkung auf einzelne Portfolios.

Die ersten Parteien-Browserversuche enthielten zwei Aufbaufehler: zunächst alte
Standardkontonamen, danach ein eingeschränktes Testkonto ohne Zugriff auf die neu
erzeugte Testimmobilie. Sie bleiben unter `browser-party-moua5gxg` und
`browser-party-0x67frfn` erhalten. Der vollständige korrigierte Lauf ist
`browser-party-tqc09gy1`; Mietzahlung: `browser-rent-dt3d87jd`.

Die Memory-/SQLite-Gesamtläufe sind abgeschlossen. Beide fanden dieselbe starre CORS-
Testerwartung für Port 3000, obwohl die isolierte Konfiguration ausschließlich
Port 5173 erlaubt. Die Anwendung lehnt die nicht erlaubte Adresse korrekt ab.
Die Testdatei prüft jetzt die tatsächlich konfigurierte Adresse und zusätzlich
eine fremde Adresse. Vollständige Gegenprüfungen der Integrationstestdatei:
**27/27 Memory** und **27/27 SQLite** bestanden. Die Erstläufe und diese gezielten
Wiederholungen werden ausdrücklich getrennt dokumentiert; es gab dafür keine
Lockerung der Produktkonfiguration.

| Gesamtlauf vor den letzten Korrekturen | Ergebnis | Abdeckung |
| --- | --- | --- |
| Memory (`backend-final-memory-gnybezp2`) | **2.007 bestanden, 101 übersprungen**, ein CORS-Testfehler; 2.198,84 s | **86,93 %**, Ziel 80 % erreicht |
| SQLite (`backend-final-sql-s7kt6qb9`) | **2.007 bestanden, 100 übersprungen**, CORS-Testfehler und reproduzierter Windows-Schlüsselfehler; 2.667,62 s | **86,44 %**, Ziel 80 % erreicht |

Die Gesamtläufe haben jeweils 2.109 Fälle ausgeführt/ausgewiesen. Native PostgreSQL-
Fälle werden dort mangels Opt-in übersprungen und separat im verpflichtenden
85-Fälle-Gate ohne Skips geprüft. Die übrigen bedingten Skips stehen vollständig
in den Rohprotokollen. Kein weiterer Fehlschlag trat auf.

Für den letzten Windows-Fix bestanden anschließend **15 gezielte SecretBox-/
Schlüssel-/Backup-Geheimnisprüfungen je Store**. Sie umfassen die neue deterministische
Windows-Regression, Schlüsselrotation, fehlende Schlüssel, verschlüsselte
Konfiguration, Passphrase-Envelope, Vollarchiv, Wiederherstellungsprobe und
Wiederherstellung in ein neues Verzeichnis. Der tatsächliche SQLite-Gesamtlauf-
Trace bestätigt denselben `PermissionError` beim ungesperrten Initialisierungswrite.
Ruff und mypy des endgültigen Codes bestehen ebenfalls.

Damit besteht der Nachweis ausdrücklich aus den beiden vollständigen Erstläufen
und den erfolgreichen gezielten Korrekturprüfungen. Nach diesen engen Änderungen
wurde kein zweiter vollständiger ununterbrochener Matrixlauf durchgeführt; die
fehlgeschlagenen Erstläufe werden nicht nachträglich als grün ausgegeben.
Die abschließenden Lastmessungen stehen in den folgenden Abschnitten.
Laufartefakte: `artifacts/review-20261015/`.

### Millionendatensatz auf dem endgültigen Implementierungsstand

`scale/rows-1000000-qzjevyft` auf `0e0d6fa` besteht alle ausgeführten unabhängigen
Finanz-, Konto-, Forderungs-, Such-, Seiten- und Exportorakel. Eine Million Buchungen
und 240 synthetische Kalendermonate bilden die Größenbasis. Der konfigurierte
Mischbetrieb dauert 60 Sekunden, einschließlich Abschluss laufender Anfragen
62,24 Sekunden. Zehn getrennte Benutzer erreichen zehn gleichzeitige Anfragen;
97 Lese-/Schreibüberlappungen, **38/38 bestätigte Schreibvorgänge nachgeprüft**,
keine HTTP-Fehler. Das zeitbegrenzte Testfenster hat 38 Vorgänge ausgelöst; zwei
weitere theoretisch mögliche Schleifen waren nicht mehr angefordert, nicht verloren.
Relevante Quellfingerprints blieben unverändert. Eigene Prozesse wurden beendet.
Vollständige ausgewählte Suchexporte: 10.310 Eigentümer- und 3.437 eingeschränkte
Treffer. Spitzen-RSS der Anwendung **330,23 MiB**, private Bytes **301,74 MiB**.

| Messung | Anfragen | p95 | Maximum |
| --- | ---: | ---: | ---: |
| Cashflow im Mischbetrieb | 610 | 1,342 s | 3,049 s |
| Suche im Mischbetrieb | 51 | 7,417 s | 7,490 s |
| Buchung im Mischbetrieb | 38 | 0,475 s | 0,483 s |
| Finanzbericht einzeln | 11 | 6,946 s | 6,946 s |
| Cashflow einzeln | 10 | 10,323 s | 10,323 s |
| Suche einzeln | 11 | 4,885 s | 4,885 s |

Gesamtlauf inklusive frischer Datenerzeugung: **464,86 s**. Die fachliche Prüfung
ist erfolgreich; die Geschwindigkeitswerte sind kein durchgehend bestandener
interaktiver Leistungstest. Sie sind teilweise deutlich schlechter als die
Messungen vom 13. Oktober. Eine nachfolgende Prozessmessung bestätigt zugleich
eine weitere fremde CPU-aktive Prüfung auf diesem Rechner (1,25 CPU-Sekunden in
zwei Sekunden). Fremde Programme wurden weder angehalten noch verändert. Daraus
lässt sich der Anteil der Rechnerlast an der Verlangsamung nicht isolieren. Dieser
Lauf wird ausdrücklich als Messung auf einem geteilten Host ausgewiesen, nicht als
sauberer kausaler Vergleich einzelner Codeänderungen. Die ungefähr sieben Sekunden
Suchlatenz bleiben ein konkreter weiterer Optimierungspunkt.

Rohwerte und Routenvergleich der historischen und neuen Läufe:
`artifacts/review-20261015/scale-comparison.json`. Der eigene Schreibstoß wird in
der folgenden XStress-Gegenprobe getrennt geprüft.

### Abschließender XStress-Lauf

`xstress/run-dze_zucf` auf demselben Implementierungsstand: 1.911 API-Aufrufe,
15 Einheiten, 27 Mietverhältnisse und ein synthetisches Verwaltungsjahr. Keine
Befunde der Klassen KRITISCH, FALSCH, LÜCKE oder RECHTE; 35 LANGSAM-Befunde und
sechs Hinweise. UI wurde hier ausgelassen und separat tatsächlich geprüft.
Zehn unabhängige Benutzer erzeugten 209 Zugriffe, 91 Lese-/Schreibüberlappungen
und **40/40 nachgelesene Schreibvorgänge**, ohne HTTP-Fehler. Last-p95 **3,50 s**
überschreitet das unverändert geltende Zwei-Sekunden-Ziel. Langsame Routen:
Prüfliste bis 5,03 s, Berichte bis 4,70 s, aktuelle Mieten bis 4,53 s und
Parteikonto bis 3,50 s. Buchungsschreibvorgänge lagen maximal bei 1,97 s.
Der Lauf endet deshalb korrekt mit Status 1; er wird nicht als vollständig
bestandener Leistungstest bezeichnet. Relevante Quellfingerprints blieben
während der Messung unverändert. Rohbericht und Anfragezeiten bleiben erhalten.

## Präzise Grenzen und Folgearbeiten

Die neue Rückzahlungsgrundlage sichert Kontosummen und datierte überschießende
Forderungen. Die bestehende vollständige historische Verzugszinsberechnung nach
Rückgabe bereits verrechneter alter Zahlungen benötigt dagegen noch datierte
Zahlungs-/Rückgabeereignisse. Eine vollständige Abnahme dieses Zinsverlaufs wird
hier nicht behauptet.

Aktenwerk wurde mit simulierten HTTP-Antworten geprüft; es fand keine reale
Übertragung statt. Ebenso wurden kein GitHub-Release veröffentlicht, kein
Windows-Installationspaket gebaut und kein WISO-Steuer-Zielimport durchgeführt.
TEHA-Schreibabnahme und WISO-Steuer-Zielimport bleiben externe Abnahmepunkte.

Die SQLite-Queue gilt pro Engine und Prozess für umgestellte Buchungs-, Archiv-
und Audit-Schreiber. Andere Prozesse und Legacy-/Billing-/Maintenance-Schreiber
bleiben außerhalb dieser Zulassung. Explizite fremde Transaktionen bleiben privat.
Rohe DBAPI-`BEGIN`-/`SET`-Steuerung liegt außerhalb des disponiblen Middleware-
Lesevertrags; dafür werden explizite Session-Transaktionen/Connection-Binds erhalten.

Globale Prüfliste, vollständiges Einsammeln aller Seiten der globalen Dokument-
ansicht und Substring-Suche über sehr große Bestände bleiben eigene Skalierungspfade.
Ein Test mit einer Million Finanzzeilen beweist keine vollständige zwanzigjährige
Fachsimulation und keine garantierte PostgreSQL-Serverkapazität.

## Nächste QoL-Ausbaustufe – Vorschläge vom 15. Oktober

Diese Vorschläge wurden inzwischen vollständig vom Benutzer zur Umsetzung
beauftragt; sie sind noch nicht Bestandteil der oben geprüften Umsetzung.
Bereits vorhandene Sammelaktionen, Favoriten, Kurzbefehle, Duplizieren,
Wiederholungserfassung, gemerkte Tabellen und Parteienkarten bleiben Grundlage.

1. **Automatische Entwurfssicherung:** Wiederaufnahme je Benutzer/Datensatz nach
   Absturz oder Sitzungsende; Revision der Quelle erhalten. Speichern eines Entwurfs
   führt keine Buchung, Freigabe oder externe Übertragung aus.
2. **Benannte Listenansichten:** Mehrere Filter-/Spalten-/Sortierkombinationen,
   beispielsweise ungeklärte Zahlungen oder Fristen der nächsten 30 Tage. Bestehende
   Berechtigungen und vollständige serverseitige Bestandsfilter gelten weiter.
3. **Zuletzt geöffnete Akten und Aktenfavoriten:** Benutzergebunden; der Zugriff auf
   inzwischen gesperrte Akten wird erneut geprüft.
4. **Schnelländerungen:** Zuständigkeit, Fälligkeit und Aufgabenstatus direkt in der
   Liste mit derselben Revision-/Rechteprüfung wie im vollständigen Formular.
5. **Arbeitszentrale:** Bestehende Prüfliste, Aufgaben, Fristen und unvollständige
   Fachabläufe priorisiert zusammenführen. Direkt bearbeiten oder begründet bis zu
   einem Termin zurückstellen, ohne Warnungen oder Vorgänge still zu verlieren.
6. **Gemeinsame Aktenchronik:** Vorhandene Zahlungen, Dokumente, Notizen, Schäden,
   Termine und Änderungen mit Quellenlinks zeitlich zusammenführen.
7. **Kennzahlen öffnen ihre Grundlage:** Filtergebundene Buchungs-/Belegansicht aus
   jeder relevanten Summe, statt erneut manuell suchen zu müssen.

Weitere kleine Abläufe: Gesprächsnotiz mit Wiedervorlage, fortlaufende Belegbearbeitung
mit Vorschau und Übernahme sinnvoller Angaben, Zurücknavigation mit Scrollposition
und Markierung des bearbeiteten Eintrags sowie nachvollziehbare Dublettenhinweise.
Rückgängig bleibt auf fachlich reversible Aktionen begrenzt; Buchungen verwenden
Storno, veröffentlichte Originale eine verknüpfte Korrekturfassung.
