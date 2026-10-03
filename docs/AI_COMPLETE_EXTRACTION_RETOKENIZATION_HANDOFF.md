# KI-Volltextanalyse – Retokenisierungs-Handoff

Parent: `0749dc80edc5129ac938ecbeff9f355e99260a42`  
Branch/Worktree: `assist/ai-complete-extraction` / `work/ai-complete-extraction`

Dieser Folgecommit korrigiert ausschließlich die nachträglich gefundene
Tokenbudget-Grenze der bereits vorhandenen Volltextanalyse. Keine Router-,
Auth-, Recovery-, Workflow-, Frontend-, OCR-, Bank- oder Datenbankschema-Datei
wurde geändert.

## Befund

Fast-Tokenizer-Offets beschreiben die Tokenisierung der **vollständigen**
Quellzeichenfolge. Ein daraus geschnittener Substring kann an seiner neuen
linken/rechten Kontextgrenze bei BPE/WordPiece anders retokenisiert werden.
Daher beweist ein Abschnitt von N Whole-Source-Tokens nicht, dass genau der
String, der anschließend an die Pipeline geht, ebenfalls höchstens N Tokens
benötigt.

Bei Zero-Shot kommt zusätzlich die Hypothesen-Sequenz hinzu. Hugging Faces
aktuelle Pipeline bildet Premise/Hypothese-Paare und verwendet
`TruncationStrategy.ONLY_FIRST`; eine zu große Premise würde deshalb intern
nochmals gekürzt, wenn das Paarbudget nicht vorab vollständig reserviert und der
tatsächliche Premise-Substring erneut geprüft wird.

Offizielle Quellen:
- https://huggingface.co/docs/transformers/main/pad_truncation
- https://github.com/huggingface/transformers/blob/main/src/transformers/pipelines/zero_shot_classification.py

## Korrektur im Runtime-Planer

`backend/services/ai/hf_runtime.py`:

1. Jeder über Whole-Source-`offset_mapping` erzeugte Abschnitt wird vor
   Rückgabe mit `tokenizer.encode(section.text, add_special_tokens=False)`
   beziehungsweise dem äquivalenten Tokenizer-Aufruf erneut gezählt.
2. Überschreitet ein solcher abgetrennter String das Budget, wird der ganze
   Quelltext mit `_slow_token_plan` aus tatsächlichen Substring-Tokenzahlen
   neu portioniert. Der übergroße Offsetabschnitt wird nie als gültige Coverage
   zurückgegeben.
3. Der Slow-Plan verifiziert den finalen String erneut, nachdem Binärsuche und
   optionale Whitespace-Grenzverschiebung abgeschlossen sind. Eine verschobene
   Whitespace-Grenze wird nur akzeptiert, wenn ihr tatsächlich retokenisierter
   String weiterhin passt.
4. NER-Overlap wird nur gesetzt, wenn der konkret überlappende Suffix selbst in
   das Overlap-Tokenbudget passt. Der folgende vollständige Abschnitt wird im
   nächsten Planungsschritt erneut verifiziert.
5. Falls eine deklarierte `model_max_length` existiert, aber kein sicherer
   Tokenplan erzeugt werden kann, fällt der Code nicht mehr auf einen scheinbar
   erfolgreichen Zeichenplan zurück. Das Resultat trägt
   `budget_kind="tokens_unverified"`; der aufrufende Analyseschritt lässt
   diesen Bereich ausdrücklich offen.
6. `section_fits_plan` retokenisiert zusätzlich jeden normalen Tokenabschnitt
   unmittelbar vor einem Summary-/NER-Pipelinecall. Ein später festgestellter
   Überlauf/Unverifizierbarkeit wird als
   `section_token_budget_exceeded` bzw.
   `section_token_budget_unverified` protokolliert, ohne den Modellaufruf
   auszuführen.

## Zero-Shot-Paarbudget

`plan_zero_shot_sections` reserviert weiterhin:

`max(hypothesis_tokens) + pair_special_tokens`

und plant nur aus dem verbleibenden Premise-Budget.

Neu verifiziert `zero_shot_section_fits` **unmittelbar vor jedem echten
Pipelinecall** denselben tatsächlich gesendeten Premise-Substring erneut gegen
das vollständige Paarbudget.

Pair-Special-Metadaten gelten bei `require_special_tokens=True` nur als
beweisbar, wenn ihr Python-Typ exakt `int` und der Wert >= 0 ist. Insbesondere
`True`, negative Zahlen oder Strings werden nicht mehr still als 0
interpretiert. In diesem Fall wird Zero-Shot nicht aufgerufen und die
Classification-Coverage bleibt explizit unvollständig.

## Aufrufer

`backend/services/ai/document_ai.py`:
- Classification: Pairbudget und aktueller Substring werden vor jedem Call
  nochmals geprüft.
- Summarization: jeder `tokens`-/`tokens_unverified`-Abschnitt wird vor dem
  Call geprüft; bei fehlendem Beweis kein Call.
- NER: dieselbe Prüfung gilt auch nach der Overlap-Planung.

`backend/services/ai/message_ai.py`:
- identische Pre-Call-Prüfung für Thread-Summarization.

Bestehende Rechnungs-, Sprach-, Modell-, Coverage-, Offset- und
Provider-Projektionen bleiben unverändert.

## Neue synthetische Gegenproben

`backend/tests/test_ai_extraction_review_fixes.py` enthält zusätzlich:

- einen kontextabhängigen Faketokenizer, der die Gesamtquelle absichtlich grob
  tokenisiert, abgetrennte Substrings aber mit deutlich mehr Tokens bewertet;
- einen Fake-Summarizer, der für **jeden tatsächlichen Call** überprüft, dass
  `premise_tokens + single_special_tokens <= model_max_length`;
- einen Fake-Zero-Shot-Provider, der pro Call
  `premise_tokens + longest_hypothesis_tokens + pair_special_tokens`
  kontrolliert und bei Überschreitung hart fehlschlagen würde;
- eine NER-Probe mit Whitespace, echtem großen Overlap und später Entity. Jeder
  konkrete NER-Call muss im Modellbudget bleiben und die späte Entity behält den
  korrekten absoluten Quelloffset;
- parametrisiert `True`, `-1` und `"3"` als ungültige
  Pair-Special-Metadaten. In allen drei Fällen: keine Zero-Shot-Pipelinecalls,
  keine erfolgreiche Coverage.

Die bestehende Mock-Zero-Shot-Probe in `test_ai_services.py` erhielt nur einen
deterministischen lokalen Faketokenizer, damit sie denselben strengeren
Budgetvertrag prüft; ihre Fachassertions wurden nicht abgeschwächt.

## Ausgeführte Gates

AI-/Integrationssuite:

`pytest backend/tests/test_ai_services.py backend/tests/test_ai_full_text.py backend/tests/test_ai_extraction_review_fixes.py backend/tests/test_integration_manager.py backend/tests/test_integrations_router.py -q -rs --tb=short`

Ergebnis auf dem finalen Arbeitsstand: **62 passed**, eine bereits vorhandene
FastAPI/Starlette-TestClient-Deprecation-Warnung.

Die vorherigen 56 Gates bleiben darin enthalten; hinzu kommen sechs konkrete
Retokenisierungs-/Pair-Metadaten-Fälle.

Statisch:
- Ruff auf geänderten AI-Runtime- und Testdateien: **grün**.
- konfigurierte Mypy-Prüfung auf den fünf AI-/Integrations-Runtimequellen:
  **Success: no issues found in 5 source files**.
- `py_compile`: **grün**.
- `git diff --check`: **grün**.

Keine echten Modelle, privaten Texte, Zugangsdaten oder externen Nachrichten
wurden verwendet. Die Tests arbeiten ausschließlich mit lokalen synthetischen
Tokenizern und Fakepipelines.
