import { AlertTriangle, RefreshCw } from 'lucide-react';
import { workflowText } from './workflowCopy';

export default function WorkflowCommandNotice({
  state,
  locale = 'de-DE',
  onRetryExact,
  onReviewCurrent,
  onDismiss,
}) {
  if (!state || ['idle', 'sending', 'success'].includes(state.phase)) return null;
  const tr = (key, params) => workflowText(locale, key, params);
  const conflict = state.phase === 'conflict';
  const unknown = state.phase === 'unknown';
  const title = unknown ? tr('unknownTitle') : conflict ? tr('conflictTitle') : tr('errorTitle');
  const body = unknown ? tr('unknownBody') : conflict ? tr('conflictBody') : state.error?.message;

  return (
    <aside className={`workflow-command-notice workflow-command-notice--${state.phase}`} role="alert">
      <AlertTriangle size={18} aria-hidden="true" />
      <div>
        <strong>{title}</strong>
        {body && <p>{body}</p>}
        <div className="workflow-command-notice__actions">
          {unknown && (
            <button type="button" className="btn btn-secondary btn-sm" onClick={onRetryExact}>
              <RefreshCw size={15} aria-hidden="true" /> {tr('retryExact')}
            </button>
          )}
          {conflict && onReviewCurrent && (
            <button type="button" className="btn btn-secondary btn-sm" onClick={onReviewCurrent}>
              {tr('reviewCurrent')}
            </button>
          )}
          {!unknown && !conflict && onDismiss && (
            <button type="button" className="btn btn-secondary btn-sm" onClick={onDismiss}>
              {tr('close')}
            </button>
          )}
        </div>
      </div>
    </aside>
  );
}
