# Paket I: generischen Testknopf ohne fachliche Nebenwirkung zusammensetzen

Plan vor UI-Code. Basis Root `95448c3`; das getrennte Backendpaket liefert
`connection-test` und meldet bei heutigen Adaptern ausdrücklich keinen
nachgewiesenen Netzwerktransport. Root integriert dessen saubere Commits.

## Konkreter Fehler und Grenze

`Integrations.jsx` ruft beim generischen Testknopf `/run` mit einer fest
eingetragenen Beispiel-Mailadresse auf. Dieses Verhalten muss entfallen.
Eine ausdrücklich gewählte Nachricht gehört in die bestehende SMTP-Outbox.
Der neue Knopf ruft ausschließlich `/connection-test` ohne Fachpayload auf.
Es erfolgt kein automatischer Retry, kein `/run` und kein fiktiver Versandnachweis.

## Benutzerablauf

- Knopf und Beschreibung benennen die Verbindungsprüfung.
- Ungültige Konfiguration, reine Konfigurationsprüfung ohne Netzwerkprobe,
  tatsächlicher Transportnachweis und Fehler erhalten verschiedene Aussagen.
- Fehlende Probe wird nicht als Erfolg einer Verbindung dargestellt.
- Während einer Prüfung ist der konkrete Knopf deaktiviert; Ergebnis bleibt
  nachvollziehbar. Behebbare Fehler lassen bewusste Wiederholung zu.
- Actor-/Grantwechsel bricht alte Arbeit ab und unterdrückt deren Ergebnis
  einschließlich privater Fehlermeldung, auch nach erneuter Berechtigung.
- Deutsch/Englisch/Spanisch erhalten den gleichen Vertrag.

## Prüfung

Bestehende PrivateAccessfälle weiterverwenden; den veralteten Historynachlauf
durch den tatsächlichen neuen Vertrag ersetzen. Regression mit konfiguriertem
SMTP-Anbieter beweist exakt den neuen Endpoint, keinen Empfänger/Payload,
keinen zusätzlichen Historyaufruf und die ehrliche `not_supported`-Anzeige.
Unklare/inkonsistente Transportzustände dürfen keine Erfolgsaussage erhalten.
Backend-Konfiguration/Probe mit synthetischen Schlüsseln prüfen. Root übernimmt
später tatsächlichen Browserablauf im gemeinsamen Integrationsstand.

## Getrenntes Folgepaket

Verschlüsselter Store ist zunächst verfügbar, aber normale Startupmigration
bleibt ausgeschlossen. Read-only Archivverifikation und expliziter einmaliger
Offline-Konvertierungsweg werden mit Startup-/Backupfence verbunden, bevor
der globale Manager dauerhaft auf diesen Store umgestellt wird. Keine echte
Provider-Schreibaktion und keine Behauptung fertiger TEHA-/WISO-Abnahme.
