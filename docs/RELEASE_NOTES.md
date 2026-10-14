# ImmoManager Pro 2.0.0

Die Hausverwaltung für private Vermieter und kleine Verwaltungen läuft lokal unter Windows (oder als Server). Es gibt keine Cloud, und das Programm versendet nichts von selbst.

**Installieren:** ZIP entpacken und `ImmoManager-Pro.exe` starten. Beim ersten Start führt „Erste Schritte“ durch die Einrichtung. Einzelheiten stehen in der Datei „LIES MICH.txt“ im Paket.

**Aktualisieren:** Die neue Version in einen neuen Ordner entpacken, die alte beenden und die neue starten. Die Daten bleiben im Datenordner (`%LOCALAPPDATA%\ImmoManagerPro`). Vor jeder Änderung an der Datenbank legt das Programm ein geprüftes Vollbackup an.

## Was neu ist

### Einrichten und Übernehmen
- **Erste Schritte** auf der Startseite führen der Reihe nach durch Portfolio, Immobilie, Einheiten, Bankkonto und Mietverträge.
- **Laufende Mietverhältnisse übernehmen:** Für jeden Vertrag lassen sich „Mietkonto hier geführt ab“ und der Saldo zu diesem Tag (Rückstand oder Guthaben) angeben. Ältere Monate gelten dann nicht als offen.
- Formulare enden nicht mehr in einer Sackgasse. Fehlt eine Voraussetzung, nennt das Formular sie und verlinkt dorthin, wo man sie anlegt. Gibt es nur eine Auswahl, ist sie schon gewählt.

### Alles an einem Ort
- **Objektseite:**
  - Einheiten, Mieter & Verträge, Finanzen, Dokumente und Instandhaltung auf einer Seite;
  - Bearbeiten direkt dort;
  - „Neu für dieses Objekt“ öffnet Einheit, Vertrag, Wartungsfall, Buchung, Rechnung oder Aufgabe schon ausgefüllt.
- **Parteiakte je Mieter:** Verträge, Mietverlauf, Konto, Dokumente, Kaution, Übergaben und Wohnungsgeberbestätigung.
- **Verlinkungen überall:**
  - Mietername → Parteiakte;
  - Objekt, Einheit, Wartungsfall, Rechnungsprüfung, Mieterkonto und Mahnfall → ihre Seite;
  - Konto → seine Buchungen;
  - Lieferant → Kontakt.
- **Globale Suche (Strg+K):** findet Datensätze und Seiten und bietet Schnellaktionen wie „Neue Buchung“.

### Mieten und Finanzen
- **Echte Mietzahlungen** mit Konto, Datum und Betrag, dem Vertrag zugeordnet; ältere Rückstände werden zuerst gedeckt. Dazu eine Mietübersicht mit Soll und Ist je Monat.
- **Cent-genaue Finanzen:**
  - Stornos neutralisieren ihre Buchung;
  - alle Berichte haben dieselben Filter (Zeitraum, Portfolio, Objekt, Einheit);
  - Summenzeilen in den Listen.
- **Nebenkostenabrechnung nach Nutzungszeit:** Mieterwechsel und Leerstand tagesgenau; Zähler, Personen und Korrekturen; abgeschlossene Abrechnungen sind unveränderlich.
- **Mahnwesen:**
  - Stufen, Verzugszinsen und Mahnsperren;
  - Briefe als PDF;
  - Antworten den Fällen zuordnen;
  - das Programm versendet nichts selbst.
- **Rechnungsprüfung:** sachlich und rechnerisch prüfen, freigeben (auf Wunsch mit vier Augen), Skonto, Reklamation.
- **Kaution** vom Vereinbaren bis zur Abrechnung beim Auszug.

### Haus und Betrieb
- **Übergabeprotokolle:** Räume, Mängel, Fotos, Schlüssel und Zählerstände; abgeschlossen als unveränderliches PDF.
- **Objektverträge** (Strom, Gas, Wärme, Hausmeister …) mit Tarifen und Fristen. An Fristen erinnert das Programm von selbst.
- **Wartungsfall als Projektakte:** Angebot, Auftrag, Nachträge, Rechnungen und Zahlungen.
- **Wohnungsgeberbestätigung** als PDF mit Original im Archiv.

### Schneller arbeiten
- **Tabellen:**
  - Mehrfachauswahl mit Sammelaktionen und Summen;
  - Suche, Filter und Seite bleiben beim Zurückkehren erhalten;
  - Einstellungen je Liste;
  - CSV für deutsche Tabellenprogramme.
- **Formulare:** „Speichern & weiteren“, „Duplizieren“, „Heute“ neben jedem Datum, Strg+Enter zum Speichern; Eingaben gehen beim Schließen nicht verloren.
- **Tastatur:** „/“ öffnet die Suche, Alt+N das Neu-Formular der Liste, „?“ zeigt alle Kürzel. Favoriten lassen sich in der Seitenleiste anheften.

### Sicherheit, Sicherung, Updates
- **Rollen und Rechte:** Rollen (Verwaltung, Buchhaltung, Technik, Nur Lesen) mit Portfoliozugriff je Konto.
- **Datensicherung:**
  - täglich ein geprüftes Vollbackup mit Datenbank, Anhängen, Einstellungen und Schlüssel;
  - monatlich eine Wiederherstellungsprobe;
  - Zugangsdaten von Schnittstellen werden verschlüsselt gespeichert.
- **Datenbank-Updates** nur ausdrücklich und immer mit Vollbackup davor.
- **Update-Prüfung** unter Einstellungen → System → Updates, nur auf Klick.
- **Aktenwerk (Dokumentenverwaltung):** Exportpaket oder direkte Übergabe von Verträgen, Rechnungen und absetzbaren Belegen mit steuerlicher Einordnung.

## Hinweise zum Update von einer älteren Version
- Beim ersten Start aktualisiert das Programm die Datenbank. Davor legt es ein Vollbackup an; der Speicherort steht im schwarzen Fenster.
- **Bestehende Benutzerkonten** sehen weiterhin alles. Neue Konten sehen erst etwas, wenn der Eigentümer ihnen Portfolios zuweist.
- **Finanzzahlen können sich ändern, und zwar richtig so:**
  - Stornos zählen nicht mehr doppelt;
  - Prognosen rechnen mit den Vertragsmieten;
  - noch nicht abgeschlossene Nebenkostenabrechnungen ergeben bei neuer Erzeugung korrekte Beträge.
  - Abgeschlossene Abrechnungen bleiben unverändert.
- **Laufende Verträge, die vor der Nutzung des Programms begannen:** „Mietkonto hier geführt ab“ und den Saldo nachtragen, sonst gelten alle Monate seit Vertragsbeginn als offen.

## Bekannte Grenzen
- **Versand:** E-Mails und Mahnbriefe erzeugt das Programm als Entwurf oder PDF und versendet sie nicht. Zahlungsdateien (SEPA) gibt es nicht.
- **Vollbackup zurückspielen:** nur über die Kommandozeile (`ImmoManager-Pro.exe ops restore …`), siehe „LIES MICH.txt“.
- **Signaturen:** keine elektronische Unterschrift auf Übergabeprotokollen.
- **Windows-Warnung:** Das Windows-Paket ist nicht signiert. Beim ersten Start meldet Windows das; über „Weitere Informationen → Trotzdem ausführen“ geht es weiter.
