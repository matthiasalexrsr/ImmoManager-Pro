import { useRef, useState } from 'react';
import { useConfirm } from './ConfirmDialog';

// Actions on several selected rows. Each row runs through the page's own single-row call, one
// after another, so every server check (rights, conflicts, deletion guards) still applies per row.
// A failure does not stop the others; the bar reports which rows failed and keeps them selected.
// The report lives in the table: when every row succeeded the selection empties, and the result
// must stay visible until it is dismissed or a new selection starts.
export default function BulkBar({ rows, total, allSelected, actions, onSelectAll, onClear, onFinished, onRunningChange, words, report, setReport, sums = [] }) {
  const confirm = useConfirm();
  const [running, setRunning] = useState(null);
  const [showAllFailures, setShowAllFailures] = useState(false);
  const busy = useRef(false);

  const run = async action => {
    if (busy.current) return;
    busy.current = true;
    try {
      onRunningChange?.(true);
      const targets = action.applies ? rows.filter(action.applies) : rows;
      if (targets.length === 0) return;
      setRunning({ label: action.label, done: 0, count: targets.length });
      const question = action.confirm?.(targets);
      if (question) {
        const ok = await (confirm ? confirm(question) : window.confirm(question));
        if (!ok) return;
      }
      setReport(null);
      setShowAllFailures(false);
      const failed = [];
      for (let i = 0; i < targets.length; i += 1) {
        setRunning({ label: action.label, done: i, count: targets.length });
        try {
          await action.run(targets[i]);
        } catch (error) {
          failed.push({ row: targets[i], message: error?.message || String(error) });
        }
      }
      const succeeded = targets.length - failed.length;
      setReport({ label: action.label, succeeded, failed, skipped: rows.length - targets.length });
      const result = { succeeded: targets.filter(row => !failed.some(f => f.row === row)), failed };
      onFinished?.(result);
      // the page reloads its list once, not once per row
      try { await action.finished?.(result); } catch { /* the page shows its own load errors */ }
    } finally {
      busy.current = false;
      setRunning(null);
      onRunningChange?.(false);
    }
  };

  return (
    <div className="bulk-bar" role="region" aria-label={words.region}>
      {rows.length > 0 && <>
      <span className="bulk-bar-count" aria-live="polite">{words.selected(rows.length)}</span>
      {sums.map(sum => <span key={sum.label} className="bulk-bar-sum">{sum.label}: <strong>{sum.value}</strong></span>)}
      {!allSelected && total > rows.length && (
        <button type="button" className="btn btn-sm btn-ghost" onClick={onSelectAll} disabled={Boolean(running)}>{words.selectAll(total)}</button>
      )}
      <button type="button" className="btn btn-sm btn-ghost" onClick={onClear} disabled={Boolean(running)}>{words.clear}</button>
      <span className="bulk-bar-actions">
        {actions.map(action => {
          const count = action.applies ? rows.filter(action.applies).length : rows.length;
          return (
            <button key={action.key} type="button" disabled={Boolean(running) || count === 0}
              className={`btn btn-sm ${action.danger ? 'btn-danger' : 'btn-secondary'}`} onClick={() => run(action)}
              title={count < rows.length ? words.applies(count) : undefined}>
              {action.label}{count < rows.length ? ` (${count})` : ''}
            </button>
          );
        })}
      </span>
      </>}
      {running && <span className="bulk-bar-progress" role="status">{words.progress(running)}</span>}
      {report && !running && (
        <div className={`bulk-bar-report${report.failed.length ? ' has-failures' : ''}`} role={report.failed.length ? 'alert' : 'status'}>
          {words.report(report)}
          <button type="button" className="btn btn-sm btn-ghost bulk-bar-dismiss"
            aria-label={words.dismiss} onClick={() => { setReport(null); setShowAllFailures(false); }}>{words.dismiss}</button>
          {report.failed.length > 0 && (
            <>
              <ul>{(showAllFailures ? report.failed : report.failed.slice(0, 5)).map(f =>
                <li key={f.row.id}>{words.rowName(f.row)}: {f.message}</li>)}</ul>
              {report.failed.length > 5 && <button type="button" className="btn btn-sm btn-ghost"
                aria-expanded={showAllFailures} onClick={() => setShowAllFailures(value => !value)}>
                {showAllFailures ? (words.lessFailures || 'Weniger Fehler anzeigen')
                  : (words.showAllFailures ? words.showAllFailures(report.failed.length)
                    : `Alle ${report.failed.length} Fehler anzeigen`)}
              </button>}
            </>
          )}
        </div>
      )}
    </div>
  );
}
