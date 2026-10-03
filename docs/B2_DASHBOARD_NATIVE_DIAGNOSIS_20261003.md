# B2: tatsächlicher SQLite-Browserbefund vor gezieltem Nachlauf

03.10.2026, eingefrorene eigene Quelle
`60e915a0f58e2e5afdd965a3e282d6ba0f0f07e3`. Ein freigegebener Edge-Lauf,
ein Build, eine migrierte eigene SQLite-Datenbank, ein Backend, ein Worker.
Keine Quelle während des Laufs verändert. Normales Runner-Finally schloss
Backend/Browser und löschte den eigenen Tempbereich; kein Prozess blieb offen.

## Individuelle Ergebnisse

| Tatsächlicher Fall | Ergebnis | Laufzeit |
| --- | --- | --- |
| B2 vollständiger 10.001er-Bestand und drei Hinweisfamilien | FAIL: fünf Benachrichtigungen fehlen | 18,4 s |
| B2 genauer Kontext, A→B-Abbruch, echte Rechte-/Grantänderung und 403 | PASS | 20,4 s |
| B2 echte Leere, verlorene native Antwort, älterer Stand und natives Cursor-422 | PASS | 26,2 s |
| Bestehender vollständiger FinCashflow mit neuer Root-CSS | PASS | 23,1 s |

Gesamt **3 PASS, 1 FAIL**, keine Skips, etwa 1,6 Minuten. Build 3,19 s und
echte Alembicmigration bis k2 sowie der opt-in SQL-Seed waren erfolgreich.
10.001 Einheiten, Verteilung 4.001 belegt / 2.000 leer / 2.000 reserviert /
2.000 andere sowie die echte letzte Unit wurden vor dem späteren Fehler
geprüft. Aufgaben wurden vollständig durchblättert. Die Vertragsfamilie und
nachfolgende Auswertungs-/Dunkelbilder wurden im ersten Fall nicht erreicht;
sie werden hier nicht als bestanden behauptet.

## Aus gesicherten Antworten belegte Ursache

Der Fehler betrifft die echte B1-SQL-Keysetseite der Benachrichtigungen.
Der Browser sendete den unveränderten, vom Backend ausgegebenen `next_after`;
die Assertions an Cursor/`as_of`/Seitenbudget wurden erfüllt. Der nächste
native GET antwortete erfolgreich mit nur drei Zeilen und `has_more=false`.

Die 13 echten Notification-POSTantworten liefern folgende Erstellungszeiten:

| Synthetische Notice-Nummern | Tatsächliches `created_at` |
| --- | --- |
| 0, 1, 2, 3 | `2026-10-03T17:45:45` |
| 4, 5, 6, 7, 8, 9 | `2026-10-03T17:45:46` |
| 10, 11, 12 | `2026-10-03T17:45:47` |

Die erste native Seite enthält Notice **0, 1, 2, 3, 6**. Der signierte Cursor
enthält exakt die Position
`["2026-10-03T17:45:46", "3e06272c-fd27-46c9-a111-41f6bb729980"]`.
Die nächste native Seite enthält **10, 12, 11**. Genau die weiteren fünf
Zeilen der Cursorsekunde fehlen:

| Notice | Tatsächliche ID |
| --- | --- |
| 4 | `e487b403-cd19-4247-a310-10cc9634674a` |
| 5 | `4cba68ce-1369-4d02-a781-3e79cf3f7302` |
| 7 | `9557855d-c20e-4154-bff6-e9a40ef47054` |
| 8 | `86debc31-01d0-4cf1-81aa-6e78b636805c` |
| 9 | `c8a16fb6-41ce-4991-8a3c-073c3b424bc3` |

Quellenabgleich: `backend/services/dashboard_summary.py:192–195` bindet die
sekundengenaue Cursorzeit als normale SQLAlchemy-DateTime. SQLite vergleicht
die durch `CURRENT_TIMESTAMP` gespeicherte Form ohne Nachkommastellen mit der
gebundenen Form `.000000`; die gleiche Sekundenzeit trifft den Equalityzweig
nicht. `NotificationORM.created_at` verwendet `func.now()` in
`backend/db/orm_models.py:640`. Derselbe Speicherdarstellungsunterschied ist
für CAS bereits in `backend/repositories/base.py:105–113` beschrieben.

Der bestehende B1-Gleichstandstest
`backend/tests/test_dashboard_summary.py:182–190` erzeugt zunächst einen
echten Storeeintrag, fügt aber die Klone als normale DateTime-Binds mit
Nachkommastellen ein. Er deckt diese beim tatsächlichen POST entstandene
Sekundengruppe nicht vollständig ab. Root/Domain besitzen den kleinsten
Backendfix samt Mischdarstellungs-/Mikrosekundenregression. Kein Backendpatch,
kein Seedzeit-Überschreiben und keine gelockerte ID-Erwartung durch B2.

## Erhaltene Belege und tatsächliche Sichtung

Der ganze erste Ergebnisordner wurde vor einem möglichen Nachlauf erhalten:
`C:/Users/matth/Documents/Codex/2026-10-01/wi/artifacts/B2_DASHBOARD_UI/first-60e915a/test-results`.
Fehlertrace, Netzwerkantworten, Fehlersnapshot und Bild:
`dashboard-bounded.pw.mjs-B-16bff-eysets-reach-all-real-hints/`.

**28 unterschiedliche PNGs tatsächlich angesehen**, ohne angehängte Kopien
doppelt zu zählen: 24 B2-Bilder aus den zwei grünen Fällen, drei Financebilder
und ein Fehlerbild. Kontext/Nullscope/älterer Stand/Neustart wurden bei
1440/360/320 aufgenommen. Lange aktuelle Eltern-/Unitnamen umbrechen;
Fehler und älterer Stand bleiben sichtbar; die normale Seitenbreite wurde
streng geprüft. Finance-Datum-/Referenzfelder haben die Root-CSS und die
großen Tabellen scrollen innerhalb ihres Containers.

Eine zusätzliche `B2-exact-context-360-detail.png` ist leer; sie gilt nicht
als brauchbarer Detailnachweis. Das vollständige 360er-Bild und die
320er-/1440er-Detailbilder zeigen den tatsächlichen Kontext. Der bestehende
globale Header/NotificationBell liegt außerhalb des B2-Besitzes: nach dem
Grantentzug bleibt in diesem Lauf sein vorheriger Badgewert 10 sichtbar,
während die B2-Ansicht die eigenen privaten Daten vollständig ausblendet.
Dieser konkrete separate Legacy-Grenzbefund wurde Root gemeldet.

Erst nach tatsächlichem Backendfix/Gate und Rootslotfreigabe wird genau der
fehlgeschlagene erste B2-Fall selektiert erneut ausgeführt. Die drei grünen
Fälle werden ohne neue relevante Änderung nicht breit wiederholt.

## Selektiver tatsächlicher Root-Nachlauf

2026-10-03, eingefrorener Integrationsstand `599bfb0`, einschließlich echtem
SQLite-Keysetfix `4f22733` sowie verschlüsselter Runtimefactory und dauerhaftem
Launcher-Schlüsselbundle. Genau der vorher fehlgeschlagene erste Fall wurde
erneut ausgeführt: **1 PASS, 15,6 Sekunden Fall / 17,4 Sekunden Playwright**,
ein Worker, keine Wiederholungen oder Skips. Der Runner baute die Oberfläche,
migrierte die eigene frische SQLiteinstallation tatsächlich bis k2, startete
den echten Backendlauncher mit ausdrücklicher Erstinitialisierung und säte
10.001 Einheiten. Seine eigenen Backendprozesse wurden im finally beendet und
sein eigener temporärer Installationsordner nach Kopie des Logs entfernt.
Es gab keinen harten äußeren Gesamtprozess-Timer; Metadatenschritt 10 Sekunden,
Backendbereitschaft 90 Sekunden und Browserfall 120 Sekunden waren begrenzt.

Vollständige Belegung, letzte echte Unit sowie **alle 13 eindeutigen IDs jeder
der drei Hinweisfamilien** wurden mit unveränderten nativen Antwortcursoren
erreicht. Keine alten Vollbestands-/Hinweislistenabfragen und kein Tenant-N+1.
Die anschließend echten sechs unabhängigen Auswertungen, Tabellenbedienung,
Tastaturseitenwechsel, Mobilbreiten und dunkle Ansicht wurden nun ebenfalls
erreicht. Die anderen drei grünen Fälle wurden nicht breit wiederholt.

Gesicherte Belege:
`C:/Users/matth/Documents/Codex/2026-10-01/wi/artifacts/B2_DASHBOARD_UI/root-599bfb0/test-results`.
Root hat drei neue vollständige Bilder tatsächlich angesehen:
`B2-complete-work-320.png`, `B2-analysis-360.png` und
`B2-analysis-dark-1440.png`. Ruhige Karten, lesbare Zeilen und getrennte
Hinweisseiten; die mobile Auswertungstabelle scrollt in ihrem eigenen Bereich.
Die alte Header-Badgebegrenzung auf 10 bleibt als separates bekanntes Problem
offen. Diese Sichtung ist keine allgemeine Abnahme aller 18 neuen PNGs oder
des gesamten Produkts. PostgreSQL-Keysetnachprüfung und gemeinsame Freigabe
sind weiterhin separate offene Gates.
