# Finanzbasis – konkreter erster Umsetzungsschritt

Root-Basis `eafe874`, kein eigenes Schema und keine zweite Zahlungsdatenbank.
PaketD bleibt vollständig in Arbeit: Zahlungsübersicht, Periodenergebnis,
vertragliche Prognose, Kaution, Mahnung, Rechnungsprüfung und Belegexporte.

## D1: gemeinsame, vollständige Zahlungsquelle

- Neue streng validierte Filter: Zeitraum einschließlich Enddatum, Portfolio,
  Immobilienauswahl, Einheit, Konto und ausdrücklich gekennzeichnete
  Buchungsstatus. Einheit/Immobilie/Portfolio-Kombinationen prüfen.
- Alle berechtigten Buchungen ohne Bestandslimit aus begrenzten Projektionen
  lesen. SQL verwendet einen konsistenten Lesesnapshot; Memory eine gemeinsame
  Datensperre und begrenzte Auswahl. Keine Rechnungs-/Forderungssumme als Zahlung
  hinzufügen: die tatsächliche Buchung ist genau eine Zahlungsquelle.
- Neue Zahlungsberichte verwenden standardmäßig `confirmed`, entsprechend
  der bereits geprüften Steuer-Zahlungsbasis. `open`, `matched`, `booked` sind
  unbestätigte gespeicherte Buchungsquellen und werden gesondert ausgewiesen.
  Eine ausdrücklich gewählte Bestandsansicht darf sie mitzählen, bezeichnet
  sich dann als Buchungsbestand. Stornierte/ungültige Quellen getrennt als
  prüfbare Ausschlüsse führen. Kein Status erzeugt eine zusätzliche Zahlung.
- Geld als ganzzahlige Centwerte addieren und verlustfrei als Dezimalstrings
  mit `currency=EUR` liefern. Ungültige Beträge ergeben einen behebbaren
  Quellenfehler, niemals eine Nullsumme. Bestehende Numeric(12,2)-Speichergrenzen
  werden offengelegt; eine spätere Geldschema-Migration gehört weiter zum Ziel.
- Dieselben Quellen treiben Gesamt-, Kostenarten-, Monats- und Objekt-/Einheits-
  Summen sowie paginierte Quellbelege und vollständigen CSV-Export. Objektkosten
  ohne Einheit bleiben als eigene Zuordnung sichtbar; kein erfundener Umlagesatz.
- Reproduzierbarer Quellenhash bindet Filter und Quellenzustand. Belegseiten
  erkennen geänderte Quellen und verlangen ein verständliches Neuladen. Nach
  Rechte-/Objektänderung private Inhalte vor Veröffentlichung erneut prüfen.

## D2: bestehende Finanzwege korrigieren

Die alten `/reports/finance` und `/reports/cashflow` behalten ihre numerischen
Felder für bestehende Dashboard-Aufrufer und nutzen denselben neuen Kern.
Neue verlustfreie Schnittstellen transportieren Decimalstrings. CSV und JSON
kommen aus demselben berechneten Ergebnis. PDF-Folgearbeit vermeidet das alte
Abschneiden langer Zeilen und wird gesondert visuell abgenommen.

Die historische Durchschnittsprognose wird ausdrücklich als Szenario geführt:
fester Stichtag, genau12 vollständig vergangene Kalendermonate einschließlich
Nullmonaten, keine zukünftigen/stornierten Buchungen, eindeutig ausgewählte
Anfangsgrundlage. Sie ist kein Ersatz für die geforderte Vertrags-/Forderungs-
Prognose. Undatierte Kontoanfänge dürfen keine behauptete historische
Liquidität erzeugen; ein Szenario benötigt eine ausdrücklich gewählte Grundlage.

## D3 und weitere Verpflichtungen

Ein eigener Finanzarbeitsplatz stellt Zeitraum, Portfolio, Objekt und Einheit
verständlich ein und verbindet Summen mit Belegen, Monatsvergleich und Export.
Leistungszeiträume, Abschreibung/Finanzierung, Verträge, Budgets, Kaution und
Mahnungen erhalten danach eigene fachliche Originale/Versionen und gemeinsame
Transaktions-/Berechtigungs-/Wiederherstellungsprüfung. Erst diese Folgearbeit
erfüllt PaketD insgesamt; D1/D2 werden nicht als vollständige Abnahme ausgegeben.

## Prüfungen

Bekannte Cent- und Nullmonatsgegenbeispiele, Zeitraum-/Objekt-/Einheitssummen,
unzugeordnete Kosten, tatsächliche Zahlung mit Bankbezug ohne Doppelzählung,
Storno, Quelle geändert, Rechteentzug, vollständige letzte Belegseite und CSV.
Memory, SQLite und echte PostgreSQL-Verbindungen; 100.000 und1Million Quellen
im Langzeitgate mit dokumentierter Laufzeit/Speicher. Kleine Bildschirmbreiten,
Tastatur, erhaltene Filter und Fehler-/Leerzustände im tatsächlichen Browser.
