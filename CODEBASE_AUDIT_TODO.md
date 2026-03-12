# ImmoManager-Pro – Full Codebase Audit TODO (v2)

Dieses Dokument ersetzt die vorherige, zu grobe Fassung durch einen **konkreten, umsetzbaren Backlog** mit klaren Arbeitspaketen.

## 0) Audit-Umfang

Geprüft wurden:
- Backend (FastAPI, Repositories, Domain, Router, Tests)
- Frontend (React, Pages, Components, Lint-Status)
- CI-Workflow
- Repo-Struktur / Dokumentation

Verwendete Checks:
- `rg --files`
- `rg -n "TODO|FIXME|NotImplemented|pass|catch \(\) => \{\}" backend frontend`
- `pytest -q` (in `backend/`)
- `pytest -q backend/tests/test_dependencies.py`
- `npm run lint` (in `frontend/`)
- `ruff check backend`
- `mypy backend --ignore-missing-imports`

---

## 1) Sofortmaßnahmen (Blocker)

### B1 – Frontend-Lint ist nicht release-fähig
**Status:** Offen (mehrere ESLint-Fehler)

**Konkrete Tasks:**
1. `frontend/src/contexts/DevModeContext.jsx`
   - Hook-Reihenfolge korrigieren (`fetchNotes` vor Verwendung deklarieren).
   - `useEffect`-Dependencies sauber ziehen.
2. Seiten mit `react-hooks/set-state-in-effect`-Befunden auf einheitliches Datenlade-Pattern migrieren.
3. Unused-Variablen bereinigen (z. B. DevModeOverlay/Statements).

**Definition of done:** `npm run lint` endet mit Exit-Code 0.

### B2 – Backend-Ruff ist rot
**Status:** Offen (Import-Order, line-length, shadowing, unused)

**Konkrete Tasks:**
1. `ruff check backend --fix` ausführen und Restfehler manuell beheben.
2. In den Routern Variablenschatten/unused vars entfernen (`diagnostics.py`, `billing.py`, `search.py` etc.).
3. Konsistente Formatierungsstrategie festziehen (Ruff formatter oder Black).

**Definition of done:** `ruff check backend` mit 0 Fehlern.

### B3 – Typprüfung mit massivem Rückstand
**Status:** Offen (hohe Fehlerzahl)

**Konkrete Tasks (phasenweise):**
1. **Phase 1:** `backend/repositories/` typisieren (Any-Leaks, fehlende Annotations).
2. **Phase 2:** `backend/routers/` (Signaturen, Return-Typen, dict-Invarianz).
3. **Phase 3:** `backend/domain/` (Decimal/Date-Vergleiche).
4. `mypy` auf Teilmodule in CI schrittweise verpflichtend machen.

**Definition of done:** Fehlerzahl pro Sprint messbar reduziert; Teilmodule laufen fehlerfrei.

### B4 – Testlauf abhängig vom Working Directory
**Status:** Offen

**Symptom:** `pytest -q` in `backend/` kann Subprocess-Importfehler erzeugen, aus Repo-Root läuft der betreffende Test.

**Konkrete Tasks:**
1. `backend/tests/test_dependencies.py` subprocess-Aufruf cwd-agnostisch machen.
2. Canonical Test Commands im Root-README dokumentieren.

**Definition of done:** Tests laufen identisch aus Root und aus `backend/`.

---

## 2) Konkrete offene Code-Gaps (mit Priorität)

## P1 – Fehlerbehandlung/Resilienz

### G1 – Verbleibende stille Fehlerbehandlung im Frontend entfernen
Folgende Dateien enthalten noch `catch(() => {})`-Muster:
- `frontend/src/pages/Meters.jsx`
- `frontend/src/pages/Settings.jsx`
- `frontend/src/pages/Statements.jsx`
- `frontend/src/pages/Messages.jsx`
- `frontend/src/pages/Dashboard.jsx`
- `frontend/src/components/DevModeOverlay.jsx`

**Task:** einheitliche `console.warn` + UI-Feedback-Strategie (Toast/Banner) einführen.

### G2 – Allgemeine `pass`-Blöcke mit Kontext ersetzen
Mehrere Stellen schlucken Fehler (z. B. in Admin/Notifications/Tasks/Search/OCR).

**Task:**
- Nur bewusst tolerierte Fehlerfälle erlauben.
- Sonst Logging mit Kontext (`entity_id`, Operation, Route).

## P1 – Datenkonsistenz

### G3 – Einheitliches Null/Empty-Handling
Formdaten und PATCH/PUT-Pfade nutzen teils uneinheitlich `""` vs `null`.

**Task:**
- Shared-Parser/Mapper für optionale Felder einführen.
- Regressionstests für alle numerischen/Foreign-Key-Felder ergänzen.

---

## 3) Fehlende Module / fehlender Unterbau

### M1 – Frontend-Testmodul fehlt vollständig
**Ist:** Kein eigener Teststack für React-UI im Projektcode.

**ToDo (neu):**
- `frontend/tests/` + Vitest + React Testing Library
- Start-Suite:
  1. Routing smoke test (`App`)
  2. `DataTable` filtering/sorting
  3. `FormModal` Type-Coercion (insb. optional numbers/selects)

### M2 – E2E-Modul fehlt
**Ist:** Keine durchgehenden UI-zu-API-Flows als Browser-E2E.

**ToDo (neu):**
- `e2e/` mit Playwright
- Flows:
  1. Login + Navigation
  2. Kern-CRUD (Property/Unit/Tenant/Contract)
  3. Finance-Basisflow (Booking/Receivable)

### M3 – API-Contract-Tests fehlen
**Ist:** Keine explizite Breaking-Change-Absicherung via OpenAPI/Schema-Snapshots.

**ToDo (neu):**
- Contract-Tests für kritische Endpunkte
- Optional OpenAPI-Diff in CI als PR-Gate

### M4 – Observability-Modul fehlt
**Ist:** Logging vorhanden, aber kein dediziertes Metrics/Tracing-Modul.

**ToDo (neu):**
- Prometheus-Metriken (`/metrics`) + zentrale Counters
- Tracing-Korrelation über Request-Grenzen hinweg

---

## 4) Testabdeckung zielgerichtet erweitern

### T1 – Router-Deep-Tests für risikoreiche Domänen
Priorisierte Router:
1. `billing`
2. `receivables`
3. `integrations`
4. `auth`
5. `admin`

**Task:** pro Router positive + negative Pfade + Berechtigungsfälle + Randfälle.

### T2 – Frontend Regressionstests für bekannte Problemklassen
1. Async-Load-Muster (`useEffect` + callbacks)
2. Fehleranzeige statt Silent-Failure
3. Form-Normalisierung (`""`/`null`/number)

---

## 5) Architektur-/Produktivitätsschulden

### A1 – Root-README ausbauen
Derzeit minimal.

**Task:**
- Quickstart (Backend/Frontend)
- ENV-Variablen
- Standardbefehle (run/test/lint/type-check)
- Troubleshooting

### A2 – Repo-Aufräumen
Viele Analyse-/Binärartefakte im Root.

**Task:**
- Archivstruktur `docs/archive/` oder Entfernen veralteter Artefakte
- Contribution-Guide: was nicht ins Repo gehört

### A3 – CI in Fast/Full Pipelines trennen
**Task:**
- Fast: Lint + targeted tests
- Full: Coverage + mypy subset + e2e nightly

---

## 6) Umsetzungsvorschlag (Sprint-fähig)

### Sprint 1 (Stabilisierung)
- B1 Frontend-Lint grün
- B2 Ruff grün
- B4 cwd-agnostische Tests

### Sprint 2 (Qualität)
- M1 Frontend-Tests aufsetzen
- T1/T2 erste High-Risk-Testpakete

### Sprint 3 (Skalierung)
- M2 E2E-Grundpfade
- M3 Contract-Checks
- B3 Typisierungsphase 1

### Sprint 4 (Betrieb)
- M4 Observability
- A1/A2/A3 finalisieren

---

## 7) Abschlusskriterien für „Audit geschlossen"

- `npm run lint` = grün
- `ruff check backend` = grün
- definierter `mypy`-Scope = grün
- reproduzierbare Tests unabhängig vom cwd
- Frontend-Tests + mindestens 1 E2E-Smoke in CI
- README und CI-Doku vollständig
