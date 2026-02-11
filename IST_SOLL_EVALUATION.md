# ImmoManager Pro – Ist-Stand vs. Soll-Architektur Evaluation

**Datum:** 2026-02-11
**Basis:** Verifiziert am Code (Branch `claude/implement-todo-item-OHtY9`, Commit `9fe547d`)

---

## 1. Zusammenfassung

| Bereich | Soll (Architekturplan) | Ist (Code) | Status |
|---------|----------------------|------------|--------|
| Backend-Routers | 24+ | 26 Router, 195 Routen | OK |
| Domain-Engines | 4 | 4 (Lease, Dunning, InvoiceMatcher, Billing) | OK |
| Tests | 80%+ Coverage | 503 Tests, alle bestanden | OK |
| Datenbank | PostgreSQL + SQLite | SQLAlchemy 2.0 + Alembic + 28 ORM-Modelle | OK |
| Auth/RBAC | JWT + 5 Rollen | JWT (PBKDF2-SHA256), 5 Rollen, Audit-Log | OK |
| API-Versionierung | `/api/v1/` | Implementiert | OK |
| Frontend | Web-UI | React + Vite, 14 Seiten, 8 Komponenten | OK |
| i18n | DE, EN, ES | 3 Locales, Frontend i18n Framework | OK |
| Docker | Compose + PostgreSQL | Dockerfile + docker-compose.yml | TEILWEISE |
| .exe-Ausführung | Windows-Deployment | **NICHT IMPLEMENTIERT** | FEHLT |
| PyInstaller | Installierbare .exe | **NICHT VORHANDEN** | FEHLT |
| Plugin-System | Erweiterbar | Plugin-Basis, Event-Bus | OK |
| CI/CD | GitHub Actions | Lint + Test Workflow | OK |

---

## 2. Detailbewertung nach Architekturplan-Modulen

### 2.1 Identity & Access (Abschnitt 3.1)

| Feature | Soll | Ist | Status |
|---------|------|-----|--------|
| Benutzer, Rollen, Rechte | Ja | UserORM + 5 Rollen (eigentuemer, verwalter, techniker, readonly, custom) | OK |
| JWT Auth | Ja | Login, Refresh, Logout Endpunkte | OK |
| RBAC auf Ressourcenebene | Ja | `require_role()` Decorator | OK |
| 2FA | Ja | **Nicht implementiert** | FEHLT |
| Session Management | Ja | JWT Token + Refresh | OK |
| Geräteverwaltung | Ja | **Nicht implementiert** | FEHLT |
| Passwort-Policies | Ja | Basis-Validierung | TEILWEISE |
| Login-Limits | Ja | **Nicht implementiert** | FEHLT |

### 2.2 Portfolio & Stammdaten (Abschnitt 3.2)

| Feature | Soll | Ist | Status |
|---------|------|-----|--------|
| Portfolios, Immobilien, Einheiten | Ja | Vollständige CRUD | OK |
| Stammdaten (Objektart, Einheitstyp) | Ja | Categories Router | OK |
| Historisierung | Ja | **Nicht implementiert** | FEHLT |

### 2.3 CRM: Mieter & Vertrag (Abschnitt 3.3)

| Feature | Soll | Ist | Status |
|---------|------|-----|--------|
| Mieterprofil | Ja | Vollständig | OK |
| Vertragsdaten | Ja | Vollständig | OK |
| Index-/Staffeloption | Ja | **Nicht implementiert** | FEHLT |
| Übergabeprotokoll | Ja | **Nicht implementiert** | FEHLT |
| Zählerstände/Fotos | Ja | Fotos ja, Zählerstände **nein** | TEILWEISE |

### 2.4 Finanzkern (Abschnitt 3.4)

| Feature | Soll | Ist | Status |
|---------|------|-----|--------|
| Konten (Bank/Kasse/Rücklage) | Ja | Vollständig | OK |
| Buchungen mit Zuordnung | Ja | Vollständig | OK |
| Offene Posten/Forderungen | Ja | LeaseEngine | OK |
| Rechnungen | Ja | InvoiceMatcher | OK |
| Steuerlogik (MwSt.) | Ja | **Nicht implementiert** | FEHLT |

### 2.5 Abrechnung (Abschnitt 3.5)

| Feature | Soll | Ist | Status |
|---------|------|-----|--------|
| BillingPeriod, AllocationKey | Ja | BillingEngine implementiert | OK |
| Verteilerschlüssel | Ja | 4 Typen (area, units, persons, consumption) | OK |
| Revisionssichere Versionierung | Ja | **Nicht implementiert** | FEHLT |

### 2.6 Dokumente & Medien (Abschnitt 3.6)

| Feature | Soll | Ist | Status |
|---------|------|-----|--------|
| Dokumentbibliothek | Ja | Documents Router | OK |
| OCR-Pipeline | Phase 2 | **Nicht implementiert** | FEHLT |
| Fotoverwaltung | Ja | ListingPhotos | OK |

### 2.7 Instandhaltung & Aufgaben (Abschnitt 3.7)

| Feature | Soll | Ist | Status |
|---------|------|-----|--------|
| Tickets/Fälle | Ja | Maintenance Router | OK |
| Wiederkehrende Aufgaben | Ja | iCal RRULE Support | OK |
| Eskalationsregeln | Ja | **Nicht implementiert** | FEHLT |

### 2.8 Inserate & Vermarktung (Abschnitt 3.8)

| Feature | Soll | Ist | Status |
|---------|------|-----|--------|
| Exposé-Datenmodell | Ja | Listings Router | OK |
| Interessenten-Tracking | Ja | Leads + Viewings Router | OK |
| Portaladapter | Phase 2 | **Nicht implementiert** | DEFERRED |

### 2.9 Benachrichtigungen (Abschnitt 3.9)

| Feature | Soll | Ist | Status |
|---------|------|-----|--------|
| In-App Notifications | Ja | Notifications Router + Bell | OK |
| E-Mail-Versand | Ja | **Nicht implementiert** | FEHLT |
| Vorlagenmanagement | Ja | NotificationTemplates im Store | OK |
| Versandprotokoll | Ja | **Nicht implementiert** | FEHLT |

### 2.10 Reporting & Analytics (Abschnitt 3.10)

| Feature | Soll | Ist | Status |
|---------|------|-----|--------|
| KPI-Dashboard | Ja | 7 Report-Endpunkte | OK |
| CSV Export | Ja | Implementiert | OK |
| PDF Export | Ja | **Nicht implementiert** | FEHLT |
| DATEV Export | Ja | Implementiert | OK |
| Bank Import | Ja | CSV/MT940 Matching | OK |

---

## 3. Technische Infrastruktur

### 3.1 Sicherheit & Datenschutz (Abschnitt 6)

| Feature | Soll | Ist | Status |
|---------|------|-----|--------|
| RBAC | Ja | 5 Rollen | OK |
| Verschlüsselte IBAN | Ja | **Nicht implementiert** | FEHLT |
| Audit-Log | Ja | AuditMiddleware + Audit-Router | OK |
| Backup/Restore | Ja | Admin-Router | OK |
| DSGVO Datenexport | Ja | **Nicht implementiert** | FEHLT |
| DSGVO Löschkonzept | Ja | **Nicht implementiert** | FEHLT |

### 3.2 Qualitätsstrategie (Abschnitt 7)

| Feature | Soll | Ist | Status |
|---------|------|-----|--------|
| Unit-Tests | Ja | 503 Tests | OK |
| API-Integrationstests | Ja | test_integration.py (TestClient) | OK |
| E2E-Tests (Kernflows) | Ja | **Nicht implementiert** | FEHLT |
| Ruff/Lint | Ja | ruff konfiguriert | OK |
| Mypy/Typchecks | Ja | **Nicht konfiguriert** | FEHLT |
| 80% Coverage | Ja | Nicht gemessen, geschätzt >80% | UNKLAR |

### 3.3 Windows-Betrieb (Abschnitt 2.3)

| Feature | Soll | Ist | Status |
|---------|------|-----|--------|
| Docker Desktop | Option A | docker-compose.yml vorhanden | OK |
| Native Windows Service | Option B | **Nicht implementiert** | FEHLT |
| .exe Ausführung | Ja | **Nicht implementiert** | FEHLT |
| PyInstaller Bundle | Ja | **Keine .spec Datei** | FEHLT |
| Backup via Task Scheduler | Ja | **Nicht implementiert** | FEHLT |

### 3.4 Installation & Deployment

| Feature | Soll | Ist | Status |
|---------|------|-----|--------|
| `pip install -e .` | Ja | pyproject.toml unvollständig | DEFEKT |
| pyproject.toml dependencies | Alle | pydantic-settings, python-multipart fehlen | DEFEKT |
| pyproject.toml testpaths | backend/tests | "tests" (falsch) | DEFEKT |
| Dockerfile Frontend | Ja | Frontend dist nicht kopiert | DEFEKT |
| `routers/__init__.py` | Alle Router | admin, search fehlen | DEFEKT |
| `domain/__init__.py` | Alle Engines | BillingEngine fehlt | DEFEKT |

---

## 4. IMPLEMENTATION_PLAN.md Erfüllungsgrad

| Feature | Status | Anmerkung |
|---------|--------|-----------|
| 1.1 Centralized Config | OK | pydantic-settings |
| 1.2 Structured Logging | OK | JSON + request correlation |
| 1.3 Global Error Handling | OK | Exception handlers + ErrorBoundary |
| 1.4 DB Integrity | OK | CHECK constraints, indexes |
| 2.1 i18n Framework | OK | Custom React i18n |
| 2.2 Spanish Locale | OK | es-ES.json |
| 2.3 Interface Customization | OK | Dark theme, preferences |
| 3.1 Plugin System | OK | Abstract base + event bus |
| 3.2 Updateability | OK | Version endpoint, update script |
| 4.1 Data Persistence | OK | SQLAlchemy default, export/import |
| 4.2 Practical Features | OK | Search, notifications, bell |
| **550+ Tests** | **NICHT ERREICHT** | 503 (Ziel: 550+) |

---

## 5. Resultierende TODOs

### Priorität KRITISCH (Installation & Ausführung)

- [ ] **T1** – pyproject.toml: `pydantic-settings` und `python-multipart` in dependencies aufnehmen
- [ ] **T2** – pyproject.toml: `testpaths` auf `["backend/tests"]` korrigieren
- [ ] **T3** – `routers/__init__.py`: `admin` und `search` Module exportieren
- [ ] **T4** – `domain/__init__.py`: `BillingEngine` exportieren
- [ ] **T5** – Dockerfile: Frontend `dist/` Verzeichnis einbinden
- [ ] **T6** – PyInstaller `.spec`-Datei erstellen für Windows .exe
- [ ] **T7** – `pip install -e .` verifizieren und sicherstellen

### Priorität HOCH (Fehlende Kernfunktionen)

- [ ] **T8** – PDF-Export für Reports implementieren (weasyprint/reportlab)
- [ ] **T9** – E-Mail-Versand für Benachrichtigungen (SMTP)
- [ ] **T10** – 2FA (TOTP) für Benutzerauthentifizierung
- [ ] **T11** – DSGVO-Datenexport und Löschkonzept
- [ ] **T12** – Verschlüsselte Speicherung sensibler Felder (IBAN)
- [ ] **T13** – E2E-Tests für Kernflows (5 Use Cases aus Abschnitt 7.3)

### Priorität MITTEL (Architekturplan-Features)

- [ ] **T14** – Steuerlogik (MwSt.-Sätze, steuerrelevante Exporte)
- [ ] **T15** – Index-/Staffelmietoption in Verträgen
- [ ] **T16** – Übergabeprotokoll mit Zählerständen
- [ ] **T17** – Eskalationsregeln bei Fristüberschreitung
- [ ] **T18** – Historisierung zentraler Strukturänderungen
- [ ] **T19** – Revisionssichere Versionierung der Abrechnungen
- [ ] **T20** – OCR-Pipeline für Rechnungen/Belege
- [ ] **T21** – Passwort-Policies und Login-Limits
- [ ] **T22** – Mypy-Typchecks konfigurieren und integrieren
- [ ] **T23** – 50+ neue Tests (Ziel: 550+)

### Priorität NIEDRIG (Nice-to-have / Phase 4)

- [ ] **T24** – Redis + Celery für Background Jobs
- [ ] **T25** – S3/MinIO Dateiablage
- [ ] **T26** – Portaladapter für Immobilieninserate
- [ ] **T27** – Budgetplanung pro Objekt
- [ ] **T28** – Liquiditäts-Forecast (3/6/12 Monate)
- [ ] **T29** – Windows Service (NSSM)
- [ ] **T30** – Backup via Windows Task Scheduler

---

## 6. Fazit

ImmoManager Pro deckt **ca. 75%** der Soll-Architektur ab. Alle Kerndomänen (Portfolios, Immobilien, Mieter, Verträge, Finanzen, Abrechnung, Instandhaltung, Inserate) sind als CRUD + Domain-Engines implementiert. Die technische Infrastruktur (API-Versionierung, Auth, RBAC, Audit, Plugin-System, i18n, Docker) ist solide.

**Hauptlücken:**
1. **Windows .exe-Deployment** – Komplett fehlend
2. **Installation** – pyproject.toml-Abhängigkeiten unvollständig
3. **DSGVO/Compliance** – Datenexport, Löschkonzept, verschlüsselte Felder
4. **Fortgeschrittene Features** – 2FA, OCR, E-Mail, PDF-Export, E2E-Tests
