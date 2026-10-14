# Dokumente

Maßgeblich ist immer der Code. Die Dokumente hier beschreiben ihn; ältere Pläne sind als Historie markiert.

## Für Anwender
- [RELEASE_NOTES.md](RELEASE_NOTES.md): was die aktuelle Version kann, Hinweise zum Update, bekannte Grenzen.
- `packaging/release/LIES MICH.txt`: Installieren, Datenordner, Sicherung, Aktualisieren (liegt jedem Windows-Paket bei).

## Für die Weiterentwicklung
- [ARCHITECTURE.md](ARCHITECTURE.md): Aufbau, wo was liegt, Rezepte für neue Felder, Seiten und Schnittstellen.
- [OPERATIONS_BACKUP_SECRETS_20261008.md](OPERATIONS_BACKUP_SECRETS_20261008.md): explizites Upgrade, Vollbackup, Wiederherstellung, Schlüssel.
- [PORTFOLIO_ACCESS_20261007.md](PORTFOLIO_ACCESS_20261007.md): wer welche Bestände sieht.
- [FILE_ACCESS_AUDIT_20261007.md](FILE_ACCESS_AUDIT_20261007.md): Dateizugriff.
- [DURABLE_JOBS_20261007.md](DURABLE_JOBS_20261007.md): Hintergrundjobs.
- [GLOBAL_SEARCH_20261007.md](GLOBAL_SEARCH_20261007.md): Suche über den ganzen Bestand.
- [POSTGRES_DECIMAL_MIGRATION_20261007.md](POSTGRES_DECIMAL_MIGRATION_20261007.md): Geldbeträge in PostgreSQL.

### Fachmodule
| Dokument | Inhalt |
| --- | --- |
| [FINANCE_PRECISION_20261008.md](FINANCE_PRECISION_20261008.md) | Cent-genaue Finanzen, Stornos, Berichtsfilter |
| [RENT_PAYMENTS_20261013.md](RENT_PAYMENTS_20261013.md) | Mietzahlungen und Vertragszuordnung |
| [BILLING_REGRESSION_20261008.md](BILLING_REGRESSION_20261008.md) | Nebenkostenabrechnung: Zähler, Personen, Korrekturen |
| [DEPOSITS_20261011.md](DEPOSITS_20261011.md) | Kaution |
| [DUNNING_20261011.md](DUNNING_20261011.md) | Mahnwesen |
| [INVOICE_REVIEW_20261011.md](INVOICE_REVIEW_20261011.md) | Rechnungsprüfung |
| [HANDOVER_PROTOCOL_20261008.md](HANDOVER_PROTOCOL_20261008.md) | Übergabeprotokoll |
| [SERVICE_CONTRACTS_20261008.md](SERVICE_CONTRACTS_20261008.md) | Objekt- und Energieverträge |
| [MAINTENANCE_PROJECTS_20261008.md](MAINTENANCE_PROJECTS_20261008.md) | Wartungsfall als Projektakte |
| [WGB_CONSOLIDATION_20261007.md](WGB_CONSOLIDATION_20261007.md) | Wohnungsgeberbestätigung und Originalarchiv |
| [AKTENWERK_INTERFACE_20261014.md](AKTENWERK_INTERFACE_20261014.md) | Schnittstelle zum DMS Aktenwerk |

## Prüfnachweise und Historie
Diese Dokumente halten fest, was zu einem bestimmten Stand geprüft oder geplant war. Ihre Aussagen über fehlende Funktionen können überholt sein.
- **Prüfnachweise:**
  - `CLAUDE_REVIEW_20261013_*`, `HARDENING_20261007_*`, `COMPETITIVE_*`;
  - `CONTINUATION_20261013.md`, `VERMIETER1_LIVE_20261007.md`, `WISO_LIVE_20261007.md`;
  - `UI_WORKSPACE_20261007_PLAN.md`.
- **Im Wurzelverzeichnis** (Pläne und Auswertungen aus Februar bis Oktober 2026, nicht mehr gepflegt):
  - `ARCHITEKTURPLAN.md`, `PLAN.md`, `IMPLEMENTATION_PLAN.md`, `EVALUATION.md`, `IST_SOLL_EVALUATION.md`;
  - `CODEBASE_AUDIT_TODO.md`, `HARDENING.md`, `CHANGES.md`, `claude_session_todo_analysis.md`;
  - `CLAUDE_HANDOFF_20261007.md`, `PARTY_WORKSPACE.md`.
- **Änderungen je Stand:** [`CHANGELOG.md`](../CHANGELOG.md).
