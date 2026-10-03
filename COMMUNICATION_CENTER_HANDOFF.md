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
- WhatsApp-Direkttext bleibt Provider-seitig opt-in; das Kommunikationszentrum selbst verlangt fail-closed ein freigegebenes Meta-Template.
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

- Kommunikationszentrum + Integrationsrouter: 29 bestanden.
- Rollen-/Integrationskonfiguration: 19 bestanden.
- Privacy/Lifecycle/Integrations-Gate: 98 bestanden, 5 optionale Skips; ein altes
  nichtnumerisches WhatsApp-Fixture wurde an die echte Meta-ID-Form angepasst und
  der zuvor rote Test danach isoliert bestanden.
- CommunicationCenter Vitest: 2/2 bestanden.
- Ruff und Mypy (6 neue/kritische Kommunikationspfade): bestanden.
- Frontend ESLint und Vite-Produktionsbuild: bestanden.
- Alembic: leer → Head, Downgrade auf `z1a2b3c4d5e6`, erneutes Upgrade: bestanden.
- OpenAPI: 19 Kommunikationszentrum-Operationen, keine ungesicherten davon.
- Bekannte vorbestehende Admin-Routen-Duplikate sind nicht Teil dieses Commits;
  separater Fix existiert auf `assist/openapi-contract`.

## Öffentliche Spezifikationen

- E-POST Swagger: https://api.epost.docuguide.com/swagger/index.html
- E-POST OpenAPI: https://api.epost.docuguide.com/swagger/v2/swagger.json
- E-POST Versionshistorie: https://api.epost.docuguide.com/versionhistory
- Meta Graph API Versions: https://developers.facebook.com/docs/graph-api/changelog/versions/

## Zusätzliche Release-Evidenz des Zwischencommits

- Frontend-Vollsuite vor den finalen Provider-Guards: 867/868 bestanden; ein
  bestehender Contract-Wizard-Test überschritt unter paralleler Last das 5-s-Budget
  und bestand isoliert in 1,37 s.
- Die verbleibende Starlette/httpx-Testclient-Deprecation stammt aus der vorhandenen
  Testumgebung und ist nicht durch diesen Workstream entstanden.

## Noch bewusst offen

- produktiver E-POST-Druckversand erst nach echter PDF/A-1b-Validierung und
  produktiver Freischaltung des Deutsche-Post-Zugangs
- WhatsApp Webhook-Verarbeitung für zugestellt/gelesen/fehlgeschlagen
- optionale weitere E-POST-Produkte (z. B. Einschreiben) erst nach eigenem
  explizitem Daten-/Statusmodell; die aktuelle Capability-Liste behauptet sie nicht
