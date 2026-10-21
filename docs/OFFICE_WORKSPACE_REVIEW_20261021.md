# Arbeitszentrale, Benachrichtigungen, Kommunikation und Einstellungen

Prüfrunde vom 21. Oktober 2026. Ausgangspunkt ist der freigegebene Integrationsstand
`56b9d7c8090f35f04a4b1bd0d4d926455816c6b7`. Claudes zuletzt abgerufener Stand
`ebcd434840b19f9ab7a940eaea02c5a8d40bdacc` ist darin enthalten. Seine Gestaltung,
Dokumentwerkzeuge und bisherigen Fachabläufe bleiben die Grundlage. Diese Runde
ändert weder den Mergezustand seiner PR #37 noch veröffentlicht sie ein Release-Tag.

## Nachgewiesene Fehler und Korrekturen

| Bereich | Gegenbeispiel | Korrektur |
| --- | --- | --- |
| Kommunikation | Nach Öffnen von `messages?focus_id=A` springt die Auswahl von B zurück zu A. | Benutzerwechsel aktualisieren den Link; Verlauf und Browser-Zurück öffnen die passende Konversation. |
| Konversationsbezug | Nicht vorhandene Kontakte und widersprüchliche Immobilien-, Einheiten- oder Vertragsbezüge lassen sich speichern. | Gemeinsame Schreibprüfung für Anlage, vollständige Änderung und PATCH in beiden Speicherarten. Unveränderte historische Bezüge bleiben lesbar und werden bei fremden Feldänderungen nicht umgedeutet. |
| Nachrichtenhistorie | Vollständiges Umbenennen im Speichermodus setzt Nachrichtenzähler und letztes Nachrichtendatum zurück. | Vollständige Änderung erhält vorhandene Metadaten und Nachrichten. |
| E-Mail-Liste | Fehler beim Laden der nächsten Seite entfernt zuvor geladene Nachrichten. | Geladene Zeilen, Auswahl und Cursor bleiben erhalten; Wiederholung lädt dieselbe Folgeseite. |
| Unbestätigte Speicherung | Erfolgreiches Aktualisieren der E-Mail-Liste entfernt den Fehler samt Abgleichaktion einer unbestätigten Speicherung. | Schreibfehler, Listenfehler und Fehler der Auswahldaten werden getrennt geführt. Der ursprüngliche Befehl bleibt abgleichbar. |
| Glocke | Auf der Archivseite übernimmt die kompakte Vorschau den Archivfilter. | Die Vorschau lädt immer den ungelesenen persönlichen Eingang und schließt nach Navigation. |
| Hinweisquelle | Nach Änderung einer Quelle scheitert jede Wiederholung der alten Lesebestätigung erneut mit 409. | Konflikte bieten das erneute Laden der Quelle; erst die neu angezeigte Fassung wird bestätigt. Ein verlorener Antwortnachweis verwendet weiterhin denselben Befehl. |
| Einstellungen | Nach 409 fehlt der aktuelle Wert; der Benutzer kann seine Eingabe nicht gezielt mit dem neuen Stand speichern. | Aktuelle Werte nachladen, eigene Eingabe behalten, Vergleich ausdrücklich übernehmen und neue Revision auch im privaten Entwurf sichern. |
| Einstellungen und Eingang | Filter und Einstellungsreiter stimmen nach Browser-Zurück nicht mit der URL überein; ein ungültiger Reiter erzeugt eine leere Seite. | Die URL bestimmt Filter und Reiter; ungültige oder nicht erlaubte Reiter zeigen den Einstellungskatalog. Neue Filter besitzen eigene Seitencursor und Schnappschüsse. |

## Bedienung und Verlinkung

- Arbeitszentrale: Fälligkeit und Zuständigkeit direkt bearbeiten, einschließlich bestehender
  Konfliktprüfung und dauerhaftem Rückgängig. Fehlende Immobilienauswahl hat eine eigene Fehleranzeige und Wiederholung.
- Kommunikation: Links zu Immobilie, Einheit, Mietvertrag und Teilnehmerkontakten;
  Kontaktanzeigen verwenden die tatsächlich gespeicherten Namens- und Firmenfelder.
  Der Wechsel in die E-Mail-Ansicht übernimmt den aktuellen Konversationsbezug.
- E-Mail-Listen zeigen laufendes Nachladen, verhindern doppelte Folgeseiten und behalten
  bestätigte Daten bei vorübergehenden Fehlern. Eine unvollständige Listenantwort gilt als Fehler.
- Einstellungen: Themen- und Geltungsbereichsfilter sowie das gezielte Nachladen aktueller
  Werte. Private Eingaben bleiben beim Filtern erhalten.
- Eindeutige Beschriftung der Auswahlfelder für Tastatur- und Hilfsmittelbedienung.

## Reproduzierbare Abnahme

Die neuen Gegenbeispiele stehen in `test_communication_records.py`,
`MessagesBoundary.test.jsx`, `CommunicationCenter.test.jsx`,
`NotificationBellQol.test.jsx`, `NotificationLanding.test.jsx` und
`SettingsCatalogue.test.jsx`. Die neue Konversationsprüfung gehört auch zum verpflichtenden
PostgreSQL-Nachweis in `test_message_postgres.py`; übersprungene Fälle sind dort nicht zulässig.

`scripts/run_daily_browser_qa.py --suite office` startet ausschließlich einen eigenen
Testserver mit synthetischen Daten. Neun Prüfabläufe decken Schnelländerung/Rückgängig,
Wiedervorlagen, tatsächliches Öffnen und Archivieren, Filter und Browser-Zurück,
einen echten Einstellungskonflikt, private Gesprächsentwürfe und die E-Mail-Vorschau ab.
Zusätzlich werden acht Ansichten bei 320, 360 und 1440 Pixeln geprüft. Externe Browseranfragen
werden blockiert; der E-Mail-Nachweis endet bei einer unversandten Vorschau.
Die Suite ist Teil der gemeinsamen CI und lässt sich gegen das gebaute Windows-Paket ausführen.

Zur Auslieferung gehören weiterhin der vollständige CI-Nachweis für genau den Commit,
Prüfungen des gepackten Programms, eine neue Vollsicherung, tatsächliche Wiederherstellung
mit dem Windows-Programm und ein expliziter Schema-Upgrade-Schritt. Diese Runde benötigt
keine neue Datenbankmigration. Der abschließende Nachweis wird getrennt unter
`C:/Users/matth/Documents/ImmoManager-Sicherungen/20261021-Kommunikation-Arbeitszentrale`
mit Commit, Paketprüfsumme, Sicherungen und Ergebnissen gespeichert.

Die Bestandsprüfung ergänzt sechs Kontrollen für Konversationsbezüge und Nachrichtenzähler.
Bereits bekannte manuelle Bezahlt-/Teilbezahlt-Kennzeichen ohne verknüpften Zahlungsbeleg
werden weiterhin als unklar behandelt; diese Runde erzeugt dafür keine fiktiven Zahlungen.
WISO-/TEHA-Auslieferungen und echte E-Mail-Zustellung sind nicht Gegenstand dieser Prüfrunde.
