# Logik, Wartbarkeit und Updatefähigkeit (Runde 14, 22.10.2026)

Geprüft wurde der Stand `4e827e3`. Die Prüfung umfasste:

- **Updates:** Neuinstallation gegenüber aktualisierter Installation (SQLite und PostgreSQL), Migrationskette, ausdrückliches Upgrade, Selbst-Updater, Update-Skript, Versionsanzeige.
- **Abhängigkeiten und Pakete:** Abhängigkeitslisten und Paketbau.
- **Fachlogik:** Löschschutz gegen kaskadierende Fremdschlüssel, Rundungen außerhalb des Geldmoduls, Budgets, Buchungsstorno, Bankabgleich, Aufgaben-Wiederholung.
- **Tests:** Zuverlässigkeit über die Zeit, ein Lauf mit vorgestellter Uhr.

Jeder behobene Befund hat einen Regressionstest, der ohne die Korrektur fehlschlägt.

## Behoben

| ID | Bereich | Schwere | Befund | Korrektur |
|---|---|---|---|---|
| R14-01 | Update | hoch | Seit März 2026 gab es 13 Indizes nur bei Neuinstallationen; keine Migration legte sie an. Betroffen waren Buchungen je Konto und Datum, Verträge je Mieter und Status, Rechnungen, Forderungen, Dokumente, Aufgaben, Mieter und Einheiten. Jeder aktualisierten Datenbank fehlten sie, Listen, Berichte und Mieterkonten wurden mit dem Bestand langsamer. Umgekehrt fehlte Neuinstallationen der Index für die Änderungshistorie eines Datensatzes. | Die Migration `d1f3a5c7e9b2` legt Fehlendes an. Neuer Test `test_schema_parity.py`: Er vergleicht Neuinstallation und Upgrade (Tabellen, Spalten, Pflichtfelder, Indizes, Fremdschlüssel, Trigger), für PostgreSQL auch im PostgreSQL-Gate. |
| R14-03 | Konten | mittel | Dieselbe IBAN durfte je nach Installation doppelt vorkommen. Eine SQL-Neuinstallation lehnte sie mit „Datenintegritätsfehler“ ab, aber nur bei gleicher Schreibweise; mit Leerzeichen ging es durch. Die Speicher-Variante und aktualisierte Datenbanken nahmen sie immer an. Ein doppelt angelegtes Konto zählt seinen Saldo doppelt. | Alle Installationen lehnen die IBAN ab und nennen das vorhandene Konto. Die Prüfung vergleicht ohne Leerzeichen. Die Migration legt den Unique-Index an, wenn keine Dubletten bestehen. |
| R14-05 | Updater (git) | mittel | Der Updater installierte Python-Pakete ohne `constraints.txt` und damit ungetestete Versionen. Ein pip-Fehler galt als „nicht kritisch“, und die Migration lief trotzdem. `npm install` veränderte `package-lock.json`. Ohne Vorspulen erzeugte er einen Merge-Commit. Ein Rückbau setzte nur den Code zurück, nicht die Pakete. Während des Updates und bis zum Neustart konnte weiter gespeichert werden: Ein Fehlschlag spielte den Datenbankstand vom Update-Beginn zurück und verwarf diese Eingaben, danach schrieb noch der alte Code in das neue Schema. | Pakete werden exakt nach `constraints.txt` installiert; bei einem Fehler wird abgebrochen und zurückgebaut, die alten Pakete werden wieder installiert. Das Frontend wird mit `npm ci` und `npm run build` gebaut. Der Code wird nur vorgespult. Änderungen sind während des Updates und bis zum Neustart gesperrt (503 mit Hinweis); Lesen und Anmelden gehen weiter. |
| R14-06 | Paketbau | mittel | `pyproject.toml` fehlte `pypdf`; `build.bat`/`build.sh` bauten deshalb ohne PDF-Volltextsuche. Die Release-Builds nahmen „irgendein PyInstaller ab 6.0“ statt der geprüften 6.22.3. | `pypdf` ist ergänzt; die Workflows installieren `requirements-build.txt`. Ein Test verlangt jede Laufzeit-Abhängigkeit in `pyproject.toml`. |
| R14-08 | Update | mittel | Die Version kam zuerst aus den Paket-Metadaten. Eine git-Installation (`install.sh`/`install.bat` installieren „editable“) behält die Version ihrer Erstinstallation: Nach dem Update auf 2.1.0 hätte sie weiter 2.0.0 gemeldet und dasselbe Update immer wieder angeboten. Auch Update-Verlauf, Vollbackup und Export hätten die falsche Version getragen. Der Starter zeigte fest „v1.0.0“. | `pyproject.toml` neben dem Code hat Vorrang (gelesen mit `tomllib`); die Metadaten gelten nur ohne diese Datei. |
| R14-09 | Instandhaltung | mittel | Eine Projektakte mit erteilten Aufträgen und zugeordneten Rechnungen ließ sich löschen. Auftrag, Nachträge und Rechnungsbezug verschwanden, obwohl das Stornieren eines solchen Auftrags verweigert wird. | Das Löschen wird verweigert (409); die Akte lässt sich abbrechen oder abschließen. |
| R14-11 | Wartbarkeit | mittel | `db/schema.sql` war ein Prototyp-Schema (33 der heute 159 Tabellen, ohne Migrationsstand), lag im Docker-Image und im Windows-Paket, und `db/README.md` empfahl, es auszuführen. | Die Datei ist entfernt; das README beschreibt den Weg über das Upgrade. |
| R14-12 | Update-Skript | mittel | `scripts/update.sh` holte fest `origin main`; das Repository hat nur `master`. Jeder Lauf scheiterte. | Das Skript holt den Branch, dem die Installation folgt. |
| R14-13 | Rechte | niedrig | Die Quelle der Updates (`/updates/configure`: Repository, Kanal, Token) durften Eigentümer und Verwalter ändern; das Einspielen nur der Eigentümer. | Auch die Update-Einstellungen sind dem Eigentümer vorbehalten. |
| R14-10 | Nebenkosten | niedrig | Die Beträge der Vorauszahlungsabschnitte wurden „zur geraden Ziffer“ gerundet (525,105 → 525,10), die Vorauszahlungen der Abrechnung kaufmännisch (3.075,11). Die angezeigten Abschnitte ergaben nicht die Summe. | Die Abschnitte werden kaufmännisch gerundet (`money`). |
| R14-02 | Update | niedrig | Unter PostgreSQL fehlte aktualisierten Datenbanken der Fremdschlüssel einer Rechnung auf ihr Quelldokument. Bezüge auf gelöschte Dokumente blieben stehen. | Die Migration leert solche Bezüge und legt den Fremdschlüssel an (`ON DELETE SET NULL`). Unter SQLite ginge das nur mit Tabellenumbau; dort bleibt es dokumentierte Ausnahme im Paritätstest. |
| R14-14 | Tests | niedrig | Der Test der Testversion baut die Daten zum 05.10.2026, fragte die Prüfliste aber zum echten Datum ab. Mit der Uhr auf dem 01.04.2027 meldet sie eine dann fällige Mietstufe; der Test wäre von selbst rot geworden, sobald dieser Tag erreicht ist. | Die Prüfliste wird zum Stichtag der Daten abgefragt (`as_of`). |
| R14-15 | Tests | niedrig | Ein Aufbewahrungstest legte eine Rechnung von 2017 an und erwartete mit zehn Jahren die Löschsperre bis 31.12.2027. Ab dem 1. Januar 2028 wäre er von selbst rot geworden; gefunden mit der Uhr auf dem 03.01.2028. | Das Rechnungsjahr liegt jetzt immer neun Jahre zurück: acht Jahre sind abgelaufen, zehn nicht. Geprüft mit der Uhr 2027, 2028 und 2030. |
| R14-04 | Wartbarkeit | niedrig | Drei IBAN-Prüfungen nebeneinander; die der Plausibilitätsprüfung kannte die Länge je Land nicht. | Eine Prüfung (`sepa_rules.iban_problem`) für Konten und Lastschriftdaten. |

## Für Wartbarkeit und Updates neu abgesichert

- **Gleiches Schema auf beiden Wegen:**
  - `test_schema_parity.py` baut eine neue Installation im eigenen Prozess, nur mit den Modulen, die `initialise_empty` registriert, und vergleicht sie mit dem Upgrade.
  - Ein neues Modell ohne Migration oder eine Migration ohne Modell fällt sofort auf, ebenso ein vergessener Import.
  - Erlaubte Unterschiede stehen mit Begründung im Test.
- **Freigabeliste der Migrationen:**
  - Ein neuer Migrationsstand muss in `ORM_ADOPTION_TARGETS` (`migrations/env.py`) eingetragen werden, sonst scheitert das Upgrade alter Desktop-Datenbanken ohne Versionsstand.
  - Bisher zeigte das nur ein anderer Test mit „table … already exists“; jetzt nennt ein eigener Test den fehlenden Eintrag.
  - Das Rezept „neues Feld“ in `docs/ARCHITECTURE.md` nennt beides.
- **Updater:** `test_updater_apply.py` prüft den Ablauf mit nachgebildetem git, pip und npm: feste Versionen, Abbruch und Rückbau, nur Vorspulen, Schreibsperre, Update-Skript.
- **Abhängigkeiten:** `test_dependency_manifests.py` gleicht `requirements.txt`, `pyproject.toml`, `requirements-build.txt` und die Workflows ab.
- **Rückwärts-Migrationen:** Ein verweigerter Downgrade bleibt unter SQLite bei der Migration stehen, die ihn verweigert; SQLite kennt keine transaktionalen Schemaänderungen. Daten ändern sich dabei nicht; der Start verlangt dann wieder das Upgrade. Der geprüfte Rückweg bleibt das Vollbackup vor dem Upgrade.

## Tests über die Zeit

Die ganze Backend-Suite lief zusätzlich zweimal mit vorgestellter Uhr, am 1. April 2027 und am 3. Januar 2028 (Paket `time-machine` nur im Prüfaufbau). Von 3539 Tests schlugen je 6 fehl. Zwei waren echte Zeitzünder (R14-14, R14-15). Die übrigen fünf sind Grenzen des Prüfaufbaus, keine Fehler des Programms:
- Testzertifikate entstehen mit der vorgestellten Python-Uhr, OpenSSL prüft sie mit der echten Systemzeit (drei TLS-Tests).
- Die Veraltungsprüfung der Backup-Sperre vergleicht das Änderungsdatum der Datei (echte Zeit) mit der vorgestellten Uhr.
- Das Registrierungskontingent wird in Unterprozessen mit echter Uhr gefüllt.

## Geprüft und in Ordnung

- **Löschschutz:** Alle kaskadierenden Fremdschlüssel wurden mit dem Löschschutz abgeglichen. Abrechnungszeiträume sind nur als Entwurf löschbar; Objektverträge mit Rechnungen oder Zahlungen, Kautionen mit Zahlungen oder Abrechnung und Akten mit abgeschlossenen Protokollen werden nicht gelöscht. Die Lücke war R14-09.
- **Buchungsstorno:** Gegenzeichen, gleiche Zuordnung, nicht vor dem Original, Summe höchstens der Betrag, keine Umbuchung eines stornierten Originals.
- **Bankabgleich:** IBAN-Abgleich ohne Leerzeichen, doppelte Bankreferenzen werden abgelehnt, Zuordnungen nur mit aktuellem Stand (409 sonst).
- **Frontend-Summen:** Tabellensummen, Mieterkonto, Kautionsraten und Projektkosten rechnen in ganzen Cent.
- **JSON-Export:** Er umfasst die Fachdaten. Bankoriginale, Kommunikation, Steuer und Schnittstellen verlangen bewusst das Vollbackup.
- **Ausdrückliches Upgrade:** Vollbackup davor, Exit-Codes, neuere Datenbank wird abgelehnt; Docker, Starter, Update-Skript und Updater führen es aus.

## Vorschläge

> Umgesetzt in Runde 15, zusammen mit den offenen Entscheidungen aus Runde 12: [IMPROVEMENTS_20261022.md](IMPROVEMENTS_20261022.md).

- **Budget-Ist aus Buchungen:** Der Ist-Betrag eines Budgets wird von Hand gepflegt. Aus den Buchungen je Objekt, Jahr und Kategorie berechnet, wäre der Soll/Ist-Vergleich immer aktuell; dafür bräuchte jede Budget-Kategorie eine Zuordnung zu Buchungskategorien.
- **Doppelte IBANs anzeigen:** Bestehende Dubletten aus der Zeit vor R14-03 bleiben stehen (die Migration legt dann keinen Unique-Index an). Ein Eintrag in der Prüfliste („Konten mit gleicher IBAN“) würde sie zeigen.
- **`iban_encryption.py`** ist unbenutzt (siehe Betriebsdoku) und könnte entfallen.
- **Update-Quelle:** Die Update-Prüfung liest die Releases von `UPDATE_REPO_URL`, eingespielt wird aber von `origin` des Checkouts. Laufen beide auseinander, wird ein Update angezeigt, das sich nicht einspielen lässt. Der Updater könnte vorab prüfen, dass `origin` auf dasselbe Repository zeigt.
- **Ein „Heute“:** 29 Module nehmen `date.today()`, also die Zeitzone des Rechners; die Hintergrundjobs nehmen `local_today()` (Europe/Berlin). Auf Windows ist beides dasselbe. Im Docker-Container (UTC, kein `TZ` gesetzt) gilt zwischen Mitternacht und 1 bzw. 2 Uhr noch der Vortag, eine Fälligkeit wird dann bis zu zwei Stunden später erkannt. Vorschlag: überall `local_today()` oder `TZ=Europe/Berlin` im Image.
- **CI:** `pip install --upgrade pip` ist nicht festgelegt; eine feste pip-Version machte die Builds noch reproduzierbarer.
- Offen aus Runde 12 bleiben die Entscheidungen R12-03, -07, -09, -12, -14 bis -20 (`docs/CALCULATION_AUDIT_20261021.md`).
