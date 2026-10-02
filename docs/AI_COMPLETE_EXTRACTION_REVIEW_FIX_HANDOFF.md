# KI-Volltextanalyse – Review-Korrekturhandoff

Parent: `61c0a28c4e48d892bf2c90538ff4f2c7ba81e5e3`
Branch/Worktree: `assist/ai-complete-extraction` / `work/ai-complete-extraction`

Diese Folgeänderung korrigiert ausschließlich drei Reviewbefunde der bereits
integrierbaren Volltextanalyse. Keine Router-, Auth-, Recovery-, Workflow-,
Frontend-, OCR-, Bank- oder Rootdatei wurde geändert.

## 1. Zero-Shot: Pair-Budget vor ONLY_FIRST

Hugging Faces Zero-Shot-Pipeline behandelt die Quelle als erste Sequenz
(Premise) und die aus dem Candidate Label erzeugte Hypothese als zweite Sequenz.
Die offizielle Pipeline tokenisiert diese Paare mit
`TruncationStrategy.ONLY_FIRST`, damit die Hypothese nicht abgeschnitten wird.

Quellen:
- https://huggingface.co/docs/transformers/main/pad_truncation
- https://huggingface.co/transformers/v4.11.1/_modules/transformers/pipelines/zero_shot_classification.html

Der bisherige Planer reservierte nur
`num_special_tokens_to_add(pair=False)`. Damit konnte ein scheinbar passend
großer Premise-Abschnitt innerhalb der Pipeline nochmals gekürzt werden.

Korrektur:
- `plan_zero_shot_sections()` berechnet für alle tatsächlich verwendeten
  Candidate Labels die explizit verwendete Hypothese
  `"This example is {}."`;
- reserviert das **größte** Hypothesen-Tokenbudget;
- reserviert zusätzlich `num_special_tokens_to_add(pair=True)`;
- nur der verbleibende Tokenraum wird als Premise-Abschnitt geplant;
- genau dieselbe Hypothesenvorlage wird beim Pipeline-Aufruf explizit übergeben.

Kann das Paarbudget mit dem vorhandenen Tokenizer nicht verlässlich bestimmt
werden, bleiben die historischen Klassifikations-Topfelder aus dem
Kompatibilitätslauf verfügbar, aber Classification erhält
`zero_shot_pair_budget_unverified`, keine `covered_ranges` und niemals
`coverage.complete=True`. Ein intern gekürztes Präfix kann deshalb nicht als
vollständig analysiert veröffentlicht werden.

## 2. Kurze Summary-Restabschnitte

Dokument- und Thread-Summarization markierten kurze Sections früher als
`covered`, ohne die Pipeline aufzurufen.

Jetzt erreicht **jeder** geplante Abschnitt die echte Pipeline. Für kurze
Sections wird lediglich der Output-`min_length` auf 1 abgesenkt. Coverage wird
erst nach einem gültigen Modellresultat gesetzt. Lehnt die Pipeline den kurzen
Abschnitt ab, bleibt dieser Abschnitt als `pipeline_error` mit seinen exakten
Quelloffsets offen; spätere Abschnitte werden unverändert weiter bearbeitet.

Damit entstehen weder künstliche Erfolgsbereiche ohne Modellaufruf noch
unnötige Lücken nur deshalb, weil der letzte Abschnitt wenige Wörter enthält.

## 3. Exceptiontexte aus Logs entfernt

Die analysierten Dokument-/Nachrichtentexte können in Exceptionmessages eines
Modells oder Tokenizers auftauchen. Die bisherigen
`logger.warning(..., exc_info=True)`-Pfade konnten diese Nachricht/Tracebacks
in Logs spiegeln.

Die geänderten Datenpfade loggen jetzt ausschließlich:
- stabilen Ereignisnamen,
- `error_type=<ExceptionClass>`.

Weder `str(exc)` noch Traceback/Exceptionmessage werden geloggt. Dasselbe
Muster wurde für Pipeline-/Embedding-Loadfehler im lokalen HF-Runtime angewandt.
Die Result-Coverage enthält weiterhin nur stabilen Fehlercode und
Exception-Klassennamen.

## Gezielte synthetische Gegenproben

`backend/tests/test_ai_extraction_review_fixes.py` prüft ohne Modelldownloads:

1. Ein One-Character-per-Token-Faketokenizer mit kleinem Modellfenster und
   explizitem Pair-Overhead. Jeder Zero-Shot-Premise-Call muss zusammen mit der
   längsten Label-Hypothese und Pair-Special-Tokens in das Modellfenster passen.
   Die Coverage läuft lückenlos bis EOF.

2. Kurze Dokument- und Threadabschnitte müssen jeweils exakt einmal den
   Fake-Summarizer erreichen, bevor sie als covered gelten. Ein absichtlich
   ablehnender Fake wird nach seinem echten Aufruf als `pipeline_error`
   ausgewiesen.

3. Eine Fakepipeline sowie ein Fake-HF-Loader werfen Exceptions, deren Nachricht
   das Fragment `SYNTHETIC_PRIVATE_TEXT_MUST_NOT_BE_LOGGED_9481` enthält.
   `caplog` darf dieses Fragment nicht enthalten, der Exceptiontyp
   `RuntimeError` bleibt diagnostisch sichtbar.

Die vorhandenen Langtextgates wurden beibehalten. Der dortige Faketokenizer
modelliert nun auch Pair-Special-Tokens und Hypothesen-Tokenzählung, sodass
dessen bisherige Voll-Coverage-Assertion denselben strengeren Zero-Shot-Vertrag
prüft.

## Ausgeführte Gates

`pytest backend/tests/test_ai_services.py backend/tests/test_ai_full_text.py backend/tests/test_ai_extraction_review_fixes.py backend/tests/test_integration_manager.py backend/tests/test_integrations_router.py -q -rs --tb=short`

Ergebnis: **56 passed**, eine bereits vorhandene
FastAPI/Starlette-TestClient-Deprecation-Warnung.

Statisch:
- Ruff auf allen geänderten AI-Runtime-/Testdateien: grün.
- konfigurierte Mypy-Prüfung der fünf AI-/Integrations-Runtimequellen:
  **Success: no issues found in 5 source files**.
- `py_compile`: grün.
- `git diff --check`: vor Commit erneut ausführen.

## Grenzen

Diese Korrektur fügt keinen persistenten AI-Job/Queue-Speicher hinzu und ändert
keine OCR-/Dateipersistenz. Fehlende Sections bleiben im synchronen Resultat
über Offset, SHA-256, Fehlercode und Typ reproduzierbar ausgewiesen.

Es wurden keine privaten Dokumente, Providerzugänge, Live-Nachrichten,
Modelldownloads oder externen API-Schreibvorgänge verwendet.
