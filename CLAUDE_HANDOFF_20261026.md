# Übergabe an eine lokale Claude-Sitzung – ImmoManager Pro

Stand: **26. Oktober 2026, nach Runde 21 (KI-Lesen mit Gespräch, Sicherheit für den öffentlichen Release)**. Diese Datei ist der Einstieg für eine neue Claude-Code-Sitzung auf dem Windows-PC des Benutzers. Die bisherige Arbeit lief in einer Cloud-Sitzung (`session_017z9FCB1ACJWyygj1LS1hNK`), die keine Dateien auf dem PC lesen kann. Deshalb geht es lokal weiter. Mit dem Benutzer auf Deutsch sprechen.

## 1. Auftrag

Letzte Bitte des Benutzers, wörtlich:

> Codex hat mal weitergearbeitet. Schau dir seinen Chatverlauf, die neuen Aufgaben und seinen Arbeitsstand an und arbeite bitte weiter.

Dazu nannte er:

```text
Codex-Ausgabeordner: C:\Users\matth\Documents\Codex\2026-10-25\https-claude-ai-code-cshk-017z9fcb1acjwyygj1ls1hnk23jugvmf8eeskmiyti1pnw\outputs
Codex-Thread:        codex://threads/01a1753f-2c0d-75f3-9900-189bcab8fd15
Geteilter Verlauf:   https://chatgpt.com/s/cx_6adfdc2f3a388191afd701041301c376   (braucht Anmeldung; aus der Cloud: HTTP 403)
```

Auf GitHub hat Codex seit dem 21.10. nichts Neues hochgeladen: Sein letzter gepushter Stand `codex/pro-integration-20261016` @ `0c6d633` ist vollständig in `claude/dreamy-gauss-nmaxhn` enthalten. Was Codex seit dem 25.10. getan hat, liegt also nur auf diesem PC.

## 2. Erste Schritte

1. Diese Datei vollständig lesen, danach `docs/RELEASE_NOTES.md`, `CHANGELOG.md` (oberste Einträge) und `docs/AI_READING_SECURITY_20261025.md`.
2. Codex-Ordner **nur lesend** sichten:
   - `outputs` auflisten. Bei einem Git-Checkout: `git status --short`, `git branch -a`, `git log --oneline -30`, `git stash list`.
   - Übergabe-, Abnahme- und Planungsdateien lesen (`*.md`, `*.txt`, `ABNAHME*`, `*HANDOFF*`, `*UEBERGABE*`).
   - Den Codex-Verlauf suchen: Codex legt Gespräche vermutlich unter `%USERPROFILE%\.codex\sessions\` als `.jsonl` ab. Nach der Thread-ID `01a1753f-2c0d-75f3-9900-189bcab8fd15` suchen. Falls er nicht auffindbar ist, den Benutzer bitten, Codex' Abschlussnachricht einzufügen.
3. Codex' Stand mit diesem Branch vergleichen:
   ```powershell
   git fetch origin
   git merge-base --is-ancestor 39f969d <codex-head>   # enthält Codex Claudes Runde 21?
   git log --oneline 39f969d..<codex-head>             # Codex' neue Commits
   git log --oneline <codex-head>..origin/claude/dreamy-gauss-nmaxhn
   ```
4. Dem Benutzer kurz auf Deutsch berichten: was Codex umgesetzt hat, welche neuen Aufgaben im Verlauf stehen, was offen oder unfertig ist und der Plan. Danach weiterarbeiten.
5. Codex' Commits per **Merge** in `claude/dreamy-gauss-nmaxhn` übernehmen, kein Rebase fremder Branches und kein Force-Push. Konflikte fachlich lösen. Lockfiles und generierte Dateien nur mit den Werkzeugen des Repos neu erzeugen. Alembic-Migrationsketten prüfen: genau ein Head, bei zwei Heads eine Merge-Migration wie `f022a1b2c001`.

## 3. Aktueller Stand

```text
Repository: https://github.com/matthiasalexrsr/ImmoManager-Pro
Branch:     claude/dreamy-gauss-nmaxhn
HEAD:       39f969d7996d8fc48333933a8fb2e39a08023027   (danach nur diese Übergabedatei)
PR:         #37, Entwurf, Basis claude/redesign-frontend-ui-RUPYS
Version:    2.0.0-beta.1 (pyproject.toml)
CI:         grün auf 39f969d, Push- und PR-Lauf mit je 9 Jobs
```

Die vollständige Historie aller Runden mit Nachweisen steht in der Beschreibung von PR #37. Die letzten Runden:

- **R18:** Volllauf Backend, Frontend und PostgreSQL; Migrationen, Versionen, Doku und Code-Review.
- **R19:** Desktop-Layout bei 1280, 1440 und 1920 px; Version 2.0.0-beta.1.
- **R20:** Keine Liste scrollt bei 1280 px seitwärts; Drucken und Teilen von Dokumenten; Nebenkostenabrechnung als geführter Assistent; Drop-in für Messdienst-Dokumente mit KI-Auswertung.
- **R21:** Lesen mit Gespräch auf `/api/v1/ai/readings`:
  - fünf Flächen: Dokumentablage, Rechnungseingang, Kostenbeleg, Messdienst-Dokument und Zählerfoto;
  - der Server wählt die feste Anweisung (`READING_PROMPT` plus Aufgabe je Fläche);
  - jeder Wert mit Zitat und Sicherheit;
  - Rückfrage, wenn schon ein Datensatz existiert;
  - Werte in der Maske bestätigen oder nur markieren, je nach Einstellung (`aiMarks.js`, `AiFieldMarks.jsx`);
  - Einstellungen unter „KI-Verarbeitung“; höchstens 40 KI-Anfragen in 10 Minuten; Auditeinträge ohne Inhalte.

  Dazu Sicherheit für den Release:
  - das Erneuerungstoken nur im HttpOnly-Cookie `immo_refresh`;
  - CSP und weitere Header in `backend/middleware.py`;
  - Passwort-Sperrliste und eine Sperre nach 50 Fehlanmeldungen je Adresse;
  - Upload-Signaturprüfung und `defusedxml` über `safe_xml`;
  - bandit und pip-audit in der CI, SBOM und `SHA256SUMS.txt` im Release;
  - die API-Dokumentation ist in Produktion aus (`API_DOCS_ENABLED`);
  - neu ist `SECURITY.md`.

## 4. Feste Regeln des Benutzers

- PR #37 **nicht mergen**, **kein Tag** (auch kein v2.0.0) ohne Entscheidung des Benutzers. Nicht auf den Standard-Branch pushen.
- Nur auf `claude/dreamy-gauss-nmaxhn` entwickeln und pushen. Codex' Branches `pro/stage-*` und `codex/*` nicht verändern.
- „Fremden dirty Checkout pro-full-handover-20261016 und vorhandene Stashes nicht anfassen.“
- „Vor Stop immer tatsächlichen Listener/Exe prüfen; fremde Server (z.B. 8000) und Claudes Prozesse nicht stoppen. Zugangsdaten/Schlüssel nicht ausgeben.“
- Die Hauptinstallation auf `http://127.0.0.1:8765/` **nie stoppen**. Umstellen nur auf ausdrücklichen Wunsch und nur über die geprüften Helfer (siehe Abschnitt 5).
- „TESTABO IST ERLEDIGT: regulär über Zahlungen & Rechnungen → Stripe gekündigt, KEINE Kontolöschung. Stripe UND Vermieter1 bestätigten Laufzeitende 02.11.2026. Nichts erneut kündigen und nicht reaktivieren.“
- TEHA-Zugangsdaten, JWTs und private `.env`-Werte nicht kopieren oder ausgeben. Passwörter der Testversion und der QA nie ausgeben.
- Externe Schreibvorgänge (Portale, E-Mail, Banking) nur mit Freigabe des Benutzers. Ein Ergebnis nur dann als abgenommen bezeichnen, wenn es tatsächlich bestätigt ist.
- Für Tests nie die echte Datenbank `immo_manager.db` des Checkouts oder die Daten der Hauptinstallation verwenden, sondern pytest, isolierte Kopien und QA-Server.
- Keine Unteragenten starten. Keine zeitgesteuerten Selbst-Erinnerungen.
- Wegen der Tokenlimits: „Arbeit der Agenten immer sicher und wiederaufnehmbar machen!“ Also eine Fortsetzungsnotiz außerhalb des Repos führen und oft committen.
- Einmal pushen und die CI zu Ende laufen lassen. Ein weiterer Push bricht laufende Läufe ab, und „Deployment readiness“ wird bei abgebrochenen Läufen rot.
- Commit-Trailer:
  ```text
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_017z9FCB1ACJWyygj1LS1hNK
  ```
  Keine Modellbezeichnungen in Commits oder im PR-Text. Der PR-Text endet mit „🤖 Generated with [Claude Code](https://claude.com/claude-code)“, einer Leerzeile und der Sitzungs-URL.
- Beim Aktualisieren des PR-Texts: einen neuen Abschnitt „Round 22“ vor „## Round 21“ einfügen und eine Testplan-Zeile ergänzen. Der übrige Text bleibt erhalten (über 100.000 Zeichen).

## 5. Bekannte Pfade auf dem PC

Stand 19. bzw. 21.10. Vor der Nutzung prüfen, Codex kann sie inzwischen geändert haben.

```text
Codex-Hauptrepo (19.10.):  C:/Users/matth/Documents/Codex/2026-10-01/wi/work/current-integration-20261016
Codex-Arbeitsrepo:         C:/Users/matth/Documents/Codex/2026-10-01/wi/work/ai-workspace-20261018
                           (mit Prüf- und Deploymenthilfen unter artifacts/)
Python (Codex-venv):       C:/Users/matth/Documents/Codex/2026-10-01/wi/work/document-engine-venv-20261016/Scripts/python.exe
Launcher Hauptinstallation: C:/Users/matth/AppData/Local/Programs/ImmoManagerPro/primary-launch.json
Sicherungen und Nachweise: C:/Users/matth/Documents/ImmoManager-Sicherungen/
                           (zuletzt 20261021-Bank-Zahlungen-Mahnwesen-Kautionen/ABNAHME.txt)
```

Codex hat die Hauptinstallation am 21.10. auf `0c6d633` umgestellt, mit Vollsicherungen davor und danach. Die Änderungen der Runden 18–21 laufen dort also noch nicht. Für eine Umstellung hat Codex Helfer im Arbeitsrepo unter `artifacts/`: `billing_release.py stage | ci | select`, `billing_primary_smoke.py`, `billing_acceptance_backup.py`. Sie stoppen nur die exakt erwartete 8765-Exe, sichern die Datenbank, migrieren ausdrücklich und stellen bei einem Fehler wieder her. Vorher den Benutzer fragen und eine frische, geprüfte Vollsicherung anlegen.

## 6. Prüfungen vor jedem Push

```powershell
# Backend (beide Stores, wie in der CI)
$env:TEST_STORE_BACKEND="memory"; pytest backend/tests -q --tb=short
$env:TEST_STORE_BACKEND="sql";    pytest backend/tests -q --tb=short
ruff check backend; mypy backend
bandit -r backend -x backend/tests,backend/services/autotest -ll -ii -q
pip-audit -r requirements.txt --strict --desc

# Frontend
cd frontend; npm ci; npm run lint; npm run test; npm run build; npm audit --audit-level=low
```

Browser-Suiten wie in `.github/workflows/ci.yml` laufen lassen. Sie brauchen Playwright mit Chromium und gebautes `frontend/dist`. Jede Suite schlägt bei einem CSP-Verstoß in der Konsole fehl.

```text
scripts/run_document_browser_qa.py
scripts/run_daily_browser_qa.py --suite {daily,interfaces,qol,application,operations,office,reports,reading}
scripts/run_assistant_browser_qa.py
scripts/run_pdf_toolbar_browser_qa.py [--suite statement-letter | --suite task-cost-workspace]
```

PostgreSQL-Prüfungen laufen über `scripts/run_pro_matrix.py --backend native ...` (siehe `ci.yml`). Neue Abhängigkeiten in `pyproject.toml` **und** `constraints.txt` eintragen, sonst schlägt `test_dependency_manifests` fehl.

## 7. Offene Punkte aus Runde 21

1. Auf GitHub „Private vulnerability reporting“ einschalten, wie in `SECURITY.md` beschrieben. Das muss der Benutzer selbst tun.
2. Der SBOM-Schritt in `release.yml` ist auf GitHub noch nie gelaufen. Manuell starten geht nicht (403), weil `release.yml` nicht auf dem Standard-Branch liegt. Er läuft beim nächsten Push, der Packaging-Pfade ändert, oder beim Tag; dort ist er Pflicht. Auf Windows lassen sich jetzt auch seine PowerShell-Zeilen lokal prüfen.
3. Die Browser-Suiten `message` und `workspace` (nicht in der CI) sind schon seit `d64eddf` rot: ein doppelter Aufgabentitel bei `getByText` und der Fokus auf `#thread-reply`. Das ist eine eigene Folgeaufgabe.
4. Die Suite `party_workspace` braucht den manuellen QA-Server und ist nicht gelaufen.
5. Die Erkennung „gleiche Datei“ über Größe und SHA-256 deckt nur den lokalen Dateispeicher ab, kein S3.
6. Das KI-Gespräch ist nur mit simulierten Antworten getestet. Lokal geht ein Test mit echtem Claude- oder ChatGPT-Konto, aber nur mit Testdaten, nie mit Daten der Hauptinstallation.
