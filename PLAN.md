# ImmoManager Pro – Plan zur Softwareentwicklung

## Ziel
Eine vollständige, konsistente deutsche UI-Textbasis für ImmoManager Pro strukturiert erfassen, integrieren und wartbar machen. Fokus: Internationalisierung (i18n), Qualitätsprozesse und Rollout.

## Annahmen
- Produktname: **ImmoManager Pro**, Kurzname: **ImmoManager**.
- UI-Strings werden zentral verwaltet (z. B. i18n JSON/YAML oder DB-gestützte Localization-API).
- Deutsche Texte sind führend; weitere Sprachen folgen.

## Arbeitsphasen

### 1) Analyse & Struktur
- Domain- und Navigationsstruktur aus dem bereitgestellten Textkatalog ableiten.
- String-Gruppierung definieren (z. B. `navigation`, `auth`, `dashboard`, `portfolio`, `properties`, `units`, `tenants_contracts`, `finance`, `maintenance`, `documents`, `tasks`, `calendar`, `reports`, `integrations`, `settings`, `help`, `system`, `validation`, `empty_states`, `errors`).
- Terminologie-Lexikon festlegen (Immobilie/Einheit/Vertrag/Buchung) für Konsistenz.

**Ergebnis:** Informationsarchitektur für i18n-Schlüssel.

### 2) i18n-Design & Datenmodell
- Schlüsselkonventionen definieren (z. B. `section.scope.label`).
- Platzhalter-Notation festlegen (z. B. `{count}`, `{name}`, `{date}`).
- Pluralisierung und Geschlecht berücksichtigen (i18n-Framework evaluieren).

**Ergebnis:** i18n-Konventionen + Beispiel-Schema.

### 3) String-Mapping & Migration
- Den gesamten UI-Katalog in strukturierte Schlüssel überführen.
- Abgleich mit bestehenden UI-Flows (Login, Dashboard, Portfolio, etc.).
- Lücken/Redundanzen markieren.

**Ergebnis:** Vollständige de-DE String-Datei (oder mehrere Module).

### 4) Implementierung im Frontend
- i18n-Provider integrieren (z. B. react-intl, i18next, vue-i18n).
- String-Keys in UI-Komponenten einsetzen.
- Lokalisierte Platzhalter und Datums-/Währungsformate verwenden.

**Ergebnis:** UI nutzt zentrale Strings.

### 5) Qualitätssicherung
- Linter/Tests zur Schlüssel-Vollständigkeit (fehlende Keys erkennen).
- Snapshot/Visual-Checks für Layouts mit langen Strings.
- Review der deutschen Texte auf Konsistenz und Tonalität.

**Ergebnis:** QA-Checkliste + automatisierte Checks.

### 6) Rollout & Betrieb
- Übersetzungsworkflow definieren (Glossar, Freigaben, Änderungen).
- Versionierung der Strings (Changelog für UI-Texte).
- Monitoring von Missing-Keys zur Laufzeit.

**Ergebnis:** Nachhaltiger Betrieb der Lokalisierung.

## Deliverables (kurz)
1. Strukturierte i18n-Schlüssel-Architektur.
2. Vollständige de-DE Strings gemäß Katalog.
3. i18n-Integration im UI.
4. QA-Prozesse und Linting.
5. Betriebs- und Übersetzungsworkflow.

## Nächste Schritte
1. Ziel-Framework identifizieren (React/Vue/Angular etc.).
2. i18n-Konventionen finalisieren.
3. String-Dateien erstellen und in UI integrieren.

