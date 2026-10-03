# Umsetzung des freigegebenen Gesamtplans

Stand: 03.10.2026. Der Nutzer hat den vollständigen Analyse- und Implementierungsplan ausdrücklich zur Umsetzung freigegeben. WISO-Zieljahr: **2026 zuerst**. Diese Datei verfolgt den tatsächlichen Fortschritt; eine Planung oder ein separat grünes Paket ist keine ausgelieferte Funktion.

## Ausgangspunkt und Arbeitsregeln

- Integrationsbasis: `679c8de`; laufende Vorschau bisher Release 126 (`1910f25`).
- Bestehende Fachjournale, Rechte, Originalarchive und Wiederherstellungswege weiterverwenden.
- Gesamtbestände nicht abschneiden: SQL-Filter, stabile Seiten und fortsetzbare Arbeitsschritte; technische Budgets betreffen einzelne Vorgänge.
- Neue finanzielle Ableitungen dezimalgenau, mit Quellbelegen und ohne doppelte Zahlungs-/Buchungszählung.
- Geänderte Rechte/Revisionen unmittelbar vor Commit prüfen; verlorene Antworten wiederholsicher behandeln.
- Entwicklungspakete besitzen eigenen Checkout/Owner. Root integriert und prüft Zusammenspiel, Browser, PostgreSQL und Recovery.
- Keine Live-Mieter-, TEHA-Schreib- oder Steuerdaten für synthetische Tests verändern.

## Pakete und verbindlicher Abschluss

| Paket | Inhalt | Abschlussnachweis | Aktueller Zustand |
|---|---|---|---|
| A | Konsolidierung, gemeinsame Releaseprüfung, aktuelles Anforderungsinventar | Exakter Gesamtcommit, vollständige erforderliche Prüfungen, kontrollierte Auslieferung | Begonnen |
| B | Vollständige Listen/Suche/Kennzahlen, Unitworkspace, einheitliche UI | Letzte Datensätze erreichbar; keine falschen Leerbestände/Altdaten; mobile Browserprobe | Unitworkspace integriert5e636e0; vollständige Suche geprüft, Dokument-/Einheitenlisten in Arbeit |
| C | Mediengetrennte Verbrauchsgrundlage, historische Mess-/Bewohnerdaten, Kostenregeln, Widerspruch | Wasser/Strom-Gegenprobe 50:50; explizite fehlende Zuordnung; unveränderte Originaljahre | Medienbindung integriert5de8762; historische Quellen separat in Arbeit |
| D | Zahlungsfluss, Periodenergebnis, Prognose, Kaution/Mahnungen/Rechnungsprüfung | Abstimmung Gesamt/Objekt/Einheit; keine Doppelzählung; gleiche Exportwerte | Offen |
| E | Vollständiger dauerhafter Scheduler, Müll-/Ablesepläne/ICS | >10.000 Ereignisse fortsetzbar, Neustart/Parallelworker ohne Dublette | Schedulerüberführung geplant0cc9590 und in Arbeit; Betriebspläne anschließend |
| F | Wohnungsgeberbestätigung und geführte Übergabe | Unveränderliche Korrekturoriginale, Unicode/Mehrseiten-PDF, exakter Retry, Browser | Backend/PDF/Accountfence integriertc253eaa; echte UI-Anbindung im bisherigen Assistenzchat in Arbeit |
| G | Strom-/Dienstleistungsverträge, versionierte Tarife/Fristen | Tarif-/Fristwechsel, mehrere Orte, keine Doppelbuchung | Offen |
| H | Schäden/Projekte, Handwerker, Aufträge/Kosten/Protokolle | Mehrere Gewerke, Nachtrag, Teilrechnung, Restmängel, Zyklenschutz | Offen |
| I | Dauerhaftes Integrationsjournal, Secretablage, TEHA-Abgleich | Neustart/Recovery, vollständige Historie, belegte fachliche Zuordnung/Import | History-Core integriert8bb1d26; Manager/Runtime im bisherigen Assistenzchat uncommittet |
| J | WISO-Steuerjahr2026-Mapping und Export | Herstellerfälle und echter Wertabgleich nach Zielimport | Mappingarbeit offen; Zielprogramm nicht installiert |
| K | Kommunikationszentrum, Kanäle, Vermarktung, Portal, Analytik/Offline | Nachweisbare Ergebnisse und getrennte externe Identitäten | Kommunikationspaket d0a63dd separat plus laufende Änderungen |
| L | DDL-freier Start, reproduzierbare Updates, Vollbackups/Restore, Betrieb/Historie/API | Start ohne DDL; abgebrochenes Upgrade rückholbar; echte Restoreprobe | Produktionsstart/PG-CI/Devrequirements integrierta1c6e2c; Vollbackupautomatik und isolierte Restoreprobe offen |

## Aktuelle Ownership und Schemafolge

- Root: Integration, Housing-Review/Routerregistrierung/PDF-QA, History-Core-Komposition und unabhängige Gates.
- Native Fachaudit-Agent: `work/billing-measurement-history`, historische Mess-/Bewohnerquellen und Berechnung.
- Native Plattform-Agent: `work/durable-scheduler`, Überführung sämtlicher Schedulerfamilien auf dauerhafte Jobs.
- Native UI-Agent: `work/bounded-legacy-lists`, vollständige Dokument-/Einheitenlisten und danach weitere Altansichten.
- Bestehender Frontend-Assistenzchat: Housing-API-/UI-Anbindung gegen echten Backendhandoff.
- Bestehender Backend-Assistenzchat: Manager/HTTP, anschließend Runtime/Recovery der privaten Integrationshistorie.
- Schemafolge: Historyd2 → Medienbindunge2 bereits integriert. Scheduler`f2a2b3c4d5e6` folgt aufe2; Messhistorie`g2a2b3c4d5e6` folgt auff2. Keine Platzhalter, parallelen Köpfe oder Blindstempel.

## Gemeinsame Abnahme

Memory und echter SQLite-/PostgreSQL-Betrieb; verlorene Antwort, stale Revision, Rechteentzug, Prozessabbruch, unveränderte Originale, vollständiger Datenschutz-/Recoveryumfang. UI bei 320/360/1440 Pixeln und Tastatur. Großbestand zunächst 100.000, anschließend 1 Mio. Finanzzeilen mit 20 Jahren Historie und zehn parallelen Benutzern auf dokumentierter Hardware. Leistungsangaben erst aus Messungen. Normale und lange PDFs rendern und visuell prüfen.

## Externe Voraussetzungen

WISO-Steuer-Zielimport erfordert die passende Windowsversion für Steuerjahr2026. Bereits untersuchter TEHA-Zugang und Transport ersetzen keinen bestätigten fachlichen Schreibtest. Zugangsdaten und private Beobachtungswerte bleiben außerhalb des Quellcodes und allgemeiner Logs.
