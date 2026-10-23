# Aufbewahrungsfristen und Löschsperre für Dokumente

Stand 20. Oktober 2026, Branch `claude/dreamy-gauss-nmaxhn`. Viertes Paket aus der Vorschlagsliste der Runde 8, nach Briefkopf und Briefvorlagen, Ablaufdaten und Volltextsuche.

## Fristen

Jedes Dokument hat eine **Aufbewahrungsklasse**. Wer nichts wählt, bekommt die Klasse, die der Dokumenttyp vorgibt; im Dokumentformular lässt sie sich unter „Aufbewahrung“ ändern.

| Klasse | Frist | Grundlage | Automatisch für |
| --- | --- | --- | --- |
| Buchungsbeleg | 8 Jahre | § 147 Abs. 1 Nr. 4, Abs. 3 AO und § 14b UStG in der Fassung ab 1. Januar 2025 | Rechnung, Handwerkerrechnung, Neben- und Betriebskostenabrechnung, Abrechnungsschreiben, Kautionsabrechnung, Gutschrift, Beleg, TEHA-Original |
| Bücher, Abschlüsse, Steuerunterlagen | 10 Jahre | § 147 Abs. 1 Nr. 1, Abs. 3 AO | Steuerbescheid |
| Geschäftsbrief oder sonstige Unterlage | 6 Jahre | § 147 Abs. 1 Nr. 2, 3, 5, Abs. 3 AO | Mahnung, Mahnschreiben, Brief, Protokoll, Instandhaltungsprotokoll, Wohnungsgeberbestätigung |
| Vertragsunterlage | 3 Jahre nach Vertragsende | regelmäßige Verjährung, §§ 195, 199 BGB (Empfehlung, keine gesetzliche Aufbewahrungsfrist) | Mietvertrag, Kündigung, Übergabeprotokoll, Objektvertrag, Versicherung |
| Dauerhaft | ohne Ende | z. B. Eigentumsnachweis | Grundbuchauszug |
| Keine | – | – | Energieausweis, Sonstiges und alle übrigen Typen |

**Beginn und Ende.** Die Frist beginnt mit dem Schluss des Kalenderjahres, in dem das Dokument entstanden ist (§ 147 Abs. 4 AO); maßgeblich ist das Dokumentdatum, sonst der Tag der Ablage. Sie endet am 31. Dezember nach Ablauf der Jahre, ein am 3. November 2025 datierter Beleg also am 31. Dezember 2033. Bei Vertragsunterlagen zählt das Ende des verknüpften Vertrags, sonst „Gültig bis“ des Dokuments; ohne beides läuft die Frist, bis ein Ende eingetragen ist.

**Einstellbar.** Die Jahre der vier Klassen sind installationsweite Vorgaben (Einstellungen → Fachliche Vorgaben, „Aufbewahrung: …“), 1 bis 30 Jahre, bei Verträgen 0 bis 30. Ändert sich das Gesetz wieder, oder will jemand länger aufbewahren, genügt eine Einstellung.

## Löschsperre

Solange die Frist läuft, lehnt der Server das Löschen ab (409, mit Frist und Grundlage), beim einzelnen Löschen wie beim Sammellöschen. Wer ein Dokument trotzdem löschen muss, etwa ein versehentlich doppelt abgelegtes, kann das als **Eigentümer oder Verwaltung mit einer Begründung** (10 bis 500 Zeichen). Der Grund steht mit Frist, Klasse und Titel im Auditjournal (`document_retention_override`); auf SQL in derselben Transaktion wie das Löschen. Andere Rollen bekommen 403. Im Sammellöschen gibt es diesen Weg nicht.

Archivierte Originale (Briefe, Protokolle, Abrechnungen) bleiben wie bisher unabhängig davon unlöschbar.

Die Sperre schützt vor versehentlichem Löschen. Sie macht das Programm nicht zu einem revisionssicheren Archiv im Sinne der GoBD, und die Einstufung ersetzt keine steuerliche Beratung.

## Oberfläche

- Dokumentliste: Spalte „Aufbewahrung“ („bis 31.12.2033“, „abgelaufen 31.12.2024“, „bis Vertragsende + 3 J.“, „dauerhaft“), Filter und Kennzahl „Aufbewahrung abgelaufen“.
- Dokumentformular: „Aufbewahrung“ mit „Automatisch nach Dokumenttyp“ und den Klassen samt Jahren.
- Löschen während der Frist öffnet den Dialog „Aufbewahrungspflicht“: Frist, Grundlage, Hinweis auf die Einstufung; für Eigentümer und Verwaltung „Trotzdem löschen, weil …“.

## Daten

- Migration **`f4c6e8a0b2d3`** hinter `e2b4d6f8a0c1`: Spalte `documents.retention_class` (leer = nach Dokumenttyp). Abgesichert wie die Vorgänger; ein Downgrade wird verweigert, solange ein Dokument eine gewählte Klasse hat.
- JSON-Export: Formatversion 13, damit ältere Programmversionen ihn ablehnen, statt die Einstufung stillschweigend zu verlieren.
- `GET /api/v1/documents/retention`: Regeln und, je sichtbarem Dokument, Klasse, Fristende, Zustand (`none`, `running`, `open`, `permanent`, `ended`) und Sperre.

## Stand der Umsetzung

- [x] Klassen, Fristberechnung, Einstellungen (`services/document_retention.py`, `settings_catalogue.py`)
- [x] Löschsperre im Einzel- und Sammellöschen, Begründung mit Auditeintrag
- [x] Migration, Exportformat 13, Migrationstest
- [x] Oberfläche: Spalte, Filter, Kennzahl, Formularfeld, Dialog
- [x] Tests: `test_document_retention.py` (Speicher und SQL), `DocumentRetention.test.jsx`
