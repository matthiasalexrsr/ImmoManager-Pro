# ImmoManager PRO – gemeinsam verifizierter Backend-/Frontend-/Messstand

**17. Oktober 2026 – ausdrücklich Entwicklungszweig, keine Auslieferungsfreigabe.**

## Scope und unveränderte Laufzeit

- Eigene Arbeitskopie: `work/pro-stage-backend-frontend-20261017`
- Eigener Zweig: `pro/stage-backend-frontend-20261017`
- Fachliche Backendbasis: `cc099121` mit TEHA, Bank, Finanzen,
  Steuer, interner Kommunikation, API-/Plugins, täglichem
  persönlichem Benachrichtigungseingang, Migration-/Auth-/
  Originalschutz und korrekter historischer Migrationsabnahme.
- Getrennt entwickelte Frontend-Gesamtregression:
  `dbcbc418` → `9f34d128` → `b209025a`, übernommen
  als `1b3da689` → `a19d4008` → `2e2a8c13`.
- Eigenes Abrechnungspaket `00975e5e` mit der nicht
  erfundenen Messabdeckung beim Zählerwechsel, übernommen
  als `fbe835a66fd7611cbd504a72c37d0de81af9e44b`.
- Die Quell-Worktrees wurden nicht verändert oder überschrieben.
  Der zentrale Checkout `claude-review-20261013` steht
  weiterhin bei `04021da5` und ist sauber. Die laufenden
  Installationen auf Ports 8000/8765, deren Daten,
  Originale und Schlüssel wurden nicht angerührt.
- `frontend/package-lock.json`, Versionen alter Datenbanken und
  die Historie bereits veröffentlichter Migrationsstände wurden
  durch diese Übernahme nicht umgeschrieben.

## Verifizierte Prüfergebnisse auf exakt `fbe835a6`

- Frisches `npm ci --ignore-scripts`, 283 Pakete,
  **0 gemeldete Schwachstellen**.
- Frontend: `artifacts/pro-tests/frontend-integrated-60917a20315b40e0a0510b0d948846f4`.
  **657 von 657 Vitestfällen**, **104 von 104 Testdateien** grün,
  `--maxWorkers=2 --testTimeout=15000 --reporter=dot`;
  ESLint und kompletter Vite-Produktionsbuild ebenfalls grün.
  Testtimeout und Parallelität dokumentieren ausschließlich
  reproduzierbare Testlast; keine fachliche Assertion entfiel.
- Ruff `check backend` und Mypy `--platform linux backend`
  bestanden für **563 Python-Quelldateien**, Stand `fbe835a6`.
- Native PostgreSQL: `artifacts/pro-native/8d9cd86b0962444eb9540c0fa9bf2357`,
  Testmatrix unter `artifacts/pro-tests/owned-native-native-805fb9cd0ea14ebb97ec7dd2c138b946`:
  **17/17 ohne Skip**, darunter reale getrennte
  PostgreSQL-Schreibverbindungen für TEHA, Plugin/S3-Vertrag,
  Plattformmigrationen sowie 3 unabhängige
  Zählerwechsel-/Messabdeckungsgegenproben.
  Der ausschließlich eigene Testserver wurde explizit beendet.
- Optionale FinTS-Bibliothek `fints==5.0.1` mittels
  `requirements-bank.txt` plus `constraints.txt` in
  `artifacts/pro-tools/fints-libs` isoliert installiert, **ohne**
  Veränderung der bestehenden Python-Venv oder echte Bankverbindung.

## Weitere aktuell laufende Code-gerechte Nachweise

- Vollständiger Backend-Memory-/Coverage-Lauf mit
  `--optional-libs artifacts/pro-tools/fints-libs`:
  `artifacts/pro-tests/integrated-full-fbe835a6-memory-1a30c268d0ca40588c076026febde468`.
  Erwartetes Ergebnis **nicht vorwegnehmen**; der vorige
  Backendlauf auf einem anderen Commit dauerte ~37 Minuten.
- Gezielte SQLite-Schnittstellen-/Fachmatrix nach Zusammenführung:
  `artifacts/pro-tests/integrated-sql-domains-fbe835a6-sql-2d19b876a2d84ca09f77671dc25558f5`.
  Status offen bis Exit-/JUnit-Nachweis.
- Echte Browserprüfung der privaten Verbindungskonsole mit
  ausschließlich eigenem synthetischen Appserver und lokalem Provider:
  `artifacts/connection-browser/connections-21vxi8pu`:
  **7/7 reale Browserabläufe**, 0 Skip, 0 Browserfehler,
  eigener Testserver gestoppt. Anlegen, eingefrorene Vorschau
  ohne Netzwerkkontakt, ausdrückliche Ausführung genau eines
  Auftrags, unveränderte Ergebnisbelege, Nur-Lese-Berechtigung
  und fokussierte Tastaturbedienung bei **1440/360/320px**.
  Die Aufnahmen `checks/connections-320.png` und
  `checks/connections-1440.png` wurden visuell kontrolliert:
  vollständig geladene, lesbare Formulare und Nachweise;
  kein horizontaler Überlauf und kein inaktiver Ladeindikator.

## Noch nicht abgeschlossene Handover-Pakete und Freigabebedingungen

**Keine Gesamtintegration und kein Release.** Insbesondere nicht
übernommen: Kanal-/WhatsApp-/Post-/OpenImmo-Checkpoint `2da46904`,
die uncommittierten Steuer- und Dokumenteditor-Stages, fünf
zugewiesene, bislang unbegonnene Sales-/Plans-/Operations-/
Abrechnungs-/Portal-Paketarbeitspunkte, die einzig autoritative
Legacy- versus Connection-Providerkonfiguration und externe
TEHA-/Bank-/DATEV-/WISO-/Aktenwerk-/S3-/E-Mail-Gegenstellenbelege.

Die Kanal-Merge-Revision war durch eine Werkzeugsicherheitsprüfung
blockiert; dies wird nicht über einen anderen Weg erzwungen.
Die native PostgreSQL-Auswahl oben ersetzt keine vollständige
native Domänenmatrix und die gezielte SQLite-Auswahl keine
komplette SQL-Coverage-Abnahme.

Endabnahme verlangt alle Fach- und Sicherheitsorakel,
einen einzigen eindeutig linearen Alembic-Head, echte Browser-/
Originalkontrolle, separate native Postgres-/Legacy-/Vollrestore-/
Scale- und CI-Prüfung **auf exakt dem endgültigen kombinierten
Produktcode**, danach unabhängige Prüfung und Auslieferung
durch Codex.
