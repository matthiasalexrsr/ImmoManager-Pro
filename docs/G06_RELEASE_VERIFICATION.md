# Geprüfte Vertragsverlängerung und Kündigung

Lokale gemeinsame Abnahme am 2. Oktober 2026. Grundlage ist der veröffentlichte
und vollständig grüne Stand `82930ad`. CI #125 auf `f3203d5` bestand die 17
neuen echten PostgreSQL-G06-Fälle sowie 64 Verwaltungs- und zwei Owner-/TOTP-
Browserfälle. Dieser Lauf ist insgesamt fehlgeschlagen: SQL meldete bei einer
fehlenden Immobilie 400 statt 404; eine ältere Dokument-PG-Testfixture war nur
bis y1 migriert, obwohl der aktuelle Schreibpfad bereits das z1-Journal liest.
Beide Ursachen sind im folgenden Workspace korrigiert. Die vollständige neue
CI bleibt erforderlich. Terminale Belege: `release125-verification.json`.

## Nutzbarer Ablauf

Unter **Verträge → Ablauf prüfen** einen eigenen Entwurf vorbereiten, speichern
und neu prüfen. Die Vorschau zeigt die gebundenen Vertragsdaten, neue Laufzeit,
Konflikte und weiterhin bestehende Verpflichtungen. Die Bestätigung verlangt
die geprüfte Zustimmung und einen bewussten Bestätigungsdialog.

- Eine Verlängerung legt einen separaten Folgevertrag mit ausdrücklich gewähltem
  Ende oder bewusst unbefristeter Laufzeit an. Zahlungen, Forderungen,
  Kautionsbeträge und Mietmodellangaben werden nicht automatisch kopiert.
- Eine Kündigung erhält das bestätigte inklusive Mietende. Bis dahin bleibt ein
  aktiver Vertrag aktiv; nach diesem Datum ist ein ausdrücklicher manueller
  Abschluss möglich. Der Server verwendet sein UTC-Datum.
- Ein früheres bestätigtes Mietende kann durch einen weiteren geprüften Vorgang
  abgelöst werden. Der alte Bestätigungsbeleg bleibt unverändert; aktueller
  Status und Ablöseverweise werden daneben angezeigt.
- Nach einer verlorenen Bestätigungsantwort lässt sich genau derselbe Befehl
  erneut senden. Der gleiche gespeicherte Beleg wird zurückgegeben; es entsteht
  keine zweite Änderung.

Eigene offene Entwürfe bleiben privat. Bestätigte Belege sind für aktuell
berechtigte Portfolio-Leser verfügbar; Schreibrechte und aktuelle Grants
bestimmen Bestätigung und Abschluss. Die Mieterauskunft enthält akzeptierte
Vorgänge, während private offene Arbeit nur als opaker Aufbewahrungsbezug zählt.

## Tatsächlich ausgeführte gemeinsame Prüfungen

| Umfang | Tatsächliches Ergebnis |
| --- | --- |
| Root: Lifecycle/Anwendungsintegration, komplette Recovery, Mieterauskunft, JSON-Transfer/Reset, Form-Drafts auf SQL | 128 bestanden / 9 ausdrücklich übersprungen |
| Native: Reset-Korrektur mit beiden tatsächlichen Auth-Stores, Lifecycle/CRUD/Import/Recovery | jeweils Memory und SQL: 240 bestanden / 15 ausdrücklich übersprungen |
| Root: verschlüsselte vollständige Recovery nach Entfernung der Quellinstallation, frische Anmeldung, historischer exakter Replay und Financevergleich | 1 bestanden |
| Unabhängiger lesender Core/HTTP/Migrations-/Offlinevalidator-Gate | 68 bestanden / 2 Memory-Varianten ausdrücklich übersprungen |
| Gesamtes Frontend nach Root-Dialogkorrektur | 865 bestanden in 69 Dateien |
| Dialog-/Parent-Refresh-Fokus | 36 bestanden; Parent-Unmount-Regression vor Korrektur tatsächlich fehlgeschlagen |
| Root: frischer echter SQLite-Server und Edge, G06 + Auth-Sitzungen + Kalender + Dokumentversionen | 7 bestanden |
| Root: echte SQLite-/Edge-Wizard-Sicherheit, Validierung, persistente Freigabe und manuelle Signatur | 3 bestanden |
| Native: alle sechs Wizard-Payload-/Validation-/Workflow-/Schema-/PG-Dateien auf endgültiger Eingabekorrektur | jeweils Memory und SQL: 118 bestanden / 6 ausdrücklich übersprungen |
| Root: vollständige Wizard-Validation-/HTTP-Regressionsdatei auf endgültiger Eingabekorrektur | 57 bestanden, kein Skip |
| CI-Mypy 2.4.0 auf allen 119 registrierten kritischen Quellen | Linux Python 3.11 und Windows Python 3.12 bestanden |
| Ruff, ESLint, Produktionsbuild und JavaScript-Syntaxprüfung | bestanden |

Die beiden G06-Browserfälle überprüfen tatsächlich angenommene Serverbefehle,
Antwortverlust und identisches Retry-Payload, Finanz-DTOvergleich, aktuelle
Ablöseverweise bei unveränderlichem alten Resultat, zu frühen Abschluss mit
HTTP 409, echte scoped Readonly-Anmeldung und verborgene private Gründe.
320/360px prüfen reale DOM-Geometrie; Escape und Fokus zum erneuerten
Vertragsbutton werden im Browser geprüft. Ein erfolgreicher Abschluss nach
Mietende wird durch Core-/HTTP-/Recovery-Fälle belegt; der Browserfall stellt
seine zukünftige Kündigung nicht künstlich als bereits abgeschlossen dar.

Ein erster gemeinsamer Browserlauf fand den neuen Vertrag auf der zweiten
Tabellenseite; der Test nutzt seitdem die sichtbare Suche. Die nächste Prüfung
fand einen echten Produktfehler: Parent-Listenrefresh unmountete den offenen
Workflow und verlor seine Auswahl. Der korrigierte Parent erhält den Dialog
während dieses Refreshs; ein eigenständiger Regressionstest belegte rot→grün.

Der zusätzliche Wizard-Review reproduzierte stilles Runden von `850,001` beim
Blur und einen tatsächlichen HTTP-500 bei 5.000-ziffriger Staffelmonat-Angabe.
Die Korrektur erhält Subcent-Rohwerte zur sichtbaren Berichtigung und formatiert
gültige deutsche Centbeträge ohne Float-Rundung, auch jenseits der JavaScript-
Safe-Integer-Größe. Der tatsächliche Python-Konvertierungsfehler wird als
korrigierbare HTTP 422 gemeldet; keine neue fachliche Monatsobergrenze wird
eingeführt, 100-stellige positive Monatsangaben bleiben ausdrücklich erlaubt.
Der Ausgangsindex wird zusätzlich serverseitig als endlich und positiv geprüft.
Die drei abschließenden echten Wizard-Browserfälle enthalten Blur vor Weiter,
eine geklonte Staffelzeile und den exakten großen Betragswert. Alle bestanden.

Die vollständige Alembic-Kette ergänzt das Journalpaar in `z1a2b3c4d5e6`.
Gewöhnliche Vertrags-/Referenz-/Mietforderungsschreibwege, Reset und partielle
JSON-Imports beachten akzeptierte Belege und aktuelle Konflikte. Vollständige
Recovery erhält die Journale; ihr Validator prüft sie vor Sitzungsentzug oder
Zielveröffentlichung. Beide fehlenden Tabellen gelten nur im echten Altformat
als Legacy; ein halbes Paar oder beschädigte Belege werden mit einem
nachvollziehbaren Korrekturweg abgewiesen. Es gibt keine behauptete Heilung
fehlender Originale durch erfundene Dateien.

## Weiter offen

Die 17 neuen PostgreSQL-G06-Fälle bestanden tatsächlich in CI #125. Dessen
vollständige Gesamtfreigabe fehlt; lokale Skips sind weiterhin kein Nachweis
für zusätzliche PostgreSQL-Fälle. Der nächste veröffentlichte Commit benötigt
seine vollständige gemeinsame CI.

G06.2-Fristenautomation, Vorlagendokumente und Versandverfolgung bleiben offen.
Die Vertragsübersicht und begrenzte Formular-Lookups sind inzwischen gemeinsam
integriert; die Abnahme steht in `CONTRACT_WORKSPACE_VERIFICATION.md`.
Dieser Stand behauptet weder vollständige
Rechtswirksamkeit/automatischen Versand noch den Abschluss des historischen
Funktionsinventars. WISO Steuer für Windows ist hier nicht installiert; ein
echter Verbraucherimport bleibt extern zu prüfen.
