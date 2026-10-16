import { useEffect, useRef, useState } from 'react';
import useEntityFormDraft from '../../hooks/useEntityFormDraft';

const fields = [{ key: 'body', type: 'textarea' }];

// Uses the existing private workspace writer; the conversation transport stays unchanged.
export default function InternalReplyComposer({ thread, value, onChange, onSend, notice }) {
  const [recoveryError, setRecoveryError] = useState('');
  const [cleaning, setCleaning] = useState(false);
  const cleanupActive = useRef(false);
  const latestValue = useRef(value);
  latestValue.current = value;
  const saved = useEntityFormDraft({ context: 'message-reply', kind: 'message_thread', id: thread.id, fields });
  useEffect(() => {
    if (notice.saved && !latestValue.current && saved.ready && !saved.recovery) {
      cleanupActive.current = true; setCleaning(true);
      saved.clear({ completed: true }).catch(failure => setRecoveryError(failure.message || 'Die private Entwurfssicherung konnte nicht abgeschlossen werden.'))
        .finally(() => { cleanupActive.current = false; setCleaning(false); });
    }
  // Clear only after a newly confirmed conversation reply; newer typing remains a draft.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [notice.saved, value]);
  const change = body => { if (!cleanupActive.current) { onChange(body); saved.stage({ body }); } };
  const recover = async () => {
    const values = saved.recovery.values;
    try { await saved.compare(); await saved.recover(values); onChange(values.body || ''); }
    catch (failure) { setRecoveryError(failure.message || 'Der Entwurf konnte nicht wiederhergestellt werden.'); }
  };
  return <div className="thread-composer">
    <label htmlFor="thread-reply">Antwort an „{thread.subject}“</label>
    {saved.recovery && <div role="status"><p>Ein privater Antwortentwurf wurde wiedergefunden.</p><pre style={{ whiteSpace: 'pre-wrap' }}>{saved.recovery.values.body}</pre><button type="button" onClick={recover}>Entwurf übernehmen</button><button type="button" onClick={() => saved.clear()}>Entwurf verwerfen</button></div>}
    <textarea id="thread-reply" disabled={cleaning || (saved.enabled && !saved.ready)} value={value} onChange={event => change(event.target.value)} rows={3}
      placeholder="Interne Nachricht schreiben …" onKeyDown={event => { if (event.key === 'Enter' && event.ctrlKey) onSend(); }} />
    {saved.enabled && <p role="status">{({ pending: 'Entwurf wird gesichert …', saving: 'Entwurf wird gespeichert …', saved: 'Privater Entwurf gespeichert', loading: 'Entwurf wird geladen …', changed: 'Die Konversation wurde geändert. Bitte vergleichen.' })[saved.status] || ''}</p>}
    {recoveryError && <p role="alert">{recoveryError}</p>}
    {saved.error && <div role="alert">{saved.error}<button type="button" onClick={saved.retry}>Entwurfssicherung wiederholen</button></div>}
    <button className="btn btn-primary" onClick={onSend} disabled={!value.trim() || notice.sending || notice.uncertain}>{notice.sending ? 'Wird gespeichert …' : 'Senden'}</button>
  </div>;
}
