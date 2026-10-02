# Gemeinsame Vertragsübersicht und sichere Bearbeitung

Lokale Abnahme vom 2. Oktober 2026 auf Basis des veröffentlichten `f3203d5`.
Backend, Oberfläche, Produktionsrouter, Einstellungen, beide Serverprofile,
verschlüsselte Serversicherung und CI-Registrierung sind gemeinsam integriert.
Dieses Dokument unterscheidet tatsächlich ausgeführte lokale Prüfungen von
weiter ausstehender vollständiger CI und echter neuer PostgreSQL-Ausführung.

## Nutzbarer Ablauf

Unter **Verträge** Suche, Status, Zeitraum und Ansicht wählen und **Filter
anwenden** benutzen. Alle Bedingungen gelten vor der serverseitigen
Seitenauswahl. Vorherige/nächste Seite laden begrenzte autorisierte Datensätze;
es gibt keine Gesamtbestandsgrenze. Namen und aktuelle Einheitskaltmiete kommen
aus derselben autorisierten Abfrage. Die Oberfläche erklärt den Unterschied
zwischen aktuellem Einheitswert, historischen Forderungen und Mietanpassungen.
Der CSV-Download umfasst ausdrücklich nur die sichtbare Seite.

**Bearbeiten** erhält auch ausgewählte Referenzen jenseits der ersten 100
Einträge. Suchbare Formularauswahlen laden begrenzte Seiten; die Einheit bleibt
an die Immobilie gebunden. Die genaue ursprüngliche ETag-Revision schützt PUT
und DELETE. Nach 412 bleibt die lokale Eingabe erhalten; erst **Aktuellen Stand
prüfen** und **Abgleich übernehmen** ersetzen bewusst die Payloadrevision.
Ein Listenrefresh, Lesefehler oder leere Seite verliert offene private Dialoge
nicht. Konto-/Rechtewechsel schließen sie und verhindern alte späte Antworten.

Seiten-/Suchbudgets sind positive konfigurierbare Ressourcenbudgets:
`CONTRACT_WORKSPACE_PAGE_MAX_SIZE` (Standard 500) und
`CONTRACT_WORKSPACE_SEARCH_MAX_CHARS` (Standard 200). Auch größere positive
Werte sind zulässig; gespeicherte Daten werden nicht abgeschnitten. Ein zu
langer Suchtext oder ungültiger/abgelaufener Cursor bietet einen konkreten
Korrekturweg. Ein Cursor bindet Query, Actor, Grants, Sortierung, Seitengröße
und das erste Bezugsdatum; die Seitenfolge ist kein eingefrorener Bestandsexport.

## Tatsächliche Prüfungen

| Umfang | Ergebnis |
| --- | --- |
| Gesamtes gemeinsames Frontend | 899 bestanden, 70 Dateien |
| Workspace-/Lifecycle-/Refresh-Dialogfokus | 37 bestanden |
| Echter frischer SQLite-/Edge-Server: Workspace, Lifecycle und Sitzungen | 7 bestanden |
| Gemeinsam registrierter Produktionsrouter, Workspace/Suche/Datumsfilter/Portfolio | 121 bestanden, 8 explizite Skips |
| Fehlendes Ziel, ETag, konkurrierende Bearbeitung und Korrektur einer fehlenden vorgeschlagenen Referenz | 52 bestanden, 4 explizite Skips |
| Abschließende Bearbeitungs-/CRUD-Auswahl nach zusätzlicher Cascade-Korrektur | 365 bestanden, 3 explizite Skips |
| Workspace-/Unicode-/Real-Auth-RLock-Auswahl im Memory-Prozess | 81 bestanden, 1 expliziter Skip |
| Kapazitätseinstellungen | 21 bestanden |
| Privates Serverprofil und verschlüsselte Serversicherung | 95 bestanden |
| Lifecycle/Datenschutz/Reset/Recovery samt echten Auth-/RLock-Regressionen | Memory und SQL jeweils 163 bestanden, 8 explizite Skips |
| CI-Mypy 2.4.0: Linux/Python3.11 und Windows/Python3.12 | je 123 registrierte Quellen ohne Fehler |
| Ruff, globaler ESLint, Produktionsbuild, JavaScript-Syntax | bestanden |

Die Browserprüfung legt 106 eigene synthetische Verträge samt Referenzen über
die normalen authentifizierten Produkt-APIs an. Die alte First-100-Abfrage
enthält den letzten Vertrag tatsächlich nicht. Die neue Tabelle zeigt alle
106 über fünf Seiten ohne Duplikate, findet ihn per Immobilienname und erhält
seine genauen Formularreferenzen. Sie benutzt keine vollständigen Contracts-/
Property-/Unit-/Tenant-Abfragen. CSV und 320/360-Pixel-Geometrie wurden geprüft;
das mobile Browserbild wurde zusätzlich visuell kontrolliert. Escape führt zum
ursprünglichen Bearbeiten-Button zurück.

Ein weiterer echter Browserfall führt eine konkurrierende Serveränderung aus:
der erste PUT erhält 412, der lokale Vertragsnummernwert bleibt erhalten,
bewusster Abgleich verwendet die neue ETag, der zweite PUT erhält 200 und
bewahrt die zwischenzeitliche Servernotiz. Zwei Lifecycle-Fälle prüfen
Antwortverlust und exakten Replay; drei Sitzungsfälle prüfen Rechte und
Kontowechsel. Alle laufen auf einem eigenen frisch migrierten Testserver.
Die bestehende Vorschau und ihre Geschäftsdaten werden dabei nicht verändert.

Der Memory-Sperrentest verwendet den echten Auth-Store und die tatsächlichen
Account-/Domain-RLocks in einem eigenen Kindprozess. Derselbe Teststand war
auf `f3203d5` mit zwei blockierenden Create-/Confirm-/Privacy-Abläufen rot;
nach Verwendung des bestehenden account→domain-Kontexts durch Lifecycle.work
bestanden alle vier Fälle. SQL-Session, Writerbarriere und Commit bleiben
unverändert. Die gemeinsame 163-Fälle-Auswahl belegt auch Undo und Recovery.

## CI #125 und verbleibende Nachweise

Der vorherige veröffentlichte Lauf ist insgesamt fehlgeschlagen. Die
fehlende Immobilie lieferte 400 statt des bisherigen 404, weil der neue
Parentguard vor der Zielprüfung sperrte. Der Guard prüft jetzt nach Eintritt
in die Writerbarriere den autorisierten Parent. Bei vorhandenem bedingtem
Edit und gelöschtem Ziel bleibt 412 erhalten; eine fehlende vorgeschlagene
Referenz bei noch vorhandenem Ziel wird weiterhin als solche gemeldet.
Eine unabhängige Prüfung fand zusätzlich alte Property-/Unit-PUTs nach dem
Löschen ihres gesamten Portfolios. Derselbe neue Teststand war mit zwei
SQLite-Fehlern und sechs bestandenen Varianten rot. Der fehlende Elternbezug
prüft jetzt zuerst, ob das bearbeitete Ziel durch Cascade ebenfalls gelöscht
wurde. Bedingte Formulare erhalten 412, alte unbedingte Aufrufe 404; eine
vorhandene Zeile mit ungültigem vorgeschlagenem Parent behält ihren
Referenzfehler. Die abschließende 365-Fälle-Auswahl und der identische
unabhängige echte Memory-/SQLite-Cascadeprobe bestanden.

Die lebende Dokument-PG-Fixture migriert jetzt die aktuelle Schema-Version;
eine separate reine Altformatprüfung bewahrt die y1-Kompatibilität. Die
terminalen alten Jobdaten stehen in `release125-verification.json`.

Sieben neue Workspace-PostgreSQL-Fälle sind im unabhängigen CI-Service
registriert. Lokale Skips und der SQL-Compilervergleich beweisen keine echte
PG-Ausführung. Neue vollständige CI, diese sieben Fälle und unabhängige
Containerprüfungen bleiben erforderlich. G06.2-Korrespondenz und Fristen werden
separat entwickelt; WISO-Steuer-Import und EXE sind hier nicht als geprüft
behauptet.
