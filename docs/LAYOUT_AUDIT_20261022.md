# Frontend- und Layout-Audit (Runde 13, 21./22.10.2026)

Geprüft wurden alle 58 Seiten (Listen, Detailseiten, Einstellungen) mit den Daten der Testversion in fünf Breiten (1440, 1280, 1024, 768 und 390 px) sowie die wichtigsten Seiten im dunklen Design. Ein Skript hat je Seite gemessen: seitlicher Überlauf der Seite und einzelner Elemente, abgeschnittene Texte, umbrechende Kurztexte, sich überlappende Bedienelemente, Größe der Touch-Ziele am Handy, Beschriftung von Feldern und Knöpfen, Bilder ohne Alternativtext, Schriftgrößen, Kontrast nach WCAG AA (4,5:1), Überschriftenstruktur, Konsolenfehler und fehlgeschlagene Anfragen. Dazu kamen Bildschirmfotos aller Seiten. Außerdem wurde auf 27 Listen das „Neu“-Formular geöffnet, am Desktop und am Handy: Passt es in den Bildschirm, scrollt es, liegt der Fokus darin, schließt Escape und kommt der Fokus zurück?

Ohne Befund blieben: Konsolenfehler, fehlgeschlagene Anfragen, unbeschriftete Felder oder Knöpfe, Bilder ohne Alternativtext und die Überschriftenstruktur (je Seite eine sichtbare Hauptüberschrift). Alle Formulare passen in den Bildschirm, scrollen bei Bedarf, sind beschriftet, beginnen im ersten Feld und schließen mit Escape.

## Behoben

| ID | Wo | Schwere | Befund | Korrektur |
|---|---|---|---|---|
| L15 | Tabellen am Handy | hoch | Die feststehende Aktionsspalte (Verträge: 9 Symbole, rund 330 px) verdeckte bei 390 px die ganze Tabelle; die Vertragsdaten waren nicht zu sehen. | Unter 640 px scrollt die Aktionsspalte mit den Daten. |
| L14 | Tabellen mit vielen Aktionen | mittel | Bis zu 9 unbeschriftete Symbole je Zeile; Namen und Einheiten brachen drei Zeilen tief um. | Bei mehr als fünf Aktionen bleiben die ersten drei und „Bearbeiten“ in der Zeile, die übrigen und „Löschen“ stehen mit Beschriftung im „⋯“-Menü (Pfeiltasten, Escape, Fokus zurück). |
| L19 | Dunkles Design | hoch | Der aktive Schnellfilter („Alle“) hatte auf allen Listen dunkle Schrift auf dunklem Grund (1,3:1). Ebenso: Benachrichtigungszahl 2,2:1, Testversion-Kennzeichen 2,0:1. | Eigene Farben im dunklen Design. |
| L01 | überall | mittel | Graue Hilfstexte (Kennzahl-Beschriftungen, Hinweise, Platzhalter, Sortierpfeile) hatten 4,39:1 auf Weiß und 4,05:1 auf Grau. | Farbe minimal dunkler: 5,27:1 bzw. 4,85:1. |
| L18 | Status-Kennzeichen | mittel | „Bezahlt“, „Aktiv“, „Überfällig“ usw. bei 11 px: Grün 3,58, Rot 4,41, Blau 3,54, Gelb 3,07, Grau 4,39. | Eine Stufe dunkler, jetzt alle ≥ 4,84:1. |
| L17 | Formulare | mittel | Nach dem Schließen eines Neu- oder Bearbeiten-Formulars sprang der Fokus an den Seitenanfang statt zurück auf den auslösenden Knopf (WCAG 2.4.3). Die übrigen Dialoge machten es schon richtig. | Der Fokus kehrt zum auslösenden Knopf zurück. |
| L09 | Kautionen ≤ 1024 px | mittel | Die ganze Seite ließ sich 144 px seitlich verschieben: Ein Screenreader-Text in der Tabelle entkam dem Scrollbereich. | Der Scrollbereich umschließt ihn jetzt. |
| L12 | Tabellen | mittel | Vertrags- und Rechnungsnummern brachen am Bindestrich um („MV-2023-“ / „046“); in der Dokumentenliste blieb vom Vertrag nur „MV-2022-…“. | Ein einzelnes Wort bis 24 Zeichen bricht nicht mehr um. |
| L13 | Tabellen | mittel | Bei zweizeiligen Überschriften rechtsbündiger Spalten stand der Sortierpfeil verwaist am linken Rand und wirkte wie eine eigene, leere Spalte. | Der Pfeil steht direkt vor der Überschrift. |
| L03 | Rechnungen | mittel | Die Erklärung zum Zahlungsstand machte jede Zeile 160 px hoch (7 Zeilen Text). | Zwei Zeilen, der ganze Text beim Darüberfahren. |
| L04 | Seitenleiste | mittel | Der aktive Menüpunkt einer langen, geöffneten Gruppe lag unter der Fußleiste (z. B. „Rechnungen“ bei 900 px Höhe). | Er wird in den sichtbaren Bereich gerollt. |
| L05 | Ladezeit | niedrig | Der Benachrichtigungs-Eingang war zugleich nachzuladen und fest eingebunden (Build-Warnung); das Nachladen brachte nichts. | Einheitlich fest eingebunden. |
| L06 | Kennzahlen | niedrig | Der Pfeil „↗“ brach allein in eine neue Zeile („Zahlungsstand ungeklärt“). | Er bleibt beim letzten Wort. |
| L10, L11 | Objektakte | niedrig | Einheiten-Bezeichnungen („1. OG links“) brachen ungleich um; „Ansehen“ unter „Letzte Dokumente“ war ein breiter Block. | Mindestbreite für die Bezeichnung; der Knopf hat seine natürliche Breite. |
| L16 | Dokumentseite am Handy | niedrig | Das Formular „Neue Fassung hochladen“ war 6 px breiter als die Karte. | Es passt sich der Kartenbreite an. |

## Offen oder bewusst so

- **L07 Namen in Tabellen** brechen in schmalen Spalten zweizeilig um. Das ist lesbar und spart Breite; kein Eingriff.
- **Kleine Schrift (11 px)** für Kennzeichen, Abschnittsüberschriften der Seitenleiste und Tastenkürzel: Nach WCAG gibt es keine Mindestgröße. Mit den neuen Farben ist der Kontrast ausreichend.
- **Tour-Angebot:** Es erscheint, bis „Später“ oder „Tour starten“ gewählt ist. Das ist gewollt.
- **Datumsfelder:** Die Anzeige im Browserformat (z. B. „10/21/2026“) kommt im Testbrowser von dessen Spracheinstellung; ein deutsches Windows zeigt das deutsche Format.
- **Trennstrich „/“** in der Pfadanzeige des dunklen Designs (1,5:1) ist reine Dekoration.
