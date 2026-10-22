# ImmoManager Pro 2.0.0

Die Hausverwaltung für private Vermieter und kleine Verwaltungen läuft lokal unter Windows (oder als Server). Es gibt keine Cloud, und das Programm versendet nichts von selbst.

**Installieren:** ZIP entpacken und `ImmoManager-Pro.exe` starten. Beim ersten Start führt „Erste Schritte“ durch die Einrichtung. Einzelheiten stehen in der Datei „LIES MICH.txt“ im Paket.

**Aktualisieren:** Die neue Version in einen neuen Ordner entpacken, die alte beenden und die neue starten. Die Daten bleiben im Datenordner (`%LOCALAPPDATA%\ImmoManagerPro`). Vor jeder Änderung an der Datenbank legt das Programm ein geprüftes Vollbackup an.

## Was neu ist

### Einrichten und Übernehmen
- **Erste Schritte** auf der Startseite führen der Reihe nach durch Portfolio, Immobilie, Einheiten, Bankkonto und Mietverträge.
- **Laufende Mietverhältnisse übernehmen:** Für jeden Vertrag lassen sich „Mietkonto hier geführt ab“ und der Saldo zu diesem Tag (Rückstand oder Guthaben) angeben. Ältere Monate gelten dann nicht als offen.
- **Kautionen übernehmen:** Wurde eine Kaution gezahlt, bevor die Buchungen im Programm beginnen, erfasst man in der Kautionsakte Übernahmetag, eingegangenen Betrag und bis dahin gutgeschriebene Zinsen. Kautionen aus früheren Versionen übernimmt die Kautionsliste nach Rückfrage in einem Schritt.
- Formulare enden nicht mehr in einer Sackgasse. Fehlt eine Voraussetzung, nennt das Formular sie und verlinkt dorthin, wo man sie anlegt. Gibt es nur eine Auswahl, ist sie schon gewählt.

### Alles an einem Ort
- **Objektseite:**
  - Einheiten, Mieter & Verträge, Finanzen, Dokumente und Instandhaltung auf einer Seite;
  - Bearbeiten direkt dort;
  - „Neu für dieses Objekt“ öffnet Einheit, Vertrag, Wartungsfall, Buchung, Rechnung oder Aufgabe schon ausgefüllt.
- **Parteiakte je Mieter:** Verträge, Mietverlauf, Konto, Dokumente, Kaution, Übergaben und Wohnungsgeberbestätigung. Auf der Mieterkonto-Seite lassen sich die Mieterdaten direkt bearbeiten.
- **Durchgehend deutsch:** Status, Arten und Ja/Nein erscheinen überall als Wörter statt als interne Kürzel, auch in Meldungen des Programms; Betragsspalten stehen bündig unter ihrer Überschrift.
- **Verlinkungen überall:**
  - Mietername → Parteiakte;
  - Objekt, Einheit, Wartungsfall, Rechnungsprüfung, Mieterkonto und Mahnfall → ihre Seite;
  - Konto → seine Buchungen;
  - Lieferant → Kontakt.
- **Globale Suche (Strg+K):** findet Datensätze und Seiten und bietet Schnellaktionen wie „Neue Buchung“.

### Mieten und Finanzen
- **Mietanpassungen nachträglich korrigieren:** Betrag, Datum, Vertrag und Mietverlauf ändern sich gemeinsam. Bei einem Fehler bleibt der vorherige Stand vollständig erhalten. Der Prozentsatz wird aus den Mietbeträgen berechnet.
- **Passende Vertragsübersicht:** Vom Mieterkonto führen die Links zu den Verträgen und Buchungen dieser Partei. Übernommene Objekt- und Parteifilter sind sichtbar und lassen sich aufheben.
- **Echte Mietzahlungen** mit Konto, Datum und Betrag, dem Vertrag zugeordnet; ältere Rückstände werden zuerst gedeckt. Dazu eine Mietübersicht mit Soll und Ist je Monat.
- **Cent-genaue Finanzen:**
  - Stornos neutralisieren ihre Buchung;
  - alle Berichte haben dieselben Filter (Zeitraum, Portfolio, Objekt, Einheit);
  - Summenzeilen in den Listen.
- **Nebenkostenabrechnung nach Nutzungszeit:** Mieterwechsel und Leerstand tagesgenau; Zähler, Personen und Korrekturen; abgeschlossene Abrechnungen sind unveränderlich.
- **Mahnwesen:**
  - Stufen, Verzugszinsen und Mahnsperren;
  - Briefe als PDF;
  - Antworten den Fällen zuordnen;
  - das Programm versendet nichts selbst.
- **Rechnungsprüfung:** sachlich und rechnerisch prüfen, freigeben (auf Wunsch mit vier Augen), Skonto, Reklamation. Ist eine ältere Rechnung als bezahlt markiert, aber keine Zahlung zugeordnet, zeigt die Übersicht „Ungeklärt“ statt einen Nachweis vorzutäuschen.
- **Kaution** vom Vereinbaren bis zur Abrechnung beim Auszug.
- **SEPA-Lastschriftdatei für Mieten** (Forderungen → „SEPA-Lastschriftdatei …“): Für ein Konto und einen Monat erstellt das Programm die Datei für das Online-Banking mit den offenen Mieten aller Lastschriftzahler (pain.008, wie es die deutschen Banken erwarten). Es zeigt vorher, was bei einem Mieter noch fehlt (IBAN, Mandat, Datum der Unterschrift), merkt sich die Gläubiger-ID je Konto und verhindert, dass dieselbe Miete versehentlich zweimal eingezogen wird. Gesendet wird nichts; die Datei lädt man selbst bei der Bank hoch. IBAN, Kontoinhaber und Mandatsdatum stehen beim Mieter.

### Haus und Betrieb
- **Übergabeprotokolle:** Räume, Mängel, Fotos, Schlüssel und Zählerstände; abgeschlossen als unveränderliches PDF.
- **Objektverträge** (Strom, Gas, Wärme, Hausmeister …) mit Tarifen und Fristen. An Fristen erinnert das Programm von selbst.
- **Objektvertragsfinanzen über alle Jahre:** freie Jahreswahl, vollständige Zahlungsvorschläge aus dem gewählten Jahr und direkte Links zu Rechnungen und Buchungen. Fehlgeschlagene Auswahldaten lassen sich gezielt erneut laden.
- **Vertragsdokumente:** eindeutige Dokumentauswahl über mehrere Standorte und direkter Sprung in die Dokumentenakte; Ladefehler bleiben als solche erkennbar.
- **Termine und Versicherungen:** Die Einheitenauswahl folgt der Immobilie; beim Immobilienwechsel wird eine nicht mehr passende Einheit zurückgesetzt. Kalendereinträge zeigen verlinkte Immobilien und Einheiten.
- **Wartungsfall als Projektakte:** Angebot, Auftrag, Nachträge, Rechnungen und Zahlungen.
- **Wohnungsgeberbestätigung** als PDF mit Original im Archiv.
- **Briefe mit Briefkopf:** Unter Einstellungen → Briefkopf stehen Absender, Kontakt, Bankverbindung, Fußzeile und Logo einmal für alle Briefe (Abrechnungsschreiben, Mahnbriefe, Kautionsabrechnungen und neue Briefe), nach DIN 5008 mit Anschriftfeld für Fensterumschläge.
- **Briefvorlagen** (Konfiguration → Briefvorlagen) und „Brief schreiben“ am Vertrag und in der Parteiakte:
  - Mieterhöhung auf die ortsübliche Vergleichsmiete mit Prüfung von Sperrfrist, Wartefrist und Kappungsgrenze und dem Datum, ab dem sie gilt;
  - Anpassung der Vorauszahlungen mit Vorschlag aus der letzten Abrechnung;
  - Mietanpassung bei Indexmiete: neue Miete aus dem Verbraucherpreisindex, Termin und Jahresfrist geprüft; die Indexwerte trägt man auf der Seite Briefvorlagen ein (das Programm ruft nichts ab);
  - Bestätigung einer Kündigung mit der gesetzlichen Frist, Mietbescheinigung, Terminankündigung und freies Schreiben;
  - Platzhalter wie `{{mieter.name}}` füllt das Programm aus dem Vertrag; eigene Vorlagen entstehen als Kopie einer mitgelieferten;
  - der fertige Brief wird als unveränderliches Original in der Akte abgelegt; versendet wird nichts.
- **Zählerverlauf:** Ein Klick auf die Zählernummer zeigt alle Ablesungen mit Verbrauch je Zeitraum und je Kalenderjahr, weist auf Auffälligkeiten hin und verlinkt den eigenen Versorgungsvertrag sowie das Kundenportal des Anbieters.
- **Neuvermietung (Leerstand):** Jede frei werdende Einheit wird zum Projekt:
  - Angebot mit Miete, Kaution, Vorgaben und den Pflichtangaben des Energieausweises;
  - Exposé als PDF und Texte für Immobilienportale zum Kopieren (es wird nichts automatisch veröffentlicht);
  - Interessenten mit Unterlagen (bereits erfasste Anfragen der Einheit und neue Anfragen kommen von selbst ins Projekt), Besichtigungen im Besichtigungskalender samt Eindruck danach;
  - Vergleich aller Bewerbungen nach denselben Kriterien, auf Wunsch als pseudonymisierte Frage an den KI-Assistenten;
  - Übernahme als Mieter mit vorausgefülltem Mietvertrag;
  - abgelehnte Bewerber mit allen Unterlagen datenschutzkonform löschen (Hinweis nach drei Monaten);
  - Übersicht und Projekt nennen jeweils den nächsten Schritt, z. B. „Vertrag MV-7 angelegt: Projekt damit abschließen“.

### Schneller arbeiten
- **Tabellen:**
  - Mehrfachauswahl mit Sammelaktionen und Summen;
  - Suche, Filter und Seite bleiben beim Zurückkehren erhalten;
  - Einstellungen je Liste;
  - CSV für deutsche Tabellenprogramme.
- **Listen passen auf den Bildschirm:** Lange Texte stehen auf höchstens zwei Zeilen (der ganze Text erscheint beim Darüberfahren), IBANs in Vierergruppen. Ist eine Liste breiter als das Fenster, bleiben die Aktionen am rechten Rand sichtbar. Jede Zeilenaktion hat ein Symbol oder ihre Beschriftung.
- **Ablaufdaten für Dokumente:** Energieausweis, Wartungsnachweis oder Police bekommen „Gültig bis“ und einen Vorlauf. Rechtzeitig vorher entstehen eine Aufgabe und eine Benachrichtigung, je Ablaufdatum genau einmal. Die Dokumentliste zeigt, was bald abläuft oder abgelaufen ist.
- **Aufbewahrungsfristen:** Jedes Dokument hat eine Aufbewahrungsfrist nach seinem Typ (Rechnungen und Abrechnungen 8 Jahre, Briefe 6 Jahre, Steuerunterlagen 10 Jahre, Verträge bis 3 Jahre nach Vertragsende) oder nach eigener Wahl. Solange sie läuft, lässt sich das Dokument nicht versehentlich löschen; Eigentümer und Verwaltung können es mit Begründung trotzdem löschen, der Grund wird protokolliert. Ein Filter zeigt, was gelöscht werden darf.
- **Seite je Dokument:** Ein Klick auf den Titel öffnet Vorschau, Angaben, Zuordnung, Aufbewahrung, alle Fassungen und den gelesenen Text. Eine korrigierte oder neu eingescannte Datei wird dort als **neue Fassung** desselben Dokuments abgelegt statt als zweites Dokument; frühere Fassungen bleiben unverändert und herunterladbar.
- **Startseite nach eigenem Geschmack:** „Kacheln anpassen“ blendet Kacheln aus und ändert ihre Reihenfolge; die Einstellung gilt je Person.
- **Selten Gebrauchtes unter „Mehr“:** Aktenwerk und TEHA stehen auf der Dokument- und der Objektseite in einem Menü „Mehr“, jeweils mit einem Satz, wofür sie da sind.
- **Volltextsuche in Dokumenten:** Die Dokumentseite durchsucht den Inhalt von PDFs, Text- und Office-Dateien und zeigt die Fundstelle. Auch die globale Suche findet Dokumente über ihren Inhalt. Das Lesen geschieht im Hintergrund und auf dem eigenen Rechner.
- **Dokumenteneingang nur für Unerledigtes:** Abgelegte Dokumente (mit Art und Zuordnung zu Objekt, Einheit, Vertrag oder Partei) zählen nicht mehr als offener Eingang; Rechnungsbelege bleiben dort, bis sie erfasst sind. „Texterkennung“ statt „OCR“.
- **Zahlungsvorschläge** zu einer Rechnung erscheinen auch bei vielen Buchungen sofort.
- **Berichte auch bei großem Bestand zügig:** Übersicht, Prüfliste und Finanzberichte lesen ihre Daten gebündelt. Bei fünf Jahren Buchungen dauert die Liquiditätsplanung für ein Konto mit eingeschränktem Zugriff (z. B. Steuerberater) wenige Sekunden statt fast einer Minute.
- **Formulare:** „Speichern & weiteren“, „Duplizieren“, „Heute“ neben jedem Datum, Strg+Enter zum Speichern; Eingaben gehen beim Schließen nicht verloren.
- **Tastatur:** „/“ öffnet die Suche, Alt+N das Neu-Formular der Liste, „?“ zeigt alle Kürzel. Favoriten lassen sich in der Seitenleiste anheften; aufgeklappte Bereiche bleiben aufgeklappt, und auf einer Detailseite führt der Seitenname oben zurück zur Liste.

### Sicherheit, Sicherung, Updates
- **Rollen und Rechte:** Rollen (Verwaltung, Buchhaltung, Technik, Nur Lesen) mit Portfoliozugriff je Konto.
- **Datensicherung:**
  - täglich ein geprüftes Vollbackup mit Datenbank, Anhängen, Einstellungen und Schlüssel;
  - auf Wunsch eine geprüfte zweite Kopie auf USB-Festplatte oder Netzlaufwerk, eingerichtet unter Einstellungen → System → Betrieb;
  - monatlich eine Wiederherstellungsprobe;
  - Zugangsdaten von Schnittstellen werden verschlüsselt gespeichert.
- **Datenbank-Updates** nur ausdrücklich und immer mit Vollbackup davor.
- **Update-Prüfung** unter Einstellungen → System → Updates, nur auf Klick.
- **Aktenwerk (Dokumentenverwaltung):** Exportpaket oder direkte Übergabe von Verträgen, Rechnungen und absetzbaren Belegen mit steuerlicher Einordnung.

- **Genauer gerechnet (Prüfung aller Rechenwege, Oktober 2026):**
  - Die Miete ist am dritten Werktag fällig (§ 556b BGB), Samstage, Sonntage und bundesweite Feiertage zählen nicht; die erste Miete wird nicht vor dem Einzug fällig. Überfälligkeit, Mahnstufen und Verzugszinsen beginnen deshalb nicht mehr zu früh. Kautionsraten 2 und 3 sind mit der Miete fällig.
  - Eine Mietänderung mitten im Monat gilt tagesgenau ab ihrem Datum und nicht erst ab dem Folgemonat.
  - Eine Zahlung vor dem Einzug oder nach dem Auszug wird dem einzigen Vertrag des Mieters zugeordnet, statt unzugeordnet liegen zu bleiben.
  - Nebenkosten: Eine Nachzahlung, deren Abrechnung erst nach Ablauf der Abrechnungsfrist beim Mieter ankommt, wird nicht mehr als Forderung angelegt (§ 556 Abs. 3 BGB); Guthaben schon. Hat der Vermieter die Verspätung nicht zu vertreten, lässt sie sich ausdrücklich doch anlegen. Bei Gewerbe gilt die Frist nicht. Fehlt beim Mieterwechsel nur eine Zwischenablesung, teilen sich die übrigen Zeiträume genau den Rest des Jahresverbrauchs.
  - Mahnungen für Gewerbeeinheiten berechnen Verzugszinsen mit 9 statt 5 Prozentpunkten über dem Basiszinssatz (§ 288 Abs. 2 BGB).

- **Bessere Lesbarkeit und Bedienung (Layout-Prüfung, Oktober 2026):**
  - Listen mit vielen Aktionen zeigen die wichtigsten direkt; die übrigen und „Löschen“ stehen mit Beschriftung im Menü „⋯“. Am Handy verdeckt die Aktionsspalte die Daten nicht mehr.
  - Graue Hinweise und farbige Status-Kennzeichen haben stärkeren Kontrast; im dunklen Design ist der aktive Filter wieder lesbar.
  - Vertragsnummern brechen nicht mehr mitten in der Nummer um; nach dem Schließen eines Formulars steht der Fokus wieder auf dem Knopf, der es geöffnet hat.

- **Zuverlässiger aktualisiert (Prüfung von Logik und Updates, Oktober 2026):**
  - Aktualisierte Datenbanken bekommen dieselben Indizes wie eine neue Installation; große Bestände laden Listen, Berichte und Mieterkonten dadurch schneller.
  - Dieselbe IBAN lässt sich nicht für zwei Konten anlegen, sonst zählte der Kontostand doppelt.
  - Eine Instandhaltungsakte mit erteilten Aufträgen oder Rechnungen lässt sich nicht mehr löschen, nur abbrechen oder abschließen.
  - In der Nebenkostenabrechnung ergeben die Vorauszahlungsabschnitte auf den Cent die Summe.

## Hinweise zum Update von einer älteren Version
- Beim ersten Start aktualisiert das Programm die Datenbank. Davor legt es ein Vollbackup an; der Speicherort steht im schwarzen Fenster.
- **Bestehende Benutzerkonten** sehen weiterhin alles. Neue Konten sehen erst etwas, wenn der Eigentümer ihnen Portfolios zuweist.
- **Finanzzahlen können sich ändern, und zwar richtig so:**
  - Stornos zählen nicht mehr doppelt;
  - Prognosen rechnen mit den Vertragsmieten;
  - noch nicht abgeschlossene Nebenkostenabrechnungen ergeben bei neuer Erzeugung korrekte Beträge.
  - Abgeschlossene Abrechnungen bleiben unverändert.
- **Datenexport (JSON):** Ein Export dieser Version hat das Format 14 (mit Ablaufdaten, Aufbewahrungsklassen und Lastschriftdaten). Ältere Versionen lehnen ihn ab, statt Daten wegzulassen; ältere Exporte lassen sich weiterhin einlesen.
- **Mietkonten nach der Rechenprüfung:** Fälligkeiten verschieben sich vom 3. Kalendertag auf den 3. Werktag. Verträge mit einer Mietänderung zur Monatsmitte zeigen für diesen Monat jetzt den tagesgenauen Betrag; Rückstand oder Guthaben dieser Konten können sich dadurch um den Unterschied ändern. Bereits abgeschlossene Mahnschreiben und Abrechnungen bleiben, wie sie sind. Bisher unzugeordnete Zahlungen eines Mieters mit nur einem Vertrag, die vor dem Einzug oder nach dem Auszug eingingen, ordnet das Programm beim ersten Start diesem Vertrag zu.
- **Konten mit gleicher IBAN** aus früheren Versionen bleiben erhalten; neue lassen sich nicht mehr anlegen. Bitte doppelt angelegte Konten zusammenführen.
- **Laufende Verträge, die vor der Nutzung des Programms begannen:** „Mietkonto hier geführt ab“ und den Saldo nachtragen, sonst gelten alle Monate seit Vertragsbeginn als offen.

## Bekannte Grenzen
- **Aufbewahrung:** Die Löschsperre schützt vor versehentlichem Löschen; sie macht das Programm nicht zu einem revisionssicheren Archiv (GoBD), und die Einstufung ersetzt keine steuerliche Beratung.
- **Volltextsuche bei Scans und Fotos:** Im Windows-Paket ist keine Texterkennung für Bilder enthalten. Gescannte PDFs ohne Textebene und Fotos sind deshalb nicht durchsuchbar; die Suche nennt, wie viele Dokumente das betrifft.
- **Kündigungsfrist:** Die Briefvorlage berücksichtigt nur bundesweite Feiertage. Serienbriefe an alle Mieter eines Objekts gibt es noch nicht.
- **Versand:** E-Mails und Mahnbriefe erzeugt das Programm als Entwurf oder PDF und versendet sie nicht. Die SEPA-Lastschriftdatei lädt man selbst bei der Bank hoch.
- **Fälligkeit und Feiertage:** Für den dritten Werktag zählen nur die bundesweiten Feiertage; regionale (z. B. Heilige Drei Könige, Fronleichnam) nicht, dort kann eine Miete einen Tag früher als fällig gelten.
- **Heizkosten nach HeizkostenV:** Die Aufteilung in Grund- und Verbrauchskosten (50–70 % nach Verbrauch) wird nicht selbst gebildet; dafür die Heizkosten als zwei Positionen mit Flächen- und Verbrauchsschlüssel erfassen.
- **Steuerliche Jahresauswertung:** Sie folgt dem Buchungsdatum; die Zehn-Tage-Regel für regelmäßig wiederkehrende Zahlungen um den Jahreswechsel (§ 11 EStG) wird nicht angewandt.
- **Vollbackup zurückspielen:** nur über die Kommandozeile (`ImmoManager-Pro.exe ops restore …`), siehe „LIES MICH.txt“.
- **Signaturen:** keine elektronische Unterschrift auf Übergabeprotokollen.
- **Windows-Warnung:** Das Windows-Paket ist nicht signiert. Beim ersten Start meldet Windows das; über „Weitere Informationen → Trotzdem ausführen“ geht es weiter.
