# Adapterhistorie – Fence-Exception-Folgefix

Parent: `fc45b3ca8423ba58b1444f705a3eff0024df0219`.

Der Runtime-/Reset-Gegenlauf hat einen schmalen Corefehler sichtbar gemacht:
`SQLIntegrationHistoryStore.connection()` übersetzte auch **bewusst aus dem
Caller-Body geworfene** `ValidationError`-Ausnahmen in
`HISTORY_CORRUPT`, weil der Contextmanager seine ValueError-Familie um den
gesamten `yield` gelegt hatte. Damit konnte ein korrekter Retention-Refusal
beim Verlassen der Historybarriere verfälscht werden.

Korrektur:
- `connection(..., passthrough_body=False)` behält für normale
  HistoryStore-Operationen die bisherige Fehlerübersetzung;
- `history_fence()` verwendet ausschließlich
  `passthrough_body=True`, sodass Fehler aus dem **fremden Reset-/Retention-
  Body** unverändert zurücklaufen;
- Setup-/Commitfehler der Historyconnection bleiben weiterhin typisierte
  `HistoryError`-Fehler.
- Keine Änderung an Provider-, Router-, Migration- oder Recoverylogik.

Regression:
`pytest backend/tests/test_integration_history_account_fences.py -q -rs --tb=short`
→ **7 passed** auf SQLite und dem bereitgestellten PostgreSQL-Dienst.

Zusätzlich: Ruff grün, Mypy
`backend/services/integrations/history_store.py` → **no issues**, und
`git diff --check` grün.
