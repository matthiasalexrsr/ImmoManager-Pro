# Tatsächliche native Fixturekorrektur vor dem Elternwechsel

Root meldet für die unveränderte fachliche Quelle 56 PASS, vier ausdrücklich
nicht anwendbare Memory-Skips und einen SQLite-Page-FAIL in 40.59s. Der echte
SQLAlchemyStore.update_property erreicht payment_integrity und importiert
erst dort die Lifecyclemodelle. Die eigene Testdatenbank wurde zuvor mit
Base.metadata.create_all aufgebaut; contract_lifecycle_drafts fehlt. Der
spätere Summaryfall profitiert vom inzwischen veränderten Prozessmetadata.
Das ist kein grüner unabhängiger Page-Elternwechselbeleg.

Die Fixture registriert vor jedem native_metadata/create_all ausdrücklich die
realen LIFECYCLE_MODELS, CORRESPONDENCE_MODELS und TENANCY_WORKFLOW_MODELS.
Quellgrund: payment_integrity._guard_sql_lifecycle_edit ruft bei einem echten
Portfolio-Wechsel guard_delete_link von Lifecycle und Korrespondenz sowie
workflow_parent_guards.guard_parent_edit auf. Die ersten beiden fragen ihre
echten Tabellen direkt ab; die dritte prüft die gesamte Mieterwechselfamilie.
DocumentVersionORM bleibt als bereits nötige FK-Metadatenregistrierung erhalten.
Alle Modelltabellen werden vor create_all in Base.metadata geprüft. Kein
Authgetter, Writer, Guard oder die erwartete 409-Publicationassertion wird
ersetzt oder abgeschwächt. Das ist Fixture-DDL, kein Migrationsnachweis.

Zusätzlich wird der bereits vorhandene, unverändert synthetisch befüllte
10.002er-Fall um vollständigen scoped CSV-Export mit chunk_size=200 ergänzt.
Die globalen list_*-Fallen bleiben während Export und Walk aktiv. Assertions:
exakt dieselben 10.002 IDs in Reihenfolge, kein verborgenes USD-Objekt, letzter
Datensatz property-10001 und keine interne _rent_cents-Spalte. Die Ergänzung
ist zunächst Testquelle; vorherige grüne Walks belegen diesen Export nicht.

Kein eigener Import-, Collection-, Test-, DB-, Server- oder Browserstart.
Root prüft nach sauberer Übernahme exakt die betroffenen nativen Fälle.
