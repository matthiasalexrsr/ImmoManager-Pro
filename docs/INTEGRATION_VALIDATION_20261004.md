# Tatsächliche Integrationsprüfungen am 4. Oktober 2026

Die Ergebnisse gehören den hier genannten Quellen und Prüfpfaden. Die laufende
Vorschau bleibt Release 126. Diese Teilprüfungen sind keine gemeinsame Freigabe
des gesamten A–L-Plans und aktivieren weder die L2-/M2-Migrationsvorschläge noch
eine externe TEHA-Schreibfunktion.

| Zusammengesetzte Quelle und Umfang | Tatsächliches Ergebnis | Beleg / Grenze |
| --- | --- | --- |
| `57bdaaa`, gemeinsamer Inventarexport | 9 bestanden, 32,43 s | `artifacts/PROPERTY_INVENTORY_SHARED_EXPORT_COMPATIBILITY_20261004.xml`; unabhängige SQLite-Änderung bei Units, Dokumenten und Instandhaltung sowie Memory/SQLite-Berechtigungsentzug und Formeltext. Die neuen Immobilienadapter erhalten zusätzlich eigene Prüfungen. |
| `57bdaaa`, aktueller Inbox-CHECK plus tatsächlicher PostgreSQL-Schreib-/Lesepfad | 3 bestanden, 20,46 s | `artifacts/NOTIFICATION_INBOX_PG_AFTER_GUARD_57bdaaa_20261004.xml`; unabhängige native Verbindungen, erster Lesebeleg pro wirklichem Actor, echte Sperrfrist mit Rollback und Retry, frische Objektzuordnung vor GET-Veröffentlichung. Keine global montierte Bell-/Migrationsfreigabe. |
| `b8432bf`, persönlicher Single-read-HTTP-Pfad | 6 bestanden, 44,35 s | `artifacts/NOTIFICATION_INBOX_SINGLE_READ_HTTP_20261004.xml`; echte SQL-Benutzer und persistente Sids, Readonly-Personalbeleg, Wiederholung, gefälschter Body, Legacy-/widerrufene Anmeldung, enger RBAC-Pfad und vollständig fehlende Familie. |
| `03594dd`, vorhandene Inbox-HTTP-/SQLite-Veröffentlichung | 15 bestanden, 89,90 s | `artifacts/NOTIFICATION_INBOX_PUBLICATION_COMPATIBILITY_20261004.xml`; eingeschränkte Bestände und historische Anmeldung weiterhin gesondert geprüft. Kein PostgreSQL- oder Browsergesamtlauf. |
| `4a97a32`, reine TEHA-Source-/Identitätsprüfung | 18 bestanden, 0,26 s | `artifacts/NOTIFICATION_INBOX_TEHA_IMAGE_SOURCE_PURE_4a97a32_20261004.xml`; der Dateiname besitzt den historischen Wrapperpräfix, der tatsächliche Inhalt ist TEHA. |
| `4a97a32`, ausgewähltes TEHA-SQLite-Bild, explizite Bildschlüssel und Originalbytes | 44 bestanden, 3,92 s | `artifacts/NOTIFICATION_INBOX_TEHA_IMAGE_CRYPTO_4a97a32_20261004.xml`; unveränderte Callertransaktion, tatsächliche AEAD-Chunks und Originalbytes. Der unabhängige Nachreview fand anschließend fehlende native NOT-NULL- und TEMP-Schattierungsprüfungen; diese Ergebnisse gelten deshalb ausdrücklich nicht als vollständige Image-Freigabe. |

Der ausschließlich synthetische PostgreSQL-16.15-Cluster dieser Nachprüfung
lief auf 127.0.0.1:58112 mit eigener Postmaster-ID 6380. Er wurde regulär beendet;
PID-Datei fehlt und der Port besitzt keinen Listener. Es wurde keine laufende
Installation oder reale Fachdatei verändert.

## Noch zu vervollständigen

Die neue Immobilienübersicht wird getrennt in Backend und Frontend umgesetzt.
Ihre echte SQLite-/PostgreSQL-, vollständige Export-, HTTP- und Browserabnahme
folgt auf die zentrale Zusammenführung. Die beiden bisherigen ChatGPT-
Assistenzchats haben ihre Gesprächsgrenze erreicht; ihre konkreten Übergaben
wurden übernommen. Die laufenden Agenten arbeiten mit GPT-6.1 Sol und Sehr Hoch.

Der TEHA-Nachreview wird zuerst mit tatsächlichen negativen Bildern reproduziert.
Die zentrale Katalogabfrage `727195f` überträgt nur die benötigten SQLite-
Familiennamen; sie beschränkt keinen Gesamtbestand. Die weitere Image-Korrektur,
vollständige Befehlsarchivierung, Jobbindung, gemeinsame Recovery und echte
Portalübernahme bleiben getrennte verpflichtende Schritte.
