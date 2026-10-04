# Paket I / TEHA – transaktionale Mapping- und Importbefehle

Basis: `2ce5e866f4dd566df7c1fc0f5008574f81d3b8c2` im isolierten
`work/teha-receive-domain`. Dieser Plan wurde vor Produktcode geschrieben.

## Belegter Ausgangspunkt

Vorhanden und bereits separat versioniert:

- DDL-freier Empfangskern mit vollständigem Source-SHA, expliziten ExternalIdentity-Werten, MappingDigest, Previewzuständen und reiner Document/Task-Projektion.
- Verschlüsseltes Integrationsjournal als alleinige private Raw-Quelle. `history.detail("teha", run_id, actor)` validiert Chunks/AAD und liefert nur terminal vollständig journalisierte Runs; `history_exchange()` akzeptiert ausschließlich `completed`.
- Append-only `teha_external_mappings` und `teha_import_receipts` aus der reservierten L2-Familie.
- Der bestehende DocumentVersion-Core besitzt mit `persist_version_bytes()` eine no-commit Primitive. Der normale `CommunicationRepository.create_task()` committet dagegen selbst; ein zusammengesetzter TEHA-Befehl darf diesen Facade-Pfad daher nicht verwenden.

## Ziel dieses Pakets

Ein lokaler Befehl darf nur dann publizieren, wenn unmittelbar in derselben Transaktion erneut bewiesen ist:

1. der angegebene TEHA-History-Run ist vollständig, unverändert und die angegebene Source-SHA entspricht exakt einem darin enthaltenen privaten Quellobjekt mit derselben opaque Identity;
2. sämtliche benötigten Mappinggenerationen sind weiterhin die aktuellen bestätigten Generationen derselben Connection und desselben Portfolios;
3. die lokalen Ziele sind noch sichtbar, gehören zum erwarteten Portfolio / Parent und entsprechen den beim Preview erfassten CAS-Revisionswerten;
4. derselbe Idempotenzschlüssel wurde nicht zuvor für andere Eingaben benutzt;
5. ein exaktes bereits importiertes Quell-/Content-Artefakt wird als Replay zurückgegeben, nicht dupliziert;
6. Document-Original und Receipt bzw. Task und Receipt committen atomar.

## Neue lokale DTO-/Servicegrenze

### Mapping

`confirm_mapping(...)` erhält Connection/Portfolio/Kind, opaque IdentityJSON+Hash, genau eine lokale Ziel-ID, Source-History-Run+Source-SHA, `expected_previous_revision` (`new` für Generation 1) und `idempotency_key`.

Ablauf: frische Owner/All-Scope-Verwalter-Autorität; Historydetail + Sourcehash/Identity prüfen; Ziel scoped sperren und Parent/Portfolio validieren; aktuelle Mappinggeneration sperren; CAS auf Revision; append-only Generation N+1.

Da die bestehende Mappingtabelle keinen separaten Command-Key besitzt, wird kein neues DDL erfunden. Die Mapping-ID/Revision werden deterministisch aus Actor + Idempotenz + Requesthash erzeugt. Vorhandener identischer Datensatz ist Replay, kollidierende Vorgangsreferenz ist 409.

### Import Preview

`preview_import(...)` ist rein lokal und schreibt nichts. Es liest den vollständig verifizierten History-Run, aktuelle bestätigte Mappings und den letzten Receipt. Zusätzlich liefert es einen `preview_hash`, der Source-SHA, Content-SHA, Mappinggenerationen, lokale Target-CAS-Werte und Connection/Portfolio bindet.

### Dokumentimport

`import_document(...)`: kein Providerreload. Bytes müssen dem History-`read_document`-Manifest nach SHA/Größe entsprechen. Neuer normaler Document-Datensatz mit minimaler Provenienz. Erstes Original als `DocumentVersionORM(operation="upload")` über `persist_version_bytes()` in derselben Transaktion. Receipt verweist auf Document+Version. Keine Raw-Providerfelder in Document/Receipt.

### Technikauftrag

`import_technical_order(...)`: gleiche History-/Mapping-/Target-/Preview-CAS-Prüfung. Lokale Task wird über den BaseRepository-no-commit-Pfad erstellt, nicht über `create_task()` mit eigenem Commit. Status immer `open`. Receipt in derselben Transaktion.

## History-Sourceprüfung

Kein Hash wird aus vom Client erneut eingesandten Rawdaten akzeptiert. Der Service entschlüsselt das vorhandene Historydetail und durchsucht nur den bereinigten terminalen Exchange. Für unterstützte Operationen werden vorhandene TEHA-DTO-Parser bzw. deren exakte beobachtete Shapes verwendet; `source_snapshot()` enthält unbekannte Felder vollständig. ExternalIdentity + Source-SHA werden serverseitig rekonstruiert.

Dokumentcontent ist absichtlich nicht im History-JSON. Der `read_document`-Run beweist reference, lieg_nr, SHA-256 und size im `result_manifest`; Importbytes werden lokal erneut dagegen gehasht.

## Autorität, Locks, CAS

- weiterhin nur Eigentümer oder All-Scope-Verwalter, da History installationsweit autorisiert ist;
- Providerfelder sind niemals Autorität;
- SQL-Befehle besitzen eine eigene caller-owned Session und genau einen Commit;
- persistente Mapping-/Importbefehle verlangen die relationale L2-Familie; kein RAM-Fallback;
- PostgreSQL sperrt Parent-/Target-/Mappingzeilen `FOR UPDATE`; SQLite nutzt den Writer vor DML;
- lokale Target-CAS-Werte werden direkt vor DML erneut geprüft; Änderungen erzwingen neue Vorschau.

## Wiederholungspolitik

Kein Provider-I/O, keine automatische Mail, keine externe Schreibaktion und kein blindes Retry. Unvollständige/uncertain History blockiert. Gleicher Key + gleicher Requesthash ist Replay; gleicher Key + anderer Hash ist 409. Geänderte Mappinggeneration/Targetrevision/Sourcehash verlangt neue Preview.

## Shared-Core-Vorschlag – nicht implementieren

Für spätere Receive-Jobs bleibt der bereits dokumentierte schmale `teha_receive`-Family-Adapter (`upper/discover/apply`) die einzige vorgeschlagene Shared-Core-Erweiterung. Dieses Paket ändert keine Shared-Job-/Registry-Datei.

## Tests

Zuerst leichte synthetische SQLite-/lokale History-Gates: Sourcehash/Identity aus vollständigem verschlüsselten Historyrun; Mapping Generation 1/2 + CAS + Replay; fremdes Portfolio/Target; Dokumentoriginal+Receipt atomar; Fehler nach Chunkinsert rollback; Task open+Receipt atomar; exakter Source/Content-Replay; unvollständiger/anderer Historyrun blockiert. Echter PostgreSQL-Gate erst nach abgestimmtem Slot. Keine Browser-/Portal-/Live-Provider-Gates.