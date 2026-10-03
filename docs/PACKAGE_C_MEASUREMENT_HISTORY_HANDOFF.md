# Paket C: historische Mess- und Belegungsgrundlage

Stand 3. Oktober 2026. Eigener Branch `assist/billing-measurement-history`,
saubere Ausgangsbasis `5de8762`; keine Root-, Main-, UI- oder zentralen
Startup-/Recovery-Dateien geändert. Nur synthetische Testdaten verwendet.

## Übernahme und Migrationsfolge

In dieser Reihenfolge übernehmen:

1. `19365a9`: konkreter Plan vor Implementierung.
2. `e8cc1f6`: typisierte Quellenfamilie, Validatoren, Migration.
3. `9b9ba33`: atomare Schreibbefehle, API, Recovery-/Privacy-Projektion.
4. `7712d45`: historische Berechnung, zulässige Billing-Hooks, native Gegenbelege.
5. Der nachfolgende C4-Commit dieses Dokuments: FK-sichere Exportreihenfolge,
   deterministischer Restore-Gegenbeleg und letzte Formatkorrektur.

Die einzige eigene Migration ist `g2a2b3c4d5e6`,
`down_revision = f2a2b3c4d5e6`. Tatsächlicher Vorgänger ist Scheduler-Commit
`d71204eb5259cc2433f08f9aea2135dc76d3e870`, keine Ersatzrevision und kein Stamp.
Die beiden dortigen Dateien `f2a2b3c4d5e6_durable_scheduler.py` und
`operational_scheduler_models.py` waren ausschließlich uncommittete lokale
Testvoraussetzungen. Plattform ergänzt danach `h2` mit Vorgänger `g2`.

`g2` erzeugt vier Tabellen und native Schutztrigger. Es übernimmt keinerlei
heutige Stammdaten als vermeintlich historische Fakten. Downgrade prüft vor
DDL, dass alle vier Tabellen leer sind, und verweigert sonst Datenverlust.

## Ergebnis und überprüftes Verhalten

- Verbrauch folgt ausdrücklich bestätigten Messkreisen, Medien, Maßeinheiten
  und Originalgrenzen. Zählerersatz, Ein-/Auszug und Leerstand werden an den
  tatsächlichen Grenzen geschnitten; es gibt keine automatische Tagesprognose.
- Personengewichte entstehen aus datierten Bewohnerzahlen mal Tagen.
  Zimmerzahlen werden nicht zu Bewohnerzahlen umgedeutet.
- Ein physischer Zähler kann innerhalb seiner aktuell zugänglichen Immobilie
  nacheinander mehreren Einheiten zugeordnet werden. Gleichzeitige Nutzung
  desselben Zählers durch mehrere Einheiten wird auch nativ konkurrierend
  durch gemeinsame Zählersperre und Überschneidungsprüfung verhindert.
- Gleichzeitige Haupt-/Unterkreise und doppelte Pfade sind unzulässig.
  Andere Messkreise müssen ausdrücklich als überschneidungsfrei bestätigt
  werden. Aus Namen oder Seriennummern wird keine Topologie erraten.
- Korrekturen und Rücknahmen sind neue Fassungen mit Vorgänger und Grund.
  Originale bleiben erhalten und einzeln abrufbar; natives UPDATE/DELETE der
  Quellen sowie SQL-Kaskaden zu ihren Eltern werden verhindert.
- Fehlende Quellen können schrittweise ergänzt werden. Erst die Vorprüfung
  verlangt vollständige Abdeckungen. Widersprüchliche Überlappungen sind schon
  beim Schreiben ein Konflikt. Keine Ersetzung fehlender Historie durch heute
  vorhandene Daten, sobald ein Schlüssel einmal historisch ausgewählt wurde.
- Verbrauch eines einzelnen Mieters darf null sein. Nichtnullkosten bei null
  Gesamtsumme benötigen einen anderen ausdrücklich bestätigten Schlüssel.
- Vollständig belegter Leerstand kann eine Periode ohne Mieterabrechnungen
  abschließen. Der Eigentümer trägt die volle abgestimmte Kostensumme; dafür
  müssen alle verwendeten Schlüssel eine vollständige historische Basis
  haben. Eine leere Mieterübersicht allein ist kein Freigabenachweis.
- Quellenkorrekturen machen einen bestehenden Entwurf ungültig. Bereits
  finalisierte Abrechnungen bleiben unverändert; erneute Finalisierung liefert
  dasselbe Original. Weitere Korrekturabrechnungen bleiben im bestehenden
  versionierten Abrechnungsablauf.

## API und tatsächlich editierbare Felder

Basispfad: `/api/v1/billing/measurement-history/units/{unit_id}`.
Alle Antworten verwenden `Cache-Control: private, no-store`.

| Aufruf | Inhalt |
| --- | --- |
| `GET ?start=YYYY-MM-DD&end=YYYY-MM-DD` | Aktuelle Revision und wirksame Fassungen einschließlich Rücknahmen im Zeitfenster. |
| `GET /journal?after=0&page_size=50` | Befehlsjournal nach Revision mit `next_after`; ohne globale Datensatzgrenze. |
| `GET /facts/{fact_id}` | Exaktes unverändertes Original, auch nach Korrektur oder Rücknahme. |
| `POST /confirm` | Atomarer Bestätigungsbefehl; Ergebnis `revision` und `fact_ids`. |

`MeasurementCommand` in `backend/services/measurement_history_types.py`:
`expected_revision`, `idempotency_key`, nichtleere `changes`.
Jeder `FactChange` enthält `source_key`, optional `predecessor_id`, `reason`,
`withdrawn`, `evidence_version_ids` und genau eine typisierte `data`:

| `data.kind` | Editierbare Nutzlast |
| --- | --- |
| `assignment` | `valid_from`, `valid_until`, `meter_id`, `medium`, `measurement_unit`, `circuit_path` als Liste von Pfadteilen. |
| `reading` | `assignment_key` als stabile `source_key` der Zuordnung, `boundary_date`, `value` als endlicher nichtnegativer Decimal-Text. |
| `occupancy` | `valid_from`, `valid_until`, `contract_id`, `persons` als nichtnegative Ganzzahl, `vacancy`. Leerstand erfordert `contract_id=null`, `vacancy=true`, `persons=0`. |
| `selection` | `valid_from`, `valid_until`, `allocation_key_id`, `basis` (`consumption` oder `person_count`), `circuits`, `confirmed_disjoint`. Verbrauch benötigt bestätigte Kreise, Personentage keine Kreise. |
| `proration` | `valid_from`, `valid_until`, `assignment_key`, `start_reading_id`, `end_reading_id`. Erfordert begründete Freigabe mit mindestens einer unveränderlichen Dokumentversion in `evidence_version_ids`. |

Alle Zeitabschnitte sind **halb offen**: Beginn einschließlich, Ende
ausschließlich. Der Abrechnungszeitraum 01.01.–31.12.2026 braucht historische
Grenzen 01.01.2026 und 01.01.2027. Die Oberfläche sollte hierzu verständliche
Beschriftungen liefern; kein stilles Vermischen mit dem alten inklusiven
Ablesepfad für noch nicht historisch ausgewählte Schlüssel.

Bearbeitungsablauf: aktuellen Stand lesen, stabile Befehlskennung erzeugen,
zusammengehörige Änderungen mit `expected_revision` bestätigen. Bei Timeout
denselben Befehl unverändert wiederholen. Wiederverwendung derselben Kennung
mit anderem Inhalt ist 409. Bei 409 wegen neuer Revision den Stand erneut
lesen und dem Nutzer die abweichenden Quellen zeigen; Änderungen nicht blind
mit neuer Revision übersenden. Korrektur nennt die konkrete Vorgänger-ID.
Rücknahme behält die vorherige Nutzlast unverändert und erklärt den Grund.
Eine von korrigierten Ablesungen abhängige Zeitfreigabe muss mit den neuen
Originalen erneut bestätigt oder gemeinsam zurückgenommen werden.

## Fehlerdarstellung und Reparatur

Die bestehende Abrechnungsvorprüfung liefert zusätzliche strukturierte
Blocker mit betroffener Schlüssel-/Einheits-ID in `context`:

| Code / Status | Sinnvoller Reparaturweg |
| --- | --- |
| `HISTORICAL_BASIS_INCOMPLETE` | Fehlenden Zeitabschnitt, Belegung, Messkreisauswahl, exaktes Medium/Maßeinheit oder Grenzablesung öffnen und ergänzen; die konkrete Meldung beschreibt die fehlende Basis. |
| `HISTORICAL_TOTAL_ZERO` | Gesamtsumme prüfen und einen belegten alternativen Schlüssel wählen; keine künstliche Mindestmenge eintragen. |
| `HISTORICAL_SOURCE_CORRUPT` | Original und Wiederherstellung prüfen; nicht als neue automatische Schätzung fortfahren. |
| 409 beim Bestätigen | Aktualisierte Revision, Vorgänger, Überschneidung oder vorübergehende Schreibsperre klären. Eine Schreibsperre erlaubt unveränderte Wiederholung derselben Kennung. |
| 422 | Ungültige Nutzlast, Datumsgrenzen, unzulässige gleichzeitige Haupt-/Unterkreise oder fehlender Freigabebeleg im Formular markieren. |
| 404 / 403 / 401 | Reale Elternbindung, Portfoliozugriff bzw. aktuelle Anmeldung prüfen; keine fremden Quelleninformationen ausgeben. |
| 503 | Quellenfamilie fehlt: reguläre Datenbankmigration ausführen, kein Schema im HTTP-Aufruf anlegen. |

Eine zurückgenommene oder in ein anderes Jahr verschobene historische Auswahl
reaktiviert niemals den früheren Stammdaten-Fallback. Aktuelle Vertragsgrenzen
und eingefrorener Mieter müssen zu bestätigter Belegung passen. Inaktive Zähler
können als belegte historische Geräte weiter benutzt werden; ihr heutiger
Aktivstatus vernichtet keine Originalgrundlage.

## Gemeinsame Sperre, Quellenbezug und SQL-Abfragen

`measurement_history.lock_measurement_property` ist derselbe Träger für
Quellenschreiben und `billing_settlement.atomic_billing`, vor bisherigen
Perioden-/Vertragssperren. SQLite verwendet die bestehende Schreibtransaktion;
PostgreSQL eine transaktionsgebundene Advisory-Sperre aus dem signierten
64-Bit-Präfix des SHA256 von `measurement:` plus Immobilien-ID. Dies schützt
auch vor dem ersten Ledgerdatensatz. Bestehende Memory-Domain-/Privacy-Sperren
decken den jeweiligen Vorgang ab.

Schreibbefehle prüfen aktuellen Actor, Rolle, Scope und Request-Credential vor
Beginn und vor Commit. SQL-Accountverwaltung wird eingebunden; Memory-Auth bei
SQL-Daten liegt beim Commit unter der Account-Sperre. Verlorene Rechte erzeugen
Rollback. Memory nimmt ausschließlich eigene Zeilen und die eigene vorherige
Ledgerfassung zurück; keine komplette Bestandskopie als Rollback.

Der Berechnungshash enthält konkrete periodische Quellen-IDs/Inhaltshashes;
die Eigentümerübersicht bewahrt denselben Quellenbezug. Ein unabhängiger
Quellenschreiber zwischen Berechnung und Veröffentlichung wird synchronisiert.

Neue SQL-Lesewege begrenzen nach Immobilie und Zeitraum; Nachfolger werden
vor dem Zeitfilter ausgeschlossen. Nur zusätzlich benannte Originalgrenzen
einer Freigabe werden gezielt hinzugeholt. Indizes liegen auf Zeitraum,
Quellenreihe, Personenbezug, Schlüssel und physischem Zähler. Beleg-IDs werden
in SQL-Blöcken geladen, ohne eine globale Höchstzahl festzulegen.

## Verbindliche zentrale Integration durch Root

Diese Hooks sind bewusst **noch nicht zentral eingebaut**. Bis zur Umsetzung
und gemeinsamen Prüfung keine vollständige Produktions-Recovery-/Privacy-
Abnahme für die neue Familie behaupten.

1. **Modellregistrierung und Schema:**
   `backend.db.measurement_history_models` vor Schema-/Snapshot-Auswertung
   importieren. `validate_measurement_schema(connection)` aus
   `backend/db/measurement_history_schema.py` an den vorhandenen zentralen
   Prüfstellen ergänzen. Unterstützt SQLAlchemy-Connection und rohe
   `sqlite3.Connection`; liest nur. Vollständig fehlende Familie ergibt
   `False`, Teilbestand/abweichende Bindungen einen `MeasurementIntegrityError`.
   SQL-Startup-/Testbootstrap darf die Modelle nicht erst durch Routerimport
   nach dem bestehenden Schemaaufbau kennenlernen. Keine DDL im Serverstart
   oder normalen HTTP-Aufruf hinzufügen.

2. **Snapshot-/Restorefamilie:**
   Alle vier Tabellen vollständig in Export, Exportmanifest, Integritäts-
   und Restorelisten aufnehmen. `RESTORE_ORDER` in
   `backend/services/measurement_history_recovery.py` ist
   `measurement_ledgers`, `measurement_commands`, `measurement_facts`,
   `measurement_evidence`. `RESTORE_PARENTS` nennt vorher zu ladende
   Portfolios, Immobilien, Einheiten, Zähler, Schlüssel, Verträge, Mieter und
   Dokumentversionen. Über `iter_measurement_family` streamen; SQL verwendet
   `yield_per=100`. Befehle nach Ledger/Revision, Fakten nach
   Ledger/Revision/Position laden: eine Korrektur muss hinter ihrem Vorgänger
   stehen. Arbiträre UUID-Sortierung verletzt sonst die Self-FK.
   `measurement_facts.valid_from/valid_until` sind `date`,
   `measurement_commands.created_at` ist `datetime`; JSON-Felder und
   `withdrawn` als echte Boolean erhalten.

3. **Reiner Datenvalidator:**
   `VALIDATE_SNAPSHOT` / `validate_measurement_snapshot(family, parents=...)`
   vor Veröffentlichung des wiederhergestellten Bestands ausführen.
   `parents` enthält ID→Dict-Abbildungen von `units`, `properties`, `meters`,
   `allocation_keys`, `contracts`, `tenants`, `document_versions`; die
   übergeordnete Recovery prüft Portfolios und deren eigenen Graphen.
   Die reine Prüfung kontrolliert Hashes, Typen, Elternbindungen,
   Revisionsketten, Command/Result/Fakt-Zuordnung, Originalbelege und zeitliche
   Überschneidungen. Sie schreibt nichts und repariert keine Historie.
   Native Schutztrigger durch echte Migration oder den ausdrücklich
   dafür vorgesehenen Restore-Staging-Aufbau installieren:
   `install_measurement_guards` ist DDL, nicht idempotent und kein Runtimehook.

4. **Privacy und Aufbewahrung:**
   `retained_measurement_subject(store, tenant_id)` in den autorisierten,
   konsistenten Privacy-Snapshot aufnehmen. Die Projektion enthält genaue
   aktuelle/eingefrorene Personenreferenzen, Belegbezüge und minimale
   Befehlsmetadaten. Komplette `command.request` dürfen nicht ungefiltert
   in den Personenexport: derselbe Befehl kann Angaben zum Nachmieter
   enthalten. Gemeinsame technische Zählerquellen bleiben auf Objektebene
   erhalten. Die Vollständigkeitsprüfung verweigert verborgene andere
   Portfolioanteile mit 403; keine stillen Teil-Exporte.
   Allgemeine Lösch-/Anonymisierungs- und Portfolio-Grenzprüfungen müssen
   diese Familie unter dem bestehenden Privacy-Fence mit erfassen.

5. **Elternschutz:**
   `assert_no_measurement_cascade(store, entity_type, entity_id)` für
   `tenant`, `unit`, `property`, `portfolio`, `contract`, `meter`,
   `allocation_key` in zentrale Memory-Löschpfade einbinden; SQL hat bereits
   `RESTRICT`-FKs. Dokumentoriginale sind zusätzlich über Evidence-FKs
   referenziert und müssen in der Memory-Dokumentversion-Aufbewahrung
   berücksichtigt werden. Bestehende Ledger-/Vertragsbindungen dürfen
   durch Eltern-Neuzuordnung nicht still brechen: Unit→Property,
   Contract→Unit/Tenant sowie AllocationKey→Property brauchen im zentralen
   CRUD einen Referenzschutz oder einen separat versionierten Umzugsablauf.
   Die neuen Quellen fixieren diese Bindungen; der Restorevalidator
   würde einen widersprüchlich umgehängten Graphen zu Recht zurückweisen.
   Historische Meter→Unit wird dagegen ausdrücklich nicht mit heutigem
   Stammdatenstand gleichgesetzt.

## Tatsächlich ausgeführte Prüfungen

Python-Laufzeit 3.14.7; Ruff sowie Mypy mit Ziel 3.11 und 3.12.
PostgreSQL ausschließlich eigener UUID-Testschema-Raum auf dem vom
Plattformagenten bereitgestellten Loopback-Testdienst. Keine Produktivdaten.

| Prüfung | Ergebnis / lokales Nachweisprotokoll außerhalb des Commits |
| --- | --- |
| Zusammengesetzte DTO-/HTTP-/Integritäts-/Konkurrenzprüfung auf Memory, real migriertem SQLite und PostgreSQL | 50 passed, 1 gezielter Memory-DDL-Skip; `work/measurement-history-final-composed.log`. |
| Danach ergänzte physische Zählerzuordnung, fremder Zugriff, Rechteverlust und 1.001 fremdjährige Ablesungen | 12 passed; `work/measurement-history-remaining-gates.log`. Die Jahresabfrage materialisiert exakt die 10 relevanten Quellenfassungen. |
| Native SQLite-Schreibsperre mit unveränderter erfolgreicher Wiederholung | 1 passed, 2 backendbedingte Skips; `work/measurement-history-sqlite-busy.log`. |
| Exakter Originalabruf nach Korrektur, finaler Stand | 3 passed; `work/measurement-history-original-schema-final.log`. |
| Reale Alembic-Kette, Downgrade zu f2, erneutes Upgrade, FK/Trigger, kein Backfill, verweigerter Datenverlust | 6 passed (SQLite und PostgreSQL), letzter Stand `work/measurement-history-migration-final.log`. |
| FK-sichere Wiederherstellungsreihenfolge trotz früher sortierender Korrektur-ID, Hash-Manipulation, Teilfamilie und Privacy-Projektion | 3 passed (Memory/SQLite/PG); `work/measurement-history-restore-order.log`. |
| Bestehende Billingengine, Preflight, Workflow, Sprint2, Integrität, Leerstand, NK6, Exporte, CRUD-Generation | 134 passed, 1 bestehender Backend-Skip auf Memory sowie nochmals auf vollständig migriertem SQLite; `work/measurement-history-regression-memory.log`, `work/measurement-history-regression-sql-migrated.log`. |

Die ergänzten Fälle wurden gezielt nach dem großen Lauf ausgeführt; keine
Behauptung eines nachträglichen einzigen vollständigen Gesamtlaufs. Ein
erster Alt-SQL-Fixturelauf ohne frühe Modellregistrierung war erwartbar rot
(`measurement_evidence` fehlte nach zu frühem Base-Schemaaufbau). Der echte
vollständig migrierte Weg ist grün; Root muss die zentrale Registrierung und
die neuen Recovery-/Privacy-Hooks gemeinsam erneut prüfen. Vorhandene
Starlette/httpx-Abkündigungswarnung unverändert.

## Verbleibende Grenzen und getrennte Folgearbeit

- Die neue API und Berechnung sind implementiert; die Eingabe-/Korrektur-UI
  gehört Root. In dieser Übernahme wird keine fertige Oberfläche behauptet.
- Messdaten sind Tagesgrenzen, keine Uhrzeitauflösung, Fernauslese oder
  automatische Anbieterimporte. Gemischte physikalische Einheiten benötigen
  einen eigenen belegten Umrechnungsablauf; aktuell reparierbare Ablehnung.
  Zählerrücksetzung/Überlauf als eigener Betriebsabschnitt mit Grenzen
  erfassen. Kein Hauptzähler-minus-Unterzähler-Differenzschema ableiten.
- Ganze Immobilien ohne Verbrauch/Personentage und zugleich Nichtnullkosten
  brauchen einen belegten anderen Verteilerschlüssel. Das Paket erfindet
  dafür keine Mengen oder Bewohner.
- Frühere Schlüsselwahl aktiviert die historische Vollständigkeitsprüfung
  für diesen Schlüssel auch in anderen Jahren. Vor Nutzung dort passende
  Originalgrundlagen erfassen oder bewusst einen anderen Schlüssel wählen.
- Die neuen Messquellenabfragen sind zeitlich begrenzt. Vorhandene übrige
  `list_*`-Aufrufe in Billing und der alte Anteil des Berechnungshashs sind
  weiterhin eigene Skalierungsarbeit; der 1.001-Fall belegt den neuen
  Selektor, nicht beliebige Gesamtbestandsgröße oder zwanzig Jahre ohne Wartung.
- Das Bestätigen validiert den effektiven Quellenstand einer Einheit; weitere
  großvolumige Schreibbenchmarks bleiben sinnvoll. Es gibt kein künstliches
  globales Datensatzlimit und keine Wiederholungsschleife ohne Konfliktmeldung.
- Das tatsächlich fehlende dauerhafte Widerspruchsjournal mit Grund, Anlagen
  und konkretem Abrechnungsfassungsbezug bleibt der im Plan abgegrenzte eigene
  Folgeschritt. Paket C überschreibt keine bestehenden Widerspruchsdaten.
