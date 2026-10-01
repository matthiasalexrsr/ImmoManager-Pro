# G03: eigene Sitzungen und Refreshrotation

Neue erfolgreiche Passwort-/TOTP-Anmeldungen erhalten ein Access-/Refreshpaar mit `sid` und `session_version=1`. Die Antwort behält die bisherigen drei Felder `access_token`, `refresh_token`, `token_type`. Authentifizierung und Portfolio-/Rollenrechte werden weiterhin frisch aus dem Server gelesen; Tokens enthalten keine kopierten Berechtigungen. Die Datenquelle ist die tatsächliche Auth-Sessionfactory, niemals ein aus der Geschäftsdatendatenbank oder einem Fallback abgeleitetes Konto.

`auth_sessions` speichert Familie, Benutzer-ID, Erzeugung/letzte Nutzung, festen Refreshablauf, Widerruf und grobe Browser-/OS-Beschreibung. Keine vollständigen User-Agents, IP-Historien, Raw-Tokens oder Credentials. `auth_refresh_tokens` speichert ausschließlich SHA256-Fingerprints und Verbrauchszeitpunkte; früher verbrauchte Generationen bleiben für die Familien-Lebensdauer erkennbar. Die Fingerprints sind keine verwendbaren Bearer-Tokens.

SQLite erwirbt vor dem ersten Lesen einer Mutation `BEGIN IMMEDIATE`. PostgreSQL sperrt die Benutzerzeile für Erstübernahme/Benutzerstatus und anschließend die Familienzeile. Zwei parallele Rotationen desselben Tokens führen zu genau einem ausgegebenen Paar; der zweite Versuch erkennt Verbrauch und commitet den Familienwiderruf vor seiner 401-Antwort. Bereits ausgegebene Access-Tokens dieser Familie scheitern anschließend ebenfalls. Es gibt kein erneutes Ausgeben eines Tokens als Replay-Erfolg. Datenbankfehler ergeben 503 und keinen Memory-Fallback. Ein fehlgeschlagener Commit verbraucht den bisherigen Refresh-Token nicht.

Ein Access-Token bleibt während einer normalen Rotation verwendbar, bis sein ursprünglicher Ablauf erreicht ist. Familienwiderruf, Ablauf oder fehlender Familienstand sperren ihn. Erfolgreiche Verwendung aktualisiert `last_used_at` höchstens einmal pro Minute; Login und Rotation schreiben ihre tatsächliche Aktivität. Gerätemerkmale stammen aus einem untrusted User-Agent und sind nur Beschreibung, kein Identitätsnachweis. Ohne SQL-Speicher ist das gleiche Zustandsmodell unter dem Benutzer-RLock nur für Entwicklung/Tests verfügbar; API und Oberfläche benennen diese fehlende Persistenz ausdrücklich.

## Übergang

- Bestehende gültige Access-JWTs ohne Familienclaims bleiben ausschließlich bis zu ihrem ursprünglichen Ablauf gültig. Sie lassen sich rückwirkend keiner zuverlässigen Geräte-/Refreshfamilie zuordnen. Die Oberfläche behauptet deshalb keine vollständige Erfassung dieser Tokens.
- Ein noch gültiger, zuvor nicht widerrufener Legacy-Refresh-JWT wird einmalig anhand seines eindeutigen Fingerprints in eine dauerhafte Familie übernommen. Deren Ablauf ist der ursprüngliche Tokenablauf und wird nicht verlängert. Auch Wiederverwendung des ursprünglichen Legacy-Tokens widerruft die übernommene Familie.
- Bereits vor dem Upgrade gespeicherte RevokedToken-Fingerprints werden weiterhin geprüft. Ungültige, abgelaufene, typenverwechselte oder unvollständige Familienclaims werden nicht zu Legacy-Tokens heruntergestuft. Die bestehenden direkten Tokenhelper bleiben explizite Legacyhelpers für interne Kompatibilität; neue HTTP-Anmeldungen verwenden sie nicht.
- Der Refresh einer bereits vollständig authentifizierten Anmeldung benötigt keinen neuen TOTP-Code; neuer Login bewahrt die bestehende TOTP-Prüfung und reserviert vor erfolgreicher Prüfung keine Familie.

Der Wiederverwendungsschutz orientiert sich an [RFC 9700 §4.14.2](https://www.rfc-editor.org/rfc/rfc9700.html#section-4.14.2), Signatur-/Typprüfung an [RFC 8725 §3](https://www.rfc-editor.org/rfc/rfc8725.html#section-3). Dies ist die bestehende private JWT-Anwendung, kein neuer OAuth-Provider oder Zertifizierungsversprechen.

## Eigene API und Integration

- `GET /api/v1/auth/sessions?offset=0&limit=25`: paginierte eigene Familien einschließlich beendeter/abgelaufener Stände; `current_session_id`, `legacy_current`, `persistent`. Keine andere Benutzer-ID als Clientparameter, kein anderer Benutzerbestand und keine Tokenfingerprints in Antworten.
- `POST /api/v1/auth/sessions/{id}/revoke`, ausschließlich `{"confirmed":true}`: eigene Familie beenden, auch die aktuelle. Fremde oder unbekannte IDs 404; unauthentifiziert 401; Readonly darf eigene Sicherheit verwalten. Wiederholter Widerruf über eine andere gültige eigene Sitzung verändert den ursprünglichen Widerruf nicht.
- Logout mit einem gültigen neuen Access- oder Refresh-Token beendet seine ganze Familie. Legacy-Logout erhält den bisherigen Einzel-Tokenwiderruf.
- ORM-Metadaten, Alembic-Environment, additiver `create_tables`-Helper und enger Middleware-Selbstverwaltungspfad sind angebunden. Upgrade `s1a2b3c4d5e6 → t1a2b3c4d5e6`; befüllter Downgrade scheitert vor DDL, weil er Replay-/Widerrufsschutz entfernen würde.
- Unterstützte Geschäfts-JSON-Teilimporte erhalten die unabhängigen Auth-Tabellen unverändert und importieren keine Sitzung. Vollarchive enthalten beide Tabellen.

## Vollrestore vor Appstart

Ein normaler Neustart erhält Familien und verbrauchte Fingerprints. Ein älterer vollständiger Datenbank-Snapshot kann spätere Sicherheitsentscheidungen zurückrollen. Ein Epochwert in derselben wiederhergestellten DB oder Konfiguration kann ebenfalls zurückrollen und löst diese Grenze allein nicht.

Die Offline-SQLite-Vollwiederherstellung und der private PostgreSQL-Restore wenden deshalb **vor dem Start aller Schreiber** `backend.db.session_models.invalidate_restored_sessions(connection)` auf ihre neue Zieldatenbank an und setzen einen **neuen JWT-Signierschlüssel**. Der DB-Hook beendet sämtliche restaurierten aktiven Familien mit `database_restore` und behält Verbrauchs-/Widerrufshistorie. Schlüsselrotation sperrt zusätzlich noch gültige Legacy-Tokens und ältere, im Snapshot fehlende Einzelwiderrufe. PostgreSQL-Zugangsdaten und unabhängige Feldverschlüsselungs-/Indexschlüssel bleiben erhalten. Alte JWT-basierte IBAN-Ciphertexte behalten bei tatsächlichem Bedarf den ursprünglichen Schlüssel ausschließlich im expliziten Entschlüsselungsring. Der Hook läuft niemals beim normalen Start.

SQLite veröffentlicht erst nach dem erfolgreichen Sicherheitsabschluss seine vollständig vorbereitete Kopie. PostgreSQL erzeugt die neue geschützte Zielkonfiguration vor den Dockeraktionen und startet die App nur nach dem bestätigten Offline-Widerruf. Ein Fehler ergibt keinen bestätigten Restore; das ausdrücklich neue PostgreSQL-Ziel bleibt für die Untersuchung erhalten. Geschäfts-JSON-Teilimporte sind keine Vollwiederherstellung und verändern diese Familien nicht.

## Browser

Die eigene Sitzungsoberfläche zeigt tatsächliche paginierte Belege, genaue Zustände und eine gesonderte Bestätigung vor Widerruf. Aktueller Widerruf löscht die lokale Anmeldung. Keine administrative Ansicht fremder Sitzungen.

Der getrennte UI-Commit koordiniert Tokenrefresh über Web Locks und liest die neuesten lokalen Tokens nach Lock-Erwerb. Damit kollidieren kooperierende Tabs desselben Browserprofils nicht bei normaler Erneuerung. Web Locks benötigen einen sicheren Browserkontext (HTTPS bzw. localhost); ohne diese API bleibt der bestehende Singleflight je Tab. Bei parallel benutztem altem Token erfolgt weiterhin der sichere Familienwiderruf und ein neuer Login. Unterschiedliche Browserprofile besitzen unabhängige Familien. Diese Strategie schützt nicht gegen XSS oder gestohlene gültige Bearer-Tokens.
