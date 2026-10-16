# Gemeinsame Backend-/Frontend-/Zählerwechsel-Integration – 17.10.2026

**Status: Entwicklungscheckpoint, nicht freigegeben und nicht ausgerollt.**

Der vollständig getrennte Zweig `pro/stage-combined-billing-20261017`
baut auf `c7a79f2d` (Backend `c5db7f39`, Frontend `1113a7bd`)
auf. Der eigenständige Billing-Checkpoint `00975e5e` wurde
ohne Dateikonflikte unter dem neuen Produktcodehash
**`a968281a6732e0f3c7af1915552030be03af0b52`** integriert.

Gegenprobe: Ein alter Zähler endet am 30.06. und der neue
beginnt am 03.07. – der 01. und 02.07. werden im
Betriebskosten-Preflight als `METER_SERVICE_GAP` blockiert.
Ein nahtloser Tausch erzeugt keine falsche Warnung,
zeitgleiche alte/neue Messstellen benötigen den gesonderten
`METER_SERVICE_OVERLAP`-Fachabgleich. Kein historischer
Zählerstand, Zahlungsbeleg oder Abschluss wird geändert.

Auf dem exakten integrierten Codecommit nachgeprüft:
- Ruff im gesamten Backend grün.
- Mypy `--platform linux` für **563 Backendquelldateien grün**.
- Memory-Fachmatrix
  `artifacts/pro-tests/combined-billing-memory-6d1b102560984dff988d9dcfc7a6fa77`:
  **52/52 Tests**, Exit 0, 0 Skips.
- SQLite-Fachmatrix
  `artifacts/pro-tests/combined-billing-sql-bbb8e829074a4c12b6859f66d8f45bd8`:
  **52/52 Tests**, Exit 0, 0 Skips.
- Die separate native PostgreSQL-QA verwendet
  `artifacts/pro-native/62590a1971d84b38b8f584d66dfe0f10` und
  `artifacts/pro-tests/owned-native-native-126464bc556e491c9a9909487d97cf5c`.
  **3/3 native PostgreSQL-Tests bestanden, kein Skip,
  NATIVE_EXIT=0, STOPPED=True.** Der SQL-Prozess hat ausschließlich
  einen eigens besessenen temporären Loopback-Cluster benutzt
  und ihn anschließend kontrolliert beendet.

**Weiterhin nicht abgeschlossen:** bestätigte Ersatz-/Parallel-
Messstellenbeziehung, Gas-Brennwert/Zustandszahl und HKV-Einheiten,
Widerspruchskorrektur und Bewohner-/Stichtagsänderungen. Dazu fehlen
die übrigen Domains (Eigentümerwechsel/Verkauf, Portal, Operations)
und die endgültige systemweite Migration/Restore-/Livegegenstellen-
Abnahme. Der Backend-Volltest auf `1113a7bd` läuft unter
`pro-stage-frontend-backend-20261017/artifacts/pro-tests/
combined-full-backend-memory-43a97fe08ce94ed7827f8427ac5240aa`
noch unabhängig. Ein historisch grüner Einzeltest wird nicht als
grüne Gesamtmatrix dieses Commits dargestellt.

Der zentrale Referenzcheckout sowie die realen Installationen auf
8000/8765 wurden weder verändert noch ausgerollt. Keine echten
Bank-/TEHA-/Post-/Kommunikationsaufträge wurden ausgeführt.
