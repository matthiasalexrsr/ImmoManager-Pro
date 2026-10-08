# Konkurrenzvergleich und durchgängige Akten – Implementierungsplan

> Agenten verwenden subagent-driven-development beziehungsweise executing-plans mit unabhängiger Schlussprüfung. Basis: `bf57f5ee` im bestehenden isolierten Arbeitszweig. Keine Rücksetzung auf ältere Projektkopien.

## Spezifikation und Entscheidung

Der Benutzer verlangt eine intensive Prüfung von vermieter1.de und WISO Hausverwalter, konkrete Funktions-/Bedienlücken und autonome Weiterentwicklung. Offizielle Quellen, tatsächliche Beobachtungen und Codebefunde werden getrennt dokumentiert. Frühere separate Entwicklungsstände gelten nicht als im aktuellen Produkt verfügbar. Die bestehende Freigabe zur autonomen Umsetzung deckt die folgenden reversiblen Verbesserungen ab.

Ziel der ersten Umsetzung: Von einem konkreten Objekt oder Prüfhinweis ohne erneute globale Suche zum zugehörigen Datensatz und Originalbeleg gelangen. Ladeprobleme und inzwischen verschwundene Einträge bleiben eindeutig erkennbar. Vorhandene Fachregeln, Rollen, Dokumentvorschau und Formulare werden wiederverwendet. Keine neue parallele Buchführung oder ungeprüfte Änderung von Abrechnungsregeln.

Alternativen: Eine rein optische Umgestaltung behebt die nachgewiesenen Ablaufbrüche nicht. Eine sofortige Übernahme aller vermarkteten Konkurrenzfunktionen würde ungeprüfte neue Datenmodelle vermischen. Daher zuerst drei vollständig prüfbare Ablauf-/Fehlerkorrekturen; der umfassende Vergleich priorisiert anschließend größere Pakete.

## Paket 1 – Operative Immobilien- und Einheitenakte

**Dateien:** `frontend/src/pages/PropertyDetail.jsx`, `UnitOverview.jsx`, neue gezielte Tests und bei Bedarf eng begrenzte eigene CSS-Datei.

- [x] Verzögerte Antwort eines vorherigen Objekts und Teilfehler reproduzieren. Laden abbrechen beziehungsweise Antworten nach Objektwechsel verwerfen; eindeutig zugehörige Daten zeigen. Fehler mit erneutem Laden statt falschem Leerbestand oder Null-Kennzahlen.
- [x] Einheitennamen in Übersicht, Tabelle und Finanzansicht auf `/units/:id` verlinken; in der Einheit den Rückweg zur tatsächlichen Immobilie `/properties/:id` anbieten. Tastaturfähige Links statt ausschließlich klickbarer Zeilen.
- [x] Direkt zugeordnete Dokumente in der Immobilienakte über den vorhandenen `FileViewer({fileUrl,title,onClose})` öffnen. Fehlende/ungültige Dateiverweise erkennbar machen; Dokumentdatum und Typ aus den tatsächlichen Modellfeldern verwenden. Vorschau beim Objektwechsel schließen.
- [x] Aus Stammdaten berechnete Mieten ausdrücklich als Plan-/Stammdatenwerte kennzeichnen. Keine Behauptung, daraus tatsächliche Vertragsforderungen oder Einnahmen abzuleiten.
- [x] Tests: Navigation, korrektes Dokument, fehlender Beleg, Leserzugriff, Fehler/Wiederholung, späte Antworten und Wechsel bei offener Vorschau. Browserprüfung auf 320/360/1440 Pixeln.

**Abgrenzung:** Kein neues Finanzaggregat, keine Vertragsbearbeitung im Dossier, keine Links mit unimplementierten Zielparametern.

## Paket 2 – Konkrete Buchungsprüfung und Originalbeleg

**Dateien:** `frontend/src/pages/ReviewList.jsx`, `Bookings.jsx`, `backend/services/review.py` und gezielte Frontend-/Backendtests; bei Bedarf eng begrenzte eigene CSS-Datei.

**Schnittstelle:** Für Buchungsprüffälle `link=/bookings?booking_id=<URL-kodierte ID>`. Die bestehende Route `GET /bookings/{id}` liefert den ausdrücklich ausgewählten Datensatz, unabhängig von einer geladenen Listenposition. Andere Prüffallarten behalten ihre vorhandenen Ziele.

- [x] Die Prüfliste trennt Laden, Fehler mit Wiederholung und tatsächlich leere Liste.
- [x] Buchungsprüffälle öffnen die identifizierte Buchung mit sichtbarem Kontext und Rückweg zur Prüfliste. Verschwundene/unzulässige IDs zeigen einen Fehler; keine andere Zeile ersatzweise öffnen. Wechselnde IDs und verspätete Antworten dürfen sich nicht vermischen.
- [x] Vorhandene Bearbeitung/Aufteilung mit bestehenden Rollen und Formularen nutzbar machen; Zielauswahl selbst verändert keine Buchung. Nach erfolgreicher Korrektur Daten neu laden. Konflikte/Fehler erhalten Nutzereingaben.
- [x] Belegaktion öffnet vorhandenes `receipt_url` über denselben FileViewer. Leere oder ungültige Verweise zeigen keine scheinbar erfolgreiche Vorschau. Kein neuer Upload-/Dokumentauswahldienst in diesem Paket.
- [x] Buchungsladefehler und fehlgeschlagene Zuordnungsladung sichtbar machen; keine scheinbar vollständig zugeordneten oder leeren Bestände aus Fehlern ableiten.
- [x] Tests: exakter Prüffall-Link, direkter Zugriff jenseits der Listenposition, unbekannte ID, Navigation während Anfrage, Beleg öffnen, Leser ohne Schreibaktion, Ladefehler/Wiederholung und Formulardaten bei Fehlern. Echtes Browser-Szenario Prüfliste → Buchung → Beleg und Rückweg.

## Paket 3 – Kontakt- und Adresssuche korrigieren

**Dateien:** `backend/routers/search.py`, gezielte Regressionen in `backend/tests`.

- [x] Kontakt mit Vorname/Nachname/Firmenname und Immobilie mit tatsächlicher `address_line` anlegen; Suche nach Namen/Firma/Adresse muss die erwarteten IDs und lesbaren Titel liefern. Erst den bisherigen Fehler nachweisen.
- [x] Suchfelddefinitionen mit den vorhandenen Modellen abgleichen; Kontaktanzeigen aus vorhandenen Namen/Firma ableiten. Verfügbare semantische Immobilienindex-Felder entsprechend konsistent halten.
- [x] Bestehende Antwortstruktur und Rollenprüfung erhalten. Leere/nicht vorhandene optionale Namensbestandteile robust handhaben. Keine behauptete vollständige serverseitige Großbestandssuche in diesem Paket.
- [x] Zieltests in isoliertem Store und vorhandene Suchregressionen ausführen.

## Gemeinsame Abnahme

- Unabhängige Astra-Ultra-Prüfung aller Produktänderungen gegen diese Spezifikation und realistische Fehlerfälle.
- Gesamte Frontendtests, ESLint, Build; fokussierte Backendregressionen für geänderte Such-/Prüffallpfade. Nach Umfang zusätzliche Backendprüfung, keine unnötige Wiederholung unveränderter Million-Zeilen-Tests.
- Reale Browserprüfung auf separater Testdatenkopie. Vergleichsbericht mit Quellen, aktueller Funktionsmatrix, priorisierten größeren Paketen und expliziten Grenzen der externen Tests.
- Vorschau nach erfolgreicher Abnahme aktualisieren; bestehende Daten sichern und bewahren.

## Review-Fokus und Zuständigkeiten

| Schnittstelle / Paket | Entscheidung |
| --- | --- |
| Paket 1/2, FileViewer | Nur vorhandene Komponente verwenden, keine konkurrierenden Änderungen am gemeinsamen Viewer. |
| Paket 1/2, CSS | Eigene Bereichsdateien; kein gemeinsamer großflächiger Stylesheet-Umbau. |
| Paket 2, Review-Link/API | Backend erzeugt `booking_id`; Frontend lädt genau diese ID unabhängig von der globalen Liste. |
| Paket 3, API-Vertrag | Feldkorrektur erhält bestehende JSON-Schlüssel und Suchoptionen. |
| Fehlende oder veraltete Daten | Kein Erfolg durch Fallback auf leere Listen/Nullsummen; Tests für Retry und Objektwechsel. |
| Berechtigungen | Lesen erlaubt keine neue implizite Bearbeitung; Buttons nutzen bestehende Rollen. |

Recherche-Agenten arbeiten lesend; nach Übergabe erhält einer Paket 2. Der Akten-Agent implementiert Paket 1, der Integrator Paket 3 und Browserabnahme. Ein unbeteiligter Astra-Ultra-Agent prüft die gemeinsame Änderung. Der bestehende umfassende A–L-Auftrag bleibt darüber hinaus offen.

## Ergänzung aus der tatsächlichen Browserabnahme: PDF-Darstellung

Am 7. Oktober zeigte die PDF-Vorschau im integrierten Browser eine leere/dunkle Fläche. HTTP 200, MIME-Typ, Range-Antwort, striktes PDF-Parsing und unabhängige Poppler-/PDFium-Darstellung bestätigen eine gültige, erreichbare Datei. Der bestehende Betrachter verwendet allein ein natives `iframe`, ohne einen nachgewiesenen Renderzustand. Die genaue Ursache innerhalb des Browser-PDF-Renderers ist nicht bestätigt.

**Paket 4:** Den bestehenden FileViewer um einen lokal gebündelten PDF.js-Betrachter ergänzen. Ein bereits passender Originaldownload, Bildbetrachter, OCR-Text und Dialogbedienung bleiben gemeinsame Infrastruktur. Kein zusätzlicher Dokumentenspeicher und kein externer Renderingdienst.

- PDF.js aus dem offiziellen Paketregister, exakte Version und Lockdatei; Lizenz und Produktionsbuild prüfen. Worker und erforderliche Begleitressourcen werden lokal ausgeliefert, keine CDN-Abhängigkeit.
- Nur die aktuelle Seite rendern; beliebige Seitennummer, vor/zurück, Zoom und Breitenanpassung. Arbeits- und Speicherbudget pro Darstellung statt Begrenzung der Dokumenthistorie oder Seitenzahl.
- Laden, Rendern, beschädigte Datei, Schutz durch Passwort, Abbruch und Wiederholung haben eindeutige Zustände. Original öffnen/herunterladen bleibt verfügbar.
- Wechsel zwischen Dateien oder Seiten darf keine verspätete Darstellung zuordnen. Dokument-/Renderaufträge und Worker beim Schließen aufräumen.
- Tastatur und mobile Bedienung erhalten; Textzugang/OCR berücksichtigen. Keine PDF-Skripte oder unkontrollierten externen Aktionen ausführen.
- Abnahme: echte gültige PDF im integrierten Browser sichtbar; mehrseitige Navigation, lange Titel, schmale Ansicht, Fehler/Retry, schneller Wechsel und Download. Unit-/Integrationstests, unabhängiger Review, Produktionsbuild, anschließend Vorschau aktualisieren.

Diese notwendige Korrektur fällt unter den ausdrücklich erteilten Auftrag zur besseren Dokumenteneinsicht und autonomen Fehlerbehebung.

## Paket 5 – Direkten Dateizugriff schützen

Die unabhängige Prüfung bestätigte, dass bekannte lokale PDF-, Bild- und OCR-Pfade anonym ausgeliefert werden. [Befund und Gegenproben](FILE_ACCESS_AUDIT_20261007.md). Dieses bestehende Problem muss vor der Auslieferung der verbesserten Dokumenteneinsicht geschlossen sein.

- Den vorhandenen `/uploads`-Pfad nur nach derselben Prüfung von Access-Token, Widerruf und aktivem Benutzer wie die API freigeben. Vorhandene Dateireferenzen und native GET-/HEAD-/Range-Auslieferung erhalten; keine Vollkopie großer PDFs in einen zusätzlichen Browser-Blob erzwingen.
- Für Browser-Dateianfragen ein ausschließlich dort akzeptiertes HttpOnly-Cookie mit dem bestehenden Access-Token verwenden: hostgebunden, Pfad `/uploads`, SameSite Strict, Secure bei HTTPS, keine zusätzliche Gültigkeitsdauer. Anmeldung, Erneuerung und bereits verpflichtende Profilprüfung setzen das Cookie; Abmeldung entfernt es. Normale API-Schreibzugriffe akzeptieren weiterhin keine Cookie-Anmeldung.
- Vertrauliche Dateien und abgeleitete OCR-Texte mit `private, no-store` ausliefern. Authentifizierung vor Dateiexistenz-, Metadaten- und Range-Auswertung; kein Ausweichen von einem ungültigen Bearer-Token auf ein anderes Cookie.
- Abgelaufene Browser-Dateisitzung vor einer neuen Vorschau oder einem Download über den vorhandenen API-Erneuerungsweg aktualisieren. Keine Token in URLs und keine Weiterleitung von Zugangsdaten an externe Dateihosts.
- Regressionen für anonym, gültig, abgelaufen, widerrufen, deaktiviert, Refresh- statt Access-Token, Logout, Range/HEAD, OCR, Pfadtraversal, Cache und normale API-Rollen. Anschließend reale PDF-/Bildprüfung und unabhängiger Review.

Die gegenwärtige Policy erlaubt allen angemeldeten Nutzern das Lesen. Objektbezogene Leserechte fehlen im aktiven Zweig und werden mit Originalarchiv und API gemeinsam konsolidiert; dieses Paket behauptet keine Mandanten- oder Mieterisolation.
