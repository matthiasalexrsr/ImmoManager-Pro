# PRO – API-/Plugin-/Speicher-Schnittstellen, Entwicklungscheckpoint 16.10.2026

**Status: geprüfter Entwicklungsblock, nicht produktiv freigegeben.**
Quell-Worktree `pro-finish-platform-20261016` bleibt unabhängig.
Zusammenführung in `pro/stage-interfaces-platform-20261016` auf
Basis `3017c330`. Der zentrale Checkout blieb bei `04021da5`,
das laufende Produkt an Ports 8000 und 8765 wurde nicht gestartet,
verändert, benutzt oder migriert. Die Datenbank-, S3-, Restore- und
Pluginprüfungen verwendeten Wegwerfzustände, synthetische Credentials
und isolierte Schlüssel. Keine Cloudanbindung wurde freigeschaltet.

## Integrierte Produktgrenzen

- Erweiterbare, deklarierte Plugin-Routen und geschützte Aktionen
  besitzen explizite API-/Datenversionen, Rechte-, Eigentümer- und
  Kompatibilitätsprüfung. Die Plugin-Datenmigration ist atomar und
  wiederholbare Befehle werden dauerhaft erkannt. Trusted Python-Plugins
  erhalten dadurch **keine Prozesssandbox**; Drittcode darf nicht als
  untrusted isolierter Dienst ausgegeben werden.
- Die JSON-Schema-Prüfung verweigert jetzt auch doppelte Pflichtfelder,
  unbekannte Pflichtfelder, falsche Datenstrukturen und nicht
  deklarierte Kind-Schemas, **vor** einer Datenmigration.
- Der Upload-/S3-Speicherpfad schützt die Originalbytes über private
  Dateizugriffsrechte, signierte/gebundene Zustände und HTTP-Range.
  Die S3-Protokolltests verwenden einen lokalen, kontrollierten
  künstlichen Backend-Client; sie belegen **keine** Amazon-/MinIO-
  Produktivverbindung.
- Die Sicherung erfasst registrierte Pluginartefakte, Runtime-Ursprünge,
  Schlüsseldaten und originalreferenzierte Uploads. Der Wiederherstellungspfad
  lehnt fehlende Referenzen oder nicht kompatible Pluginpakete ab.
  Eine frische Zielinstallation wurde wirklich gestartet und die
  Anmeldungs- und Originaldownload-Grenzen dort überprüft.
- `e160a1b2c314` bleibt eine additive Plattform-Migration auf
  `d73f2b9a041c`. Die reine Merge-Revision
  `e1f0a1b2c314` vereinigt sie mit dem bestehenden
  Anwendungs-Head `e1f0a1b2c3f5`, ohne frühere
  Migrationshistorie umzuschreiben.

## Prüfbelege im eigenen Checkout

- `artifacts/pro-tests/platform-interfaces-full-sql-sql-1193ededb0954ffd8813eebfe5c58a52`:
  **14/14 SQLite bestanden**, 0 Skip. Enthält Plugin-Protokoll,
  private S3-Originale, sichere Aktionen, additive Migrationen und
  vollständigen künstlichen Vollbackup-/App-Restore.
- `artifacts/pro-tests/platform-owned-restore-fixed-sql-9598d48a86ff4a40898e5428f3ad5a37`:
  **1/1** tatsächlicher Restart einer vollständig restaurierten
  Anwendung; mit synthetischem Login, authentifizierten Bytes,
  gezielten HTTP-Range-Anfragen und verweigerten anonymen Abrufen.
  Der zunächst rote Test hatte ein Ziel außerhalb des vom
  Restore-Gate vorgeschriebenen, frischen `artifacts/`-Verzeichnisses
  gewählt; *die Sicherheitsprüfung wurde nicht aufgeweicht*.
- Native PostgreSQL: erster Teilstand
  `artifacts/pro-native/bce41abae2234d35ac325156093681ae`
  mit **7/7**. Auf dem **exakten Codecommit `f1a2917e`**
  `artifacts/pro-native/2cc21ae7367145e8bcb3296571081359`
  mit `artifacts/pro-tests/owned-native-native-b6f70e1fd6804f359868cb6eb3078297`:
  **11/11 ohne Skip**, frischer lokaler Testcluster anschließend beendet.
- `artifacts/pro-tests/platform-schema-declarations-sql-2047fd93737543dcb9760f31546c47ec`:
  **4/4 SQLite-Negativprüfungen** von falschen, fehlenden,
  doppelten und unbekannten Plugin-Schemakennungen.
- Frontend: sauberes `npm ci --ignore-scripts` (283 Pakete,
  0 gemeldete Schwachstellen), ESLint, **11/11**
  `PlatformSection.test.jsx` plus `IntegrationConnections.test.jsx`,
  Produktionsbuild erfolgreich. Eine zuvor fehlerhafte
  Async-Testannahme wartete nicht auf den asynchron ausgelösten
  GET-Request; Test wartet jetzt gezielt auf die tatsächliche
  Antwortgrenze. Die Komponente selbst wurde dafür nicht
  umgangen.
- Vollständige statische Abschlussprüfung des Integrations-Worktrees:
  **Ruff und Mypy --platform linux für 535 Backend-Quelldateien grün**.
  Hierzu wurden die bekannten Audit-Append-/Notification-Inbox-
  Typkonflikte und vier neue reine Testtyping-Stellen behoben.
  Der Rollback entfernt nun das eigene Auditereignis, nicht einen
  späteren Eintrag eines zweiten Schreibers.

## Offen / zusätzliche Betreiber- und Gegenstellenabnahmen

1. **Browserprobe ist nun real durchgeführt**, ausschließlich auf
   einer bereits separat wiederhergestellten Testinstallation:
   `artifacts/restored-browser-9ndwpdls/result.json` ist
   `browser_verified` und `stopped=true`; Login,
   anonym verweigerter Zugriff, authentifizierter Originalhash,
   Dashboard und Speicher-/Pluginverwaltung bei 320/360/1440 px
   sind nachgewiesen. Sechs Screenshots wurden visuell kontrolliert.
   Ein zunächst grüner Browsertest zeigte nur Ladezustand bzw.
   Einführungsdialog, also kein vollwertiges Layoutorakel. Ein
   strengerer Lauf deckte bei 320 px eine abgeschnittene
   Restore-Schaltfläche auf; die Aktionszeile wurde daraufhin
   mobil umgebaut und mittels bounding-client-rect-Grenzen
   wiederholt grün geprüft. Das gilt nur für diese Plattformoberfläche,
   **nicht** als Browserabnahme der anderen Fachpakete.
2. Keine autorisierten echten S3-/MinIO-Endpunkte, Provider-
   Credentials oder Third-Party-Plugin-Daten wurden zum Test
   verwendet. Die Speicherauthentizität und Pluginlaufzeiten
   bei echter Netzausfall-/Versionsdrift sind separat abzunehmen.
3. Keine Integration mit dem bisher nur lokal gesicherten TEHA-
   (`d35057c0`) und Kanal-Checkpoint (`2da46904`);
   letztere hat noch einen explizit blockierten Alembic-Merge.
   Ohne vollständig linearisierte Migrationen kein
   gemeinsamer SQL-Appstart und kein Deployment.
4. Zusätzlich sind `artifacts/pro-tests/platform-static-green-final-sql-e45b022fc3b7422da9f78a45d3869a00`
   mit **19/19 SQLite** im früheren Worktree sowie
   `artifacts/pro-tests/platform-committed-f1a2917e-sql-231093b580ee4fdd9f9dde02dec2a137`
   mit **19/19 auf exakt Commit `f1a2917e`**, einschließlich Memory-Audit-Rollback-Negativfall,
   `artifacts/pro-tests/platform-schema-declarations-sql-2047fd93737543dcb9760f31546c47ec`
   mit **4/4** Invalid-Schema-Fällen und
   `artifacts/pro-tests/platform-plugin-transport-fence-sql-6d3a17cb247a492fb9572dbb96be30b4`
   mit **1/1** Replay-/WebSocket-Gegenprobe erfolgreich.
   Der Browserlauf und seine Screenshots sind der exakten
   Arbeitskopie zugeordnet, nicht fälschlich einem älteren CI-Commit.

5. Weiterhin fehlen Vollbestands-Scale-, gesamte Native-/Restore-
   Matrix und CI **auf dem später kombinierten exakten Git-Hash**.
   Ein produktiver Rollout ist ausdrücklich **nicht** freigegeben.

## Für die spätere Zusammenführung

Vorsicht bei den derzeit gleichzeitig bearbeiteten Dateien
`backend/services/full_backup.py`, `backend/routing.py`,
`backend/db/__init__.py`, `backend/services/integrations/manager.py`,
`backend/services/upload_policy.py` und
`backend/services/portfolio_scope.py`.
Nicht einfach konkurrierende Änderungen überschreiben oder
frühere Migrationen umnummerieren. Bei einem Konflikt Bank-,
TEHA-, Kanal- und Plugin-Originalprüfer additiv auf derselben
archivierten Datenbankkopie und dem restaurierten Schlüsselring
zusammenführen. Keine automatischen externen Aufträge
auf Grundlage bloßer Migrations- oder Restoreprüfungen auslösen.
