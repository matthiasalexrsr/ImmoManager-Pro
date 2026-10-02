# Plan: dauerhafte private Adapterhistorie und Parameterkatalog

Stand 02.10.2026. **Nur Planung, keine Implementierung.** Gelesen: `work/root-correspondence-integration`, HEAD `0becc289998ae5b2f7836e84515c27217f28b7d2`, einschließlich der tatsächlichen Integrations-, Config-, UI- und Recoveryquellen. Grundlage: `work/adapter-extraction-inventory-20261002.md`. Keine Root-/Produktänderung, Anmeldung, privaten Konfigurationswerte, externe Aktion oder Modelldownloads. Die unten dokumentierten SHA256 beziehen sich auf tatsächliche Dateibytes. Der parallel veränderte Parentretentioncode ist nicht Teil dieses Plans. Abschlussstand der Sourcefingerprints: HEAD `63dc1103567be1cd0d295342153d565bcdee6473`. Vergleich gegen 0becc: inventarisierte Manager-/Provider-/Router-/UI-/Recoverydateien unverändert; Settings ergänzt unabhängig vier Bank-Discoverybudgets. Die verwendeten Integrations-/AIdefaults sind identisch, ihre unten genannten Settingszeilen wurden auf den Abschlussstand aktualisiert.

## 1. Belegter Bestand und Ziel

`backend/services/integrations/manager.py:22-24,155-196` hält Runs in RAM, verwirft ab201 ältere Einträge und verliert alle beim Neustart. `/integrations/{id}/history` liefert maximal100 ohne Cursor (`routers/integrations.py:126-134`); Metriken zählen dieselbe begrenzte Liste. Eine Providerexception vor `_append_history` hinterlässt keine Historie. Mailpayloads werden bewusst als `{}` erhalten; andere Payloads sind nur top-level gegen Manifestsecretkeys maskiert, `details` wird unbereinigt kopiert.

Die atomare private JSONkonfiguration (`integrations/config_store.py:143ff`) ist bereits persistierbar, aber keine Runhistorie. Das Schema nennt nur Pflicht-/Secretkeys und Capabilities (`manager.py:77-88`). Die UI besitzt keine durchblätterbare History; nach einem Lauf liest sie nur `history?limit=1` (`pages/Integrations.jsx:99-116`). Bei zwei gleichzeitigen Läufen kann deren Zeitstempel zum anderen Aufruf gehören.

**Ziel:** Alle vom Manager angenommenen Versuche dauerhaft privat erfassen, alle tatsächlich gelieferten erlaubten JSONfelder ohne Präfix-/Arraykürzung erhalten, alle Runs per Cursor erreichen und wirkliche Config-/Payload-/Returnparameter mit Quellen katalogisieren. Keine zweite Zahlungs-, Bank-, Outbox- oder Dokumenthistorie. Andere Dienste, die den Manager nicht verwenden, gelten nicht automatisch als abgedeckt. Bank-, KI- und Datenschutzpakete bleiben bei ihren bisherigen Besitzern.

Vollständig bedeutet hier vollständiger semantischer JSONsnapshot **nach ausgewiesener Privacy-/Secretpolicy**. Original-HTTPbytes, SMTPdialog, Zustellung oder bereits vor dem Manager verlorene KI-Felder werden nicht behauptet. Verlorene alte RAMhistorie ist nicht rekonstruierbar; die UI nennt den Beginn der dauerhaften Erfassung ausdrücklich.

## 2. Speicher-, Ausführungs- und Verschlüsselungsentscheidung

Eine neue SQL-Journalfamilie am bestehenden privaten `DATABASE_URL`, keine wachsende JSONdatei und kein neues Backupformat. Kurze eigenständige Historysessions werden injiziert und vor Provider-I/O geschlossen. Keine geerbte offene FinanceSession oder global ungescopte Domaincollection.

Auch ein expliziter Domain-MemoryStore soll seine **History** am konfigurierten SQLjournal behalten: `settings.py:78,135` hat einen von Domain-Memory unabhängigen Default `sqlite:///./immo_manager.db`; `dependencies.py:45-51` schaltet damit nur Domainpersistenz um. Der Historybootstrap prüft/erstellt ausschließlich seine Familie. SQLfehler erlauben keinen stillen RAMfallback. Nur bewusst injizierte Unitfixtures verwenden einen flüchtigen HistoryStore. Das macht übrige Memory-Geschäftsdaten ausdrücklich nicht dauerhaft oder vollständig sicherbar.

Vorgesehene Familie (endgültige Tabellennamen im Paket festschreiben):

- `integration_history_heads`: pro Integration kurze serialisierte Journalgrenze, monotoner Run-/Eventindex und atomare Metadatenzähler. PostgreSQL Rowlock bzw SQLitewriter; kein Lock über Netzwerk. Sie erlaubt einen **Commitreihenfolge**-High-water-Mark und stabile Statusfilterseiten ohne globales COUNT oder lang offene Paginationtransaktion. Normales SQLsequenz-ID-Allokieren allein wäre wegen noch nicht committeter kleinerer IDs kein solcher Snapshotbeweis.
- `integration_runs`: unveränderliche Run-ID, Integration, serverseitiger Actor-ID-Auditwert, Herkunft, Scopekind, optionale autorisierte Subjectbindung, UTCbeginn, Policy-/Katalog-/Envelopeversion und bereinigte Configsnapshotbindung. Keine Klartextnamen/Mailadressen als Indizes und kein löschender User-FK.
- `integration_run_events`: append-only nummerierte Ereignisse accepted/execution_started/completed/rejected/observation_failed/outcome_uncertain, Unique(run_id,event_number), vorherige Ereignisprüfsumme. Originales Provider-success/message/details getrennt vom lokalen Ausführungszustand. AbschlussCAS exakt an ursprünglichen Run, Request und Configbindung.
- `integration_run_chunks`: authentifiziert verschlüsselte positionsgebundene Request-/Response-/private Schemaartefakte; Unique(event_id,kind,position), erwartete Anzahl/Bytes/SHA über bereinigte Bytes. Kein veröffentlichter Hash eines geheimen Originals/Passworts.

G44-Stable-Keyring verwenden, mit eigenem HKDF-/AEAD-Kontext und versions-/Key-ID-tragendem Envelope. `form_draft_crypto.py:16-55` ist ein Muster; dessen Formdraftidentität darf nicht wiederverwendet werden. AAD bindet Integration, Run, Actor, Scope/Subject, Ereignis, Artefaktart/Chunkposition und unveränderliche Metadaten. Wrong/missing Key oder Bindungsfehler wird fest typisiert und behebbar, niemals Plaintextfallback, `***` als Datenersatz oder SQL-/Credentialwert im Log. JWTwechsel verändert diese Schlüssel nicht.

Ausführung:

1. Tatsächlichen Actor/Scope frisch prüfen, vollständige Eingabe/JSONvalidität und immutable Configauswahl bereinigen. Keine Actor-/Portfolioautorität aus PayloadJSON.
2. accepted plus Request/Configbeobachtung atomar persistieren. Schreibfehler bedeutet **null Provideraufrufe**. Disabled/planned/ungültige Versuche werden mit festem Ablehnungsgrund erfasst.
3. Vor Provideraufruf Berechtigung erneut frisch prüfen und execution_started dauerhaft schreiben. Keine Auth-/Domain-/DBsperre über Provider-I/O; vorhandene SMTP-/Outbox-DATA-Grenzen nicht verändern.
4. Ganze erlaubte Rückgabe bereinigen und genau einen atomaren Abschluss anhängen. Providerexceptions bekommen sichere feste Fehlerkategorien, keine ungeprüften Exceptiontexte/Tracebacks als Historyinhalt. Keine automatische Wiederholung.
5. Ein Grantentzug nach externer Aktion darf den sicheren **genau-run** Ergebnisabschluss nicht verhindern. Dafür schmale run-/tokengebundene CAS, keine allgemeine interne Scopefreigabe. Private Antwortpublikation bleibt anschließend 401/403-fähig.
6. Crash oder Abschluss-Schreibfehler nach execution_started bleibt outcome_uncertain/history_outcome_unconfirmed. Kein erfundenes „nicht versandt“, kein blindes Replay. Fremder SMTPserver und lokale DB können nicht gemeinsam atomar committen; diese reale Beobachtungsgrenze wird erklärt. Neustart/Restore schließt alte offene Versuche als ungewiss, ohne externe Aktion neu auszuführen.

## 3. Rechte, Revokation und rekursive Bereinigung

Die sechs heutigen Manageradapter sind installationsweit, ohne geprüfte Portfoliozuordnung. `routers/integrations.py:10-28` verlangt Owner oder All-Scope-Verwalter und Installationsscope; selected Manager/Buchhaltung/Techniker/Readonly sind ausgeschlossen. Das bleibt für LIST/ID/config/schema/history/metrics/clear/export bestehen. Bestehende berechtigte All-Verwalter dürfen weiterhin die globale Historie lesen. Actorbindung ist Provenienz, keine neue scheinbare Own-only-Freigabe.

Ein später subjectgebundener Provider braucht einen registrierten **serverseitigen Resolver** mit tatsächlichen aktuellen Document-/Account-/Contracteltern. Erst dann scope_kind=portfolio und konkrete Originalsubjectbindung. Aktuelle Parent-/Grantbindung muss jede Liste/ID/Publikation erneut einschränken; historisches Portfolio allein reicht nach Parentmove nicht. Freie property_name/listing/portfolio_id-Werte sind kein Beweis. Mehrdeutige globale Daten erhalten keinen geratenen Scope. Solche Bindungen brauchen dann die bestehende Reparent-/Retentionintegration; die sechs gegenwärtigen Adapter bleiben in diesem Paket global.

Router gibt den wirklichen Authactor an den Manager. Die Signatur der `IntegrationServiceFacade.run_action(id,payload)` bleibt; Runtimecontext stammt aus geprüftem Authkontext oder einem ausdrücklich registrierten internen Servicekontext. Unbekannter produktiver Aufruf ohne Kontext wird abgelehnt, nicht still actor=system. Unitmanager verwenden explizite Testkontexte.

Private JSONantworten bleiben hinter CheckedPublicationRoute mit fresh Scope und AccessToken vor Veröffentlichung (`checked_publication.py:23-39`); private,no-store/Vary:Authorization. Downloads erst vollständig in neuer ownerprivater Datei verifizieren, dann vorhandenes PrivateDownloadResponse-Muster: Token/Rolle/Scope vor Headers und jedem Chunk, kein ScopeContext über Yield, Late-Denial erkennbar. Cleanup bei Erfolg, Abort, Deadline und Fehler; niemals fremde Datei überschreiben.

`private_json_values`, JsonSchemaObserver und echte PrivateJsonExchange wiederverwenden (`providers/exchange_observation.py:83,127,171`; `schema_observation.py:126`). Nicht `_safe_config` allein:

- Alle verschachtelten Objekte/Arrayelemente/zusätzlichen erlaubten Felder beobachten. Secretbranches und bekannte Credentialliterale auch in Texten und Keys entfernen; Auth-/Cookieheaderwerte niemals speichern. Aktuelle und für den Lauf ausgewählte Configsecrets nur transient zur Redaktion verwenden.
- Request, details, message, Nichtsecret-Configsnapshot und private Schemazeiger gemeinsam bereinigen. Dynamische Feldnamen bleiben privat.
- Mailpayload bleibt kompatibel `{}`: keine neue pauschale Speicherung von recipient/subject/HTML-/Textbody. Policy weist diese Auslassung aus. Outboxoriginale bleiben separate bestehende Belege.
- Unbekannte beliebige Secrets ohne erkennbaren Key/bekanntes Literal sind nicht automatisch erkennbar. Keine Garantie beliebiger geheimnisfreier Rawdaten. Policy-/Formatversion, Auslassungsarten und Erfassungsabdeckung je Run anzeigen.
- Budgets pro Operation/Artefakt/Seite: positive Integerbytes, finite positive Zeiten, begrenzte RAM-/Temp-/SQLbuffer. Expliziter korrigierbarer Fehler oder fortsetzbare Seite statt erfolgreicher Präfixspeicherung. Kein Run-/Jahres-/Gesamtbestandslimit oder automatische TTLlöschung; keine neuen willkürlichen Configceilings.

## 4. Kompatible API und UI

run behält success/message/gegebenenfalls details; additiv run_id/history_status/history_recorded. SMTP accepted/not_sent/unknown sowie delivery_confirmed=false bleiben. Statuslesen, Cursorretry, Reload oder Export löst keine Aktion erneut aus.

`GET /{id}/history?limit=20` behält items und bisherige Itemfelder id/integration_id/success/message/payload/details/created_at. Additiv next_cursor/has_more/history_started_at/history_complete_from/projection. Neue UI nutzt projection=summary; alte Calls behalten vollständige bereinigte Recordprojektion. Übergroße Legacyseite: bezifferter page_size_exceeded mit kleinerer Seite/Einzeldetail als Korrektur, keine stillen Kürzungen.

Run-Keyset anhand des committeten monotonen Runindex (UTC+ID als Display-/Tie-breakvertrag), limit+1, passende Integration-/Scopeindizes. Cursor bindet Integration/Filter/Projektion/Sortierung, Actor und aktuelle Rechte sowie initialen Event-/Run-High-water-Mark. Statusfilter wird gegen den letzten Event **bis diesem Watermark** ausgewertet, sonst könnten Abschlüsse zwischen Seiten Einträge verschieben. Kein OFFSET, globales preload/COUNT oder unbounded cursor-RAM. Grant-/Actor-/Filterwechsel invalidiert Cursor.

Additiv autorisierter Einzelrun-GET und privater Runexport mit Manifest sowie ganzen bereinigten JSON-/Schemaartefakten. Gesamtarchiv benutzt denselben iterativen Keyset-/Chunkpfad bis EOF. Fremd-/unbekannte IDs: konsistente 404/403 ohne Leck. metrics zählt dauerhaft, nicht UIbuffer; zusätzlich runs_pending/runs_uncertain. Legacy runs_failed meint weiterhin nicht-erfolgreich, neue UI nennt dies nicht pauschal Sendefehler. Health/config-GETs sind keine Runs.

**Clearentscheidung:** Bisheriges explizites administratives DELETE bleibt wirklich löschende **Telemetrie** mit `{id,cleared}`; nicht nur verdeckt eine Ansicht leeren. Keine Autolöschung. Minimaler eigener privater Clearnachweis (Actor/Zeit/Integration/tatsächlicher Count/bereinigter Manifestdigest) bleibt. Noch laufende Runs blockieren mit Busy/Konflikt, Parent-/Retentionsbelege dürfen nicht mitgelöscht werden. Keine Zahlungen/Outbox/Workflow-/Dokumentoriginale berühren. Notwendige Retentionbindung verlangt Ablehnung statt Umgehung. UI erklärt die Wirkung vor bewusstem Klick.

Zwei scoped UIcomponents: IntegrationHistoryPanel und IntegrationParameterPanel. Cursornavigation, Loading/Error/Retry, Einzelrun/Export, klare ungewisse Ergebnisse, sofortiges Leeren/Abort bei Actor-/Grantwechsel, stale Responses verwerfen. Runzeit gehört zur erhaltenen run_id, nicht latest=1. Kein automatischer SMTPtest; vorhandener UI-Demopayload ist keine Adapterkonfiguration. DE/EN/ES, mobile/dark/Tastatur, Providertext nur sicher als Text rendern.

## 5. Vollständige tatsächliche Parameterinventur

Additiver statischer Katalog je Feld: name/location/expected_type/default/required/secret/effective/validation/source(file,line,symbol)/evidence_kind. Quelle ist Katalogmetadatum, konkrete Values bleiben privat. Erwarteter Typ ist keine Behauptung schon vorhandener strikter Typprüfung. Unbekannte verschachtelte Config bleibt erhalten, aber stored_unknown/not_consumed; keine erfundene Unterstützung. Kataloglesen lädt keine Modelle, sendet nichts und prüft keinen fremden Server.

### 5.1 Providerconfig

| Adapter / Schlüssel | Echter Default / Verwendung | Typ / tatsächliche Validierung / Quelle |
|---|---|---|
| email.smtp_host | `""`, erforderlich | String; Host/Header; providers.py:22; email_service.py:76-82,117 |
| email.sender_email | `""`, erforderlich | Mailboxstring; **Mappingdefault leer**, nicht Legacydataclass-noreply; email_service.py:120-124 |
| email.smtp_port | 587 | int(str(value)), bool abgewiesen,1..65535; email_service.py:81,112,118 |
| email.smtp_timeout_seconds | 20 | float-Konversion, bool abgewiesen,finite1..60; email_service.py:88-92,113,126 |
| email.smtp_user | `""` | String max1024; User/Password gemeinsam oder beide leer; email_service.py:95,97,119 |
| email.smtp_password | `""` | Secretstring max4096; *** kein Passwort; Auth nur TLS/SSL; email_service.py:96-101,120 |
| email.smtp_use_tls | True | bool oder true/false-String; nicht zugleich SSL; email_service.py:56-61,83-87,121 |
| email.smtp_use_ssl | False | wie TLS; email_service.py:122 |
| email.sender_name | `"ImmoManager Pro"` | Headerstring; email_service.py:94,124 |
| contract-wizard.template_count | 3, nur Health.templates | keine strikte Typvalidierung, keine echte Vorlagenzählung; providers.py:110-111 |
| whatsapp.phone_number_id | fehlt → nicht konfiguriert | truthy; expected String, nicht streng typisiert; providers.py:77,82-83; planned |
| whatsapp.api_token | fehlt; Secret | truthy; keine Transportverwendung; providers.py:77-83; planned |
| deutsche-post.api_key | fehlt; Secret | truthy; keine Transportverwendung; providers.py:128-133; planned |
| listing-portals.default_portal | fehlt; erforderlich | truthy; erwarteter Registryname; providers.py:154-164; Manager blockiert planned |
| huggingface.hf_token | fehlt; Manifestsecret | gespeichert/maskiert, **kein aktueller Runtimezugriff**; huggingface.py:34; nicht als wirksam anbieten |

`ImmobilienScout24Adapter(api_key="",api_secret="")` besitzt lokale Stubconstructorargumente (portal_adapter.py:72-74), keine Managerconfig. Docstring-IS24_API_KEY/IS24_API_SECRET/IS24_ACCESS_TOKEN:60-67 haben keinen getenv-/Settingsreader. Als declared_unimplemented katalogisieren, ohne Envwirksamkeit oder externe Endpunkte zu erfinden. Immowelt hat derzeit keine solchen Constructorparameter. Registryaliases sind vorhandene lokale Namen, keine Herstellerkompatibilitätsliste.

### 5.2 Globale Runtime-/Storeparameter und feste Grenzen

| Parameter / Ort | Typ / Default | Wirkung und Quelle |
|---|---|---|
| Settings.INTEGRATION_STATE_FILE | optionaler Pfad None | JSONconfig statt RAMconfig; settings.py:202. Desktop __main__.py:109 persistiert DATA_DIR/integrations.json, Compose:46 `/data/integrations.json`. Kein Historypfad. |
| Settings.AI_ENABLED | bool True | Mastertoggle; settings.py:205; hf_runtime.py:70-76. Privates Compose setzt false. |
| Settings.AI_DEVICE | String cpu | Pipeline/Embeddingdevice; settings.py:206; hf_runtime.py:45,108ff. Kommentar cpu/cuda ist kein hier neu validiertes Deviceenum. |
| Settings.AI_CACHE_DIR | String leer | Runtime cache_dir=None bei leer; settings.py:207; hf_runtime.py:46 |
| Settings.AI_SUMMARIZATION_MODEL | String facebook/bart-large-cnn | settings.py:208; hf_runtime.py:40 |
| Settings.AI_ZERO_SHOT_MODEL | String facebook/bart-large-mnli | settings.py:209; hf_runtime.py:41 |
| Settings.AI_NER_MODEL | String dslim/bert-base-NER | settings.py:210; hf_runtime.py:42 |
| Settings.AI_EMBEDDING_MODEL | String sentence-transformers/all-MiniLM-L6-v2 | settings.py:211; hf_runtime.py:43 |
| Settings.AI_MAX_INPUT_LENGTH | int4096 | aktuell KI-Zeichenpräfix, keine bewiesene ganze Tokenabdeckung; settings.py:212; hf_runtime.py:44; separates KIpaket |
| RuntimeConfig-Modell-/Device-/Längenfelder | oben genannte Defaults, cache_dir=None | optionaler interner Constructoroverride; hf_runtime.py:23-35,57-59; nicht zweite Managerconfig |
| JsonFileIntegrationConfigStore.max_bytes | int1MiB | tatsächlicher Constructorbereich1..16MiB; config_store.py:143-145; kein aktueller HTTP-/Settingskey |
| JsonFileIntegrationConfigStore.lock_timeout | finite Zahl5.0 Sekunden | tatsächlicher Constructorbereich>0..60; config_store.py:143,146-149; kein Settings-/HTTPkey |
| Configstruktur-Tiefe64 | feste Implementierungsgrenze | config_store.py:30-39; kein optionaler Parameter |
| EmailConfig Legacyconstructor | from_address=noreply@immomanager.local; andere Defaults wie5.1, from_name=ImmoManager Pro, timeout_seconds=20.0 | context-local Default/set_email_config, email_service.py:65-74,133-142. Manager nutzt from_mapping und dessen andere sender_email-Vorgabe. |

Keine dieser AIsettings beweist externe Modellexistenz. Neue geplante Historysettings sind gesondert planned, bis implementiert/validiert. Vorhandene Configstore-/SMTPceilings werden als tatsächlicher Altvertrag genannt; der Katalog ändert sie nicht versehentlich. Neue Historybudgets erhalten keine willkürliche Obergrenze. Die Hostsettings DATABASE_URL/DATA_DIR und die G44keys werden nur referenziert, nicht als Providerpayload missverstanden; Credentials werden nie als effektive Werte ausgestellt.

### 5.3 Alle tatsächlich konsumierten Managerpayloadfelder

| Adapter / Aktion | Felder / Defaults | Quelle / Grenze |
|---|---|---|
| email | recipient leer; subject ImmoManager Pro; body HTML leer; body_text None | providers.py:50-55; SMTP-Messagevalidierung; bewusst unarchivierter Mailpayload |
| contract-wizard | tenant_name Mieter; property_name Objekt | providers.py:114-116; lokale Stringformatierung, keine strikte Typprüfung oder vollständige G07-Wizarddatei |
| huggingface | action fehlend/falsy → health, lower; text leer für analyze; messages=[] und subject leer für summarize | huggingface.py:58-101; empty text/messages ablehnt, keine umfassende Payloadmodeltypprüfung |
| huggingface.messages[*] | sender_name Unbekannt; body leer | message_ai.py:31-34. Threadsubject ist äußeres subject; msg.subject wird dort nicht gelesen. |
| listing-portals | action fehlend/falsy → publish; portal fehlend/falsy → default_portal; listing={}; portal_listing_id=None | providers.py:166-176; update/unpublish/status brauchen ID; Manager blockiert planned vor Aufruf |
| Listingstub listing.title | leer | nur Stublogtext; portal_adapter.py:77,113; kein implementiertes externes Listingfachschema |
| whatsapp/deutsche-post | keine tatsächlich konsumierten Fachpayloadfelder | aktuelle Runstubs unimplemented; keine erfundenen Template-/Medien-/Adressfelder |

Unbekannte Payloadkeys werden im freien dict akzeptiert. Katalog darf diese nicht still verwerfen oder als fachlich genutzt deklarieren. Eine neue umfassende Providerbusinessvalidierung wäre ein eigener Auftrag.

### 5.4 Returnkatalog und Aussageklassen

| Quelle | Tatsächlich gelieferte Felder / Bedeutung |
|---|---|
| Managerstatus, manager.py:56-74 | id/name/category/description/planned/enabled/configured/operational/capabilities/health/config/required_config_keys/secret_config_keys/message. Capabilities/description sind Deklarationen; operational ist lokale Ableitung. Config künftig rekursiv bereinigt, bekannte Secretplätze *** kompatibel. |
| Manageraktion, manager.py:127-152 | success/message/details; disabled ohne details; planned.details planned=true/implemented=false; Configablehnungdetails valid/missing_keys/message. Alle tatsächlichen Formen erhalten. |
| Emailhealth/run, providers.py:30-36,57-64 | health status configured/not_configured/provider smtp/transport_checked=false/delivery_confirmed=false; run.details status accepted/not_sent/unknown/code/delivery_confirmed=false/retry_automatically=false. Annahme ist keine Zustellung; keine gelieferten SMTPbytes. |
| Contractwizard | health status ok/templates; details.preview. Lokale Textpreview, keine Vertragsfreigabe. |
| WhatsApp/Post | health status planned/provider/implemented=false; Run unimplemented. |
| Portal | health status planned/adapters/implemented=false. Direkter Stubstatus status not_configured/portal. PortalPublishResult success/portal_name/portal_listing_id/portal_url/error/published_at; Managerprojektion action/portal/portal_listing_id/portal_url. Keine tatsächliche Herstellerresponse. |
| HF, huggingface.py:69-109 | health status/transformers_installed/models_loaded/device; health.success=true heißt Status gelesen, auch bei unavailable. Analyze details document_type/confidence/summary/entities; summarize summary/key_points/action_items. Weitere berechnete AIResult-/Rawmodellfelder werden aktuell davor verworfen. |

Export trennt declared_contract, observed_request, observed_provider_result, local_execution_state, privacy_omissions und coverage. Gelieferte Originalaussagen als Providerbehauptung erhalten, lokale Beobachtung separat beweisen. Ein success=true ersetzt keinen Zustell-/Publikationsnachweis. Nach dem separaten KIpaket nur dessen tatsächlich verfügbaren ganzen Sidecar aufnehmen und Katalog versionieren, nicht verlorene Werte erfinden.

## 6. Migration, Recovery und Aufbewahrung

Neue lineare Revision nach tatsächlich integriertem Head (gelesen c2a2b3c4d5e6), endgültige ID mit Root reservieren. Komplett fehlende Familie bedeutet kompatibler Altstand; teilweise fehlende Tabellen/Columns/Constraints sind vor DDL abzuweisen. Kein Backfill verlorener RAMruns. Falls vorhandene RAMeinträge ausdrücklich übernommen werden, legacy_import_unattributed mit unbekanntem Actor/Scope, keine geratene Zuordnung; Standard ist klar datierter leerer Beginn.

Downgrade muss vor jedem Drop belegtragende Runs/Events/Chunks/Clearnachweise erkennen und ohne Schema-/Wertmutation verweigern. Empty up→down→up erlaubt. create_all ersetzt keinen nachgewiesenen Upgradepfad.

Präzise Root-Hookstellen für Paket A:

1. db/session.py:create_tables, Alembicenvmetadata und Appstartup: atomare Familie prüfen/register/ensure; Historyfactory nach privatem Env-/Keyload injizieren. Keine Configimports vor Desktop-PrivateEnvload. Domain-Memoryinit darf die Historyfactory nicht löschen. Keine automatischen Fremdaktionen beim Neustart.
2. services/full_recovery.py:_database_info/create_full_backup/restore_full_backup: ganze optionale Familie und Chunks/Bindings/Cipher prüfen mit der expliziten gesicherten Keymap, nie Ambientfallback. HauptSQLiteimage enthält alle Tabellen. Integrations.json bleibt separat, vor Restore gegen denselben strikten Configdecoder prüfen.
3. services/recovery_validation.py sowie recovery_sessions.py:invalidate_and_inspect: reiner gestreamter Journalvalidator für SQLite- und SQLAlchemyConnection, vor Jobclaimreset/Authrevocation/Signer-/Credentialpublikation. Alle Rows/Bindings, NULL-/SQL-UNKNOWN- und große malformedBlobfälle beachten. Komplette Legacyabwesenheit akzeptieren, partielle Familie ablehnen. Private PGrestore ruft vorhandenen Sicherheitsabschluss vor Appstart auf (private_server_backup.py:951ff); kein neues Dumpformat.
4. Restore setzt alte execution_started-Versuche allenfalls auf ungewiss, nie auf ausführbare Versandjobs. Stable Encryption-/Indexkeys bleiben erhalten; JWTsignerrotation bleibt bestehend.
5. SQLStore.clear_all, Memoryclear/PartialJSONtransfer: Historienretention vor Business-DML, niemals allgemeines Drop-/Resetlöschen von Journal/Subjectbindungen. Minimaler Clear-Audit bleibt außerhalb Businessreset. Private Memorysnapshots müssen die neue Journalfamilie berücksichtigen, auch wenn sie separat persistent geführt wird. BusinessJSON nimmt keine Actor-/Cipher-/Runjournale auf und ist kein Vollbackup.
6. Tenantprivacy: ungebundene globale Payloads werden nicht nach Namensgleichheit zu Tenantbelegen. Bei später exakten Subjectbindings Retentiondisclosure und Graph mit dessen Besitzer integrieren; keine fremde Mieterdata durch gleiches Objekt/freies Payload. Kein zweiter G43patch in diesem Planauftrag.

Private PGbackup hat bereits vollständigen pg_dump plus /data-Tar/server.env (private_server_backup.py:856-869), also HauptDBjournal und /data/integrations.json. Offline gemeinsame Schreibruhe beibehalten. Vollbackup bleibt Recoveryquelle; Historyseiten/Einzelrunexport ersetzen es nicht. Alte notwendige Encryptionkeys werden nicht automatisch entfernt. Kein Produktbestand wird für die Umsetzung migriert oder gelöscht.

## 7. Zwei unabhängig prüfbare Implementierungspakete

### A: dauerhaftes Journal und sichere Runtime/Recovery

Historyagent besitzt neue services/integrations/history*.py, Crypto-/Validationhelper, db/integration_history_models.py/schemahelper/reservierte Migration, enges Manager-/Base-Kontextdelta, History-/Runrouter und Tests. Keine fachliche SMTP-/KI-/Bankrefaktorierung. Root integriert Startup/Session/Alembic/Recovery/Reset-/Transfer-/Config-/CI-Hooks in eigenem Paket anhand Abschnitt6. Abnahme erst nach wirklicher Hookintegration, kein Core-only-Fertigclaim.

Prüfbare Kriterien:

- >201 und >1.000 synthetische Runs aus zwei echten unabhängigen SQLiteprozessen/PGsessions: alle genau einmal persistiert, bis zum ersten Run cursorseitig erreichbar, Neustart erhält alles. Kein vollständiger RAMpreload. Serialisierte Headgrenze bei delayed Commit und Statuswechsel zwischen Seiten beweisen.
- Echte HTTP-Auth: Owner/All-Verwalter erlaubt; selected Manager/andere Rollen bei allen History-/Config-/Detail-/Export-/Metrics-/Clearpfaden abgewiesen. Derselbe Token verliert Zugriff bei Role/Grant/Active-/Sessionentzug; Veröffentlichung und Downloadchunk prüfen frisch. Actor-/Portfolio-Payloadbypass scheitert. Spätere Subjectresolver erst mit tatsächlichem Parentmove-/Fremd-ID-Test freigeben.
- Verschachtelte Secrets/Arrays/Text-/Keyalias/Headerauth/kurzsecretüberredaktion und spätes unbekanntes Nichtsecretfeld: kein Secret in rawSQL, HTTP, Export, Schema oder Logger; ganzes letztes Arrayelement erhalten. Mailinhalt bleibt ausgelassen, Policy sichtbar.
- Persistierungsfehler vor Start: null Providercalls. Crash/Writefehler nach Beginn: ungewiss/null autoreplay. Genau-run AbschlussCAS und konkurrierendes Clear erhalten In-flight-Evidence. SMTPaccepted bleibt nicht-delivered; Grantentzug verhindert private Ausgabe, aber nicht den sicheren genau-run Abschluss.
- Budgetüberschreitung, NaN/Infinity/duplicate keys, malformed/wrong KeyID/Cipher/Actor-/Scope-/Chunkbindung, leere/mehrchunkige Artefakte: sichere korrigierbare Fehler, kein Teilcommit/500/Plaintextfallback. Neue größere valide Budgets funktionieren.
- Echte Alembickette/kompletter Legacyabsentstand/halbe Familie/belegtragender zero-DDL-Downgrade/empty down-up. Verschlüsseltes synthetisches Fullbackup, eigene Originalquelle gelöscht, Restore, alle privaten Runartefakte gleich: SQLite und tatsächlicher PGrestore. Korruption scheitert vor Authfamilienmutation/Targetpublikation. Businessreset/PartialJSON zero-DML bei retained/subjectgebundenem Journal.
- Ruff/Mypy relevante Quellen; Memory-Domain mit persistentem SQLjournal, SQLDomain sowie PGfixture. Keine echte Mail, privaten Credentials oder Produktmigration erforderlich.

### B: Quellenkatalog und bedienbare vollständige History

Nach A separater UI/Katalogagent: neue services/integrations/catalog.py, additive get_schema-Erweiterung, Sourcecontracttests; History-/Parametercomponents, enges Integrations.jsx-Delta, scoped CSS/DE/EN/ES/UItests. Manager-/Routeredits strikt sequenziell zu A. Bank/KI/Privacyquellen bleiben fremder Besitz.

Prüfbare Kriterien:

- Jede tatsächlich gelesene Config-/Payload-/Returnvariable oben mit Typ/echtem Default/Wirksamkeitsstatus/Sourceanker abgedeckt. Schmaler Literalreader-/DTOabgleich plus handgeprüfte Constructor-/Aliaszuordnung; source contract drift erzeugt fehlenden/obsoleten Katalogbefund, kein unverifizierter AST-Generatewrite. Keine Configwerte in statischem Katalog. Tests ausdrücklich hf_token/IS24_ENV unwirksam und sender_email-Mappingdefault leer.
- Alte Schema-/Run-/Privateaccess-/SMTP-/Configtests bleiben streng; Pflicht-/Secret-/Capabilitylisten und Run-/Historyreturnkeys kompatibel. Unknown nested Config erhalten, *** überschreibt bekannten Credential nicht; statische Katalogdefaults und effektive Runtimewerte getrennt.
- UI erreicht >100/200 Runs bis zum Erfassungsbeginn, lädt große Einzelruns on demand, serverseitige Filter/Cursor. Run-ID/Zeit/Ergebnis korrekt bei zwei parallelen Runs. Error statt falscher leerer Liste, Seitenbudgetkorrektur, stale-Abort/Actorwechsel/Grantentzug sinnvoll.
- Private Detail/Export trennt Deklaration/Originalaussage/tatsächliches Ergebnis/Ausführungszustand/Auslassung/Coverage. Alle erlaubten späten Felder downloadbar; kein unsafe HTML; kein automatischer Lauf nach Reload/Recovery/Retry einer Historyabfrage.
- Relevante Vitestfälle, vollständiges Lint/Build, Root-owned echte Browserabnahme Desktop/320px/dark, zwei Akteure und Late-Grantentzug. Runtime nicht allein auf Mocks freigeben.

## 8. Abgrenzung und offene Punkte

Die vorhandenen optionalen Manager-/APIsteuerparameter sind zusätzlich zu den Providertabellen zu katalogisieren: enabled bool beim Toggle (Providerdefaults email/contract-wizard/huggingface true, drei planned false), IntegrationManager.store=None als intern injizierbarer Configstore, list_history.limit=20 und HTTP limit20/ge1/le100 sowie JsonFileIntegrationConfigStore.file_path (erforderlich). Managerregistration/provider manifests sind interne Verträge, keine Kundensecrets. Nicht eingebundene Constructor-/Docstringoptionen werden nicht mit installierbaren Runtimekeys vermischt.

Es wird für Paket A zuerst ein typed Journal-/Actor-/Publicationvertrag festgelegt; danach implementiert, migriert und tatsächlich getestet. Neue Confignamen und ihre Defaultbudgets gehören erst nach Umsetzung in den Katalog. Keine hier vorgeschlagene Tabelle, Route, Config oder Abnahme ist bereits vorhanden. Der Plan ersetzt weder die KI-/Bank-/Datenschutzaufträge noch deren eigene Abnahme. Noch offen: Rootreservierung der Revision sowie Implementierung und Gates A/B.

## Quellenfingerprints

SHA256 über tatsächliche Dateibytes; relative Pfade beziehen sich auf den gelesenen Root-Integrationscheckout. Bericht und Inventur sind Planartefakte außerhalb des Produktcheckouts.

| Datei | SHA256 |
|---|---|
| backend/services/integrations/base.py | 66ca69fd7838e694f651b226943b0b2e00270194028c9ef2099b344404d95880 |
| backend/services/integrations/manager.py | 70cb67f1a7bc095128cca687ea363f80b77ec876ffe5861307baaa4b0436d7bb |
| backend/services/integrations/config_store.py | fe7b190d40a768332e804e6fe844f6201292856b2fdcfa3a9901917c7c09fe09 |
| backend/services/integrations/providers.py | 4481d154f4955b31131dc534a2cd817376d71b82dd3cc239de2cdae2e90e5fdd |
| backend/services/integrations/huggingface.py | e1b223a31bab3b6e09a3ecdd4be006ca54b8ccb4f82062824149e07f66a6e2db |
| backend/services/integration_service.py | f2683bf2c3f24ae1d83457545c6ca955262ca4a459aad52c5bd6c37fe67c2225 |
| backend/services/email_service.py | 99bff8c88093f5ece800cbe967353165f40c2f77e6260c8861253e5594db1ba9 |
| backend/services/ai/hf_runtime.py | ce6f0c00228800f48c6aa144aa31dcc368d927375a210bb374c6b1a996c5348b |
| backend/services/ai/message_ai.py | 13dd63e3726f1338c0e30c33d7afbc33b6a6bf47df759c45191dff4ad8e4dbd5 |
| backend/services/portal_adapter.py | 29e8b8b086597e5ceab2979a069dc5e925d018d0ac0748bcde7a28209ec30a1f |
| backend/routers/integrations.py | b9b2c5d7a5b2c7c7c3c5979a39d1f507d7b619847ce5f1acfdc3dfb6eeebd7f0 |
| frontend/src/pages/Integrations.jsx | c06ba321e92ebba30223dcedf0f4821c61aec5954fc41d47061c9e122395721c |
| backend/settings.py | dd96f6cfced45a99c61508915773cd9a3d7814ab8a803ff59a43e0d5ef4a4132 |
| backend/services/providers/exchange_observation.py | 54b0bde3dd51de338e507aa25c54e8c8092e10d07e338be8be038ff7afd3fe48 |
| backend/services/providers/schema_observation.py | d0bd44cbdff0378026caa3252ddb6b861715747f74a6050d05c53ca7e4192537 |
| backend/services/checked_publication.py | a543923ebe9f9b5f0a0582176a9afba302230593a4d29ab283aa04725cf241d6 |
| backend/services/full_recovery.py | d1a9056974e637437808f64963534056860eebfa4cdaeeed1f4a61f0c9f4b7c1 |
| backend/services/recovery_sessions.py | d7291ec36f86e024ed53ac6bf52b04c639dc0250ae775d24f7e51d9b3c80a27f |
| backend/services/recovery_validation.py | 70a520ae96698606cacd3bc12e02b11f597dc8fd4b84d98577a86291c486f342 |
| scripts/private_server_backup.py | eee016a67b88a674da5fc46ef324644092e0e3e906479d8902b6c9f5b23be586 |
| backend/services/form_draft_crypto.py | cd8e7baf7b008ef08f5d6e4be4c8b18d15ace94d9d27e912d78e33a5feefce20 |
| backend/services/iban_encryption.py | 5933bc4b4e6c76e6d299244bc103f18a4d2bee42e57ed541a239ed61091ccccd |
| backend/__main__.py | da4bd6f8d31252f9b081dffd59031d327e20613b4679da15af6990e816a765b4 |
| compose.private-server.yml | a9588e70572645dde7f5596aa88dec877aefc4d6da11a7eec982aa749c42c586 |
| backend/dependencies.py | 5522a793a090f0950c23c066e6bb6ff092bd30a33dcced64366e8f0f93f4fa7f |

