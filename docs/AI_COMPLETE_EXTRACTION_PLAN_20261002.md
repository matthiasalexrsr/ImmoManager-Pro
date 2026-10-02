# KI-Textanalyse ohne stille Präfixkürzung – Implementierungsplan

Basis: `92c30c937e5d758bea68c1f9cba9b40f2ebd39f2`
Branch/Worktree: `assist/ai-complete-extraction` / `work/ai-complete-extraction`

## Belegter Ist-Zustand

- `document_ai.py` schneidet vor allen KI-Schritten auf
  `runtime.config.max_input_length` ab; Klassifikation nochmals auf 512 Zeichen,
  NER nochmals auf 2048 Zeichen.
- `message_ai.py` fasst nur den Präfix bis `max_input_length` zusammen.
- Regex-Rechnungsfelder laufen bereits über den vollständigen Dokumenttext, werden
  aber im HuggingFace-Provider nicht vollständig projiziert.
- `DocumentAIResult` besitzt bereits invoice_number, invoice_date,
  total_amount, supplier, cost_category, language und ai_model. Der Provider gibt
  davon derzeit nur Typ/Confidence/Summary/Entities aus.
- NER verliert Score, lokale Start/End-Offets sowie unbekannte Labels.
- Fehler einzelner Modellaufrufe werden derzeit in None/{} umgewandelt; es gibt
  keine prüfbare Abdeckungs- oder Teilfehlerangabe.

## Zielarchitektur

1. **Modellgerechte Abschnittsplanung**
   - `hf_runtime.py` erhält eine reine Abschnittsplanung.
   - Wenn ein Pipeline-Tokenizer ein brauchbares `model_max_length` liefert,
     wird dieses Tokenbudget abzüglich Special Tokens verwendet.
   - Bei Tokenizern mit `return_offsets_mapping` werden daraus exakte
     Zeichenabschnittsgrenzen erzeugt.
   - Falls ein Pipeline-Dummy/älterer Tokenizer keine Offsets liefern kann,
     wird ausschließlich als transparenter Fallback das vorhandene positive
     `max_input_length` als Zeichenbudget pro Abschnitt benutzt.
   - Das Budget begrenzt **nur einen Modellaufruf**, nicht die Gesamttextlänge.
     Abschnitte decken lückenlos [0, len(text)) ab.

2. **Prüfbare Abdeckung statt Erfolg über Präfix**
   - `schemas.py` wird additiv um Abschnitts-/Coverage-Dataclasses erweitert.
   - Dokument- und Thread-Ergebnisse behalten alle bisherigen Felder.
   - Zusätzlich: `analysis_complete`, per Capability (`classification`,
     `summarization`, `ner`) erfolgreiche und fehlende
     `start_offset/end_offset`-Bereiche, Abschnittsbudget/-art sowie
     fehlgeschlagene Abschnittsindizes.
   - Fehlertexte aus Exceptions werden nicht gespiegelt; gespeichert werden nur
     stabiler Fehlercode und Exception-Klassenname.
   - Ein Fehler in Abschnitt N lässt N+1 weiterlaufen. Fehlende Bereiche bleiben
     explizit in der Antwort und können gezielt erneut verarbeitet werden.

3. **Dokumentanalyse**
   - Regex-Fachprojektion bleibt unverändert auf dem vollständigen Text und hat
     damit Vorrang für bereits vorhandene Rechnungselemente.
   - Klassifikation läuft über alle Klassifikationsabschnitte. Das bestehende
     Topfeld wird deterministisch aus den erfolgreich analysierten Abschnitten
     gewählt; Abschnittsresultate bleiben separat nachvollziehbar.
   - Zusammenfassung läuft über alle Summary-Abschnitte; bestehendes
     `summary: str|None` bleibt und enthält die geordneten Teilzusammenfassungen.
   - NER läuft über alle NER-Abschnitte. Das bestehende `entities`-Dictionary
     bleibt kompatibel; zusätzlich werden normalisierte Mentions mit
     entity/entity_group/word/score, lokalen und absoluten Offsets sowie
     Abschnittsnummer erhalten. Unbekannte Labels werden nicht verworfen.
   - Supplier aus NER füllt weiterhin nur eine zuvor fehlende Regex-Lieferantenangabe.

4. **Threadanalyse**
   - Der vollständige zusammengesetzte Thread erhält stabile Quelloffsets.
   - KI-Summarization verarbeitet alle Modellabschnitte; Teilfehler werden nicht
     als vollständige KI-Zusammenfassung ausgegeben.
   - Action-Items werden nicht mehr nach zehn abgeschnitten. Key-Point-Heuristik
     bleibt eine kompakte Ansicht; zusätzlich wird die vollständige
     Abschnittsabdeckung ausgewiesen.
   - Bei nicht verfügbarer KI bleibt der bestehende extractive Fallback nutzbar,
     aber Coverage weist die nicht ausgeführte KI-Summarization ausdrücklich aus.

5. **Integration-Provider**
   - Keine neuen externen Calls.
   - `analyze` projiziert alle nicht geheimen Ergebnisfelder einschließlich
     Rechnungs-, Sprach-, Modell-, Coverage- und Mention-Feldern.
   - `summarize` projiziert analog Coverage/Modellfelder.
   - `success=True` nur bei vollständig ausgeführter angeforderter
     Modellanalyse; Teilresultate erhalten `success=False` plus Details statt
     einer erfundenen Vollerfolgsmeldung.

6. **Tests**
   - ausschließlich synthetische Fakepipelines/Faketokenizer; keine Downloads.
   - Kurzer bestehender Rechnungsfall bleibt kompatibel.
   - > alte 512/2048/4096-Grenzen: späte ORG-Entität und absolute Offsets werden
     gefunden.
   - Rechnungsnummer, Datum, Betrag und Supplier spät im Dokument bleiben in
     Resultat und Providerprojektion erhalten.
   - Mittlerer Abschnitt wirft absichtlich; spätere Abschnitte werden trotzdem
     analysiert, `analysis_complete=False`, fehlende Offsets exakt.
   - Lange Threads analysieren alle Abschnitte und späte Action-Items.
   - Provider meldet Teilanalyse nicht als Erfolg.
   - Existing `test_ai_services.py` plus neue fokussierte Tests, Ruff,
     konfigurierte Mypy-Prüfung und `py_compile`.

## Nicht im Scope

Keine Router-, Auth-, Recovery-, Workflow-, Frontend-, Bank- oder OCR-Service-
Änderung. Keine Modelldownloads, echten Dokumente, Zugangsdaten oder externen
Nachrichten. Keine Änderung der vorhandenen OCR-Budgets oder Suche.

## Korrekturplan nach unabhängigem Review (Basis 61c0a28)

Vor dem Korrekturcode wurden die drei Befunde gegen den aktuellen Branch erneut
am Quelltext geprüft.

1. **Zero-Shot-Paarbudget / ONLY_FIRST**
   - Der generische Tokenplan reserviert aktuell nur
     `num_special_tokens_to_add(pair=False)`. Hugging Faces offizielle
     Zero-Shot-Pipeline bildet jedoch Premise/Hypothese-Paare und tokenisiert mit
     `TruncationStrategy.ONLY_FIRST`, damit die Label-Hypothese nicht gekürzt
     wird.
   - Korrektur: Für Zero-Shot wird vor der Abschnittsplanung das maximale
     Hypothesen-Tokenbudget aller tatsächlich verwendeten Candidate Labels plus
     Pair-Special-Tokens reserviert. Erst der Rest ist Premise-Budget.
   - Wenn dieses Paarbudget mit dem vorhandenen Tokenizer nicht verlässlich
     bestimmt werden kann, darf Classification nicht als vollständig analysiert
     ausgewiesen werden. Es gibt dann eine explizite fehlende Coverage statt
     einer potenziell intern nochmals gekürzten Erfolgsmeldung.
   - Offizielle Quellen:
     https://huggingface.co/docs/transformers/main/pad_truncation
     und
     https://huggingface.co/transformers/v4.11.1/_modules/transformers/pipelines/zero_shot_classification.html

2. **Short-Section ohne Modellaufruf**
   - Dokument- und Thread-Summarization markieren Abschnitte unter dem bisherigen
     Mindestwortschwellwert aktuell als `covered`, obwohl die Pipeline nicht
     aufgerufen wird.
   - Korrekturentscheidung nach Gegenprobe: auch kurze Restabschnitte werden
     tatsächlich an das Summarization-Modell übergeben. Nur der Output-
     `min_length` sinkt für diese Abschnitte auf 1. Ein erfolgreicher
     Modellaufruf darf Coverage erzeugen; ein Fehler wird als `pipeline_error`
     mit exakten Offsets ausgewiesen. Es gibt keine Erfolgs-Coverage mehr ohne
     Modellaufruf.

3. **Exceptiontext / PII-freies Logging**
   - Die aktuellen `exc_info=True`-Warnungen spiegeln Exceptiontexte und damit
     potenziell Dokument-/Nachrichteninhalt in Logs.
   - Korrektur: keine Tracebacks/Exceptionmessages aus Datenpfaden loggen.
     Warnungen enthalten ausschließlich stabilen Ereignisnamen und
     Exception-Klassennamen; Ergebnis-Coverage hält wie bisher nur Fehlercode und
     Typ, niemals `str(exc)`.

### Gezielte Gegenproben

- Faketokenizer mit kleinem Modelllimit und absichtlich langem
  Zero-Shot-Hypothesentext: jeder Premise-Abschnitt muss inklusive Pair-Overhead
  in das Modellfenster passen und die Source-Offsets müssen lückenlos bis EOF
  reichen.
- Fake-Summarizer mit kurzem Abschnitt: Callcount ist exakt 1; Coverage wird
  erst nach dem echten Modellresultat gesetzt. Ein ablehnender Fake würde
  stattdessen denselben Abschnitt als `pipeline_error` ausweisen.
- Fakepipeline wirft eine Exception, deren Nachricht ein synthetisches
  Geheim-/Textfragment enthält: Coverage enthält nur Exceptiontyp; `caplog`
  enthält das Fragment nicht.
- Bestehende Langtext-/späte-Entität-/Rechnungsfeld- und Provider-Gates bleiben
  zusätzlich grün.

### Präzisierung zur Short-Section-Korrektur

Bei der Gegenprobe zeigte sich, dass bloßes Markieren kurzer Restabschnitte als
fehlend die Vollanalyse langer Quellen unnötig unvollständig machen würde.
Die engere Umsetzung ist daher: **auch kurze Restabschnitte werden tatsächlich
an das Summarization-Modell übergeben**, lediglich mit einem auf 1 reduzierten
Output-`min_length`. Erst wenn dieser reale Modellaufruf scheitert, wird der
Abschnitt als `pipeline_error` fehlend ausgewiesen. Damit gibt es keine
Coverage ohne Modellaufruf und zugleich keine künstliche Lücke nur wegen eines
kurzen letzten Abschnitts.


## Retokenisierungs-Folgeplan nach Budgetreview

Zusätzlicher Befund auf Parent `0749dc80edc5129ac938ecbeff9f355e99260a42`:
Fast-Tokenizer-Offsets stammen aus der Tokenisierung der vollständigen Quelle.
Ein daraus geschnittener String kann an seiner neuen linken/rechten Kontextgrenze
durch BPE/WordPiece anders tokenisiert werden. Deshalb ist
`N Whole-Source-Tokens` kein hinreichender Beweis, dass der tatsächlich an die
Pipeline übergebene Substring ebenfalls höchstens N Tokens besitzt.

### Korrektur

1. Jeder aus Whole-Source-Offsets gebildete Tokenabschnitt wird unmittelbar als
   **exakter Substring** mit demselben Tokenizer und `add_special_tokens=False`
   erneut gezählt.
2. Passt ein Offsetabschnitt nicht, wird nicht gekürzt veröffentlicht, sondern
   der komplette Text über den Slow-Plan anhand echter Substring-Tokenzahlen neu
   portioniert.
3. Auch der Slow-Plan verifiziert den endgültigen Abschnitt nach binärer Suche
   und nach einer optionalen Whitespace-Grenzverschiebung nochmals. Eine
   Whitespace-Grenze wird nur übernommen, wenn der tatsächliche Substring weiter
   ins Budget passt.
4. Ein NER-Overlap wird nur übernommen, wenn dessen tatsächlich retokenisierter
   Suffix ins gewünschte Overlap-Tokenbudget passt; der daraus entstehende
   nächste Abschnitt wird anschließend erneut vollständig verifiziert.
5. Vor jedem echten Summary-/NER-Pipelinecall wird ein Tokenplan-Abschnitt erneut
   retokenisiert. Ist er jetzt zu groß oder nicht mehr messbar, erfolgt **kein**
   Modellaufruf und der Bereich wird als
   `section_token_budget_exceeded` beziehungsweise
   `section_token_budget_unverified` ausgewiesen.
6. Zero-Shot verifiziert unmittelbar vor jedem Aufruf erneut:
   `premise_tokens + max(hypothesis_tokens) + pair_special_tokens <= model_max_length`.
   Bei nicht beweisbarem Pairbudget wird die Pipeline nicht aufgerufen und keine
   Classification-Coverage als erfolgreich gemeldet.
7. Kann trotz deklarierter `model_max_length` kein sicherer normaler Tokenplan
   erzeugt werden, wird nicht auf einen scheinbar erfolgreichen Zeichenplan
   zurückgefallen. Der Plan trägt `tokens_unverified`; Summary/NER lassen den
   Quellbereich explizit offen.
8. Pair-Special-Token-Metadaten sind für Zero-Shot nur gültig, wenn ihr Typ
   exakt `int` und der Wert nicht negativ ist. `bool`, negative Werte und
   andere Typen gelten bei `require_special_tokens=True` ausdrücklich nicht
   als bewiesene Null.

### Offizielle Semantik

Aktuelle Hugging-Face-Transformers-Quellen bestätigen, dass
`truncation='only_first'` ausschließlich die erste Sequenz eines Paars kürzt
und die Zero-Shot-Pipeline Premise/Hypothese-Paare mit
`TruncationStrategy.ONLY_FIRST` tokenisiert:

- https://huggingface.co/docs/transformers/main/pad_truncation
- https://github.com/huggingface/transformers/blob/main/src/transformers/pipelines/zero_shot_classification.py

### Gegenproben

- kontextabhängiger Faketokenizer: Whole-Source-Offets modellieren grobe
  Tokenmerges, abgetrennte Substrings brauchen absichtlich mehr Tokens;
- Fake-Summary-Pipeline prüft pro tatsächlichem Call
  `consumed_tokens + special_tokens <= model_max_length`;
- Fake-Zero-Shot-Pipeline prüft pro tatsächlichem Call zusätzlich längste
  Hypothese und Pair-Special-Tokens;
- NER-Probe enthält Whitespace und großen Overlap und kontrolliert sowohl späte
  Entity-Offsets als auch das reale Modellbudget jedes Calls;
- `True`, `-1` und `"3"` als Pair-Special-Metadaten müssen fail-closed
  bleiben und dürfen keinen Zero-Shot-Modellaufruf auslösen.
