# Eigentümer und Eigentumsanteile (Runden 16 und 17, 22.10.2026)

Objekte und Einheiten können verschiedenen Eigentümern gehören, auch mehreren zu Anteilen. Diese Anteile können sich mit der Zeit ändern, etwa durch Verkauf, Schenkung, Erbschaft oder Teilung. Berichte, Budgets, Startseite, Steuerauswertung und Prüfliste rechnen jeden Betrag mit den Anteilen der Eigentümer **an dem Tag, zu dem er gehört**. Die Teile aller Eigentümer ergeben dabei immer auf den Cent das Ganze.

Code: `backend/services/ownership.py` (Regeln, Aufteilung, Wechsel, Verlauf), `backend/routers/ownership.py` (`/api/v1/ownership-shares`), Oberfläche im Objekt-Reiter „Eigentümer“ (`frontend/src/features/ownership/PropertyOwnership.jsx`).

## Das Modell

- **Eigentümer** ist ein Kontakt im Adressbuch mit dem Typ „Eigentümer“. Ein eigenes Personenverzeichnis gibt es nicht.
- Ein **Eigentumsanteil** besteht aus:
  - einem Eigentümer und einem Objekt, optional einer Einheit dieses Objekts;
  - einem Prozentsatz (größer 0 bis 100, bis zu vier Nachkommastellen; drei Erben zu je einem Drittel: 33,3334 + 33,3333 + 33,3333 %);
  - optional „Gilt ab“ und „Gilt bis“, beide Tage eingeschlossen. Ohne Angabe gilt der Anteil seit jeher bzw. bis auf Weiteres.
- An einem Tag ergeben die Anteile an einem Objekt oder einer Einheit **höchstens 100 %**. Der Rest gehört keinem erfassten Eigentümer („Ohne Eigentümer“); die Prüfliste nennt ihn.
- Derselbe Eigentümer kann an derselben Einheit nicht zwei sich überschneidende Anteile haben.
- Eine **Buchung** kann einen Eigentümer nennen. Sie gehört dann ihm allein, z. B. eine Entnahme von Linda oder eine Rechnung, die nur Matthias trägt.
- **Eigentümerwechsel** stehen in einem eigenen Journal (`ownership_transfers`). Es hält Art, Stichtag, Abgebenden, übertragenen Teil, Empfänger, Notiz und wer den Wechsel erfasst hat.

### Welche Anteile ein Betrag nimmt

| Betrag | Aufteilung |
|---|---|
| Buchung mit Eigentümer | ganz dieser Eigentümer |
| Betrag einer Einheit (Miete, Reparatur WE 3, Forderung, Rechnung) | die Anteile an der Einheit; hat sie keine eigenen, die Anteile am Objekt |
| Betrag des ganzen Objekts (Gebäudeversicherung, Grundsteuer) | die Anteile am Objekt. Ohne solche Anteile: die Eigentümer der Einheiten nach Wohnfläche. Fehlt bei einer Einheit die Fläche, zählt jede Einheit gleich. |
| Betrag ohne Objekt (Kontoführung) | „Ohne Eigentümer“ |

Beispiel: Haus mit WE 1 (50 m², Matthias), WE 2 (70 m², Linda), WE 3 (80 m², je 50 %). Die Gebäudeversicherung von 200 € teilt sich nach Fläche: Matthias 50 + 40 = 90 m² (45 %), Linda 70 + 40 = 110 m² (55 %), also 90 € und 110 €.

### Auf den Cent

Jeder Betrag wird in einem Schritt auf alle Eigentümer verteilt, und zwar nach dem Verfahren des größten Rests (`allocate_cents`, wie in der Nebenkostenabrechnung). 100 € zu den drei Dritteln oben ergeben 33,34 + 33,33 + 33,33 €. Deshalb ergibt jeder Bericht je Eigentümer, über alle Eigentümer und „Ohne Eigentümer“ zusammengezählt, genau den Bericht ohne Eigentümerfilter. Der Bericht „Ergebnis je Eigentümer“ prüft das bei jedem Aufruf.

## Eigentümerwechsel

„Eigentümerwechsel erfassen“ im Reiter „Eigentümer“ bildet einen Wechsel in einem Schritt ab:

- **Art:** Kauf, Schenkung, Erbschaft, Teilung, Verkauf an Dritte, sonstiger Wechsel.
- **Wirksam ab:** der Stichtag (Übergang von Nutzen und Lasten).
- **Bisheriger Eigentümer** und der **übertragene Teil seines Anteils** (Standard 100 %).
- **Gilt für:** die gewählte Einheit, das ganze Objekt (die Anteile am Objekt) oder „Alles, was er an diesem Objekt hält“ (Objekt und alle Einheiten mit einem Anteil von ihm).
- **Neue Eigentümer** mit ihren Prozenten am übertragenen Teil (zusammen 100 %). Beim Verkauf an Dritte gibt es keinen Empfänger. Der Teil gehört ab dem Stichtag keinem erfassten Eigentümer mehr.

Was dabei geschieht:

1. Der Anteil des Abgebenden endet am Vortag. Gibt er nur einen Teil ab, beginnt am Stichtag ein Anteil über den Rest.
2. Jeder Empfänger bekommt ab dem Stichtag seinen Teil. Hält er an demselben Objekt schon einen Anteil, endet dieser am Vortag, und ab dem Stichtag gibt es einen Anteil über die Summe. Die Notiz nennt Art, Abgebenden und Tag.
3. Die Summe der Anteile bleibt gleich. Der Wechsel kommt ins Journal.
4. Alles geschieht in einer Transaktion. Schlägt ein Teil fehl, bleibt der vorherige Stand vollständig erhalten.

Die Beispiele aus der Anfrage (alle als Tests in `backend/tests/test_ownership_changes.py`):

| Fall | Erfassung | Ergebnis |
|---|---|---|
| Matthias verkauft 100 % an Linda | Kauf, WE 1, ab 16.07.2026, Linda 100 % | bis 15.07. Matthias, ab 16.07. Linda; die Julimiete von 1.000 € teilt sich 483,87 € (15 Tage) / 516,13 € (16 Tage) |
| Sebastian teilt sein Haus 50/50 mit Linda | Teilung, ganzes Objekt, ab 01.04., übertragener Teil 50 %, Linda 100 % | ab 01.04. je 50 %; ein Jahresbudget von 1.000 € ergibt 623,29 € / 376,71 € |
| Sabine und Richard (je 50 %) vererben an Linda | zwei Wechsel „Erbschaft“ am selben Tag, je an Linda | ab 01.09. Linda 100 %; der Verlauf zeigt beide Abschnitte, das Journal beide Erbschaften |
| Richard verkauft an Linda und Matthias (50/50); Matthias hält schon 50 % | Kauf, WE 3, Linda 50 %, Matthias 50 % | Matthias 75 %, Linda 25 % |
| Matthias verschenkt alles an Sebastian | Schenkung, „Alles, was er an diesem Objekt hält“ | WE 1 Sebastian 100 %, WE 3 Linda/Sebastian je 50 % |

Abgelehnt wird mit einem Satz:

- ein Abgebender ohne Anteil am Stichtag. Gehören ihm nur Einheiten, nennt der Hinweis „Alle Anteile am Objekt“.
- ein Wechsel vor einem schon erfassten späteren Wechsel am selben Objekt („Bitte die Wechsel der Reihe nach erfassen“). Sonst würde der Verlauf rückwirkend umgeschrieben.
- ein beteiligter Anteil mit festem Ende;
- Empfänger, die nicht zusammen 100 % ergeben, oder der Abgebende als Empfänger.

**Rückgängig machen** (Runde 17): Der jeweils letzte Wechsel eines Objekts lässt sich im Journal zurücknehmen. Seine neuen Anteile werden gelöscht, beendete Anteile laufen wieder offen weiter, zusammengefasste Anteile kommen zurück. Das Journal behält den Wechsel durchgestrichen mit „rückgängig gemacht am …“. Abgelehnt wird:

- ein früherer Wechsel, solange ein späterer gilt („Bitte zuerst den letzten Wechsel rückgängig machen“);
- ein Wechsel, dessen Anteile seitdem von Hand geändert wurden. Dann bleibt die Korrektur über die Anteile (Bearbeiten/Löschen);
- ein schon zurückgenommener Wechsel.

Wechsel aus der Zeit vor Runde 17 haben keinen Änderungssatz und lassen sich nur über die Anteile korrigieren.

**Stand am** zeigt die Eigentümer an einem beliebigen Tag. **Verlauf** zeigt je Objekt und Einheit die Zeitabschnitte zwischen den Wechseln und darunter das Journal.

## Tagesgenaue Aufteilung

- Ein Betrag eines Tages (Buchung, Rechnung zum Rechnungsdatum, Forderung zur Fälligkeit) folgt den Eigentümern dieses Tages.
- Ein Betrag eines Zeitraums wird nach den Tagen der Eigentümer in diesem Zeitraum geteilt:
  - die Sollmiete je Mietzeile (innerhalb der Vertragslaufzeit);
  - die Monatsanteile einer Nebenkostenabrechnung;
  - eine Rechnung mit Leistungszeitraum, je Monat;
  - ein Budgetjahr.

## Wo die Eigentümer einfließen

| Bereich | Wirkung |
|---|---|
| **Berichte** (Übersicht, Finanzen, Belegung, Altersstruktur, Zahlungen, Periodenergebnis, Instandhaltungskosten, Liquiditätsprognose, PDF) | Filter „Eigentümer“, auch „Ohne Eigentümer“. Jeder Betrag zählt mit dem Teil des Eigentümers. Anzahlen (Objekte, Einheiten, Verträge, Belegung) zählen, woran er heute einen Anteil hat. |
| **Finanzberichte** (Zahlungen, Ergebnis, Prognose, gespeicherte Definitionen) | ebenso; Mieten, Abrechnungen und Rechnungen tagesgenau |
| **Ergebnis je Eigentümer** (`/reports/owner-results`, auch als CSV) | Sollmiete, sonstige Erträge, Kosten, Ergebnis, Entnahmen, Einlagen; eine Zeile je Eigentümer und „Ohne Eigentümer“, zusammen das Gesamtergebnis |
| **Budgets** (Analyse) | Plan und Ist nach den Tagen des Eigentümers im Budgetjahr |
| **Startseite** | Auswahl „Eigentümer“ für die Geldkacheln |
| **Steuer** (Jahresauswertung) | Tabelle „Anteile je Eigentümer“: die Beträge je Eigentümer, Objekt und Zeile der Anlage V (`owner_split`); nur mit erfassten Anteilen |
| **Prüfliste** | „Eigentumsanteile von … unvollständig“, z. B. „WE 4: 100 % ohne Eigentümer“, sobald an einem Objekt Anteile erfasst sind |
| **Buchungen** | Feld „Eigentümer“ (gehört allein ihm); ein Storno übernimmt es. Die Buchungsliste hat die Auswahl „Eigentümer“: nur Buchungen mit seinem Anteil, Spalte „Anteil des Eigentümers“ mit Summe, die Kennzahlen mit seinem Teil (`/bookings?owner_contact_id=`) |
| **Konten** | Feld „Kontoinhaber (Eigentümer)“: Ein Konto, das einem Eigentümer allein gehört, bringt seinen Eröffnungssaldo diesem Eigentümer. „Kontostand je Eigentümer“ teilt die Kontostände nach den Buchungsanteilen (`/accounts/owner-balances`); „Ergebnis je Eigentümer“ nennt den Kontostand zum Periodenende |
| **DATEV-Export** | Auswahl „Eigentümer“: jede Buchung mit dem Anteil dieses Eigentümers, Buchungen ohne seinen Anteil entfallen; Stornos werden gegen den Originalbeleg geprüft. Ohne Auswahl bleiben Export und Wiederholungsschlüssel wie bisher |
| **WISO-Vorbereitung** | der gesicherte Übertragungsbogen zeigt „Je Eigentümer“ die Zeilen mit seinem Anteil; der Download enthält `manual-transfer-worksheet-by-owner.csv`. Die Anteile einer Zeile ergeben centgenau ihren Betrag, sonst gilt die Fassung als beschädigt |
| **Wohnungsgeberbestätigung** | schlägt als Eigentümer die Eigentümer der Wohnung am Vertragsbeginn vor (größter Anteil zuerst), sonst den Eigentümer des Portfolios |
| **Briefe** | Platzhalter `{{eigentuemer.namen}}`: die Eigentümer der Einheit zum Briefdatum, sonst der Eigentümer des Portfolios |
| **Listen und Seiten** | Spalte „Eigentümer“ in den Objekt- und Einheitenlisten (sobald Anteile erfasst sind), Eigentümer auf der Einheitenseite, „Anteile anzeigen“ beim Kontakt mit Links zu Objekt, Einheit und seinen Buchungen |
| **Kontakttyp** | Ein Eigentümer, den Anteile, eigene Buchungen, Wechsel oder Konten nennen, bleibt vom Typ „Eigentümer“; die Meldung nennt, was ihn nennt |
| **DSGVO** | Auskunft und Anonymisierung auch für Kontakte (`/admin/dsgvo/contact/{id}/export` und `/anonymize`): Anteile, Wechsel, Buchungen, Konten, Objektverträge. Die Anteile bleiben (Aufbewahrung) und zählen für den Platzhalternamen |
| **Löschen** | Objekt, Einheit und Kontakt mit Anteilen, Wechseln oder Buchungen mit Eigentümer lassen sich nicht löschen; die Meldung nennt den Grund |
| **Datenexport** | Format 15 mit Anteilen, Wechseln (mit Änderungssatz und Rücknahme), dem Eigentümer der Buchung und dem Kontoinhaber |

Ohne Eigentümerfilter rechnet jeder Bericht genau wie bisher. Der Eröffnungssaldo eines Kontos ohne Kontoinhaber gehört keinem Eigentümer; mit einem Eigentümer im Filter zählt nur der Eröffnungssaldo seiner eigenen Konten, mit „Ohne Eigentümer“ der der Konten ohne Inhaber. Mit einem Objekt oder einer Einheit im Filter bleiben Eröffnungssalden weg.

## Update

- Drei Migrationen: `c9a1b3d5e7f9` (Tabelle `ownership_shares`, Spalte `bookings.owner_contact_id`), `d0b2c4e6f8a1` (Tabelle `ownership_transfers`) und `e1a3c5e7f9b2` (Runde 17: `accounts.owner_contact_id`; `ownership_transfers.changes`, `reverted_at`, `reverted_by`). Alle legen nur neu an und prüfen vorher, ob es die Tabelle oder Spalte schon gibt. Ein Downgrade wird abgelehnt, solange Anteile, Buchungseigentümer, Wechsel, Kontoinhaber oder zurückgenommene Wechsel erfasst sind.
- Ohne erfasste Anteile ändert sich keine Zahl. Gespeicherte Berichtsdefinitionen ohne Eigentümer behalten ihren Prüfwert; Steuerauswertungen ohne Anteile ebenso.
- Exporte haben das Format 15; ältere Versionen lehnen sie ab, ältere Exporte lassen sich weiter einlesen.

## Korrekturen aus Runde 17

- Eine gespeicherte Steuer-Jahresfassung mit Anteilen ließ sich nicht wieder öffnen: Beim Lesen wurde die Prüfsumme ohne die Eigentümeraufteilung nachgerechnet. Jetzt gehört sie dazu.
- Gab es keine Anteile, aber einzelne Buchungen mit Eigentümer, fehlte in der Steueraufteilung der übrige Betrag „Ohne Eigentümer“. Jetzt wird jeder Betrag aufgeteilt, sobald irgendwo ein Eigentümer erfasst ist.

## Grenzen

- Die WISO-Vorbereitung und der DATEV-Export je Eigentümer verteilen nach den erfassten Anteilen. Ob ein Betrag steuerlich so zuzurechnen ist (z. B. gesonderte und einheitliche Feststellung, abweichende Vereinbarungen), prüfen sie nicht; sie ersetzen keine steuerliche Beratung.
- Der Kontostand je Eigentümer teilt jede Buchung nach den Anteilen ihres Tages. Er ist ein rechnerischer Anteil, kein eigenes Bankkonto.
- Rückgängig zu machen ist nur der jeweils letzte Wechsel eines Objekts mit Änderungssatz (ab Runde 17).
- Die DSGVO-Auskunft und -Anonymisierung für Kontakte gibt es über die Programmschnittstelle, wie bei Mietern, noch ohne eigene Schaltfläche.
