# Wohnungsgeberbestätigung: geprüfter Implementierungsplan

Stand: 02.10.2026. Nutzerauftrag: eigener vollständig nutzbarer Ablauf am
Mietvertrag und beim Einzug. Dieser Plan wird vor Sourceänderungen festgehalten.

## Fachliche Grundlage

Primärquellen, tatsächlich gelesen:

- https://www.gesetze-im-internet.de/bmg/__19.html?iframe=1
- https://www.berlin.de/ba-mitte/politik-und-verwaltung/aemter/amt-fuer-buergerdienste/buergeraemter/wohnungsgeberbestaetigung.pdf

§ 19 Abs. 3 BMG verlangt Namen und Anschrift des Wohnungsgebers, bei abweichendem
Eigentümer dessen Namen, Einzugsdatum, Anschrift der Wohnung und Namen der
meldepflichtigen einziehenden Personen. Der Wohnungsgeber oder eine von ihm
beauftragte Person stellt die Bestätigung aus. Ein unterschreibbares lokales PDF
belegt keine elektronische Übermittlung an die Meldebehörde und keine tatsächlich
geleistete Unterschrift. Namen weiterer Haushaltsmitglieder werden ausdrücklich
erfasst; aus einer Personenzahl oder dem Hauptmieter entstehen keine erfundenen
Bewohner. Geburtsdatum, Ausweisnummer und Steuernummer sind dafür nicht nötig.

## Tatsächliche Ausgangslage und Architekturentscheidung

Vertrag, Immobilie, Einheit, Mieter und Portfolio sind vorhanden. Eigentümername
ist teilweise vorhanden, eine vollständige Wohnungsgeberanschrift und sämtliche
einziehenden Personen fehlen. Geplante Übergabe, Vertragsbeginn und tatsächlicher
Einzug sind verschiedene Angaben. Geprüfte Mietvertrag-Wizard-Daten können nur
bei nachweisbar identischer Vertragsbindung als gekennzeichnete Vorschläge dienen.

Die Korrespondenz verlangt Fristen und besitzt ein anderes Freigabejournal. Ein
Meldebeleg erhält daher keinen erfundenen Korrespondenzstichtag. Ein neues
parallel gepflegtes Archiv oder eine zusätzliche Migration ist ebenfalls nicht
nötig: bestehende Document/DocumentVersion-Originale, unveränderliche Manifeste,
64-KiB-Blöcke, Berechtigungen, Vollsicherung und Personenauskunft werden verwendet.

Das neue Modul erstellt zunächst eine zustandsfreie Serverprüfung/Vorschau und
veröffentlicht nach ausdrücklicher Bestätigung genau diese Fassung atomar als
neues Dokument mit archiviertem Original. Offene Eingaben bleiben im gemounteten
Formular. Eine Browser-Persistenz personenbezogener Entwürfe wird nicht heimlich
eingeführt; die generische Entwurfssicherung erlaubt absichtlich keine beliebigen
Journalbefehle. Bewusstes Schließen nach Änderungen erhält einen Hinweis.

## Eingaben und Quellenbindung

Ein streng typisiertes CertificateData enthält Wohnungsgebername und -anschrift,
Eigentümergleichheit und gegebenenfalls Eigentümername, tatsächliches Einzugsdatum,
Ausstellungsdatum, Wohnungsanschrift mit optionaler Wohnungsbezeichnung,
ausstellende Person und Rolle (Wohnungsgeber/beauftragte Person) und eine geordnete,
nicht leere Liste vollständiger Namen. Namen werden nicht algorithmisch in
Vor-/Nachnamen zerlegt. Gleichnamige tatsächliche Personen sind kein Fehler.
Mehrzeilige Anschriften und internationale Unicode-Namen bleiben darstellbar.

Der Source-Endpunkt liefert ausschließlich den frisch autorisierten exakten
Vertrag mit zugehörigen Quellen und starken Revisionen. Immobiliendaten und
Hauptmietername werden als Vorschläge gezeigt. Die tatsächliche Belegung sowie
Ausstellungsbefugnis erfordern gesonderte Bestätigungen beim Speichern. Kein
automatisches Übernehmen eines Übergabetermins als tatsächlicher Einzug. Keine
willkürlichen Gesamtzahl-, Personen- oder historischen Datumsgrenzen; ungültige
Pflichtfelder erhalten verständliche Korrekturhinweise. Vorläufige Vorschau und
bewusst bestätigte Ausgabe werden im Produkt sprachlich unterschieden.

Die geprüfte Serverfassung enthält normalisierte Eingaben, komplette relevante
Quellsnapshots/Revisionen, Formatversion und deterministischen PDF-SHA256. Ihr
Hash bindet diese gesamte Fassung. Jede Eingabeänderung entwertet die Vorschau.
Beim Speichern werden Quellen und Rechte unter denselben Eltern-/Account-Sperren
wie vorhandene erzeugte Originale erneut geprüft. Geänderte Daten: 409/412 mit
erhaltenem Formular, kein ungeprüfter Beleg.

## Unveränderliches Original und Wiederholung

Document-Typ `housing_confirmation`; benutzerfreundlicher Titel/Beschreibung,
Datum und genaue Immobilien-/Einheits-/Vertragsbindung. Eine feste aus Actor und
Command-Key abgeleitete Dokument-ID macht ein erfolgreiches Speichern nach
verlorener HTTP-Antwort wiederholbar. Dieselbe Referenz mit anderen Eingaben wird
abgewiesen. Vor Wiederholung werden gespeicherter Request, Originalmanifest,
Quelle, Rechte und vollständige Bytes geprüft. Es entsteht genau ein Original.

Das bestehende interne Original-Publish-Hilfsverfahren darf eine schmale optionale
Metadatenergänzung bekommen, die keine bestehenden Document-Felder überschreibt.
Default und Hashpolitik vorhandener Belege bleiben byte-/datenkompatibel. Unter
`housing_confirmation` werden Schema, geprüfte Fassung, Freigabebefehl, Actor und
optionaler Korrekturbezug im unveränderlichen Versionssnapshot gespeichert.
Der eigene reine Belegvalidator prüft Typen, Quellenbindung, Review-/Requesthash,
PDFhash und Bestätigungen. Live-Manifeste und Offline-Vollsicherung rufen ihn für
diesen Dokumenttyp auf; kein beschädigter Beleg wird still ausgelassen.

Liste und Downloads beziehen sich auf archivierte Erstfassungen und deren
Snapshots, nicht auf nachträglich editierbare Dokumenttitel/-typen. Filter und
Cursor erfolgen in SQL vor dem Seitenlimit; Memory verwendet begrenzte Auswahl.
Keine vollständige Jahreshistorie wird für eine sichtbare Seite kopiert. Eine
Korrektur erzeugt ein neues ausdrücklich verknüpftes Original; das alte bleibt
erhalten. Ein fremder Vertrags-/Portfoliobeleg darf kein Korrekturbezug werden.

Der reservierte Dateipfad `housing-confirmations/<id>.pdf` liefert ausschließlich
verifizierte Originalbytes. Ein gleichnamiges physisches Upload ersetzt ihn nicht.
Standard-Dokumentdownload und Originalversion bleiben bedienbar. Die bestehenden
Dokument-Retentionssperren, Personenauskunft und Vollsicherung schützen den Beleg
ohne zusätzliche Tabelle. Mitspeicherte weitere Namen sind als personenbezogene
Originalinhalte transparent; keine erfundenen Stammdatenbeziehungen.

## Oberfläche und PDF

Eigener klar benannter Einstieg am Vertrag; beim Einzug Einstieg mit ausdrücklich
gebundenem neuem Vertrag. Kompakte Abschnitte für Wohnung, Wohnungsgeber,
Eigentümer, Personen und Ausstellung. Personen hinzufügen/entfernen ohne starre
Anzahlgrenze. Vorschau, klare Freigabebestätigungen, Speichern und PDF öffnen.
Gespeicherte Bestätigungen sind mit Datum und Korrekturbezug wieder auffindbar.

Role-/Portfolio-/Benutzerwechsel neutralisieren alte Inhalte render-synchron;
laufende Requests werden abgebrochen. 401/403/404 löschen private Anzeige und
Retry. Bei unbekannter Netzwerkantwort bleibt genau der eingefrorene Befehl mit
verständlichem Wiederholen verfügbar; Bearbeiten erzeugt keine stille neue
Referenz. Modal ist per Tastatur bedienbar, Fokus kehrt zum Auslöser zurück.
320/360/1440 Pixel werden am echten Browser geprüft, keine horizontale Überbreite.

PDF: A4, klare Überschrift, Pflichtangaben, fortlaufende Personennummern mit
wiederholter Tabellenüberschrift bei Seitenwechsel, Seitenzahlen sowie Platz für
Ort/Datum und tatsächliche Unterschrift. Keine kopierte digitale Unterschrift,
keine Anmeldung-/Zustellbehauptung. Lange Namen/Anschriften und 40+ Personen
müssen sich auf Folgeseiten lesbar umbrechen. Normale und mehrseitige synthetische
PDFs werden gerendert und visuell kontrolliert, zusätzlich textuell vollständig
geprüft. Fonts müssen Umlaute und benutzte Unicode-Zeichen abdecken.

## Arbeitsaufteilung und notwendige Beweise

Backend-Assistent: eigene Featurebranch vom angegebenen Root-Commit; Source,
Modelle/Renderer/Validator, Router und minimale bestehende Original-/Offline-
Download-Anbindung, gezielte Memory/SQLite/echte PG- und HTTP-Gates. Vor Code
Plan gelesen bestätigen und alle nötigen Abweichungen im Handoff begründen.
Frontend-Assistent: eigener Component/API-Client/Styles/DE-EN-ES-Texte und
Vertrags-/Einzugseinstieg, echte Erfolg-/Unbekannt-/Scope-/Änderungsfälle. Erst
nach Abschluss seines aktuellen Workflow-UI-Pakets und festem Backendvertrag.
Root: Komposition, unabhängige Regressionen, reale Browserbedienung und PDF-QA.

Pflichtproben: mehrere Personen und nicht identischer Eigentümer; tatsächliches
Datum unabhängig vom Vertragsbeginn; alle Pflichtfelder; spezielle Textzeichen;
lange Mehrseitenausgabe; geänderte Quellen; fremdes Portfolio; entzogenes Recht;
identischer Retry nach Commit; andere Eingaben mit gleichem Key; paralleles
Speichern; Rollback zwischen Dokument und Chunks; beschädigte Review/Bytes;
reservierter Pfad; Korrekturbindung; Personenauskunft/Anonymisierung behält Beleg;
Offline-Vollsicherung akzeptiert Original und verweigert beschädigte Metadaten.

Keine Hauptdatenbank, Privatnamen, Portalzugänge oder Release126-Vorschau werden
für Tests verändert. Ein veröffentlichter Erfolg wird erst nach Komposition und
den passenden Beweisen berichtet.
