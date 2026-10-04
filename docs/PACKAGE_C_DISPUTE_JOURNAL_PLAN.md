# Separates Folgepaket: dauerhaftes Widerspruchsjournal

Ursprünglicher Planungsstand auf Basis `bc90599`. Der konkrete Domainstand,
native Belege und die noch ausstehenden zentralen/UI-Anteile sind jetzt in
`docs/PACKAGE_C_DISPUTE_JOURNAL_HANDOFF.md` dokumentiert. Die ursprüngliche
Lückenbeschreibung unten hält den damaligen Ausgangsstand fest.

Umsetzung reserviert nach tatsächlicher Graphprüfung: ausschließlich
`j2a2b3c4d5e6` mit Vorgänger `h2a2b3c4d5e6`. Die zunächst von Root genannte
Kennung i2 ist eine bereits bestehende historische Migration; sie bleibt
unverändert. Der erste SQLiteprobeversuch erkannte die doppelte Kennung vor DDL,
danach wurde nur die neue uncommittete Journalmigration auf j2 umbenannt.

## Tatsächlich vorhandene Lücke

`backend/routers/billing.py:949` nimmt `reason` als Queryparameter an,
übergibt ihn aber nicht an `settlement.dispute_period`.
`backend/services/billing_settlement.py:427` schreibt ausschließlich
`BillingPeriod.status = disputed`. Dadurch fehlen der tatsächliche Grund,
Anlagen, Eingangsdatum, Beteiligte, Verlauf und ein ausdrücklicher Bezug zur
damals beanstandeten Einzelabrechnungsfassung. Diese fehlenden Angaben lassen
sich für bestehende Datensätze nicht aus dem Status rekonstruieren.

## Fachliches Ziel und sichtbarer Ablauf

Eine Person öffnet die konkrete finalisierte Einzelabrechnung, erfasst den
Widerspruch mit Grund und tatsächlichem Eingangsdatum und verknüpft vorhandene
unveränderliche Dokumentoriginale. Die Prüfseite zeigt Abrechnungsrevision,
beanstandeten Betrag/Positionen, Quellenfassung und die erfassten Angaben.
Bestätigen schreibt eine unveränderliche Journalfassung. Weitere Notizen,
begründete Berichtigungen, Rücknahme und dokumentierter Abschluss sind neue
Ereignisse. Ein offener Vorgang bleibt in der Arbeitsübersicht auffindbar.

Eine rein objektbezogene Verwaltungsbeanstandung benötigt einen ausdrücklich
gewählten anderen Vorgangstyp und darf nicht als Widerspruch eines beliebigen
Mieters erscheinen. Für belegten Vollleerstand ist dieser Typ nutzbar.
Eine neue Korrekturabrechnung wird mit dem Anlass verknüpft, überschreibt
aber weder den Widerspruch noch die beanstandete Originalabrechnung.

Es werden keine Erstattungen, Forderungsstornos, Zustellungen oder rechtlichen
Fristen aus einem Statuswechsel erfunden. Finanzfolgen bleiben ausdrücklich
bestätigte Vorgänge des bestehenden Abrechnungssystems. Vor Einführung einer
automatischen Zahlungssperre ist deren fachliche Regel gesondert festzulegen.

## Vorgeschlagene Datenfamilie und DTOs

Die konkrete Migrationskennung muss Root in der dann aktuellen linearen
Alembic-Kette reservieren; keine Kennung oder parallelen Heads vorwegnehmen.

- `billing_dispute_cases`: stabile Akten-ID, Portfolio, Immobilie, betroffene
  Periode sowie optional konkrete Einzelabrechnung, eingefrorener Vertrags-/
  Mieterbezug, aktuelle Journalrevision. Bindungsfelder nach Eröffnung fest.
- `billing_dispute_events`: unveränderliche Ereignis-ID, Akte, Revision,
  Actor, Erfassungszeit, tatsächliches Eingangs-/Beobachtungsdatum, Ereignistyp,
  Grund/Notiz, Vorgänger bei Berichtigung, referenzierte Abrechnungsrevision
  und deren gespeicherter Snapshot-Hash, explizite Positionsbezüge, Inhaltshash.
- `billing_dispute_evidence`: Ereignis, unveränderliche Dokumentversion und
  SHA256; Originale bleiben durch RESTRICT und den vorhandenen Dokument-
  Aufbewahrungspfad geschützt. Kein veränderlicher Dateipfad als Belegersatz.
- `billing_dispute_commands`: Actor, Idempotenzschlüssel, kanonischer
  Requesthash, erwartete/neue Revision, exakte Ergebnis-IDs und Erfassungszeit.

`OpenDispute` enthält `expected_case_revision=0`, `idempotency_key`,
`period_id`, `statement_id` oder ausdrücklich `case_kind=property_review`,
`expected_statement_revision`, `expected_snapshot_hash`, `received_on`,
`reason`, optionale `line_item_refs` und `evidence_version_ids`.
`AppendDisputeEvent` enthält `expected_revision`, `idempotency_key`, `kind`,
`reason`, `observed_on`, optionale `corrects_event_id`, `evidence_version_ids`
und den ausdrücklich geprüften Verweis auf eine erzeugte Korrekturabrechnung.
Keine Auswertung freier Texte zur automatischen Personen-/Objektzuordnung.

## Zustände, Speicherung und Kompatibilität

Zustände sind aus bestätigten Ereignissen ableitbar: offen, in Prüfung,
zurückgenommen, abgeschlossen. Berichtigung ändert weder Originaltext noch
Eingangsdatum des ursprünglichen Ereignisses. Erneute Öffnung nach Abschluss
braucht einen neuen begründeten Vorgang oder ein ausdrücklich zulässiges
Wiederaufnahme-Ereignis; keine stille Wiederverwendung derselben Kennung.

Jede Speicherung läuft atomar unter frischer Rolle, Scope und tatsächlichem
Request-Credential bis Commit. Reihenfolge mit bestehenden Sperren abstimmen:
Account → Messimmobilie → Root-Abrechnungsperiode → Einzelabrechnung/Akte.
Erste Akte darf keine ungeschützte Abwesenheitslücke besitzen. SQL-Unique-
Constraints und Compare-and-Swap der Aktenrevision ergänzen die gemeinsame
Sperre. Wiederholung desselben Befehls liefert dasselbe Ergebnis; andere
Nutzlast derselben Kennung und konkurrierende Revision liefern 409.

Der alte Endpunkt darf weiterhin kompatibel reagieren, wenn er einen echten
vollständigen Eröffnungsbefehl ausdrücken kann. Leerer Grund oder fehlender
Fassungsbezug darf nicht mehr still als erfolgreicher vollständiger Vorgang
gelten. Für neue Clients JSON-DTO statt vertraulicher Gründe in der URL.
Bestehende `disputed`-Perioden werden als **Altstatus ohne vollständige Akte**
angezeigt. Migration erfindet keinen Grund, Actor, Eingangszeitpunkt oder
Beleg. Eine nachträgliche Ergänzung kennzeichnet den tatsächlich späteren
Erfassungszeitpunkt und belässt frühere Abrechnungsoriginale unverändert.

Statuskomposition ausdrücklich prüfen: Der heutige Gesamtperiodenstatus
blockiert auch Aktionen anderer Mietparteien. Die neue Akte soll ihre konkrete
Einzelabrechnung identifizieren. Globale Sammelaktionen benötigen eine
Vorprüfung mit betroffenen IDs und handlungsfähigem Ergebnis, ohne erledigte
Originale oder unbeteiligte Einzelabrechnungen still umzuschreiben.

## Lesen, Oberfläche und Aufbewahrung

Neue API unter `/billing/disputes`: konkrete Akte lesen, Originalereignis
abrufen, Journal nach Revision blättern, gefilterte offene Akten nach
Immobilie/Periode/Mieter anzeigen, eröffnen und Ereignis bestätigen.
SQL-Filter und Keyset-Seiten statt vollständigem Gesamtbestand. Keine feste
Höchstzahl über die Lebensdauer; Belege werden gestreamt und überprüft.
`Cache-Control: private, no-store`; Scopefehler verraten keine fremden Akten.

UI: Abrechnung → Beanstandung erfassen → Grund/Eingang/Originalanlagen prüfen
→ bestätigen. Nach Änderungen Entwurf erhalten und Konflikt verständlich
auflösen. Detailseite zeigt Chronik, konkrete damalige Fassung, Originalbelege,
aktuellen Prüfstand und bewusst verknüpfte Korrekturabrechnung. Rollen beachten;
keine Umsetzung eines Buttons ohne tatsächlichen Speichernachweis.

Recovery führt vollständige Familien, Parent-/Self-FK-Reihenfolge, Datumsfelder,
Quittungen, Hashketten und unveränderliche Belege auf. Reiner Validator vor
Veröffentlichung des Restores, Trigger/FKs gegen Originalüberschreibung.
Privacy verwendet exakte aktuelle/eingefrorene Mieterbezüge; Akten anderer
Mietparteien und gemeinsame Befehlsinhalte bleiben ausgeschlossen. Vorschau
der Anonymisierung nennt erhaltene Originaltexte und Anlagen ausdrücklich.

## Kleine Umsetzungspakete und Abnahme

1. DTO/Schema/reiner Validator und echte leere/historische SQLite-/PG-Migration.
2. Atomarer Dienst mit Account-/Scope-/Idempotenz-/Revisionsprüfungen,
   Original-/Journalabruf und tatsächlicher Abrechnungsfassungsbindung.
3. API-Komposition und Altstatusbehandlung; endgültige Statusregeln im Kontext
   von Zustellung, Korrektur und Forderungsbuchung verifizieren.
4. Recovery/Privacy/Parentguards einschließlich Scope-Vollständigkeit.
5. Formular, Chronik, Arbeitsübersicht und echter Browserdurchlauf.

Pflichtgegenbelege: Grund und Anlagen nach Neustart unverändert; falsche
Abrechnungsrevision reparierbar abgewiesen; paralleles Eröffnen/Notieren;
verlorene Rolle oder Token vor Commit; exakte Wiederholung ohne doppelte Akte;
Berichtigung behält altes Original; bestehender Altstatus erfindet keine
Historie; unabhängiger Nachmieter bleibt aus Exporten heraus; Korrekturabrechnung
verweist nachvollziehbar auf Anlass und unverändertes Original; echtes
Backup/Restore mit Anlagenhash; offene Akten über mehrere Jahre paginierbar.

Erst nach diesen Belegen als vollständiges Widerspruchsjournal ausweisen.
