# Immobilienexport aus einer gebundenen Caller-Verbindung

Der unabhängige Source-Review fand eine tatsächliche Vertragsabweichung:
JSON normalisiert einen nativen Connection-Bind zu dessen Engine, der
gemeinsame CSV-Kern liest danach erneut den ursprünglichen Connection-Bind.
Eine SQLAlchemy-2-Connection besitzt kein `connect()` für den neuen Snapshot.

Zuerst wird der unveränderte Produktpfad mit einer wirklichen Connection,
Callertransaktion, ungeflushten ORM-Änderung und aktuellen SQL-Benutzerrechten
geprüft. Der CSV-Adapter soll dieselbe bereits geprüfte Engine ausdrücklich
an den gemeinsamen Export übergeben. Die optionale Ergänzung erhält dessen
bisherige Aufrufer; sie ersetzt keinen Caller-Bind und verändert keine
Callertransaktion. Snapshot und frische Veröffentlichung bleiben getrennt.

Nach der kleinsten Korrektur folgen derselbe native Gegenfall sowie die
bereits bestehenden gemeinsamen Exportprüfungen für Einheiten, Dokumente
und Instandhaltung. Dies ist kein Beleg für andere Betreiberkonfigurationen
oder eine gemeinsame Produktfreigabe.
