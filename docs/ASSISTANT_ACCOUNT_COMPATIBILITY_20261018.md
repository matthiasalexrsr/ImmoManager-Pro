# Kontoclients: Kompatibilitätskorrektur vom 18.10.2026

Die echte ChatGPT-Kontobestätigung und ein anschließender Modellaufruf haben eine
Lücke gegenüber der zuvor bestandenen lokalen Abnahme aufgedeckt: Der installierte
Codex-Client weist `readOnly.access` in `turn/start` zurück. Die Anmeldung und das
Laden des Modellkatalogs allein konnten diesen Fehler nicht nachweisen.

## Umsetzung

- Ein eigenes Berechtigungsprofil `immomanager` verweigert Dateizugriff außerhalb
  des temporären Arbeitsordners. Dieser Ordner ist ausschließlich lesbar;
  Netzwerkzugriff für lokale Werkzeuge ist deaktiviert.
- Gespräch und Modelllauf wählen dieses Profil ausdrücklich. Vor einem Modelllauf
  muss der native Client die Profilidentität ohne geerbtes Profil bestätigen.
  Ein fehlender oder abweichender Nachweis bricht den Lauf vor der Übertragung ab.
- Die dafür erforderliche Protokolloption aktiviert nur die entsprechenden
  Clientfelder. Shell, Plugins und fremde Werkzeuge bleiben deaktiviert; sämtliche
  unerwarteten Anfragen werden weiterhin abgelehnt.
- Veraltete Sandbox-Overrides werden nicht zusätzlich gesendet. Es gibt keinen
  Rückfall auf unbeschränkten Dateizugriff.
- Native Protokollablehnungen und Zeitüberschreitungen erhalten unterscheidbare
  Fehlerzustände; interne Meldungen und Zugangsdaten gelangen nicht in die API.
- Claude verarbeitet bereits gepufferte Ausgaben eines beendeten Clients, ohne
  auf geerbte Browser-Ausgabekanäle zu warten. Eine erfolgreiche Anmeldung muss
  anschließend weiterhin durch den offiziellen Kontostatus bestätigt werden.

Grundlage sind das vom installierten Client erzeugte Protokollschema und die
offiziellen Dokumentationen zu
[Berechtigungsprofilen](https://learn.chatgpt.com/docs/permissions) und
[App-Server-Konten und Gesprächen](https://learn.chatgpt.com/docs/app-server).

## Nachweise und verbleibende Abnahme

Der angemeldete offizielle Codex-Client hat mit GPT-6.1 Sol und hoher Denktiefe
eine echte, quellenfreie Testantwort geliefert. Dies ist ein Konten- und
Modellnachweis, noch kein Nachweis des vollständigen Recherche- und Anlageablaufs.

Regressionen prüfen insbesondere falsche oder fehlende Profilbestätigungen,
unzulässige Werkzeuge, native Request-Ablehnungen, Zeitüberschreitungen und
beendete Claude-Prozesse mit weiterhin offenen Ausgabekanälen.

Die weitere Abnahme erfolgt über ausdrücklich synthetische Objekt- und
Dokumentdaten: Recherchewerkzeuge, Lesen eines Originalbelegs, geprüfter
Aufgabenvorschlag, dauerhafte Speicherung und wiederholsicheres Speichern.
Authentifizierungsmaterial bleibt im verschlüsselten benutzergebundenen Tresor
der Installation; Anmeldecodes und OAuth-URLs werden nicht in dieses Repository
oder Prüfprotokolle aufgenommen.
