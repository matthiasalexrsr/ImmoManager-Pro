# Fachpaket 4 – Messabdeckung beim Zählerwechsel (Teillieferung)

**Stand: 16.10.2026; Entwicklerzweig `pro/stage-billing-coverage-20261016`.**

Dieses isolierte Arbeitspaket setzt den vorhandenen Zähler-/
Betriebskostenrechner unverändert fort. Alle Tests verwenden
ausschließlich eigene synthetische Immobilien, Einheiten,
Verträge und Zähler. Bestehende Installationen, Hauptcheckout
und andere Fachpakete bleiben unangetastet.

## Fehlende fachliche Invariante nach dem Handover

Bislang summierte `_consumption_shares` jeden in-service-Zähler
einer Einheit. Wurde der alte Zähler am 30.06. ausgebaut und der neue
erst am 03.07. eingebaut, konnten trotzdem vollständig vorhandene
erste/letzte Ablesungen zu einem scheinbar nahtlosen
Jahresverbrauch aufsummiert werden. **Ungemessene Tage wurden
nicht sichtbar.**

Jetzt prüft dieselbe Berechnung, die auch die Preflight- und
Finalisierungsentscheidung versorgt, die taggenauen
Dienstintervalle jedes ausgewählten Zählertyps getrennt je Einheit.
Zwischen nicht nahtlosen Intervallen entstehen
`METER_SERVICE_GAP`-Blocker mit Einheitenbezeichnung,
Zähleridentität und exakt fehlenden Tagen. Überlappende Intervalle
lösen die ausdrückliche Warnung `METER_SERVICE_OVERLAP` aus:
Sie sind ohne bestätigte Ersatz-/Parallelbeziehung **nicht**
eindeutig, werden aber nicht automatisch als Messdefekt erfunden.
Anfangs-/Endstände, Summen, Rechnungen, bestehende PDFs und
Originalbytes werden durch diese reine Preflight-Prüfung
nicht verändert.

### Gegenbeispiele

- Ausgebaut 30.06.2025, eingebaut 03.07.2025:
  **01.07.2025 bis 02.07.2025 fehlen**; Blocker statt
  stiller Summenfreigabe.
- Einbau direkt am 01.07.2025: kein falscher
  `METER_SERVICE_GAP`- oder Überschneidungsalarm.
- Alte und neue Messstelle vom 30.06. bis 03.07. zugleich
  aktiv: `METER_SERVICE_OVERLAP` mit beiden Seriennummern
  und einer Aufforderung zum fachlichen Abgleich.
- Beide Quellwerte bleiben erhalten; der Algorithmus füllt
  keine Werte aus angenommenem Tagesverbrauch auf.

## Prüfnachweise

`artifacts/pro-tests/billing-meter-fixed-memory-88ac33a2ebcb4f42bbba21de8df9874a`:
**52/52 Memorytests** bestanden, 0 Skip.

`artifacts/pro-tests/billing-meter-fixed-sql-64807c1f5b8b4cbeb3ae75cc50b46f70`:
**52/52 SQLitetests** bestanden, 0 Skip.

Die Tests enthalten drei unabhängige neue Intervallgegenproben
und die bestehenden `test_billing_preflight.py`- und
`test_billing_regression.py`-Fachorakel. Die gezielten
ursprünglichen drei Tests hatten zunächst 2/3 Grün wegen
eines falschen *Testzugriffs* auf eine nicht vorhandene
`BillingPreflightResult.issues`-Eigenschaft; das
Produktproblem lag dabei in der fehlenden Gap-Prüfung und
wurde nicht durch schwächere Assertions verdeckt.

## Was Fachpaket 4 weiterhin benötigt

1. Eindeutige persistente, versionierte Erklärung der
   Beziehung „Zähler ersetzt Zähler“ **oder**
   „Messstellen laufen parallel“. Die neue Überlappungswarnung
   erkennt den Konflikt, sie löst ihn noch nicht durch
   eine authentisierte Entscheidung.
2. Fachlich begrenzte, gültigkeitsbezogene Gasvolumen-zu-Energie-
   Faktoren (Brennwert/Zustandszahl) und HKV-Bewertungsprofile,
   niemals durch still angenommene exakte Einheitengleichheit.
3. Revisionsgesicherte Bewohnerkorrektur, begründete
   Widerspruchszurückweisung sowie eine sauber nachgeführte
   Abrechnungsentscheidung ohne Änderung alter Originale.
4. Native PostgreSQL-/Browser-, komplette Rechte- und
   Vollrestoreprüfung im **endgültigen Gesamtintegrationszweig**.

Dieses Teilpaket beansprucht weder eine vollständige
Betriebskosten-/Eigentümerwechselabnahme noch eine
Auslieferungsfreigabe.
