# Kommunikationszentrum – Handoff

Branch: `assist/communication-center`
Base: `f3203d5`

## Umfang

- Eigene Korrespondenz-Domäne mit persistenten Vorlagen, Bausteinen und Entwürfen.
- Zielgruppen `tenant/company/any`, Kanäle `email/post/whatsapp/universal`, Sprache und Tags.
- Server-seitiger Merge aus Mietpartei/Kontakt, Vertrag, Einheit, Objekt, Portfolio und Kanal-Absender.
- Vorlagen-/Baustein-Editor mit Starterbibliothek und freier Textbearbeitung.
- Freigabe erzeugt unveränderlichen Kontext-/Inhalts-Snapshot mit SHA-256 und professionell formatiertes PDF.
- Mieterkorrespondenz benötigt einen eindeutigen oder ausdrücklich gewählten Vertrag.
- Vorlagen werden serverseitig auf Zielgruppe und Versandkanal geprüft.
- Portfolio-Wechsel verwirft die aktive Editor-Zuordnung, damit kein Vorgang unter falschem Portfolio weiterbearbeitet wird.

## Versand

- E-Mail: Übergabe nur über den bereits gehärteten, manuell freigegebenen SMTP-Outbox.
- WhatsApp: offizielle Meta Cloud API `/{graph-version}/{phone-number-id}/messages`; Standard `v26.0`.
- WhatsApp-Direkttext ist opt-in; Standardweg ist ein freigegebenes Meta-Template.
- Deutsche Post: öffentliche E-POSTBUSINESS API unter `https://api.epost.docuguide.com`.
- Implementiert sind Login, Testeinlieferung über `POST /api/Letter` und Status über `GET /api/Letter/{letterID}`.
- Testsendungen setzen `testFlag=true`, Sperrflächenanzeige und Dubletten-Failsafe.
- Produktiver E-POST-Versand bleibt bewusst blockiert: freigegebene Dokumente sind derzeit normale PDFs, kein nachgewiesenes PDF/A-1b.
- Alternative E-POST-Basis-URLs werden abgelehnt; Credentials können nicht an beliebige Hosts gesendet werden.
- Generischer `/integrations/{id}/run` darf E-Mail, WhatsApp und E-POST nicht auslösen; externe Kommunikation läuft nur über geprüfte Workflows.
- Integrationshistorie redigiert Kommunikationspayloads; Nachrichtentext, Telefonnummern und PDF-Base64 werden dort nicht gespeichert.

## Berechtigungen und Datenschutz

- Lesen folgt Authentifizierung und Portfolio-Scope.
- Schreiben/Versand nutzt die Communication-Capability; Vorlagenbibliothek nur Eigentümer/Verwalter.
- Read-only kann Bibliothek/Vorgänge ansehen, aber keine Integrationen verändern oder ausführen.
- Freigegebene Korrespondenz wird beim normalen Store-Reset nicht gelöscht.
- Tenant-Datenauskunft enthält Korrespondenz-Metadaten sowie geprüfte PDF-Originale mit Hash-Prüfung.

## Verifikation

- Kommunikations-/Integrations-/Rollen-Subset: 36 passed.
- Tenant Privacy/Lifecycle/Wizard: 94 passed, 5 skipped.
- Kommunikationszentrum UI: 3 passed, ohne React-Testwarnung.
- Ruff: alle geänderten Python-Dateien sauber.
- ESLint: sauber.
- Vite Produktionsbuild: erfolgreich.
- Alembic: frische SQLite-Datenbank erfolgreich von leer bis `a01b2c3d4e5f` migriert.
- OpenAPI: 19 Kommunikationszentrum-Operationen, keine ungesicherten davon.
- Bekannte vorbestehende Admin-Routen-Duplikate sind nicht Teil dieses Commits; separater Fix existiert auf `assist/openapi-contract`.

## Öffentliche Spezifikationen

- E-POST Swagger: https://api.epost.docuguide.com/swagger/index.html
- E-POST OpenAPI: https://api.epost.docuguide.com/swagger/v2/swagger.json
- E-POST Versionshistorie: https://api.epost.docuguide.com/versionhistory
- Meta Graph API Versions: https://developers.facebook.com/docs/graph-api/changelog/versions/

## Verifikation

- Alembic Clean-DB-Upgrade bis `a01b2c3d4e5f`: bestanden
- Kommunikations-/Integrations-/Rollen-/Privacy-Gate: 64 bestanden, 2 optionale Skips
- Ruff für alle geänderten Backendpfade: bestanden
- Mypy für die neuen/kritischen Kommunikationspfade: bestanden
- CommunicationCenter Vitest: 3/3 bestanden
- Frontend ESLint: bestanden
- Vite Produktionsbuild: bestanden
- Frontend-Vollsuite: 867/868 bestanden; ein bestehender Contract-Wizard-Test
  überschritt unter paralleler Vollsuite-Last das 5-s-Testbudget. Derselbe Test
  bestand isoliert in 1,37 s.

Die verbleibende Starlette/httpx-Testclient-Deprecation stammt aus der vorhandenen
Testumgebung und ist nicht durch diesen Workstream entstanden.

## Noch bewusst offen

- produktiver E-POST-Druckversand erst nach echter PDF/A-1b-Validierung und
  produktiver Freischaltung des Deutsche-Post-Zugangs
- WhatsApp Webhook-Verarbeitung für zugestellt/gelesen/fehlgeschlagen
- optionale weitere E-POST-Produkte (z. B. Einschreiben) erst nach eigenem
  explizitem Daten-/Statusmodell; die aktuelle Capability-Liste behauptet sie nicht
