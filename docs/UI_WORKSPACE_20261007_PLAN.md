# Visuelle Überarbeitung des Verwaltungsarbeitsplatzes

> Ausführung mit Astra-Ultra-Agenten und unabhängiger Browserabnahme. Der Benutzer hat den vollständigen UI-Umbau und autonome Umsetzung ausdrücklich autorisiert; am 7. Oktober priorisiert er die sichtbare Qualität erneut. Die laufende Dokumenten-/Sicherheitsarbeit bleibt erhalten.

## Ziel und Gestaltungsentscheidung

Die Anwendung soll als zusammenhängender, professioneller Verwaltungsarbeitsplatz wirken. Die tatsächliche Browseransicht zeigt derzeit etwa 40 offene Navigationspunkte und viele gleichgewichtige Kennzahl-/Prozesskarten. Seitenname, Hauptüberschrift und Tabellenüberschrift wiederholen sich. Auf Mobilgeräten verschwinden Navigationsbeschriftungen. Diese konkreten Ursachen werden strukturell korrigiert.

Gewählte Richtung: kompakte dunkle Navigation, sehr heller neutraler Arbeitsbereich, weiße Inhaltsflächen, dunkle gut lesbare Schrift und zurückhaltendes Petrol für Hauptaktionen. Klare Typografie und Abstände ersetzen die große Zahl gleichgewichtiger Rahmen. Vorhandene Komponenten und Fachlogik werden weiterverwendet. Ein neues UI-Framework oder eine bloße Farbänderung würde den Auftrag nicht angemessen erfüllen.

**Gemeinsamer Vertrag:** `index.css` ist die tatsächlich geladene globale Basis; `styles.css` wird nicht verwendet. Nur der Shell-Agent verändert globale Regeln. Fachbereiche bekommen eigene, begrenzte CSS-Klassen. Bestehende semantische `--color-*`-Variablen bleiben erhalten. Primärfarbe `#176b63`, Hover `#12564f`, heller Akzent `#e2f1ed`, Seitenfläche `#f4f6f5`, Text `#182a30`, Sekundärtext `#586a70`, Rahmen `#dce4e0`; dunkler Modus erhält passende Gegenwerte. Grundtext 15 px, Formularinhalte mindestens 14 px, Überschriften 26–30 px, Flächenradien 10–14 px, Bereichsabstände 20–28 px. Systemschriften bleiben lokal verfügbar, keine externen Fontabrufe.

## Paket UI-1 – Navigation und gemeinsame Gestaltung

**Besitzer:** responsive_astra. Dateien: `Layout.jsx`, `index.css`, bei Bedarf eigene Shell-CSS und gezielte Navigationstests. API-/Sitzungslogik aus Paket 5 erhalten.

- [x] Hauptnavigation kompakt gliedern; häufige Einstiege sichtbar, übrige Bereiche aufklappbar. Alle bisherigen Routen bleiben erreichbar. Aktiver Bereich öffnet sich bei direkter Navigation; aktive Seite erkennbar. Gruppenschalter erhalten `aria-expanded` und Tastaturbedienung.
- [x] Sidebar, Produktkopf, Topbar und Suche als eine zusammenhängende Shell gestalten. Seitenname in der Topbar nur als dezenter Kontext, keine konkurrierende zweite Hauptüberschrift. Abmeldung, Sprache, Theme und Hilfe erreichbar halten.
- [x] Mobilen Drawer mit vollständigen Beschriftungen, Schließen-/Escape-/Fokusverhalten und ohne textlose breite Fläche gestalten. Eingeklappte Desktopnavigation bleibt eindeutig bedienbar.
- [x] Gemeinsame Typografie, Buttons, Eingaben, Dialoge, Tabs, Rahmen und Abstände vereinheitlichen. Fokus, lesbare Fehler und Light/Dark erhalten. Keine seitenfremden Tabellen-/Dashboardregeln hinzufügen.
- [x] Gezielte Tests für Gruppennavigation, aktive Route, mobilen Zustand und vorhandenen Logout-Fehlerfall. Visuelle Abnahme erfolgt anschließend gemeinsam.

## Paket UI-2 – Dashboard als Arbeitsstart

**Besitzer:** compare_vermieter_astra. Dateien: `Dashboard.jsx`, `DashboardWorkflow.jsx`, `DashboardWorkflow.css`, ggf. scoped `dashboard.css` und gezielte Tests. `dashboardWorkflow.js`-Fachregeln möglichst unverändert; keine Backendänderung.

- [x] Einen klaren Seitenkopf mit sinnvoller Kurzbeschreibung, Datum und vorhandenen Arbeitseinstiegen bilden. „Arbeit“/„Analyse“ als verständliche Ansichten erhalten.
- [x] Dringliche Vorgänge und nächste Aktionen auf der ersten Bildschirmhöhe positionieren. Vier kompakte Bestandsmetriken genügen; restliche Zahlen im passenden Bereich erhalten. Keine erfundenen Finanzsummen oder dekorativen Trends.
- [x] Sieben Einzel-Prozesskacheln und fünf gleichgewichtige Workflowkarten zu einer ruhigeren Prozessübersicht zusammenführen. Die bisherigen Häkchenquoten nicht als reale Bearbeitungsfortschritte eines Monats ausgeben.
- [x] Aufgaben, Vertragsfristen und Hinweise lesbar darstellen; Titel dürfen nicht „meine“ oder „heute fällige“ behaupten, wenn die tatsächliche API-Auswahl dies nicht garantiert. Ziele nur mit tatsächlich unterstützten Routen/Filtern verknüpfen.
- [x] Ladefehler dürfen keine Nullbestände oder „Alles erledigt“ erzeugen. Datenquellen mit Lade-/Fehler-/Wiederholzustand behandeln; Analyseansicht und bestehende Auswertungen erhalten.
- [x] Gezielte Regressionen für echte Inhalte, Fehler/Retry und vorhandene Links. Darstellung bei schmalen Breiten und im dunklen Modus prüfen.

## Paket UI-3 – Listen, Immobilien und Parteien

**Besitzer:** Root. Dateien: `DataTable.jsx`, eigene `DataTable.css`, `Properties.jsx`, `Tenants.jsx`, scoped Listen-CSS und bei geändertem Verhalten gezielte Tests.

- [x] Eine klare Kopfzeile pro Bereich, kompakte Bestandsinformationen und eine erkennbare Hauptaktion. Doppelte Überschriften vermeiden, ohne Tabellenbeschriftung für assistive Technik zu verlieren.
- [x] Suche und Filter logisch gruppieren; Spalten/Export als sekundäre Werkzeuge. Tabellenzeilen mit ruhigen Trennlinien, klarer führender Identität, einheitlicher Zahlenausrichtung und gut erreichbaren Aktenaktionen.
- [x] Immobilien- und Mieterseiten mit denselben Gestaltungsregeln ausstatten; bekannte undefinierte Farbvariablen korrigieren. Vorhandene Info-/Dokumentkarten und Formulare weiterverwenden.
- [x] Sortierung, Filter, Paging, vollständiger Export und Rollen unverändert erhalten. Keine neuen CRUD- oder Finanzabläufe in diesem Paket.

## Gemeinsame Abnahme und Reihenfolge

1. Aktuelle Dokumenten-/Auth-Prüfkette beendet ihre laufenden Prozesse; Paketstand und offene Testbefunde werden festgehalten. Währenddessen nur Design-/Codelektüre, keine Änderungen am getesteten Frontend.
2. Drei UI-Pakete parallel mit obiger eindeutiger Dateizuständigkeit. Neue Verhaltenstests nur für tatsächliche Navigations-/Ladeänderungen; reine CSS-Abstände visuell prüfen.
3. Unabhängiger Review und anschließend eine gemeinsame Frontendprüfkette: Tests, ESLint, Audit und Produktionsbuild. Backend-Runtime bleibt gegenüber dem geprüften Dateizugriffspaket unverändert.
4. Tatsächliche Browserabnahme von Dashboard, Immobilienliste, Parteiakte, Tabelle, Bearbeitungsformular und PDF bei 1440, 1024, 390 und 320 Pixeln sowie Light/Dark. Lesbare Mobilnavigation, Tastatur, volle Aktionsflächen und keine abgeschnittenen Inhalte.
5. Gesicherte Vorschau aktualisieren und das sichtbare Ergebnis zeigen. Weder der UI-Umbau noch die Konkurrenzrecherche gilt als Abschluss aller historischen A–L-Funktionen.
