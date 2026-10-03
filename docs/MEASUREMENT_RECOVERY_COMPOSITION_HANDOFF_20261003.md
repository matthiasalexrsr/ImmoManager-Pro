# Historische Quellen: gemeinsame Start- und Wiederherstellungsprüfung

Plan vor Sourceänderung: `MEASUREMENT_RECOVERY_COMPOSITION_PLAN_20261003.md`.
Der neue reine Datenbankprüfer verarbeitet je Einheitenakte sämtliche Befehle,
Quellen, Korrekturen und Originalbezüge. Stammdaten werden ausschließlich in
kleinen relevanten ID-Paketen als minimale Projektionen gelesen. SQLite-Rohbilder
und SQLAlchemy-Verbindungen verwenden dieselben gebundenen Abfragen. Eine
SQL-Fensterprüfung erkennt zusätzlich zeitlich überschneidende physische Zähler
über unterschiedliche Einheiten. Keine globale Python-Gesamtliste oder
Abschneidung. Die größte einzelne Einheitenakte bleibt die bisherige
Speichergröße des reinen Fachprüfers; eine weitere schrittweise Quellenprüfung
bleibt Aufgabe für die gemeinsame Großbestandsabnahme.

Frühe Metadatenregistrierung verhindert nachträglich entstehende Tabellenlücken.
Produktionsstart prüft Migration, Struktur und native Originalschutzregeln ohne
DDL; fehlende oder deaktivierte Schutzregeln werden nicht repariert. Die
ausdrückliche lokale Dev-/Testinstallation erstellt nur eine komplett zuvor
fehlende Familie samt Regeln. Vollständig ältere Bilder ohne diese Familie
bleiben als ältere Bilder lesbar; Teilfamilien werden verweigert.

Vollsicherung, Dateireferenzprüfung und Sicherheitsabschluss prüfen die Quellen
vor Veröffentlichung, Änderung der Sitzungen oder Wiederaufnahme von Jobs.
Fachliche Teilübertragung/Reset erhält keine konkurrierende Teilkopie dieser
Originale: vorhandene Historie verweigert die Operation vor Datenänderung.
Die bestehende vollständige physische Sicherung bewahrt alle vier Tabellen,
Originalschutzregeln und Dokumentoriginale. Datenschutz und gewöhnliche
Elternänderungen werden getrennt vom Domain-Agenten fertiggestellt.

## Tatsächliche Prüfungen

- Native SQLite-/PostgreSQL-Quellen: **11 bestanden**, 280,15 s; kein Skip.
  Enthalten: belegte Korrektur, Roh-SQLite-Proof, beschädigte Hashes vor
  Sicherheits-DML, global widersprüchliche Zählerzuordnung, fehlender/ersetzter/
  deaktivierter Schutz, geschützter Teilreset sowie Legacy-/Teilfamilie.
- Vollsicherung/Wiederherstellung und Produktionsstart: **54 bestanden**,
  zusätzlich **ein Infrastrukturfehler** nach Verlust des separaten
  PostgreSQL-Dienstes beim Agentenwechsel. Der Dienst wurde separat wieder
  gestartet; dieser letzte PostgreSQL-Startfall wird gezielt nachgeprüft.
  Enthalten sind echte verschlüsselte Wiederherstellung mit sieben Quellen,
  drei Befehlen und einem Dokumentbeleg, bytegleiche Originalreihen sowie
  tatsächlich wirksamer Änderungsschutz nach Wiederherstellung. Beschädigte
  Quellen veröffentlichen kein Backup. Die übrige bestehende Vollbackup-
  Suite und der SQLite-Produktionsstart unter tatsächlich verbotenem DDL
  sind in diesen 54 Fällen enthalten.
- Ruff und Mypy des neuen Prüfers und der Schemaprüfung grün.

Nach Wiederanlauf des dedizierten Testdienstes bestanden **9 tatsächliche
PostgreSQL-Fälle ohne Skips**, 100,36 s, im strikten Runner: fünf native
Quellenprüfungen, drei tatsächliche Migrations-/Originalschutzprüfungen und
der zuvor nur durch Dienstausfall fehlgeschlagene Produktionsstart mit
einer Datenbankrolle ohne DDL-Rechte. Damit sind alle 55 Fälle der obigen
Vollbackup-/Startauswahl durch abgeschlossene Läufe belegt. Der initiale
Dienstausfall bleibt im ersten Log sichtbar und wurde nicht ausgeblendet.
Mypy prüft nun auch die vier betroffenen Recoverydienste: sieben Quellen grün.

CI verlangt die tatsächlichen PostgreSQL-Quellen-, HTTP-, Integritäts- und
Migrationsfälle über den strikten Runner ohne Skip-Freigabe. Dies ist weiterhin
eine Fachkomposition, keine Freigabe aller Pakete A–L oder der laufenden Vorschau.
