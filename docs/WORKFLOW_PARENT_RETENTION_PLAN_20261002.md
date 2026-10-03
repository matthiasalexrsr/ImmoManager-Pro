# Retain the live scope parents of frozen workflows

The offline review found that ordinary Property.portfolio_id and Unit.property_id
edits can move the live parent while published templates and started changes keep
their immutable original portfolio/location. Contract relocation has the same
problem. A legitimate edit must never make later recovery reject an image created
by normal application actions.

Before changing these actual location fields, the ordinary Memory lock or SQL
parent-first writer locks must check for retained template/change references and
refuse an unsupported relocation with an actionable message. Metadata edits,
unreferenced parent moves, and a permitted later contract-tenant correction remain
available. Deletion must also preserve any portfolio/property/unit/contract and
historical tenant still referenced by a frozen change. A historical tenant link
comes from the original snapshot, not the contract's current tenant.

Implement a small read-only existence helper, without auth lookups, new locks,
commits or a new table family. SQL uses bounded existence queries after the
existing parent locks, including pending new facts. Memory uses the existing
shared lock. Both reject before DML and keep ordinary privacy/payment/lifecycle
guards. An entirely absent legacy family remains compatible.

First reproduce ordinary parent relocation on synthetic fixtures, then verify
Memory, SQLite and actual PostgreSQL. Check template-only and started references,
historical deletion after party correction, and allowed unrelated/metadata edits.
Run the composed recovery cases and scoped mutation regressions after integration.
## Ergänzung nach unabhängiger Prüfung: vorgemerkte SQL-Änderungen

Die unveränderte unabhängige Probe reproduziert sechs Fehler mit explizit
aktiviertem SQLAlchemy-Autoflush in SQLite und PostgreSQL. Schon vorgeschaltete
Existenzprüfungen, der erste Parent-Lock-Lookup oder der Delete-Subject-Lookup
können eine vorgemerkte Vorlage schreiben, bevor der Retentionsguard sie erkennt.
Die normale Anwendungssitzung deaktiviert Autoflush; native Sitzungen bleiben
dennoch unterstützte Aufrufer und müssen dieselbe Vorprüfung gewährleisten.

Vor der Korrektur festgelegt: die ganze betroffene Repository-Vorprüfung unter
`Session.no_autoflush` ausführen, einschließlich Property-/Unit-/Contract-
Parentprüfungen und Portfolio-Delete-Subjectprüfung. Auch die beiden direkt
aufrufbaren SQL-Integritätsguards erhalten diese Grenze. Explizites Schreiben,
Flush und bestehende Commitzuständigkeiten bleiben nach bestandenen Prüfungen
unverändert. Die Grenze setzt weder Sessionkonfiguration dauerhaft um noch führt
sie einen eigenen Commit/Rollback ein. Die unveränderte unabhängige 24-Case-Probe
und ihr tatsächlicher Zwei-Session-PG-Wettlauf müssen anschließend bestehen.

## Nachgewiesene Ergebnisse

- Die korrigierte unveränderte unabhängige Probe bestand 19 Fälle; acht
  Memory-/Nicht-PG-Varianten wurden mit konkretem Grund übersprungen. Darin
  enthalten: alle zwölf Autoflush-/Operation-SQL-Varianten auf SQLite und PG
  sowie der tatsächliche Zwei-Session-PG-Wettlauf. Vorher waren sechs Fälle rot.
- Die zusammengesetzte Parent-/bestehende SQLStore-/Payment-/Bankpayment-/
  Lifecyclegruppe bestand 130 Fälle, drei erwartete Varianten wurden
  übersprungen (226,18 Sekunden). Sessionkonfiguration, explizite Flushes und
  bestehende Commitzuständigkeit bleiben erhalten.
- Die Parent-/verschlüsselte Recoverygruppe bestand zuvor 18 Fälle; die
  zusätzliche ganze-/teilweise Familienprüfung bestand separat 19 Fälle mit
  zwei reinen Memory-Schema-Skips.
- Sechs neue/geänderte Repository-/Guardmodule bestanden die konfigurierte
  Typprüfung für Python 3.11. Der unabhängige Bericht und unveränderte Probe
  liegen außerhalb des Produktrepos unter `work/workflow-parent-retention-
  independent-review.md` bzw. `work/test_workflow_parent_independent_probe.py`.

Die übernommene Produktregression ergänzt die unabhängige Probe um den Beweis,
dass vorgemerkte Daten, laufende Callertransaktion und deren Autoflush-Einstellung
nach der Ablehnung erhalten bleiben. Dieser zusätzliche aktuelle Gate wird
gesondert im Releaseprotokoll festgehalten.
