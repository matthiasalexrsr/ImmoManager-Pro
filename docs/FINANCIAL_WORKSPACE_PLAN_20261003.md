# D3 – Zahlungsübersicht als nutzbarer Finanzarbeitsplatz

Basis `114e01a`, anschließend kleine eigene Sourcecommits. Der freigegebene
Gesamtplan bleibt verbindlich; diese Oberfläche ist der erste Zahlungsbereich,
keine vorweggenommene Fertigmeldung für Periodenergebnis oder Vertragsprognose.

## Bedienablauf

Neue Navigation „Finanzauswertungen“ unter Finanzen. Zeitraum und Stichtag,
Portfolio, Immobilien und optional Einheit/Konto ausdrücklich auswählen.
Filterentwurf getrennt von angewendeter Auswahl halten: Datumseingaben lösen
keine Zwischenberichte mit unvollständigem Zeitraum aus. Ausgewählte Namen
werden über begrenzte, suchbare Referenzseiten aufgelöst; ein großer Bestand
darf Auswahloptionen nicht abschneiden. Bestehende Referenzdienste um die
konkreten Konten-/Portfolioauswahlen und kompatible Portfoliofilter ergänzen.

Bestätigte Buchungen sind die Standardgrundlage. Eine ausdrücklich wählbare
Bestandsansicht erklärt unbestätigte Buchungen. Ausschlüsse nach Status und
Stichtag bleiben mit Grund in der Belegübersicht nachvollziehbar. Keine Summe
vermischt Forderungsstand, Rechnungsbetrag oder eine bereits zugeordnete
Zahlungsquittung mit der Bankbuchung.

## Darstellung und Zustände

- Einnahmen, Ausgaben und Saldo in ruhigen Kennzahlkarten; Währung immer EUR.
- Monats-/Kostenarten-/Objektsicht aus denselben Gesamtsummen, jede Summe führt
  in die passende Quellbelegauswahl. Kosten ohne Einheit bleiben erkennbar.
- Dezimalstrings verlustfrei mit ganzzahligen Centwerten formatieren. Diagramme
  skalieren relative Centverhältnisse; kein Float dient als maßgeblicher Betrag.
- Separate Belegseiten: Cursor und Quellenhash, vollständige CSV unabhängig von
  sichtbarer Seite. Filter-/Benutzerwechsel entwerten alte Seiten sofort.
- Ladefehler, ungültige Antwort, leerer Bestand und Quellenänderung werden
  getrennt angezeigt. Fehler zeigen keine Nullsumme; Filter bleiben für eine
  erneute Abfrage erhalten. Alte private Antworten werden synchron verborgen,
  ausstehende Anfragen und Exporte abgebrochen.
- Seitennavigation mit fokussierbaren Vor-/Zurückaktionen, responsive
  Formular-/Kartenansicht bei 320/360/1440; breite Belegtabelle separat scrollbar.

## Folgepflichten

XLSX und geprüfte Dokumentausgabe, Vorperiodenvergleich, dauerhafte große
Berichtsläufe, wirtschaftliches Periodenergebnis, vertragliche Prognose sowie
alle weiteren D-Fachprozesse folgen auf die geprüfte Grundlage. Bestehende
Dashboard-Aufrufer bleiben erreichbar und werden danach auf gezielte
vollständige Kennzahlendienste überführt.

## Prüfung

Echte HTTP-Finanz-/Referenzfilter, Rechtewechsel, letzte Auswahlseiten und
Portfolio-/Einheitskonflikte. UI: exakte große/negative Beträge, Filterentwurf,
erhaltene Fehlereingaben, gleicher Cursorretry, Quellenänderung, Benutzerwechsel
und vollständiger Export. Tatsächlicher Edge/SQLite-Browser mit verschiedenen
Objekten, Kosten ohne Einheit, mehrseitigen Belegen und drei Bildschirmbreiten.
