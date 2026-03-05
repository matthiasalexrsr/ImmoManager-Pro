# ImmoManager Pro — Comprehensive Implementation Plan

_Generated 2026-03-04 from full codebase audit (backend models, frontend pages,
routers, storage, tests, auth, i18n, error handling)._

---

## Phase 1: CRITICAL — Navigation & Unreachable Pages

### 1.1 Add Categories and Deposits to Sidebar
**Files:** `Layout.jsx`, `Icons.jsx`
**Issue:** Both pages exist, are routed in App.jsx, but have NO sidebar entry.
Users cannot find them without typing the URL directly.
**Fix:** Add `CategoryIcon` + `DepositIcon` SVGs to Icons.jsx. Add Categories
to Finance section and Deposits to Tenants & Contracts section in NAV_SECTIONS.

### 1.2 Fix Contracts.jsx Silent Catches
**File:** `Contracts.jsx` lines 21-23
**Issue:** Last remaining `.catch(() => [])` patterns from before hardening.
**Fix:** Replace with `.catch(err => { console.warn(...); return []; })`.

### 1.3 Add Missing Contract Form Fields
**File:** `Contracts.jsx`
**Issue:** Backend `ContractCreate` has `index_rent` and `service_charge_settlement`
not in frontend form. `notice_period` IS present already.
**Fix:** Add `index_rent` (select: index/stepped/fixed) and
`service_charge_settlement` (select: annual/monthly).

---

## Phase 2: HIGH — FormModal & CrudPage Bugs

### 2.1 CrudPage Delete Error Invisible
**File:** `CrudPage.jsx`
**Issue:** `handleDelete` has no try-catch — API errors during delete are
completely invisible. `handleSave` errors DO propagate to FormModal, but
delete happens outside the modal.
**Fix:** Add try-catch to `handleDelete`, render error banner above table.

### 2.2 FormModal Empty Number → 0 Bug
**File:** `FormModal.jsx` line 25
**Issue:** `Number('')` returns `0`. All empty optional number fields silently
send `0` to backend instead of `null`. Affects: purchase_price, market_value,
estimated_cost, deductions, vat_amount, etc.
**Fix:** Check `v === '' || v === null` before Number() conversion; return
`null` for non-required fields.

### 2.3 FormModal Empty Select → "" Bug
**File:** `FormModal.jsx` line 26-27
**Issue:** Optional select fields left at "— Auswählen —" send empty string
`""` to backend. FK fields like `property_id`, `unit_id` etc. should be `null`.
**Fix:** Convert `""` to `null` for non-required fields in handleSubmit.

---

## Phase 3: HIGH — Backend Gaps

### 3.1 MeterReading Missing PUT/PATCH Endpoints
**File:** `backend/routers/handover_protocols.py`
**Issue:** Meter readings can be created and deleted but NOT corrected. No
PUT or PATCH endpoint exists.
**Fix:** Add PUT and PATCH endpoints for `/{protocol_id}/meter-readings/{reading_id}`.

### 3.2 SQLAlchemyStore Missing Methods
**File:** `backend/repositories/sql_store.py`
**Issue:** `update_meter_reading()` and `add_change_history()` exist in
InMemoryStore but NOT in SQLAlchemyStore. SQL backend silently loses change
history and cannot update meter readings.
**Fix:** Implement both methods in SQLAlchemyStore.

---

## Phase 4: MEDIUM — Missing Form Fields & Data

### 4.1 Units — Missing `features` Field
**File:** `Units.jsx`
**Issue:** Backend `UnitCreate` has `features: Optional[str]` (balcony,
parking, etc.) not exposed in form.
**Fix:** Add `features` textarea field.

### 4.2 Deposits — `contract_label` Column Empty
**File:** `Deposits.jsx`
**Issue:** Column key `contract_label` doesn't exist on Deposit model — shows
blank in every row.
**Fix:** Load contracts on mount, create enriched deposit list mapping
`contract_id` → `contract_number` as `contract_label`.

### 4.3 Statements.jsx — BillingPeriod `label` Required
**File:** `Statements.jsx`
**Issue:** `BillingPeriodCreate` requires `label` field but the Statements
form doesn't include it. Creates will fail.
**Fix:** Add `label` text field to billing period form, or auto-generate from
property + dates.

---

## Phase 5: MEDIUM — SearchBar & Dashboard

### 5.1 Expand SearchBar Entity Coverage
**File:** `SearchBar.jsx`
**Issue:** Only 6 of ~15 entity types searchable. Missing: portfolio, account,
booking, document, maintenance, deposit, category, lead, listing.
**Fix:** Add missing types to ENTITY_ROUTES and ENTITY_ICON_MAP.

### 5.2 Dashboard Array Safety
**File:** `Dashboard.jsx` lines 82-92
**Issue:** Calls `.length`/`.filter()` on values that could theoretically be
non-array from API.
**Fix:** Add `Array.isArray()` guards.

---

## Phase 6: MEDIUM — Auth & Security

### 6.1 Show Password Complexity Requirements
**File:** `Login.jsx`
**Issue:** Backend requires 8+ chars + 1 upper + 1 lower + 1 digit. Frontend
only shows "Mindestens 8 Zeichen". Users discover rules only after rejection.
**Fix:** Add hint text listing all requirements below password field.

### 6.2 Auth Preferences Session Safety
**File:** `backend/routers/auth.py` lines 99, 135
**Issue:** `get_my_preferences` and `update_my_preferences` create raw
`SessionLocal()` outside DI. DB failures crash these endpoints.
**Fix:** Wrap in try-except, fall back to defaults on failure.

### 6.3 JWT Secret Key Warning
**File:** `backend/config.py`
**Issue:** Default JWT_SECRET_KEY is a dev value. Production deployments
silently use the insecure default.
**Fix:** Already logs a warning. Consider refusing to start without explicit
JWT_SECRET_KEY in production mode.

---

## Phase 7: LOW — i18n Coverage

### 7.1 Shared Components (~15 hardcoded German strings)
**Files:** `FormModal.jsx`, `CrudPage.jsx`, `DataTable.jsx`
**Key strings:** "— Auswählen —", "Abbrechen", "Speichern", "Suchen...",
"Filter", "Spalten", "CSV", "Neu", "Keine Einträge gefunden", "Aktionen",
"Alle", "/ Seite", "Laden...", "wirklich löschen?"

### 7.2 Page Components (~25+ hardcoded German strings)
**Files:** `Login.jsx`, `Dashboard.jsx`, `Settings.jsx`, `RentOverview.jsx`,
`Messages.jsx`, `Contacts.jsx`, `Statements.jsx`
**Includes:** All page titles, button labels, chart labels, form labels.

---

## Phase 8: LOW — Missing Frontend Pages (Backend APIs exist)

Backend entities with full CRUD APIs but NO frontend page:

| Entity | Endpoint | Use Case |
|--------|----------|----------|
| CalendarEvent | `/calendar` | Calendar view for appointments |
| Lead | `/leads` | Vacancy management: prospect tracking |
| Listing | `/listings` | Vacancy management: portal listings |
| ListingPhoto | `/listings/{id}/photos` | Photos for listings |
| ViewingAppointment | `/viewings` | Vacancy management: viewing scheduling |
| HandoverProtocol | `/handover-protocols` | Move-in/out protocols (only meter part exposed) |
| RentAdjustment | `/rent-adjustments` | Index/stepped rent tracking |
| Budget | `/budgets` | Budget vs actual analysis |
| AllocationKey | `/billing/allocation-keys` | Billing cost distribution keys |
| TaxRate | `/tax-rates` | VAT rate configuration |
| EscalationRule | `/escalation-rules` | Automated escalation rules |
| NotificationTemplate | `/notifications/templates` | Notification template management |

---

## Phase 9: LOW — Code Quality

### 9.1 Remove Unused Icons
**File:** `Icons.jsx`
6 defined but never imported: AlertIcon, CheckCircleIcon, InfoIcon,
XCircleIcon, CalendarIcon, BuildingIcon.

### 9.2 Test Coverage Gap
**File:** `backend/repositories/sql_store.py`
`update_meter_reading()` and `add_change_history()` untested since they
don't exist yet (Phase 3.2).

---

## Implementation Priority Matrix

| # | Phase | Item | Effort | Impact |
|---|-------|------|--------|--------|
| 1 | 1.1 | Sidebar nav for Categories + Deposits | 15 min | Critical |
| 2 | 2.2-2.3 | FormModal null handling bugs | 15 min | High |
| 3 | 2.1 | CrudPage delete error display | 15 min | High |
| 4 | 1.2-1.3 | Contracts catches + missing fields | 10 min | Medium |
| 5 | 3.1-3.2 | MeterReading PUT/PATCH + SQLStore gaps | 30 min | High |
| 6 | 4.1-4.3 | Missing form fields (Units, Deposits, Statements) | 20 min | Medium |
| 7 | 5.1-5.2 | SearchBar + Dashboard safety | 20 min | Medium |
| 8 | 6.1-6.2 | Password hints + auth safety | 15 min | Medium |
| 9 | 7.1-7.2 | i18n hardcoded strings | 2+ hrs | Low |
| 10 | 8.x | New frontend pages | Large | New features |
---

## Detaillierter Masterplan: Bereich „Nebenkostenabrechnungen“

### 1) Zielbild (Produkt)
Der Bereich „Nebenkostenabrechnungen" soll den kompletten Lebenszyklus abdecken:
1. Abrechnungsperiode vorbereiten
2. Kosten erfassen/importieren (inkl. Beleg/OCR)
3. Verteilung plausibilisieren
4. Einzelabrechnungen erzeugen
5. Prüfen/freigeben/finalisieren
6. Zustellen und Nachverfolgen
7. Nachzahlung/Guthaben in Finanzflüsse überführen

### 2) Vorhandene Basis im Code (Anknüpfungspunkte)
- Backend-Router mit vollständigen CRUD-Endpoints für Perioden, Verteilerschlüssel, Kostenpositionen und Utility Statements sowie Generierungsendpoint. (`backend/routers/billing.py`)
- Abrechnungslogik über `BillingEngine` mit centgenauer Rundung und Advance-Abzug. (`backend/domain/billing_engine.py`)
- Datenmodelle mit Status/Revisionsfeldern für `UtilityStatement`. (`backend/models.py`)
- Frontend-Seite `Statements.jsx` mit Listen-/Detailansicht, Kostenpositionen und Vorjahreskopie.
- Zähler/Ablesungen in `Meters.jsx` als Grundlage für verbrauchsbasierte Schlüssel.

### 3) Funktionsbausteine (Soll)

#### A. Stammdaten & Regeln
- Kostenartenkatalog (umlagefähig/nicht umlagefähig, Standard-Verteilerschlüssel)
- Objekt-Check „abrechnungsbereit“ (Flächen, aktive Verträge, Schlüssel vorhanden)
- Versionierte Verteilerschlüssel-Regeln pro Periode

#### B. Datenerfassung
- Manuelle Kostenpositionen mit Pflichtvalidierung
- Dokumentimport mit OCR-gestützter Vorbelegung (Betrag, Datum, Lieferant, Kostenart)
- Vorjahresübernahme inkl. Markierung „Wert noch zu prüfen"

#### C. Rechenkern
- Vollständige Schlüsselunterstützung: `area_sqm`, `unit_count`, `person_count`, `consumption`
- Leerstandslogik (Eigentümeranteil)
- Deterministische Resteverteilung auf Cent
- Plausibilitätsprüfungen vor Finalisierung

#### D. Workflow / Governance
- Statuskette: `draft -> review -> finalized -> delivered -> disputed -> corrected`
- Finalisierungssperre (immutable Snapshot)
- Revisions-/Korrekturabrechnungen statt Überschreiben

#### E. Output / Zustellung / Forderungen
- PDF-Erstellung je Einzelabrechnung inkl. Kostenzeilen
- Sammel-Export (ZIP/PDF) je Periode
- Zustellstatus je Vertrag (gesendet/zugestellt/fehlgeschlagen)
- Automatische Folgebuchungen:
  - Nachzahlung => Forderung
  - Guthaben => Erstattung/Verrechnung

#### F. Monitoring
- Dashboard: offene Perioden, offene Prüfungen, Widersprüche
- Fristenmonitoring mit Eskalationshinweisen

### 4) Architektur-Roadmap (12 Wochen, 6 Phasen)

#### Phase NK-1 (Woche 1–2): Preflight & Datenqualität
**Backend**
- Endpoint: `GET /billing/periods/{period_id}/preflight`
- Ergebnis: `blockers`, `warnings`, `metrics`

**Frontend**
- Preflight-Panel in `Statements.jsx` (Ampel, Blocker-Liste)

**Akzeptanzkriterien**
- Generierung kann optional blockiert werden, wenn Blocker vorliegen.
- Mindestens 8 Qualitätschecks implementiert (z. B. keine Kostenposition, fehlende Schlüssel, fehlende Flächen).

---

#### Phase NK-2 (Woche 3–4): Rechenkern ausbauen
**Backend**
- `BillingEngine`: implementiere `person_count` und `consumption`
- Einbindung von Zählerablesungen in die Verbrauchsverteilung
- Resteverteilungsstrategie dokumentiert + testbar

**Akzeptanzkriterien**
- 100% Abdeckung der Schlüsseltypen in Tests.
- Bei identischen Inputs deterministische Ergebnisse.

---

#### Phase NK-3 (Woche 5–6): Workflow & Revision
**Backend**
- Statusübergänge mit Guard-Rules
- Finalisieren-Endpoint mit Snapshot-Markierung
- Korrekturabrechnung erzeugt neue Revision

**Frontend**
- Actions: „Zur Prüfung“, „Finalisieren“, „Korrektur starten"
- Revisionshistorie im Detail-View

**Akzeptanzkriterien**
- Finalisierte Revision ist nicht editierbar.
- Jede Korrektur erzeugt Revision `n+1`.

---

#### Phase NK-4 (Woche 7–8): PDF & Zustellung
**Backend**
- PDF-Generator für Einzelabrechnung (`/billing/statements/{id}/pdf`)
- Batch-Export pro Periode
- Zustellstatus speichern

**Frontend**
- Buttons: „PDF“, „Alle exportieren“, „Versand starten"
- Versandstatus-Spalte in Statement-Liste

**Akzeptanzkriterien**
- Pro Periode kann ein vollständiges Zustellpaket erstellt werden.
- Zustellstatus je Einheit nachvollziehbar.

---

#### Phase NK-5 (Woche 9–10): Finanzintegration
**Backend**
- Mapping Statement-Saldo -> Receivable/Refund
- Referenzfelder zur Rückverfolgung (`statement_id`)

**Frontend**
- Anzeige „Folgebuchung erstellt“ im Statement-Detail

**Akzeptanzkriterien**
- Keine manuelle Doppelerfassung von Salden nötig.
- Jede Folgebuchung referenziert die Ausgangsabrechnung.

---

#### Phase NK-6 (Woche 11–12): OCR-gestützter Kostenimport & Ops
**Backend**
- Beleg -> OCR -> Kostenentwurf Endpoint
- Confidence-Felder + manuelle Freigabe

**Frontend**
- Import-Dialog für Rechnungsbelege
- Vorschlags-Mapping (Kostenart, Betrag, Zeitraum)

**Akzeptanzkriterien**
- Mind. 60% der Pflichtfelder aus OCR vorbefüllt (bei geeigneten Belegen).
- Benutzer kann Vorschläge vor dem Speichern korrigieren.

### 5) Konkrete API-Erweiterungen (Vorschlag)
- `GET /billing/periods/{period_id}/preflight`
- `POST /billing/periods/{period_id}/finalize`
- `POST /billing/periods/{period_id}/revisions`
- `GET /billing/statements/{statement_id}/pdf`
- `POST /billing/periods/{period_id}/export`
- `POST /billing/cost-items/import-document`

### 6) Datenmodell-Erweiterungen (Vorschlag)
- `cost_items`: `is_recoverable`, `cost_category`, `source_document_id`, `vat_rate`, `net_amount`, `gross_amount`
- `utility_statements`: `delivery_status`, `delivered_at`, `delivery_channel`, `snapshot_hash`
- neue Entität `BillingPreflightResult` (persistiert oder on-the-fly)

### 7) Teststrategie je Phase
- **Unit**: Verteilungs- und Rundungslogik, Status-Transitions
- **Integration**: End-to-End von Periode -> Kosten -> Generate -> Finalize -> Output
- **Regression**: Referenzfälle mit bekannten Sollwerten
- **UI-Tests**: Preflight-Blocker, Finalisierungssperre, Revisionsdarstellung

### 8) Sprint-1-Backlog (direkt startbar)
1. Preflight-Endpoint (Backend) inkl. 8 Checks
2. Preflight-Panel in `Statements.jsx`
3. `person_count`-Key im BillingEngine
4. `consumption`-Key + Meter-Readings-Mapping
5. Erweiterte Tests in `test_crud_routers.py`
6. Finalize-Endpoint + Status-Guard
7. UI-Button „Finalisieren" + Sperrlogik
8. PDF-Skeleton-Endpoint für Einzelabrechnung
9. Statement-Detail um Revisionsinformationen erweitern
10. Folgebuchungs-Prototyp für Nachzahlung/Guthaben

### 9) KPIs für Erfolg
- Anteil finalisierter Perioden ohne Nachbearbeitung
- Zeit von Periodenbeginn bis Versand
- Anteil automatisch vorbefüllter Kostenpositionen
- Anzahl/Quote Widersprüche je Periode
- Vollständigkeit der Zustellnachweise
