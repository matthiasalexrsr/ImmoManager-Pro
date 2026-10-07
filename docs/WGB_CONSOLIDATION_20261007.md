# Wohnungsgeberbestätigung – vorhandene Pakete und nächste kontrollierte Integration

Stand: 2026-10-07. Reines Bestands-/Machbarkeitsinventar durch Astra Ultra. Keine Produktänderungen, keine Tests, keine UI-Steuerung, keine Datenbankzugriffe und keine Paketkopien durchgeführt. Historische Prüfergebnisse sind als solche gekennzeichnet und wurden heute nicht wiederholt.

Aktive Vergleichsbasis: `98cd457b` in `C:/Users/matth/Documents/Codex/2026-10-01/wi/work/party-document-workspace`. Die parallel begonnenen PDF4-Änderungen waren uncommittet und wurden nicht als fertige Schnittstelle angenommen.

## Ergebnis und Entscheidungsvorschlag

**Eine fachlich weit ausgearbeitete Wohnungsgeberbestätigung ist bereits vorhanden. Neuimplementierung von Formular, Vorschau, PDF, Korrekturen oder Idempotenz wäre unnötige Doppelarbeit.** Der vollständigste nachweisbare Featurestand ist die integrierte Fassung bis `f588c7fcba6adc7ff71200b6be072379b7f7e1ff`. Sie enthält gegenüber den ursprünglichen Einzelpaketen die tatsächlichen PDF-, Zugriffssperren- und Browserkorrekturen.

Als gut lesbare lokale Quelle dient:

`C:/Users/matth/Documents/Codex/2026-10-01/wi/work/release-readiness-a-l`

Dieser Checkout steht auf `fc2cf695c512a25ea78102930799fa43ee02c23a` und war beim Inventar sauber. Die unten genannten WGB-Runtime-/UI-/Browserdateien unterscheiden sich im Git-Diff **nicht** von `f588c7fc`. Seine darüber hinaus vorhandenen Release-, Finanz- und Inventarpakete sind keine pauschale Übernahmeempfehlung.

**Das WGB-Paket allein lässt sich jedoch nicht unverändert in die aktive Basis übernehmen.** Dort fehlen insbesondere das Originalarchiv `DocumentVersion`/Chunks, dessen Migration und Recovery-/Retention-Anbindung sowie die Scope-/Writer-Fences des alten Standes. Außerdem unterscheiden sich Rechte-/Benutzerdatenvertrag und Migrationshistorie. Nächster kontrollierter Schritt ist deshalb die klar begrenzte Konsolidierung dieser Voraussetzungen mit anschließendem Reuse des vorhandenen WGB-Pakets. Ein vollständiger Merge des alten Releasezweigs würde zahlreiche aktive Verbesserungen und unabhängige Fachmodelle vermischen.

## Gefundene Entwicklungsstände

| Quelle unter `work/` | Tatsächlicher Stand | Eignung |
| --- | --- | --- |
| `housing-confirmation` | HEAD `b11f9f92d5c157b1c6ed579d79a85e684086cc54`; Backendkern und Handoff, kein eingebundener Produktflow | Historischer Ursprung; enthält noch nicht die späteren PDF-/Account-Commit-Korrekturen. |
| `housing-confirmation-ui` | HEAD `07c375072a607f8694b70a18ddec73f40b8a6220`; Dialog, eigener Client, Tests und Einbindungen | UI-Ursprung; spätere echte Browserkorrekturen fehlen. |
| `housing-ui-root-qa-20261003` | HEAD `faacc6cc2b008f243316d343fa15b1a3e61cde81`; umgesetzte UI in weiterem historischen Zweig | Kein Beleg für höhere WGB-Reife als die anschließend komponierte Fassung. |
| `release-readiness-a-l` | Integrierte Backend-/UI-Fassung einschließlich `c253eaaa` und `f588c7fc` | **Primäre Reusequelle**, Fachdateien gegen Featurecommit abgeglichen. |
| `root-correspondence-integration` | HEAD `75ebd2fb76383705a27a12914e8b8000a47bbf43`; gleiche WGB-Dateien im Git-Vergleich, zusätzliche spätere Kalenderarbeit; ungetrackte `artifacts/` | Alternative Lesekopie, kein zusätzlicher WGB-Funktionsvorsprung festgestellt. |

Die Dateinamensuche fand zahlreiche kopierte/inzwischen weiterentwickelte Worktrees mit denselben WGB-Dateien. Gleiche Dateinamen wurden deshalb nicht als unabhängige fertige Implementierungen gezählt. Raw-Dateihashes unterscheiden sich teils durch Checkout-Zeilenenden; maßgeblich war der Git-Inhaltsvergleich der konkreten Featurepfade.

## Exakte Featurecommits und Reusepfade

| Commit | Inhalt und Reuseentscheidung |
| --- | --- |
| `9b5aadc23d54a4896402865c40880f7fb9007289` | Integrierter Backendkern; entspricht der übernommenen Arbeit aus `b11f9f92`. Fünf Runtime-/Routermodule plus additive Original-/Download-/Offline-Prüfung und Tests. |
| `c253eaaab2f4850eb8474784e825875b14a1b4ef` | **Unbedingt mitnehmen:** Routerregistrierung; Noto-Schriften; korrekte Personenspalte statt schmaler Nummernspalte; Datums-/Unterschriftslayout; Account-Fence bis nach tatsächlichem SQL-Commit; PostgreSQL-Proben mit realen SQL-Accounts. |
| `7d54e541a85ae80a5ec7a22b7a52114bdc437b87` | UI-Grundmodul: Dialog, Formularmodell, Texte, CSS, Commandzustand und Tests. |
| `3b891879e26a2fb8ff5f35ccd58ce98d38430707` | Echter DTO-/HTTP-Client sowie Einstieg aus ContractLifecycle und Mieterwechsel; Modell-/History-/Recoveryanbindung. |
| `f588c7fcba6adc7ff71200b6be072379b7f7e1ff` | **Unbedingt mitnehmen:** echtes Preview-PDF, geschütztes Original nach asynchronem Download, korrekt reserviertes Browserfenster, schmale Dialoglayouts, realer Browserfall. |

Primäre Fachmodule, jeweils relativ zum oben angegebenen Quellcheckout:

- `backend/routers/housing_confirmations.py`
- `backend/services/housing_confirmation.py`
- `backend/services/housing_confirmation_types.py`
- `backend/services/housing_confirmation_validation.py`
- `backend/services/housing_confirmation_render.py`
- `backend/assets/fonts/NotoSans-Regular.ttf`, `NotoSans-Bold.ttf`, `OFL-Noto.txt`, `README.md`
- `frontend/src/features/housingConfirmation/HousingConfirmationDialog.jsx`
- `frontend/src/features/housingConfirmation/housingConfirmationApi.js`
- `frontend/src/features/housingConfirmation/housingConfirmationModel.js`
- `frontend/src/features/housingConfirmation/housingConfirmationText.js`
- `frontend/src/features/housingConfirmation/useHousingConfirmationCommand.js`
- `frontend/src/features/housingConfirmation/HousingConfirmation.css`

Die fachlich abgeschlossenen DTO-/Validierungs-/Renderer-/Formular-/Commandmodule sind die stärksten Reusekandidaten. Service und Router sind ebenfalls vorhandene Implementierungen, benötigen aber den unten beschriebenen konsistenten Unterbau. **Keinesfalls nur die neuen Featuredateien kopieren und fehlende Schutzfunktionen durch leere Adapter ersetzen.**

Vorhandene Integrationsstellen:

- `backend/routing.py`: Import und Registrierung `housing_confirmations.router`, im Quellstand Zeile 44/102.
- `backend/services/document_versions.py`: `publish_generated_original(..., metadata_extra=...)`; Sondergrenze gegen generischen Upload/Restore von Housing-Originalen.
- `backend/services/document_version_validation.py`: featurebezogene Metadatenprüfung beim Offline-/Originalvalidator.
- `backend/routers/files.py:248`: reservierter virtueller Pfad `housing-confirmations/` wird aus verifizierten Originalbytes aufgelöst, nicht aus einer überschattenden physischen Upload-Datei.
- `frontend/src/components/ContractLifecycle.jsx:839–861`: Vertragseinstieg mit exakter Contract-ID und Fokus-Auslöser.
- `frontend/src/features/tenancyWorkflows/TenancyChangeFile.jsx:259`: Einzugseinstieg nur bei `move_in|turnover` und `next_contract_id`.
- `frontend/src/pages/TenancyWorkflows.jsx:674`: gemeinsamer Dialog, Übergabedatum ausschließlich als Referenz.
- `frontend/src/api.js`: authentifizierte `getBlob`-/`postBlob`-Schnittstellen.

## Erfüllter Nutzerablauf und stabile Schnittstelle

Die folgende Tabelle beschreibt **gelesenen vorhandenen Code**, keine neu ausgeführte Abnahme.

| Anforderung | Vorhandenes Verhalten |
| --- | --- |
| Vertrag und Einheit | Service lädt den exakt autorisierten Vertrag und prüft Property-/Unit-/Tenant-/Portfolio-Beziehungen; widersprüchliche Bindungen werden verweigert. |
| Tatsächlicher Einzug | `actual_move_in_date` bleibt in den Sourcevorschlägen leer. Vertragsbeginn und geplanter Übergabetag sind nur Referenzen; der Nutzer erfasst `move_in_date` ausdrücklich. |
| Personen | Geordnete nicht leere Liste vollständiger Namen. Hauptmieter wird nur bewusst als Vorschlag hinzugefügt. Keine erfundenen Personen aus Personenzahl, keine Namenszerlegung oder Deduplizierung gleichnamiger Personen. |
| Wohnungsgeber / Eigentümer | Eigener Name/Anschrift des Wohnungsgebers; `owner_same_as_provider` als echtes boolesches Feld; abweichender Eigentümer verlangt `owner_name`. Ausstellername und Rolle `housing_provider|authorized_person` separat. |
| Vorschau | Zustandsfreie normalisierte Fachvorschau und echtes Preview-PDF. Review bindet Quelldaten/Revisionen, Eingaben, Korrekturbezug, Formatversion und PDF-SHA256. Jede fachliche Änderung entwertet die Vorschau. |
| Freigabe | Alle drei Bestätigungen zu tatsächlichem Einzug, Befugnis und Personenliste notwendig. Rechte/Quellen werden vor Mutation erneut geprüft; keine stillschweigende Freigabe. |
| Unveränderliches Original | Atomare Veröffentlichung als normales `Document` vom Typ `housing_confirmation` plus archiviertes `DocumentVersion`-Original und 64-KiB-Chunks. PDF und Manifest werden beim Lesen überprüft. |
| Korrektur | Neues Dokument/Original mit `correction_of={document_id,version_id}`. Altes Original bleibt bytegleich; Korrekturbezug muss zum selben autorisierten Vertrag gehören. |
| Wiederholung | Actor + Idempotency-Key ergeben eine deterministische UUID. Identischer verlorener-Reply-Retry liest dasselbe verifizierte Original; gleicher Key mit anderem Inhalt wird zurückgewiesen. UI hält den eingefrorenen Originalbefehl für bewusstes unverändertes Wiederholen. |
| Zugriff/Wechsel | 401/403/404 verwerfen private Anzeige und Retry. Vertrags-/Benutzer-/Rollen-/Portfolio-Wechsel neutralisieren den bisherigen Inhalt render-synchron und brechen Anfragen ab. |
| Historie | Servercursor `after`, `limit` 1–500 (UI 25), Filterung nach Vertrag/archiviertem Dokumenttyp vor SQL-Seitenlimit. Später editierte normale Dokumenttitel verändern den Originalbeweis nicht. |

Routerprefix: `/contracts/{contract_id}/housing-confirmations`.

- `GET /source`: Quellwerte, Vorschläge, Policy und `source_etags`.
- `POST /preview`: `PreviewRequest`; strukturierte geprüfte Fassung.
- `POST /preview-pdf`: gleicher Request, private PDF-Bytes mit `X-Content-SHA256` und `X-Review-SHA256`.
- `POST` auf den Prefix: `SaveRequest`; Originalveröffentlichung.
- `GET` auf den Prefix: Cursorhistorie.
- `GET /{document_id}/download`: authentifizierte verifizierte Originalbytes.

`CertificateData` umfasst `housing_provider_name`, `housing_provider_address`, `owner_same_as_provider`, optional `owner_name`, `move_in_date`, `issue_date`, `apartment_address`, optional `apartment_label`, `issuer_name`, `issuer_role`, `residents:string[]`. `PreviewRequest` ergänzt `source_etags` für Portfolio/Vertrag/Objekt/Einheit/Mieter und optional Wizardrevision sowie optional `correction_of`. `SaveRequest` ergänzt `idempotency_key` (1–100 Zeichen), 64-stelligen `review_hash` und drei strikte `confirmed_*`-Booleans.

Archivextension: `metadata_snapshot.housing_confirmation`, Schema `housing-confirmation/1`, PDFformat `housing-confirmation-pdf/1`. Diese Beweisstruktur einschließlich Hashes/ID-Ableitung ist ein bestehender Schnittstellenvertrag; nicht nebenbei ändern.

## Tatsächliche Integrationslücken zur aktiven Basis

| Grenze | Quellpfade / vorhandener Ursprung | Aktiver Befund und notwendige Entscheidung |
| --- | --- | --- |
| Originalarchiv | `backend/db/document_version_models.py`, `services/document_versions.py`, `services/document_version_validation.py`, `routers/document_versions.py`; Ursprung `4e36b07fd980ccff0865086dbe63c1864cb9be19` | Alle vier fehlen aktiv. Normale `Document`-Daten und eine Dateivorschau ersetzen kein unveränderliches Original. Archiv mit Transaktion, Constraints, Triggern, Download, Recovery und Retention als kohärentes Paket konsolidieren. |
| Portfolio-Scope | `services/portfolio_scope.py`, `services/portfolio_references.py`, `db/access_models.py`; Ursprung `500bf633b09e30b4e20674ca25d4492eb3b70312` | Scope-/Accessmodule und Portfoliofelder am aktiven UserRead fehlen. Quellservice erwartet `current_scope`, `refresh_scope`, `scope_context`, `scope_from_user`; autorisierte SQL-/Memoryabfragen müssen dieselbe Bedeutung erhalten. |
| Atomare Writer / Privacy | `services/tenant_privacy_fence.py` aus `c0d95f433cf02ac0454008e9d9d680e021f0b39d`; `contract_occupancy.py` aus `d972ec72`; `tenant_privacy.py`, `services/payments.py` | Module fehlen aktiv. Lock- und Transaktionsgrenzen nicht durch vorhandenes `backend/concurrency.py` namensähnlich ersetzen: benötigt sind `begin_writer`, Parentfence, Accountfence bis Commit und vollständige Retention. |
| Transitive Fencedaten | `db/auth_models.py`, `db/operational_models.py`, `db/operational_job_models.py`, `db/tenancy_workflow_models.py` | Die Fencedatei importiert diese tatsächlich. Ein vollständiger Direktreuse hängt daher auch von diesen Modellen ab. Vor Implementation eine begrenzte Foundation-/Adapterentscheidung treffen; kein spontanes Nachkopieren weiterer Releasepakete. |
| Wizardquelle | `db/contract_wizard_models.py`, `services/contract_wizard.py`, `services/contract_attachment.py`; Ursprung `d972ec7286bd81c16a2e573dc667ce4ffce2d6cf` | Aktiver separater Mietvertrag-Wizard ist keine Schnittstellenidentität. `_wizard_snapshot` fragt im SQL-Pfad `ContractDraftORM` ab, auch wenn kein veröffentlichter Wizardstand existiert. Fehlende Tabelle lässt sich nicht als bloß fehlender Vorschlag behandeln. Entweder geprüfte Foundation übernehmen oder ausdrücklich kompatible optionale Quellenanbindung definieren. |
| Kleine Helfer mit großer Importkette | `services/concurrency.py:etag`, `services/tenancy_workflow.py:encode_cursor/decode_cursor` | Beide Pfade fehlen aktiv. Ein einfacher Cursorgebrauch darf nicht versehentlich den kompletten Workflow-Unterbau importieren; exakte Wiederverwendung/saubere Abgrenzung festlegen. |
| Geschütztes Streaming | `routers/datev.py:PrivateDownloadResponse`, Scopeprüfung vor/zwischen Bytes | DATEV-Router fehlt aktiv. Die benötigte Streaminghilfe ist nicht der ganze DATEV-Fachprozess; Schutz- und Cleanupvertrag gezielt konsolidieren. |
| Rollenvertrag Backend | Quell-`permissions.py:may_write_resource(role, resource)` | Aktiv existiert `may_write(role, path)` mit `WRITE_AREAS`, kein `may_write_resource`. WGB-Freigabe verlangt gleichzeitig Contracts- und Documents-Schreibrecht. Ein Adapter muss diese beiden realen Rechte prüfen und darf nicht die gesamte aktuelle Rollenmatrix unbemerkt ersetzen. |
| Rollen-/Benutzervertrag Frontend | `utils/writeAccess.js:authMayWrite`; User `write_permissions`, `portfolio_access`, `portfolio_ids` | Aktiver Context liefert `{user,write,role,isAdmin,isReadonly}`, kein `canWrite`; UserRead besitzt die neuen Scope-/Capabilityfelder nicht. Dialogbindung/Forgetpfad und Rechteprüfung müssen auf den tatsächlich integrierten Authvertrag abgestimmt werden. Einfaches Kopieren würde auf Legacy-Rollenfallback fallen und aktuelle pathbasierte Grants nicht explizit nutzen. |
| HTTP-Blobclient | Quell-`api.getBlob/postBlob` | Am untersuchten aktiven Commit fehlen beide. PDF4 kann diesen Bereich gerade verändern; nach dessen Commit den finalen Vertrag neu abgleichen und denselben authentifizierten Client nutzen. |
| Einstieg | `ContractLifecycle.jsx`, `TenancyWorkflows.jsx`, `TenancyChangeFile.jsx` | Diese UI-Familien fehlen aktiv. Der eigenständige Housing-Dialog kann kontrolliert aus der vorhandenen `Contracts.jsx` geöffnet werden; dafür muss nicht sofort die komplette Vertragsverlängerungs-/Kündigungsoberfläche übernommen werden. Der zweite Einstieg aus einem echten Einzug benötigt den entsprechenden künftig integrierten Workflowvertrag `next_contract_id`. |

Vorhandene kompatible Grundlagen: `get_store()`, `auth.get_user_by_id()`, Pydantic 2, SQLAlchemy, ReportLab, Contracts/Property/Unit/Tenant/Portfolio/Document-Modelle und heutige React-Grundbausteine. Diese Funktionen sind vorhanden, aber ihre vollständige transaktionale/Scope-Semantik ist damit noch nicht als gleich bewiesen.

### Migrationen: „WGB hat keine Migration“ gilt nur für die damalige Basis

Das Feature legt keine eigene WGB-Tabelle an. Benötigt wird das bestehende Archivschema aus:

`backend/db/migrations/versions/y1a2b3c4d5e6_document_versions.py`

- `document_versions`: Originalidentität, Version/Predecessor, Actor+Command, Request/PDF-SHA256, Größe, Metadatensnapshot und genaue Elternbindung.
- `document_version_chunks`: 64-KiB-Blöcke mit Versions-/Portfoliobindung.
- Uniques `(document_id,number)` und `(actor_id,idempotency_key)`.
- SQLite-/PostgreSQL-Trigger verweigern UPDATE/DELETE; Downgrade mit vorhandenen Originalen wird verweigert.

Historische Kette: `y1...` hängt an `x1..._private_form_drafts`, diese an `w1...`, davor liegt u. a. `v1..._reviewed_contract_workflow`. Portfoliozugriff stammt aus `o1..._portfolio_access`. Der aktuelle Checkout besitzt diese Migrationen nicht; sein aktiver späterer Pfad endet im Dateibestand bei `d7a2f9c4e681_postgres_decimal_amounts.py`, dessen Parent `8c4d2e6f1a93` ist.

**Die Migrationslinien sind auseinanderentwickelt, nicht nur unvollständig hintereinander:** Der aktive Stand enthält z. B. `4f8...billing_usage_periods`, `6e2...document_tenant_link`, `7b3...contract_rent_periods`, `a1d...payment_allocations` und `d7a...postgres_decimal_amounts`, die im alten WGB-Releasezweig nicht vorkommen. Umgekehrt enthält dieser zahlreiche andere Fachmigrationen. Vor Übernahme muss eine additive, zum aktiven Schema passende Revisions-/Mergeentscheidung dokumentiert werden. Das alte `y1` unverändert allein hinzulegen lässt einen fehlenden Parent zurück; die gesamte alte Kette einzuspielen würde weitere Fachpakete importieren. Hier wurde keine solche Migration ausgeführt oder neu entworfen.

### Recovery, Retention und PDF gehören zum Mindestumfang

Quellpfade für die Original-Erhaltung: `services/tenant_document_versions.py`, `services/tenant_privacy.py`, `services/recovery_sessions.py`, `services/full_recovery.py`, `services/document_version_validation.py` und zugehörige Repository-/Referenzprüfungen. Der historische Code exportiert den exakten Belegbezug und bewahrt weitere frei eingegebene Haushaltsnamen im Original, ohne daraus erfundene Tenant-IDs abzuleiten. Profilanonymisierung ist keine Beleglöschung. Ohne integrierte Recovery-/Retentionprüfung wäre die ursprüngliche Anforderung an ein unveränderliches Original nur teilweise erfüllt.

Renderer braucht ReportLab (aktiv bereits deklariert) und die beiden lokalen Noto-Dateien samt Lizenz; keine Betriebssystemschrift oder Laufzeitdownload. Der zugehörige Font-Handoff begrenzt die nachgewiesene Abdeckung auf Latein/Griechisch/Kyrillisch; universelle Schriftsysteme/Formgebung nicht behaupten. `pdfplumber` wird für die vorhandenen Layouttests benötigt, ist keine neue fachliche Runtimeabhängigkeit.

## Vorhandene Tests und historische Beweise zur Wiederverwendung

Backend:

- `backend/tests/test_housing_confirmation.py`: Sourcevorschläge, manuelles Einzugsdatum, Preview/Publish/Replay, Stale-ETags, Korrektur, Cursorliste, manipulierte Metadaten, viele Unicode-Personen, HTTPrechte, virtueller Dateischatten, exakter Wizardbezug, Rollback nach Chunks, Rechteentzug, tatsächlicher SQLite-Commitfence, Retention, nachträgliche normale Dokumentmetadaten und Verbot generischer Ersatzversionen.
- `backend/tests/test_housing_confirmation_postgres.py`: tatsächliche SQL-Accounts, atomarer Publish/Replay, stale Source und gleichzeitiger Same-Key-Publish.
- `backend/tests/test_housing_confirmation_pdf_layout.py`: reale PDFtexte und Koordinaten, vollständige Namen in breiter Spalte, 45-Personen-Mehrseitigkeit, Datums-/Unterschriftsbereich und Schriftzeichen.
- Foundationregressionen: `test_document_versions.py`, `test_document_versions_http_schema.py`, `test_document_versions_postgres.py`, `test_document_version_recovery.py`, `test_document_version_recovery_postgres.py`, `test_tenant_document_versions.py`, `test_tenant_document_versions_review.py`.

Frontend:

- `frontend/src/test/HousingConfirmationModel.test.js`
- `frontend/src/test/HousingConfirmationCommand.test.jsx`
- `frontend/src/test/HousingConfirmationDialog.test.jsx`
- `frontend/src/test/HousingConfirmationApiContract.test.js`
- Integrationsfälle in `ContractLifecycle.test.jsx` und `TenancyChangeFile.test.jsx`.
- `frontend/e2e/housing-confirmation.pw.mjs`, basierend auf `demoFixtures.mjs`: tatsächlicher Einzug, 45 Personen, Preview ohne Archivoriginal, verlorene erfolgreiche Antwort, unveränderter Retry, privater Download, Korrektur und bytegleich altes Original.

Historische Belege im Quellcheckout, heute nur gelesen:

- `docs/WOHNUNGSGEBERBESTAETIGUNG_PLAN_20261002.md`: Nutzerablauf und Beweisvertrag.
- `docs/WOHNUNGSGEBERBESTAETIGUNG_BACKEND_HANDOFF_20261002.md`: ursprüngliche **34 bestanden, 2 definierte Storevariantenskips**, PostgreSQL ausgeführt; keine Vollreleasefreigabe.
- `docs/WOHNUNGSGEBERBESTAETIGUNG_UI_HANDOFF.md`: ursprüngliche UI-/Integrationsgates (61 beziehungsweise 105 Tests mit angrenzenden Workflowtests), nicht heutiger aktiver Bestand.
- `docs/HOUSING_ROOT_REVIEW_20261003.md`: nach tatsächlichen Gegenbeispielen korrigierte PDF-/Accountfence-Fassung; **38 bestanden, 3 definierte Storevariantenskips**, reale PostgreSQL-Proben; zusätzlich gerenderte PDFkontrolle.
- `docs/HOUSING_CONFIRMATION_COMPOSITION_20261003.md`: **ein komplexer echter Edge-/SQLite-Browserfall bestanden**, 45 Personen, 1440/360/320 px, Preview/Original/Korrektur/Lost-Reply; **20 direkte UI-/Client-/Model-/Commandtests bestanden**. Belegt dieses Paket, nicht alle historischen Releasefamilien.

## Empfohlene nächste kontrollierte Schritte

1. **PDF4 abschließen und aktive Basis festhalten.** Insbesondere Blob-/Viewer-/API-Vertrag erneut vergleichen. Neue WGB-Arbeit darf diese gerade geprüften Komponenten nicht durch historische Fassungen ersetzen.
2. **Ein abgegrenztes Foundationpaket planen:** immutable Dokumentoriginale mit passendem aktivem Migrationspfad, aktuellen Rollen, autorisierter Elternbindung, Transaktion/Accountfence, geschütztem Download, Retention und Recovery. Die oben genannten vorhandenen Implementierungen/Testfälle als Quelle verwenden. Transitive Wizard-/Scheduler-/Workflowabhängigkeiten explizit entscheiden; keine neue parallele Archivtechnik entwickeln und keine no-op-Sicherheitsadapter.
3. **WGB-Fachmodul aus der vollständigen `f588c7fc`-Fassung integrieren.** DTOs, Review-/Requesthashes, PDF, Originalpublikation, Korrektur und Frozen-Retry gemeinsam übernehmen. Vorhandene deklarative Fachgrenzen beibehalten; bei einer notwendigen Adapterentscheidung die originalen Gegenbeispiele als Integrationsnachweis verwenden.
4. **Bestehenden Dialog an den aktuellen Vertragseinstieg anbinden.** Dünne Aktion in aktiver Contracts-Oberfläche mit exakter ID; kein Zwang, dafür alle älteren Vertrags-Lifecyclefunktionen zu übernehmen. Einzugseinstieg erst an einen tatsächlich vorhandenen neuen-Vertrag-Workflow binden; tatsächliches Einzugsdatum bleibt im Housingformular manuell. Rollen-/Scope-Wechsel und aktuelle Authfelder vollständig einbinden.
5. **Danach Abnahme auf isolierter Datenkopie:** vorhandene Feature-/Foundationregressionen, SQLite und echtes PostgreSQL für Atomarität/gleiche Keys, beschädigte Originale und Recovery, tatsächliche Browserfolge Vertrag → mehrere Personen/abweichender Eigentümer → PDFvorschau → bewusste Freigabe → Lost-Reply-Retry → Korrektur → unverändertes früheres Original; 320/360/1440 px und langes Mehrseiten-PDF. Diese Schritte wurden im Inventar ausdrücklich noch nicht ausgeführt.

**Konkrete Liefergrenze:** Wiederverwendung ist gut möglich und fachlich weit vorbereitet. Der Aufwand liegt primär in der Konsolidierung des fehlenden Original-/Rechte-/Schemasystems, nicht im Neuerfinden der Wohnungsgeberbestätigung. Eine Aussage „nur noch Button einbauen“ wäre durch den aktiven Bestand nicht gedeckt.
