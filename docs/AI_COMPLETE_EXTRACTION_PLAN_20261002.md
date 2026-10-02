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
