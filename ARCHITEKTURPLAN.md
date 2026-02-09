# ImmoManager Pro – Vollständiger Architektur- und Funktionsplan (Windows, produktionsreif)

## 1. Zielbild
ImmoManager Pro wird als voll funktionsfähige Immobilienverwaltungssoftware für private Vermieter (ca. 20 vermietete Immobilien) konzipiert. Die Anwendung deckt den gesamten operativen Lebenszyklus ab:

- Objekt- und Einheitenverwaltung
- Mieter- und Vertragsmanagement
- Soll-/Ist-Mieten, Forderungen, Mahnwesen
- Nebenkosten- und Jahresabrechnung
- Eingangsrechnungen, Belegprüfung, Kostenzuordnung
- Instandhaltung, Aufgaben, Fristen
- Foto-, Dokument- und Inseratsverwaltung
- Berichte, Export, steuerrelevante Auswertungen

Die Lösung wird von Anfang an backend-zentriert und API-first aufgebaut, sodass später Web-Frontend, Mobile-Apps und Integrationen sauber andocken.

---

## 2. Technische Gesamtarchitektur

## 2.1 Architekturprinzipien
- Modulare Monolith-Architektur (klar getrennte Domänenmodule, ein Deployable)
- API-first (OpenAPI, stabile Versionierung)
- Ereignisorientierte Nebenprozesse (z. B. Benachrichtigungen, Dokumentverarbeitung)
- Strikte Mandantentrennung per Portfolio
- Nachvollziehbarkeit per Audit-Log für kritische Vorgänge

## 2.2 Backend-Stack (empfohlen)
- Sprache/Framework: Python + FastAPI
- Datenbank: PostgreSQL (prod), SQLite optional lokal
- ORM/Migration: SQLAlchemy 2 + Alembic
- Queue/Background Jobs: Redis + RQ/Celery
- Dateiablage: S3-kompatibel (lokal MinIO), optional OneDrive/SharePoint-Connector
- Suche: PostgreSQL Full Text (später optional OpenSearch)

## 2.3 Windows-Betrieb
- Deployment-Option A (empfohlen): Docker Desktop + Docker Compose (Windows 11 Pro)
- Deployment-Option B: Native Services (NSSM/Windows Service Wrapper)
- Lokale Pfade und Speicherstrategie für Backups/Anhänge mit NTFS-Berechtigungen
- Geplanter Task für Backups via Task Scheduler

---

## 3. Backend-Domänenmodule (vollständig)

## 3.1 Identity & Access
- Benutzer, Teams, Rollen, Rechte
- 2FA, Session Management, Geräteverwaltung
- Passwort-Policies und Login-Limits
- Rollenmodell:
  - Eigentümer
  - Verwalter
  - Buchhaltung
  - Techniker
  - Nur Lesen

## 3.2 Portfolio & Stammdaten
- Portfolios, Immobilien, Einheiten
- Stammdaten für Objektart, Einheitstyp, Zustände
- Historisierung zentraler Strukturänderungen

## 3.3 CRM: Mieter & Vertrag
- Mieterprofil inkl. Kontakt, Bankdaten, Dokumente
- Vertragsdaten: Laufzeit, Kaution, Index-/Staffeloption
- Vertragsstatus und Verlängerungs-/Kündigungsworkflows
- Übergabeprotokoll inkl. Zählerstände/Fotos

## 3.4 Finanzkern
- Konten (Bank/Kasse/Rücklage/Kredit)
- Buchungen mit Kategorie, Objekt-/Einheitszuordnung
- Offene Posten / Forderungen (Sollstellung)
- Rechnungen (Eingangsrechnungen) inkl. Prüfstatus
- Steuerlogik (MwSt.-Sätze, steuerrelevante Exporte)

## 3.5 Abrechnung (Betriebskosten)
- Umlagefähige vs. nicht umlagefähige Kosten
- Verteilerschlüssel (m², Einheiten, Personen, Verbrauch)
- Abrechnungsperioden je Objekt/Einheit
- Abrechnungserstellung inkl. Nachzahlung/Guthaben
- Revisionssichere Versionierung der erzeugten Abrechnung

## 3.6 Dokumente & Medien
- Dokumentbibliothek mit Tagging und Versionen
- OCR-Pipeline für Rechnungen/Belege (optional Phase 2)
- Fotoverwaltung (Objekt, Einheit, Schäden, Übergabe)
- Verknüpfung von Dateien mit Domänenobjekten

## 3.7 Instandhaltung & Aufgaben
- Tickets/Fälle inkl. Priorität, Zuständigkeit, SLA
- Maßnahmen-/Angebots-/Rechnungsfluss pro Fall
- Wiederkehrende Aufgaben (Wartung, Prüfungen)
- Eskalationsregeln bei Fristüberschreitung

## 3.8 Inserate & Vermarktung
- Exposé-Datenmodell (Text, Fotos, Eckdaten)
- Veröffentlichungsvorbereitung (Portaladapter später)
- Interessenten-Tracking (Anfrage, Besichtigung, Status)
- Leerstandspipeline pro Einheit

## 3.9 Benachrichtigungen & Kommunikation
- In-App, E-Mail, optional Push/Webhook
- Ereignisse: überfällige Zahlung, Vertragsende, fällige Aufgabe
- Vorlagenmanagement für Mahnungen/E-Mails
- Versandprotokoll und Zustellstatus

## 3.10 Reporting & Analytics
- KPI-Dashboard (Vermietungsquote, Cashflow, Forderungen, Instandhaltung)
- Portfolio-/Objekt-/Einheitsberichte
- Finanzberichte, Forderungsalterung, Vertragsfristen
- Export: CSV/PDF/DATEV

---

## 4. Datenmodell (Fachlich, vollständig)

## 4.1 Kernentitäten
- User, Role, Permission
- Portfolio, Property, Unit
- Tenant, Contract, Deposit
- Account, Category, Booking, Receivable, Invoice
- MaintenanceCase, Task, CalendarEvent
- Document, MediaAsset
- Listing, Lead, ViewingAppointment
- BillingPeriod, AllocationKey, UtilityStatement

## 4.2 Wichtige Relationen
- Portfolio 1:n Property
- Property 1:n Unit
- Unit 1:n Contract (zeitlich disjunkt)
- Contract 1:n Receivable
- Account 1:n Booking
- Property/Unit/Contract 1:n Document/Media
- Property/Unit 1:n MaintenanceCase

## 4.3 Konsistenzregeln
- Keine überlappenden aktiven Verträge pro Einheit
- Buchung darf nur existierende Referenzen tragen
- Vertragsende >= Vertragsbeginn
- Abrechnungsperiode je Objekt eindeutig
- Löschungen nur mit fachlicher Kaskade und Audit-Log

---

## 5. API-Design

## 5.1 Standards
- REST + JSON, klare Ressourcenstruktur
- Idempotente Writes (PUT/PATCH mit Version/ETag)
- Validierungsfehler standardisiert (RFC7807-ähnlich)
- API-Versionierung `/api/v1/...`

## 5.2 Kritische Endpunkte (Auszug)
- `/auth/*`, `/users/*`, `/roles/*`
- `/portfolios/*`, `/properties/*`, `/units/*`
- `/tenants/*`, `/contracts/*`, `/deposits/*`
- `/accounts/*`, `/bookings/*`, `/receivables/*`, `/invoices/*`
- `/billing-periods/*`, `/utility-statements/*`
- `/maintenance/*`, `/tasks/*`
- `/documents/*`, `/media/*`
- `/listings/*`, `/leads/*`
- `/reports/*`

---

## 6. Sicherheit, Datenschutz, Compliance
- RBAC auf Ressourcenebene
- Verschlüsselte Speicherung sensibler Felder (z. B. IBAN)
- TLS, sichere Cookies, Rotation von Secrets
- DSGVO: Datenexport, Löschkonzepte, Einwilligungen
- Audit-Log für sicherheits-/finanzrelevante Aktionen
- Backup + Restore-Prozesse getestet

---

## 7. Qualitätsstrategie (Definition of Done)

## 7.1 Testpyramide
- Unit-Tests für Domänenlogik
- API-Integrationstests mit Testdatenbank
- E2E-Tests für Kernflows (Vertrag bis Zahlung, Rechnung bis Abrechnung)

## 7.2 Lint & Qualität
- Ruff/Flake8 + Black + isort + Mypy
- SQL-Migrationschecks und Schema-Drift-Prüfung
- Mindestabdeckung: 80% im Domänenkern

## 7.3 Kritische End-to-End-Use-Cases
1. Einheit anlegen → Vertrag aktivieren → Sollstellungen erzeugen
2. Zahlungseingang buchen → Forderung ausgleichen
3. Eingangsrechnung erfassen → Objekt/Einheit zuordnen → Abrechnung berücksichtigen
4. Instandhaltungsfall eröffnen → Aufgabe erzeugen → Abschluss mit Rechnung
5. Vertragsende-Alarm → Verlängern/Kündigen

---

## 8. Empfohlene Zusatzfunktionen (sinnvoll)
- Bankabgleich-Import (CSV/MT940) mit Matching-Regeln
- OCR-gestützte Rechnungsvorerfassung
- Regelbasierte Zuordnung (Kategorie, Objekt)
- Budgetplanung pro Objekt mit Abweichungsanalyse
- Forecast für Liquidität auf 3/6/12 Monate
- Wiedervorlagen und Fristen-Cockpit

---

## 9. Umsetzungsphasen (Roadmap)

## Phase 1 – Fundament (4–6 Wochen)
- Auth/Rollen, Portfolio/Objekt/Einheit, Mieter/Vertrag
- Finanzkern (Konten, Buchungen, Forderungen)
- Dokumente (Upload, Verknüpfung)
- Basisreporting

## Phase 2 – Operative Tiefe (4–8 Wochen)
- Abrechnungsmodule (Betriebskosten vollständig)
- Instandhaltung/ToDos/Fristen
- Rechnungsworkflow inkl. Zuordnung
- Benachrichtigungen + Vorlagen

## Phase 3 – Produktivierung (3–5 Wochen)
- Härtung Sicherheit, Audit, Backup/Restore
- Import/Export, DATEV, Monitoring
- Windows-Deploymentpaket + Betriebsdoku

## Phase 4 – Wachstum (optional)
- Inseratsmanagement + Lead-Tracking
- OCR/Automationen
- Erweiterte Analytics/Forecast

---

## 10. Ergebnisbild für Ihren konkreten Anwendungsfall (20 private Mietobjekte)
Nach Umsetzung der obigen Architektur erhalten Sie eine stabile, übersichtliche und vollständig nutzbare Verwaltungsplattform, mit der Sie:

- alle Objekte zentral verwalten,
- laufende Mietverhältnisse rechtssicher steuern,
- Einnahmen/Ausgaben transparent verfolgen,
- Rechnungen/Belege sauber zuordnen,
- Fristen und Aufgaben verlässlich organisieren,
- und steuer-/abrechnungsrelevante Auswertungen konsistent erzeugen.

Damit ist ImmoManager Pro für Ihren Zielumfang (ca. 20 vermietete Immobilien) fachlich und technisch vollständig aufgestellt.
