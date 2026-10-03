# B2 Dashboard: Quellenübergabe und abgegrenzte Nachweise

03.10.2026, eigener Checkout `work/bounded-dashboard-ui`, Branch
`assist/bounded-dashboard-ui`. Vor-Code-Plan `1cb93fb`, zentral bereits
`ab8c91d`. Root hat B1 nach seinen tatsächlichen nativen Gates freigegeben.

## Produktquelle zur zentralen Übernahme

- `4e3f670`: geprüfte B1-Projektion, vollständige Counts, Statusbelegung und
  Grundpräsenz, eine atomare Summarylane für drei aktuelle Keysetseiten,
  derselbe fehlgeschlagene Query bei Retry, numerischer 422-/Scopezustand.
- `776c302`: eigener privater Dashboardboundary, aktuelle Authprüfung bei
  Fokus/Aktualisieren/Seiten-/Kontextwahl, einzelne bewusst ausgewählte genaue
  Task-/Contractdetails samt geprüften Unit-/Propertyeltern, Abbruch zwischen
  A/B und bei Rechtewechsel, getrennte Reportzustände, lokale Komponenten.
- `5704835`: enges tatsächliches Dashboardwiring, CSS und drei Sprachen;
  überholte getAll-Units-/Tasks-/Notifications-/Expiring-Quellen vollständig
  entfernt. Vorhandene sechs Auswertungen und kanonische Geldsumme erhalten.

Nur eigene Frontend-/Tests-/Dashboardübersetzungen. Shared Auth, API,
FormModal/Drafts, Layout/DataTable, Backend, Registry, Recovery/CI und DDL
unverändert. Root integriert. Kein eigener Root-/Main-/Previewwrite.

Die vier bereits sauberen B1-Abhängigkeiten wurden nur für den eigenen Checkout
übernommen: `c924cf1 → 27c4f2e`, `f1cd91d → 8c34484`,
`f49c895 → 724e9d2`, `617c868 → 1cdcb6c`. **Nicht nochmals integrieren.**
Ihre 47 zusammengesetzten nativen Backendfälle sind Plattformnachweise,
keine eigenen B2-Testläufe.

## Tatsächlich geprüfte UIzustände

Die Oberfläche verwendet ausschließlich den echten B1-Vertrag
`GET /dashboard/stats`, `preview_limit`, `as_of`, `tasks_after`,
`notifications_after`, `contracts_after`. Jede Query sendet alle aktuell
ausgewählten Familiencursor. Nur drei aktuelle begrenzte Seiten werden
gespeichert; Rückwege behalten Cursor, keine gesammelten Bestandszeilen.
Cursor sind opak; keine erfundenen Fehlercodes. Bei 422 ist ein bewusster
Neustart aller Seiten mit neuem serverseitigem Stichtag verfügbar.

`occupied` umfasst occupied+rented, weitere Status bleiben getrennt.
`billing_presence` bleibt ausdrücklich Grundpräsenz und keine vollständige
Abrechnungsvorprüfung. Finanz-/Kostenberichte werden separat geladen; kein
gemeinsamer Snapshotclaim. Analyse ist bedarfsgesteuert, geschütztes Audit
erst nach Aufklappen. Bestätigte Null, Erstfehler, Ladestand und sichtbar
älterer Stand bleiben unterscheidbar. Fehlende/Stalequellen erzeugen keine
Entwarnung oder neue Einrichtungsbehauptung; ein leerer freigegebener Bereich
ist kein Nachweis einer leeren Installation.

Initiale Berechtigung kommt aus dem vorhandenen ProtectedRoute. Bei Fokus,
Aktualisieren sowie bewusster Seiten-/Kontextwahl prüft der eigene Boundary
`/auth/me` erneut und übergibt ausschließlich dessen echte Antwort an den
bestehenden AuthContext. Actor-/Grantswechsel remountet die ganze private
Dashboardfläche. Numerische 401/403 einer beliebigen Quelle blenden alles aus
und brechen laufende Reads ab. Ein nicht prüfbarer Authrefresh bleibt ein
eigener Fehler ohne private Daten; keine behauptete Scopeänderung aus 503.

Genau ein ausgewählter Task-/Contractkontext liest höchstens Entity, Unit und
Property. IDs und Elternzuordnung werden geprüft, erst die vollständige
Kette wird veröffentlicht. Kein Tenantread oder Namenshydration im
Hintergrund. 404 bleibt generisch ohne fremde Namen. Echte Property-/Unitlinks
verwenden bekannte App-Routen; allgemeine Bestandslinks heißen entsprechend.
`source_url` ist niemals ein ungeprüftes UIziel. NotificationBell ist ein
separater unverändert gebliebener Legacybereich, nicht als B2-vollständig
behauptet. Kontextschluss gibt den Fokus zum auslösenden Hinweis zurück.

## Tatsächliche leichte Gates

1. Neue Parser-/Hookdatei: **13 PASS / 2,88 s**, gezielte Vitestquelle.
2. Erstes tatsächliches Dashboardwiring: **28 PASS / 9,11 s**.
3. Genau ein neuer Stockabruf-Negativfall gegen die tatsächliche alte
   Dashboardquelle aus `1cdcb6c`: **1 FAILED / 2,13 s**, 27 andere Fälle nicht
   selektiert. Fehler exakt: `getAll('/units')` wurde tatsächlich einmal
   aufgerufen. Das ist keine Produktfreigabe und kein Importfehler. Die
   Produktdatei wurde im `finally` bytegenau wiederhergestellt. Reacts
   act-Warnungen betreffen ausschließlich diesen sofort scheiternden alten
   Quellenfall.
4. Nach zwei weiteren vollständigen Dreifamilien-/Stale-Reportfällen und dem
   kleinen Source-/Race-Review: **43 unterschiedliche positive Fälle in zwei
   Dateien zusammen PASS / 12,37 s**. Das zählt die früheren positiven Läufe
   nicht zusätzlich. ESLint und `git diff --check` grün.

```text
node node_modules/vitest/vitest.mjs run
  src/test/DashboardSummary.test.jsx src/test/DashboardHome.test.jsx --maxWorkers=1
```

Das sind echte Komponenten-/Hookzustände mit ausdrücklich gemockter API;
kein nativer DB-/Browser-/Authbeweis. Eigene Prozesse vollständig beendet.

## Native Browserquellen: vorbereitet, noch nicht ausgeführt

Root hat den opt-in Testsupport im vorhandenen Runner explizit freigegeben.
`--dashboard-fixture` wird vor Playwrightargs entfernt; erst nach normaler
eigener Migration und App-/Demoinitialisierung erzeugt der eigene Seedhelper
10.001 synthetische SQLUnitzeilen in einer gebundenen Bulktransaktion.
Portfolio/Property verwenden den tatsächlichen SQLAlchemyStore; keine DDL,
keine neue Backendroute und keine fake DTO-/Auth-/Summaryantwort. Datenbank,
Manifest und DATA_DIR müssen exakt demselben runner-eigenen temporären Ordner
entsprechen. Das Manifest enthält bekannte synthetische IDs/Counts und nur 13
beabsichtigte Unitreferenzen plus die letzte Unit, keine Zugangsdaten oder
vollständige Clientstockliste. Kleine Aufgaben-/Vertrags-/Meldungsfixtures
werden anschließend über die echte API angelegt. Keine 10.001 HTTPwrites.

Die neue B2-Browserdatei wird ohne den opt-in Manifestkontext ausdrücklich
nicht ausgeführt. Im geplanten konkreten Lauf mit `--dashboard-fixture` müssen
alle drei tatsächlichen Fälle laufen, keine Skips:

1. 10.001 Units, unabhängige Verteilung, echte letzte Unit und autorisierte
   Totals; alle 13 Hinweise jeder Familie durch echte Cursor erreichbar,
   Gleichstände/NULL-Aufgaben und 0-/90-Tage-Vertragsgrenzen. Keine Dashboard-
   Stockabrufe; globale NotificationBell wird separat benannt. Bestehende
   sechs Reports, Hell/Dunkel, strenge Seitenbreite und tatsächliche Bilder
   bei 1440/360/320.
2. Tatsächlicher ausgewählter Manager, genauer Kontext, A→B-Abbruch vor
   weiteren Parentreads, Fokus-Rückweg. Reale Konto-/Grantänderung zu Readonly
   ohne Portfoliozugriff; tatsächlicher Audit-GET wird 403, anschließend echter
   Authrefresh/Nullbestand ohne fortbestehenden privaten Kontext.
3. Eigenes echtes leeres Portfolio, Erstfehler sowie verlorene Auslieferung
   einer tatsächlich erfolgreichen nativen Summary-GETantwort. Diese
   Transportinjektion ist ausdrücklich benannt. Älterer Stand, genaues Retry,
   dann echte zusätzliche Aufgaben. Bewusste Änderung der Stichtagbindung
   eines realen Cursors erzeugt tatsächliches Backend-422; expliziter Neustart.

Bestehender `dashboard.pw.mjs` wurde auf B1-Occupancy ohne abgeschnittenen
1000er-Unitvergleich umgestellt; dieser vorhandene separate Fall ist im
geplanten Dreifällepaket nicht neu behauptet.

Als abgestimmte vierte Abnahmequelle ist der unveränderte reale FinCashflow
mit Root-QA/CSS vorbereitet: Root `faa43eb/dcd0b8c/7b914fc/f1d460c/83c86a9/
017d1a8/9ca1612` wurden nur als saubere Abhängigkeiten übernommen. Eigene
entsprechende Commits `1fea6b3/71eade6/50a7840/63aa135/cb54199/4d20072/768985c`
**nicht nochmals zentral integrieren**. Kein Finproduktsourcefix durch B2.

```text
npm run test:e2e -- --dashboard-fixture
  dashboard-bounded.pw.mjs financial-workspace.pw.mjs
  --grep "B2:|FinancialWorkspace: real scoped"
```

Genau ein Build, ein eigener Backend-/Port-/Tempbereich und Edge. Interpreter
ist die ausdrücklich freigegebene Projekt-Venv; keine parallelen Appstarts
und keine private Preview. Nativeausführung erst nach eigener Sourcefreeze
und ausdrücklicher Rootslotfreigabe. JavaScript-Syntax/ESLint der Browser-
quellen und Ruff des eigenen Seedhelpers sind bereits grün.

## Tatsächlicher erster nativer Lauf und offene Abnahme

Opt-in Test-/Runnerquellen sind sauber als `60e915a` separat freigegeben.
Auf dieser während des Gates unveränderten Quelle liefen ein Build, ein
eigener migrierter SQLite-Backendbereich und ein Edge-Worker: **3 PASS,
1 FAIL**, keine Skips. Kontext-/Rightsfall 20,4 s und echte Leere/verlorene
Antwort/älterer Stand/natives Cursor-422 26,2 s bestanden. Der bestehende
vollständige FinCashflow bestand mit neuer Root-CSS in 23,1 s; alle drei
Financebilder wurden tatsächlich angesehen. Alle eigenen Prozesse wurden
durch das normale Runner-Finally geschlossen, der Tempbereich entfernt.

Der 10.001er-Fall scheiterte nach korrekten Counts/letzter Unit und
vollständigen Aufgaben an fünf ausgelassenen Benachrichtigungen: echte
SQLite-CURRENT_TIMESTAMP-Sekundendarstellung gegenüber DateTime-Cursorbindung
im B1-Backend. Root/Domain korrigieren diesen belegten Backendbefund;
Frontend/Seed/Erwartung bleiben unverändert. Exakte Traceantworten, einzelne
Ergebnisse, erhaltene absolute Bildpfade und die tatsächlich gesichteten
28 unterschiedlichen PNGs stehen in
`docs/B2_DASHBOARD_NATIVE_DIAGNOSIS_20261003.md`.

Die Vertrags-Keyset-/Auswertungs-/Dunkelbildstrecke im ersten Fall wurde
noch nicht erreicht. Gezielt genau dieser Fall bleibt nach Backendgate und
Slotfreigabe offen. Eine leere zusätzliche 360er-Kontextdetailaufnahme zählt
nicht als brauchbarer Bildbeleg; das vollständige 360er-Bild und die
320er-/1440er-Detailaufnahmen zeigen den tatsächlichen Kontext. Separater
Legacy-NotificationBell-Badge nach Grantentzug ist an Root gemeldet.
Nativefehler werden nicht durch gelockerte Assertions verdeckt.

B1-Memory-create-Lockgrenze bleibt unverändert und bekannt. Live-Keysets
sind kein über Requests eingefrorener historischer Bestand. Der synthetische
10.001er-Test ist kein 100.000-/1-Mio.-Leistungs-, 20-Jahre- oder
Zehnnutzerbeweis. B2 ist kein gesamter B-/A–L-Abschluss.
