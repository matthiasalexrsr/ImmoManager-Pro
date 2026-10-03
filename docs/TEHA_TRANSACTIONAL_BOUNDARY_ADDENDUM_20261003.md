# TEHA transaktionale Mapping-/Importgrenzen – Addendum 2026-10-03

Basis: `3be51c706059d23e5d5cac22c2768b0525953428` im isolierten
`work/teha-receive-domain`. Dieses Addendum präzisiert den bereits vor Code
committeten Plan `TEHA_TRANSACTIONAL_MAPPING_IMPORT_PLAN_20261003.md`.

Die reservierte L2-Revision bleibt bestehen; keine zweite Queue oder History
wird eingeführt. Das nie ausgelieferte Entwicklungs-Layout aus `2ce5e86` ist
nicht schemaidentisch mit dem jetzt eingefrorenen initialen L2-Release inklusive
Mapping-ID/Digest/FK. Siehe `TEHA_L2_MAINTENANCE_20261004.md`.
Raw/unbekannte TEHA-Felder leben ausschließlich im verschlüsselten Journal.
Die folgenden Writepfade sind vorbereiteter Fachcode und aktuell gesperrt.

## Transaktionsgrenzen

1. **Aktuelle lokale Eltern.** Property/Unit/Period/Tenant/Task-Ziele werden
   scoped aus der aktuellen Datenbank gelesen. Unit/Period werden zusätzlich
   gegen ihren aktuellen Property-Parent und dessen Portfolio geprüft. Bei
   Dokumentvertrag werden Contract, Unit, Property und Tenant erneut gebunden.

2. **Connection-Namespace.** Jeder neue Journalread enthält den opaque
   `connection_key`. Source- und Content-Run müssen exakt denselben Namespace
   wie Mapping/Import besitzen; gleichlautende Provider-IDs anderer
   Verbindungen sind nicht austauschbar.

3. **Root-CommitAuthority ist zwingend und derzeit noch nicht vorhanden.**
   Der Router nutzt weiterhin `WorkflowAuthorityRoute`; der Service prüft
   Owner/All-Scope-Verwalter, aktuelle Installationsrechte,
   `require_fresh_request_authority` und bei SQL-UserStore die vorhandene
   Management-Serialisierung. **Diese Prüfungen sind nur zusätzliche Fences und
   keine Commitgarantie.** Solange Root nicht die tatsächliche
   Unit/Session-/Transaktions-/Datenbankziel-/Operation-/Targetbindung
   bereitstellt, brechen alle Mapping- und Importwrites mit HTTP 503 ab, bevor
   Fachsession/Writer/DML betreten werden. Der frühere dynamische Actor-only-Hook
   ist entfernt; auch ein namensgleicher Pythonmodultyp wird nicht akzeptiert.
   Dieses Paket erfindet keinen Ersatztyp und akzeptiert weder
   Managementlock, letzten SID-Check, bool/lambda noch Duck-Typ als
   CommitAuthority.

4. **History ist Commit-Evidence.** Source-ID, Source-SHA und Connection werden
   nicht aus Client-Rawdaten akzeptiert. Der terminale erfolgreiche
   `integration_runs`-Beleg wird vor Preview und im Writeversuch erneut
   entschlüsselt und die exakte opaque Identität + SHA rekonstruiert.

5. **Mapping CAS.** Mappingbestätigung sperrt zuerst das Portfolio als
   gemeinsamen Parent, danach das aktuelle lokale Target/Parent und anschließend
   die Mappinggeneration. `expected_previous_revision` ist `new` für
   Generation 1, sonst die letzte Revision. Der Insert läuft in einem Savepoint;
   ein Unique-Race wird nach sauberem Rollback als Konflikt gemeldet, nie als
   fremder Replay.

6. **Initiales L2-Release-Layout.** L2 wurde nie in Root/live126 ausgeliefert.
   Das endgültige initiale Receipt speichert `mapping_id`, `mapping_sha256`,
   Mapping-FK, Generation, Source-/Content-SHA und Command-SHA. Die eingefrorene
   Migration importiert keine laufenden ORM-Modelle. Frühere isolierte
   Entwicklungsdatenbanken werden nicht automatisch repariert; siehe
   `TEHA_L2_MAINTENANCE_20261004.md`.

7. **Exakte Mappingreferenz bei Dokumenten.** Das unveränderliche
   DocumentVersion-`teha_import/2`-Manifest enthält `mapping_id`, Generation,
   kanonischen Mappingdigest, geprüften kindgenauen Target-/Elternkontext und
   die archivierte Dokumentklassifikation. Receipt-Connection/Portfolio,
   Mapping-Connection/Portfolio und Originalbinding müssen übereinstimmen;
   gleicher Portfoliobesitz erlaubt kein Original B für Mappingziel A. Der Digest
   umfasst Mapping-ID, opaque Identität/hash, Generation/Revision, lokales Ziel
   und Mapping-Source-History/SHA. Replay/Download berechnen ihn aus der
   unveränderlichen Mappinggeneration neu und prüfen aktuelle Eltern/Grants.
   Klassifikation wird gegen den unveränderlichen Originalsnapshot geprüft;
   normale spätere lokale Neukategorisierung ersetzt diesen Beleg nicht.

8. **Technikauftrag.** Für Task-Receipts bindet der Command-SHA die bestätigte
   Preview inklusive Mappingauswahl/-revision/-generation. Vor Task-DML und vor
   gleichem Command-Replay wird die aktuelle Mappinggeneration sowie das
   aktuelle lokale Target erneut geprüft. Der lokale Task wird ausschließlich
   als `open` erzeugt; keine Provideraktion wird ausgelöst.

9. **Idempotenzclaim.** Gleicher Actor + `idempotency_key` + Command-SHA kann
   erst nach erneuter Source-/Mapping-/Targetprüfung wiederholt werden.
   Gleicher Source-/Contentstand mit anderem Actor/Key ist Konflikt und wird
   nicht als eigener Replay ausgegeben.

10. **Originalbytes.** Dokumentbytes müssen SHA und Größe des terminalen
    `read_document`-Historienmanifests entsprechen. Der vorbereitete Fachpfad
    schreibt Document + erstes DocumentVersion-Original + L2-Receipt in einer
    Fachsession. Eine tatsächliche Root-owned Transaktion/Commitgarantie ist
    noch nicht implementiert; Writes brechen vorher mit 503 ab. Replay/Download validiert Manifest und alle
    DocumentVersion-Chunks vor Erfolg.

11. **Recovery bleibt Root-owned.** Root soll die L2-Tabellen gemeinsam mit
    IntegrationHistory + DocumentVersion/Task-Originalen validieren: Familie
    absent = Legacy-kompatibel, partiell/inkonsistent = fail closed vor
    Zielmutation; keine Providerkontakte oder Wiederholung externer Aktionen.

## Shared-Core-Vorschlag

Für spätere resumierbare Receive-Jobs bleibt nur der bereits dokumentierte
schmale Family-Adapter `teha_receive` (`upper/discover/apply`) als Vorschlag.
Dieses Paket ändert weder OperationalJobs noch Registry/Startup/Recovery.

## Prüfgrenze

Die Korrekturrunde 2026-10-04 bereitet Testquellen vor und prüft nur Source-Diffs.
Keine Pythonimports, Testausführung, App-/DB-/PostgreSQL-/Browser-/Portalprozesse.
Die frühere Datei `test_teha_transaction_boundaries_pure.py` importierte den
Runtime-Service und damit Auth/Settings; ihr beobachteter PASS war kein
No-Runtime-Beleg. Neue Manifestfälle liegen unter `tests/pure`, Runtimefälle
unter `backend/tests/test_teha_runtime_boundaries.py`. Native Gates bleiben Root.
