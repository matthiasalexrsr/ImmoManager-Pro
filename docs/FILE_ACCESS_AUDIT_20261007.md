# P1: anonymer Dateizugriff über /uploads

Unabhängige Prüfung am 7. Oktober 2026. Nur der lokale QA-Server `http://127.0.0.1:52195` und isolierte temporäre TestClients wurden geprüft. Keine externe Instanz, keine Sicherheitsänderung und keine Änderung von QA-Geschäftsdaten.

## Gesicherter Laufzeitbefund

Für jeden QA-Aufruf wurde ein neuer Python-urllib-Opener ohne Proxy- und Cookie-Handler verwendet. Die Requests enthielten weder `Authorization` noch `Cookie`. Geprüft wurde ausschließlich ein bereits bekannter, vom QA-Musterbestand erzeugter Dokumentpfad; keine Dateisuche oder fremde Datenabfrage.

| Anfrage ohne Anmeldung | Ergebnis |
|---|---|
| `/health` | 200; `environment=development`, `store_backend=SQLAlchemyStore`, `testversion=true`, Datenbank verbunden |
| `/api/v1/documents` | 401, Authentifizierung erforderlich |
| `/api/v1/files/download?key=<bekannter QA-Schlüssel>` | 401, Authentifizierung erforderlich |
| `GET /uploads/documents/<bekannte QA-Datei>.pdf` | **200**, `application/pdf`, 2.027 Bytes, Signatur `%PDF-`, `Accept-Ranges: bytes` |
| Derselbe GET mit `Range: bytes=0-31` | **206**, 32 Bytes, `Content-Range: bytes 0-31/2027` |
| `HEAD` auf dieselbe PDF | **200**, PDF-Metadaten zugänglich |
| Aus dem PDF-Namen abgeleiteter `_ocr.txt`-Pfad | **200**, `text/plain`, 446 Bytes |

SHA-256 der tatsächlichen QA-PDF: `2c3f09d38cb5d792f68b6263482d5f6591c448dd5ef313dd3ed907eb3dbc59b1`. Keiner dieser Dateiaufrufe erhielt `Cache-Control`. Inhalte, Dateiname und Personendaten werden hier nicht wiedergegeben.

Zwei zusätzliche Gegenproben liefen in frischen Python-Prozessen mit separaten temporären Datenverzeichnissen, zufälligem JWT-Secret, deaktivierter KI/Demobefüllung und Memory-Store. Ein synthetischer PDF-Marker und ein synthetischer OCR-Text wurden nur dort angelegt. Sowohl mit `IMMO_TESTVERSION=false` als auch `true` ergaben sich dieselben Werte: Dokumenten-API und API-Download **401**, beide `/uploads`-Dateien **200**. Diese Gegenprobe betrifft die Zugriffsentscheidung, nicht PDF-Rendering. Die temporären Verzeichnisse wurden durch `TemporaryDirectory` bereinigt.

## Ursache und Priorität

- `backend/app.py:226` mountet `UploadStaticFiles` bedingungslos außerhalb der geschützten API-Router. Die Registrierung hängt weder von Testversion noch Umgebung ab.
- `backend/services/upload_policy.py:52` ergänzt MIME-/Download-/Sandbox-Header, prüft aber keinen Benutzer und kein zugehöriges Fachobjekt. Diese Header schützen nicht vor Lesen der Datei.
- `backend/routing.py:73`, `:91`, `:115` verlangen Authentifizierung für die Dokumenten- und Datei-API. Der parallele statische Pfad umgeht diese Anforderung.
- `backend/config.py:140` und `backend/__main__.py:100` behandeln die Testversion als Daten-/Startkonfiguration; sie schalten die API-Authentifizierung nicht ab. Die gleiche statische Registrierung existiert auch für normale beziehungsweise Produktionskonfiguration. Eine externe Produktionsinstanz wurde nicht geprüft.

**P1: Ein erreichbarer Server liefert vertrauliche Uploads und OCR-Nebenprodukte an nicht angemeldete Clients aus, sobald deren Pfad bekannt ist.** Zufällige Dateinamen erschweren bloßes Erraten, ersetzen aber keine Zugriffsprüfung. Der Befund ist unabhängig vom neuen PDF.js-Renderer und bestand vorher. P0 ist anhand dieser Untersuchung nicht belegt: Die bestätigte Instanz ist lokal mit synthetischen Daten; eine aktuelle öffentliche Exposition oder ein tatsächlicher Datenabfluss wurde nicht festgestellt.

## Portfolio-/Objektberechtigung

Auch die geschützte API prüft beim Download eines bekannten Schlüssels nur die übergeordnete Anmeldung, keine zugehörige Immobilie: `backend/routers/files.py:212` liest den Storage-Key direkt; `:258` behandelt OCR ähnlich. Dokumentlisten/-details nehmen in `backend/routers/documents.py:24` beziehungsweise `:126` keinen Benutzerkontext entgegen. `UserRead` enthält keine Portfolio-/Objektzuordnung (`backend/models.py:972`).

Das ist von dem bestätigten anonymen Bypass zu trennen: `backend/permissions.py:3` und `backend/middleware.py:240` beschreiben ausdrücklich, dass **alle angemeldeten Nutzer lesen dürfen** und Rollen bisher Schreibrechte begrenzen. Es existiert in den geprüften Pfaden keine durchzusetzende Portfolio-Lesematrix. Deshalb wird hier keine bereits vorhandene Mandanten-/Objektisolation behauptet und keine konkrete fremde Portfoliozuweisung als verletzt ausgegeben. Falls getrennte Lesergruppen Produktanforderung sind, benötigen API und Dateien gemeinsam ein solches Berechtigungsmodell; ein Token vor dem Dateipfad allein stellt es nicht her.

## Kleiner, tragfähiger Integrationsplan

1. **P1 innerhalb der aktuellen Lesepolitik schließen:** eine zentrale authentifizierte Content-Route für lokale Dateien verwenden und die anonyme statische Auslieferung entfernen beziehungsweise standardmäßig sperren. Gespeicherte `/uploads/...`-Referenzen dürfen intern weiter auf Storage-Keys abgebildet werden. Schlüssel normalisieren, Pfadtraversal ablehnen, MIME-/Sandbox-/Attachment-Verhalten beibehalten. Nicht bloß einen zweiten sicheren Pfad ergänzen und den alten Bypass offenlassen.
2. **Auslieferungsvertrag erhalten:** geschützter GET/HEAD mit Byte-Range für PDFs, explizitem `inline`/`attachment`, sicherem Dateinamen und privater Cache-Politik. OCR-Nebenprodukte müssen dieselbe Zugriffsentscheidung erben. Die vorhandene `/files/download`-Route ist ein Ansatzpunkt, liest aber derzeit die komplette Datei in den Speicher und bietet noch nicht diesen Range-Vertrag.
3. **Gemeinsamen Frontend-Dateizugriff einführen:** app-eigene Storage-Referenzen von externen HTTP(S)-URLs unterscheiden. API-Authentifizierung nur an die vertrauenswürdige eigene Content-Route senden. PDF.js kann diese Route mit kontrollierten Headern und Abbruchsignal verwenden. Bilder benötigen einen authentifizierten Fetch mit verwalteter Blob-URL, solange die Anmeldung ausschließlich Bearer-Tokens verwendet. Der bestehende Download erhält denselben Zugriffspfad. „Original öffnen“ kann eine authentifiziert geladene Blob-Datei in einem neuen Tab öffnen; Revokation darf den Tab nicht vor dem Lesen abschneiden. Keine JWTs in URL-Queries, fremden URLs oder pauschalen `withCredentials`-Einstellungen.
4. **Alle direkten Dateioberflächen migrieren:** nicht nur FileViewer, sondern Fotos, Belegbilder, Vorschau-/Original-Links und OCR-Zugriffe. Sonst würde der Backend-Schutz funktionierende Bilder oder Originalöffnen brechen. 401/403 müssen verständlich sichtbar werden; eine ausgelaufene Sitzung darf keinen leeren Viewer erzeugen. Externe signierte URLs behalten ihren bisherigen CORS-/Öffnen-Vertrag ohne angehängte App-Credentials.
5. **Objektisolation gesondert und konsistent definieren:** Bei entsprechendem Produktziel `can_read_resource(user, resource)` zentral für Metadaten und Dateiinhalt einsetzen. Lokale Dateien müssen ihrem Dokument, Foto oder Buchungsbeleg zugeordnet werden. Noch nicht zugeordnete Uploads brauchen Ersteller-/Staging-Metadaten und eine definierte Zugriffspolitik. Die heutige globale Leseberechtigung darf dabei nicht versehentlich als fertige Portfolio-Prüfung bezeichnet werden.

Gezielte Abnahme: anonym GET/HEAD/Range/PDF/Bild/OCR abgewiesen; angemeldet dieselben Formate vollständig lesbar; deaktivierter/abgelaufener Zugang abgewiesen; kein zweiter Raw-Pfad; alter `/uploads`-Datensatz migrierbar; Originalöffnen/Download und PDF-Seitenwechsel funktionieren. Bei späterer Objektisolation zusätzlich zwei Lesergruppen mit disjunkten Objekten gegen Listen, Metadaten, Datei und OCR testen. Kein generischer Serverproxy für externe URLs.

Der PDF.js-Autor wurde vorab über den Befund und die künftige Auth-Fetch-Kompatibilität informiert. Dieser Audit hat keinen Produktcode verändert.

## Beschlossener begrenzter P1-Umfang (vor Implementierung)

Der Integrator hat nach Abgleich der tatsächlichen Frontendstellen Option B gewählt: ein ausschließlich für `GET`/`HEAD /uploads/...` ausgewertetes Upload-Cookie. Option A (Bearer-Contentclient, Blob-Bilder und umgestellte Originalaktionen) wäre möglich, würde aber native Links und mehrere Bildoberflächen umbauen. Option B erhält bestehende URLs, native Byte-Ranges und große PDFs ohne vollständige Blob-Zwischenkopie.

- Das Cookie enthält genau den bestehenden Access-JWT, hat dessen Ablaufzeit und keine zusätzliche Lebensdauer. Attribute: `HttpOnly`, `SameSite=Strict`, Host-only, `Path=/uploads`, bei HTTPS `Secure`. Keine Token in URLs; kein Domain-Cookie und keine Weitergabe an fremde Datei-Hosts.
- `/auth/login`, `/auth/refresh` und der bereits vor App-Inhalten abgewartete Bearer-Aufruf `/auth/me` setzen beziehungsweise aktualisieren das Cookie; `/auth/logout` löscht es mit identischem Pfad. Der bestehende JWT-Decoder, Revocation- und aktive Benutzercheck gelten bei jedem Dateiabruf. Ein ausdrücklich mitgeschickter ungültiger Bearer darf nicht auf ein gültiges Cookie zurückfallen.
- Nur der Upload-Auslieferer akzeptiert dieses Cookie, ausschließlich lesend. API-Routen erhalten dadurch keine Cookieauthentifizierung. Schreibrechte bleiben unverändert. Die bestehende globale Lesepolitik angemeldeter aktiver Benutzer wird erhalten; keine neue Objekt-/Portfolio-ACL oder entsprechende Garantie wird behauptet.
- Die Authentifizierung erfolgt vor Dateiauskunft einschließlich HEAD, Range und Fehlerantworten. Bestehender Pfadschutz, sichere Inline-Typen und Attachment/Sandbox-Verhalten bleiben bestehen. Uploadantworten inklusive Fehler erhalten `Cache-Control: private, no-store` und `Vary: Cookie, Authorization`.
- Alte `/uploads`-Referenzen sowie bisher nicht objektgebundene Uploads bleiben gemäß derselben globalen Lesepolitik für angemeldete Benutzer lesbar. Es werden weder Dateien umbenannt noch Daten migriert. Das offene spätere Objektberechtigungsmodell bleibt von diesem P1-Paket getrennt.

Frontend-Inventar: `FileViewer` ist gemeinsamer Einstieg aus Documents, PartyWorkspace, PropertyDetail und Bookings; `PartyDocuments` benutzt den zentralen Downloadhelper; `PhotoDropZone` verwendet direkte Bild-URLs. `Statements` reicht Uploadreferenzen an die geschützte OCR-API weiter. Weitere produktive direkte Dokument-/Fotolinks wurden in `frontend/src` nicht gefunden. Der rohe OCR-Sidecar unter `/uploads` ist Teil des Bypasses; die vorhandene `/api/v1/files/ocr-text`-API ist bereits Bearer-geschützt.

Nach dem PDF4-Commit wird eine schmale Sessionvorbereitung für vertrauenswürdige eigene Upload-URLs an Anzeige/Originalöffnen/Download vereinbart: vorhandener `/auth/me`-Aufruf mit bestehendem Tokenrefresh, bevor neue Dateiaktionen starten. Fremde HTTP(S)-Dateien lösen keine App-Tokenweitergabe aus. Lange offene PDFs benötigen nach abgelaufener Sitzung einen sichtbaren Wiederholpfad. Die Dateien des PDF4-Autors werden bis zu dessen Übergabe nicht verändert.

Regressionen zuerst: anonymes PDF/Bild/OCR GET, HEAD und Range; gültiger Bearer und Cookie; Ablauf, Refresh-Token statt Access, Revocation und deaktivierter Benutzer; ungültiger Bearer trotz gültigem Cookie; API bleibt mit Cookie allein 401; Login/Me/Refresh/Logout-Attribute und exakte Ablaufbindung; Download-/Inline-/Sandbox-/Range-/Traversalschutz und private Fehlerantworten. Alle Testprozesse erhalten frische isolierte Datenpfade. Unabhängiger Review und echte QA erfolgen anschließend durch den Integrator.

## Backend-Implementierung und verifizierter Stand

Der vorhandene `UploadStaticFiles`-Mount authentifiziert jetzt vor Dateisuche und übernimmt weiterhin Starlettes Pfad-/Symlinkschutz, GET/HEAD und native Byte-Ranges. `backend/services/upload_access.py` kapselt ausschließlich die Upload-Cookieausgabe und deren lesende Prüfung; die bestehende synchrone Benutzer-/JWT-Prüfung läuft im Threadpool. Ein vorhandener Authorization-Header verhindert jeden Cookie-Fallback, auch bei leerem oder falschem Authentifizierungsschema. Die API-Abhängigkeiten wurden nicht um Cookieauthentifizierung erweitert.

`login`, `refresh` und das Bearer-geschützte `me` setzen den unveränderten Access-JWT als `immo_upload_access`; dessen signierte Ablaufzeit ist das Cookie-Expires, ohne zusätzliche Max-Age. `logout` widerruft die übermittelten Tokens vor der Erfolgsantwort und löscht das Cookie auch bei leerem Payload. Bereits bestehende direkte Aufrufe der Authfunktionen bleiben kompatibel. Wie zuvor gibt es keinen serverseitigen Begriff einer gesamten Browser-Sitzungsfamilie: Ein Logout kann nur übermittelte Tokens widerrufen. Parallele andere Tabs beziehungsweise separat ausgegebene gültige Tokens werden durch dieses Paket nicht global abgemeldet.

`Cache-Control: private, no-store`, `Vary: Cookie, Authorization` und `nosniff` werden direkt beim Response-Start ergänzt. Damit gelten sie auch für 304, Auth-/Pfad-/Methodenfehler sowie von `FileResponse` intern erzeugte Rangefehler 400/416. Unerwartete Fehler vor Response-Start liefern eine generische private 500-Antwort und werden anschließend für das bestehende Serverlogging erneut ausgelöst. Inline-/Attachment-/Sandbox-Verhalten bleibt erhalten.

Verifikation mit Python 3.12 in je einem frischen temporären Datenverzeichnis, separater SQLite-URL, zufälligem JWT-Secret, Memory-Store, deaktivierter KI und Demobefüllung:

| Lauf | Ergebnis | Bedeutung |
|---|---|---|
| Neue Regressionen vor Produktänderung | 27 fehlgeschlagen, 49,16 s | Anonymer Bypass und fehlender Cookie-Lebenszyklus reproduziert |
| Erster grüner Uploadlauf | 42 bestanden, 44,00 s | 27 neue Regressionen plus 15 vorhandene Uploadpolicytests |
| Erweiterte Auth-/Dateikombination | 90 bestanden, 59,02 s | Zusätzlich gelöschte Nutzer, leere Abmeldung, Bearer-Priorität und bedingter Abruf nach Widerruf |
| Zusätzliche konkrete 500-Regression vor Korrektur | 1 fehlgeschlagen, 3,72 s | Fehlendes Cache-Control bei unerwartetem Fehler nachgewiesen |
| Abschließende unveränderte Kombination | **91 bestanden, 62,26 s** | 32 Uploadauth-, 15 Uploadpolicy-, 38 bestehende Auth- und 6 Dateivertragstests |

Aufruf des Abschlusslaufs: `python -m pytest backend/tests/test_upload_auth.py backend/tests/test_upload_policy.py backend/tests/test_auth.py backend/tests/test_files_router.py -q`. Zwei bekannte Deprecation-Warnungen betreffen Starlettes httpx-Testclient und den bisherigen HTTP-413-Konstantennamen. `git diff --check` für die geänderten bestehenden Backenddateien ist sauber. Der unabhängige statische Review meldete für dieses Backendpaket einschließlich 500-Pfad keinen P1/P2-Befund.

Der erste Teststart hatte einen falschen Testimport (`jose` statt des vorhandenen `jwt`/PyJWT) und brach vor Sammlung ab; dies wurde ausschließlich im neuen Test korrigiert und zählt nicht als RED-Nachweis. Die oben aufgeführten RED-/GREEN-Läufe erfolgten danach. Laufprotokolle liegen in `.superpowers/sdd/COMPETITIVE_20261007/upload-auth-*.log`.

Die Frontend-Sessionvorbereitung einschließlich sichtbarer Logout-/Retryfehler wird im getrennten Integrationspaket umgesetzt. Erfolgreiche Browserabmeldung setzt eine erfolgreiche Serverantwort voraus, weil JavaScript das HttpOnly-Cookie bei Netzfehlern nicht selbst löschen kann. Reale HTTP-/Browserabnahme und unabhängige Backend-Gegenproben sind an den Integrator übergeben; dieses Backendprotokoll behauptet deren Abschluss nicht. Produktionsdateien, vorhandene Uploadreferenzen und Daten wurden nicht migriert oder umbenannt.

## Grenze bei mehreren Diensten auf einem Host

Hostgebundene Cookies sind im Browser nicht zusätzlich an eine Portnummer gebunden. `SameSite=Strict` ändert diese Eigenschaft nicht. Für den privaten Server soll die Anwendung deshalb einen eigenen HTTPS-Hostnamen hinter dem vorhandenen Reverse Proxy erhalten, wenn andere Dienste unter demselben Servernamen betrieben werden. Gegenseitig nicht vertrauenswürdige Dienste dürfen keine sicherheitsrelevanten Cookies unter einem gemeinsamen Hostnamen verwenden. Das ist eine Grenze des Cookievertrags, kein hier nachgewiesener Datenabfluss. [RFC 6265, Abschnitt 8.5](https://www.rfc-editor.org/rfc/rfc6265.html#section-8.5).

Der JavaScript-Helfer gibt keine Bearer-Header an fremde Dateiquellen weiter. Diese Zusicherung bedeutet ausdrücklich keine Portisolation von automatisch durch den Browser gesendeten Cookies.
