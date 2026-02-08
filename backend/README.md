# ImmoManager Pro Backend

Dieses Backend ist ein FastAPI-Startpunkt für die ImmoManager-Pro-Anwendung.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Starten

```bash
uvicorn app:app --reload
```

## Endpunkte (Auszug)

- `GET /health` – Health-Check
- `GET /portfolios` – Portfolios auflisten
- `POST /portfolios` – Portfolio anlegen
- `GET /properties` – Immobilien auflisten
- `POST /properties` – Immobilie anlegen
- `GET /units` – Einheiten auflisten
- `POST /units` – Einheit anlegen
- `GET /tenants` – Mieter auflisten
- `POST /tenants` – Mieter anlegen
- `GET /contracts` – Verträge auflisten
- `POST /contracts` – Vertrag anlegen
- `GET /accounts` – Konten auflisten
- `POST /accounts` – Konto anlegen
- `GET /bookings` – Buchungen auflisten
- `POST /bookings` – Buchung anlegen
- `GET /receivables` – Forderungen auflisten
- `POST /receivables` – Forderung anlegen
- `GET /invoices` – Rechnungen auflisten
- `POST /invoices` – Rechnung anlegen
- `GET /maintenance` – Instandhaltungsfälle auflisten
- `POST /maintenance` – Instandhaltungsfall anlegen
- `GET /documents` – Dokumente auflisten
- `POST /documents` – Dokument anlegen
- `GET /tasks` – Aufgaben auflisten
- `POST /tasks` – Aufgabe anlegen
- `GET /calendar` – Termine auflisten
- `POST /calendar` – Termin anlegen
- `GET /categories` – Kategorien auflisten
- `POST /categories` – Kategorie anlegen
- `GET /reports/summary` – Kennzahlenübersicht abrufen
- `GET /reports/finance` – Finanzreport nach Kategorien abrufen
- `GET /reports/occupancy` – Vermietungsquote abrufen
- `GET /reports/receivables-aging` – Offene Forderungen nach Alter abrufen
- `GET /reports/cashflow` – Cashflow-Übersicht abrufen
- `GET /reports/contracts-expiring?days=90` – Auslaufende Verträge im Zeitraum abrufen
- `GET /reports/maintenance-costs` – Instandhaltungskosten nach Kategorie abrufen
- `GET /i18n/manifest` – Locale-Metadaten abrufen
- `GET /i18n/{locale}` – Locale-Strings abrufen

Für alle Ressourcen stehen zusätzlich `PUT /{id}` (Aktualisieren) und `DELETE /{id}` (Löschen) zur Verfügung.

Die Daten werden aktuell in-memory gespeichert und dienen als Grundlage für die weitere Implementierung.
