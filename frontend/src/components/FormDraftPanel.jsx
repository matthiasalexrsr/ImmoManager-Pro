import { useTranslation } from '../i18n';
import './FormDraftPanel.css';

export default function FormDraftPanel({ draft, businessSaved = false, onComplete }) {
  const { t, locale } = useTranslation();
  if (!draft.enabled) return null;
  const date = value => value && new Date(value).toLocaleString(locale || undefined, { dateStyle: 'short', timeStyle: 'short' });
  const available = draft.status === 'available';
  const busy = ['loading', 'saving', 'discarding', 'pending'].includes(draft.status);
  const uncertain = draft.status === 'uncertain';
  return <section className="form-draft-panel" aria-label={t('formDraft.title')}>
    <p className="form-draft-status" role="status">{businessSaved ? t('formDraft.businessSaved') : t(`formDraft.status.${draft.status}`)}</p>
    {draft.draft?.updated_at && <small>{t('formDraft.savedAt')} {date(draft.draft.updated_at)} · {t('formDraft.expiresAt')} {date(draft.draft.expires_at)}</small>}
    {available && <><p>{t(draft.draft.submission_pending ? 'formDraft.pendingRestore' : 'formDraft.restoreHint')}</p>
      {!draft.schemaMatches && <p role="alert">{t('formDraft.schemaChanged')}</p>}
      <div className="form-draft-actions"><button type="button" className="btn btn-secondary btn-sm" disabled={!draft.schemaMatches} onClick={draft.restore}>{t(draft.draft.submission_pending ? 'formDraft.restoreAfterReview' : 'formDraft.restore')}</button>
        <button type="button" className="btn btn-secondary btn-sm" onClick={draft.discard}>{t('formDraft.discard')}</button></div></>}
    {uncertain && <><p>{t('formDraft.pendingRestore')}</p><button type="button" className="btn btn-secondary btn-sm" onClick={draft.resume}>{t('formDraft.restoreAfterReview')}</button></>}
    {draft.error && <p className="form-draft-error" role="alert">{draft.error}</p>}
    {['error', 'conflict'].includes(draft.status) && <div className="form-draft-actions"><button type="button" className="btn btn-secondary btn-sm" onClick={businessSaved ? onComplete : draft.status === 'conflict' ? draft.inspect : draft.retry}>{t(businessSaved ? 'formDraft.cleanupRetry' : draft.status === 'conflict' ? 'formDraft.inspect' : 'ui.buttons.retry')}</button></div>}
    {businessSaved && <p>{t('formDraft.cleanupHint')}</p>}
    {!available && !uncertain && !businessSaved && !busy && <small>{t('formDraft.storageHint')}</small>}
  </section>;
}
