# ImmoManager Pro i18n

Diese Ablage enthält die Lokalisierungsdateien für ImmoManager Pro.

## Struktur

- `de-DE.json` enthält den vollständigen deutschen UI-String-Katalog.
- `manifest.json` definiert die verfügbaren Locales und das Standard-Locale.

## Schlüsselkonventionen

- Gruppierung nach Funktionsbereichen (z. B. `navigation`, `auth`, `dashboard`).
- Flache, lesbare Schlüssel je Bereich, z. B. `dashboard.headings.keyMetrics`.
- Platzhalter werden in geschweiften Klammern notiert (z. B. `{count}`), sofern benötigt.

## Erweiterung

1. Neues Locale in `manifest.json` ergänzen.
2. Neue Locale-Datei in `i18n/` anlegen (z. B. `en-US.json`).
3. Inhalte anhand von `de-DE.json` strukturkonform pflegen.
