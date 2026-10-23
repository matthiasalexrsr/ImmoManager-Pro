# vermieter1: Untersuchung des angemeldeten Produkts

Stand: 7. Oktober 2026. Direkte, lesende Untersuchung im vom Nutzer angemeldeten In-App-Browser. Die betrachtete Installation hat einen leeren Bestand und den Free-Tarif. Es wurden keine Immobilien, Personen, Zahlungen oder Verträge angelegt, keine Bankkonten verbunden und keine kostenpflichtigen Funktionen aktiviert. Leere Erfassungsformulare wurden geöffnet und verworfen. Persönliche Kontodaten, Cookies und Zugangstoken gehören nicht zu diesem Bericht.

Dieser Bericht beschreibt beobachtete Oberfläche und Felder. Er bestätigt weder die fachliche Richtigkeit der Berechnungen noch Speicherung, Rechteprüfung, Skalierbarkeit oder Zuverlässigkeit des Wettbewerbers. Gesetzeshinweise in dessen Formularen sind Produkttext und wurden hier nicht als Rechtsgrundlage übernommen.

## Zugang und Arbeitskontext

Im Kopf stehen ein globaler Immobilienfilter und ein globales Abrechnungsjahr. Der betrachtete Stand war 2026. Die Navigation gruppiert Verwaltung, Mieter/Verträge, Banking, Finanzen/Abrechnung und Dokumente. Zusätzliche Module werden separat aufgeklappt. Die Gesamtansicht bleibt erreichbar, obwohl einzelne Fachseiten einen eigenen Filter besitzen.

Für uns: Objekt und Zeitraum sollten innerhalb eines Arbeitsablaufs erhalten bleiben. Dabei muss sichtbar sein, ob eine Seite diesen Filter tatsächlich berücksichtigt. Ein dekorativer globaler Filter, dessen Wirkung zwischen Modulen unklar ist, wäre eine Verschlechterung.

## Beobachtete Masken und Abläufe

| Ansicht | Direkt beobachtet | Folgerung für ImmoManager |
| --- | --- | --- |
| Dashboard | Hinweis auf unvollständige Absenderanschrift; Einrichtungsfolge Gebäude → Einheiten → Mieter → Zähler; Bestands-/Vermietungskennzahlen, monatliche Soll-/Istwerte, Handlungsbedarf, Aktivitäten, auslaufende Verträge | Startklarheit und laufende Tagesarbeit unterscheiden. Bei leerem Bestand sinnvolle nächste Schritte statt unbegründeter Erfolgsmeldungen. |
| Abrechnungsvorbereitung auf dem Dashboard | Jahr und Frist, Fortschritt über Kostenkategorien, direkte Erfassungsaktionen; Zählerfristen gesondert | Vorprüfungen mit direktem Weg zum betroffenen Datensatz. Kostenarten dürfen erst nach Prüfung ihrer Anwendbarkeit als fehlend gelten. |
| Immobilienliste | Suche, Leerstandsfilter, Kennzahlen, Excel-Auswertung, Einrichtungsassistent | Vollständiger Bestand hinter Filtern/Exporten; direkte Aktennavigation. Ein Exportmenü allein belegt noch keinen vollständigen Export. |
| Immobilie anlegen | Name, Gebäudetyp, Baujahr, getrennte Adressfelder, Erwerbsdatum/-preis, Notiz, einzelne Eigentumswohnung mit externer WEG-Verwaltung | Fachliche Sonderfälle als optionale Bereiche. Erwerbsdaten mit Zweck erklären, ohne sie bei einfacher Mietverwaltung zu erzwingen. |
| AfA-Unterbereich | Grundstücksanteil, lineare/degressive Methode, Restnutzungsdauergutachten | Versionierte Steuergrundlagen mit Quellen und Gültigkeit. Hersteller-Voreinstellungen und heutige Steuersätze nicht ungeprüft fest einbauen. |
| Heizung am Gebäude | Heizungs-/Brennstoffart, zentrale Warmwasserbereitung, Verbrauchsanteil, Sonderfall-/Befreiungsangaben, Startmonat des Heizjahrs, Leerstandsbehandlung, Solarthermie und BHKW | Heizsystem als eigene datierte Grundlage. Ausnahmen mit Begründung/Nachweis; nicht nur lose boolesche Stammdaten. |
| Weitere Energieangaben | Vermieter stellt Strom bereit; separate Photovoltaik-Konfiguration | Energieverträge, Anlagen, Messstellen und lokale Abrechnung trennen und miteinander verknüpfen. |
| Einheitenliste | Immobilie, Status, Mieter, Fläche, Warmmiete; Filter verfügbar/vermietet/in Wartung | Status und tatsächliche Vertragsbelegung eindeutig unterscheiden. Wartung bedeutet nicht automatisch Leerstand. |
| Neue Einheit | Ohne Gebäude verständliche Voraussetzung und Weg zur Gebäudeanlage; weitere Schritte nicht zugänglich | Fehlende Voraussetzungen gezielt beheben lassen; Entwurf und Rückweg erhalten. Kein Nachweis der späteren Assistentenfelder. |
| Mieterliste | Aktiv/ehemalig, fehlende Angaben, Kontakt, aktuelle Einheit, Portalstatus, Personenzahl; Importaktion | Partei, Bewohner und Vertrag fachlich unterscheiden; vollständige Akte statt verstreuter Namenslinks. |
| Neuer Mieter, privat | Vor-/Nachname, E-Mail, Mobil/Festnetz, Geburtsdatum, optionale Bankdaten, vorige/abweichende Post-/Abrechnungsanschrift, Notfallkontakt, Notizen | Seltene Angaben einklappbar; Kommunikationsadresse und Vertragsanschrift getrennt. Keine pauschale Pflicht, unnötige sensible Angaben zu erfassen. |
| Neuer Mieter, gewerblich | Umschaltung auf Firma und Ansprechpartner | Eine Partei kann eine Organisation sein; Ansprechpartner bleiben eigenständige Kontakte. |
| Datenschutzfeld | Allgemeines Einwilligungs-Kontrollkästchen im Parteienformular | Dieses Muster nicht ungeprüft übernehmen: ein Häkchen ist kein vollständiges Modell für Zwecke, Rechtsgrundlagen, Nachweise und Aufbewahrung. |
| Mietverhältnisse | Aktiv/Entwurf/gekündigt/beendet/bald endend, gelöschte Einträge gesondert, Partei/Einheit/Zeitraum/Warmmiete, Personenzahl und bald endende Verträge | Statuswechsel als Vorgang führen; historische Verträge bleiben auffindbar. |
| Vertragsassistent | Vier angekündigte Abschnitte; ohne Einheiten konkreter Hinweis und Objektlink | Weitere Schritte mangels Bestand nicht unabhängig geprüft. Vorhandenen eigenen Assistenten verbessern, keinen zweiten erstellen. |
| Zahlungsübersicht | Jahr, Objekt, Soll/eingegangen/offen/überfällig; ausstehend/teilweise/vollständig/überzahlt; Mieten erzeugen und Zahlung erfassen als getrennte Aktionen | Sollstellung und tatsächlichen Geldfluss trennen. Überzahlungen und Nullmonate sichtbar lassen. |
| Zahlung erfassen | Mietvertrag, bewusst auszuwählender Monat, Jahr, Betrag, tatsächlicher Eingang, Zahlungsart, Referenz, Notiz | Nicht aus heutigem Datum still auf den auszugleichenden Monat schließen. Zuordnung bei Mehrvertragsparteien explizit. |
| Kautionen | Eigener Reiter mit Soll/erhalten/offen und Rückzahlungsfälligkeit; teilweise/überzahlt/zurückgezahlt | Zustände sind hilfreich, aber unsere Abnahme muss zusätzlich vollständige Geldbewegungen und Gegenbelege nachweisen. Keine Kautionsdetailprüfung ohne Datensatz möglich. |
| Rückstandsanalyse | Abgleich von Sollstellungen mit Bankumsätzen; im betrachteten Tarif wegen fehlender Kontoanbindung nicht verfügbar; verständlicher Fehler und Wiederholung | Automatische Bankanbindung darf bei uns die manuelle/offline Rückstandsprüfung nicht ersetzen oder blockieren. |
| Betriebskostenliste | Jahr, Kategorien, Ausgaben/Gutschriften, DATEV-Aktion, Weg zur Abrechnung | Umlagefähige und nicht umlagefähige Kosten derselben finanziellen Quelle zuordnen, ohne doppelte Buchung. |
| Neue Ausgabe | Kategorien nach Steuern/Wasser/Energie/Wartung/Entsorgung/Versicherung/Personal und nicht umlagefähigen bzw. steuerbezogenen Ausgaben gruppiert | Gemeinsamer versionierter Kostenkatalog; einfache Auswahl mit gezielter Hilfe. |
| Zeitbezug einer Ausgabe | Leistungsbeginn/-ende, Rechnungsdatum und Zahlungsdatum separat; Jahres-/Quartalsvorgaben | Periodenergebnis, Nebenkosten und Zahlungsbericht dürfen unterschiedliche Daten verwenden, müssen diese Grundlage aber klar ausweisen. |
| Beleg einer Ausgabe | Upload oder vorhandenen Beleg verknüpfen; Hinweis, dass Entknüpfen das Archivoriginal erhält | Ein Originalarchiv mit fachlichen Verknüpfungen weiterverwenden; keine zweite Belegkopie pro Modul. |
| Kostendetails | Optionaler Lieferant, Rechnungsnummer, Dienstleister; Zuordnung zu allen oder bestimmten Einheiten | Leistungsbezug und Kostenkreis ausdrücklich modellieren. Teilmengen dürfen keine versteckte Umlage auf übrige Einheiten erzeugen. |
| Rechnungsimport | PDF-/KI-Import angeboten | Nur Angebot beobachtet, keine Datei hochgeladen. Für uns: Vorschau, Quellenmarkierung, Fehlerkorrektur und bestätigte Übernahme statt stiller Buchung. |
| Erweiterte Kosten | Fläche, Verbrauch, gleiche Einheiten, Personen, Pauschale, Kombination Fläche/Verbrauch, Miteigentumsanteile und feste Prozente; Komponenten wie Grundpreis/Verbrauch; Umsatzsteuer, Umlagefähigkeit und Gutschrift | Kostenkomponenten brauchen jeweils eigene Verteilungsgrundlage. Historische Regeln versionieren und Summen vor Veröffentlichung abstimmen. |
| Zählerliste | Gebäude-/Wohnungszähler getrennt; Kalt-/Warmwasser, Heizung, Strom/Nachtstrom, Gas, Öl, Fernwärme/Wärmemenge; mehrere Geräte anlegen | Medium, Gerätetyp und Einheit fachlich trennen. Ein abweichender Gerätetyp darf nicht still dieselbe Messgröße bedeuten. |
| Zähleranlage | Gebäudemodus entfernt die Pflicht zu einer Wohnung; typabhängige Maßeinheit, Seriennummer, Beschreibung, Startwert mit Datum, Hersteller/Modell, Eichdatum/-ablauf, Fernablesbarkeit | Gebäudezähler sind ein echter fehlender Fall bei uns. Automatisch ermittelte Fristen brauchen versionierte Grundlage und begründbare Korrektur. |
| Differenzmessung | Optionale Eigentümereinheit beim Gebäudezähler, Verbrauch als Hauptzähler minus Zwischenzähler beschrieben | Differenz darf erst nach Prüfung identischer Medien, Intervalle und vollständiger Unterzähler einer Einheit zugerechnet werden. Nicht pauschal jeden Messverlust einem Bewohner zuordnen. |
| Ablesungen | Karten/Tabelle, Posteingang, Stichtagsablesung; Formular mit Objekt/Einheit/Typ, Ablesedatum, vorherigem/aktuellem Stand, Notiz und Fotos | Beleg und Herkunft des Messwerts festhalten; historischen Vorgänger referenzieren statt unbemerkt manuell ersetzen. Weiterführende Stichtags-/Prüfabläufe ohne Geräte nicht abgenommen. |
| Abrechnungsassistent | Vier sichtbare Schritte: Zeitraum, Kostenprüfung, Verteilung je Mieter, Abschluss; individuell wählbarer Zeitraum | Summenprüfung vor Veröffentlichung, jederzeit zurück zu den betroffenen Quellen. Die späteren Schritte waren ohne Objekt nicht erreichbar. |
| Brennstoffkonto | Eigenes Modul für Bestände und Zukäufe, verlangt Objektwahl | Lagerbestand und Verbrauch einer Periode nicht mit Rechnungszahlung gleichsetzen. Detailmaske ohne Gebäude nicht geprüft. |
| Dokumentenverwaltung | Ordner, nicht zugeordnete Dokumente, eigene Kategorien, Suche; Upload mit Kategorie und Tags | Archivorganisation ergänzen, fachliche Partei-/Objektverknüpfungen und Originalversionen bleiben maßgeblich. Kein Nachweis von Versionierung allein aus diesem Formular. |
| Postausgang | Vorbereitung, PDF-Prüfung, Versand; Statusgruppen Entwürfe/in Zustellung/versendet, getrennte Zahlungsmethode | Fachliche Freigabe, Bezahlung eines Versanddienstes und tatsächlicher Zustellstatus getrennt führen. Es wurde kein Brief angelegt oder versendet. |
| Aufgaben | Titel, Beschreibung, Priorität, Fälligkeit und getrennte Erinnerung; Objekt/Einheit/Mieter und Kategorie optional | Fälligkeit und Erinnerungszeit unterscheiden; gleiche Aufgabe aus mehreren Akten erreichbar machen. |
| Aufgabenserie | Alltagssprache für täglich/wöchentlich/monatlich/quartalsweise/halbjährlich/jährlich; Intervall und Enddatum | Vorhandene eigene Serienengine mit verständlichem Editor erschließen; letzte Monatstage und Ausnahmen explizit behandeln. |
| Bankkonten | Kontostatus, SCA-Bedarf/Fehler, letzter erfolgreicher Abruf, offene Zuordnungen | Verbindungsstatus und Datenfrische sichtbar; fehlgeschlagener Abruf darf keinen scheinbar aktuellen Nullsaldo erzeugen. |
| Banktransaktionen | Zugeordnet/Vorschlag/offen/ignoriert; Konto, Richtung, Zeitraum, Suche; Erklärung der verwendeten Zuordnungskriterien | Vorschläge begründen, mehrdeutige Kandidaten gemeinsam zeigen, Regeln versionieren. Die tatsächliche Zuordnung konnte ohne Konto nicht geprüft werden. |
| Sichtbare Zuordnungslogik | Punktbasierte Kriterien für IBAN, Betrag, Vertragsmiete, Name, Text, Zeitpunkt und Dauerauftrag; Toleranzen und Schwellen erklärt | Erklärbarkeit ist nützlich. Wir sollten korrelierte Treffer nicht als unabhängige Sicherheit addieren und einen Betrag innerhalb einer Toleranz nicht ohne Restbetragsprüfung als vollständig bezahlt behandeln. |
| Anlage V | Übersicht mit Entwurf/berechnet/geprüft/exportiert und Jahressummen; Freischaltung erforderlich | Exportiert ist nicht erfolgreich im Zielprogramm importiert. WISO-Abnahme bleibt eigener Prüfpunkt. |

## Sichtbare Zugangsbeschränkungen

Im aufgeklappten Menü waren Energieverträge, Dienstleister, Übergaben, Terminabstimmung, Besichtigungen, Bewerber, Jahresübersicht, Rücklagen, Vorauszahlungen, Stromabrechnung, WEG, Generator-Hub, Mieternachrichten, Einstellungen und Zählerstandsprüfung als im Free-Tarif gesperrt gekennzeichnet. Diese Funktionen wurden nicht als live geprüfte Abläufe gewertet. Die transaktionsbasierte Rückstandsprüfung verlangte ein Bank-Add-on.

Ein leerer Bestand verhinderte die Untersuchung echter Partei-/Vertragsdetailakten und der späteren Schritte mancher Assistenten. Die vorhandenen offiziellen Beschreibungen ergänzen diese Lücken, ersetzen aber keine praktische Abnahme. Zeitweise Browser-Verbindungszeitüberschreitungen wurden nach Abschluss der parallelen nativen Windows-Untersuchung behoben; Kosten-, Zähler-, Aufgaben-, Dokument- und Bankingoberflächen wurden anschließend weiter untersucht. Ein technischer Zusammenhang ist damit nicht bewiesen.

## Technisch beobachtete Lesezugriffe

Die Browser-Netzwerkbeobachtung bestätigte die API-Herkunft `https://api.vermieter1.de` und erfolgreiche GET-Aufrufe von `/api/properties`, `/api/units` sowie `/api/leases` mit den Parameternamen `page` und `limit`. Erfasst wurden nur Ursprung, Pfad, Methode, Parametername und Status; keine Authentifizierungsheader, Cookies oder personenbezogenen Antwortinhalte. Es wurden keine Endpunkte geraten, keine Schreibaufrufe wiederholt und keine Tarifschranken umgangen.

Weitere tatsächlich von der Oberfläche ausgelöste GET-Aufrufe:

| Pfad unter `/api` | Beobachtete Parameter | HTTP-Ergebnis |
| --- | --- | --- |
| `/meter-numbers` | keine | 200 |
| `/meter-readings` | `page`, `limit`, `startDate`, `endDate` | 200 |
| `/meter-readings/pending/count` | keine | 403 |
| `/abrechnungen` | `page`, `limit`, `year` | 200 |
| `/document-folders`, `/document-categories`, `/documents` | keine | 200 |
| `/postal/eligibility`, `/postal/templates` | keine | 200 |
| `/postal`, `/tenants` | `limit` | 200 |
| `/tasks` | `page`, `limit` | 200 |
| `/tasks/stats` | keine | 200 |
| `/bank-connections/billing-summary` | keine | 200 |
| `/bank-connections`, `/bank-transactions/summary` | keine | 403 |
| `/bank-transactions` | `page`, `limit` | 403 |

Die Ereignishistorie war bei einer Zwischenabfrage gekürzt. Das Inventar ist daher eine positiv belegte Teilmenge, keine vollständige API-Spezifikation. 403-Antworten wurden nicht umgangen. Sichtbare leere Banklisten sind im vorliegenden Konto kein Nachweis eines erfolgreichen Datenabrufs.

Diese Beobachtung ist ein Schnittstelleninventar, keine stabile oder unterstützte Integrationsvereinbarung. Sie rechtfertigt insbesondere keinen produktiven Adapter, der auf interne Routen des Wettbewerbers angewiesen wäre. Für einen später ausdrücklich gewünschten Datenumzug wären zunächst dessen tatsächliche Exportmöglichkeiten und ein versionierter Import in unser eigenes Datenmodell zu prüfen.

## Konkrete Designentscheidungen

1. Den vorhandenen Kern zu vollständigen Abläufen verbinden: Akte → Quellbeleg → Bearbeitung → Rückweg mit gleichem Objekt/Zeitraum.
2. Häufige Felder zuerst; fachliche Sonderfälle gezielt aufklappen. Änderungen an abgeschlossenen Perioden benötigen eine neue Fassung.
3. Eine Liste zeigt den Bestand, eine Kennzahl ihre Berechnungsgrundlage, ein Fehler einen behebbaren Zustand. Keine stillen Nullwerte bei Ladefehlern.
4. Soll, Zahlung, Kaution, Vorauszahlung und Ergebnis getrennt benennen und über gemeinsame Belege abstimmen.
5. Fachregeln und Datenintegrität unabhängig von Online-Diensten halten. Banking, KI und Versand ergänzen die private lokale Verwaltung.
6. Bestehende Parteieninfokarte und Dokumenteneinsicht weiterverwenden. Ein globaler Dokumentbereich allein reicht für die tägliche Arbeit an einer Partei nicht.

Siehe auch [Gesamtvergleich und Umsetzungsreihenfolge](COMPETITIVE_REVIEW_20261007.md).
