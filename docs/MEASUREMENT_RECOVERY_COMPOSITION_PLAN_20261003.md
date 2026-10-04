# Historische Messquellen: zentrale Betriebsintegration

Der gelieferte Quellenkern wird in den bestehenden Start- und Wiederherstellungsweg eingebunden. Die vier Tabellen werden vor der Schemaerkennung registriert. Ein normaler Produktionsstart prüft ausschließlich; Installation und Migration bleiben ausdrücklich getrennt.

Die Offline-Prüfung erkennt vollständig fehlende ältere Quellenfamilien, verweigert jedoch teilweise fehlende Tabellen, beschädigte Fremdschlüssel, fehlende Originalschutzregeln und widersprüchliche Originale. Sie liest Quellen je Einheitenakte und nur deren tatsächliche Eltern. Eine SQL-Prüfung erfasst zusätzlich überschneidende physische Zählerzuordnungen über mehrere Einheiten. Kein Gesamtbestand wird abgeschnitten oder als eine globale Python-Liste geladen. Die größte einzelne Akte bleibt vorerst die Speichergrenze des vorhandenen reinen Fachprüfers; eine spätere schrittweise Prüfung einzelner Quellenreihen bleibt erforderlich.

Vollarchive erhalten die vorhandene physische Datenbank einschließlich Originalen und Schutzregeln. Die fachliche Teilübertragung wird weiterhin ausdrücklich verweigert, wenn zurückzubehaltende Historie vorhanden ist. Sicherheitsabschluss und Claim-/Sessionerneuerung erfolgen erst nach erfolgreicher Prüfung sämtlicher Quellen. Die laufende Parentguard-/Datenschutzarbeit des Domain-Assistenten bleibt getrennt.

Abnahme: tatsächliche Memory-/SQLite-/PostgreSQL-Quellen, Roh-SQLite und SQLAlchemy, Korrekturen, beschädigte Hashes, fehlende Tabellen/Schutzregeln, globale Zählerüberschneidung, unveränderte Quellen nach Vollwiederherstellung, verweigerte Teilübertragung und Produktionsstart unter tatsächlich verbotenem DDL. Die Prüfung gilt für den gemeinsamen aktuellen Migrationsstand; historische einzelne Migrationsrundläufe bleiben ausdrücklich benannt.
# Ergänzung 2026-10-03: gemeinsame Parent-/Historyprüfung

Die native PostgreSQL-Komposition nach den Parentguards ergab 19 erfolgreiche
Fälle und acht HistoryRuntime-Fixturefehler. Der tatsächliche Auslöser ist
`f2.upgrade`: `Index(name, table.c...)` hängt bei jedem neuen Upgrade im selben
Prozess ein weiteres gleichnamiges Objekt an das globale ORM-Metadatum. Ein
anschließendes `Base.metadata.create_all` führt dann doppelte CREATE INDEX aus.

Vor der Korrektur festgelegt: f2 erzeugt dieselben bestehenden Indizes über
Alembic `op.create_index`, ohne ORM-Metadaten zu mutieren. Eine tatsächliche
SQLite-Migration mit anschließendem frischen `create_all` in demselben Prozess
prüft den Regressionfall. Der offene gemeinsame PG-Teil wird danach wiederholt.
Nur synthetische Daten; keine automatische Reparatur beim Produktstart.
