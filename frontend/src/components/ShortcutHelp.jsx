import { useEffect, useRef } from 'react';
import { useTranslation } from '../i18n';
import { CloseIcon } from './Icons';

const SHORTCUTS = [
  { keys: ['Strg', 'K'], alt: ['/'], key: 'shortcutHelp.search', fallback: 'Suche öffnen (Seiten, Aktionen, Datensätze)' },
  { keys: ['Enter'], key: 'shortcutHelp.firstHit', fallback: 'In der Suche: ersten Eintrag öffnen' },
  { keys: ['Alt', 'N'], key: 'shortcutHelp.newEntry', fallback: 'Neuen Eintrag in der Liste dieser Seite anlegen' },
  { keys: ['Strg', 'Enter'], key: 'shortcutHelp.save', fallback: 'Formular speichern' },
  { keys: ['Esc'], key: 'shortcutHelp.close', fallback: 'Dialog oder Suche schließen' },
  { keys: ['?'], key: 'shortcutHelp.help', fallback: 'Diese Übersicht anzeigen' },
];

export default function ShortcutHelp({ onClose }) {
  const { t } = useTranslation();
  const tr = (key, fallback) => { const text = t(key); return !text || text === key ? fallback : text; };
  const closeRef = useRef(null);
  useEffect(() => {
    const returnFocus = document.activeElement;
    closeRef.current?.focus();
    const keydown = event => { if (event.key === 'Escape') { event.preventDefault(); onClose(); } };
    document.addEventListener('keydown', keydown);
    return () => {
      document.removeEventListener('keydown', keydown);
      if (returnFocus?.isConnected) returnFocus.focus();
    };
  }, [onClose]);
  const title = tr('shortcutHelp.title', 'Tastenkürzel');
  return (
    <div className="modal-overlay" role="presentation" onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal shortcut-help" role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-header">
          <h3>{title}</h3>
          <button ref={closeRef} type="button" onClick={onClose} className="btn-close" aria-label={t('ui.buttons.close')}><CloseIcon size={18} /></button>
        </div>
        <div className="modal-body">
          <dl className="shortcut-list">
            {SHORTCUTS.map(item => (
              <div key={item.key} className="shortcut-row">
                <dt>
                  {item.keys.map((k, i) => <span key={k}>{i > 0 && ' + '}<kbd>{k}</kbd></span>)}
                  {item.alt && <span className="shortcut-or"> {tr('shortcutHelp.or', 'oder')} {item.alt.map(k => <kbd key={k}>{k}</kbd>)}</span>}
                </dt>
                <dd>{tr(item.key, item.fallback)}</dd>
              </div>
            ))}
          </dl>
        </div>
      </div>
    </div>
  );
}
