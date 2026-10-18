import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useCanWrite } from '../contexts/AuthContext';
import { dunningText } from '../features/dunning/dunningText';
import { CasesTab, OutboxTab, RepliesTab, RunTab, SettingsTab } from '../features/dunning/DunningTabs';
import '../features/dunning/dunning.css';

const TABS = ['cases', 'run', 'outbox', 'replies', 'settings'];
const TAB_KEYS = { cases: 'tabCases', run: 'tabRun', outbox: 'tabOutbox', replies: 'tabReplies', settings: 'tabSettings' };

// Mahnwesen (Finanzen): cases, run preview, outbox, replies to review, stage and base rate settings.
export default function Dunning() {
  const { locale } = useTranslation();
  const say = useCallback((key, params) => dunningText(locale, key, params), [locale]);
  const canWrite = useCanWrite('/dunning');
  const [tab, setTab] = useState('cases');
  const [portfolios, setPortfolios] = useState([]);

  useEffect(() => {
    const controller = new AbortController();
    api.list('/portfolios', { signal: controller.signal }).then(rows => setPortfolios(rows || [])).catch(() => {});
    return () => controller.abort();
  }, []);

  return (
    <div className="page dunning">
      <h1 className="page-title">{say('title')}</h1>
      <p className="page-subtitle dunning-intro">{say('intro')}</p>
      {!canWrite && <div role="note" className="alert alert-info">{say('readOnly')}</div>}
      <div className="detail-tabs" role="tablist" aria-label={say('title')}>
        {TABS.map(name => (
          <button key={name} type="button" role="tab" aria-selected={tab === name} id={`dn-tab-${name}`}
            className={`detail-tab${tab === name ? ' active' : ''}`}
            aria-controls={`dn-panel-${name}`} onClick={() => setTab(name)}>{say(TAB_KEYS[name])}</button>
        ))}
      </div>
      <div role="tabpanel" id={`dn-panel-${tab}`} aria-labelledby={`dn-tab-${tab}`}>
        {tab === 'cases' && <CasesTab say={say} />}
        {tab === 'run' && <RunTab say={say} canWrite={canWrite} portfolios={portfolios} />}
        {tab === 'outbox' && <OutboxTab say={say} canWrite={canWrite} />}
        {tab === 'replies' && <RepliesTab say={say} canWrite={canWrite} />}
        {tab === 'settings' && <SettingsTab say={say} canWrite={canWrite} />}
      </div>
    </div>
  );
}
