# Finanzseiten: Ladefehler und vollständige Listen

Basis: `21c67d1`. Isolierter Worktree `wi/work/statements-review`, Branch
`assist/statements-ui-reliability`. Integration und Veröffentlichung bleiben beim
Root-Koordinator; dieser Patch verändert die Hauptarbeitskopie nicht.

## Behobene Defekte

Accounts, Bookings, Invoices, Budgets, Deposits, RentCharges, RentAdjustments und
AllocationKeys verschluckten Ladefehler und/oder lasen nur die erste API-Seite.
Receivables las bereits alle Forderungen, aber keine vollständigen Vertragslisten;
Fehler waren nicht wiederholbar. Categories, TaxRates und Insurances übernahmen
die auf eine Seite begrenzten Cache-Listen. Fehler ihrer Referenzdaten blieben
unsichtbar. Meters verschluckte Fehler der Zähler und Ablesungen; die verschachtelte
Ladekette beendete den Ladezustand vor Abschluss aller Daten und las nur Teilmengen.

Alle 13 Seiten laden jetzt Haupt- und Referenzlisten vollständig mit `api.getAll`.
Der neue, ausschließlich dort eingesetzte Hook `useFinanceData` veröffentlicht die
Daten erst nach erfolgreichem Abschluss aller Listen. Fehler bleiben als Alert
mit betroffener API-Quelle und Wiederholen-Schaltfläche sichtbar. Fehler werden
nicht als Nullsummen, leere Listen oder leere Formularoptionen dargestellt.

Abbruch bei Unmount/erneutem Laden, ignorierte verspätete Antworten und Abbruch
noch laufender Geschwisteranfragen verhindern inkonsistente Zustände. Erfolgreiche
Schreibvorgänge schließen ihr Formular vor dem Neuladen. Ein fehlgeschlagener
anschließender GET erfordert nur einen erneuten GET, nicht nochmals POST/PUT.
Accounts/Bookings/Invoices zeigen bisher unbehandelte Löschfehler, Invoices auch
Fehler beim Statuswechsel, als Alert. Budgets summiert Dezimalstrings centbasiert
statt sie zu verketten. Meters berechnet letzte Ablesung und Verbrauchshistorie
aus derselben vollständigen Ablesungsliste; die separate, veraltbare Detailabfrage
entfällt. Die bestehenden fachlichen Schreib-APIs werden nicht geändert.

Categories, TaxRates und Insurances verwenden einen kleinen `FinanceCrudPage`-
Adapter mit externem Listenzustand. Der globale `CrudPage`, `DataStoreContext`,
`api.js`, `FormModal.jsx`, `RentOverview.jsx`, Backend, Ex-/Import, Pakete und
Lockdateien bleiben unverändert. Bestehende Cache-Invalidierungen bleiben erhalten.

## Prüfungen

Vor der Änderung reproduzierten 27 gezielte Tests die Defekte auf `21c67d1`.
Nach der Änderung: 118 Frontend-Tests bestanden, davon 80 neu: 70 Seiten-/HTTP-
Regressionstests und 10 Hook-Tests. `npm run lint`, `npm run build` und
`git diff --check` gehören zum Prüfprotokoll. Die Seiten-Tests verwenden den echten
API-Client mit simulierten HTTP-Antworten, nicht nur ein Mock von `getAll`.

Die Matrix prüft 1.001 Einträge je Haupt- und Referenzliste, reale `skip=1000`-
Anforderungen, Fehler jeder Datenquelle, Fehler auf der zweiten Seite, leere
Erfolge, Wiederholen, Auswahloptionen jenseits der ersten Seite, Fehler nach
Mutationen, keine Wiederholung erfolgreicher Writes und Dezimal-Budgetsummen.
Der Hook ist auf Abbruch, verspäteten Erfolg/Fehler, Quellenwechsel, Fehlerkontext,
Malformed-Responses, stabile Render und Root-StrictMode geprüft.
Edge prüfte den Produktionsbuild auf allen 13 Routen mit injiziertem Ladefehler,
Wiederholen und 1.001 Zeilen. Zusätzlich: Referenzfehler, mobiles Buchungsformular
mit Konto aus Seite zwei, Budgetsummen und keine JavaScript-Laufzeitfehler.
Bei 390 px war die Dokumentbreite 390 px, der Dialog lag zwischen x=15 und x=375.
Diese Browserprüfung verwendet isolierte API-Testantworten und führt keine
Geschäftsdaten-Schreibvorgänge aus. Sie ist kein echter Backend-E2E-Nachweis.

Reproduzierbar im Worktree (`frontend` als Arbeitsverzeichnis):

```text
npm test
npm run lint
npm run build
node ../../browser-check/finance-smoke.mjs ..
```

Die Browserprüfung benötigt die bereits vorhandene Playwright-Installation unter
`wi/work/browser-check` und Edge. Sie startet/stoppt ihren eigenen Preview auf
Port 5193; ein vorhandener Server wird nicht übernommen. Nachweise stehen unter
`wi/work/ui-evidence`: baseline.json, all-tests.json, tests.log, lint.log,
build.log, lint-final.log, browser-result.json und finance-*.png. Kein Paket wurde installiert.

## Grenzen und weitere Befunde

Die vollständigen Listen werden lokal gehalten; bei großen Beständen ist später
serverseitiges Filtern/Aggregieren vorzuziehen. Der globale Cache anderer Seiten
wurde bewusst nicht umgestellt. Keine Änderung der fachlichen Zahlungslogik.
Bei der visuellen Kontrolle waren vorhandene rohe Übersetzungsschlüssel in
Buchungsformularen sichtbar. Sie sind nicht Teil dieses Lade-/Paginierungspatches.
Der separat gemeldete mobile Überlauf der Statements-Detailseite wird getrennt
untersucht. Der Ausbauvorschlag steht in UI_FINANCE_E2E_PROPOSAL.md; der Browser-Agent hat
inzwischen f39863b samt responsiver CSS-Korrektur geliefert. Diese wird nicht
in diesem Patch dupliziert.
