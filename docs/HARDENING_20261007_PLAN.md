# Hardening und Bedienabläufe – 7. Oktober 2026

## Spezifikation und Ausgangspunkt

Fortsetzung des vom Benutzer freigegebenen A–L-Plans auf Claudes letztem Stand
3223a36a und der darauf aufgebauten Parteienakte eb458493. Der aktuelle Auftrag
verlangt weitere Funktionen, Schnittstellen, Fehlersuche und ausgedehnte Lasttests.
Die drei unabhängigen Bestandsprüfungen haben konkrete Fehler reproduziert.
Dieses Paket behebt diese Fehler vor weiteren externen Adaptern.

Erforderliches Verhalten:

- Datumsfilter berücksichtigen den gesamten Bestand vor der Seitenauswahl.
- Serienaufgaben schreiten tatsächlich fort, behalten ihre Verknüpfungen und
  erzeugen bei ungültigen Regeln verständliche Einzelfehler.
- Integrationen zeigen ihren tatsächlichen Funktionszustand. Speichern beschädigt
  keine maskierten Geheimnisse; fehlgeschlagene Speicherung ändert keinen Livezustand.
- Eine E-Mail gilt nur nach erfolgreicher SMTP-Annahme als versendet.
  Verbindungstests senden keine Nachricht. Versand benötigt einen gewählten Empfänger.
- Fehler werden sichtbar und wiederholbar; archivierte Parteien bleiben in
  historischen Vertragsakten erreichbar.
- Belastungsprüfungen laufen ausschließlich mit synthetischen Daten in eigenen
  Verzeichnissen und nennen Umfang, Hardware, Messmethode und verbleibende Grenzen.

## Umsetzung

### 1. Vollständige Datenzugriffe und begrenzte Zwischenspeicherung

Repository, SQLStore und InMemoryStore erhalten additive `range_filters` mit
inklusiven unteren/oberen Grenzen. Buchungen, Verträge, Rechnungen, Instandhaltung
und Aufgaben verwenden diese Filter vor Offset/Limit. Die Aufgabenumstellung
führt Paket 2 durch, alle anderen Paket 1. Bestehende Aufrufer bleiben kompatibel.
Gezielte Indizes erhalten eine eigene additive Migration, falls Messungen ihren
Nutzen bestätigen. Abgelaufene Berechnungsergebnisse werden freigegeben;
Cachealter beginnt nach erfolgreicher Berechnung. Abgebrochene wartende Jobs
dürfen nicht anschließend ausgeführt werden.

Prüfung: gleiche Ergebnisse in SQL und Speicher, Datensätze hinter 10.000,
Grenztage, stabile Folgeseiten, Fehler- und Abbruchfälle; anschließend erneuter
synthetischer Test mit einer Million Buchungen und zehn parallelen Lesern.

### 2. Aufgaben und historische Akten

Serienregeln validieren, Folgetermin aus dem letzten Vorkommen ableiten,
ungültige historische Regeln einzeln melden. Aufgabenänderungen nutzen PATCH,
bewahren Serienbezüge und prüfen Objekt-/Einheitszuordnung. Schnelle Aktionen
für Erledigen/Wiederöffnen und verständliche Rückmeldungen ergänzen. Aufgaben-
und Vertragsansichten bekommen sichtbare Ladefehler und Wiederholung; historische
Verträge laden auch archivierte Parteien. Keine neuen konkurrierenden Stammdaten.

Prüfung: zweite und dritte Wiederholung, ungültige Intervalle, Bearbeitung eines
Serienkindes, unzulässige Objektzuordnung, schnelle Aktionen, Ladefehler und
historische Parteinavigation.

### 3. Verlässliche Integrationsschnittstelle

Konfigurations- und Aktionsbeschreibung erweitern; Konfiguration validieren,
maskierte Geheimnisse erhalten, vor Veröffentlichung dauerhaft atomar speichern.
Providerfehler werden zu nachvollziehbaren fehlgeschlagenen Ergebnissen.
E-Mail erhält eine echte konfigurierte SMTP-Verbindung mit Timeout, TLS und
seiteneffektfreiem Verbindungstest; expliziter Versand wird getrennt angeboten.
Unimplementierte Portalanbindungen und fehlgeschlagene KI-Modellladung erhalten
einen ehrlichen Status. Die Oberfläche erhält Konfigurationsformulare,
Aktionsauswahl, gewählte Eingaben, Berechtigungsprüfung und Ergebnisanzeige.

Prüfung: Transport-/Speicherfehler, maskierter Roundtrip, ungültige Payloads,
kein Versand beim Verbindungstest, SMTP-Ablehnung, lesende Benutzer,
Konfigurations- und Aktionsabläufe im Browser. Keine realen externen Empfänger.

### 4. Gemeinsame Belastungs- und Regressionsprüfung

Windows-Prozessabbruch und Umgebungstrennung des vorhandenen XStress-Harness
prüfen und korrigieren, dann Geschäftsvorgänge mit synthetischen Daten ausführen.
Den Backend-Basistest (1.135 bestanden, 5 Fehler, 3 übersprungen) auflösen:
History-Sortierung und vier Windows-Unterprozessimporte getrennt untersuchen.
Frontendprüfung, Build, unabhängiges Review und Browserprüfung des Gesamtstands.
Nach erfolgreicher Prüfung die separate Vorschau aktualisieren. Benutzerdateien
und installierte EXE bleiben während synthetischer Tests unberührt.

## Zuständigkeiten und Grenzen

### Ergänzung aus dem echten PostgreSQL-Test

Die frische Alembic-Installation erzeugt `bookings.amount` weiterhin als
`double precision`, obwohl das aktuelle ORM dezimale Beträge deklariert.
100 gleichzeitig erzeugte Zahlungen zu 11,11 EUR ergeben deshalb in PostgreSQL
1111,0000000000002 statt einer exakten Dezimalsumme. Alle 100 Zahlungszuordnungen
waren dagegen vorhanden und ergaben bereits exakt 1111,00 EUR.

Paket 5 ergänzt eine eigene Migration nach dem neuen Buchungsindex. Die
historisch abweichenden Betragsfelder werden anhand des tatsächlichen Schemas
geprüft und auf dezimale Speicherung überführt. Vorhandene Werte dürfen dabei
nicht still gekürzt oder gerundet werden. Frische Installation und Upgrade
werden gegen einen echten isolierten PostgreSQL-Server geprüft; SQLite bleibt
kompatibel. Diese Änderung wird gesondert überprüft. Sie ersetzt noch keine
vollständige Umstellung sämtlicher Python-Finanzrechnungen auf Decimal.

Der erste PostgreSQL-Test bestand alle 200 gleichzeitigen API-Zugriffe mit zehn
verschiedenen Benutzern und die Schreibsperre der Leserrolle. Die gesamte
Abnahme bleibt wegen des gefundenen Betragsfehlers bis zur Korrektur offen.

Paket 1 besitzt generische Paginierung, Cache, Jobqueue und seine Migration;
Paket 2 besitzt Aufgabenrouter, Aufgabenvalidierung und Tasks/Contracts-Oberflächen;
Paket 3 besitzt Integrationsdienste und deren Oberfläche. Änderungen an
`storage.py` werden auf unterschiedliche Methoden begrenzt. Paket 1 liefert
Paket 2 den genauen Filtervertrag vor dessen Umstellung.

Der Integrator koordiniert Tests und Review. Reale TEHA-Schreibvorgänge und der
WISO-Zielimport werden durch synthetische Tests nicht als abgenommen dargestellt.
Eine Million Zeilen auf SQLite mit zehn Lesern ist kein Nachweis für PostgreSQL-
Mehrschreiberbetrieb oder eine Garantie für zwanzig wartungsfreie Jahre.
