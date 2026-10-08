import { useId, useRef, useState } from 'react';
import { useTranslation } from '../../i18n';
import { CloseIcon } from '../../components/Icons';
import { useModalDialog } from '../../features/partyWorkspace/useModalDialog';

/**
 * Which portfolios an account sees and changes. Only owners assign them; the server
 * checks every read and write against this choice, also for tokens already issued.
 */
export default function PortfolioAccessDialog({ user, portfolios, onSave, onClose }) {
  const { t } = useTranslation();
  const u = (key, params) => t(`pages.settings.users.access.${key}`, params);
  const id = useId();
  const dialogRef = useRef(null);
  const [mode, setMode] = useState(user.portfolio_access === 'all' ? 'all' : 'selected');
  const [chosen, setChosen] = useState(() => new Set(user.portfolio_ids || []));
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  useModalDialog(dialogRef, onClose);

  const toggle = portfolioId => setChosen(current => {
    const next = new Set(current);
    if (next.has(portfolioId)) next.delete(portfolioId); else next.add(portfolioId);
    return next;
  });

  const submit = async event => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await onSave(mode === 'all'
        ? { portfolio_access: 'all', portfolio_ids: [] }
        : { portfolio_access: 'selected', portfolio_ids: portfolios.map(p => p.id).filter(pid => chosen.has(pid)) });
      onClose();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const nothing = mode === 'selected' && !portfolios.some(p => chosen.has(p.id));
  return (
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div className="modal" ref={dialogRef} onClick={e => e.stopPropagation()} role="dialog" aria-modal="true"
        aria-labelledby={`${id}-title`} tabIndex={-1}>
        <div className="modal-header">
          <h3 id={`${id}-title`}>{u('title', { name: user.full_name || user.username })}</h3>
          <button type="button" onClick={onClose} className="btn-close" aria-label={t('ui.buttons.close')}>
            <CloseIcon size={18} />
          </button>
        </div>
        <form onSubmit={submit}>
          <div className="modal-body portfolio-access">
            {error && <div className="alert-error" role="alert">{error}</div>}
            <p className="text-muted">{u('explanation')}</p>
            <fieldset className="form-section">
              <legend className="form-section-label">{u('scope')}</legend>
              <label className="portfolio-access-choice">
                <input type="radio" name={`${id}-mode`} value="all" checked={mode === 'all'} onChange={() => setMode('all')} />
                <span><strong>{u('all')}</strong><small>{u('allHint')}</small></span>
              </label>
              <label className="portfolio-access-choice">
                <input type="radio" name={`${id}-mode`} value="selected" checked={mode === 'selected'}
                  onChange={() => setMode('selected')} />
                <span><strong>{u('selected')}</strong><small>{u('selectedHint')}</small></span>
              </label>
            </fieldset>
            {mode === 'selected' && (
              <fieldset className="form-section">
                <legend className="form-section-label">{u('portfolios')}</legend>
                {portfolios.length === 0 ? <p className="text-muted">{u('noPortfolios')}</p> : (
                  <ul className="portfolio-access-list">
                    {portfolios.map(portfolio => (
                      <li key={portfolio.id}>
                        <label>
                          <input type="checkbox" checked={chosen.has(portfolio.id)} onChange={() => toggle(portfolio.id)} />
                          <span>{portfolio.name}</span>
                        </label>
                      </li>
                    ))}
                  </ul>
                )}
                {nothing && <p className="alert-info portfolio-access-warning" role="status">{u('nothingWarning')}</p>}
              </fieldset>
            )}
          </div>
          <div className="modal-footer">
            <button type="button" onClick={onClose} className="btn btn-secondary">{t('ui.buttons.cancel')}</button>
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? `${t('ui.buttons.save')}...` : t('ui.buttons.save')}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
