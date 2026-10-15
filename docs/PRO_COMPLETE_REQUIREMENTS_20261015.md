# ImmoManager Pro Programmierübergabe an ChatGPT PRO

Stand 15. Oktober 2026. Empfänger ist ein ChatGPT-PRO-Chat mit dem Plugin Remote Desktop Commander. Auftraggeber ist Matthias. Du entwickelst die offenen Funktionen vollständig und prüfst sie lokal; Codex übernimmt anschließend die unabhängige Prüfung, Zusammenführung und Auslieferung in die Hauptanwendung.

## Auftrag und Arbeitsweise

Entwickle die unten beschriebenen Pakete autonom bis zu ihren Abnahmekriterien. Arbeite an echten Implementierungen mit verwendbarer Oberfläche, Datenhaltung, Migrationen, Fehlerbehandlung und Tests. Eine Schaltfläche, ein Stub, ein neutraler CSV-Export oder simulierte Antworten allein schließen eine externe Schnittstelle nicht ab. Bei einem externen Hindernis dokumentierst du genau den fehlenden Nachweis und arbeitest an allen unabhängigen Paketen weiter.

Der Benutzer erlaubt grundlegende Überarbeitung, Vereinfachung, neue Funktionen und die Verwendung geeigneter Open-Source-Bausteine. Bestehende Daten, veröffentlichte Originale und die laufende Anwendung müssen dabei erhalten bleiben. Entwicklung und Integration sind ausdrücklich getrennt: Ändere weder den zentralen Integrationszweig noch die beiden laufenden Installationen. Lege einen eigenen Entwicklungszweig mit einem eigenen Arbeitsverzeichnis an und liefere nachvollziehbare Commits an Codex. Kein Zwischenpaket wird von dir auf die Anwenderdaten migriert oder in die Hauptanwendung ausgerollt.

Das Produkt ist eine professionelle, privat betriebene Immobilienverwaltung für mehrere Benutzer, lokalen Server und gesicherten Fernzugriff. Ziel sind große Bestände und 20 Jahre nachvollziehbare Historie bei überschaubarer Wartung. Keine stillen Abschneidungen, künstlichen Gesamtbestandsgrenzen, verschluckten Fehler oder nicht wiederaufnehmbaren Großvorgänge. Grenzen eines einzelnen Arbeitsschrittes sind erlaubt und nötig, wenn Folgecursor, gespeicherter Fortschritt oder ein fortsetzbarer Hintergrundauftrag alle Daten erreichbar halten.

## Zugriff auf den richtigen Rechner und Quellstand

Remote Desktop Commander wurde für das Konto geprüft. Das Gerät `DESKTOP-O008GV9` war online, Geräte-ID `22166494-d25d-4097-b6cf-e93b2ddfacd9`. Rufe zu Beginn erneut `list_devices` auf und bestätige das Gerät; eine alte Onlineanzeige ist kein Verbindungsnachweis für deine Sitzung.

Die wichtigsten Desktop-Commander-Werkzeuge sind `list_directory`, `read_file`, `start_process` und `read_process_output`. Verwende absolute Windows-Pfade und PowerShell-Syntax. `start_process` wartet auf dem entfernten Rechner höchstens ungefähr drei Sekunden und kann eine laufende Sitzung zurückgeben. Lies deren Ausgabe weiter, statt denselben Befehl erneut zu starten. Verwende für Textsuche `rg` und für Dateiinventare `rg --files`. Drucke keine Zugangsdaten, Tokens, Schlüssel oder vollständigen privaten Konfigurationsdateien in den Chat.

| Gegenstand | Verbindlicher Ort beziehungsweise Stand |
| --- | --- |
| Diese Übergabe | `C:\Users\matth\Documents\Codex\2026-10-01\wi\outputs\CHATGPT_PRO_HANDOVER_20261015.md` |
| Zentraler geprüfter Checkout | `C:\Users\matth\Documents\Codex\2026-10-01\wi\work\claude-review-20261013` |
| Integrationszweig | `codex/claude-review-20261013` |
| GitHub | `https://github.com/matthiasalexrsr/ImmoManager-Pro.git` |
| Ausgang der fachlich geprüften QoL-Fassung | `ec6b62689d5e6b2788cf279f1ab6365dc69216a4` |
| Aktuelle Programmierbasis einschließlich Windows-Protokollkorrektur und stabiler Dialogprüfung | `04021da57e009419ae8d07346ad890fdabad6533` |
| Aktueller Alembic-Head | `b82d5fa03147` |
| Python 3.12 für Prüfungen | `C:\Users\matth\Documents\Codex\2026-10-01\wi\work\review-venv-20261013\Scripts\python.exe` |
| Native PostgreSQL-Prüfumgebung | `work\review-postgres-20261013` im übergeordneten Arbeitsbereich; vor Verwendung Prozess, Port und Testdatenbank neu prüfen |
| Playwright-Modul | `<zentraler Checkout>\artifacts\tooling\browser-20261013\playwright-local.mjs` |

Beginne lesend mit `git status --short`, `git log -5 --oneline`, `git branch --show-current` und `git worktree list`. Existieren danach neuere Änderungen von Codex oder Claude, inventarisiere sie und arbeite vom tatsächlich neuesten abgestimmten Stand aus. Ältere Verzeichnisse mit Namen wie `outputs\ImmoManager-Pro`, `root-correspondence-integration` oder `party-document-workspace` sind keine alternative aktuelle Basis. Einzelne Altmodule dürfen gezielt wiederverwendet werden, nachdem ihre Daten-, Rechte- und Migrationsverträge verglichen wurden.

Beispiel für eine eigene Arbeitskopie, nach dieser Zustandsprüfung:

```powershell
Set-Location -LiteralPath 'C:\Users\matth\Documents\Codex\2026-10-01\wi\work\claude-review-20261013'
git worktree add -b pro/interfaces-20261015 'C:\Users\matth\Documents\Codex\2026-10-01\wi\work\pro-interfaces-20261015' 04021da57e009419ae8d07346ad890fdabad6533
```

Existiert Zweig oder Verzeichnis bereits, prüfe dessen Status und setze ihn kontrolliert fort; verwende keinen Reset und kein erzwungenes Überschreiben. Lege weder eine neue unabhängige App noch eine zweite konkurrierende Finanzdatenbasis an.

## Laufende Installationen und Sicherungen

Die beiden vorhandenen Datenbestände wurden getrennt vollständig gesichert, auf getrennte Kopien wiederhergestellt und explizit auf `b82d5fa03147` migriert. Beide Migrationsvergleiche erhielten sämtliche Zeilen und ursprünglichen Feldwerte in 47 vorhandenen Tabellen. Alle 234 Uploaddateien der Hauptvorschau und 92 Uploaddateien der Desktop-Testversion blieben bytegleich.

| Installation | Daten und Zugriff |
| --- | --- |
| Bisherige Hauptvorschau | `http://127.0.0.1:8765/`; Daten: `C:\Users\matth\Documents\Codex\2026-10-01\wi\work\party-workspace-preview-20261007` |
| Desktop-Testversion | `http://127.0.0.1:8000/`; Daten: `C:\Users\matth\AppData\Local\ImmoManagerPro-Testversion`; Programm: `C:\Users\matth\OneDrive\Desktop\ImmoManager-Pro` |
| Dauerhafte native Programmfassungen | `C:\Users\matth\AppData\Local\Programs\ImmoManagerPro\releases` |
| Hauptvorschau erneut starten | Desktop-Verknüpfung `ImmoManager - Hauptvorschau.lnk`; zuerst prüfen, ob Port 8765 bereits läuft |
| Vollständige Sicherung vor der Umstellung | `C:\Users\matth\Documents\ImmoManager-Sicherungen\20261015-QoL\vollstaendige-installation-vor-update.zip` plus `.sha256` |
| Ursprüngliches Desktop-Programm | Im selben Sicherungsverzeichnis unter `desktop-program-original` und zusätzlich im Vollarchiv |
| Frühere Hauptvorschau einschließlich Quellarchiv und damaligem Frontend | `hauptvorschau-programm-vor-update.zip` plus `.sha256` im selben Sicherungsverzeichnis |
| Betriebs-, Migrations- und Installationsnachweise | Sicherungsverzeichnis: `before.json`, `*-backup-restore.json`, `*-upgrade-live-preservation.json`, `installed-program-manifest.json`, Prozess- und Abschlussberichte |

Das ursprüngliche Vollarchiv enthält 596 geprüfte Dateien einschließlich unveränderter Runtimekonfiguration, SQLite-Dateien samt WAL/SHM, konsistenter zusätzlicher Datenbankkopien, Dokumenten, früheren Backups und Desktop-Programm. Der Ordner ist mit eingeschränkten Windows-Dateirechten geschützt und enthält Geheimnisse. Er gehört nicht nach GitHub und wird nicht an externe Dienste übertragen.

Für den tatsächlichen laufenden Build und die Prozessidentität sind die aktuellen `*-process.json` sowie der Abschlussbericht im Sicherungsverzeichnis maßgeblich. PIDs sind Momentaufnahmen. Beende niemals Prozesse nur nach Namen wie `python`, `node` oder `ImmoManager-Pro`; auf diesem Rechner laufen andere Projekte.

Die vorstehenden Browseradressen dienen dem Anwender. Benutze für Entwicklung ausschließlich eigene Datenverzeichnisse, eigene Datenbanken und freie andere Ports. Die Anwendung besitzt bereits einen synthetischen Testdatengenerator. Prüfe zunächst, welches Konto und welcher Bestand tatsächlich vorliegen. Test- und Masterpasswörter werden in dieser Übergabe absichtlich nicht wiederholt; Testkonstanten stehen in `backend/testversion/dataset.py` beziehungsweise `tools/xstress/core.py`. Externe Zugangsdaten gehören in die vorhandene verschlüsselte Geheimnisablage.

## Bereits vorhandene Funktionen erhalten

Die ursprüngliche Anforderungsliste A bis L ist historisch. Viele damalige Lücken sind inzwischen geschlossen. Prüfe den heutigen Code und seine Regressionen, bevor du etwas neu entwickelst.

- FastAPI, React/Vite, SQLAlchemy, SQLite für lokale Installationen und PostgreSQL als Ziel des Mehrbenutzerservers; persistente Anmeldung, Rollen, Portfolio-/Objektrechte und TOTP.
- Immobilien-, Einheiten- und Parteiakten mit verknüpften Verträgen, Mietkonten, Dokumenten, Schäden und Aufgaben. Namen öffnen eine Parteiakte; Originaldateien werden authentifiziert angezeigt.
- Mietzahlungen, datierte Übernahmesalden und Rückzahlungen, Forderungen, Teilzahlungen, Bankbuchungszuordnung, Guthaben, Stornos und dezimalgenaue Berichte mit Quellbezügen.
- Verbrauchsabrechnung mit Medium/Maßeinheit, historischen Zählerwechseln, datierten Bewohnern, Zeitabschnitten und unveränderlichen finalisierten Fassungen. Wohnungsgeberbestätigung und veröffentlichte Übergabeprotokolle sind integriert.
- Objekt-/Energieverträge mit Tarifen, Fristen, Rechnungen und Zahlungen; Schaden-/Projektakten, Angebote, Aufträge, Nachträge, Protokolle; Kautions- und Mahnabläufe sowie Rechnungsprüfung.
- Dauerhafte Jobs, Leasing und Wiederanlauf; explizite Migration mit vorheriger Vollsicherung; automatische tägliche Vollbackups und monatliche isolierte Wiederherstellungsproben; Schlüsselring und verschlüsselte Integrationskonfiguration.
- Sämtliche angeforderten QoL-Grundlagen sind integriert: private Entwürfe und Absturzpuffer, mehrere benannte Ansichten, zuletzt geöffnete und angeheftete Akten, Arbeitszentrale und begründete Wiedervorlagen, gemeinsame Chronik, Kennzahlquellen, Schnelländerungen mit Konfliktprüfung, Gespräch plus Wiedervorlage, Rückgängig für zulässige Aktionen, Dokumenteneingang mit Vorschau/Weiterbearbeitung, Kontexterhalt und Dublettenprüfung.
- Konto- und Rechtewechsel zwischen Tabs, späte Antworten, Datei-Uploads/-Downloads, Refresh und Logout sind gemeinsam abgesichert. Verwende den vorhandenen API-Client und `captureSession`; direkte neue `fetch`-Wege dürfen diese Grenzen nicht umgehen.

`docs/QOL_WORKSPACE_20261015.md` beschreibt die aktuellen QoL-Verträge. `docs/CLAUDE_REVIEW_20261015_VALIDATION.md` enthält ältere Prüfungsetappen und Leistungslücken; der dort noch stehende Abschnitt „Nächste QoL-Ausbaustufe“ wurde durch die spätere QoL-Implementierung überholt. Alte Statusangaben in `CODEBASE_AUDIT_TODO.md`, `CLAUDE_HANDOFF_20261007.md` und historischen Paketen sind keine neue Fehlerbestätigung.

## Gemeinsame Entwicklungsverträge

1. **Berechtigung:** Jede direkte und indirekte Quelle, Suche, Summe, Datei, Vorschau und Speicherung prüft die aktuellen Rechte. Rechteentzug unmittelbar vor Commit, Benutzerwechsel und spätere Antworten gehören zu den Tests. Ein interner Leser ist kein Mieterportalbenutzer.
2. **Mehrbenutzerzugriff:** Schreibbefehle verwenden erwartete Revision und Wiederholungsschlüssel. Gleiches Kommando nach verlorener Erfolgsantwort erzeugt genau ein Ergebnis. Veraltete Quelle und abweichender Befehl mit altem Schlüssel erzeugen einen bearbeitbaren Konflikt.
3. **Originale:** Bestätigte Dokumentbytes, veröffentlichte Protokolle und finale Abrechnungsgrundlagen bleiben unverändert. Änderungen werden als neue verknüpfte Fassung oder separate Anmerkung geführt. Export und Wiederherstellung bewahren ursprüngliche Bytes und Beziehungen.
4. **Geld:** Dezimalbeträge beziehungsweise Cent-Darstellung und Währung verlustfrei transportieren. Leistung, Forderung, Rechnung, Zahlung, Bankbuchung und Storno sind unterschiedliche Quellen mit ausdrücklich geregelter Zusammenführung. Neue Module buchen dasselbe finanzielle Ereignis nicht erneut.
5. **Großvorgänge:** Stabile Sortierung, Cursor/Checkpoint, vollständige Zählung und Exporte unabhängig von der sichtbaren Seite. Abbruch, Neustart, parallele Worker und einzelne fehlerhafte Datensätze verlieren weder Fortschritt noch Ergebnisse.
6. **Integrationen:** Unbekannte Quellfelder geschützt mit ursprünglichem Rohbeleg aufbewahren. Beobachtetes Feld ist nicht automatisch fachlich zugeordnet; beobachteter Endpunkt ist nicht automatisch freigegebene Schreibfunktion. Aktionskatalog, Vorschau, Ergebnisnachweis und Journal müssen zusammenpassen.
7. **Unklarer externer Ausgang:** Ein Timeout nach einem möglichen Schreibzugriff bedeutet nicht „nicht gesendet“. Erst externen Zustand abgleichen, dann gezielt fortsetzen. Keine blinde Wiederholung von Zahlung, Auftrag, Porto- oder Nachrichtenversand.
8. **Fehlerzustände:** Leerbestand, Ladefehler, veraltete Daten, laufender Job, Berechtigungskonflikt und unklarer externer Ausgang sind unterscheidbar. Eingaben bleiben erhalten. Keine erfolgreiche Nullsumme nach fehlgeschlagener Abfrage.
9. **Migration:** Veröffentlichte Revisionen werden nicht umgeschrieben. Neue additive Migrationen vom aktuellen Head; vorhandene SQLite-Daten und beide früheren Migrationszweige prüfen. Neue Tabellen, Rechte, Lösch-/Datenschutzverhalten und Vollbackup/Wiederherstellung gemeinsam berücksichtigen. Koordiniere gemeinsame Modelle und Migrationsköpfe für die spätere Integration.
10. **Oberfläche:** Deutsche verständliche Verwaltungssprache, klare Hauptaktion, leise sekundäre Aktionen, Aktenkontext, Tastatur/Fokus, 320/360/1440 Pixel. Keine technischen Adapterdetails im normalen Verwaltungsablauf, soweit sie keine Benutzerentscheidung unterstützen.

## Neue ausdrücklich beauftragte Bedienfunktionen

### Benachrichtigungen öffnen und gelesen archivieren


**Intention:** Ein Klick führt unmittelbar zur betroffenen Aufgabe, Forderung, Frist, Immobilie, Partei, Abrechnung oder zum Dokument. Erfolgreich bearbeitete Hinweise verschwinden aus dem ungelesenen Eingang und bleiben in der Historie auffindbar.


**Aktueller Stand:** `frontend/src/components/NotificationBell.jsx` setzt beim Klick oder Enter/Space nur `status=read`; eine Navigation findet nicht statt. Das Modell besitzt `entity_type/entity_id` und den Status `archived`, aber keine Benutzer-ID für einen individuellen Lesestatus. Glocke, Badge und „Alle gelesen“ beziehen sich auf die zehn geladenen Hinweise. Das ist keine vollständige benutzerbezogene Eingangs-/Archivverwaltung. Fachliche Erzeugung und Deduplizierung sind bereits in `backend/tests/test_generated_notifications.py` geprüft.

**Umsetzung:** Die heutige Benachrichtigungsverwaltung auf stabile Zieltyp-/Ziel-ID-Bezüge prüfen. Ziele aus Quellen ermitteln, nicht aus frei formulierten Titeln erraten. Einen gemeinsamen Zielauflöser für Glockenmenü, vollständige Liste, Arbeitszentrale und Deep Links verwenden. Nach gültigem Vorgangsaufruf die eigene Benachrichtigung mit `read_at` und `archived_at` wiederholsicher aktualisieren. Ungelesene Zähler serverseitig korrekt liefern; Archivfilter, Quelle und Wiederöffnen anbieten. Bestehende Benachrichtigungen ohne eindeutiges Ziel erhalten einen nachvollziehbaren Fallback.

Der fachliche Hinweis und die persönliche Lesebestätigung sind getrennte Daten. Ergänze bei gemeinsam sichtbaren Hinweisen einen benutzergebundenen Receipt-/Archivvertrag; das Öffnen durch A darf B nicht als gelesen quittieren. Leser dürfen ihre eigenen Hinweise bedienen, ohne allgemeine fachliche Schreibrechte zu erhalten. „Alle gelesen“ muss den vollständigen berechtigten Eingang erfassen. Für historische globale Statuswerte ist eine dokumentierte Übernahmeregel nötig; erfinde keine vergangenen Leser oder Lesezeitpunkte.

**Abnahme:** Umbenannte Vorgänge bleiben erreichbar. Maus, Enter, neuer Tab und mobile Bedienung funktionieren. Ein fremder Benutzer kann den Hinweis nicht quittieren. Bei fehlenden Rechten, gelöschter Quelle, fehlgeschlagener Navigation oder Offlinezustand geht die Benachrichtigung nicht verloren. Doppelklick, verlorene Antwort und parallele Tabs erzeugen keine widersprüchlichen Zähler; Archivierung bedeutet keine Datenlöschung.

### Dokumentwerkzeuge und Dokumenteditor


**Intention:** Eine professionelle Dokumentenarbeit mit den wichtigsten Word- und Foxit-ähnlichen Werkzeugen direkt aus Partei-, Immobilien- und Dokumentenakte. Der Schutzstatus bestimmt, ob Inhalt bearbeitet oder ein unveränderliches Original ergänzt wird.

**Aktuelle Grundlage:** Authentifizierter PDF-/Bildbetrachter, PDF.js, PDF-Textansicht, Seiten/Zoom, Originaldownload, OCR/Analyse, Versionierung, unveränderliches Archiv, Dokumenteingang und Entwurfssicherung. Ein vollständiger Word-/PDF-Inhaltseditor ist damit noch nicht vorhanden.

**Unveränderliche Dokumente:** Markierung, Hervorhebung, Kommentar, Textnotiz, Freihand, Stempel und handschriftliche beziehungsweise Bildunterschrift als eigene versionierte Ergänzung. Originaldatei und Originalhash bleiben identisch. Ergänzungen besitzen Autor, Zeit, Seitenbezug und Koordinatensystem. Eine sichtbare oder abgeflachte Ausgabe wird als abgeleitete Fassung mit Herkunftsnachweis gespeichert. Unterschriebene Rückfassung verknüpfen; handschriftliche Darstellung und kryptografisch verifizierte digitale Signatur klar unterscheiden. Änderungen an bereits signierten Bytes werden als Signaturbeeinträchtigung erkannt und nicht als unveränderte Signatur ausgegeben.

**Bearbeitbare Dokumente:** DOCX- beziehungsweise Textbearbeitung mit Absatz-/Zeichenformaten, Überschriften, Listen, Einzügen, Tabellen, Bildern, Links, Seitenformat/Rändern, Kopf-/Fußzeilen, Seitenzahlen/-umbrüchen, Fußnoten, Inhaltsverzeichnis, Suchen/Ersetzen, Kommentaren, Änderungsverfolgung mit Annehmen/Ablehnen, Rückgängig/Wiederholen, Vorlagen, Autosave, DOCX- und PDF-Export. PDF-Werkzeuge umfassen Anmerkungen, Formularfelder, Unterschriften, Seiten drehen/einfügen/neu ordnen/entnehmen/zusammenführen/teilen, Zuschneiden, OCR-Textschicht, Größenoptimierung und tatsächliche Inhaltsbearbeitung, soweit der gewählte Bearbeitungsmodus sie zusagt. Für Schwärzung muss entfernte Information auch in Textschicht, Objekten und Metadaten unzugänglich sein; ein schwarzes Rechteck genügt nicht.

**Architektur:** Vorhandenen Betrachter und Archivvertrag weiterverwenden. Geeigneten lokalen Editor beziehungsweise dokumentierten quelloffenen Baustein nach Formatqualität, Lizenz, Wartbarkeit und Offline-/Mehrbenutzerfähigkeit auswählen; keine ungeprüfte Abhängigkeit mit verpflichtendem fremden Cloudkonto. Formatumwandlung und große PDF-Arbeiten als isolierte wiederaufnehmbare Jobs. Jede Bearbeitung bindet Quellhash, Revision, Rechte und Ausgangsformat. Bei einer nicht verlustfrei unterstützten Datei vor dem Speichern einen konkreten Vergleich beziehungsweise einen ehrlichen separaten Bearbeitungsmodus anbieten.

**Abnahme:** Originalhash vor/nach Anmerkung und Signaturergänzung gleich. Lange mehrseitige DOCX-Dateien mit Tabellen/Bildern/Kopfzeilen und Sonderzeichen werden geöffnet, bearbeitet, wieder geöffnet und als PDF visuell geprüft. Formular-PDF, Scan, passwortgeschützte und beschädigte Datei, gedrehte Seiten, digitale Signatur, zwei Bearbeiter, Rechteentzug, Sitzungswechsel, Absturz und Exportwiederholung sind geprüft. Rückgängig wirkt fachlich zulässig; veröffentlichte Originale werden nie überschrieben. Die Werkzeugliste wird gegen echte Browserabläufe abgenommen, nicht allein gegen Bibliotheksdemos.

### Verkauf und Übergabe einer Immobilie


**Intention:** Ein seltener, über Objektoptionen erreichbarer Ablauf begleitet Verkauf und Eigentümerwechsel, ohne das normale Verwaltungsmenü zu überladen oder historische Daten zu verlieren.

**Umsetzung:** Verkaufsvorbereitung, Interessenten/Makler/Ansprechpartner, Angebote und relevante Dokumente optional mit der vorhandenen Vermarktung verbinden. Meilensteine und Checkliste für Vertrag, tatsächlichen wirtschaftlichen Übergang, Zählerstände, Schlüssel, Unterlagen und Restabrechnungen. Historische Eigentums-/Verwaltungszeiträume und den bestätigten Übergangsstichtag explizit führen. Offene Mieten, Guthaben, Kautionen, Dienstleistungsverträge, Ablesungen und später eingehende Rechnungen bleiben zuordenbar. Verkaufserlös, Nebenkosten, Darlehensablösung und laufende Miete sind getrennte Ereignisse; steuerliche Zuordnung benötigt ein eigenes bestätigtes Profil.

**Bedienung:** In den Optionen der Immobilienakte „Verkauf / Eigentümerwechsel“. Vorschau zeigt alle betroffenen Verträge, Aufgaben, Restposten, Dokumente und vorgeschlagenen Übergänge. Keine automatische Kündigung von Mietverhältnissen und keine automatische Übertragung von Benutzerrechten an einen Käufer. Historische Auswertungen behalten ihre damalige Grundlage; neue Verwaltungsaktivitäten berücksichtigen den Stichtag.

**Abnahme:** Immobilie mit zwei vermieteten Einheiten, Rückstand, Guthaben, Kaution, unterjährigem Übergang, späterer Betriebskostenrechnung und laufendem Stromvertrag vollständig bearbeiten. Stichtag korrigierbar mit neuer Fassung; Originale und frühere Berichte unverändert. Käuferausgabe enthält nur ausdrücklich freigegebene Daten. Wiederholung/Abbruch erzeugt keine doppelten Finanzereignisse oder verschwundenen Fristen. Rücknahme eines noch unbestätigten Verkaufs ist möglich; bestätigte Vorgänge werden nachvollziehbar korrigiert.

### Einstellungen grundlegend neu aufbauen


**Intention:** Eine gut auffindbare, umfangreiche Einstellungszentrale für täglichen Betrieb, individuelle Arbeitsweise, Fachregeln und privaten Serverbetrieb.


**Aktueller Stand:** `frontend/src/pages/Settings.jsx` besitzt Persönlich/Arbeitsweise/System, Administrationsbereiche, Backup/Betrieb und Updates; Preferences werden serverseitig gespeichert. `date_format`, `email_notifications`, `reminder_days` und `default_due_day` haben im lesenden Abgleich jedoch keinen nachgewiesenen fachübergreifenden Verbraucher außerhalb der Preferences-/Settings-Verwaltung. `formatDate` verwendet Locale, `formatMoney` standardmäßig EUR. Eine gespeicherte Option ist deshalb noch kein Nachweis ihrer Wirkung. Prüfe die tatsächlichen Verbraucher und schließe diese Verbindung, bevor neue Controls ergänzt werden. Anzeige in einer anderen Währung ist keine automatische Währungsumrechnung.

**Struktur:** Suche und klare Bereiche für persönliches Profil/Ansicht, Verwaltung und Nummernkreise, Finanzen/Abrechnung, Dokumente/Vorlagen/Editor, Benachrichtigungen/Erinnerungen, Integrationen, Benutzer/Rollen/Objektzugriff, Sicherheit/Sitzungen/TOTP, Sicherung/Wiederherstellung, Jobs/Betrieb, Import/Export und Erweiterungen. Persönliche Einstellungen, objektbezogene Fachregeln und installationsweite Konfiguration bleiben getrennt. Seltene technische Parameter gehören in einen verständlich erklärten erweiterten Bereich.

**Konkrete Optionen:** Sprache, Datum/Zahlen/Währung, Layout/Dichte, Startseite, Favoriten und gespeicherte Ansichten; Erinnerungsvorlauf, Ruhezeiten und Kanäle; Vorlagen/Briefkopf/Signatur/Profile; Standardkostenarten und bestätigte Regeln; Zuordnungs-/Importprofile und Integrationsverbindungen; Backupzeit, Aufbewahrung, zweites Ziel, Probe und letzter Ergebnisstatus; Jobstatus/Retry, Fehler- und Speicherübersicht; Rollen/Objektgrants, Sitzungsübersicht, MFA; Pluginstatus/Kompatibilität und dokumentierte API-Einstellungen. Vorhandene Einstellungen aus `.env` und der Oberfläche übernehmen, keine zweite konkurrierende Konfigurationsquelle.

**Verträge:** Effektiver Wert, Herkunft, Änderbarkeit und Geltungsbereich erkennbar. Geheimnisse maskiert speichern; Leerlassen bedeutet nicht versehentlich löschen. Servervariablen mit Vorrang werden als solche angezeigt. Änderungen validieren, CAS und Audit anwenden; nötigen Neustart kennzeichnen. Unsichere Produktionszustände dürfen nicht durch einen bequemen Schalter entstehen. Globale Regeln versionieren, damit alte Belege unverändert bleiben.

**Abnahme:** Suche findet die Einstellung und ihren Bereich; Eigentümer, Verwalter, Buchhaltung und Leser sehen nur zulässige Optionen. Änderungen überleben Neustart und Vollbackup/Restore. Parallele Bearbeitung, ungültige Werte, fehlender Schlüssel, unerreichbares Backupziel, env-Vorrang und Sitzungsauslauf haben verständliche Ergebnisse. Alte Einstellungen bleiben erhalten. Tastatur, 320/360/1440 Pixel und wiederaufnehmbare Formulare werden im Browser geprüft.

**Konkrete weitere UI-Nacharbeit aus der visuellen Installationsprüfung:** Sehr lange deutsche Überschriften können bei 320 Pixeln noch den letzten Buchstaben auf eine eigene Zeile umbrechen, beispielsweise „Dokumenteneingang“. Die Zusammenfassungskarten der Arbeitszentrale sind auf Desktop teilweise so schmal, dass Wörter wie „Kündigungsfristen“ zerfallen. Passe Mindestbreiten, responsive Schriftgrößen, Zeilenführung und gegebenenfalls kurze sichtbare Beschriftungen an. Prüfe fertig geladene Inhalte statt eines zufällig noch sichtbaren Ladezustands. Kein horizontaler Überlauf allein ist noch kein Nachweis guter Lesbarkeit.

## Schnittstellen und übrige Umsetzungspakete

Alle relativen Code- und Testpfade in den folgenden Abschnitten beziehen sich auf den zentralen Checkout. Historische Pfade beziehen sich auf dessen übergeordneten Ordner `C:\Users\matth\Documents\Codex\2026-10-01\wi\work`, sofern ein anderer Pfad ausdrücklich genannt ist. Genannte vorhandene Tests sind konkrete Ansatzpunkte, keine Behauptung einer neuen Liveabnahme.

### Gemeinsamer Integrationsrahmen und API Katalog


**Intention:** Jede Verbindung besitzt nachvollziehbare Parameter, unterstützte Aktionen, externen Bezug, Zustand, Vorschau und Ergebnisnachweis. Alle gefundenen zulässigen Schnittstellenfelder bleiben auswertbar, ohne dadurch unkontrolliert Geschäftsaktionen auszuführen.

**Stand:** `backend/services/integrations/manager.py` registriert genau sieben Provider: `email`, `whatsapp`, `contract-wizard`, `deutsche-post`, `listing-portals`, `huggingface`, `aktenwerk`. `backend/routers/integrations.py` stellt Schema, Konfiguration, Validierung, Aktivierung, Status/Metriken, explizite Ausführung und paginierte Historie bereit. Ausführung: `POST /api/v1/integrations/{id}/run` mit `{"payload":{"action":"…",…}}`. Provider-Manifeste bilden einen lokalen Aktionskatalog; FastAPI erzeugt den HTTP-Katalog. Eine integrierte ChatGPT-Action-/MCP-Fassade besteht nicht.

SecretBox schützt ausgewiesene Geheimnisfelder; `***` bewahrt einen vorhandenen Wert. Andere Konfigurationsfelder sind damit nicht vollständig verschlüsselt. Das aktuelle indizierte SQLite-Journal schreibt den Beginn vor dem Provideraufruf. Scheitert dieser Beginn, findet der Aufruf nicht statt; scheitert die Ergebnisablage, wird vor erneutem Versand gewarnt. Das Journal ersetzt keine fachliche dauerhafte Outbox mit wiederholsicherem Befehl.


**Restarbeiten:** Verbindung, nicht vertrauliche Konfiguration, Geheimnisreferenzen, externe Zuordnung und Aktionslauf dauerhaft trennen. Beobachtungen mit Zeitpunkt/Quellhash als `discovered`, `observed`, `mapped`, `accepted` führen. Aktionen mit Pflicht-/Optionalfeldern, Typen, Einheiten, Einschränkungen, Seitennavigation, externem Ergebnis und Nebenwirkungsart beschreiben. Unbekannte Rohfelder geschützt erhalten; personenbezogene Rohantworten nicht in allgemeine Logs schreiben. Verbindungstest ohne Geschäftsänderung. Dauerhafte Job-/Run-IDs und Checkpoints, fachliche Wiederholungsschlüssel, eigene Quellenrevision, Rechtezaun und Abschlussbeleg anbinden. Erweiterbare Fassade erst auf diesem Vertrag aufbauen.

**Wiederverwendung:** `integration-history` (`0fb59785`) enthält verschlüsselte private SQL-Historie/Chunks und Wiederherstellungsprüfungen. `integration-connections` (`552e3460`) besitzt verschlüsselten Konfigurationsstore, CAS und Parameterzustände; die globale Aktivierung beziehungsweise Connection-/Mappingpersistenz war bewusst noch `ddl_pending`. Historische generische Probes sind keine reale Netzabnahme. Den heute echten SMTP-NOOP nicht durch einen solchen Platzhalter ersetzen.

**Abnahme:** Neustart erhält Verbindungen, History und unbekannte Felder; Rotation, fehlender Schlüssel, Rollen-/Objektentzug, parallele Konfigurationsänderung und Wiederherstellung funktionieren. Mehr als 10.000 Läufe bleiben vollständig auffindbar. Unklarer externer Ausgang besitzt einen Abgleichpfad; eine erneute Browserantwort erzeugt keine zweite Geschäftsaktion. Kein Geheimnis in Schema, API-Fehler, Log oder Export. Vorhandene Testfamilien: `test_integrations_hardening.py`, `test_integrations_api_hardening.py`, `test_integration_manager.py`, `test_integrations_router.py`, `frontend/src/test/Integrations.test.jsx`.

### TEHA Kundenportal


**Intention:** Kosten-/Nutzerdaten, Abrechnungen/Rechnungen, Immobilien/Perioden und technische Termine mit TEHA verbinden; wiederholbare Übernahme und später belegte Rückübertragung direkt aus den passenden Akten.

**Stand im Produkt:** Kein TEHA-Provider, Receive-Router oder integriertes TEHA-Domänenmodell. Das Portal des autorisierten Kontos ist `https://kunden.socs.ws`. Die Zugangsdaten wurden vom Benutzer bereitgestellt, werden hier nicht wiederholt. Lies sie nur aus der autorisierten verschlüsselten Konfiguration beziehungsweise verwende eine vorhandene autorisierte Sitzung.

**Vorhandene Pakete:** `teha-transport` (`951b3de512351dd9a2c782546628c08ff9eda102`) mit `backend/services/providers/teha_transport.py`, `teha_types.py`, `schema_observation.py`, `exchange_observation.py`, `docs/TEHA_TRANSPORT_HANDOFF.md` und Tests `test_teha_transport.py`, `test_teha_exchange_observation.py`. Historisch beobachtet wurden Login `POST /api/user`, Immobilien/Perioden über `/api/liegenschaften`, lesende POSTs für Dokumentliste/-inhalt sowie technische Aufträge über `/api/auftrag` und `/api/Auftrag/{terminId}`. `terminId`, Auftragsnummer, Objekt- und Periodenkennung bleiben unterschiedliche Identitäten. Der Transport begrenzt Methoden/Origin, prüft JSON/Base64/PDF, persistiert keine Tokens und wiederholt keine Netzwerkaktion automatisch.

`teha-receive-domain` (`b3d6d5d382e656eb21c29726f0dc9ada917f4e6e`) enthält Mapping, Preview, Importreceipt, Originaldownload und Domänenmodelle. Veröffentlichung verweigert dort bewusst mit `503 teha_write_unit_unavailable`, solange die zentrale atomare Transaktions-/Rechtegrenze fehlt. `teha-transaction-unit-proposal` (`6d7157cb`) ist ein Vorschlag und keine fertige Commitstrecke.


**Restarbeiten:** Historischen Transport am heutigen Portal erneut lesend prüfen; Versions-/Feldmanifest aktualisieren. Explizite Zuordnung von externem Objekt, Periode, Einheit/Nutzer und Auftrag zu heutigen Akten. Fortsetzbare Empfangsläufe mit vollständigem Rohquellnachweis. Vorschau für neu/unverändert/geändert/widersprüchlich; geprüfte Bestätigung atomar mit Originalarchiv und Receipt speichern. Dokumentänderungen anhand tatsächlicher Bytes behandeln. Techniktermine zu Aufgabe/Projekt verknüpfen. Danach Kosten-/Nutzerdatenübermittlung und Restarbeitsaufträge einzeln entwickeln, inklusive tatsächlichem externem Abschlussstatus. Geänderte Portalantworten erzeugen einen bearbeitbaren Mappingfall.

**Abnahme:** Neuer autorisierter Portal-Lesetest mit vollständigem Byte-/Hashvergleich. Wiederholter Import, Tokenablauf, Abbruch/Neustart, geänderte Bytes, unbekannte Felder, parallele Quelle, Rechteentzug bis Commit und identischer Wiederholungsauftrag. Vollrestore behält Mappings/Originale/Receipts. Jede externe Schreibfunktion braucht einen überprüften kontrollierten Vorgang und belegte Antwort beziehungsweise anschließenden Zustandsabgleich. Ein GET-/Dokumenttransport beweist keine Kosten- oder Auftragsübertragung.

### Bankimporte und Zahlungszuordnung


**Intention:** Originale Bankbewegungen vollständig und doppelfrei übernehmen, Mieten/Teilzahlungen/Gebühren/Rückläufer erklären und Quellen erhalten.

**Stand:** `backend/routers/reports.py` bietet `POST /reports/bookings/import` mit `account_id` und `csv_content`, Format `date;amount;text`. Es schreibt zeilenweise und sammelt Fehler; Teilimporte sind möglich. Originalarchiv, vollständige bestätigte Vorschau und Importfingerprint fehlen in dieser Strecke. Bestehende Bankbuchungs-/Mietzahlungszuordnung im Produkt ist davon getrennt und wird wiederverwendet.

**Kandidat:** `bank-import` (`e01d3996`) besitzt CSV und MT940, Originalbytes/SHA, Format-/Encoding-/Spaltenmapping, Fehler-/Zeilenstaging, vollständige revisionsgebundene Vorschau, atomare Bestätigung, Fingerprint/Replayprüfung, Rechte-/Kontosperren sowie SQLite-/PostgreSQL-Konfliktprüfungen. Dateien: `bank_import.py`, `bank_import_parser.py`, `bank_import_guards.py`, `bank_import_download.py`, `bank_matching.py` und zugehörige Router/Modelle/Testfamilien. `bank-discovery` (`80b548f7`) erhält ungewöhnliche Spalten/MT940-Tags und fehlerhafte Zeilen in einem privaten, an Quell-/Mappinghash gebundenen NDJSON-Manifest.


**Restarbeiten:** Die robuste Importstrecke an heutige Buchungs-, Verschlüsselungs-, Objektgrants-, Archiv- und Revisionsverträge portieren. Legacyimport über dokumentierten Kompatibilitätsweg führen. Original, Vorschau, Fehlerkorrektur und bestätigte Übernahme bedienbar verbinden. Matching bleibt ausdrücklicher Vorschlag; Teilbudget, Rest, Storno und Rücklastschrift berücksichtigen.

**Abnahme:** Alle Zeilen/Salden/Centbeträge stimmen mit Original. Zweiter Import, verlorene Erfolgsantwort und parallele Bestätigung erzeugen keine zweite Buchung. Fehlerhafte/geänderte Vorschau schreibt nichts; Rechteentzug bis Commit wirkt. Mehrere reale CSV-Varianten, MT940-Sammelfälle, Kodierungen, negative Beträge und >10.000 Bewegungen verlustfrei. Quellbeleg und Zuordnung bleiben nach Restore erhalten.

### CAMT und FinTS HBCI


**Intention:** Strukturierte Bankdateien und optional autorisierten Bankabruf anschließen. Das ist ein eigener Transport-/Formatumfang und keine Folge einer gespeicherten IBAN.

**Stand:** Kein integrierter CAMT-Parser, FinTS-/HBCI-Transport, TAN-Ablauf oder Zahlungsauftrag. Der historische robuste Bankimport deckt CSV/MT940, nicht diese zusätzlichen Verfahren.


**Restarbeiten:** CAMT-Versionen/Namespaces und Bankvarianten, Sammelbuchung/Unterpositionen, Gebühren, Referenzen und Rückläufer an den gemeinsamen Stagingvertrag anbinden. FinTS zunächst lesend: Bankkonfiguration, Kontenauswahl, Sessions, TAN/Freigabe, Ablauf/Abbruch und Rückfragen. Etablierte gepflegte Bibliotheken nach aktuellen offiziellen Verträgen prüfen und hinter einen versionierten Adapter setzen. Zahlungsaufträge sind gesonderte ausdrücklich ausgewählte Aktionen mit Vorschau und eindeutigem Auftragsnachweis.

**Abnahme:** Bankkonkrete Originaldateien und unabhängige Saldenorakel, Duplikate und geänderte Referenzen, wiederholter Abruf und nicht doppelte Bewegungen. TAN abgelaufen/abgebrochen, Bank nicht erreichbar, Reauth und unklarer Auftragsausgang haben bedienbare Zustände. Zugangsdaten/TAN niemals in Historie. Annahme eines Zahlungsauftrags und tatsächliche Ausführung bleiben getrennt.

### DATEV und Steuerberaterexport


**Intention:** Einen tatsächlich importierbaren, abgestimmten Buchungsstapel mit eindeutiger Kontierung und Belegbezug erzeugen.

**Stand:** `backend/routers/reports.py` exportiert einen vereinfachten UTF-8-CSV mit neun Spalten, Centbeträgen und separaten Stornos, verwendet aber Konten-/Kategorienamen statt validierter DATEV-Kontonummern. `EXTF_Buchungsstapel.csv` ist deshalb kein belegter DATEV-Importvertrag. Tests: `test_advanced_features.py`, `test_finance_precision.py`.

**Kandidat:** `datev-export` (`d7ba1808`) mit `backend/services/datev_streaming.py`, `datev_export.py`, Router `datev.py`, `test_datev_streaming.py`, `test_datev_export.py` und HTTP-/Scope-/Migration-/PostgreSQL-Prüfungen. Historischer Vertrag: EXTF700/21/v13, 125 Spalten, striktes CP1252, Centgenauigkeit, Profile, konsistenter Snapshot und vollständiges privates Exportpaket. Allgemeine Umsatzsteuer-/Automatikkontenabdeckung ist dort bewusst nicht vorhanden. `chat-datev` enthält Entwürfe, kein pauschal fertiges Zusatzmodul.


**Restarbeiten:** Kontenrahmen, Konten-/Steuerschlüssel, Berater/Mandant, Wirtschaftsjahr und erlaubte Buchungstypen versioniert konfigurieren. Eindeutige Mappingvorschau und quellgenaue Summen. Unvollständige/ungültige Kontierung blockiert den ganzen Export. Streamen/Job statt vollständigem Bestand im Speicher. Neutrale CSV separat benennen. Benötigte Umsatzsteuerfälle ausdrücklich modellieren und fachlich abnehmen.

**Abnahme:** Tatsächlicher Zielimport beim geeigneten DATEV-/Steuerberaterwerkzeug; identische Summen, Soll/Haben, Stornos, Belegbezüge und Umlautzeichen. Mehrere Konten/Jahre/Objektfilter, unzulässige Zeichen/Kontierung und große Bestände. Historische Schemafixtures sind eine Vorprüfung, kein Zielimport.

### WISO Steuer Windows und Steuerjahr 2026


**Intention:** Daten aus der Immobilienverwaltung mit nachvollziehbarem Formularbezug direkt in die Einkommensteuererklärung übernehmen. Das erste verbindliche Fachjahr ist 2026.

**Stand:** Keine integrierte WISO-/Buhl- oder Jahressteuerprojektion. WISO Hausverwalter 365 ist installiert und wurde vom Benutzer zur Untersuchung bereitgestellt. WISO Steuer für Windows ist auf diesem Rechner bislang nicht installiert; ein tatsächlicher Zielimport ist noch nicht nachgewiesen. Steuerjahr und Jahreszahl des Programmtitels nicht ungeprüft gleichsetzen.

**Kandidaten:** `annual-tax-projection` (`12a537b3`) mit `annual_tax_source.py`, `annual_tax_projection.py`, `annual_tax_export.py`, `annual_tax_storage.py`, Router `annual_tax.py`, `AnnualTaxPage.jsx` und Tests für Projection/Access/Integration/Recovery/Migration/PostgreSQL. Enthält neutrale CSV-/JSON-/ZIP-Projektion bestätigter Zahlungsbuchungen, explizite Konten-/Kategorien-/Objekt-/Formularmappings, Ausschlüsse/Aufteilungen, unveränderliche Profile/Snapshots und Quellen. Allgemeine AfA-, Eigentumsquoten-, Umsatzsteuer- oder Steuerberechnungsautomatik ist damit nicht fertig. `annual-tax-fixture-guards` (`ba12d451`) korrigiert Fixtures/Startupgrenzen.

`buhl-probe` (`0ac0538b`) mit `tools/buhl_xml_probe.py` analysiert Strukturen/Signaturen/Differenzen; `buhl-research` enthält lokale Untersuchungsartefakte. `BUHL_PRODUCER_EVIDENCE.md` dokumentiert synthetische Herstellerexporte aus Hausverwalter 365 21.02.1530 für 2025/2026: XML, Formular V, Feldnummern/Indizes/Werte. Jahresfeldsätze unterscheiden sich; einzelne AfA-Feldbedeutungen sind nicht isoliert bewiesen.


**Restarbeiten:** Neutrale quellgenaue Jahressteuerbasis portieren, danach herstellerspezifisches Profil getrennt entwickeln. Im installierten Hausverwalter je Fachfeld kontrollierte synthetische Änderungen exportieren und vergleichen. Zuordnung zu Quelle/Formular/Feld/Index/Jahr dokumentieren; keine nicht verstandenen Feldnummern raten. Exportvorschau mit fehlenden Angaben, Objektzuordnung und Quellsummen; Herstellerformat mit Profilversion und unverändertem Originalexport archivieren. Eigentumsanteile/AfA/Finanzierungsgrundlagen nur mit klaren versionierten Eingaben und bestätigter fachlicher Bedeutung ergänzen.

**Abnahme:** Passende WISO-Steuer-Windowsausgabe für Fachjahr 2026 bereitstellen, tatsächlichen Importweg prüfen und jedes unterstützte Feld in der Zieloberfläche vergleichen. Mehrere Objekte, Aufteilungen, Erstattungen, negative/Nullwerte und unterstützte AfA-Fälle. Exportbyteprüfung allein und neutraler CSV/JSON-Download zählen nicht als WISO-Kompatibilität. Fehlt die Zielinstallation, entwickle alle übrigen Teile autonom weiter und liefere diesen einzelnen externen Nachweis als klar benannte Voraussetzung; behaupte keine Freigabe.

### E Mail Kommunikation und allgemeine Outbox


**Intention:** Aktenbezogene Vorlagen, Entwürfe, Empfänger, freigegebene Originale/Anhänge, Versand und Empfang besitzen eine gemeinsame nachvollziehbare Historie.

**Stand:** `backend/services/email_service.py` besitzt SMTP/SMTP_SSL, STARTTLS, Authentifizierung, TLS-Kontext, Timeout, expliziten Empfänger, Text/HTML und NOOP-Verbindungstest ohne Nachricht. Angenommene Nachricht bleibt trotz anschließendem QUIT-Fehler erfolgreich. Allgemeine Anhänge, dauerhafte Versandzustandsmaschine und sichere Trennung vor/nach möglicher DATA-Annahme fehlen. Kein integrierter IMAP-/Graph-/Exchange-Eingang gefunden.

Die Mahnung hat bereits eine echte manuelle Outbox: `/dunning/outbox`, `/{id}/eml`, `/{id}/mark-sent`. Die EML enthält das geprüfte archivierte Mahn-PDF; `mark-sent` dokumentiert manuelle Zustellung, sendet nicht per SMTP. Sie wird angeschlossen, nicht neu erfunden.

**Kandidat:** `C:\Users\matth\Documents\Codex\2026-10-02\wi\work\communication-center`, Commit `d0a63ddfbc606a4eac669d74126c0039fe415ccc`. SQL-Outbox mit ready/claimed/sent/failed/unknown, stabiler Message-ID, eingefrorenen MIME-Bytes, Checkpoint vor DATA, Lease/Workergrenzen und ausdrücklicher Wiederaufnahme. Tests: `test_outbox_transport.py`, `test_outbox_crash_disconnect.py`, `test_outbox_postgres.py` sowie HTTP-/State-/Journal-/Integrationstests. Vorlagen und Kommunikations-PDF-Snapshots sind ebenfalls vorhanden. Achtung: `dispatch_email` übergibt dort Empfänger/Betreff/Text; das separat eingefrorene PDF wird noch nicht als Anhang mitgegeben.


**Restarbeiten:** Aktuelle Quellen/Rechte/Archive anschließen, Vorlagen und Bausteine versionieren, mehrere Empfänger mit korrektem To/Cc/Bcc, Originalanhänge und MIME bytegleich einfrieren. Allgemeine SQL-Outbox mit Jobkern verbinden, Mahn-Outbox erhalten. Posteingang und Antworten über stabile Message-ID/In-Reply-To/Referenzen zuordnen; mehrdeutige Fälle zur Prüfung. Interne Threadfehler aus dem Fachanhang zuerst korrigieren.

**Abnahme:** Vorschau sendet nichts. Kontrollierter Empfänger, TLS und tatsächliche Anhangbytes; Abbruch vor/nach DATA, fehlende Bestätigung, Browserverbindungsabbruch nach Annahme, Workerwechsel, Rechteentzug und Wiederholung. Unbekannte Zustände niemals blind erneut senden. Empfangene Antwort landet genau im richtigen Vorgang; gleicher Name oder ähnliche Betreffzeile reichen nicht. Kein fest hinterlegter Beispieladressat in generischen Tests.

### WhatsApp und Post

**Stand:** Beide aktuellen Provider sind ausdrücklich planned/not_implemented. Historisch bietet `communication-center` WhatsApp über die offizielle Meta-Cloud-API für Templates, Direkttext nur mit gesondertem Opt-in, externe Message-ID und unknown ohne Auto-Retry. Kein belegter Livezustellnachweis oder vollständiger Webhook-/Medienweg.

INTERNETMARKE dort ist Privatkunden-Shopvorbereitung im Browser ohne Geschäftskundenvertrag: Produktvorauswahl und Anschriftprüfung. Shopöffnung ist kein Kauf, kein Frankaturbeleg und keine Briefzustellung. Historische Preise sind datierte Hinweise. Eine vorhandene `DeutschePostBusinessProvider`-Klasse ist keine aktiv abgenommene Geschäftskundenstrecke.

**Rest und Abnahme:** WhatsApp-Template/Parameter/Sprache/Empfänger korrekt, autorisierter kontrollierter Empfänger, Medien soweit zugesagt, Zustell-/Fehlerwebhook mit geprüfter Herkunft und Replaykontrolle. Angenommen, zugestellt und gelesen getrennt. Privatkunden-Posthandoff mit dem tatsächlich gekauften Originalbeleg und dem gewählten Schreiben verknüpfen; vorbereiten/frankiert/manuell versandt getrennt. Automatischer Portokauf wäre ein zusätzlicher expliziter Aktionsvertrag mit Preisvorschau, Wiederholungsschlüssel, Beleg und Abgleich unklarer Kaufzustände. Keine tatsächliche Bestellung nur zum Erkunden von Parametern auslösen.

### Immobilienportale und Vermarktung

**Stand:** `backend/services/portal_adapter.py` enthält IS24-/Immowelt-Stubs; lokale Listings/Exposé-/Text-/Clipboardfunktionen sind keine belegte Veröffentlichung. Kandidat `portal-integrations-current` (`05f18c09`) hat IS24 OAuth1, Publish/Update/Deactivate/Status, Publikationsjournal und UI. IS24-Fotos sind dort ausdrücklich angefordert, aber null hochgeladen. Immowelt/OpenImmo erzeugt XML 1.2.7 im ZIP und überträgt per FTP/standardmäßig FTPS; Bilder sind REMOTE-URLs. „Datei übertragen“ beweist keine Veröffentlichung. Branch enthält weitere alte Familien/Migrationen und wird nicht komplett darübergelegt.


**Restarbeiten:** Quellen-/Foto-/Objektrechte, externes Inserat, Inhaltsvorschau und Veröffentlichungsrevision anschließen. Fotos tatsächlich übertragen beziehungsweise erlaubte erreichbare Bildquelle nachweisen. Reale OAuth-/Providerkonfiguration und Rückmeldungen. Exposé-PDF, Interessenten, Besichtigungen und Übernahme in einen Mietvertrag zu einem durchgängigen lokalen Ablauf verbinden; lokale Vorbereitung bleibt ohne Anbieterlogin möglich.

**Abnahme:** Autorisierte Anbieterumgebung, präzise Vorschau, stabile externe ID, Create/Update/Deactivate/Status und Bilder. Timeout nach Publish reconciliert statt doppelt anzulegen. FTPS-Transfer und fachliche Veröffentlichung getrennt. Quelle geändert, Rechte entzogen, Rückmeldung verspätet und mehrdeutige Fehler. Tests als Einstieg: `test_portal_adapter.py`, `test_portal_publication.py` und historische Frontendtests.

### Aktenwerk

**Intention und Stand:** Bereits echte aktuelle Schnittstelle: `backend/routers/aktenwerk.py`, `backend/services/aktenwerk.py`, `frontend/src/features/aktenwerk/`, `docs/AKTENWERK_INTERFACE_20261014.md`. Vertrag `immomanager-aktenwerk/1`, stabile Exchange-ID, Art/Datum, Objekt-/Einheits-/Partei-/Vertragsbezüge, Finanz-/Steuerhinweise und Originaldatei/SHA. `/status`, `/manifest`, `/export`, explizites `/send`; ZIP beziehungsweise multipart an `/api/immomanager/v1/documents`, Idempotency-Key aus Exchange-ID und Hash. Teilfehler bleiben sichtbar; keine automatische Übertragung. `test_aktenwerk.py` prüft unter anderem Klassifikation, ZIP, Rechte, URLgrenzen und simulierten Transport.

**Restarbeiten und Abnahme:** Gegenstelle muss den Vertrag wirklich implementieren. HTTP 409 wird heute als „bereits vorhanden“ behandelt, ohne zwingenden zurückgegebenen Hashvergleich. Receipt beziehungsweise Statusabgleich muss Exchange-ID und Hash bestätigen; andere Bytes bei gleicher ID dürfen nicht als Erfolg gelten. Tatsächlicher ZIP-/Einzeldokumentimport, wiederholter Versand, Teilfehler, unterbrochene Bestätigung und Rückmeldung prüfen. Steuerhinweise sind weder WISO- noch DATEV-Abnahme.

### KI Speicher Plugins und weitere APIs

**Stand:** HuggingFace ermöglicht echte optionale lokale CPU-Modelle und Fallbacks; Health ist kein Qualitätsnachweis der Extraktion. Der `contract-wizard`-Provider ist eine kleine Textvorschau und nicht der vollständige integrierte Vertragsworkflow. Lokale Pythonplugins unter `backend/plugins/` können Router/Lifecycle/Ressourcen beisteuern, laufen aber mit Prozessrechten; keine Sandbox, Signatur- oder eigene Rechteisolierung. `file_storage.py` hat S3-Abstraktion, während der globale Speicher LocalStorage bleibt; eine wirksame Startupverdrahtung der beworbenen S3-Variablen fehlt im geprüften Code. `s3://` ist kein Browserdateizugriff. `backend/routers/autotest.py` hat einen echten ausdrücklich ausgelösten GitHub-Contents-API-PUT für Berichte; als externe Übermittlung erfassen.

**Rest und Abnahme:** KI-Vorschläge behalten Quelle/Vertrauen/Bestätigung und verändern keine Finanzdaten automatisch. S3 nur mit vollständig geprüftem Originalzugriff, Auth/Range, Objektgrants, Restore, Fehlerzustand und optionalem lokalem Betrieb aktivieren. Persistente Plugins benötigen API-Kompatibilität, deklarierte Daten/Migrationen, Rollen, Sicherungsumfang und Upgrade-/Deinstallationsverhalten. API-/Action-/MCP-Fassade führt nur freigegebene Aktionen über dieselben Rechte- und Wiederholungsverträge aus. Installationskeys oder ein Pluginmanifest sind keine sichere Sandbox. Wiederholbarer API-Vertragstest und mindestens ein echtes Pluginupgrade mit Backup/Restore; externe Berichte enthalten keine privaten Daten oder Geheimnisse ohne bewusste Auswahl.

## Fachliche Restpakete und Betrieb

Die folgenden Fachpakete enthalten die aktuellen Code-/Testbelege. Dort als optionale Ergänzung bezeichnete Funktionen sind keine bereits fertigen Kernfunktionen. Die im Benutzerplan ausdrücklich beauftragten Erweiterungen werden nach den vorrangigen Schnittstellen ebenfalls entwickelt; „optional“ beschreibt gegebenenfalls ihren seltenen Bedienzugang, keine Aufforderung zum Abbruch des Auftrags.


### Fachpaket 1 Leistungsperiodenergebnis


**Intention:** Cashflow, periodengerechtes Ergebnis und Prognose nachvollziehbar trennen.

**Aktueller Stand:** compute_period_result summiert Vertrags-Sollmiete plus sonstige Erträge minus
Kosten aus booking_totals nach Buchungsdatum. Es ist keine vollständige periodische
Rechnungs-/Leistungsabgrenzung; unbezahlte Lieferantenrechnungen fehlen. Warmmieten
inklusive Vorauszahlungen sind die bestehende bewusst dokumentierte Basis.

**Restarbeiten:** Abgrenzungsregeln für Leistungszeiträume, Rechnungen, Korrektur/Gutschrift,
Nebenkostenabrechnung/Vorauszahlungen und Erstattungen explizit festlegen. Gemeinsame
Belegidentität nutzen, damit Zahlung und Rechnung nicht doppelt als Aufwand zählen.
Bestehenden Cashflow und bisherigen Bericht nicht still semantisch umdefinieren;
Ergebnisbasis/API-Ausgabe versionieren bzw. eindeutig benennen und erklären.

**Abnahmekriterien:** Rechnung für 2026, bezahlt 2027: Aufwand im gewählten Leistungsjahr,
Zahlungsabfluss nur 2027. Teilzahlung, Storno/Gutschrift, Kostenübernahme aus Projekt
und Objektvertrag, Nullmonate und alle Portfolio-/Objekt-/Einheitsfilter centgenau.

**Codebelege:** backend/services/report_service.py::compute_period_result/_other_flows;
backend/services/finance_ledger.py; backend/domain/service_contract_finance.py;
backend/routers/reports.py; backend/services/report_render.py.

**Vorhandene Regressionen:** test_finance_precision.py::test_period_result_counts_rent_due_once_and_not_the_payments,
test_period_result_runs_in_whole_months; test_report_pdf.py::test_report_pdf_uses_json_filters.

### Fachpaket 2 Liquiditätsprognosen und gespeicherte Berichte


**Intention:** belastbare erwartete Geldflüsse mit erklärbaren Annahmen/Szenarien.

**Aktueller Stand:** künftige volle Monate; Vertrags-Soll nach Mietverlauf/Vertragsende plus
Durchschnitt sonstiger Erträge minus Durchschnitt historischer Kosten. Startsaldo
bis heute, Nullmonate im Durchschnitt. Kein Szenariomodell, kein Rest des laufenden
Monats, keine gezielte Rückstandsprognose oder geplante künftige Buchungs-/Rechnungs-
fälligkeiten. Noch nicht angewendete Mietanpassungen und Tarif-/Projektpläne fließen
nicht als eigene Zukunftsquelle ein. Private Tabellenansicht ist kein gespeicherter
finanzieller Bericht mit eingefrorener Definition/Parametern.

**Restarbeiten:** Ursprung und Priorität der geplanten Flüsse, Szenarioabweichungen, Rückstands-
annahmen, Leerstand und Zahlungstage modellieren; Basis vs. Szenario trennen;
Berichtsdefinition/Filter/Version speichern und Rechte bei erneutem Öffnen prüfen.

**Abnahmekriterien:** unabhängig vorgerechnete 3/6/12-Monatsfälle einschließlich Restmonat,
Vertragsende, Mietänderung, Ausfall, Lieferantenfälligkeit und bereits geplanter
Buchung ohne Doppelzählung. Gleiche Definition in Bildschirm, JSON, CSV und PDF.

**Codebelege:** backend/services/report_service.py::compute_liquidity_forecast/current_balance;
backend/routers/reports.py::liquidity_forecast; frontend/src/pages/Dashboard.jsx.

**Vorhandene Regressionen:** test_finance_precision.py::test_forecast_expects_the_contracts_rent_and_averages_over_months_without_bookings,
test_forecast_ends_with_the_contract_and_ignores_bookings_after_today.

### Fachpaket 3 Forderungsreste und gemeinsame Zahlungszuordnung


**Intention:** jede Forderung hat einen belegbaren offenen Rest, konsistent mit Zahlung,
Guthaben, Kautionsverrechnung, Mahnung und Auswertung.

**Aktueller Stand:** Vertragszahlungen werden fachlich zugeordnet; Mahn-/Kautionsabläufe besitzen
eigene abgeleitete Restberechnungen. Allgemeines Receivable.status='partial' besitzt
keinen gespeicherten bezahlten Teil; compute_receivables_aging addiert amount_due.

**Restarbeiten:** gemeinsame eindeutige Forderungsidentitäten und Zuordnungs-/Ausgleichsledger
für manuelle Forderungen, Abrechnungsdifferenzen, Guthaben und Kautionsverrechnung;
keine Parallelbuchhaltung neben bestehenden bookings/payment_allocations.

**Abnahmekriterien:** Forderung 100, Zahlung 40, Kautionsverrechnung 20 => überall Rest 40;
Gutschrift und spätere Rücklastschrift nachvollziehbar; Stichtage, erneutes Ausführen,
Parallelzugriff und Rücknahme atomar. Migration lässt alte Beträge interpretierbar.

**Codebelege:** backend/services/report_service.py::compute_receivables_aging;
backend/services/payment_allocations.py; backend/services/deposits.py;
backend/services/dunning.py; backend/routers/billing.py::create_receivables_from_period;
docs/DEPOSITS_20261011.md Abschnitt Bewusst offen.

**Vorhandene Regressionen:** test_finance_precision.py; test_deposits.py; test_dunning_process.py;
test_billing_regression.py::test_receivable_generation_rolls_back_all_tenants_on_failure.

### Fachpaket 4 Messabdeckung Bewohner und Widerspruchsentscheidung


**Intention:** vollständige zeitbezogene Umlage mit erklärbarer Messgrundlage.

**Aktueller Stand:** Personentage und Zählerersatz sind implementiert. consumption summiert alle
in_service-Zähler derselben Art; keine Erkennung ungemessener Lücken bzw. absichtlich
paralleler/überlappender Messstellen. Nur feste exakte Einheitenfaktoren. Gasvolumen
zu Energie mit zeitbezogenem Brennwert/Zustandszahl und HKV-Bewertungsfaktoren fehlen.
Bewohnerhistorie sind datierte Personenzahlen; API hat GET/POST/DELETE, kein Update.
BillingObjection kennt nur open/correction/resolved; keine begründete Zurückweisung
ohne neue Abrechnungsfassung. Das separate dunning_dispute/decide ersetzt das nicht.

**Restarbeiten:** Messstellen-/Ersatzbeziehung und Tagesabdeckung mit explicit warning/blocker;
fachlich begrenzte/versionierte Umrechnungsfaktoren; Bewohnerkorrektur gegen Revision;
Objection-Entscheidung mit Begründung und Wiederaufnahme des Periodenablaufs.
Keine individuelle Bewohner-Personendatenbank erfinden, wenn nur Personentage verlangt.

**Abnahmekriterien:** alter Zähler endet 30.6., neuer beginnt 3.7. => fehlende Tage sichtbar;
Parallelzähler von Ersatz unterscheiden; Gasfaktorwechsel und unzulässige Mischung;
Personenzahlkorrektur verändert keine finalisierte Fassung; abgewiesener Widerspruch
behält das Original bytegleich und ändert nur nachvollziehbaren Entscheidungsstatus.

**Codebelege:** backend/services/utility_billing.py::_consumption_shares/conversion_factor;
backend/models.py::ContractOccupancyCreate/MeterCreate/BillingObjectionCreate;
backend/routers/contracts.py occupancies; backend/routers/billing.py objections.

**Vorhandene Regressionen:** test_billing_regression.py; test_billing_preflight.py;
test_billing_regression_postgres.py; test_handover_protocol.py::
test_handover_readings_split_the_consumption_at_the_tenant_change.
Altgrenze: vor Snapshot-Einführung finalisierte PDFs können heutige Namen zeigen;
kein nachträgliches vermeintliches Original erzeugen. Als Altbeleg kennzeichnen.

### Fachpaket 5 Mieterwechsel und zusätzliche Übergabenachweise


**Intention:** Auszug, Leerstand, Einzug, Bestätigung und belegbare Zustandsübergabe.

**Aktueller Stand:** verbunden, revisions- und rechtegeprüft; Originale und Korrekturen archiviert;
WGB tatsächlicher Einzug wird nicht aus Vertragsdatum erfunden. Namen+Bestätigungen
sind keine elektronische Signatur. related.templates ist ausdrücklich []. Fotos
sind gehasht und verkleinert im PDF, die externen Quelldateien nicht unveränderlich
archiviert. Einheit hat keine versionierte Raumliste; Vorschlag aus Vorprotokoll.
Beauftragte Ergänzungen: versionierte Mieterwechsel-Briefvorlagen mit Quellenbindung;
eigene Raum-/Inventarliste; unveränderliche Originalfotos bzw. unterschriebener Scan
als ergänzender Nachweis mit eigener Identität; elektronische Signatur separat.

**Abnahmekriterien:** Vor-/Nachvertrag korrekt, Vorlagendaten stammen aus geprüfter Revision,
Korrektur erzeugt neues Original, alte PDFs/Fotos bytegleich; fremde Verträge/Dateien
404; keine Signaturbehauptung allein aus eingetippten Namen oder Kontrollkästchen.

**Codebelege:** backend/services/handover_protocol.py::_related/create_from_contract/finalize/start_correction;
backend/services/housing_confirmation.py; backend/services/document_versions.py;
frontend/src/features/handoverProtocol/; docs/HANDOVER_PROTOCOL_20261008.md.

**Vorhandene Regressionen:** test_housing_confirmation.py; test_housing_confirmation_pdf_layout.py;
test_handover_protocol.py; test_handover_protocol_postgres.py; HandoverProtocol*.test.jsx.

### Fachpaket 6 Vertragsfristen und Nachführung ihrer Aufgaben


**Intention:** historische Tarife/Orte, Kosten und konkrete Fristfolgen ohne Doppelzählung.

**Aktueller Stand:** Erwartungen, Rechnungen, Zahlungen, Kostenübernahme und dauerhafte Erinnerungen
implementiert. Erinnerungsaufgabe hängt am ersten Vertragsort; bei mehreren Portfolios
kann ein berechtigter Benutzer eines anderen Ortes die Mitteilung, aber nicht die
Aufgabe sehen. Geänderte Fristen erzeugen neue Erinnerungen, alte Aufgaben bleiben.
Längere Ausfälle nach Ablauf des Vorlaufs werden nicht fachlich nachgemeldet.

**Restarbeiten:** obsolete Aufgaben/Benachrichtigungen anhand Quellfrist versioniert erledigen;
klare Mehrort-Sichtbarkeit; expliziter Catch-up-Status. Verbrauchskostenprognose aus
Grund-/Arbeitspreisen, Sonderkündigungsprüfung und frei eingegebener Abschlagsplan
sind eigene Erweiterungen, nicht durch weitere versteckte Buchungen zu simulieren.

**Abnahmekriterien:** Friständerung + Neustart + zwei Worker => eine aktuelle Aufgabe, alter Stand
erkennbar erledigt; alle berechtigten Standorte sehen dieselbe Frist, fremde nicht;
verpasste Frist klar überfällig statt verschwunden. Teilperioden-Rundung über mehrere
Kostenübernahmen ergibt exakt den freigegebenen Gesamtbetrag; Überlappungen ablehnen.

**Codebelege:** backend/services/jobs/service_contract_deadlines.py::remind/_primary_property;
backend/services/service_contracts.py::deadlines/due_reminders;
backend/domain/service_contract_finance.py.

**Vorhandene Regressionen:** test_service_contracts.py::test_deadline_reminders_are_created_once_per_contract_and_deadline,
test_recoverable_bills_enter_each_billing_period_once; test_service_contracts_postgres.py;
test_service_contract_terms.py.

### Fachpaket 7 Projekte und belegbare Nacharbeit


**Intention:** eine Projektakte bis Abnahme/Kosten, keine zweite Finanzdatenquelle.

**Aktueller Stand:** Abhängigkeiten kreisfrei; Quote→Order→Change→Invoice→Payment, Statusgates,
immutable Protocol-PDF und gemeinsame Zahlungsquellen vorhanden. Keine automatische
Rechnungsstatusangleichung; abgeleitete Unterschiede erscheinen als Hinweise.

**Restarbeiten:** belegbare Mängel-/Nacharbeitsobjekte und Fristen/Benachrichtigungen; optional
Gantt/kritischer Pfad/Kapazität. Regeln für nachträglich geänderte Rechnung/Buchung
explizit festlegen statt still durch gedeckelte Zuordnung zu kaschieren. Kontakt-
Lebenszyklus (derzeit Namenssnapshot ohne harte Kontakt-FK) bewusst behandeln.

**Abnahmekriterien:** fachliche Nacharbeit schließt mit Nachweis, wird bei offener Pflicht nicht
versehentlich abgeschlossen; Rechnungssaldo konsistent mit Rechnungsprüfung;
Umbuchung/Betragsverkleinerung führt zu Konflikt oder sichtbarem Reconcile-Auftrag;
Abhängigkeiten bleiben bei parallelen Gegenkanten kreisfrei.

**Codebelege:** backend/services/maintenance_projects.py; backend/domain/project_costs.py;
backend/domain/project_graph.py; frontend/src/features/maintenanceProject/.

**Vorhandene Regressionen:** test_maintenance_projects.py und test_maintenance_projects_postgres.py;
MaintenanceProject.test.jsx; test_business_qol_review.py (Statushistorie/Fieldtimeline).

### Fachpaket 8 Nachrichtenzuordnung bei Threadwechsel


**Intention:** Threadwechsel darf weder Nachrichten noch Antwortadressierung vertauschen.

**Aktueller Stand:** interne MessageThreads/Messages und paginierte HTTP-Listen existieren;
api.list liest Folgeseiten vollständig. Kein generelles externes Kommunikations-
zentrum. Dunning besitzt bereits eigene richtige langthreadfähige Antwortzuordnung.
Statisch konkreter **Restarbeiten:** Messages.jsx::loadThreadMessages setzt selectedThread vor
await und übernimmt anschließend jede Antwort ohne thread-/requestgebundene Fence;
späte A-Nachrichten können nach Wechsel zu B in B-Ansicht landen. Fehler wird als []
verschluckt. create_message in routers/messages.py prüft Pfadthread, speichert aber
payload.thread_id unverändert; eine abweichende Body-ID wird nicht abgeglichen.

**Restarbeiten:** Pfad-ID als maßgebliche ID erzwingen oder abweichende Body-ID 422; Threadwechsel
mit Abort+Generation; Lese-/Sendefehler sichtbar; Entwurf und Antwort-ID an Thread
binden; stabile SQL-Keysetseiten mit identischen Zeitstempeln statt gesamter Liste.

**Abnahmekriterien:** zwei Threads A/B, A verzögert nach B => niemals A-Inhalt unter B; Senden
bleibt beim bewusst gewählten Thread; PfadA/BodyB schreibt nichts; >10.000 Nachrichten
und gleiche sent_at vollständig; Rechteentzug und fremder Thread weiter geschützt.

**Codebelege:** frontend/src/pages/Messages.jsx::loadThreadMessages/handleSendMessage;
backend/routers/messages.py::create_message/list_messages;
backend/repositories/communication_repo.py::list_messages/create_message.
Vorhandene Tests: test_crud_routers.py Nachrichtenfälle; test_dunning.py::
test_a_long_thread_is_read_completely_page_by_page (nur Mahnthread, nicht UI-Beweis).
Dies ist aus Code abgeleitet, in dieser Inventur nicht gegen reale Daten ausgeführt.

### Fachpaket 9 Allgemeine Kommunikation und Empfang


**Intention:** fachgebundene, ausdrücklich freigegebene Kommunikation mit Belegnachweis.

**Aktueller Stand:** Gesprächsnotiz+Followup atomar; Mahn-PDF/.eml/Versandvermerk und Reply-Matching
vorhanden. SMTP-Textversand ist explizit bereits implementiert und meldet nur nach
Empfängerannahme Erfolg; SMTP kann keine archivierten Anhänge. WhatsApp, Deutsche
Post und ListingPortal sind ausdrücklich planned/not_implemented; IS24/Immowelt-
Adapter sind Stubs. Ein Listingportal ist kein Mieterportal.

**Restarbeiten:** gemeinsame dauerhafte Outbox mit Richtung, Teilnehmern, Fachbezug, Original-
anhängen, Auswahlvorschau, Idempotenzschlüssel, Retry/unklarer Zustellung, Provider-
Referenz und Empfangskorrelation; bestehende Dunning-Outbox anschließen. Reale
Adapter/Providerabnahme je Kanal separat, niemals Mock/HTTP200 als Zustellbeweis.

**Abnahmekriterien:** Vorschau ohne Versand; nur explizite Auswahl sendet; verlorene Antwort
erzeugt keine behauptete zweite Zustellung; PDF-Anhang bytegleich zum geprüften
Original; falsches/mehrdeutiges Aktenzeichen landet in Prüfung, nicht automatisch
bei namensgleicher Partei; partielle Erfolge und endgültige Ablehnung sichtbar.

**Codebelege:** backend/services/email_service.py; backend/services/integrations/providers.py;
backend/services/portal_adapter.py; backend/services/dunning.py;
backend/db/dunning_models.py; frontend/src/features/dunning/.

**Vorhandene Regressionen:** test_dunning.py::test_the_outbox_prepares_letters_and_email_drafts_but_sends_nothing;
test_integrations* / test_services_and_security.py bestehende SMTP-/Stub-Gegenproben.

### Fachpaket 10 Mieterportal Offlineerfassung und Historie


**Intention:** vertragsgebundene Selbstbedienung und begrenzte offline Wiederaufnahme.

**Aktueller Stand:** Rollen sind eigentuemer/verwalter/buchhaltung/techniker/readonly; Portfolio-
grenzen sind keine Mieterrechte. Kein User↔Tenancy-Mandat und keine Tenant-Portal-
Routen. Offline existiert schon als privater lokaler Formularbuffer, serverseitige
Entwürfe und revisionsgeprüfte Wiederaufnahme; kein allgemeiner Offline-Client mit
heruntergeladenen Fachdaten oder Offline-Finalisierung. Feldhistorie gilt für KINDS
in business_field_history, nicht jede Domäne/Bulkoperation; fachliche langlebige
Ereignisse existieren modulspezifisch, keine allgemeine Event-/Pluginmigrationsebene.

**Restarbeiten:** Portalmandate mit Gültigkeit und Akten-/Dokument-Whitelist; APIs/UI separat;
keine Portalrolle durch Freigabe ganzer Portfolios bauen. Offline nur bewusst
freigegebene Daten/Entwürfe, Benutzerbindung, Quoten/Ablauf/Löschung und explizite
Konfliktentscheidung; Originalabschluss/Finanzschreiben bleiben online geprüft.
Historie nur um gezielt gewählte Domänen erweitern, keine Vergangenheit erfinden.

**Abnahmekriterien:** zwei Mietverträge derselben Einheit zu verschiedenen Zeiten und zwei
Haushalte sehen nur eigene genehmigte Daten; Widerruf entzieht Zugriff; abgelaufene
Offlinebuffer werden nicht angezeigt/veröffentlicht; zwei Geräte + Sourceänderung
führen zur Gegenüberstellung statt Überschreiben; keine A-Daten nach Login B.

**Codebelege:** backend/models.py::_VALID_ROLES; backend/services/portfolio_scope.py;
backend/services/workspace.py/workspace_contexts.py/business_field_history.py;
frontend/src/hooks/useFormDraft.js; frontend/src/api.js; frontend/src/contexts/AuthContext.jsx.

**Vorhandene Regressionen:** test_workspace.py/test_workspace_postgres.py; WorkspaceForms.test.jsx;
WorkspaceAnchorDraft.test.jsx; CrossTabSession/CrossTabAuth/CrossTabDraft.test.*.

### Fachpaket 11 Fachpläne und dauerhafte asynchrone Arbeit


**Intention:** fortsetzbare Vorkommen/Belege, bedienbarer dauerhafter Betrieb.

**Aktueller Stand:** job_runs/job_occurrences, Leases/Fencing, Checkpoints, Retry, Berliner
Sommerzeit und >10.000 Nachholvorkommen vorhanden. Periodisch: Serienaufgaben,
Eskalation/Mahnvorschläge, ServiceContract-Fristen, Vollbackup und Restoreprobe.
Der ältere Doc sagt Eskalation sei insgesamt ein einziger Abschnitt; mittlerweile
werden Mahnverträge in DUNNING_CHUNK=100 abgearbeitet. Das erste Eskalationssegment
bleibt getrennt; nicht den ganzen Job neu bauen.

**Restarbeiten:** Müll-/Ablesepläne und ICS-Ausnahmen inklusive EXDATE/Änderungs-/Stornofolge und
Belegabschluss auf diesem Kern; kein solcher Fachplan im aktuellen Jobkatalog.
Allgemeine OCR-Tasks nutzen noch services/task_queue (sync/thread, temporäre lokale
Status), nicht job_runs; dauerhafte owner-/portfolio-gebundene Async-API und
kontrolliertes Neustarten/Bereinigen von Läufen fehlen. Monat/Jahrregeln kappen
bisher auf Tag 28. Admin-Ops zeigt Backup/Probe, keine generelle Job-Konsole.

**Abnahmekriterien:** Planimportänderung, Ausnahme, Ausfall/Neustart, Leaseübernahme und zwei
Worker => genau ein aktuelles Vorkommen mit Beleg; alter Worker kann nichts
publizieren; Status aus anderem Worker/Prozess verfügbar; Zugriff nur auf eigene
oder ausdrücklich administrative Läufe; Retry mit begrenztem Backoff; Speicher
und Historienspeicherung bleiben begrenzt, fachliche Nachweise bleiben erhalten.

**Codebelege:** backend/services/jobs/{core,recurring,schedule,scheduler}.py;
backend/services/task_queue.py; backend/routers/tasks_status.py;
backend/routers/files.py::upload_file; backend/services/task_recurrence.py.

**Vorhandene Regressionen:** test_durable_jobs.py (Restart, Leaseverlust, konkurrierende Worker,
10.000+, Regelversion, DST); test_operations_backup.py; test_hardening_scale.py.

### Fachpaket 12 Portable vollständige Wiederherstellung


**Intention:** echte komplette Installation aus unabhängiger Sicherung reproduzieren.

**Aktueller Stand:** SQLite-online-copy inklusive WAL, reguläre Uploads, Integrationsstate+Journal,
Keyring und DATA_DIR/.env, SHA-Manifest, zweites Ziel, Retention, isolierte Probe und
explizite Migration implementiert. Restoreziel muss frisch/leer sein. Normaler
Appimport migriert bestehende DB nicht; Launcher führt vorher upgrade aus.
Konkrete Restlücken: Prozessenv/CWD-.env und externe Schlüssel/Dateien sind nicht
automatisch im Vollbackup; backup-settings.json bewusst ausgeschlossen; Symlinks
übersprungen, fehlender Uploadordner ergibt 0 Dateien. Probe kann mit Secretwarnung
ok=true melden (Passphrase fehlt/externe SECRET_KEYS/missing_key_ids). Sie prüft
DB-Integrität/ursprüngliche Counts und Testmigration, startet aber keine Anwendung.
Direkt backend.ops/upgrade liest Settings aus CWD/.env; der normale Launcher lädt
DATA_DIR/.env und schreibt gegebenenfalls Defaults bereits vor dem Backup.

**Restarbeiten:** exportierbarer tatsächlicher Runtime-Manifest ohne Geheimnisprotokollierung,
gesondert geschütztes Secret-Bundle, Restore-Reifegrad statt pauschalem ok, Referenz-
vollständigkeit von Attachments, wiederholbare isolierte Start-/Browserprobe und
explizite neue Zweitzielkonfiguration. Migrationbackup in frischem Ziel prüfen;
bestehende Backuparchive werden sonst durch apply_retention verändert.

**Abnahmekriterien:** Maschine/Umgebung ohne Original-CWD/env/Keyfile, Restore aus Archiv+extern
verwahrter Passphrase, Anmeldung und Originale korrekt, keine Verbindung zur
Live-DB, keine Scheduler-/Integrationswirkungen in Probe, alle produktiven
Belegreferenzen vorhanden; Vorher/Nachher-Dateninvarianten nach Migration erhalten.

**Codebelege:** backend/services/full_backup.py::Sources.from_settings/_create/_probe/
_check_secrets/restore_archive; backend/ops.py; backend/upgrade.py;
backend/__main__.py::_configure_runtime_environment; backend/db/schema_state.py;
scripts/start_windows.ps1; scripts/backup_scheduler.py.

**Vorhandene Regressionen:** test_operations_backup.py; test_backup_credentials.py;
test_migrations.py; test_secret_key_concurrency.py; test_tee_writer.py.
Zusatz: Windows-Starter baut vorhandene frontend/dist/index.html nicht neu;
Releaseprozess muss dist ausdrücklich aus dem gewünschten Commit bauen.

### Fachpaket 13 Großbestände und Mehrbenutzerbetrieb


**Intention:** vollständige, berechtigte und reproduzierbar schnelle Arbeit unter Last.

**Aktueller Stand:** echter synthetischer SQLite-Cardinality-Benchmark 100k/1m Buchungen, 72k
Forderungen, 240 Monate, zehn getrennte Benutzer mit parallelen Reads/Writes,
unabhängigen Centsummen und vollständigen Such-/Export-IDs. Keine allgemeine
20-Jahre-Geschäftsworkflow-Garantie; ausdrücklich nicht enthalten: Periodenergebnis,
Forecast, DATEV, OCR/Dateien, Restore, PostgreSQL und Browserrendering unter Last.
Portfolio-/Dateifences und JWT-Rechte gelten bereits; Login-Ratelimits und Token-
Revocation sind im SQL-Modus DB-backed. Die alte Behauptung 'alles prozesslokal'
ist falsch. Der allgemeine Registrierungs-RateLimiter bleibt prozesslokal.

**Restarbeiten:** gezielte Zusatzmessungen für echte neue Bericht-/Job-/Dokumentpakete, dieselben
unabhängigen Orakel, klare Budgets und Freeze-Hashes; PostgreSQL als eigener Lauf.
Distributed Registrierungslimit nur bei Multiworker/öffentlich angebotenem Register
ergänzen. Kein ungezielter Performanceumbau und keine Abschneidegrenzen einführen.
Snapshot-JSON ist Geschäftsdatenexport, kein Installationsbackup: Benutzer und
Resource-/Upload-Grants werden nicht transportiert; nach Import bleibt ungebundene
Altinformation für eingeschränkte Konten unsichtbar. Optional sichere bewusste
Rebind-Werkzeuge statt still Rechte nach Namen rekonstruieren.

**Abnahmekriterien:** vollständige Summen/Seiten über 10k, 100k, 1m, abgeschnittene/übersprungene
Phasen kein Erfolg; alle bestätigten Writes dauerhaft; Memory/RSS/Deadline im Bericht;
kein fremder Name/Beleg unter Last oder nach Rollenentzug; parallele Registrierung
über Worker überschreitet festgelegtes globales Limit nicht.

**Codebelege:** tools/scale_finance_search.py/.md, tools/scale_runtime.py, tools/xstress/;
backend/auth.py::check_login_rate_limit/is_token_revoked/check_register_rate_limit;
backend/services/portfolio_http.py/portfolio_scope.py/data_snapshot.py;
backend/db/access_models.py.

**Vorhandene Regressionen:** test_global_search_scale.py; test_workspace_scale.py;
test_hardening_scale.py; test_portfolio_access.py; test_upload_auth.py;
test_booking_writes.py; tools/scale_finance_search_test.py.

### Fachpaket 14 Rechnungsoriginal und kontrollierte OCR Übernahme


**Intention:** vom geprüften Eingangsbeleg nachvollziehbar zur freigegebenen Rechnung.

**Aktueller Stand:** Sach-/Rechenprüfung, Vieraugenregel, Teilfreigabe, Skonto, Gutschriften und
Streitentscheidung sind vorhanden. Ordinary Uploads werden nur per Datei-SHA
überwacht; sie werden noch nicht als unveränderliche Originalbytes archiviert.
Dokumenteingang erkennt inzwischen Rechnungsnummer/-datum/Betrag/Lieferant und
speichert Vorschläge; seine Reviewoberfläche übernimmt Dokumentmetadaten und
Zuordnungen, nicht diese Werte als neuen Invoice-Entwurf. Daher ist 'OCR fehlt'
falsch, die kontrollierte Invoice-Feldübernahme bleibt jedoch ein eigenes Paket.

**Restarbeiten:** normalen Belegupload revisionsgebunden als Original übernehmen; Invoice-
Entwurf aus Erkennung mit sichtbarer Quellen-/Feldzuordnung und Bestätigung,
keine automatische Freigabe/Buchung; Quelle/hash und Korrekturen versionieren.
Endgültige Entscheidungen nur durch eigene dokumentierte Wiederaufnahme bzw.
Korrekturregel ändern; keine alte Freigabe nach Quelländerung still weiterverwenden.

**Abnahmekriterien:** Dateitausch nach Eingang kann Original nicht zerstören; erkannte Beträge
mit Fehl-/Mehrdeutigkeit bleiben Vorschlag; wiederholte Übernahme erzeugt genau
eine Rechnung; Rechteentzug/Sourceänderung vor Commit schreibt nichts; VAT-/Skonto-
und Zahlungsrechnung bleiben dieselben wie bei manueller Erfassung.

**Codebelege:** backend/services/document_versions.py (Moduldokumentation: keine öffentliche
Originalarchivierung gewöhnlicher Uploads); backend/services/invoice_review.py;
backend/services/business_documents.py::analyze_bytes/DOCUMENT_FIELDS;
frontend/src/features/workCenter/DocumentIntakeQueue.jsx::DocumentReview;
frontend/src/features/invoiceReview/ReviewPanels.jsx.

**Vorhandene Regressionen:** test_invoice_review.py::test_receipt_records_original_and_refuses_a_duplicate_key_without_reason
(der Name beweist SHA-Eingang, nicht Archivbytes), test_arithmetic_checks_every_rate_and_the_gross,
test_partial_approval_dispute_credit_note_and_result; test_business_qol.py::
test_document_proposal_requires_explicit_cas_review; DocumentIntakeQueue.test.jsx.

### Fachpaket 15 Widerruf von Sitzungen bei Datenbankfehlern


**Intention:** bestätigtes Logout/Refreshrotation muss auch über Neustart/Worker gelten.

**Aktueller Stand:** SQL-Revocation und SQL-Loginlimits existieren. Aber _revoke_token_db fängt
SQLAlchemyError ab und protokolliert nur; Router-Logout meldet trotzdem erfolgreich
abgemeldet. _is_token_revoked_db antwortet bei SQLAlchemyError mit False, wenn der
lokale Cache den Token nicht kennt. Damit ist die Ausfallsemantik kein bestätigter
installationsweiter Widerruf. Das ist ein konkreter Codepfad, keine ausgeführte
Behauptung über einen Vorfall in der Installation.

**Restarbeiten:** Widerrufspersistenz explizit bestätigen oder Aktion als fehlgeschlagen melden;
fehlgeschlagene Revocationprüfung darf einen unbekannten Token nicht als gültig
ausgeben. DB-Fehler von fachlich 'nicht widerrufen' unterscheiden; Refreshrotation
und Uploadcookie-Lifecycle mit derselben Entscheidung behandeln. Lokale Caches
bleiben Optimierung, nicht die Garantie.

**Abnahmekriterien:** zwei getrennte Authworker, Worker A widerruft Token; Worker B verweigert
ihn auch nach Neustart. Injizierter Commitfehler => kein falsches Erfolgs-Logout/
keine erfolgreiche Rotation des nicht dauerhaft gesperrten alten Refresh-Tokens.
Injizierter Lesefehler => expliziter temporärer Authfehler, keine erfolgreiche
Autorisierung nur wegen fehlendem Cacheeintrag. Normale DB-Wiederaufnahme erlaubt
weiterhin gültige nicht widerrufene Sitzungen; kein Tokeninhalt in Fehlermeldungen.

**Codebelege:** backend/auth.py::_revoke_token_db/_is_token_revoked_db/revoke_token;
backend/routers/auth.py::logout/refresh.

**Zu erweiternde Regressionen:** backend/tests/test_auth.py Revocation-/Logout-Fälle;
backend/tests/test_upload_auth.py::test_logout_deletes_cookie_and_rejects_its_replayed_access_token.

## Verbindliche Umsetzungsreihenfolge

1. **Arbeitsbasis sichern und konkrete Fehler nachweisen:** eigenen Zweig/Runtime anlegen; historische Pakete inventarisieren. Die statischen Revocation- und Threadzuordnungsbefunde zuerst mit aussagekräftigen Regressionen auf der aktuellen Basis reproduzieren und schließen. Keine Fehlersimulation gegen Anwenderdaten.
2. **Gemeinsame Verbindungs- und Importgrundlage:** Connection-/Mapping-/Run-/Receipt-Vertrag, sichere Journal-/Secretpersistenz und fortsetzbare Arbeit. Vorhandene Originale, Rechte und Jobgrenzen verwenden. Robuste CSV-/MT940-Bankübernahme und TEHA-Empfang bis zur lokalen bestätigten Veröffentlichung vollständig entwickeln.
3. **Finanz- und Steuerquellen:** gemeinsamer Forderungsrest, Leistungsperiodenergebnis, DATEV-Kontenprofile und Jahressteuerquellen. WISO-Profil 2026 und verfügbare Zielprüfungen anschließen; fehlende Consumerinstallation als genau abgegrenzten Nachweis behandeln. CAMT und lesendes FinTS parallel unabhängig voranbringen.
4. **Kommunikationsgrundlage und Anbieter:** allgemeine Outbox/Anhänge/Empfang, bestehende Mahnakte anschließen; WhatsApp, Post und Portale getrennt abnehmen. Aktenwerk-Receipt/-Hashabgleich gegen reale Gegenstelle. TEHA-Rückübertragungen erst auf der bestätigten lokalen Basis ergänzen.
5. **Neue tägliche Bedienung:** Notificationrouting/persönliches Archiv und die vollständige neue Einstellungszentrale früh liefern. Editorumfang zuerst als konkrete Werkzeugmatrix festhalten, dann Annotationen/Originalschutz und vollständigen bearbeitbaren Dokumentweg implementieren. Verkauf über Objektoptionen.
6. **Fachliche Ergänzungen:** Müll-/ICS-/Ablesepläne, Vertragsfrist-Nachführung, Messabdeckung/Widerspruchsentscheidung, OCR→Rechnungsentwurf, Restmängel und vollständige Übergabenachweise. Bestehende Hauptmodule gezielt ergänzen.
7. **Erweiterungen und Betrieb:** Szenarien, Berichtskonfiguration/-planung, Mieterportal, begrenzte Offlineerfassung, Pluginupgrade-/Eventverträge und portable Restoreabnahme. Diese ausdrücklich geplanten Pakete gehören zum Auftrag; native Apps, Blockchain und alternative Cloud-Neuentwicklung sind historische Ideen ohne aktuellen Implementierungsauftrag.
8. **Gemeinsame Abnahme im eigenen Zweig:** nicht nur Einzelpakete prüfen. Berechtigungs-/Archiv-/Finanz-/Restoreverträge über alle neuen Verknüpfungen, echte unabhängige PostgreSQL-Verbindungen, reale Browser und große Bestände gemeinsam nachweisen. Danach ein integrationsfertiges Ergebnis an Codex liefern.

Die Reihenfolge beschreibt Abhängigkeiten. Unabhängige Teile dürfen parallel vorbereitet werden, wenn gemeinsame Modelle/Migrationen zentral koordiniert sind. „Vollständig“ bedeutet alle zugesagten Wege einschließlich Konflikten und Wiederanlauf; ein funktionierender Happy Path mit unverbundenem Rest ist kein Paketabschluss.

## Prüfen ohne die laufenden Installationen zu verändern

Verwende je Lauf ein frisches eigenes Datenverzeichnis. Kopiere keine produktive `.env` und keine echten Zugangsdaten in Fixtures. Setze Pfade, Datenbank und Scheduler ausdrücklich vor jedem Testprozess. Die automatische Testfixture ist zusätzlicher Schutz und kein Ersatz für eine kontrollierte Umgebung.

Beispiel für Backendprüfungen im eigenen Entwicklungsverzeichnis:

```powershell
Set-Location -LiteralPath 'C:\Users\matth\Documents\Codex\2026-10-01\wi\work\pro-interfaces-20261015'
$qaDir = Join-Path (Get-Location) ('artifacts\pro-tests\' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $qaDir | Out-Null
$env:DATA_DIR = $qaDir
$env:UPLOADS_DIR = Join-Path $qaDir 'uploads'
$env:BACKUP_DIR = Join-Path $qaDir 'backups'
$env:INTEGRATION_STATE_FILE = Join-Path $qaDir 'integrations.json'
$env:SECRET_KEY_FILE = Join-Path $qaDir 'secrets\keyring.json'
$env:DATABASE_URL = 'sqlite:///:memory:'
$env:ENVIRONMENT = 'development'
$env:JOB_SCHEDULER_ENABLED = 'false'
$env:BACKUP_SCHEDULE_ENABLED = 'false'
$env:TEST_STORE_BACKEND = 'memory'
$env:SQLITE_PERSISTENT_STORE = 'false'
$env:ALLOW_INMEMORY_FALLBACK = 'true'
$pyExe = 'C:\Users\matth\Documents\Codex\2026-10-01\wi\work\review-venv-20261013\Scripts\python.exe'
& $pyExe -m pytest backend/tests -q --tb=short --cov=backend --cov-fail-under=80
```

Für SQL einen neuen Prozess mit `TEST_STORE_BACKEND=sql`, `SQLITE_PERSISTENT_STORE=true`, `ALLOW_INMEMORY_FALLBACK=false` und `DATABASE_URL=sqlite:///<absoluter eigener qaDir>/test.db` verwenden. Vor dem Start kontrollieren, dass die URL tatsächlich in deinem Laufverzeichnis liegt. Unter Windows `/` in der SQLite-URL verwenden. Die vorhandene Pythonumgebung nicht für neue Abhängigkeitsversuche verändern; bei neuen Paketen eine eigene Umgebung mit den bestehenden Constraints anlegen.

Weitere verpflichtende Prüfungen:

```powershell
& $pyExe -m ruff check backend
& $pyExe -m mypy --platform linux backend
Set-Location -LiteralPath '.\frontend'
npm.cmd ci
npm.cmd run lint
npm.cmd run test
npm.cmd run build
```

Die Linux-Plattformwahl dient dem Vergleich mit der bestehenden CI; tatsächlich Windows-spezifische Teile zusätzlich auf Windows prüfen. `requirements.txt`, `constraints.txt`, `backend/requirements-dev.txt` und `frontend/package-lock.json` gemeinsam konsistent halten. Keine Assertions, Berechtigungsgrenzen oder CI-Gates lockern, um einen Lauf grün zu machen.

**PostgreSQL:** `scripts/check_postgres.py` verwendet `IMMO_TEST_POSTGRES_ADMIN_URL` und verweigert fehlende Konfiguration beziehungsweise übersprungene Pflichtfälle. Verwende nur einen eindeutig eigenen Testserver/eigene Testdatenbanken. Große Schema-/Rechte-/Idempotenzänderungen benötigen echte unabhängige Verbindungen, nicht zwei Sessions auf derselben Verbindung. Bekannte Testumgebungen erst inventarisieren; kein fremdes Cluster stoppen oder zurücksetzen.

**Browser:** `scripts/run_workspace_browser_qa.py` startet ausschließlich seine eigene synthetische lokale Installation. Aufruf aus deinem Zweig mit absolutem Playwrightpfad:

```powershell
& $pyExe scripts/run_workspace_browser_qa.py --playwright 'C:\Users\matth\Documents\Codex\2026-10-01\wi\work\claude-review-20261013\artifacts\tooling\browser-20261013\playwright-local.mjs' --output '.\artifacts\pro-browser'
```

Dieser Prüfer setzt seine eigenen Zugangsdaten und beendet nur seine eigenen Prozesse. Ändere ihn nicht so, dass er stattdessen die Anwenderdatenbank verwendet. Der Installationssmoke in `artifacts/deployment-20261015/installed-browser.mjs` wurde für Codex' autorisierte Umstellung erstellt; er besitzt gezielte private Schreibrechte und ist kein allgemeines Fixtureskript gegen Port 8765.

Für neue Schnittstellen-/Editor-/Einstellungswege eigene tatsächliche Browserprüfungen ergänzen: 1440/360/320 Pixel, Tastatur und Fokus, Formularfehler und Sitzungswechsel, gewöhnliche sowie lange mehrseitige PDFs/DOCX mit Sonderzeichen. Screenshots auch ansehen. Ein Browserautomationsergebnis ohne visuelle Dokumentkontrolle genügt für Layout nicht.

**Leistung:** `tools/scale_finance_search.py`, `tools/scale_runtime.py`, `tools/xstress/` und ihre Anleitungen verwenden. Bestehende Tests mit einer Million Buchungen, 240 Monaten und zehn getrennten Benutzern sind eine gezielte Größenbasis. Zusätzliche Domänen wie Forecast, Periodenergebnis, DATEV, Dokumentarchive, OCR, Restore und PostgreSQL gesondert messen. Physisches Dokumentarchiv und Metadatenbestand unterscheiden. Bericht enthält CPU/RAM/Datenträger, Datenmengen, Scope, p50/p95/Maximum, Gesamtspeicher, Sperrwartezeiten, bestätigte Writes und vollständige Quellenorakel. Langsame oder abgebrochene Phasen bleiben sichtbar und gelten nicht als bestanden.

## Abschlusskriterien und Lieferung an Codex

Jedes Paket liefert:

1. Konkrete Benutzerabsicht und endgültigen Umfang, implementierte Oberfläche/Endpunkte und ausdrücklich nicht unterstützte Eingaben.
2. Commit-Hashes in Abhängigkeitsreihenfolge, eigenen Zweig/Arbeitsordner und sauberen Status. Gemeinsame Migrationen/Modelle/Router/Permissions/Archive-/Restoredateien gesondert nennen. Kein erzwungenes Umschreiben veröffentlichter Commits.
3. Daten-/API-Vertrag, additive Migration, Kompatibilitätsweg für `/api/v1`, Berechtigung, Revision, Wiederholungsschlüssel und Fehler-/Wiederanlaufverhalten.
4. Aussagekräftige Regressionen mit unabhängig vorgerechneten fachlichen Ergebnissen. Memory und SQLite, relevante native PostgreSQL-Gegenproben, tatsächliche Browser- und Dokumentprüfung; Logs, XML/JSON-Ergebnisse und Screenshots mit eindeutigem Commitbezug.
5. Bei einem Adapter eine Aktions-/Feldmatrix: Quelle, Typ, Pflicht/optional, Einheit, entdeckt/beobachtet/gemappt/abgenommen, Testfall und tatsächlicher externer Ergebnisbeleg. Keine Geheimnisse oder fremden privaten Rohdaten in öffentlichen Artefakten.
6. Vollbackup-/Restore-Nachweis für neue persistente Daten, Geheimnisse, Dateianhänge, private Workspacebezüge und Originale. Simulierter Stromausfall/Abbruch darf keine halbe Veröffentlichung hinterlassen.
7. Liste tatsächlich offener externer Nachweise mit genauer Voraussetzung und vorbereitetem Prüfschritt. Keine pauschale Behauptung „fertig“, wenn Consumerimport oder Zustellung noch aussteht.
8. Kurze Integrationsanweisung für Codex: Übernahmereihenfolge, Konfliktstellen, erforderliche Konfiguration, Testbefehle, Migrationsvorbereitung, Rückweg und sichtbare neue Benutzerabläufe.

Halte in deinem eigenen Zweig ein Fortschrittsdokument mit Anforderung → Implementierung → Tests → externe Abnahme → Commit → noch offen. Aktualisiere es nach jedem abgeschlossenen Paket und vor einer Kontextunterbrechung. Setze anschließend von diesem Stand fort. Ältere erfolgreiche Tests nicht als Prüfung späterer Änderungen ausgeben. Wenn du GitHub verwenden kannst, darfst du deinen eigenen Entwicklungszweig mit seinen Ergebnissen pushen; Zusammenführung, Releaseveröffentlichung und Umstellung der laufenden Anwenderinstallation bleiben bei Codex.

## Freigabe und Installationsnachweis

Der ursprüngliche vollständige QoL-Stand `ec6b6268` bestand GitHub-Lauf `38775719192`: 574 Frontendtests, vier Backendvarianten mit jeweils 2.078 bestandenen und 103 bedingten übersprungenen Fällen, 86 native PostgreSQL-Prüfungen ohne Skip, Container-Systemtest und Deploymentfreigabe. Die bedingten Skips der allgemeinen Varianten sind kein Ersatz für das verpflichtende separate PostgreSQL-Gate.

Die autorisierte bestehende Installation wurde anschließend vollständig gesichert, isoliert wiederhergestellt und migriert. Native Windows-Builds wurden gestartet; Anmeldung, exakte Frontendbytes, zwölf API-/Aktenprüfungen, acht tatsächliche Originaldownloads je Lauf, anonymer Dateizugriff 401 und Rangezugriff 206 wurden geprüft. In beiden aktualisierten Beständen bestand der tatsächliche Browser jeweils 13/13 Prüfungen mit 18 Screenshots, keinen Browser-/API-5xx-Fehlern und bestätigter Bereinigung der temporären privaten Ansichten/Favoriten/Entwürfe. Fachliche Datensätze wurden dabei nicht gespeichert.

Die Umstellung machte einen Windows-Konsolefehler mit CP1252 und Unicodepfeilen sichtbar. `b839fe44` schützt die Konsolenkopie, während das UTF-8-Startprotokoll den Originaltext erhält. Neun gezielte Launcher-/Runtime-/Konsolefälle bestanden; der native Probestart bestätigt vollständiges Unicode im Log ohne Loggingfehler. `ccfd6135` korrigiert ausschließlich die Typisierung der Teststreams; `04021da5` wartet im bestehenden Dialogtest auf die tatsächliche Fokusrückgabe. Der gezielte Parteienlauf besteht 14/14. Eine frühere Matrix scheiterte an den Testtypen, die nächste an der vorzeitig geprüften Dialogsichtbarkeit; diese Erstläufe werden nicht nachträglich als grün umbenannt.

Die endgültige Matrix und der tatsächliche finale installierte Build stehen im Abschlussbericht `C:\Users\matth\Documents\ImmoManager-Sicherungen\20261015-QoL\DEPLOYMENT_COMPLETE_20261015.json`. Verwende zusätzlich den aktuellen GitHub-Lauf des genauen Commits; ein alter grüner Lauf ist keine Freigabe deines zukünftigen Entwicklungsstands. Die vier zuletzt beauftragten Bedienpakete und die Schnittstellen-Restarbeiten in dieser Übergabe sind noch zu entwickeln, keine bereits ausgelieferten Funktionen.

**Abgeschlossener Endstand:** Commit `04021da57e009419ae8d07346ad890fdabad6533` ist gepusht und GitHub-Lauf `38798953019` ist vollständig erfolgreich: `https://github.com/matthiasalexrsr/ImmoManager-Pro/actions/runs/38798953019`. Frontend 574/574; Backend in allen vier Varianten jeweils 2.083 bestanden/103 bedingte Skips; PostgreSQL 86/86 ohne Skip; Container-Systemtest und Deploymentfreigabe erfolgreich. Der finale native Code läuft auf 8765 und 8000 mit Schema `b82d5fa03147`. Beide endgültigen Installationen bestanden erneut je 13/13 Browserprüfungen ohne Skip oder Browser-/API-5xx-Fehler; private Testeinträge sind bereinigt. Die Hauptvorschau wurde zusätzlich mit vollständig abgewarteten Ladezuständen aufgenommen. Der visuelle Restbefund zu langen Überschriften/Karten ist oben ausdrücklich als Folgearbeit enthalten.

Die normale Hintergrundverarbeitung ist aktiv. Beide Bestände haben nach der Migration selbstständig eine vollständige Sicherung und eine isolierte Wiederherstellungsprobe ohne Warnung erfolgreich abgeschlossen. Die ursprünglichen 234 beziehungsweise 92 Uploads sind auch im Abschlussvergleich unverändert; die JWT-Geheimnisse wurden erhalten. Die temporären Prüfinstanzen auf 18765/18766 sind beendet. Aktueller Hauptprogrammordner: `C:\Users\matth\AppData\Local\Programs\ImmoManagerPro\releases\04021da5`. Der Rückweg ist in `RUECKWEG_UND_START.txt` im Sicherungsordner beschrieben; ein altes Programm vom 5. Oktober darf nicht einfach gegen das neue Schema gestartet werden.
