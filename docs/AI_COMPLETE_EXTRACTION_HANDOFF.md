# KI-Volltextanalyse – Handoff

Basis: \`92c30c937e5d758bea68c1f9cba9b40f2ebd39f2\`  
Branch/Worktree: \`assist/ai-complete-extraction\` / \`work/ai-complete-extraction\`

Der vor der Implementierung geschriebene Plan liegt in
\`docs/AI_COMPLETE_EXTRACTION_PLAN_20261002.md\`.

## Gelieferter Umfang

Geändert wurden ausschließlich:

- \`backend/services/ai/document_ai.py\`
- \`backend/services/ai/message_ai.py\`
- \`backend/services/ai/schemas.py\`
- \`backend/services/ai/hf_runtime.py\`
- \`backend/services/integrations/huggingface.py\`
- \`backend/tests/test_ai_services.py\`
- \`backend/tests/test_ai_full_text.py\`
- die beiden Plan-/Handoff-Dokumente

Keine Router-, Auth-, Recovery-, Workflow-, Frontend-, OCR- oder Bankdatei wurde
geändert.

## Abschnittsmodell und Vollständigkeit

\`hf_runtime.plan_text_sections\` behandelt Modellgrenzen nur noch als Grenze
eines einzelnen Modellaufrufs:

- ein Tokenizer mit verwendbarem \`model_max_length\` liefert das Tokenbudget;
- Fast-Tokenizer verwenden \`return_offsets_mapping\`, daher sind
  Zeichenoffsets direkt an Tokenabschnitte gebunden;
- Slow-Tokenizer ohne Offset-Mapping werden weiterhin nach ihrem echten
  Tokenbudget portioniert: eine iterative Tokenzählung sucht die maximal
  passende Zeichenregion, statt auf einen 4096-Zeichen-Präfix zurückzufallen;
- nur wenn gar kein verwendbares Tokenlimit/-zählen verfügbar ist, wird das
  bisherige \`max_input_length\` transparent als **Zeichenbudget je Abschnitt**
  verwendet;
- es existiert kein Gesamttext-, Objekt- oder Jahrescap;
- NER nutzt einen kleinen Abschnittsoverlap innerhalb desselben Modellbudgets,
  damit mehrteilige Entitäten an Chunkgrenzen nicht durch einen harten Schnitt
  verschwinden.

Coverage-Offsets sind halboffene Python-Zeichenoffsets \`[start,end)\`.
Jede Capability enthält zusätzlich SHA-256 des vollständigen UTF-8-Quelltexts,
Quelllänge, Budgetart/-größe, Overlap, Modell-ID, erfolgreich bearbeitete
Bereiche und explizit fehlende Bereiche.

Fehler eines mittleren Abschnitts stoppen spätere Abschnitte nicht.
\`MissingRange\` enthält Abschnittsindex, exakte Quelloffsets,
\`pipeline_error\` und nur den Exception-Klassennamen; Exceptiontexte werden
nicht als Ergebnis weitergegeben. Dadurch ist die Lücke gezielt erneut
verarbeitbar, ohne einen Präfix als Vollergebnis auszugeben.

## Dokumentanalyse

Die bestehende Regex-Fachprojektion bleibt unverändert kompatibel und läuft
weiterhin auf dem gesamten Text. Dadurch bleiben insbesondere
\`invoice_number\`, \`invoice_date\`, \`total_amount\`, \`supplier\` und
\`cost_category\` erhalten, auch wenn sie erst weit hinter bisherigen
512/2048/4096-Zeichenfenstern stehen.

Klassifikation, Summarization und NER laufen jeweils über **alle** geplanten
Abschnitte. Die bisherigen Topfelder bleiben bestehen. Additiv vorhanden sind:

- \`analysis_complete\`
- \`coverage\` je Capability
- \`classification_sections\`
- \`summary_sections\`
- \`entity_mentions\` mit entity/entity_group, Word, Score, lokalen und
  absoluten Offsets sowie weiteren JSON-artigen Modellfeldern.

Unbekannte NER-Labels bleiben in \`entity_mentions\` erhalten, auch wenn sie
nicht in die alten Komfortgruppen persons/organizations/locations/dates passen.
Numerische Modellwerte werden ohne NumPy-Abhängigkeit in normale JSON-fähige
int/float-Werte projiziert. Ein vorhandener Regex-Supplier wird weiterhin nicht
durch NER überschrieben.

## Threadanalyse

Die komplette aus Subject/Sender/Body gebildete Quelle wird sectionweise
zusammengefasst. Teilfehler werden als fehlende Bereiche ausgewiesen und spätere
Sections trotzdem verarbeitet.

\`action_items\` besitzt nicht mehr die frühere feste erste-10-Abschneidung.
\`key_points\` bleibt bewusst eine kompakte repräsentative Ansicht; sie ist kein
Volltext-/Extraktionsarchiv. Ist keine KI-Pipeline verfügbar, bleibt der
bestehende extractive Fallback verwendbar, aber
\`analysis_complete=False\` und die fehlende KI-Abdeckung ist explizit.

## HuggingFace-Provider

Der Provider projiziert mit \`dataclasses.asdict\` alle nicht geheimen
Resultatfelder, nicht nur Typ/Summary/Entities. Damit gehen Rechnungsfelder,
\`language\`, \`ai_model\`, Coverage und Mentions nicht mehr an der
Integrationsgrenze verloren.

Für Kompatibilität bleibt der historische Provider-Schlüssel \`confidence\`
zusätzlich zu \`document_type_confidence\` erhalten.

\`success=True\` wird nur noch für eine vollständig ausgeführte angeforderte
Analyse gesetzt. Ein Pipeline-Ausfall/Teilresultat liefert die vorhandenen
Ergebnisse weiter, aber mit \`success=False\`, einer Teilanalyse-Meldung und
exakten \`missing_ranges\`.

## Ausgeführte Gates

Alle Tests verwenden synthetische Texte und lokale Fakepipelines/-tokenizer;
es wurden keine Modelle heruntergeladen und keine privaten Daten verwendet.

### AI + Integrationsregressionen

\`pytest backend/tests/test_ai_services.py backend/tests/test_ai_full_text.py backend/tests/test_integration_manager.py backend/tests/test_integrations_router.py -q -rs --tb=short\`

Ergebnis: **53 passed**, eine bereits vorhandene
FastAPI/Starlette-TestClient-Deprecation-Warnung.

Die neuen Gates prüfen unter anderem:

- echte Tokenabschnittsgrenzen und lückenlose Vollquellenabdeckung;
- Slow-Tokenizer ohne Offset-Mapping;
- Rechnung/Datum/Betrag/Supplier hinter >4096 Zeichen;
- späte NER-Entitäten mit absoluten Quelloffsets;
- unbekannte NER-Labels und zusätzliche Modellfelder;
- NER-Overlap an Abschnittsgrenzen;
- absichtlich fehlschlagenden mittleren Abschnitt plus erfolgreiche spätere
  Abschnitte;
- lange Threads und Action-Items hinter der früheren Grenze/ersten zehn;
- Provider-Teilerfolg wird nicht als Erfolg ausgegeben;
- vollständige Projektion bestehender invoice/language/model-Felder.

### Statische Gates

- Ruff auf allen geänderten Pythonquellen und AI-Tests: **grün**.
- konfigurierte Mypy-Prüfung auf den fünf geänderten Runtime-Modulen:
  **Success: no issues found in 5 source files**.
- \`py_compile\` auf Runtime-Modulen und neuem Test: **grün**.
- \`git diff --check\`: vor Commit erneut ausführen.

## Bewusste Grenzen

Dies ändert keine OCR-Erzeugung, keine Datei-/Dokumentpersistenz und baut keinen
neuen privaten Resultatspeicher. Coverage lebt im Resultat des bestehenden
AI-Aufrufs. Ein persistenter/resumierbarer Job über Prozessneustarts wäre eine
separate Queue-/Storage-Arbeit; für den aktuellen synchronen Adapter sind
fehlende Abschnitte eindeutig und reproduzierbar ausgewiesen.

Es wird keine Sprache neu erfunden/detektiert. Das bestehende \`language\`-Feld
bleibt kompatibel und wird jetzt an der Providergrenze vollständig erhalten,
wenn ein aufrufender/weiterer Analyseschritt es gesetzt hat.

Classification speichert bewusst nicht das Pipeline-Feld \`sequence\`, weil das
nur den gesamten privaten Quelltext duplizieren würde. Analytische Felder
Labels/Scores/Model/Offsets sowie NER-Modellfelder werden dagegen erhalten.

Keine Liveprovider, externen Nachrichten, Modelldownloads, Zugangsdaten oder
privaten Dokumente wurden verwendet.
