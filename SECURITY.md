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
- **KI:** Dokumente gehen nur an das KI-Konto, das die jeweilige Person selbst verbunden hat, und nur, wenn die Einstellungen es erlauben. Die KI hat keinen Zugriff auf Werkzeuge der Anwendung; jeder gelesene Wert wird geprüft und muss in der Maske übernommen werden. Das Auditjournal vermerkt Lesen, Nachfragen und Übernehmen ohne Inhalte.
- **Lieferkette:** feste Versionen (`requirements.txt`, `constraints.txt`, `package-lock.json`), in der CI `pip-audit`, `npm audit` und `bandit`; jedes Release enthält SBOMs (CycloneDX) und `SHA256SUMS.txt`.

## Was der Betreiber einrichtet

1. **`ENVIRONMENT=production`** setzen. Der Start bricht dann bei unsicheren Vorgaben ab (Standard-`JWT_SECRET_KEY`, `*` in `CORS_ORIGINS`, Demodaten, Speicher ohne Persistenz); die API-Dokumentation ist aus.
2. **`JWT_SECRET_KEY`** mit mindestens 32 zufälligen Zeichen (z. B. `python -c "import secrets; print(secrets.token_urlsafe(48))"`) und **`CORS_ORIGINS`** mit genau den eigenen Adressen.
3. **Nur über HTTPS** erreichbar machen, wenn andere Rechner zugreifen (Reverse-Proxy wie Caddy, nginx oder Traefik). Den Server dann mit vertrauenswürdigen Proxy-Headern starten (`uvicorn --proxy-headers --forwarded-allow-ips=<Proxy-IP>`), damit HSTS und sichere Cookies greifen. Das Windows-Paket hört nur auf `127.0.0.1`.
4. **Vollbackups** mit `BACKUP_PASSPHRASE` verschlüsseln und ein zweites Sicherungsziel einrichten (Einstellungen → System → Betrieb).
5. **Zwei-Faktor-Anmeldung** für Eigentümer- und Verwalterkonten einschalten; Selbstregistrierung (`ALLOW_SELF_REGISTRATION`) aus lassen.
6. **Updates** einspielen, sobald die Update-Prüfung eine neue Version meldet; Prüfsummen eines heruntergeladenen Pakets mit `SHA256SUMS.txt` vergleichen (`Get-FileHash` unter Windows, `sha256sum` unter Linux).
7. **KI-Verarbeitung** (Einstellungen → KI-Verarbeitung) nach der eigenen Datenschutzprüfung einstellen: Auftragsverarbeitung mit dem Anbieter des KI-Kontos, Seitenbilder, Angaben zur Immobilie, Aufbewahrung der Lesevorgänge.

Technische Einzelheiten der Härtung: [docs/AI_READING_SECURITY_20261025.md](docs/AI_READING_SECURITY_20261025.md).
