# ImmoManager Pro – aktueller Entwicklungsstand

Stand: 2. Oktober 2026. Ausgangspunkt: `c64b2f1` auf
`claude/redesign-frontend-ui-RUPYS`, einschließlich PR #32.
Die Fortsetzung wird in PR #33 auf `codex/continue-rental-workflows` gesichert.

## Projekt und Ziel

Das aktive Repository ist `matthiasalexrsr/ImmoManager-Pro`. Die gefundenen lokalen
Archivkopien unter `C:\02_Projekte_Archiv\ImmoManager`, `Git-Repositories` und
`Immobilienverwaltung` enthalten ältere Stände und wurden nicht verändert.
Entwickelt wird eine lokale Verwaltung für private Vermieter mit Bestand,
Vermietung, Finanzen, Nebenkosten, Instandhaltung, Dokumenten und Berichten.

FastAPI, React, SQLAlchemy, Alembic, die Stammdatenmasken und fachlichen Engines
waren bereits vorhanden. Die beiden bestehenden ChatGPT-Chats
„Software verbessern und fertigstellen“ und „Software verbessern“ wurden für
Import/Recovery sowie Finanz-/Abrechnungsoberfläche und Browserprüfungen eingebunden.

## Umgesetzte Fortsetzung

| Bereich | Verhalten |
|---|---|
| Monatsforderungen | Vorschau aus aktiven Verträgen, gespeicherte Preise, atomare Erstellung, genau ein Datensatz je Vertrag/Monat; große Serien als gespeicherte, ausdrücklich freigegebene Läufe mit Pause und Wiederaufnahme |
| Zahlungen | Dauerhafte Belege, Centprüfung, Teilzahlungen, unveränderbarer Zahlungsstand bei normalen Formularänderungen |
| Bankzuordnung | Gemeinsames verfügbares Buchungsbudget, Herkunftsprüfung, atomare Zuordnung und keine doppelte Bankzählung |
| Storno | Datierter Gegenbeleg mit Grund; Original bleibt erhalten, Saldo und Bankbudget werden wiederhergestellt |
| Offene Posten/Berichte | Monatsforderungen und sonstige Forderungen gemeinsam; historische Beleg-/Stornodatierung für Vertragskonto und Mahnlauf |
| Nebenkosten | Tatsächlich bezahlte Vorschüsse mit Receipt-IDs, gespeicherte Finalisierung, korrekte PDF-Revisionen und Korrekturdifferenzen |
| Guthaben/Leerstand | Verfügbare Guthaben getrennt von Forderungen; gespeicherter Eigentümeranteil, erhaltene Gesamtkosten, blockierende Vorprüfung bei fehlender Datenbasis |
| Finanzoberfläche | Vollständige Pagination, sichtbare Fehler/Retry, abgesicherte Formularwerte, Readonly-Aktionen und neue Texte in Deutsch/Englisch/Spanisch |
| Zugang | Einmalige lokale Eigentümeranlage, dauerhaft geschlossene öffentliche Registrierung, genehmigte Benutzer und vollständiger TOTP-Ablauf; atomare Refresh-Abstimmung zwischen Tabs, aktuelle Sitzungsprüfung und entfernte private Ansichten bei Benutzerwechsel |
| Portfoliozugriff | Ausdrückliche All-/Auswahlzuordnung durch Eigentümer, aktuelle serverseitige Prüfung auch bei alten Tokens, geschützte Referenzen und Dateien |
| DATEV | Geprüfte unveränderliche Kontenzuordnungen, vollständige Vorschau, reproduzierbare Dateien mit Quellenreferenzen; keine Übermittlung oder Importzertifizierung |
| Dokumente/Fotos | Authentifizierte Downloads und Blob-Vorschauen, sichere Dateitypen und SPA-Pfade, korrektes konfiguriertes Upload-Verzeichnis |
| Dokumenthistorie | Ausdrücklich geprüftes Original, unveränderliche Upload-/Restore-Versionen mit SHA256 und Originalbytes; historische Mieterzuordnung, vollständige Wiederherstellung und geschützte Downloads |
| Kalenderexport | Expliziter Portfolio-ICS-Download aus konsistentem, gebatchtem Snapshot; stabile IDs, Zeitzonen und reine Leserechte; aktuelle Quell-/Berechtigungsprüfung auch während der Ausgabe |
| JSON-Transfer | Vollständige Vorbereitung und eine atomare Veröffentlichung des unterstützten Geschäftsdaten-Teilsatzes; Benutzer/Installationsmarker bleiben erhalten |
| Vollständige Recovery | Passwortverschlüsseltes Offline-Archiv aller SQLite-Tabellen, lokalen Uploads, Konten/2FA, Schlüsseln und Konfiguration; geprüfter Neustart in neuem Ordner |
| Windows-Betrieb | Quellen-/Konfigurationsfingerprint, geprüfter Build, Offline-Neustart bei unverändertem Build, Erhalt vorheriger Oberfläche bei Fehlern |
| Windows-OCR | Ausdrückliches privates Setup aus festgelegten SHA256-geprüften Paketen, vollständige Lizenz-/Herkunftsnachweise, echte PNG-/Raster-PDF-Prüfung und Unicode-Werkzeugziele; keine Installation aus Dokumentanfragen |
| Updates/Scheduler | Wartung bei gestoppter Anwendung; konsistente Datenbank-Snapshots, begrenzte Laufzeit, exklusive Veröffentlichung, echte Fehlerstatus |
| Lokale Plugins | Geprüfte Initialisierung/Beendigung, geschützte HTTP-/WebSocket-Routen, sichtbarer Betriebsstatus |
| Stabilität/Sicherheit | Anfragenbezogene Datenbank-Sessions einschließlich Streams, erweitertes Typechecking, PyJWT statt python-jose/ecdsa |

SQLite erhält additive Schema-Ergänzungen; Alembic enthält eine eindeutige Kette
bis `y1a2b3c4d5e6`. Mehrdeutige alte Finanzdaten und Downgrades mit bestehenden
Abrechnungsnachweisen werden vor zerstörenden Änderungen abgewiesen.

## Fachliche Regeln und Umfang

Die Monatsvorschau verwendet derzeit volle vereinbarte Monatsbeträge, auch bei
Teilmonaten. Diese sind ausdrücklich erkennbar. Noch nicht gebuchte ältere Monate
verwenden aktuelle Einheitenbeträge und benötigen Prüfung vor Bestätigung.
Bereits gebuchte Monatsforderungen sind die Grundlage historischer Auswertungen;
noch nicht gebuchte Monate erscheinen getrennt als Vorschau.

Einzelabrechnungen berücksichtigen belegte Zahlungen anteilig über ihre
Mietbestandteile. Undatierte übernommene Altzahlungen und Belege außerhalb des
Stichtags sind ausdrücklich ausgewiesen. Finalisierte Werte bleiben erhalten;
Korrekturen erzeugen eine neue Revision und buchen die Differenz zur bisherigen
Kette. Guthaben werden als verfügbar geführt. Eine Auszahlung wird dadurch nicht
behauptet. Eigentümeranteile erzeugen keine Mieterforderung.

Diese Version dient einer privaten Installation. Genehmigte Benutzer erhalten
ausdrücklich zugewiesene Portfoliozugriffe; Rollen bestimmen zusätzlich die
zulässigen Handlungen. Siehe [Zugangsmodell](docs/ACCESS_MODEL.md).

WISO Steuer für Windows ist der gewünschte Steuerimport. Das offizielle
Hausverwalter-Handbuch beschreibt einen XML-Export; dessen reale Dateistruktur
und Importannahme werden mit der installierten Testversion untersucht. DATEV-
oder allgemeine CSV-Dateien werden nicht als verifizierter WISO-Import ausgegeben.

JSON ist ein Teilsatztransfer und enthält keine Upload-Bytes, Benutzer oder
komplette Abrechnung. Die vollständige lokale Recovery läuft offline und benötigt
einen neuen Zielordner. Externe HTTP-/S3-Dateien und Plugin-Binaries sind separat
zu erhalten. Gemischte alte Upload-Speicherorte verursachen einen Fehler, wenn
Dateiverweise nicht vollständig gedeckt sind. Siehe [Recovery](docs/RECOVERY.md)
und [private Dateien](docs/PRIVATE_FILES.md).

## Abnahme und Dokumentation

Die finale Evidenz mit Gesamtzahlen, Coverage, Browserabläufen und Grenzen steht
in [LOCAL_RELEASE.md](docs/LOCAL_RELEASE.md). CI verlangt Backendtests mit Memory
und SQL auf Python 3.11/3.12, Ruff, Typechecking der kritischen Dienste, Pip-Audit,
Frontendtests/-Build/-Audit, Browserabläufe auf SQLite sowie Compose-Smoke.

Historische Pläne und einzelne Übergaben beschreiben ihre jeweilige Basis.
Dieser Entwicklungsstand, die Release-Evidenz und die aktuellen Laufzeitanleitungen
sind für den vereinten Stand maßgeblich. Die ausführbaren Befehle stehen in README.md.

## Externe Voraussetzungen und spätere Erweiterungen

WhatsApp, Postversand und externe Immobilienportale sind ausdrücklich als geplant
gekennzeichnet. Ein gespeicherter Schlüssel gilt nicht als betriebsbereite
Integration; Anbieterimplementierung und echte Zugangsdaten müssen folgen.
Die lokalen Tests versenden keine Nachrichten und veröffentlichen keine Inserate.

Produktive PostgreSQL-Installationen, separate Mandanten, Rückzahlungsabgleich,
externe Dienstanbieter und zusätzliche optionale KI-Modelle benötigen eine eigene
Einrichtung und Abnahme. Die vorhandenen Adapter bleiben dafür der Anschluss.
