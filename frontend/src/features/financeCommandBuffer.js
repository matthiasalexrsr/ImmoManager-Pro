// Same owner namespace as the existing workspace crash buffers; logout clears it.
// Recovered commands may be displayed only after the source was authorized again.
export const financeCommandKey = (owner, source) => owner ? `workspace:${owner}:finance-command:${source}` : null;
export function readFinanceCommand(key) {
  if (!key) return null;
  try {
    const value = JSON.parse(localStorage.getItem(key) || 'null');
    const source = key.slice(key.lastIndexOf(':') + 1);
    const base = `/receivables/${source}/settlements`;
    const validPath = source === 'report-definition' ? value?.path === '/reports/v2/saved'
      : value?.path === base || (value?.path?.startsWith(`${base}/`) && /^[a-f0-9]{64}\/reverse$/.test(value.path.slice(base.length + 1)));
    return validPath && value?.request?.idempotency_key ? value : null;
  } catch { return null; }
}
export function rememberFinanceCommand(key, command) {
  if (key) {
    const existing = readFinanceCommand(key);
    if (existing && existing.request.idempotency_key !== command.request.idempotency_key) {
      throw new Error('Ein anderes Fenster hat bereits einen unbestätigten Vorgang. Bitte diesen zuerst prüfen und fortsetzen.');
    }
    try { localStorage.setItem(key, JSON.stringify(command)); }
    catch { throw new Error('Der Wiederanlaufpuffer konnte nicht gespeichert werden. Bitte den Browserspeicher prüfen; es wurde kein Ausgleich gesendet.'); }
  }
}
export function forgetFinanceCommand(key, command) {
  if (key && readFinanceCommand(key)?.request.idempotency_key === command.request.idempotency_key) localStorage.removeItem(key);
}
