# Paket I – DDL-freier Connection-/Parametervertrag

Parent: `da127fb9c8eefb75a0cc97a3da5c9f6b0dfd9806`

Dieser Folgecommit ist additiv und besitzt **keine Migration, keinen
Providerlogin und keine externe Schreibaktion**.

## Generischer Verbindungstest

`IntegrationManager.connection_test(id)` besitzt eine explizite
nebenwirkungsfreie Grenze:

- Konfiguration wird zunächst lokal mit dem bestehenden Providervertrag geprüft.
- Ein Provider wird nur dann wirklich probiert, wenn er ausdrücklich eine
  `probe_connection(config)`-Methode implementiert.
- `provider.run(...)` wird vom Verbindungstest nie verwendet.
- Ein Probe-Ergebnis wird verworfen, wenn es
  `business_action_performed=True` oder `test_message_sent=True` behauptet.
- Aktuelle produktive Provider implementieren noch **keinen** Netzwerkprobe.
  SMTP liefert deshalb ehrlich `status=not_supported`,
  `network_checked=false`; es wird keine Nachricht erzeugt oder gesendet.
- Die Antwort nennt
  `mail_test_policy=explicit_outbox_recipient_only`. Eine echte Testmail
  gehört weiterhin ausschließlich in die bestehende Outbox und benötigt einen
  vom Benutzer bewusst gewählten Empfänger.
- Es gibt keinen automatischen externen Retry.

HTTP:
`POST /integrations/{integration_id}/connection-test`

Die bestehende installationsweite Owner/All-Manager- und
CheckedPublicationRoute-Grenze des Integrationsrouters bleibt erhalten.

## Parameterbelege

`connection_contract.py` modelliert die vier Zustände getrennt:

1. `discovered`
2. `observed`
3. `mapped`
4. `accepted`

`accepted` erfordert eine explizite Fachzuordnung; weder Discovery noch
Observation setzen automatisch Mapping oder Abnahme.

Die heutige manifestbasierte Projektion markiert nur tatsächlich deklarierte
Configkeys als `discovered`. Secret-/Required-Kennzeichnung kommt aus dem
realen Provider-Manifest. Persistenz steht ausdrücklich auf
`ddl_pending`, bis Root die lineare Schemafolge nach der reservierten
`i2 -> h2`-Migration abgestimmt hat.

HTTP:
`GET /integrations/{integration_id}/parameters`

Damit wird nicht behauptet, dass ein Manifestparameter bereits extern
beobachtet oder fachlich abgenommen wurde.

## Gates

Leichte synthetische Tests, ohne Provider-I/O:

`pytest backend/tests/test_integration_encrypted_config_store.py backend/tests/test_integration_connection_contract.py -q -rs --tb=short`

Ergebnis: **10 passed**.

Zusätzlich:
- Ruff auf den neuen/geänderten Integrationsdateien: **passed**
- Mypy auf Store, ConnectionContract, Manager und Router:
  **Success: no issues found in 4 source files**
- `py_compile`: **passed**
- `git diff --check`: **passed**

## Bewusste Grenzen

- Keine echte SMTP-/TEHA-/Portal-/WhatsApp-/Post-Verbindung wurde getestet.
- Kein persistenter `provider_connections`-/Mappingkatalog ohne abgestimmte
  Migration.
- Der verschlüsselte Store aus dem Parentcommit ist noch nicht als globaler
  Produktionsstore aktiviert, damit eine vorhandene Klartextdatei nicht beim
  normalen Startup heimlich migriert wird.
- Startup/Recovery/Fullrestore bleiben Root-owned; keine dieser Dateien wurde in
  diesem Paket editiert.
