# Paket I – Offline-Verifikation, Legacy-Konvertierung, Ressourcenpolitik und CAS

Stand: 03.10.2026
Parent: `7b6073f96106f0fc2efdb51430f53e5de75a69bb`
Checkout: `work/integration-connections`

Vor Code gelesen: aktueller Klartext-/Encrypted-ConfigStore, Stable-Keyring/
HistoryCrypto, Manager/Router, bisherige Store-/Connection-Tests und Root-Handoffs.
Root/Main/Preview/Recovery/Startup/UI bleiben in diesem Paket unangetastet.

## 1. Ressourcenpolitik statt künstlicher Obergrenzen

Der bestehende Dateistore hat heute:
- Default `max_bytes=1 MiB`, aber willkürliche Obergrenze 16 MiB;
- Default `lock_timeout=5 s`, aber willkürliche Obergrenze 60 s;
- feste JSON-Tiefe 64.

Korrektur:
- bestehende Defaults bleiben unverändert;
- Byte-/Zeitbudgets müssen nur **positiv** sein, Zeit zusätzlich endlich;
- keine feste obere Produktgrenze;
- JSON-Tiefe wird als explizite `max_json_depth`-Ressourcenpolitik geführt,
  Default weiterhin 64. Sie begrenzt Parser-/Validierungsarbeit, nicht Providerfelder
  oder Gesamtbestand; unbekannte erlaubte Felder bleiben vollständig erhalten;
- boolesche Werte gelten nicht als numerische Budgets.

## 2. Rein lesender Archivverifier

Neuer DDL-/Auth-/Settings-freier Kern:
`verify_encrypted_integration_state(path, configuration, ...)`.

Eigenschaften:
- öffnet ausschließlich den expliziten Pfad read-only;
- verwendet ausschließlich die **mitgelieferte** Archivkonfiguration über
  `keyring_from_configuration`; niemals current settings, default key oder Liveauth;
- prüft Dateityp/Reparse/Symlink, Envelopeform, AEAD/AAD, JSONzustand,
  Ressourcenbudgets und vollständige unbekannte Felder;
- schreibt weder Datei, Locksidecar noch Metadaten;
- gibt nur nichtgeheime Verifikationsmetadaten zurück:
  Format, Bytegrößen, aktiven Ciphertext-Key-ID, State-SHA256 und Zählwerte.
  Keine Configwerte, Secretwerte oder Ciphertextbytes.

Root kann diesen Kern später vor Zielpublikation in Full-Recovery einhängen.

## 3. Expliziter Offline-/Maintenance-Konvertierungsweg

Ein CLI unter `scripts/` konvertiert vorhandenen Klartextzustand nur auf
expliziten Operatoraufruf:
- `--state-file` und `--configuration` sind Pflicht;
- Konfiguration wird aus der explizit genannten JSONdatei gelesen;
- keine Settings/.env-/Liveauth-Fallbacks;
- Validierung des gesamten Klartextzustands vor Verschlüsselung;
- atomare Publikation über denselben Lock/temp/fsync/`os.replace`-Pfad;
- bis zum Replace existiert nur der alte Klartextzustand, danach nur der neue
  verschlüsselte Zustand; **kein Klartext-Backup-/Rollbackfile**;
- bei Fehler vor Replace bleibt der alte Zustand byteidentisch;
- Ausgabe enthält nur festen Status/Format, niemals State/Credentials/Ciphertext.

Bereits verschlüsselter gültiger Zustand ist idempotent read-only erfolgreich.
Envelope-artiger Schaden wird nie als Legacy-Klartext interpretiert.

## 4. CAS-/Revisionvertrag für Connections

Der nächste Managervertrag benötigt keine neue DDL:
- Store liefert einen opaque Revisiontoken aus den **exakten Dateibytes**,
  nicht aus Klartext/Secretwerten;
- `load_with_revision()` liest Zustand + Revision unter derselben Sperre;
- `update_if_revision(expected, mutate)` vergleicht unter derselben Sperre,
  verändert bei mismatch nichts und meldet `state_revision_conflict`;
- unbekannte Felder und maskierte Secretwerte bleiben durch den bestehenden
  Mergepfad erhalten;
- Revision ist ein Nebenläufigkeitstoken, keine Inhalts-/Rechtsaussage.

HTTP-/Managerprojektion dieses Tokens wird erst in einem separaten additiven
Folgecommit vorgenommen; globale Manageraktivierung des verschlüsselten Stores
bleibt Root-owned bis Upgradepfad/Verifier integriert sind.

## 5. Factory / präziser Root-Hook

Additive Factory:
`build_encrypted_integration_store(path, explicit_configuration, budgets...)`.

Sie:
- konstruiert Keyring ausschließlich aus expliziter Konfiguration,
- konfiguriert die oben genannten Ressourcenbudgets,
- führt **keine** Initialisierung/Migration/Provideraktion aus.

Root kann sie nach erfolgreicher Upgrade-/Recoveryverifikation verwenden, ohne
den globalen Manager in diesem Paket umzuschalten.

## 6. Gates

Nur synthetisch/lokal:
- Defaults weiter 1 MiB / 5 s / Tiefe 64;
- >16 MiB explizites Budget und >60 s Timeout werden konstruktiv akzeptiert
  (ohne riesige Datei erzeugen zu müssen);
- ungültige/bool/negative/NaN Budgets fail-closed;
- Tiefe 64 Default failt bei >64, explizit höhere Tiefe erhält unbekannte Felder;
- read-only verifier verändert weder Statefile noch Verzeichnisinhalt/mtime und
  funktioniert mit absichtlich falschen Ambient Settings;
- falscher Archivkey/AAD/Tamper fail-closed;
- CLI Klartext→Encrypted, schon encrypted idempotent, Fehler lässt Altbytes
  unverändert, kein Backupfile und keine Secret-Ausgabe;
- CAS gleicher Revision erfolgreich, stale Revision ohne Mutation;
- bestehende Store/Connection-Gates, Ruff, Mypy, py_compile, diff-check.

Keine Migration: historisches `i2` existiert bereits; `j2a2b3c4d5e6 -> h2`
ist anderweitig reserviert. Dieses Paket erzeugt keine DDL.
