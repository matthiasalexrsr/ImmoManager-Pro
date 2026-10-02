# Prüfstände für Release 127

Stand: 2. Oktober 2026. Die Ergebnisse gehören jeweils zum genannten Sourcezustand. Die laufende Vorschau verwendet weiterhin Release 126. Neue Mieterwechsel- und Jobbausteine sind im Integrationsbranch zusammengeführt; ihre Runtime-/Recovery-/Browserabnahme ist noch in Arbeit.

## Eingefrorene breite Basis

| Source / Konfiguration | Tatsächliches Ergebnis | Grenze |
| --- | --- | --- |
| `da8678b`, kompletter Backendlauf Memory | 3.920 bestanden, 188 übersprungen; 4 Warnungen; 4.212,31 Sekunden | Übersprungene optionale Umgebungen werden nicht als geprüft gezählt. |
| `da8678b`, kompletter Backendlauf Strict SQLite | 3.918 bestanden, 2 fehlgeschlagen, 188 übersprungen; 4 Warnungen; 4.515,89 Sekunden | Beide Fehler: Outbox-Prozessabbruchtests überschritten unter paralleler Last die unveränderte 15-Sekunden-Prozessfrist. |
| derselbe `da8678b`, isolierter Gegencheck beider SQLite-Abbruchtests | 2 bestanden; 15,09 Sekunden | Keine Source-, Assertion- oder Friständerung. Der ursprüngliche breite SQLite-Lauf bleibt ein Lauf mit zwei Fehlern. |
| `258d264`, sieben tatsächliche PostgreSQLgruppen | 39 bestanden, kein Skip; 182,79 Sekunden | Dedizierter PostgreSQL 16.15, zufällige exklusive Schemata; Lifecycle, Korrespondenz, Portfolio/Privacy, Dokumentversionen und Recovery. |
| `258d264`, TEHA-Beobachtung und private Integrationsgrenze zusammen | 225 bestanden; 98,90 Sekunden | Vollständige private JSON-Beobachtung und Integrationsrouter; kein neuer Live-TEHA-Geschäftsschreibtest. |
| `7ccee8c`, echte Edge-/SQLite-Browserabnahme | 68 bestanden | Der UI-Stand ist vor dem neuen Mieterwechsel-Frontend und vor der zusätzlichen privaten Integrationsgrenze. |

Sechs frühere PostgreSQLfehler hatten eine gemeinsame Testfixture-Ursache: Sie bereitete nur `z1` vor, während bereits vorhandene Privacy-/Resetdienste die Correspondence-Familie `a2` benötigten. Der reine Fixturefix `807eb7b` wurde als `258d264` übernommen. Alle sechs ursprünglichen Fälle und anschließend alle sieben PostgreSQLgruppen bestanden. Es wurde keine Produktionsprüfung oder Assertion entfernt.

Nachweise außerhalb des Produktrepos: `work/release127-backend-full-memory-da8678b.log`, `work/release127-backend-full-sql-da8678b.log`, `work/release127-outbox-crash-sql-recheck-da8678b.log`, `work/release127-native-postgres-258d264.log`, `work/release127-adapter-composition-258d264.log`, `work/release127-browser-full-scoped-final.log`.

## Neue gelieferte und separat geprüfte Bausteine

- Referenzdienst `334d3db`, integriert als `3046d57`: 24 bestanden, zwei modusabhängige Skips; darunter zwei tatsächliche PostgreSQLtests. Memory-Race mit gewöhnlichen Anlegepfaden unabhängig reproduziert und nach Korrektur erneut bestanden. SQL-Suche erreicht den Treffer nach 10.003 Datensätzen ohne Vollabruf und mit begrenzter Ergebnisseite.
- Mieterwechselkern `2cad91f`, integriert als `ce01a5f`: gelieferte Kern-/Skalengruppe 48 bestanden, zwei reine Memory-Trigger-Skips; zusätzlicher relevanter bestehender Bereich 51 bestanden, ein Skip. SQLite und tatsächlicher PostgreSQL-Auf-/Abstieg bis `b2` bestanden. Der unabhängige Review fand zwei konkrete Fehler an Receipt-Pfadbindung und Meter-UPDATE-Elternschutz; Root korrigiert und prüft sie im zusammengesetzten Stand.
- Operative Arbeitspakete `4cc21de` + `45026b5`, integriert als `7d6033d` + `c27ebf2`: Memory und Strict SQLite jeweils 97 bestanden, acht erwartete Skips; getrennt vier tatsächlich ausgeführte PostgreSQLtests, kein Skip. Später Sessionwiderruf vor Commit, UTC-Leaseablauf, Fenceübernahme und 64-Bit-Zähler nachgewiesen. Unabhängiger Nachtragsreview ohne Restbefund im angefragten Umfang. Diese Phase ist kein vollständiger Schedulerersatz.
- Workflowoberfläche `bd348217` → `8fa4e645` → `08d608783`, integriert bis `69ec16a`: 39 passende Workflowtests bestanden, ESLint und Build bestanden. Gesamte Frontendsuite 980 von 981 bestanden; der unveränderte ContractWorkspace-Cursortest überschritt unter Parallelbelastung sein festes 5-Sekunden-Limit. Derselbe Test bestand unverändert einzeln in 2,362 Sekunden. Kein vollständiger grüner Gesamtlauf behauptet. Dokumentrichtungsfilter wird durch den bisherigen Frontend-Assistenten passend zum tatsächlich implementierten Backend korrigiert.

Die Laufzeiteinbindung, lineare Migration `a2 → b2 → c2`, Tokenprüfung unmittelbar vor eigenem Commit, ganze optionale Recoveryfamilien und Retention-/Resetgrenzen werden in einem folgenden exakt identifizierten Integrationsstand abgenommen. Breite ältere Ergebnisse sind keine Freigabe dieser neuen Pfade.

Root-Laufzeiteinbindung und Korrekturen: 21 bestanden, zwei reine Memory-DBtrigger-Skips in 60,93 Sekunden, einschließlich sechs tatsächlich ausgeführter PostgreSQLfälle. Nachgewiesen sind die vollständige HTTP-Akte bis zum Abschluss auf Memory/SQLite, echter JWT-Ablauf nach Geschäfts-DML mit Rollback und unverändertem Retry, tatsächlicher persistenter PostgreSQL-Sessionwiderruf nach INSERT, lineare PostgreSQLmigration `a2 → b2 → c2 → a2` mit erhaltenen Altdaten, Startupablehnung teilweiser Familien vor DML sowie Receipt-/Meter-/Template-Reparentregressionen. Der unabhängige Korrekturreview bestätigte zusätzlich zehn Fälle mit zwei reinen Memory-Trigger-Skips; ursprünglicher Memory-Replay nun 409 statt fremdem Beleg, beide SQL-Parentguards einschließlich PostgreSQL wirksam. Zwanzig neue/geänderte Produktionsmodule bestanden Mypy für Linux/Python 3.11. Die späteren Recovery-/Resetänderungen und echte Browserabnahme sind noch nicht Bestandteil dieses Nachweises.

Eine zusätzliche, nicht als CI-Gate konfigurierte Typprüfung sämtlicher Backend-Testdateien fand 499 Typmeldungen in 124 Dateien. Viele Tests verwenden absichtlich rohe JSONwerte oder vereinfachte Fixtureobjekte. Dieses Ergebnis wird nicht als bestandene Typprüfung bezeichnet; die konfigurierte Produktionsgruppe und die gezielt veränderten Runtimequellen werden gesondert geprüft. Eine dabei sichtbare Typinkonsistenz im neuen generischen Meter-Anlegeguard wurde mit derselben Modeldump-Grenze wie bei anderen Anlegeguards korrigiert.

Die vollständige konfigurierte CI-Produktionsgruppe bestand danach: 112 Zielargumente, 131 geprüfte Quelldateien, keine Typfehler. Der konfigurierte gesamte Rufflauf über Backend und die beiden vorgegebenen Betriebsskripte bestand. Der typisierte Meter-Anlegeguard wurde anschließend mit sechs tatsächlichen Memory-/SQLite-/PostgreSQLfällen für Handovers, Ablesungen und Aufgabenrollback erneut geprüft; alle sechs bestanden. Die korrigierte Dokumentauswahl `0ba440b`, integriert als `1d4bf7e`, bestand 14 passende Frontendtests und ESLint beim bisherigen Frontend-Assistenten.

## Adapterbeobachtung

TEHA hat 74 statisch aus dem öffentlichen Client abgeleitete Aufrufstellen im versionierten Katalog. Statische Aufrufstellen sind ausdrücklich weder live bestätigte Schnittstellen noch ausgeführte Schreibaktionen. Der Transport hatte zuvor sechs echte lesende Portaloperationen auf dem freigegebenen Konto bestätigt, einschließlich eines bytegleich geprüften PDFs. Die jüngere Vollbeobachtung vor der DTO-Auswertung ist mit synthetischen vollständigen, unbekannten und späten JSON-Feldern geprüft; ein erneuter echter Portallauf dieses jüngeren Stands wurde bisher nicht durchgeführt.

Die Beobachtung erfasst vollständige fachliche Antwortkörper sowie Parameter, Requeststruktur und Metadaten; Zugangsdaten, Sitzungstoken und Cookies werden dabei nicht zu gewöhnlichen Logs oder Produktquelltext. Installationsweite private Integrationskonfigurationen sind nur für Eigentümer oder Verwalter mit Zugriff auf alle Portfolios zugänglich. WISO Steuer für Windows ist auf diesem Rechner weiterhin nicht installiert; ein tatsächlicher Import in diese Zielanwendung bleibt unbestätigt.
