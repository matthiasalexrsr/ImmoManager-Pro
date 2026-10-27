# Audit, Behebung und erste Integrationspakete von Codex

Stand 27. Oktober 2026, Branch `claude/dreamy-gauss-nmaxhn`, Runde 22. Codex hat vom 25. bis 26. Oktober auf dem Windows-PC des Benutzers gearbeitet, ausgehend von Runde 21 (`39f969d`), auf dem lokalen Branch `codex/integrated-workflows` (`94dd6a0`, nie gepusht). Diese Runde übernimmt ihn unverändert per Merge. Sieben additive Migrationen, ein Head (`f8a0124d6e9b`). Die Version bleibt `2.0.0-beta.1`.

Codex' ausführliche Berichte liegen nur auf dem PC im Codex-Ausgabeordner (`Auditbericht.md`, `Kommerzielle-Freigabe.md`, `Behebungsbericht.md`, `Integrationsbewertung.md`, `Integration-2026-10-26/Ergebnisbericht.md` mit Nachweisen und dem Windows-Testpaket). Im Repository stehen Betrieb und Rückfall in [INTEGRATION_RELEASE.md](INTEGRATION_RELEASE.md) und [INTEGRATION_MIGRATION.md](INTEGRATION_MIGRATION.md), die Lizenzfragen in [COMMERCIAL_RELEASE.md](COMMERCIAL_RELEASE.md) und das Hostingprofil in [HOSTING_ISOLATION.md](HOSTING_ISOLATION.md).

## Ablauf

1. **Audit von Runde 21:** elf belegte Anwendungsfehler (vier mit hoher Priorität), dazu zehn Punkte zu Abhängigkeiten, Lizenzen und Auslieferung.
2. **Behebung** (`42ba24d`): die elf Fehler und fünf weitere, die dabei auffielen.
3. **Bewertung der drei Masterreports** des Benutzers („Immobilienverwaltung 2035“, „Real Estate Operating System 2035“, „Immobilienverwaltung 2030“): zusammengefasst zu 26 Arbeitspaketen. Empfehlung: zuerst ein verlässliches Produkt für die Mietverwaltung, kein Technologiewechsel.
4. **Umsetzung der ersten Pakete** (zwölf Commits): E-Rechnungen, Zahlungsfreigaben, Arbeitscockpit, Datenübernahme und Kundenexport, Portale, Datenschutz, Quellenbelege.

## Behobene Fehler

| Nr. | Fehler | Korrektur |
|---|---|---|
| F01 | Die Anmeldung bot keinen zweiten Faktor an | Das Formular fragt nach dem sechsstelligen Code; ein falscher Code lässt sich korrigieren |
| F02 | Ein aktiver TOTP-Schlüssel ließ sich durch erneutes Einrichten ersetzen | Einrichten bei aktivem Schlüssel wird abgewiesen; Ein- und Ausschalten prüfen den erwarteten Zustand |
| F03 | Gespeicherte KI-Lesevorgänge blieben nach Rechteentzug lesbar | Rechte, Quellen, Kontext und Dubletten werden bei jedem Zugriff neu geprüft |
| F04 | Eine eingelesene Gutschrift wurde als Rechnung übernommen | Belegart und Bezug auf die Ursprungsrechnung werden übernommen und geprüft |
| F05 | Fälligkeit und Leistungszeitraum gingen beim Einlesen verloren | werden übernommen; eine erkannte IBAN bleibt ein markierter Hinweis |
| F06 | Eine Wiederholung nach verlorener Antwort erzeugte einen neuen Schlüssel mit alter Revision | dieselbe Nachricht behält Schlüssel und Revision |
| F07 | Lange Windows-Pfade verhinderten Sicherung und Wiederherstellung | auch Prüfsummen, Schlüsseldateien, PDF-Arbeitsordner, Vorlagen und DATEV |
| F08 | Der zentrale Fehlerhandler verlor Kopfzeilen wie `X-2FA-Required` | Kopfzeilen bleiben erhalten |
| F09 | Eine unbekannte Einlesestelle gab HTTP 500 | jetzt 404 |
| F10 | „Neu“ überschrieb die Vorbelegung aus dem Assistenten | eindeutige Übergabe an das Formular |
| F11 | Die PDF-Ansicht lag hinter der Parteienkarte | Ebenen und Fokus korrigiert |
| F12 | Der Vertragsassistent machte aus 100.50 den Betrag 10.050,00 | Beträge mit Dezimalpunkt und deutscher Schreibweise werden richtig gelesen |
| F13 | Vertragsfelder wurden als HTML gedeutet; ein Bild-Tag ließ den Server eine Adresse abrufen | Eingaben werden als Text behandelt |
| F14 | Vorschau und beide PDF-Wege des Vertrags hatten unterschiedliche Texte | beide PDFs verwenden den Text der Vorschau |
| F15 | Eine unvollständige Sicherung meldete auf der Kommandozeile Erfolg | der Rückgabecode zeigt das tatsächliche Ergebnis |
| F16 | Der FastAPI-Adapter des Vertragsassistenten nutzte eine veraltete Vorlagen-Signatur | aktuelle Signatur |

Dazu: AnyIO 4.14.2 und Certifi 2026.10.19 (veröffentlichte Sicherheitsmeldungen), pip-audit prüft die tatsächlich installierten Pakete aus einer getrennten Umgebung, der optionale Editor wird mitgeprüft, die Laufzeitabhängigkeiten stehen in `requirements-runtime.txt`. Dokumentwerkzeuge (PyMuPDF, SuperDoc, DOCX Engine) gehören nicht ins Kernpaket; ein Build mit ihnen braucht den ausdrücklichen Zweck `validation` oder `licensed` mit Rechtefreigabe (`tools/build_profile.py`).

## Neue Funktionen

| Bereich | Wo | Was |
|---|---|---|
| E-Rechnungen | Rechnungsprüfung → „E-Rechnungseingang“ | XRechnung und ZUGFeRD (EN 16931), geprüft mit KoSIT 1.6.3 (XRechnung 3.0.2) und Mustang 2.26.0 auf mitgelieferter Java-21-Laufzeit. Original, gelesene Daten und Prüfbericht getrennt; gültig, Warnung, ungültig und technischer Fehler unterscheidbar; Übernahme nach Bestätigung, atomar und wiederholbar. |
| Zahlungsfreigaben | Rechnung → Bankdaten | Empfänger versioniert; die Freigabe bindet Betrag, Empfängerstand und Rechnungsstand. Vier Augen als Vorgabe; Einzelbenutzermodus nur ausdrücklich durch den Eigentümer, dann mit TOTP-Code, Begründung und Bankgegenprüfung je Freigabe. Keine Zahlung durch das Programm. |
| Arbeitscockpit | Arbeitszentrale | nächster Schritt, Blocker, Zuständigkeit, Wartegrund und Fristgrundlage aus den Fachdaten; Rechnung, Schaden und Mieterwechsel als durchgehende Abläufe |
| Datenübernahme | Einstellungen → „Datenübernahme / Kundenexport“ (Eigentümer) | sechs CSV-Vorlagen, Spaltenzuordnung, Dublettenbericht, Vorschau ohne Schreiben, Mengen- und Betragsabgleich; keine Teilübernahme bei Konflikten |
| Kundenexport | ebenda | Daten, Beziehungen, Originale und Prüfsummen, ohne Zugangsdaten; ein Wiederimport erweckt alte Zugänge und Freigaben nicht |
| Portale | Einstellungen → „Mieter- und Eigentümerportale“ | eigene externe Konten und Sitzungen, einmalige befristete Einladungen, nur veröffentlichte Dokumentfassungen, eigene Vorgänge und Schadensmeldungen mit Fotos. Aus, solange `PORTAL_ENABLED` nicht gesetzt ist; braucht HTTPS (`PORTAL_PUBLIC_URL`). |
| Datenschutz | Einstellungen → „Datenschutz / Aufbewahrung“ | Sperren, Aufbewahren, Löschen, Betroffenenanfragen, eigenes Journal; nach einer Wiederherstellung bleiben Portal, Suche und KI bis zum Abgleich gesperrt |
| Quellen | KI-Antworten, Finanzberichte | Dokumentfassung, Hashes und Fundstelle; Definition, Datenstand und Grenzen eines Berichts |
| Lizenzen | „Lizenzen und Quellarchive“, `/api/v1/legal` | Lizenztexte und Quellarchive der mitgelieferten Fremdbestandteile |

## Paket, Docker und CI

- Das Windows-Paket enthält Validatoren und Java-Laufzeit samt Lizenztexten und wird rund 400 MB groß. Die Validatoren werden nur beim Build geladen und per SHA-256 geprüft (`tools/prepare_e_invoice.py`); das Programm lädt keinen Code nach.
- Ein Release-Tag verlangt eine Herausgebersignatur (`scripts/sign_release.ps1`, Secrets `WINDOWS_SIGNING_PFX_BASE64`, `WINDOWS_SIGNING_PASSWORD`, Variable `WINDOWS_TIMESTAMP_URL`) und erhält eine Attestierung. Ohne Tag entsteht ein unsigniertes Prüfpaket.
- Docker baut das Frontend selbst und läuft als UID/GID 10001. Compose verlangt `POSTGRES_PASSWORD` und `JWT_SECRET_KEY` und veröffentlicht nur den Anwendungsport auf 127.0.0.1; PostgreSQL hat keinen Hostport mehr.
- CI: neuer Job „Windows native path and recovery regressions“, Browser-Suite `auth-party`, PostgreSQL-Schritt für Zwei-Faktor und gespeicherte Lesevorgänge, Asset-Profilprüfung im Frontend, npm-Audit des optionalen Editors.

## Beim Zusammenführen

- Der Merge lief ohne Konflikte: Codex' Branch enthält Runde 21 vollständig, auf `claude/dreamy-gauss-nmaxhn` kam seither nur die Übergabedatei hinzu.
- Korrigiert: `scripts/e2e_smoke.sh` setzt für den Lauf zufällige `POSTGRES_PASSWORD` und `JWT_SECRET_KEY`. Ohne sie bricht `docker compose` nach Codex' Änderung schon beim Start ab.
- Geprüft: Der gepinnte Hash der Linux-Java-Laufzeit für das Docker-Image entspricht der von Adoptium veröffentlichten Prüfsumme. Die Python-Quellen enthalten keine f-String-Syntax, die erst ab Python 3.12 gilt (CI und Docker laufen auch mit 3.11).
- Nicht übernommen: Codex' unfertige, nicht committete Änderungen an Docker, nginx und `tools/validate_hosting_config.py` in seinem Checkout.

## Geprüft

Lokal unter Windows 11 mit Python 3.14 und Node 24.21.0 (die CI prüft zusätzlich Python 3.11 und 3.12):

- Backend: ruff, mypy (855 Dateien), bandit (keine Befunde ab mittel), pip-audit (keine bekannten Schwachstellen), Import der App.
- Backend-Tests vollständig: Speicher-Store 3.894 bestanden, 151 übersprungen, Abdeckung 87,9 %; SQL-Store 3.898 bestanden, 147 übersprungen. In beiden Läufen schlug nur ein Windows-Test fehl, weil der für die Prüfung gekürzte PATH kein `powershell` enthielt; mit PowerShell im PATH besteht er (alle 24 Tests der Datei auf SQL).
- Frontend: npm audit (Hauptfrontend und optionaler Editor ohne Treffer), ESLint, 1.410 Vitest-Tests in 194 Dateien, Asset-Profilprüfung, Build.
- Browser aus dem Quellstand: die neue Suite `auth-party` (Zwei-Faktor-Anmeldung, Parteiakte, Vertrags-PDFs) sowie daily, interfaces, qol, application, operations, office, reports, reading, assistant, PDF-Werkzeugleiste, Abrechnungsschreiben und Aufgabenkosten – alle grün. Die Dokument-Suite lief lokal nicht (sie braucht den Build mit den optionalen Dokumentwerkzeugen).

Codex' eigene Nachweise am selben Code: Speicher- und SQLite-Backend vollständig (zwei Fehler im Speicherlauf danach behoben und gezielt nachgeprüft), 123 PostgreSQL-Gateprüfungen und 161 native Fachprüfungen, 47 Browser-Prüfketten am fertigen Windows-Paket, 16 neue integrierte Browserketten, sieben Windows-Betriebsketten (Upgrade, Sicherung, Wiederherstellung, Kundenimport).

## Offen

- **Freigaben außerhalb des Codes:** Herausgeberzertifikat für die Signatur; echte Zugänge für Bank, Nachrichtenversand und KI; Einrichtung und Abnahme des Linux-/Proxy-Hostings; Nutzungsrechte für die optionalen Dokumentwerkzeuge (PyMuPDF, SuperDoc, DOCX Engine).
- **Sporadischer Ladefehler:** In zwei frühen Browserläufen von Codex scheiterte einmal das Nachladen eines Programmmoduls. Spätere Läufe und Codex' Diagnose vom 27.10. (Transportvergleich, 40 Antwort-Hashes) zeigten ihn nicht mehr. In Runde 23 zeigte die Suite „application“ unter Last denselben Fehler bei einem Seitenwechsel: Der Wechsel bricht das Nachladen ab, und die Fehleranzeige meldete das. Seitdem gilt ein beim Verlassen der Seite abgebrochenes Nachladen nicht mehr als Fehler (`frontend/src/buildRecovery.js`). Ob das Codex' Fall vollständig erklärt, ist nicht bewiesen.
- **Bestandsdaten:** Früher mit falschem Belegtyp oder ohne Fälligkeit gespeicherte Belege erkennt das Programm nicht von selbst; sie sind anhand der Originale zu prüfen. Gespeicherte Lesevorgänge ohne neuen Berechtigungsnachweis müssen neu eingelesen werden.
- **Hauptinstallation:** läuft weiter auf `0c6d633`; die Runden 18–22 sind dort nicht eingespielt.
