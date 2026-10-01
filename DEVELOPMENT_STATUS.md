# ImmoManager Pro – Entwicklungsstand

Stand: 1. Oktober 2026. Ausgangspunkt: Commit `c64b2f1` auf
`claude/redesign-frontend-ui-RUPYS`, einschließlich PR #32.

## Gefundenes Projekt und Produktziel

Das aktive Repository ist `matthiasalexrsr/ImmoManager-Pro`. Lokale Kopien unter
`C:\02_Projekte_Archiv\ImmoManager`, `Git-Repositories` und `Immobilienverwaltung`
enthalten ältere Entwicklungsstände. Die Fortsetzung basiert auf dem aktuellen
GitHub-Stand; diese Archivkopien wurden nicht verändert.

Das Ziel aus ARCHITEKTURPLAN.md ist eine deutsche Immobilienverwaltung für private
Vermieter mit rund 20 Immobilien: Bestand, Vermietung, Finanzen, Nebenkosten,
Instandhaltung, Dokumente und Berichte. Ergänzend sind Windows-Betrieb,
Aktualisierungen, Erweiterungen, Sprachen und konfigurierbare Ansichten vorgesehen.

## Tatsächlich vorhandener Unterbau

- FastAPI mit versionierter API, SQLAlchemy, SQLite/PostgreSQL und Alembic.
- JWT-Anmeldung, Rollen, Audit-Logging und persistente lokale Laufzeitverzeichnisse.
- React-Oberfläche mit Stammdaten, Vertragsverwaltung, Mietübersicht, Abrechnung,
  Dokumenten, Instandhaltung, Vermarktung, Berichten und Einstellungen.
- Geführtes Dashboard und Windows-Starter mit lokaler Datenhaltung und Backups.
- Fachliche Engines für Vertragsabrechnung, Mahnungen und Betriebskosten.
- CI, Backend- und Frontend-Tests. Viele Aufgaben in PLAN.md,
  IMPLEMENTATION_PLAN.md und CODEBASE_AUDIT_TODO.md sind inzwischen umgesetzt.
- Externe Integrationen sind teilweise Adapter/Platzhalter; echte Kontozugänge
  und End-to-End-Verifikation der jeweiligen Dienste fehlen.

## In dieser Fortsetzung umgesetzt

1. Zahlungsbelege für Forderungen und Sollstellungen: Betrag, Datum, Bemerkung,
   dauerhafte Speicherung, Zahlungshistorie und korrekte Teilzahlungen.
2. Atomare SQL-Transaktion für Beleg und Saldo, Schutz gegen verlorene parallele
   Änderungen sowie idempotente Wiederholung identischer Zahlungsanforderungen.
3. Serverseitige Prüfung positiver Cent-Beträge und des offenen Restbetrags.
4. Mietübersicht vereinfacht: klare Aktionen, offene Posten als Standardansicht,
   Summen je ausgewähltem Bereich, sichtbare Ladefehler und erneutes Laden.
5. Vollständige paginierte Listenabrufe für die Mietübersicht und Forderungen.
6. Teilzahlungen werden in Forderungsalterung, Dashboard und Berichten berücksichtigt;
   erfasste Mietzahlungen erreichen auch die Vertragsabrechnung.
7. Export/Import korrigiert Eltern-Kind-Verweise beim Erzeugen neuer IDs und erhält
   Zahlungssalden und Belege. Importfehler werden im Ergebnis zurückgegeben.
8. Additive SQLite-Aktualisierung und Alembic-Migration mit Übernahme bisher bereits
   als bezahlt markierter Forderungen.
9. Neue UI-Texte in Deutsch, Englisch und Spanisch; übersetzte Zahlungsstatusanzeigen.
10. Layoutkorrektur für mobile Breiten und lesbare Summenkarten.
11. npm-Lockdatei aktualisiert: zwölf gemeldete Sicherheitslücken behoben.

## Grenzen dieses Stands

Manuelle Zahlungszuordnungen erzeugen noch keine Bankbuchung. Derselbe Geldeingang
darf nicht zusätzlich als eigenständige manuelle Zahlung und Bankbuchung in der
Vertragsabrechnung erfasst werden. Die beiden Ansichten Sollstellungen/Forderungen
sind weiterhin getrennte Register; es gibt noch keinen gemeinsamen Forderungsschlüssel.
Zahlungsstorno und automatische Bankzuordnung sind noch nicht implementiert.

Der JSON-Export bildet die dort registrierten Geschäftsentitäten ab. Er ist keine
vollständige Sicherung von Upload-Dateien, Benutzerkonten, allen Abrechnungstabellen
oder externen Integrationszuständen. Eine vollständige Wiederherstellung muss diese
Bestandteile zusätzlich sichern. Der Import meldet Fehler, ist aber noch kein
vollständig atomarer Wiederherstellungsprozess.

## Nächste priorisierte Arbeitspakete

| Priorität | Arbeitspaket | Fertig, wenn |
|---|---|---|
| P1 | Bankbuchungen und Zahlungszuordnungen verknüpfen | Bestehende Buchungen auswählbar, Doppelzählung ausgeschlossen, Abgleich nachvollziehbar |
| P1 | Zahlungsstorno/Korrektur | Gegenbeleg statt stiller Löschung, Restbetrag und Berichte konsistent |
| P1 | Vollständige Sicherung/Wiederherstellung | Datenbank, Uploads, Benutzer und Integrationszustände gemeinsam geprüft wiederherstellbar |
| P1 | Restliche stille Datenladefehler | Nutzer sehen Ausfälle in allen Finanz- und Abrechnungsseiten |
| P2 | Durchgehende Browser-E2E in CI | Anmeldung, Bestand, Vertrag, Zahlung und Abrechnung regelmäßig im Browser geprüft |
| P2 | Wiederkehrende Sollstellung vereinfachen | Monatliche Erstellung aus aktiven Verträgen mit Vorschau und Duplikatschutz |
| P2 | Einheitliche Forderungsquelle | Sollstellungen und sonstige Forderungen über explizite Links statt unabhängiger Statuspflege |
| P2 | Datenmodell-/API-Kompatibilität vereinfachen | Dynamische Modellergänzungen aus backend/compat durch reguläre Modelle und Migrationen ersetzt |
| P3 | Externe Kommunikation und Portale | Reale Zugangsdaten konfigurierbar und Adapter verifiziert |
| P3 | Erweiterungen, Updates, 2FA und Portfoliozugriff | Konkrete Laufzeit- und Berechtigungsszenarien durch Integrationstests abgesichert |

## Prüfung

- Backend: gesamte Suite mit Speicher- und SQLite-Backend; Mindestabdeckung 80 %.
- Frontend: ESLint, Vitest, Produktionsbuild und npm-Audit.
- Migration: Alembic-Kette auf leerer SQLite-Datenbank; wiederholbarer lokaler
  Schema-Upgrade für eine bereits bestehende SQLite-Datenbank.
- Browser: Edge, echter lokaler Server, Demo-Anmeldung, Zahlung speichern,
  Beleg lesen, Desktop und mobile Breite; keine JavaScript-Laufzeitfehler.
- PostgreSQL und Docker wurden auf diesem Windows-Rechner nicht ausgeführt.

Reproduzierbare Standardbefehle stehen in README.md. Die historische Roadmap bleibt
als Kontext erhalten; dieser Stand und die tatsächlichen Tests führen die Fortsetzung.
