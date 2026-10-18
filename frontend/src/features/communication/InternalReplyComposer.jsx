import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { useTranslation } from '../../i18n';
import useEntityFormDraft from '../../hooks/useEntityFormDraft';
import '../../components/workspace.css';

const fields = [{ key: 'body', type: 'textarea' }];

// Uses the existing private workspace writer; the conversation transport stays unchanged.
export default function InternalReplyComposer({ thread, value, onChange, onSend, notice }) {
  const { t } = useTranslation();
  const tr = (key, fallback) => { const translated = t(key); return translated && translated !== key ? translated : fallback; };
  const confirmId = useId();
  const [recoveryError, setRecoveryError] = useState('');
  const [cleaning, setCleaning] = useState(false);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const [discardBusy, setDiscardBusy] = useState(false);
  const cleanupActive = useRef(false);
  const discardActive = useRef(false);
  const generation = useRef(0);
  const activeThread = useRef(thread.id);
  const replyRef = useRef(null);
  const discardRef = useRef(null);
  const keepRef = useRef(null);
  const focusReplyAfterDiscard = useRef(false);
  const latestValue = useRef(value);
  latestValue.current = value;
  const saved = useEntityFormDraft({ context: 'message-reply', kind: 'message_thread', id: thread.id, fields });

  // Invalidate late private cleanup/discard callbacks when the thread changes or unmounts.
  useLayoutEffect(() => {
    generation.current += 1;
    activeThread.current = thread.id;
    discardActive.current = false;
    cleanupActive.current = false;
    focusReplyAfterDiscard.current = false;
    setConfirmDiscard(false); setDiscardBusy(false); setCleaning(false); setRecoveryError('');
    return () => { generation.current += 1; };
  }, [thread.id]);

  useLayoutEffect(() => {
    if (confirmDiscard && !discardBusy && !cleaning) keepRef.current?.focus();
  }, [confirmDiscard, discardBusy, cleaning]);
  useLayoutEffect(() => {
    if (!focusReplyAfterDiscard.current || discardBusy || cleaning || saved.recovery || !saved.ready) return;
    if (replyRef.current?.disabled) return;
    focusReplyAfterDiscard.current = false;
    replyRef.current?.focus();
  }, [discardBusy, cleaning, saved.recovery, saved.ready]);

  useEffect(() => {
    if (!saved.recovery && confirmDiscard && !discardActive.current) setConfirmDiscard(false);
  }, [saved.recovery, confirmDiscard]);

  useEffect(() => {
    if (notice.saved && !latestValue.current && saved.ready && !saved.recovery) {
      const epoch = generation.current;
      const current = () => epoch === generation.current && activeThread.current === thread.id;
      cleanupActive.current = true; setCleaning(true);
      saved.clear({ completed: true })
        .catch(failure => { if (current()) setRecoveryError(failure.message || 'Die private Entwurfssicherung konnte nicht abgeschlossen werden.'); })
        .finally(() => { if (current()) { cleanupActive.current = false; setCleaning(false); } });
    }
  // Clear only after a newly confirmed conversation reply; newer typing remains a draft.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [notice.saved, value]);

  const currentOperation = (epoch, sessionKey) => generation.current === epoch
    && activeThread.current === thread.id && (!saved.isCurrent || saved.isCurrent(sessionKey));
  const change = body => {
    if (!cleanupActive.current && !discardActive.current && !confirmDiscard) {
      onChange(body);
      saved.stage({ body });
    }
  };
  const recover = async () => {
    if (!saved.recovery || cleanupActive.current || discardActive.current || confirmDiscard) return;
    const epoch = generation.current;
    const sessionKey = saved.sessionKey;
    const values = saved.recovery.values;
    try {
      await saved.compare();
      if (!currentOperation(epoch, sessionKey)) return;
      await saved.recover(values);
      if (currentOperation(epoch, sessionKey)) {
        onChange(values.body || '');
        replyRef.current?.focus();
      }
    } catch (failure) {
      if (currentOperation(epoch, sessionKey) && failure.name !== 'AbortError') {
        setRecoveryError(failure.message || 'Der Entwurf konnte nicht wiederhergestellt werden.');
      }
    }
  };
  const cancelDiscard = () => {
    if (discardActive.current) return;
    setConfirmDiscard(false);
    discardRef.current?.focus();
  };
  const discard = async () => {
    if (!confirmDiscard || !saved.recovery || discardActive.current || cleanupActive.current
        || notice.sending || notice.uncertain) return;
    const epoch = generation.current;
    const sessionKey = saved.sessionKey;
    const sameThread = () => generation.current === epoch && activeThread.current === thread.id;
    discardActive.current = true;
    setDiscardBusy(true); setRecoveryError('');
    try {
      await saved.clear();
      if (currentOperation(epoch, sessionKey)) {
        focusReplyAfterDiscard.current = true;
        setConfirmDiscard(false);
      }
    } catch (failure) {
      if (currentOperation(epoch, sessionKey) && failure.name !== 'AbortError') {
        setRecoveryError(failure.message || 'Der Antwortentwurf konnte nicht verworfen werden.');
      }
    } finally {
      if (sameThread()) { discardActive.current = false; setDiscardBusy(false); }
    }
  };

  return <div className="thread-composer">
    <label htmlFor="thread-reply">Antwort an „{thread.subject}“</label>
    {saved.recovery && <section className="draft-recovery reply-draft-recovery" aria-label="Wiedergefundener Antwortentwurf"
      onKeyDown={event => {
        if (!confirmDiscard) return;
        if (event.key === 'Escape' || (event.key === 'Enter' && (event.ctrlKey || event.metaKey))) {
          event.preventDefault(); event.stopPropagation();
          if (event.key === 'Escape') cancelDiscard();
        }
      }}>
      <p role="status">Ein privater Antwortentwurf wurde wiedergefunden.</p>
      <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{saved.recovery.values.body}</pre>
      <div className="workspace-actions">
        <button type="button" className="btn btn-secondary" disabled={confirmDiscard || discardBusy || cleaning || notice.sending || notice.uncertain}
          onClick={recover}>Entwurf übernehmen</button>
        <button ref={discardRef} type="button" className="btn btn-ghost"
          disabled={discardBusy || cleaning || notice.sending || notice.uncertain}
          aria-expanded={confirmDiscard} aria-controls={confirmDiscard ? confirmId : undefined}
          onClick={() => setConfirmDiscard(true)}>{tr('ui.form.discardDraft', 'Entwurf verwerfen')}</button>
      </div>
      {confirmDiscard && <div id={confirmId} className="draft-discard-confirm" role="group"
        aria-label={tr('ui.form.confirmRecoveredDiscard', 'Entwurf verwerfen bestätigen')}>
        <p role="alert">{tr('ui.form.recoveredDiscardWarning', 'Wiedergefundenen Entwurf endgültig verwerfen? Die ungespeicherten Eingaben gehen verloren.')}</p>
        <div className="workspace-actions">
          <button ref={keepRef} type="button" className="btn btn-secondary" disabled={discardBusy}
            onClick={cancelDiscard}>{tr('ui.form.keepRecoveredDraft', 'Entwurf behalten')}</button>
          <button type="button" className="btn btn-danger"
            disabled={discardBusy || cleaning || notice.sending || notice.uncertain}
            onClick={discard}>{tr('ui.form.discardRecoveredDraft', 'Endgültig verwerfen')}</button>
        </div>
      </div>}
    </section>}
    <textarea ref={replyRef} id="thread-reply"
      disabled={cleaning || discardBusy || confirmDiscard || (saved.enabled && !saved.ready)}
      value={value} onChange={event => change(event.target.value)} rows={3}
      placeholder="Interne Nachricht schreiben …" onKeyDown={event => {
        if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
          event.preventDefault();
          if (!confirmDiscard && !discardBusy && !cleaning && !notice.sending && !notice.uncertain && value.trim()) onSend();
        }
      }} />
    {saved.enabled && <p role="status">{({ pending: 'Entwurf wird gesichert …', saving: 'Entwurf wird gespeichert …', saved: 'Privater Entwurf gespeichert', loading: 'Entwurf wird geladen …', changed: 'Die Konversation wurde geändert. Bitte vergleichen.' })[saved.status] || ''}</p>}
    {recoveryError && <p role="alert">{recoveryError}</p>}
    {saved.error && <div role="alert">{saved.error}<button type="button" onClick={saved.retry}>Entwurfssicherung wiederholen</button></div>}
    <button type="button" className="btn btn-primary" onClick={onSend}
      disabled={!value.trim() || cleaning || discardBusy || confirmDiscard || notice.sending || notice.uncertain}>
      {notice.sending ? 'Wird gespeichert …' : 'Senden'}
    </button>
  </div>;
}
