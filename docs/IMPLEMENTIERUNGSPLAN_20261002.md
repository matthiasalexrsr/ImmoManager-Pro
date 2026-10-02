# Implementierungsplan für die professionelle Immobilienverwaltung

Stand: 2. Oktober 2026. Grundlage: aktueller Produktcode, historisches Funktionsinventar und die sieben Ergänzungen des Eigentümers. TEHA aus Heppenheim und ein vorhandener Kundenportalzugang sind bestätigt. Dieser Plan beschreibt die noch zu implementierenden Erweiterungen; er ersetzt keine Abnahme bereits laufender Arbeiten.

## 1. Ziel und feste Architekturentscheidungen

Die Anwendung soll einen vollständigen Arbeitszusammenhang bieten: Immobilie → Einheit → Mietverhältnis → Aufgaben/Termine → Verträge/Zähler → Schäden/Projekte → Dokumente/Kosten → Auswertung. Jede Information wird einmal geführt und in den passenden Ansichten verknüpft.

Für den privaten Mehrbenutzerserver bleibt PostgreSQL die vorgesehene Betriebsdatenbank; SQLite bleibt für lokale Nutzung, Entwicklung und Wiederherstellung unterstützt. FastAPI, SQLAlchemy/Alembic und React werden weiterverwendet. Neue Module werden innerhalb dieser Anwendung als klar getrennte Fachbereiche ergänzt. Ein zusätzlicher Microserviceverbund oder ein zweites Aufgaben-/Buchhaltungssystem ist für diese Anforderungen nicht erforderlich.

Vier Entscheidungen gelten durchgehend:

1. Objektindividuelle Konfiguration: Eine Immobilie besitzt eigene Abläufe, Müllpläne, Ablesetermine und Dienstleistungsverträge. Einheiten können ausdrücklich dokumentierte Abweichungen erhalten.
2. Erhaltene Geschichte: Vorlagen, Tarife, Prüfergebnisse und veröffentlichte Protokolle erhalten Versionen. Eine Änderung überschreibt keine bereits ausgeführte Arbeit und kein früheres Original.
3. Vollständige Daten: Listen werden serverseitig gefiltert/paginiert; Auswertungen verwenden vollständige Aggregation. Ein Arbeitsbudget begrenzt einen Durchlauf und besitzt eine Fortsetzung. Es gibt keinen pauschalen Gesamtbestandsdeckel.
4. Nachvollziehbare Nebenwirkungen: Aufgaben, Termine, Buchungsverknüpfungen und externe Übertragungen benötigen eine stabile Vorgangsidentität. Wiederholung nach Verbindungsabbruch darf nichts doppelt erzeugen.

Das Ziel von 20 Jahren Nutzung wird durch portierbare Daten, überprüfbare Wiederherstellung, dokumentierte Migrationen und einen einfachen Aktualisierungspfad unterstützt. Dafür werden Betrieb und Abhängigkeiten regelmäßig überprüfbar gehalten; ein unverändert eingefrorenes Installationspaket wäre kein belastbares Wartungskonzept.

## 2. Tatsächlicher Bestand und notwendige Ergänzungen

| Bereich | Im Code vorhanden | Noch aufzubauen |
|---|---|---|
| Aufgaben | Objekt-/Einheitsbezug, Zuständigkeit, Fälligkeit, Priorität, Status, einfache Wiederholung | Fachlicher Ursprung, Checklisteninstanzen, Abhängigkeiten, wiederverwendbare versionierte Ablaufvorlagen und belegter Abschluss |
| Kalender | Objekt-/Einheitstermine, operative Erzeugung, Wiederholung und geschützter ICS-Export | Geprüfter Import, Ausnahmen und ursprüngliche externe Identität; Müll-/Ableseansichten und eindeutige Verbindung zum Fachvorgang |
| Mieterwechsel | Mietverträge, geprüfte Vertragsvorgänge, Übergabeprotokolle, Zähler | Eine gemeinsame Wechselakte mit individueller Checkliste und Ein-/Auszugsterminen |
| Zähler | Lieferant, Seriennummer, Einheitsbezug, Ablesewerte, Prüftermine und einfache Vertragsangaben | Objektzähler, Ablesepläne, echte Versorgerverträge, Tarif-/Messstellenzuordnung und TEHA-Abgleich |
| Finanzen | Buchungen, Zahlungs-/Stornobelege, Forderungen, Rechnungen, Kategorien und einzelne Berichte | Vollständige dimensional gefilterte Ergebnisse, nachvollziehbare Kostenverteilung, Zeitreihen und getrennte Grundlagen für Zahlungsfluss und periodisches Ergebnis |
| Schäden | Instandhaltungsfall, Objekt/Einheit, Zuständigkeit, Handwerkertext, Termin und Kostenschätzung | Projektakte, strukturierte Beteiligte, Aufgabenplan, Meilensteine, Angebote/Aufträge, Protokolle und verknüpfte Istkosten |
| Kontakte/Dokumente | Kontakte mit Firmenangaben sowie unveränderliche Originalversionen | Handwerkerprofile/Gewerke, Vorgangsrollen und allgemeine Dokumentverknüpfung für neue Fachakten |
| Schnittstellen | Bestehender Integrationsbereich und geprüfte Import-/Versandabläufe | TEHA-spezifischer Adapter mit belegtem Format, Zuordnungen, Vorschau, Protokoll und Wiederholungsbehandlung |

Relevante Ausgangsstellen: `backend/models.py`, `backend/db/orm_models.py`, `backend/services/operational_schedule.py`, `backend/services/recurrence.py`, `backend/services/report_service.py`, `backend/routers/reports.py`, `backend/services/integration_service.py` und die Seiten `Tasks`, `Calendar`, `Maintenance`, `Meters`, `Contacts`. Der aktuelle Finanzbericht summiert Buchungen teilweise als Fließkommazahlen und arbeitet mit vollständigen Pythonlisten. Das wird für die neuen Ergebnisse durch centgenaue, gefilterte Aggregation ersetzt. Der einfache Wiederholungsparser unterstützt derzeit keine Wochentagsregeln wie `BYDAY`; Müllpläne benötigen eine bewusst erweiterte Wiederholungsgrundlage.

## 3. Gemeinsame Grundlage vor den Fachmodulen

### 3.1 Objekt- und Einheitskonfiguration

Ein versioniertes Betriebskonfigurationsmodell bindet Einstellungen an `portfolio_id`, `property_id` und optional `unit_id`. Eine Einheit übernimmt die Objektkonfiguration, solange keine ausdrücklich angelegte Abweichung besteht. Die Oberfläche zeigt die Herkunft jeder Einstellung. Das Kopieren einer Objektkonfiguration erzeugt eine eigene Version für das Zielobjekt.

Bereits gestartete Vorgänge speichern die verwendete Konfigurations-/Vorlagenversion als Snapshot. Ein später geänderter Standard verändert nur zukünftige Vorgänge. Eine bewusste Übernahme auf offene Vorgänge zeigt vorher die Unterschiede und schützt erledigte Schritte.

### 3.2 Einheitliche Verknüpfungen

Aufgaben, Termine, Ansprechpartner, Rechnungen und Dokumente erhalten überprüfbare Verknüpfungen zu Wechselakten, Dienstleistungsverträgen und Projekten. Jede Verknüpfung wird auf den tatsächlichen Objekt-/Einheitsbezug und die aktuellen Benutzerrechte geprüft. Es werden keine ungeprüften fremden IDs oder unkontrollierte URL-Verweise gespeichert.

Der erste Entwurf verwendet ergänzende Verknüpfungstabellen. Bestehende Datensätze bleiben kompatibel; die bisherigen Tabellen müssen nicht sofort vollständig umgebaut werden. Wo feste Fremdschlüssel möglich sind, werden sie einem beliebigen Freitexttyp vorgezogen.

### 3.3 Schreibvorgänge und Hintergrundarbeit

Gemeinsame Regeln: frische Rechte, `If-Match`/Revision, atomare Transaktion, Wiederholungsschlüssel und bestätigtes Ergebnis. Eine Gruppenaktion besitzt ein unveränderliches Prüfergebnis mit der konkret betroffenen Auswahl. Nach einem Konflikt bleiben Benutzereingaben erhalten.

Der vorhandene operative Worker wird um klar getrennte Aufgabenarten erweitert. Er verarbeitet einen begrenzten Abschnitt und speichert seine Position. Fehler erscheinen mit dem betroffenen Vorgang und erlauben Fortsetzung. Ein fehlgeschlagener Versand wird nicht als zugestellt markiert. Für Nebenwirkungen über mehrere Prozesse werden dauerhafte Jobs, Sperren und Wiederholungsschlüssel verwendet; eine flüchtige Pythonliste reicht dafür nicht aus.

### 3.4 Rechte und Datenschutz

Die bestehenden Rollen werden zunächst genutzt: Eigentümer/Verwalter für Konfiguration, Buchhaltung für Finanzberichte und Kostenbezüge, Technik für operative Vorgänge, reine Leser für zugelassene Ansichten. Feldbezogene Sichtbarkeit trennt etwa Handwerkertermine von Vertragskonditionen und personenbezogenen Mieterunterlagen.

Jedes neue Modell gehört von Anfang an zu Sicherung, Wiederherstellung, Portfoliofreigaben, Export und Lösch-/Archivierungsregeln. Originalprotokolle und Finanzbelege werden erhalten; private offene Arbeit wird im Datenschutzexport angemessen getrennt. Benutzerentzug wird auch bei einem bereits geöffneten Download oder Hintergrundauftrag berücksichtigt.

## 4. Mieterwechsel: individuelle Abläufe

### Bedienung

Eine Immobilie erhält einen Bereich „Mieterwechselvorlagen“. Dort werden Einzug und Auszug getrennt konfiguriert. Beispielschritte: Termin abstimmen, Schlüssel zählen, Übergabeprotokoll erstellen, Zählerstände aufnehmen, Reinigung prüfen, Dienstleister informieren, Unterlagen/Kaution nachhalten. Jeder Schritt kann Pflicht, optional oder für diesen Wechsel unzutreffend sein.

In der Einheit startet der Benutzer eine Wechselakte, wählt alte/neue Mietverhältnisse, Ein-/Auszug und tatsächlichen Übergabetermin und prüft die vorgeschlagenen Aufgaben. Termine werden relativ zu einem ausdrücklich gewählten Anker definiert, etwa sieben Tage vor Übergabe. Der Vertragsbeginn wird nicht stillschweigend mit dem Übergabetag gleichgesetzt.

Die Akte zeigt Verantwortliche, offene/blockierte/erledigte Schritte, Protokolle, Zählerstände und fehlende Unterlagen. Eine verschobene Übergabe erzeugt eine Vorschau der betroffenen offenen Aufgaben. Erledigte Aufgaben behalten ihren tatsächlichen Abschlusszeitpunkt.

### Geplante Modelle

- `workflow_templates` und `workflow_template_versions`: Objektzuordnung, Auslöser Ein-/Auszug, veröffentlichte Fassung.
- `workflow_template_steps`: stabile Schrittidentität, Reihenfolge, Terminanker/-versatz, Pflichtstatus, Rolle, optionale Abhängigkeiten und benötigter Belegtyp.
- `tenancy_changes`: Objekt/Einheit, vorheriger/neuer Vertrag, Ein-/Auszug, Übergabe, Vorlagenversion, Status und Revision.
- `workflow_instances` und `workflow_step_instances`: eingefrorene Aufgabenbeschreibung, ursprünglicher Termin und Verknüpfung zur vorhandenen Aufgabe; Abschluss, Ausnahmegrund und Originalbeleg.

Es entstehen keine Kopien bestehender Mietforderungen. Ein neuer Mietvertrag kann eine Wechselakte vorschlagen; das Erzeugen der Aufgaben wird zunächst ausdrücklich bestätigt.

### Abnahme

Zwei Immobilien mit unterschiedlichen Vorlagen erzeugen unterschiedliche Aufgaben. Eine Wiederholung desselben Starts erzeugt keine zweite Akte. Vorlagenänderung und Terminverschiebung erhalten erledigte Schritte. Gleichzeitige Änderungen führen zu einem korrigierbaren Konflikt. Übergabeprotokoll und Zählerwerte bleiben nach vollständiger Wiederherstellung verknüpft.

## 5. Müllpläne und Ableseerinnerungen

### Müllpläne

Pro Immobilie: frei benennbare Abfallart, Sammelstelle, einmalige Termine oder Serie, Erinnerungsvorlauf und Zuständigkeit. Mehrere Tonnen und getrennte Termine sind möglich. Einheiten übernehmen den Objektplan; abweichende Sammelstellen oder Zuständigkeiten können ergänzt werden.

Eingabewege: manuelle Termine, geprüfter ICS-Import und später ein konkreter kommunaler Adapter. Importvorschau zeigt neue/geänderte/entfallene Termine und das Zielobjekt. Externe `UID`, Version und Quelle bilden die Identität; Änderungen dürfen keine Doppeltermine erzeugen. Feiertagsverschiebungen werden aus tatsächlichen Importdaten oder ausdrücklichen Ausnahmen übernommen.

### Ablesepläne

Ein Plan bindet Objekt/Einheit, einzelne oder mehrere Zähler, Intervall oder konkreten Termin, Vorlauf und Verantwortlichen. Objektzähler wie Hauptwasser oder Allgemeinstrom werden als Objektzähler modelliert und benötigen keine erfundene Wohnung.

Die Erinnerung verlinkt zur Ablesemaske. Dort werden Datum, Messwert, Einheit, Bild und gegebenenfalls Korrekturgrund erfasst. Eine erledigte Erinnerung gilt erst mit dem vorgesehenen Ablesebeleg als abgeschlossen. Zählerwechsel erhält Alt-/Neuzähler und die zugehörigen Zeiträume.

### Technik und Abnahme

Ergänzende Modelle: `property_operating_plans`, `operating_plan_versions`, `operating_plan_occurrences`, `calendar_import_sources` und `calendar_import_batches`. Die vorhandenen Aufgaben/Termine bleiben die sichtbaren Ausgaben. Datumsserien verwenden feste Zeitzonen; Ganztagstermine bleiben kalendarische Daten. RFC-Regeln, Ausnahmen und bestehende Legacy-Serien bekommen getrennte, versionierte Semantik.

Abnahme: Wochentagsserien, Zweiwochenrhythmus, Schaltjahr, Jahreswechsel, Sommer-/Winterzeit, einzelne Ausnahme, Importwiederholung, Quellkorrektur, bereits erledigte/verschobene/gelöschte Instanz und mehrere parallel laufende Worker. Lange Serien werden abschnittsweise erzeugt und bleiben vollständig fortsetzbar.

## 6. Strom- und weitere Objektverträge

### Vertragsakte

Ein gemeinsamer Fachbereich „Objektverträge“ führt Strom, Gas, Wasser, Wärme, Internet, Reinigung, Wartung und frei definierbare Dienstleistungen. Die Akte gehört zu einer Immobilie und optional einer Einheit. Ein Vertrag für mehrere Objekte benötigt ausdrücklich zugeordnete Vertragsorte; die Konditionen werden dadurch nicht mehrfach kopiert.

Gemeinsame Felder: Anbieter/Ansprechpartner, Vertrags-/Kundennummer, Beginn/Ende, Status, Leistungsumfang, Konditionen, Zahlungsintervall, bestätigte Termine und Originaldokumente. Erinnerungsregeln, Verlängerung und Beendigung beziehen sich auf eine konkrete Vertragsfassung. Tatsächliche rechtliche Fristen werden aus dem Vertrag bewusst bestätigt; freie Notizen lösen keine automatische Kündigung aus.

### Strom und Energie

Zusätzliche Zuordnung: Zähler, Messstelle, Marktlokation soweit vorhanden, Tariffassung, Gültigkeitszeitraum, Arbeitspreis, Grundpreis, Abschlag, Preisbindung und Abrechnungsintervall. Tarife können über die Zeit wechseln. Preise pro Verbrauchseinheit benötigen mehr Präzision als ein fertiger Eurobetrag; Berechnung verwendet Decimal und rundet erst am fachlich festgelegten Abschluss.

Die Kostenübersicht zeigt Abschläge, tatsächliche Rechnungen, Zahlungen, Verbrauch und eine getrennt gekennzeichnete Prognose. Ein Vertragsabschlag erzeugt zunächst einen erwarteten Termin. Eine tatsächliche Buchung benötigt ihre eigene Freigabe/Quelle. Allgemeinstrom und Einheitsstrom bleiben unterscheidbar.

### Modelle und Abnahme

Modelle: `service_contracts`, `service_contract_locations`, `service_contract_versions`, `service_contract_deadlines`, `energy_tariff_versions`, `service_contract_meter_links` und geprüfte Finanz-/Dokumentverknüpfungen. Versicherungen bleiben als vorhandener Fachbereich erhalten und können dieselben Fristen-/Dokumentdienste nutzen.

Abnahme: Tarifwechsel im Abrechnungsjahr, anteilige Grundpreise mit sichtbarer Berechnungsgrundlage, doppelte Rechnung, Zählerwechsel, mehrere Standorte, Terminänderung, mehrere Währungen getrennt und nachträgliche Vertragskorrektur. Kündigung/Versand wird nur durch einen gesonderten ausdrücklich bestätigten Vorgang dokumentiert.

## 7. Gewinn-/Verlustauswertungen und Statistiken

### Fachliche Grundlage zuerst

Es werden drei erkennbare Ansichten aufgebaut:

1. Einnahmen/Ausgaben nach tatsächlichen Buchungen/Zahlungsdatum.
2. Wirtschaftliches Ergebnis nach ausdrücklich erfassten Leistungszeiträumen und Ergebniskategorien.
3. Prognose nach Sollstellungen, offenen Posten und bestätigten laufenden Vertragskosten.

Die erste Ansicht ist die verlässlichste initiale Veröffentlichung. Die zweite wird erst angeboten, wenn Periodenzuordnung, Investition/Finanzierung und gegebenenfalls Abschreibungsdaten vollständig modelliert sind. Vorhandene historische Buchungen erhalten sichtbare Hinweise auf fehlende Zuordnung und werden nicht willkürlich umklassifiziert.

Eine Zahlung und ihre zugeordnete Bankbuchung zählen im selben Ergebnis nur einmal. Storno-/Gutschriftbelege werden korrekt berücksichtigt. Kautionen, interne Umbuchungen, Investitionen, Finanzierung und laufende Objektkosten benötigen eigene fachliche Kategorien. Die bereits vorhandene Steueraufbereitung/WISO-Ausgabe bleibt eine getrennt prüfbare Ableitung.

### Filter und Darstellung

Zeitraum beliebig wählbar; Gesamtbestand, Portfolio, Immobilie, Einheit und mehrere ausgewählte Objekte. Hauptzahlen: Einnahmen, Ausgaben, Ergebnis, offene Posten und Datenvollständigkeit. Zeitreihen nach Monat/Jahr, Vorperiodenvergleich, Kostenarten und Einheitsvergleich. Kennzahlen wie €/m² oder Rendite werden nur mit vollständiger Bezugsgrundlage berechnet und zeigen ihre Formel.

Jede Zahl führt zu den enthaltenen Quellbuchungen. Objektkosten ohne Einheit bleiben als solche sichtbar. Eine optionale Einheitsverteilung benötigt einen versionierten Schlüssel, Zeitraum und Nachweis; ihre Summe muss exakt zum Ausgangsbetrag passen. Die Auswertung unterscheidet echte Buchungszuordnung und rein analytische Verteilung.

### Daten und Leistung

Bestehende Buchungen/Rechnungen bleiben die Quellen. Ergänzend: `financial_category_rules`, `financial_period_assignments`, `financial_allocation_versions` und `financial_allocation_lines`; gegebenenfalls geprüfte Abschreibungs-/Finanzierungsdaten für die zweite Ansicht. Geldwerte werden centgenau mit Decimal verarbeitet. Die vorhandenen begrenzten Numeric-Spalten und Float-Schnittstellen werden vor Erweiterung auf größere Beträge gesondert geprüft und mit einer kontrollierten Migration erweitert.

SQL aggregiert nach Datum, Objekt, Einheit und Kategorie mit aktuellen Portfoliofiltern. Detailbelege kommen als Cursorseiten. Große CSV-Ausgaben werden vollständig kompiliert/gestreamt. Voraggregationen sind optional und jederzeit aus Quellen neu aufbaubar; ein Ergebnis darf nicht allein von einem vergessenen Cache abhängen.

Abnahme: Cent- und Rundungssummen, Teilzahlung/Storno/Gutschrift, doppelte Quelle, fehlende Einheitszuordnung, Kostenverteilung mit Restcent, Zeitraumgrenzen, mehrere Währungen, selektiver Portfoliozugriff und ein Ergebnis mit sehr großem Buchungsbestand. Gesamt-/Objekt-/Einheitssummen müssen unter gleicher Definition abstimmbar sein.

## 8. Schäden und Projekte

### Gemeinsame Vorgangsakte

Ein Schaden beginnt mit Meldung, Ort, Beschreibung, Priorität, Fotos und Ansprechpartner. Er kann als kleiner Instandhaltungsfall bearbeitet oder ausdrücklich zu einem Projekt erweitert werden. Beide behalten ihre ursprüngliche Identität; der ursprüngliche Schaden bleibt in der Projektakte sichtbar.

Eine Projektakte bündelt Überblick, Aufgaben, Zeitplan, Beteiligte, Kosten und Dokumente/Protokolle. Hauptablauf: gemeldet → geprüft → geplant → beauftragt → in Arbeit → Abnahme → abgeschlossen/archiviert. Blockierungen und Wartezustände besitzen einen Grund und nächsten Termin.

### Planung und Handwerker

Meilensteine, geplante/tatsächliche Termine, Zuständigkeiten und Aufgabenabhängigkeiten. Abhängigkeiten werden auf Zyklen geprüft; ein Vorgänger kann erst nach seinem bestätigten Abschluss automatisch weitere Schritte freigeben. Ein Balkenplan ergänzt eine auf Mobilgeräten nutzbare Termin-/Aufgabenliste.

Die bestehende Kontaktverwaltung erhält Handwerkerprofile mit Gewerk, bedienten Regionen/Objekten, Kontaktdaten und optionalen Qualifikations-/Versicherungsnachweisen. Projektdaten verknüpfen Angebote, Auswahl, Auftrag, Termin und Rechnung mit dem Kontakt. Handwerker bleiben wiederverwendbare Kontakte; vertrauliche Kontaktdaten werden nicht frei veröffentlicht.

### Protokolle und Kosten

Besichtigung, Gespräch/Entscheidung, Arbeitsfortschritt und Abnahme besitzen strukturierte Felder, Datum, Beteiligte, Mängel, Fotos und nächste Schritte. Entwürfe bleiben bearbeitbar; eine Veröffentlichung erzeugt ein unveränderliches Original. Korrekturen veröffentlichen eine neue Fassung.

Kostenansicht: Budget, beauftragte Kosten, erwartete Kosten, Rechnungen und tatsächlich bezahlt. Dieselbe Rechnung wird über ihre Identität eingebunden und nicht als neuer Aufwand kopiert. Nachträge besitzen eine bewusste Freigabe und erhalten den ursprünglichen Auftrag.

Modelle: `projects`, `project_milestones`, `project_task_links`, `project_dependencies`, `project_participants`, `contractor_profiles`, `project_orders`, `project_cost_links` und `project_protocol_versions`. Jede Graphänderung prüft die gemeinsame Projektrevision, damit parallele Abhängigkeitsänderungen keinen Zyklus erzeugen können.

Abnahme: Schaden→Projekt mit erhaltenen Bildern, zwei Gewerke, Terminverschiebung, Abhängigkeitszyklus, Ausfall eines Handwerkers, Nachtrag, Teilrechnung, Original-/Korrekturprotokoll, Rechtewechsel und vollständige Wiederherstellung.

## 9. TEHA: geprüfte Anbindung

Der vorhandene Kundenportalzugang ist bestätigt. Zuerst wird lesend festgestellt, welche Portalversion, Objekt-/Nutzernummern, Export-/Importmöglichkeiten und Funktionen für dieses Kundenkonto tatsächlich verfügbar sind. Anmeldedaten gehören in geschützte Konfiguration und nicht in Quellcode, Dokumentation oder Browserprotokolle.

Der Eigentümer hat am 2. Oktober 2026 die konkrete Portaladresse `https://kunden.socs.ws` und die Zugangsmeldung bereitgestellt. Diese nennt Kosten-/Nutzerdatenübermittlung, Dokumentdownloads einschließlich Gesamtabrechnungen und Rechnungen sowie offene Techniktermine und Restarbeitsaufträge. Das sind belegte Angaben aus der bereitgestellten Nachricht; die tatsächlich angebotenen Funktionen des angemeldeten Kontos und ihre technischen Formate sind noch live zu prüfen. Zugangsdaten werden in diesem Plan nicht wiedergegeben. Der erste Desktopprüfversuch wurde von der Computer-Use-Steuerung vor der Anmeldung angehalten, weil sie die aktuelle Browseradresse nicht zuverlässig erkennen konnte; daraus folgt keine Aussage über Erreichbarkeit oder Gültigkeit des TEHA-Zugangs.

TEHA beschreibt elektronischen Abrechnungsaustausch auf seiner offiziellen Seite, nennt dort aber keinen öffentlichen API-Endpunkt oder verbindlichen Datensatz. Eine öffentliche API-Dokumentation ist keine Voraussetzung: Der Eigentümer hat die Untersuchung und das Reverse Engineering seines autorisierten Portalzugangs ausdrücklich erlaubt. Der Anschluss wird aus tatsächlich beobachteten Portalabläufen und Datensätzen abgeleitet. [TEHA Datenaustauschservice](https://teha-wd.de/leistungen/abrechnung-ablesung/datenaustausch/).

Der bved veröffentlicht Standards für Dateiaustausch und Webservices. Diese werden als Kandidaten geprüft; ihre Existenz belegt noch keine Unterstützung im konkreten TEHA-Konto. Die für TEHA bestätigte Version wird eingefroren und mit Originalbeispielen/Schema getestet. [bved Spezifikationen](https://bved.info/datenaustauschneu/spezifikationen/).

### Untersuchung des vorhandenen Portals

1. Die tatsächlich genutzte Portaladresse und die angemeldete, autorisierte Sitzung erfassen; vorhandene Objekte, Zeiträume und angebotene Export-/Importfunktionen lesend prüfen.
2. Netzwerkanfragen während gewöhnlicher Portalbedienung untersuchen: Session-/CSRF-Verfahren, Objekt-/Nutzer-/Geräteauswahl, Zeitraumauswahl, Downloads, Pagination und tatsächliche Fehlerrückmeldungen.
3. Anonymisierte Beispieldatensätze und Antwortstrukturen ableiten. Cookies, Passwörter und Zugriffstoken werden aus technischen Nachweisen entfernt; Originaldaten bleiben im geschützten Arbeitsbereich.
4. Falls das Portal strukturierte HTTP-/JSON-Endpunkte verwendet, diese hinter einem eigenen TEHA-Adapter kapseln und ihre Bindung an Benutzer, Objekt und Zeitraum prüfen. Ein interner Portalendpunkt wird als beobachtete Schnittstelle dokumentiert.
5. Falls strukturierte Endpunkte fehlen, tatsächliche Datei-/Dokumentausgaben nutzen. Eine Browserautomatisierung ist als gekapselter zusätzlicher Transportweg möglich; sie erhält klare Anmeldung, Sitzungsprüfung, Rückmeldung und Wiederaufnahme.
6. Antwort-/Seitenschema, Identitätsbindung und Dateiformat vor jeder Veröffentlichung prüfen. Nach einer Portaländerung werden unklare Daten im Importbereich zurückgehalten und der Adapter meldet einen korrigierbaren Anschlussfehler.

Für diese Untersuchung wird keine erneute allgemeine Reverse-Engineering-Freigabe verlangt. Ein noch nicht dokumentierter Endpoint oder ein proprietäres Exportformat führt zur Analyse des tatsächlichen Verhaltens und blockiert die lokale Entwicklung nicht. Zugriff und Datenübertragung bleiben an den autorisierten Kundenaccount und den konkret gewählten fachlichen Vorgang gebunden.

### Reihenfolge des Adapters

1. Zuordnung: TEHA-Kundennummer, Objekt-/Nutzer-/Gerätenummern mit internen stabilen IDs verbinden; keine Namensgleichheit als automatische Identität.
2. Empfang zuerst: tatsächlich verfügbare Abrechnungen/Verbrauchs-/Gerätedaten in einen geschützten Importbereich lesen. Quelle, Originalhash und Datensatzversion bewahren.
3. Vorschau: neue, geänderte, widersprüchliche und unzugeordnete Daten anzeigen. Aktuelle bestätigte interne Daten werden nicht stillschweigend überschrieben.
4. Bestätigung: geprüfte Veröffentlichung mit Wiederholungsschlüssel; Originalabrechnungen unverändert archivieren und Kosten-/Zählerbezug herstellen.
5. Nutzerwechsel/Kostenübermittlung: aus einer geprüften Wechsel-/Abrechnungsakte exportieren. Zunächst ausdrückliche Übertragung; später optional eine bewusst aktivierte Automatisierung.
6. Rückmeldung: tatsächliche Annahme/Ablehnung und externe Vorgangsreferenz speichern. Ein Timeout bleibt unklar und wird mit demselben Vorgang abgeglichen.

Dokumentdownloads werden mit den unveränderten Originalabrechnungen verknüpft. Techniktermine erhalten externe Identität, Objekt-/Zählerbezug und eine sichtbare Quelle; Änderungen aktualisieren offene Termine, ohne abgeschlossene Vorgänge umzuschreiben. Restarbeitsaufträge werden aus der Schaden-/Projektakte mit geprüften Angaben vorbereitet und erst als tatsächlicher Auftrag ausgewiesen, wenn das Portal die Übermittlung bestätigt hat. Dafür wird dieselbe Austauschhistorie genutzt wie für Kosten- und Nutzerdaten.

Modelle: `provider_connections`, `provider_object_mappings`, `provider_meter_mappings`, `provider_exchange_batches`, `provider_exchange_items` und ein dauerhaftes Übertragungsjournal. Konfiguration und Geheimnisse werden getrennt von fachlichen Daten gehalten. Der Adapter sitzt hinter einer kleinen dokumentierten Schnittstelle, sodass Datei-, Webservice- und später andere Messdienstadapter dieselbe Vorschau/Zuordnung verwenden können.

Abnahme umfasst eine tatsächliche Operation im autorisierten TEHA-Portal oder einem zugänglichen Testsystem und den Abgleich der Ergebnisse. Lokale synthetische Tests allein erklären die externe Anbindung nicht als fertig. Offizielle API, beobachtete Portalschnittstelle, Dateiaustausch oder Browsertransport erhalten jeweils einen sichtbaren Verbindungsstatus; die fehlende öffentliche API ist kein allgemeiner Hinderungsgrund.

## 10. Oberfläche und Informationsarchitektur

Die Immobilienakte bekommt logisch verbundene Bereiche: Überblick, Einheiten/Mietverhältnisse, Aufgaben/Abläufe, Termine/Müll/Ablesung, Objektverträge, Schäden/Projekte, Finanzen und Dokumente. Die Einheitsakte zeigt denselben Zusammenhang für die Einheit und kennt die Herkunft übernommener Objekteinstellungen.

Die persönliche Arbeitsübersicht bündelt „heute“, „als Nächstes“, „überfällig“ und „wartet auf Rückmeldung“. Vorgänge öffnen sich im fachlichen Kontext. Filter werden nachvollziehbar beibehalten. Zahlen führen zu Belegen; Aufgaben führen zur ausführbaren Maske. Leere, fehlerhafte und noch nicht angeschlossene Zustände erhalten klare nächste Aktionen.

Gestaltung: ruhige Typografie, konsistente Abstände, zurückhaltende Farben, erkennbare Prioritäten und klare Hauptaktion je Ansicht. Lange Formulare werden in sinnvolle Abschnitte geteilt. Mobilansichten verwenden Karten/Listen für komplexe Tabellen; Tastatur, Fokus, Kontrast und 320/360-Pixel-Breiten gehören zur Prüfung. Interne technische Informationen stehen im Diagnose-/Administrationsbereich und nicht im normalen Arbeitsablauf.

## 11. Umsetzung in überprüfbaren Paketen

| Paket | Inhalt | Voraussetzungen | Abschlussbeleg |
|---|---|---|---|
| P0 | Laufende Korrespondenz-/Fristenarbeit und vorhandene CI-Fehler abschließen; Datenbestand sichern | Aktueller Stand | Exakter abgenommener Commit/Tree, Browser und echte PostgreSQL-Gates; dokumentierte verbleibende Grenzen |
| P1 | Objektkonfiguration, Vorgangs-/Dokumentverknüpfung, Cursor-/Jobfortsetzung und Rechte | P0 | Migration/Legacyupgrade, SQLite/PostgreSQL, parallele Änderungen und Recovery |
| P2 | Individuelle Mieterwechselvorlagen und vollständige Wechselakte | P1 | Zwei unterschiedliche Immobilien, vollständiger Ein-/Auszug und erhaltene Originalbelege |
| P3 | Müll-/Ablesepläne und geprüfter Kalenderimport | P1, Zählerzuordnung | Ausnahmen/Zeitzonen/Importwiederholung und reale mobile Bedienung |
| P4 | Strom-/Dienstleistungsverträge, Tariffassungen und Fristen | P1, P3 | Tarifwechsel, Zählerbezug und abgestimmte Rechnungs-/Zahlungsbezüge |
| P5 | Einnahmen/Ausgaben, Objekt-/Einheitsberichte, Statistik und vollständige Exporte | P1, Finanzquellenprüfung | Vollständige abstimmbare Ergebnisse, genaue Rundung, große Bestände |
| P6 | Schaden-/Projektakte, Handwerker, Zeitplan, Protokolle und Kosten | P1, P2-Aufgabenmechanik, P5-Kostenbasis | Tatsächlicher Schaden→Projekt→Abnahme-Ablauf, parallele Graphänderungen und Recovery |
| P7 | TEHA-Zuordnung, Empfang, geprüfte Veröffentlichung und danach Übertragung | Anbieterprüfung kann während P1–P6 laufen; Fachanschluss braucht P2/P3/P5 | Tatsächlicher TEHA-Austausch und wiederholsicheres Journal |
| P8 | Periodischer Ergebnisbericht, optionale weitergehende Automatisierung und Betriebshärtung | Erprobte Quellen/Arbeitsabläufe | Explizite Ergebnisdefinition, Last-/Wiederanlaufprüfung und vollständige Dokumentation |

Die Reihenfolge gibt zuerst praktisch nutzbare Abläufe frei. TEHA-Recherche läuft parallel, damit noch nicht untersuchte Portalabläufe und Dateiformate die lokale Entwicklung nicht blockieren. Jedes Paket liefert Backend, Oberfläche, Migration, Rechte, Sicherung und Belege zusammen; ein sichtbarer Menüpunkt ohne vollständigen Arbeitsablauf ist kein Abschluss.

## 12. Last, Migration und langfristiger Betrieb

Vor Ausbau werden Datenumfang, größte Dateien und reale Berichtslaufzeiten gemessen. Neue Listen erhalten Indexe nach Portfolio/Objekt, Status, Datum und stabiler ID. Finanzberichte aggregieren in SQL; Detailansichten bleiben begrenzt. Abfragen vermeiden wiederholtes Laden derselben Eltern pro Datensatz. PostgreSQL-Partitionierung wird erst bei nachgewiesenem Bedarf eingeführt, da sie das Datenmodell und den Betrieb zusätzlich beeinflusst. [PostgreSQL Partitionierung](https://www.postgresql.org/docs/current/ddl-partitioning.html).

Lastprüfungen verwenden steigende synthetische Bestände, darunter Millionen von Buchungen/Belegen und große Originaldateien, auf dokumentierter Hardware. Gemessen werden Speicher, Antwortzeiten, Import-/Exportdauer, Sperrwartezeit und Wiederaufnahme. Zielbudgets werden aus diesen Messungen festgelegt; es werden keine ungemessenen festen Sekunden- oder 20-Jahres-Leistungsgarantien behauptet.

Migrationen ergänzen neue Tabellen/Spalten kontrolliert. Finanztypänderungen prüfen jeden vorhandenen Wert und erzeugen einen Prüfbericht vor Umstellung. Für historische lokale Datenbanken wird der tatsächliche Schemastand geprüft; ein fehlender Alembicmarker wird nicht blind als neuestes Schema gestempelt. Jede Umstellung benötigt eine geschützte Originalkopie und einen verifizierten Wiederherstellungsweg.

Betrieb: reproduzierbare Installation, unabhängige Konfiguration/Geheimnisse, dokumentierte Versionsstände, automatische geschützte Sicherungen mit Rotation, regelmäßige echte Restoreprobe, Gesundheits-/Jobstatus und Datenexport in offenen Formaten. Sicherheits- und Kompatibilitätsaktualisierungen bleiben klein, getestet und nachvollziehbar. Der private Server erhält keine öffentlich erreichbare Datenbank; Fernzugriff nutzt den vorhandenen privaten HTTPS-/VPN-Betriebsansatz.

## 13. Auswahl bestehender Open-Source-Module

Die vorhandenen Datenbank-, PDF-, HTTP- und UI-Bibliotheken werden zuerst genutzt. Für erweiterte Serien und Kalenderimport werden `python-dateutil` und `icalendar` anhand der offiziellen Dokumentation geprüft. Sie sind Kandidaten, derzeit keine neu installierten Produktabhängigkeiten. Vor Übernahme werden Release, Lizenz, Wartungsstand, benötigte Funktionen, Paketgröße und tatsächliche Eingabefälle geprüft. [dateutil rrule](https://dateutil.readthedocs.io/en/stable/rrule.html), [icalendar](https://icalendar.readthedocs.io/en/latest/).

Bestehende Monatsserien haben eigene geprüfte Legacyregeln. Eine neue Bibliothek wird deshalb über einen Adapter mit versionierter Semantik eingebunden und ersetzt diese Regeln nicht blind. Für TEHA werden belegte Standards bevorzugt; für Finanzaggregation reicht zunächst SQLAlchemy/PostgreSQL. Ein schweres Analyseframework oder zusätzlicher Scheduler wird nur bei einem konkreten, gemessenen Vorteil ergänzt.

## 14. Konkreter nächster Arbeitsschritt nach diesem Plan

1. Den laufenden Stand mit seinen tatsächlichen Tests/CI-Ergebnissen sauber dokumentieren und sichern.
2. Für P1 ein kurzes Architekturentscheidungsdokument und den exakten Migrationsentwurf aus diesem Plan ableiten.
3. Einen vollständigen Pilotablauf bauen: zwei Immobilien mit unterschiedlichen Mieterwechselvorlagen, tatsächliche Aufgabeninstanz und Protokollverknüpfung.
4. Parallel den bestätigten TEHA-Portalzugang lesend auf Daten-/Exportmöglichkeiten prüfen; technische Zugangsdaten geschützt halten.
5. Den Pilot nach den P1/P2-Kriterien abnehmen und anschließend die gemeinsam genutzten Dienste für Müll-/Ablesepläne erweitern.

Es wird keine erneute allgemeine Freigabe für die bereits autorisierte lokale Entwicklung benötigt. Externe Übertragung wird als konkrete, prüfbare Funktion vorbereitet und nur im ausdrücklich autorisierten fachlichen Umfang ausgeführt.
