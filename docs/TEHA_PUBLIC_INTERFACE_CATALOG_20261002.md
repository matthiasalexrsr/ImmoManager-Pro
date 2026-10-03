# TEHA: Katalog der öffentlich ausgelieferten Portalschnittstellen

Am 2. Oktober 2026 wurde die vom gewöhnlich geöffneten Kundenportal geladene
öffentliche Programmdatei `https://kunden.socs.ws/assets/index-isnTekQ1.js`
ohne Zugangsdaten über geprüftes HTTPS heruntergeladen und ausschließlich als
Daten geparst. Ihr SHA-256 lautet
`c0809d5357b5a5e3b058bce6dfa23942c9da3a0806849eed76013ed387cddd27`,
die Größe beträgt 1.259.135 Bytes. Der fremde Programmcode wurde nicht ausgeführt.

Der [maschinenlesbare Katalog](TEHA_PUBLIC_INTERFACE_CATALOG_20261002.json)
enthält **74 statische HTTP-Aufrufstellen** mit Methode, abgeleitetem Pfad,
Quellposition, URL-Ausdruck, sämtlichen im Aufruf vorkommenden Zusatzargumenten,
direkt geschriebenen Objektfeldern, öffentlichen Literalwerten und symbolischen
Wertausdrücken. Gleiche Routen können an mehreren Aufrufstellen vorkommen;
die Zahl ist keine Behauptung über 74 verschiedene oder vollständige
Serverfunktionen. Es wurde kein gefundener Geschäfts-Schreibaufruf ausgeführt.

## Gefundene Funktionsgruppen

| Gruppe | Im öffentlichen Client erkennbare Vorgänge |
|---|---|
| Konto | Anmeldung, Sitzungserneuerung, Profil, Passwortänderung und Passwortzurücksetzung |
| Liegenschaften | Inventar, aktuelle Periode, Einstellungen, Brennstoffe, Betriebs-/Heiz-/Hausnebenkosten, Sonderleistungen, CO₂-Aufteilung und Datenprüfung |
| Bewohner/Einheiten | Nutzerlisten, Eigentümer-/Mieterwechsel, Flächen-/Personenwechsel, Vorauszahlungen und Zwischenablesung |
| Dokumente | Archiv, Originalinhalt, Kapitel, einzelne Kapitelinhalte, ZIP und Änderungsprotokoll-PDF |
| Datenaustausch | Aktive Liegenschaften, Austauschdokumente, Inhalte, ZIP, A-Export und Upload |
| Technik | Aufträge, Nutzerdetails, Jahresablesung, offene Nutzer, Folge-/Serviceauftrag und Anmeldedaten |
| Mieterportal | Einladungen, Versandarten, Anschrift, Ereignisse, Sperren/Entsperren und Passwortzurücksetzung |
| Sonstige Stammdaten | Enumerationen und Dashboard |

Dies belegt die im Client sichtbaren Pfade und Ausdrucksformen. Tatsächliche
Berechtigungen, Semantik, Erfolgsantworten und Fehlerverfahren müssen für jede
zu verwendende Operation geprüft werden. Insbesondere sind Upload, Kosten-
und Nutzereinreichung, Mieterportalaktionen und Auftragserteilung noch keine
implementierten, abgenommenen Fachabläufe der Verwaltungssoftware.

## Ausdrückliche Grenzen der statischen Auswertung

- `live_verified` und `runtime_request_schema_verified` stehen bei allen
  Einträgen auf `false`. Die unabhängig tatsächlich ausgeführten Portalabläufe
  sind in [TEHA_PORTAL_OBSERVATIONS_20261002.md](TEHA_PORTAL_OBSERVATIONS_20261002.md)
  belegt und werden durch diesen Katalog nicht ersetzt.
- `{parameter}` bezeichnet einen aus dieser Auswertung nicht als konstant
  bestimmten Pfadanteil. Seine Laufzeitwerte stammen aus dem autorisierten Konto
  und sind nicht Teil dieser öffentlichen Quelldokumentation.
- Bei Bezeichnern, berechneten Schlüsseln und Objekt-Spreads sind direkte
  Schlüssel unvollständig. Die Originalausdrücke bleiben vollständig erhalten;
  es werden keine fehlenden Parameterwerte geraten. Auch ein reines Inlineobjekt
  beweist noch kein Laufzeitschema, weil der Client Werte weglassen oder umformen
  kann.
- Beispiel: Der statische Dokumentinhalt-Aufruf enthält `{Ref:e,...SO(n)}`.
  Daher erscheint direkt nur `Ref`; die tatsächlich beobachtete Anfrage enthielt
  zusätzlich `LiegNr`. Die reale Objektbindung bleibt verbindlich.
- `POST /api/user/refresh` mit dem Ausdruck `{RefreshToken:e}` ist jetzt statisch
  belegt. Seine erfolgreiche Sitzungserneuerung und Fehlersemantik wurden noch
  nicht tatsächlich geprüft; der aktuelle Transport benutzt diesen Aufruf nicht.
- Der Katalog enthält öffentliche Ausdrücke und Literalwerte, keine Tokens,
  Passwörter oder privaten Portalantworten. Unbekannte fachliche Antwortwerte
  gehören in autorisierte private Snapshots und die spätere verschlüsselte
  Importablage. Allgemeine Fehlertexte und Quellcode sind dafür ungeeignet.

Die Auswertung ist ein Ausgangspunkt für weitere Adapterversionen. Sie besitzt
keinen ersten-100- oder ersten-10.000-Aufrufdeckel. Eine spätere Portalversion
erhält einen neuen Quellhash und einen nachvollziehbaren Katalogvergleich;
der bestehende Vertrag wird nicht unbemerkt ersetzt.

## Wiederholbare Auswertung

Das versionierte Werkzeug `scripts/catalogue_public_http_client.cjs` benutzt
die vorhandenen Babel-Abhängigkeiten des Frontends. Nach dessen regulärem
`npm ci` lässt sich eine bewusst ausgewählte öffentliche Quelldatei erneut
auswerten:

```text
node scripts/catalogue_public_http_client.cjs public-client.js catalogue.json https://kunden.socs.ws/assets/index-isnTekQ1.js 2026-10-02
node --test scripts/tests/test_catalogue_public_http_client.cjs
```

Das Werkzeug führt keine Netzwerkanfrage aus. Es löst lexikalische
Stringkonstanten auf und verwirft mehrdeutige oder veränderte Basispfade.
Vier tatsächlich bestandene Prüfungen belegen unter anderem verdeckte
Bezeichner, widersprüchliche Klassenbasen, Spreads/Literalwerte und 257
vollständig erfasste Aufrufe mit einer Quelle, die bei Ausführung absichtlich
scheitern würde. Die produktive TEHA-Quelle wurde damit erneut ausgewertet;
alle 74 Aufrufstellen und der identische Quellhash bleiben erhalten.
