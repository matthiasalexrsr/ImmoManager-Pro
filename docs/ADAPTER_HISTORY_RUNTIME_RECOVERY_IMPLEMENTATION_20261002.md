# Konkrete Einbindung der Adapterhistorie

Vor Code gelesen: Rootplan `ADAPTER_HISTORY_RUNTIME_RECOVERY_PLAN_20261002.md`
aus dem unveränderten Commit `d8696c5`. Eigener Checkout
`work/integration-history-runtime`, Branch
`assist/integration-history-runtime-recovery`. Core-Autor besitzt weiterhin alle
Historien-/Manager-/Routerquellen in seinem getrennten Checkout.

## Versionierung und API-Abgleich

Zuerst den ersten versionierten Corestand übernehmen und vollständig lesen;
keine fremden Arbeitskopien als eigene Quellen kopieren. Eigene Hookcommits
beginnen nach diesem Basiscommit und verändern keine Coredateien. Angekündigte
APIs vor dem versionierten Abgleich:

- `integration_history_models.HISTORY_MODELS/TABLES`: genau fünf Tabellen;
  die Lauftabelle heißt `integration_runs`.
- `integration_history_schema.ensure_history_schema(connection)`: rein lesend,
  vollständig fehlend `False`, teilweise Familie/fehlende Spalten verweigert.
- `history_validation.validate_history_journal(connection, configuration,
  deadline=None)`: rein offline, SQLite/SQLAlchemy, fehlende Familie vor
  Schlüsselauflösung; vorhandene Fakten mit explizitem Archivschlüsselring.
- `history_store.configure_history(session_factory)`: eigener dauerhafter
  SQL-Speicher auf der tatsächlichen DATABASE_URL, unabhängig vom Domänenmodus.
- Restore-Normalisierung und Lauf-/Clear-Serialisierung werden am ersten
  versionierten API-Vertrag ergänzt, bevor davon abhängiger Code entsteht.

## Umsetzungsreihenfolge

1. Registrierungen in normalem `db/session.py` und Alembic ergänzen. Lokaler
   Start prüft die vollständige optionale Familie vor `create_all`, einschließlich
   Metadaten. Frisches explizites Setup/Migration darf DDL besitzen; der Validator
   und Recoverybridge schreiben niemals Tabellen oder technische Köpfe nach.
   Historienkonfiguration außerhalb des möglichen Memory-Domänenfallbacks
   initialisieren; Datenbankfehler dürfen keine RAM-Historie erzeugen.
2. Testkonfiguration noch vor Import von Anwendung/Session immer auf eine eigene
   temporäre DATABASE_URL setzen, wenn keine ausdrückliche synthetische URL
   vorhanden ist. Das gilt auch im Memory-Domänenmodus. Dieser neue tatsächliche
   SQL-Nebenspeicher darf weder die Produktdatenbank noch fremde Testdateien
   berühren; nur das eigene Tempverzeichnis wird nach Session-/Engine-Abschluss
   entfernt.
3. Einen schmalen Recoverybridge mit Schlüssel- und Fehlergrenzen ergänzen.
   SQLite-`_database_info` besitzt keine Archivkonfiguration: dort nur optionale
   Metadatenprüfung plus Legacy-Ausnahmen der gemeinsamen ORM-Tabellenliste.
   Anschließend `verify_history(database, explicitConfiguration)` auf dem
   unveränderten staged Bild, analog zu IBAN/Entwurfsprüfungen. Auf Sicherungs-
   und Restorepfaden erfolgt die volle Crypto-/AAD-Prüfung vor Dateiverweis-
   Rebasing, Claims, Sitzungswiderruf und Signierrotation.
4. SQL-`invalidate_and_inspect` erhält bereits eine ausdrückliche Konfiguration:
   volle lesende Historienprüfung in der Caller-Offline-Transaktion, danach
   Restore-Normalisierung begonnener Läufe. Kein Provideraufruf oder Replay;
   Ausgang bleibt unbestätigt. Normalisierung, Job-Claimreset und Sessionwiderruf
   rollen bei jedem Folgeschaden gemeinsam zurück.
5. Subsetexport/Import und generischer Reset verweigern tatsächliche vorhandene
   Lauf-/Ergebnisfakten mit Verweis auf Vollarchive. Reine technische Heads und
   minimale Clearbelege bleiben erhalten und erzeugen keinen dauerhaften
   Subsetkonflikt. SQL `clear_all` überspringt ausdrücklich alle fünf Tabellen.
   Vor destruktiver Domänen-DML recheck hinter derselben Writerbarriere; Pending-
   Historien-DML wird nicht committed. Memory-Domänenmodus liest/serialisiert die
   tatsächliche separate SQL-Historie, nicht erfundene RAM-Kopien. Lockreihenfolge
   wird mit dem versionierten Start/Clearvertrag abgestimmt.
6. Echte Gates: frische Alembic-Linie und Up-/Downgrade; beschädigte Familie vor
   DDL; vollständig altes Vollarchiv; verschlüsseltes SQLite-Roundtrip mit echten
   Resultchunks; falscher Schlüssel/AAD; offene Ausführung; PostgreSQL-Offline-
   Transaktion samt Folgefehlerrollback; Pending-/Parallelreset und Clear-only-
   Wiederholung. Bestehende Startup-/Recovery-/Transferprüfungen mitlaufen lassen.
   CI und Typ-/Lintlisten enthalten alle neuen Produktmodule ausdrücklich.

## Abnahmekriterien und Grenzen

Keine Änderung an UI, AI, Historienkern, Manager, Router oder PrivacyFence.
Kein Schreiben in Root/Main/Preview, keine Provideraktionen, kein Push. Jeder
gesicherte Inhalt ist ein tatsächlicher versionierter Corefact. Eine fehlende
Schlüsselkonfiguration, beschädigte Familie oder unbestätigte Ausführung wird
niemals als erfolgreiche Zustellung oder leere RAM-Historie ausgegeben.
Coretests ersetzen nicht die zusätzlichen tatsächlichen Archiv-/Laufzeitgates.
Abweichungen von diesem Plan werden vor ihrer Implementierung dokumentiert.

## Präzisierung der Lockgrenze vor Code

Root hat zusätzlich ausschließlich `InMemoryStore.clear_all` und seinen minimalen
Context-Hook freigegeben. Der vorhandene `_payment_mutation` wurde tatsächlich
gelesen: Er nimmt nur `payments._memory_lock`, ohne Accountlock. Der Core-Autor
bestätigt für Historywrites Accountlock vor SQL-Writer/Historyhead; der Historystore
nimmt selbst keinen Domänenlock und hält keinen Lock über Provider-I/O.

Die Reset-Hülle muss deshalb den Accountlock vor dem vorhandenen
`_payment_mutation` nehmen. Innerhalb dessen Domänenlock wird die eigene SQL-
Historybarriere bis zum Ende der Mutation gehalten; kein Helper darf danach
Account/Domain in umgekehrter Reihenfolge anfordern. Die entsprechende Memory-
Subset-Staginggrenze in `data_transfer` verwendet dieselbe Reihenfolge. SQL-
Rechecks bleiben hinter der bestehenden Account-/Domänenbarriere und verwenden
dieselbe Callerconnection; kein fremder Pending-DML-Commit. Ein tatsächlicher
paralleler Start wird ereignisgesteuert geprüft, statt die Reihenfolge nur aus
Decoratornamen abzuleiten.

Heads/Clears stehen ausschließlich im echten gemeinsamen SQL-Journal und werden
nicht in Dataclass-Dicts gespiegelt oder beim Memoryreset ausgeblendet/gelöscht.
Ihre bloße Existenz ist kein Subsetkonflikt; tatsächliche Runs/Event-/Chunkfakten
bleiben die relevante Retentiongrenze. Die genaue Barriere-/Normalisierungs-API
wird am versionierten Corestand belegt, bevor die Hookimplementierung beginnt.

## Erweiterung: ausdrückliche Ressourcen-Konfiguration

Root hat die bestehende `backend/settings.py` und ihre Environment-Anbindung
zusätzlich freigegeben. Mit dem Core-Autor abgestimmte Felder sind
`integration_history_artifact_bytes`, `integration_history_page_bytes` und
`integration_history_timeout_seconds`; die ENV-Namen sind entsprechend
`INTEGRATION_HISTORY_ARTIFACT_BYTES`, `INTEGRATION_HISTORY_PAGE_BYTES` und
`INTEGRATION_HISTORY_TIMEOUT_SECONDS`. Dokumentierte Anfangswerte sind
16.777.216 Byte je Artefakt, 33.554.432 Byte je Antwort-/Prüfschritt und
60 Sekunden. Diese Werte besitzen keine Obergrenze und begrenzen niemals die
Anzahl gespeicherter Ausführungen. Bytewerte müssen echte positive ganze Zahlen
sein, Zeitwerte positiv und endlich. Boolesche Werte werden verweigert.

Runtime übergibt diese tatsächlichen Settings ausdrücklich als `HistoryLimits`
an `configure_history`. Offlineprüfungen bauen denselben Limitswert ausschließlich
aus der archivierten Konfigurationsmap, ohne globale Settings oder `.env` zu lesen;
alte Archive ohne Historienfamilie werden bereits vor Budget-/Schlüsselauflösung
erkannt. Für vorhandene Familien ohne neuere Budgetfelder gelten nur die oben
dokumentierten kompatiblen Anfangswerte. Die ausdrücklich frische
Memory-Domäneninitialisierung erstellt ausschließlich die fünf Tabellen auf der
vorhandenen `SessionLocal`-Engine, niemals eine neue Hilfsdatenbank.

Die jetzt fest angekündigten Core-APIs sind `lock_history_fence(connection,
nowait=False)` für die vorhandene Callertransaktion, `history_fence(nowait=False)`
für die lange tatsächliche SQL-Grenze der Memory-Mutation und
`mark_restored_unconfirmed(connection, configuration, deadline=None, limits=None)`.
Keine davon erhält einen neuen Providerauftrag. Die schmale neue Memory-Reset-
Hülle sitzt vor dem bestehenden `_payment_mutation`; ihr Context nimmt Account,
Domain-RLock und History in dieser Reihenfolge. Der bestehende Payment-Decorator
darf den bereits gehaltenen reentranten Domainlock innerhalb erneut nehmen.

## Präzisierung nach konkretem SQLite-Gegenbeweis

Root hat im freigegebenen Core einen tatsächlichen Lockkonflikt identifiziert:
Ein bestehender SQLitewriter benötigt beim Abschluss den Memory-Accountlock;
ein neuer Historywriter darf diesen Lock deshalb nicht schon während des Wartens
auf `BEGIN IMMEDIATE` halten. SQLite erhält eine ausdrücklich dokumentierte
Ausnahme: Zuerst den tatsächlichen gemeinsamen Writer erwerben, danach Account
und Memory-Domain; diese Autorität bleibt durch die echte SQL-Commitgrenze und
die Memory-Veröffentlichung erhalten. PostgreSQL behält Account → Domain →
History. Der consumerseitige Context wird erst gegen den versionierten Corefix
abgenommen; eine Ereignisbarriere beweist die native SQLite-Konstellation.

`data_transfer._atomic_store` und `_staged_memory` werden auch von der separaten
Privacy-Mutation unter deren eigenen Locks benutzt. Sie erhalten deshalb keine
neue implizite Historybarriere. Nur der ausdrückliche Geschäftsimport umschließt
seinen gesamten Staging-/Veröffentlichungspfad mit dem neuen Context;
Subsetexport und `clear_all` haben ebenfalls ausdrückliche Grenzen. Damit werden
keine fremden Privacy-/Autoritäts-Lockregeln durch einen gemeinsam verwendeten
Hilfscontext geändert.

Der Autor ergänzt im nächsten versionierten Paket das frei erhöhbare positive
`HistoryLimits.temp_bytes`. Konsistente Konfiguration:
`integration_history_temp_bytes` / `INTEGRATION_HISTORY_TEMP_BYTES`, Anfangswert
536.870.912 Byte. Dieser Wert begrenzt die private Exportdatei pro Arbeitsschritt,
niemals die Anzahl historischer Läufe. Neue Constructorparameter werden erst mit
dem tatsächlich versionierten Dataclassvertrag aktiviert.
