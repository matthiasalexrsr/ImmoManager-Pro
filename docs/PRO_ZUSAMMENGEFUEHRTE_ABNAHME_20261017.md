# PRO – Frontend-/Backend-Integrationscheckpoint am 17.10.2026

**Kein Release / keine Installationsfreigabe.** Dieser Bericht dokumentiert
nur die gemeinsame Testgrundlage und ihre tatsächlich beobachteten Resultate.
Kein Zugang zu produktiven Originaldateien, echten Bank-/TEHA-/Post-/WhatsApp-
Gegenstellen oder zu laufenden Userinstallationen war Teil dieser Abnahme.

## Gemeinsamer Code statt getrennter Einzelzweige

Zweig `pro/stage-frontend-backend-20261017` im getrennten Worktree
`work/pro-stage-frontend-backend-20261017`.

Ausgangspunkt: `c5db7f39` (Backend: sicherer, selektiver
Schemaadoptions-/Migrationsgraph, Eigentümer- und Receipt-Guards,
kürzerer synthetischer Testdatenpfad). Die Frontendcheckpoint-Commits
`dbcbc418`, `9f34d128` und `b209025a` wurden in dieser
Reihenfolge **ohne Mergekonflikt** übernommen und liegen nun
unter `0eb768f9`, `8797b926`, `1113a7bd`.
Letzter tatsächlicher Produkt- und Testcode-Head:
**`1113a7bd04c2b1ddc8393a76fd153190d9e72600`**.

Der separate zentrale Referenzcheckout blieb bei `04021da5` sauber.
Weder der zentrale Branch noch die laufenden Installationen
auf Port 8000/8765 wurden angetastet. Es gibt keinen Live-Rollout.

## Prüfergebnisse AUF DEM GEMEINSAMEN COMMIT

- **Ruff + Mypy**: gesamte Backendbasis, **562 Dateien** ohne Fehler
  (PowerShell-Abschluss `JOINT_STATIC_GREEN`, Exit 0).
- **Frontendabhängigkeiten**: `npm ci --ignore-scripts` frisch aus
  unverändertem `package-lock.json`, 283 Pakete, Audit meldet
  **0 Schwachstellen**; getrennte ESLint-Prüfung erfolgreich.
  Nachweis:
  `artifacts/pro-tests/combined-frontend-fc7b7459629447be8798535bee6f3ac9/npm-ci.log`,
  `lint.log`. Dies ist keine Behauptung eines vollständig mit
  Installationsskripten ausgeführten `npm ci`.
- **Native PostgreSQL**: unabhängiger, selbst gestarteter
  Testcluster `artifacts/pro-native/1cc7dfb38fa341059a84966580a7a47a`,
  Testbeleg unter
  `artifacts/pro-tests/owned-native-native-942efc8f4c674ead97a9483bcdead0b8`:
  **13/13 bestanden, kein Skip**, inklusive TEHA-Quell-/Rechtezaun,
  Pluginaktionen, Speicherung und Migration.
  `NATIVE_EXIT=0`, `STOPPED=True`: kein Testcluster verbleibt.
- **Vollständige React-/Vitestmatrix auf dem gemeinsamen Commit**:
  `artifacts/pro-tests/combined-frontend-fc7b7459629447be8798535bee6f3ac9/vitest.log`.
  **656/657 bestanden, 1 Timeout** bei
  `ContractsTenantCache.test.jsx` mit 15-Sekunden-Grenze
  während parallel laufender Backend-/Coverage-Prüfung.
  Damit ist der erste Gesamt-Frontend-Exit **rot**, nicht
  als 657/657 umdeuten. Der isolierte identische Test bei
  `artifacts/pro-tests/tenant-cache-repeat-e0c80f5a4f1c4370840067a693c3d1ec/vitest.log`
  besteht **3/3** mit *demselben* Timeout von 15 Sekunden.
  Das macht einen transienten Testrechnerlast-Effekt plausibel,
  beweist aber ohne erneut grünen Gesamtlauf keine vollständige
  Frontendabnahme. Die Produktassertions wurden nicht gelockert.
- **Backend-Gesamtmemorymatrix mit Coverage**:
  `artifacts/pro-tests/combined-full-backend-memory-43a97fe08ce94ed7827f8427ac5240aa`.
  Der Lauf wurde auf exakt `1113a7bd` gestartet, hatte bei
  18 % bislang **einen** Fehler und ist bei Erstellung
  dieses Berichts **noch nicht abgeschlossen**. Weder
  finale Failanzahl noch neue Coverage/Releasequalität
  werden vor Vorliegen seines tatsächlichen Exit-Codes behauptet.
  Ein älterer, roter Lauf lag bei 2612 Bestandenen, 54
  Fehlgeschlagenen, 114 Skips und 83,63 % Coverage;
  dieser ist NICHT der Beleg des neuen Commitstands.

## Verifizierte Grenzen und offene Lücken

1. Ein weiterer Teststarter zum Laden der optionalen
   `fints==5.0.1`-Bibliothek aus einem isolierten QA-Pfad
   wurde durch die Sicherheitsprüfung des Remote-Werkzeugs
   **blockiert**. Der einzelne bereits angewendete Parserdeltapunkt
   wurde rückgängig gemacht; diese Sperre wurde nicht
   umgangen. Der Bibliotheksvertrag bleibt in einer älteren
   unabhängigen QA-Umgebung grün, ist aber **kein** Beleg
   für die vollständige gemeinsame Prüfung. Kein FinTS-Netz-/Bankkontakt.
2. Das bestehende globale `integration_manager`-Config-/Run-
   System und die privaten `integration_connections` sind
   noch keine freigegebene **einzige Konfigurationsautorität**.
   `adopt_legacy` ist explizit durch das weiterhin
   inaktive `connection_bridge_enabled` gesperrt.
   Das ist Absicht, um eine unsichere doppelte Provideraktivierung
   vor der kontrollierten Migration zu verhindern; es ist
   noch keine abgeschlossene Konfigurationsübernahme.
3. TEHA, Bank/FinTS, Portale, WhatsApp/Post, DATEV/WISO,
   Aktenwerk und optionales S3 benötigen weiterhin autorisierte
   echte Gegenstellen-/Zielsystemnachweise und fachliche
   Ergebnisabgleiche; erfolgreiche Mock-/Protocol-Tests
   ersetzen diese nicht.
4. Die weiteren Domain- und Ops-Pakete, insbesondere
   Übergabe/Verkauf, Betriebskosten, Portal, Fristenpläne
   und restliche Dokumenteditor-Anforderungen, sind noch
   **nicht** alle in diesem Gesamtcommit integriert.
   Die vollständige SQL/native-PG-/Browser-/Backup-/
   Stress-/Coverage-/CI-Matrix des finalen Kombinationsstands
   fehlt weiter.
5. Die aktuelle gemeinsame Migrationsaufnahme darf nicht
   leichtfertig auf Anwenderdatenbanken angewendet werden.
   Es fehlt das validierte Upgrade einer autorisierten
   historischen Backupkopie und eine unabhängige
   Original-/Schlüssel-/Indexkontrolle.

## Weiterer sicherer Arbeitsweg

Zuerst den tatsächlichen Backend-Gesamtlauf bis zum Exit
auswerten; optionale Bibliotheks-/echte Fachfehler einzeln
nachweisen. Einen vollständigen Frontendlauf
`npm run test -- --maxWorkers=2 --testTimeout=15000`
bei unbeeinträchtigtem QA-Rechner und nach
Integrationsänderungen wiederholen; gezielte grüne Tests
allein ersetzen ihn nicht. Anschließend die weiteren
unabhängigen Domain-Worktrees nach Tests auf einen
einheitlichen Schemahead und ein einziges Archiv prüfen.
Ein Gesamt-Go benötigt endgültigen Quellhash,
native PostgreSQL, 320/360/1440-Browserabnahme,
Restore und CI – kein altes grünes Ergebnis.
