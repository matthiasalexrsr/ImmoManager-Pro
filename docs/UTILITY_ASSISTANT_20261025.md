# Nebenkosten-Assistent und Dokumente des Messdienstes

Stand 25. Oktober 2026, Branch `claude/dreamy-gauss-nmaxhn`, Runde 20. Keine Migration.

## Der Assistent

Finanzen → **Nebenkosten-Assistent** (`/statements/assistant`), auch über „Mit dem Assistenten abrechnen“ auf der Abrechnungsseite und „Im Assistenten öffnen“ bei einer Abrechnung. Er führt in sieben Schritten durch eine Abrechnung und zeigt neben jedem Schritt, was für die gewählte Immobilie gilt („Für dieses Haus“). Unter 1600 px Breite stehen diese Hinweise über dem Schritt.

| Schritt | Was er zeigt | Was man dort tut |
|---|---|---|
| 1. Objekt & Zeitraum | Einheiten (Wohnungen, Gewerbe, Stellplätze), Fläche, Zähler je Art, Frist nach § 556 Abs. 3 BGB mit verbleibenden Tagen, vorhandene Abrechnungen | einen Entwurf weiterführen oder eine neue Abrechnung anlegen (vorgeschlagen: die zwölf Monate nach der letzten, sonst das Vorjahr) |
| 2. Nutzer & Zeiträume | je Einheit die Mietverhältnisse und Leerstände im Zeitraum mit Tagen, Personen und Vorauszahlungen | Fehlendes über die Links ergänzen (Fläche, Personen, Vertragsende) |
| 3. Verteilerschlüssel | die Schlüssel der Immobilie und ob die Abrechnung sie benutzt; Empfehlungen aus der Lage des Hauses | eine Empfehlung mit einem Klick anlegen |
| 4. Kosten | die Kosten des Zeitraums, die Kostenarten des Vorjahrs, die hier noch fehlen, offene Rechnungen aus Objektverträgen | Kostenart nach § 2 BetrKV wählen (Bezeichnung und üblicher Schlüssel werden vorgeschlagen), Betrag eintragen; aus dem Vorjahr übernehmen; das Dokument des Messdienstes einlesen |
| 5. Zählerstände | die Stände, die die Verbrauchsschlüssel brauchen: am ersten und letzten Tag und bei jedem Mieterwechsel (Auszug, Einzug), mit vorhandenem Wert (±7 Tage) | fehlende Stände an Ort und Stelle eintragen oder das Ableseprotokoll einlesen |
| 6. Prüfen | die Prüfung der Abrechnung (dieselbe wie auf der Abrechnungsseite): was vorher geklärt werden muss, was sich ansehen lohnt | — |
| 7. Abrechnen | die Einzelabrechnungen je Nutzer mit Kosten, Vorauszahlungen und Nachzahlung oder Guthaben | erzeugen; weiter zu Schreiben, Prüfung und Versand auf der Abrechnungsseite |

### Hinweise „Für dieses Haus“

Sie entstehen aus den Daten der Immobilie (`GET /billing/guide`, `services/billing_guide.py`) und nennen deren Einheiten, Mieter, Zähler und Tage, zum Beispiel:

* Frist: „Die Abrechnung muss den Mietern bis 31.12.2026 zugehen (§ 556 Abs. 3 BGB), noch 67 Tage“; abgelaufen: Nachforderungen an Wohnungsmieter ausgeschlossen.
* Mieterwechsel mit Datum und Namen, Leerstand mit Tagen (trägt der Vermieter), Stellplätze ohne Fläche (nehmen an der Flächenumlage nicht teil), Gewerbe (Ausschlussfrist gilt nicht, Umsatzsteuer bei Option), fehlende Fläche oder Personenzahl, Verträge ohne Vorauszahlung, sich überschneidende Verträge.
* Heizung: mit Heizkostenverteilern oder Wärmezählern der Hinweis auf 50 bis 70 % nach Verbrauch (HeizkostenV §§ 7, 8); ohne Verbrauchserfassung bei Heizkosten das Kürzungsrecht von 15 % (§ 12 HeizkostenV) und bei höchstens zwei Wohnungen die Ausnahme des § 2.
* Schlüssel: ein Verbrauchsschlüssel wird empfohlen, wenn **jede vermietete Einheit** einen Zähler dieser Art hat und alle in derselben Einheit zählen; sonst steht im Hinweis, wo einer fehlt.
* Kosten: im Vorjahr abgerechnete Kostenarten, die fehlen; Positionen, die sich um mehr als 25 % geändert haben; Objektverträge mit noch nicht übernommenen Rechnungen.
* Zählerstände: wie viele fehlen, davon Zwischenablesungen beim Mieterwechsel (ohne sie teilt die Abrechnung den Verbrauch nach Tagen).

Der Assistent schreibt nur über die vorhandenen Wege (Abrechnungsperiode, Verteilerschlüssel, Kostenposition, Zählerstand, Erzeugen); Rechte und Prüfungen sind dieselben wie auf den übrigen Seiten. Eine abgeschlossene Abrechnung lässt sich dort nur ansehen.

## Dokumente des Messdienstes

Auf der Abrechnungsseite (bei einer Abrechnung, Abschnitt Kosten), im Assistenten (Schritte Kosten und Zählerstände) und auf der Zählerseite (nur Zählerstände) gibt es ein Ablagefeld für die Heiz- und Warmwasserkostenabrechnung, das Ableseprotokoll, die Wasserkostenabrechnung oder die Rechnung eines Messdienstes (ista, Techem, Brunata-Metrona, Minol, KALO und andere). Die Datei wird als Dokument der Immobilie abgelegt und gelesen; das Ergebnis ist ein **Vorschlag**, nichts wird ohne Prüfung gespeichert.

### Wer liest

* **KI:** Ist im Bereich Assistent ein Claude- oder ChatGPT-Konto verbunden, liest es das Dokument (voreingestellt). Übergeben werden der Text des Dokuments und – bei Scans ohne Textebene (mit PyMuPDF) und Fotos – die Seitenbilder, dazu die Gerätenummern und Einheiten der Immobilie. Das Konto bekommt keine Werkzeuge der Anwendung und keine Internetrecherche. Die Antwort muss ein JSON-Block in festem Schema sein; jeder Wert wird geprüft (Beträge, Daten, Arten), Unlesbares wird verworfen.
* **Lokale Regeln:** immer verfügbar, ohne Konto. Sie lesen die üblichen Abrechnungen mit Textebene: Messdienst, Art, Zeitraum, Ablesetag, Verbrauchsanteil („30 % Grundkosten, 70 % Verbrauchskosten“), Kostenzeilen mit Betrag (Summenzeilen, Vorauszahlungen und Anteile einzelner Nutzer nicht), Gerätezeilen mit Anfangsstand, Ablesewert und Verbrauch (erkannt an ihrer Summe) und die Kosten je Nutzeinheit.

### Der Vorschlag

* **Kosten** mit Kostenart und dem Schlüssel der Immobilie: Heizung und Warmwasser nach dem Verbrauchsschlüssel mit dem Anteil aus dem Dokument (sonst 70 %), die Grundkosten nach Fläche; Wasser nach den Wasserzählern, sonst nach Personen, sonst nach Fläche. Verbrauchserfassung und Gerätemiete für Heizkostenverteiler zählen zu den Heizkosten, für Wasserzähler zum Wasser. Gibt es mehrere Schlüssel einer Art („Personen 2023“, „Personen 2025“), gilt der, den die Abrechnung schon benutzt, sonst der mit ihrem Jahr im Namen, sonst der neueste.
* **Zählerstände**, den Zählern der Immobilie über die Gerätenummer zugeordnet (auch über die Ziffern allein: „WZ 26958890“ = „26958890“); unklare Werte sind markiert, fremde Gerätenummern bleiben abgewählt.
* **Ergebnis je Nutzeinheit** laut Messdienst, zum Vergleich mit der eigenen Abrechnung.
* **Hinweise:** Positionen, die nicht die Summe des Dokuments ergeben; Zeitraum des Dokuments ≠ Abrechnungszeitraum; Kostenarten, die die Abrechnung schon enthält (sonst doppelte Umlage); fehlender Verbrauchsschlüssel.

Jede Zeile lässt sich ändern oder abwählen. **Übernehmen** legt die gewählten Kosten als Kostenpositionen der Abrechnung an (Herkunft: das Dokument) und die Zählerstände mit dem Vermerk „aus „…““, in einer Transaktion. Abgelehnt werden: ein zweites Übernehmen aus demselben Dokument in dieselbe Abrechnung, Zählerstände, die für denselben Tag schon mit anderem Wert gespeichert sind (gleiche Werte werden übersprungen), Schlüssel einer anderen Immobilie, Ablesetage in der Zukunft. Kosten übernehmen dürfen Eigentümer, Verwaltung und Buchhaltung, Zählerstände Eigentümer, Verwaltung und Technik. Jede Übernahme steht im Änderungsprotokoll.

Schnittstellen: `GET /billing/meter-documents/readers`, `POST /billing/meter-documents/{document_id}/analysis` (`reader`: `local`, `claude`, `codex`), `POST /billing/meter-documents/{document_id}/apply`.

### Grenzen

* Die lokalen Regeln lesen nur Text; für Scans und Fotos braucht es die KI oder eine Texterkennung (im Windows-Paket nicht enthalten). Gescannte PDFs gibt die KI-Auswertung nur mit PyMuPDF als Bilder weiter, sonst bitte ein Foto oder eine PDF mit Textebene.
* Die Aufteilung des Messdienstes je Nutzeinheit wird angezeigt, nicht übernommen: Die Anwendung rechnet aus Kosten und Zählerständen selbst. Weicht das Ergebnis ab, liegt es meist an einem anderen Verbrauchsanteil, an Gerätefaktoren der Heizkostenverteiler oder an Zwischenablesungen.

## Drucken und Teilen von Dokumenten

* **Drucken** in der Dokumentliste (eine Zeile oder mehrere ausgewählte), auf der Dokumentseite und in beiden Ansichten. `POST /documents/print` setzt die aktuellen Dateien zu einem PDF zusammen: PDFs mit allen Seiten, Bilder je auf eine A4-Seite (quer, wenn das Bild quer ist), Textdateien, mit lokalem LibreOffice auch Word-Dateien. Was sich nicht drucken lässt, wird genannt. Der Druckdialog des Browsers öffnet sich, ohne die Seite zu verlassen.
* **Teilen** (Dokumentliste, Dokumentseite): Empfänger aus der zugeordneten Partei (Name, E-Mail, Mobilnummer), Betreff und Nachricht vorbelegt, dann
  * **E-Mail mit Anhang:** ein E-Mail-Entwurf (`.eml`, als ungesendet markiert), der sich in Outlook, Thunderbird oder Windows Mail als fertige E-Mail öffnet; im Änderungsprotokoll mit Empfänger vermerkt;
  * **WhatsApp:** öffnet den Chat mit der Mobilnummer (deutsche Nummern werden international geschrieben) und der Nachricht, die Datei liegt zum Anhängen in den Downloads;
  * **Mit Windows teilen …:** der Teilen-Dialog von Windows (WhatsApp, Outlook, Teams, Nearby Sharing), wenn der Browser Dateien teilen kann;
  * Link für Kollegen kopieren, Herunterladen.
  Das Programm versendet nichts selbst. Konten mit Leserechten dürfen drucken und Entwürfe erstellen.

## Listen bei 1280 px

Eine Liste, die seitwärts scrollen müsste, setzt zuerst Namen etwas früher um und rückt die Zellen enger (`table-tight`), wenn das nicht reicht, noch etwas enger (`table-tighter`); Listen, die passen, bleiben unverändert. Lange zusammengesetzte Wörter trennen an Silben statt in die Nachbarspalte zu laufen. In den Verträgen steht das Ende unter dem Beginn („Laufzeit“); die Währung der Portfolios ist ausgeblendet. Keine Liste scrollt bei 1280, 1366, 1440 oder 1920 px seitwärts.
