# Vollständige Handover-Entwicklung – Koordination

Verbindliche Anforderungen: `PRO_COMPLETE_REQUIREMENTS_20261015.md` (unveränderte Kopie der Übergabe). Der Auftrag umfasst alle dort beauftragten Pakete, nicht nur Nachrichten und Verbindungen. Dieses Dokument ist ein Arbeitsauftrag und kein Fertigstellungsnachweis.

## Schutz und Zuständigkeit

Der zentrale Checkout und die laufenden Installationen auf 8000/8765 werden weder verändert noch für Tests verwendet. Alle Entwicklungszweige beginnen mit `pro/`. Separate Entwicklungsarbeitskopien dienen ausschließlich der Arbeit an dieser Anwendung; sie sind keine zweite Fachanwendung oder Finanzdatenbank. Codex' zentraler Integrationszweig bleibt unverändert. Es werden keine Tags, Releases, Live-Migrationen, echten Nachrichten, Käufe, Zahlungs- oder Veröffentlichungsaufträge ausgelöst.

Die vorhandene Python-Prüfumgebung bleibt unverändert. Tests starten mit vollständig eigenen DATA_DIR-, Upload-, Backup-, Keyring-, Datenbank- und Integrationspfaden sowie deaktivierten Schedulern. Neue Abhängigkeiten benötigen eine eigene Umgebung und konsistente Constraints/Lockdateien. Keine Produktivkonfiguration, Benutzerdatei, Token oder Schlüsselmaterial wird kopiert oder veröffentlicht.

## Entwicklung und Prüfungen

Entwicklungshelfer dürfen nur den ihnen zugewiesenen eigenen Checkout ändern. Keine gemeinsame Bearbeitung einer Arbeitskopie, keine Änderung anderer Zweige, keine globale Konfigurationsänderung. Sandbox und Freigabegrenzen bleiben aktiv. Ein verweigerter Werkzeugaufruf wird nicht über einen anderen Weg nachgebildet. Insbesondere ist der frühere Block für `connection_evidence.py` kein Auftrag zur Umgehung.

Ein lokal grüner Pakettest ist weder Gesamtabnahme noch externer Zustell-/Importbeleg. Aufnahmen werden angesehen. Tests erhalten unabhängige fachliche Orakel und prüfen neben Erfolg auch Konflikt, Wiederholung, Rechteentzug, Abbruch/Neustart, Originalschutz und vollständige Seiten. Schwere Gesamtläufe laufen koordiniert, nicht gleichzeitig in jeder Entwicklungsarbeitskopie.

## Migrationskoordination

Gemeinsame Startrevision der begonnenen Verbindungsgrundlage: `d73f2b9a041c`, Vorgänger `c61e9a2f034b`. Jeder getrennte Paketentwicklungszweig erhält eine eigene eindeutige additive Nachfolgerevision. Bereits veröffentlichte Migrationen werden nicht geändert. Nach Übernahme der Paketcommits im eigenen Gesamtentwicklungszweig werden die Köpfe durch eine neue ausdrücklich dokumentierte Merge-Revision zusammengeführt und beide Upgradewege/Bestandsübernahme gemeinsam geprüft. Abhängigkeiten auf fremde Pakettabellen sind vor Übernahme zu koordinieren.

## Verbindliche Arbeitsfelder

1. Verbindungs-/Mapping-/Run-/Receipt-Basis einschließlich Legacy-Autorität, Ergebnisabgleich, verschlüsselter Originalnachweise, Wiederherstellung und großer Historie.
2. CSV/MT940/CAMT/FinTS-Empfang mit Original, Vorschau, bestätigter Buchungsübernahme und Matching.
3. Gemeinsame Forderungsreste, Leistungsperiodenergebnis, Liquiditätsszenarien und gespeicherte Berichte.
4. DATEV und quellgenaue Jahressteuerbasis/WISO-Fachjahr 2026.
5. Allgemeine Outbox/Anhänge/Empfang und Anschluss der bestehenden Mahnakte.
6. TEHA-Empfang und getrennt bestätigte Rückübertragungen.
7. WhatsApp/Post/Immobilienportale und Aktenwerk-Receipt/Hash.
8. Persönliche Benachrichtigungen und wirksame, durchsuchbare Einstellungszentrale.
9. Dokumentwerkzeugmatrix, bearbeitbare Dokumente/Annotationen, Rechnungsoriginal und kontrollierte OCR-Übernahme.
10. Verkauf/Eigentümerwechsel und vollständige Übergabenachweise.
11. Messabdeckung/Bewohnerkorrekturen/Widerspruchsentscheidung, Vertragsfristen und Restmängel.
12. Müll-/ICS-/Ablesepläne und dauerhafte OCR-/Jobbedienung.
13. Mieterportalmandate, begrenzte Offlineerfassung und gezielt erweiterte Historie.
14. S3, Pluginupgrade/API-Fassade, portable vollständige Wiederherstellung und neue Größen-/Mehrbenutzerabnahme.

Alle Teilaufträge werden gegen die vollständigen jeweiligen Handoverabschnitte geprüft; diese Kurzliste ersetzt keine der dort genannten Anforderungen. Externe Voraussetzungen werden einzeln mit dem konkret fehlenden Nachweis festgehalten. Ein fehlender Zugang beendet nicht die übrige Entwicklung.
