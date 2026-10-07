# ImmoManager Pro – Frontend

React und Vite, gemeinsam mit dem FastAPI-Backend im übergeordneten Verzeichnis.

## Voraussetzungen

Zum Entwickeln und Bauen ist Node.js 24 oder neuer erforderlich. Die CI und das Windows-Paket verwenden Node.js **24.21.0**. Nutzer des fertigen Server-/Windows-Pakets benötigen keine separate Node-Installation.

```sh
npm ci
npm run dev
```

## Prüfungen und Produktionsbuild

```sh
npm run lint
npm run test -- --maxWorkers=1
npm run build
```

Ein einzelner Testworker vermeidet auf dem gemeinsam genutzten Windows-Rechner ressourcenbedingte Zeitüberschreitungen. Die normalen Testzeitlimits bleiben unverändert.

Die Ausgabe unter `dist/` muss vollständig ausgeliefert werden. Dazu gehören die lokal gebündelten PDF.js-Ressourcen und ihre Lizenzdateien. Der PDF-Betrachter benötigt zur Laufzeit keinen CDN-Zugriff und keinen externen Renderingdienst. Große Dokumente werden seitenweise dargestellt; Datei- und Renderfehler müssen in der Oberfläche erkennbar bleiben.

API-Basis, Zugang und Datenhaltung werden vom Backend bereitgestellt. Keine Zugangsdaten oder privaten Dokumente in das Frontend-Bundle aufnehmen. Weitere Einrichtung: [Projekt-README](../README.md).
