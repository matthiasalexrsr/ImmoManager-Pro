# Prüfung der Rechen- und Buchungslogik (Runde 12, 21.10.2026)

Geprüft wurde der Stand `0c6d633` (nach Codex' Prüfung von Bankimport, Zahlungszuordnung, Mahnwesen und Kautionen): Geld und Rundung, Mietsoll, Zahlungszuordnung und Mieterkonto, Nebenkostenabrechnung, Kaution, Mahnwesen, Berichte und Steuer, Mieterhöhung und Indexmiete, Rechnungsprüfung, Objektverträge und SEPA. Jeder behobene Befund hat einen Regressionstest, der ohne die Korrektur fehlschlägt.

## Behoben

| ID | Bereich | Schwere | Befund | Korrektur |
|---|---|---|---|---|
| R12-01 | Mietsoll | mittel | Die erste Miete war am 3. des Einzugsmonats fällig, auch bei Einzug am 15.: vor Vertragsbeginn „überfällig“, mit Mahnstufe, Zinsen und Altersstruktur. | Fälligkeit wird ab dem Einzugstag gezählt (`lease_engine._due_date`). |
| R12-02 | Mietsoll | mittel | Eine Mietänderung zur Monatsmitte (ein Mietstand im Mietverlauf ab 15.03.; Mietanpassungen gelten nur ab Monatsersten) galt erst ab dem Folgemonat; der März wurde voll zur alten Miete berechnet (bei +100 € 54,84 € zu wenig). Die Nebenkostenabrechnung rechnete die Vorauszahlungen dagegen schon tagesgenau – Mieterkonto und Abrechnung passten nicht zusammen. | Jeder Tag trägt die an ihm gültige Miete (`_rent_segments`), gerundet je Bestandteil einmal pro Monat. |
| R12-04 | Mietsoll | mittel | Fälligkeit immer am 3. Kalendertag. § 556b Abs. 1 BGB: bis zum dritten Werktag; Samstag zählt dafür nicht (BGH, 13.07.2010, VIII ZR 291/09). Überfälligkeit, Mahnstufe 1 und Verzugszinsen begannen bis zu drei Tage zu früh. | `domain/calendar_days.rent_due_date`: Montag bis Freitag ohne bundesweite Feiertage. Ein fester Tag (`due_day`) bleibt möglich, aber nie vor dem Einzug. |
| R12-05 | Mahnwesen | mittel | Gewerbemiete wurde mit dem Verbraucherzins (+5 Punkte) verzinst; § 288 Abs. 2 BGB sieht +9 Punkte vor. | Einheit vom Typ „Gewerbe“: +9 Punkte, der Hinweis im Schreiben nennt § 288 Abs. 2. Die 40-€-Pauschale (§ 288 Abs. 5) wird bewusst nicht erhoben. |
| R12-06 | Zahlungszuordnung | mittel | Eine Zahlung außerhalb der Vertragslaufzeit (erste Miete vor dem Einzug, Rückstand nach dem Auszug) blieb unzugeordnet, auch wenn der Mieter nur einen Vertrag hat (Bankimport setzt keine Einheit). Der Rückstand blieb offen und wurde weiter gemahnt. | Regel 2 der automatischen Zuordnung: läuft kein Vertrag und hat der Mieter genau einen, geht die Zahlung an ihn. |
| R12-08 | Nebenkosten | hoch | „Forderungen erzeugen“ legte Nachzahlungen auch nach Ablauf der Abrechnungsfrist an – auch bei Korrekturen zulasten des Mieters. Die Vorschau warnte nur; die Forderung wurde gemahnt und verzinst, obwohl sie nach § 556 Abs. 3 S. 3 BGB ausgeschlossen ist. | Nachzahlungen einer Wohnung, deren Abrechnung nach der Frist zugeht (nicht zugestellt: frühestens heute), werden nicht angelegt und in der Antwort und im Hinweis genannt; Guthaben immer. `late_not_attributable=true`, wenn der Vermieter die Verspätung nicht zu vertreten hat. Gewerbe ist ausgenommen. |
| R12-10 | Nebenkosten | niedrig | Fehlte beim Mieterwechsel nur eine Zwischenablesung, wurde ein Zeitraum gemessen und die übrigen zusätzlich nach Tagen vom Jahresverbrauch geschätzt: die Einheit zählte z. B. 85,34 statt 100 m³. | Ungemessene Zeiträume teilen sich nach Tagen, was die gemessenen vom Jahresverbrauch übrig lassen. |
| R12-11 | Nebenkosten | niedrig | Abrechnungsfrist bei einem Zeitraum bis zur Monatsmitte (15.03.) bis Monatsende statt 15.03. des Folgejahres. | §§ 187, 188 BGB: derselbe Tag ein Jahr später; Monatsende bleibt Monatsende. |
| R12-13 | Kaution | niedrig | Kautionsraten 2 und 3 waren am 3. Kalendertag fällig; § 551 Abs. 2 BGB: zusammen mit der Miete. | Fälligkeit wie die Miete (dritter Werktag). |

## Offen oder zur Entscheidung

> Stand 22.10.2026: alle Punkte entschieden und umgesetzt (R12-09 bleibt beobachtet), siehe [IMPROVEMENTS_20261022.md](IMPROVEMENTS_20261022.md).

| ID | Bereich | Schwere | Befund | Vorschlag |
|---|---|---|---|---|
| R12-19 | Nebenkosten | mittel | Forderungen entstehen auch aus noch nicht zugestellten Abrechnungen (Status „finalisiert“) und sind 30 Tage ab Erzeugung fällig, nicht ab Zugang; eine Mahnung ist möglich, bevor der Mieter die Abrechnung hat. | Fälligkeit ab Zustellvermerk; ohne Vermerk nur mit Bestätigung. |
| R12-20 | Mieterkonto | mittel | Der Saldo des Mieterkontos enthält nur die Miete; gespeicherte Forderungen (Nachzahlung, Guthaben, Gebühren) stehen getrennt unter „Forderungen & Guthaben“. Eine Zahlung auf eine Nachzahlung wird automatisch als Miete gutgeschrieben: Das Mietkonto zeigt ein Guthaben, die Forderung bleibt offen, bis der Ausgleich von Hand gebucht ist. Das Mahnwesen verrechnet dagegen alles nach § 366 BGB. | Entscheidung: ein Konto mit allen Forderungen oder Vorschlag „Ausgleich buchen“. |
| R12-03 | Mietsoll | niedrig | Beginnt der Mietverlauf eines Vertrags nach dem Vertragsbeginn, haben die Tage davor kein Soll. Über die Oberfläche kaum erreichbar (erster Stand = Vertragsbeginn, folgt ihm bei Änderung). | Beobachten; ggf. Prüfliste. |
| R12-07 | Nebenkosten | mittel | Heizkosten nach HeizkostenV § 7 (50–70 % nach Verbrauch, Rest nach Fläche) werden nicht selbst aufgeteilt; ohne händische Aufteilung in zwei Positionen droht das Kürzungsrecht von 15 % (§ 12). | Entscheidung: eigene Position „Heizkosten“ mit Verbrauchsanteil und Prüfung. |
| R12-09 | Nebenkosten | niedrig | Abrechnung summiert die Soll-Vorauszahlungen ungerundet, das Mieterkonto rundet je Monat: bei Einzug und Auszug im selben Jahr bis 1 ct Unterschied. | Beobachten. |
| R12-12 | Nebenkosten | Hinweis | Die Abrechnung zieht Soll-Vorauszahlungen ab; offene Vorauszahlungen bleiben als Miete im Mieterkonto. Die Summe stimmt; rechtlich ist nach Abrechnungsreife nur noch der Saldo einforderbar (BGH VIII ZR 271/10). | Hinweis im Abrechnungsschreiben erwägen. |
| R12-14 | Steuer | mittel | Die Jahresauswertung folgt streng dem Buchungsdatum; die Zehn-Tage-Regel des § 11 Abs. 1 S. 2 EStG (z. B. Januarmiete am 29.12., Grundsteuer, Darlehensraten) wird nicht angewandt; eine Ausnahme kann eine Buchung nur ausschließen, nicht ins andere Jahr übernehmen. | Entscheidung: Jahreszuordnung je Buchung. |
| R12-15 | Berichte | niedrig | Periodenergebnis: von Hand angelegte Forderungen an Mieter (Schaden, Schlüssel) fehlen als Ertrag. Sie können eine Monatsmiete doppeln (siehe Mahnwesen), deshalb nicht einfach addiert. | Entscheidung: Art „sonstige Forderung“ kennzeichnen und dann zählen. |
| R12-16 | Mieterhöhung | niedrig | Die § 558-Prüfung zählt für Sperr- und Wartefrist jede Kaltmietänderung, auch Modernisierungserhöhungen (§ 559) und Korrekturen; § 558 Abs. 1 S. 3 BGB nimmt §§ 559–560 aus. Der Mietverlauf kennt die Art der Änderung nicht. | Art der Mietänderung im Mietverlauf erfassen. |
| R12-17 | Mietsoll | niedrig | Ein Vertrag ohne gespeicherten Mietverlauf (nur ältere Daten ohne Migration) rechnet rückwirkend mit der aktuellen Miete der Einheit. Die Migration hat die Verläufe angelegt. | Beobachten. |
| R12-18 | Mahnwesen | Hinweis | Voreingestellte Mahngebühren 2,50 / 5,00 / 5,00 €: bei Verbrauchern sind nur tatsächliche Kosten ersatzfähig; 5 € werden oft beanstandet. | In den Einstellungen anpassbar; Standard ggf. senken. |

Regionale Feiertage zählen für den dritten Werktag nicht (nur die neun bundesweiten); in Ländern mit z. B. Heilige Drei Könige gilt eine Miete dann einen Tag zu früh als fällig.

## Geprüft und in Ordnung

- **Geld:** `Decimal` mit kaufmännischer Rundung, Cent-Aufteilung nach größtem Rest (keine Partei mehr als 1 ct von ihrem Anteil), Rundung je Bestandteil einmal pro Monat.
- **Mieterkonto:** Zahlungen nach Buchungstag auf die älteste Forderung (§ 366 Abs. 2 BGB), am selben Tag Kosten vor Zinsen vor Hauptforderung (§ 367 Abs. 1); Stornos mindern genau ihre Zahlung, Rücklastschriften über dem Gezahlten werden zur eigenen Forderung; Übernahme mit Saldo; Kautions- und Ausgleichsanteile einer Buchung zählen nicht als Miete.
- **Verzugszinsen:** ab dem Tag nach Fälligkeit (Miete) bzw. nach der Frist des ersten Schreibens (Nachzahlung), je Abschnitt mit gleichem Betrag und Basiszins exakt, einmal je Forderung gerundet, keine Zinsen auf Kosten (§ 289), kein Tag doppelt.
- **Nebenkosten:** Nutzungszeiten tagesgenau mit Leerstand beim Vermieter, Personentage, Zählerwechsel mit Lückenprüfung, Einheitenumrechnung nur mit exaktem Faktor, Korrektur bucht nur die Differenz.
- **Kaution:** höchstens drei Nettokaltmieten, Zinsen tagesgenau (365/366) mit jährlicher Zinseszins-Gutschrift, Abrechnung ohne doppelte Ansprüche.
- **Mieterhöhung/Index:** Zustimmungsfrist und Wirksamkeit (§ 558b), Kappungsgrenze auf Basis der Miete drei Jahre vor Wirksamwerden, Indexmiete ab dem übernächsten Monat (§ 557b Abs. 3), ein Jahr unverändert; Kündigungsfrist § 573c mit Samstag als Werktag.
- **Rechnungsprüfung:** Netto + Steuer = Brutto je Steuersatz mit 1-ct-Toleranz, Skonto nur bei fristgerechter Zahlung im Skontorahmen.
