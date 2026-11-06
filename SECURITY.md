# Sicherheit – ImmoManager Pro

*English summary: please report vulnerabilities privately via GitHub ("Security" → "Report a vulnerability"), not in public issues. Only the latest release line receives fixes. The sections below describe what the application protects and what the operator has to configure.*

## Eine Schwachstelle melden

Bitte **nicht** als öffentliches Issue. Stattdessen im Repository unter **Security → Report a vulnerability** eine private Meldung anlegen (GitHub „Private vulnerability reporting“). Hilfreich sind:

- betroffene Version (Einstellungen → System → Über ImmoManager Pro) und Betriebsart (Windows-Paket, Docker, Server),
- Schritte zum Nachvollziehen, erwartetes und tatsächliches Verhalten,
- ob echte Daten betroffen sein können.

Wir bestätigen den Eingang innerhalb von 5 Werktagen und nennen nach der Prüfung eine Einschätzung und einen Zeitplan. Kritische Lücken (Zugriff ohne Anmeldung, Daten anderer Portfolios, Codeausführung) werden vorrangig behoben und mit einem Release und einem GitHub-Sicherheitshinweis veröffentlicht. Wer verantwortungsvoll meldet, wird auf Wunsch genannt.

Bitte keine Tests gegen fremde Installationen, keine echten Mieterdaten in Meldungen und keine Angriffe auf die Verfügbarkeit (Last, Spam).

## Unterstützte Versionen

| Version | Sicherheitskorrekturen |
|---|---|
| 2.0.x (einschließlich Beta und Release-Kandidaten) | ja |
| 1.x | nein – bitte auf 2.0 aktualisieren (Vollbackup vorher legt das Programm selbst an) |

## Was die Anwendung schützt

- **Anmeldung:** Passwörter mit PBKDF2-SHA256 (600 000 Runden). Abgelehnt werden zu kurze Passwörter, bekannte und leicht erratbare (Sperrliste, Jahreszeit/Monat mit Jahr), solche mit Benutzername oder E-Mail-Adresse sowie über 128 Zeichen. Nach 5 Fehlversuchen je Konto und 50 je Adresse in 15 Minuten wird gewartet. Zwei-Faktor-Anmeldung (TOTP) ist je Konto möglich und für Eigentümerkonten empfohlen.
- **Sitzung:** kurzlebiges Zugriffstoken (30 Minuten) und ein Erneuerungstoken, das die Browser-App nur als HttpOnly-Cookie erhält (SameSite=Strict, über HTTPS Secure, nur für `/api/v1/auth`). Jedes Erneuerungstoken gilt einmal; Abmelden widerruft es, ein neues Passwort beendet alle übrigen Sitzungen des Kontos, und jede Sitzung lässt sich unter Einstellungen einzeln beenden.
- **Rechte:** Rollen (Eigentümer, Verwalter, Buchhaltung, Technik, Nur Lesen) und Portfolio-Zuordnung werden für jeden Lese- und Schreibzugriff auf dem Server geprüft, auch für Dateien.
- **Browser:** Content-Security-Policy (nur eigene Herkunft, kein Inline-Skript, kein `eval`), Schutz vor Einbettung in fremde Seiten, Referrer-Policy, Permissions-Policy, COOP/CORP und über HTTPS HSTS.
- **Dateien:** nur erlaubte Dateitypen; der Inhalt muss zur Endung passen (Signatur); was ein Browser als aktiven Inhalt deuten könnte, wird nur als Download in einer Sandbox ausgeliefert. XML aus Uploads und Bankdateien wird ohne Entitäten gelesen.
- **Geheimnisse:** Zugangsdaten von Schnittstellen und KI-Konten sind verschlüsselt (AES-256-GCM); Vollbackups enthalten die Schlüssel nur passphrasegeschützt.
- **KI:** Dokumente gehen nur an das persönlich verbundene KI-Konto und nur, wenn die Einstellungen es erlauben. Die Dokumentlesung hat keine Anwendungs- oder Recherchewerkzeuge. Der globale Assistent erhält ausschließlich freigegebene lesende Fachwerkzeuge und ausdrücklich eingeschaltete Recherche; Daten und Verlauf werden an die aktuelle Akten-/Dateiauswahl gebunden. Fachliche Änderungen bleiben prüfbare Vorschläge vor der Übernahme. Das Auditjournal der Lesung vermerkt Aktionen ohne Dokumentinhalte. Ein passender Systemprompt ersetzt keine technische Rechteprüfung und garantiert keine fehlerfreie Modellantwort.
- **Lieferkette:** feste Versionen (`requirements-runtime.txt`, `constraints.txt`, `package-lock.json`), in der CI `pip-audit`, `npm audit` und `bandit`. Die Freigabe verlangt CI, native Abnahme und Härtung auf demselben Commit. Der reguläre Kundenpfad benötigt bestätigte Herausgebersignaturen einschließlich macOS-Notarisierung; der ausdrücklich gewählte unsignierte Beta-Testweg bleibt davon getrennt. Prüfsummen, Herkunftsnachweise, vollständige Quellbeilagen und die SBOMs des jeweiligen Produktprofils gehören zur Releaseprüfung; ältere Test-Releases sind keine pauschale Bestätigung aller dieser Nachweise.
- **Updates:** Kundenupdates verwenden ein geprüftes Installationspaket. Der HTTP-Sourceupdater ist gesperrt. Ein ausschließlich ausdrücklicher Entwickler-CLI-Aufruf muss Versionstag, erwarteten Commit und Herkunft binden und Sicherung/Transaktionszustand prüfen. Bei unklarem oder fehlgeschlagenem Rollback bleiben Schreibzugriffe gesperrt.

## Was der Betreiber einrichtet

1. **`ENVIRONMENT=production`** setzen. Der Start bricht dann bei unsicheren Vorgaben ab (Standard-`JWT_SECRET_KEY`, `*` in `CORS_ORIGINS`, Demodaten, Speicher ohne Persistenz); die API-Dokumentation ist aus.
2. **`JWT_SECRET_KEY`** mit mindestens 32 zufälligen Zeichen (z. B. `python -c "import secrets; print(secrets.token_urlsafe(48))"`) und **`CORS_ORIGINS`** mit genau den eigenen Adressen.
3. **Nur über HTTPS** erreichbar machen, wenn andere Rechner zugreifen (Reverse-Proxy wie Caddy, nginx oder Traefik; Vorlage: `ops/nginx/immomanager.conf.example`). Den Server dann mit vertrauenswürdigen Proxy-Headern starten (`uvicorn --proxy-headers --forwarded-allow-ips=<Proxy-IP>`), damit HSTS, sichere Cookies und die Anmeldebremse je Adresse greifen. Das Docker-Image tut das von selbst und prüft vor dem Start die Einstellungen (`TRUSTED_PROXY_IPS`, `CORS_ORIGINS`, `BACKUP_PASSPHRASE` …, siehe `docs/INTEGRATION_RELEASE.md`). Das Windows-Paket hört nur auf `127.0.0.1`.
4. **Vollbackups:** `BACKUP_PASSPHRASE` schützt die enthaltene Schlüsseldatei und `.env` mit scrypt/AES-GCM. Die Datenbank und Dokumente im ZIP sind dadurch nicht vollständig archivverschlüsselt. Das Sicherungsziel und externe Kopien müssen deshalb mit passenden Zugriffsrechten und gegebenenfalls Laufwerks-/Speicherverschlüsselung geschützt werden. Ein zweites Ziel unter Einstellungen → System → Betrieb einrichten und seine Wiederherstellbarkeit prüfen.
5. **Zwei-Faktor-Anmeldung** für Eigentümer- und Verwalterkonten einschalten; Selbstregistrierung (`ALLOW_SELF_REGISTRATION`) aus lassen.
6. **Updates:** Vorher ein geprüftes Vollbackup erstellen und die Anwendung geordnet schließen. Herkunft und Herausgebersignatur des neuen Pakets prüfen; Prüfsummen mit `SHA256SUMS.txt` vergleichen (`Get-FileHash` unter Windows, `sha256sum` unter Linux). Eine Prüfsumme aus derselben unbekannten Quelle bestätigt allein keine vertrauenswürdige Herkunft. Bei Rückkehr zur alten Programmversion das zugehörige Vor-Upgrade-Vollbackup in einen getrennten Datenordner wiederherstellen.
7. **KI-Verarbeitung** (Einstellungen → KI-Verarbeitung) nach der eigenen Datenschutzprüfung einstellen: Auftragsverarbeitung mit dem Anbieter des KI-Kontos, Seitenbilder, Angaben zur Immobilie, Aufbewahrung der Lesevorgänge.

Technische Einzelheiten der Härtung: [docs/AI_READING_SECURITY_20261025.md](docs/AI_READING_SECURITY_20261025.md).
