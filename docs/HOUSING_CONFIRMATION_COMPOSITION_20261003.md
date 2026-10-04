# Wohnungsgeberbestätigung – gemeinsame Browserabnahme

Backend/PDF/Accountfence aus `c253eaa`, Frontend aus `3b89187` sind verbunden.
Diese Prüfung betrifft Wohnungsgeberbestätigung; Paket F verlangt zusätzlich
weiterhin den geführten Übergabeablauf. Vorschau bleibt Release126.

## Im Browser gefundene und behobene Fehler

- Ein bereits geöffnetes Original-PDF wurde als blockiert gemeldet: der
  verwendete `noopener`-Aufruf liefert auch bei erfolgreichem Öffnen keine
  Fensterreferenz. Jetzt wird beim bewussten Klick ein leeres Fenster reserviert,
  dessen `opener` sofort entfernt. Erst der geschützte geprüfte PDF-Download
  ersetzt dessen Inhalt. Fehler oder verlorener Zugriff schließen das Fenster.
- Lange Inhalte konnten den schmalen Dialog verbreitern. Begrenzte Gridspalte,
  umbrechende Überschrift/Aktionen und konsistente Formularfelder beseitigen
  den tatsächlich gemessenen Überlauf. Einzugsdatum hat ein kurzes Feldlabel
  und separat zugeordneten Hilfetext.
- Eine echte geschützte PDF-Vorschau kann jetzt vor Freigabe geöffnet werden.
  Der bestehende `preview-pdf`-Backendpfad wird verwendet; eine Vorschau erzeugt
  kein Archivoriginal. Eingabe-/Quelldatenänderung entwertet die Vorschau.

## Tatsächliche Nachweise

- Reale Edge-/SQLite-App mit vollständiger damals aktueller Migration:
  **1 komplexer Browserfall bestanden,21.0s**. 45 Personen mit langen Namen,
  manuelles tatsächliches Einzugsdatum abweichend von Vertragsbeginn,
  PDF-Vorschau ohne Archivoriginal, vollständig gespeicherter POST mit verlorener
  Antwort, unveränderter Retry und genau ein Original, anonymer PDF-Zugriff401,
  geschütztes geöffnetes PDF, Korrekturbezug zu genau Dokument+Version und
  bytegleich erhaltenes früheres Original.
- 1440/360/320 Pixel geprüft, Dialog besitzt keine horizontale Überbreite.
  Desktop-/320-Bilder nach den Korrekturen visuell kontrolliert. Die Belegliste
  zeigt beide Fassungen und den Korrekturbezug; lange Personenlisten bleiben
  innerhalb des Dialogs vertikal erreichbar.
- Direkter UI-/Client-/Model-/Command-Gate: **20 passed**,9.35s. Zusätzlicher
  Gegenbeleg reserviert das Fenster vor verzögerter Antwort und prüft, dass
  Rechtefehler es ohne private Navigation schließen.
- ESLint für Housing, Client, gemeinsamen API-Baustein und Browserfall grün.
  Der echte Browserrunner baut den Produktionsfrontendstand vor dem Test.

Die API-/PDF-/SQL-Konkurrenzprüfungen des früheren Backendhandoffs bleiben
eigene belegte Gates. Ein kompletter Gesamtstand mit h2, sämtlichen neuen
Recoveryfamilien und allen anderen Produktpaketen ist damit noch nicht freigegeben.
Allgemeine mehrsprachige PDF-Schrift-/Layoutgrenzen und die noch offene
geführte Übergabe werden nicht durch einen grünen Browserfall ersetzt.
