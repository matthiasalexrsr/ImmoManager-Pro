import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useConfirm } from '../components/ConfirmDialog';
import useWriteAccess from '../hooks/useWriteAccess';
import './DatevExport.css';

const endpoint = '/reports/datev';
const newRule = () => ({ key: crypto.randomUUID(), account_id: '', category_id: '', flow: 'income',
  account_type: '', bank_gl: '', counter_gl: '', counter_kind: 'general', no_vat_nonautomatic: true });
const newDraft = () => ({ name: '', adviser: '', client: '', gl_length: 4, chart: '', freeze: 0,
  currency: 'EUR', calendar_year: true, document_reference: 'empty', reviewed_by: '', review_confirmed: false,
  rules: [newRule()] });
const referenceFor = (ref, body) => {
  const encoded = JSON.stringify(body);
  if (ref.current?.encoded !== encoded) ref.current = { encoded, key: crypto.randomUUID() };
  return ref.current.key;
};
const validPreview = value => value?.id && value?.rows > 0 && Array.isArray(value.files) && value.files.length > 0 && Array.isArray(value.samples)
  && /^[a-f0-9]{64}$/.test(value.sha256 || '') && Number.isSafeInteger(value.size) && value.size > 0;

export default function DatevExport() {
  const { t, locale } = useTranslation();
  const label = key => t(`pages.datev.${key}`);
  const confirm = useConfirm();
  const { canWrite, requireWrite, isAllowed } = useWriteAccess('/reports');
  const [portfolios, setPortfolios] = useState([]);
  const [portfolioId, setPortfolioId] = useState('');
  const [profiles, setProfiles] = useState([]);
  const [profileTotal, setProfileTotal] = useState(0);
  const [options, setOptions] = useState({ accounts: [], categories: [] });
  const [selectedId, setSelectedId] = useState('');
  const [draft, setDraft] = useState(null);
  const [previousVersion, setPreviousVersion] = useState(null);
  const [journal, setJournal] = useState({ total: 0, items: [] });
  const [page, setPage] = useState(0);
  const [preview, setPreview] = useState(null);
  const [dates, setDates] = useState({ start_date: `${new Date().getFullYear()}-01-01`, end_date: new Date().toISOString().slice(0, 10) });
  const [loading, setLoading] = useState(false);
  const [journalLoading, setJournalLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const running = useRef(false);
  const activePortfolio = useRef('');
  const profileCommand = useRef(null);
  const previewCommand = useRef(null);
  const firstField = useRef(null);
  const summaryRef = useRef(null);
  const selected = profiles.find(profile => profile.id === selectedId);

  useEffect(() => {
    const controller = new AbortController();
    api.getAll('/portfolios', { signal: controller.signal }).then(setPortfolios)
      .catch(err => { if (err.name !== 'AbortError') setError(err.message); });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    activePortfolio.current = portfolioId;
    if (!portfolioId) return undefined;
    const controller = new AbortController();
    setLoading(true); setError('');
    const query = `portfolio_id=${encodeURIComponent(portfolioId)}`;
    Promise.all([api.get(`${endpoint}/profiles?${query}&limit=100`, { signal: controller.signal }),
      api.get(`${endpoint}/options?${query}`, { signal: controller.signal })])
      .then(([versions, choices]) => {
        if (controller.signal.aborted) return;
        setProfiles(versions.items); setProfileTotal(versions.total); setOptions(choices);
      }).catch(err => { if (err.name !== 'AbortError') setError(err.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [portfolioId]);

  useEffect(() => {
    if (!portfolioId) return undefined;
    const controller = new AbortController();
    setJournalLoading(true);
    api.get(`${endpoint}/exports?portfolio_id=${encodeURIComponent(portfolioId)}&offset=${page * 10}&limit=10`, { signal: controller.signal })
      .then(exports => { if (!controller.signal.aborted) setJournal(exports); })
      .catch(err => { if (err.name !== 'AbortError') setError(err.message); })
      .finally(() => { if (!controller.signal.aborted) setJournalLoading(false); });
    return () => controller.abort();
  }, [portfolioId, page]);

  useEffect(() => { if (draft) firstField.current?.focus(); }, [!!draft]); // eslint-disable-line react-hooks/exhaustive-deps

  const changePortfolio = async value => {
    if (running.current || (draft && !await confirm(label('discardDraft')))) return;
    setPortfolioId(value); setPage(0); setProfiles([]); setSelectedId(''); setPreview(null);
    setJournal({ total: 0, items: [] }); setDraft(null); setNotice('');
  };
  const beginDraft = existing => {
    if (!canWrite || running.current) return;
    setDraft(existing ? { ...existing.spec, rules: existing.spec.rules.map(rule => ({ ...rule, key: crypto.randomUUID() })), review_confirmed: false } : newDraft());
    setPreviousVersion(existing?.id || null); setError(''); setNotice(''); profileCommand.current = null;
  };
  const field = (name, value) => setDraft(current => ({ ...current, [name]: value }));
  const ruleField = (key, name, value) => setDraft(current => ({ ...current,
    rules: current.rules.map(rule => rule.key === key ? { ...rule, [name]: value,
      ...(name === 'account_id' ? { account_type: options.accounts.find(account => account.id === value)?.account_type || '' } : {}) } : rule) }));

  const saveProfile = async event => {
    event.preventDefault();
    if (running.current) return;
    running.current = true; setBusy(true); setError('');
    try {
      requireWrite();
      const body = { ...draft, portfolio_id: portfolioId, previous_version_id: previousVersion,
        adviser: Number(draft.adviser), client: Number(draft.client), gl_length: Number(draft.gl_length), freeze: Number(draft.freeze),
        rules: draft.rules.map(rule => { const bodyRule = { ...rule }; delete bodyRule.key; return bodyRule; }) };
      const saved = await api.post(`${endpoint}/profiles`, { ...body, idempotency_key: referenceFor(profileCommand, body) });
      if (!isAllowed() || activePortfolio.current !== portfolioId) return;
      if (!saved?.id || !saved?.spec) throw new Error(label('malformed'));
      setProfiles(current => [saved, ...current.filter(row => row.id !== saved.id)]);
      setProfileTotal(current => current + 1); setSelectedId(saved.id); setDraft(null); setPreview(null);
      setNotice(`${label('saved')} · ${saved.id}`);
    } catch (err) { setError(err.message); }
    finally { running.current = false; setBusy(false); }
  };

  const generatePreview = async event => {
    event.preventDefault();
    if (running.current) return;
    running.current = true; setBusy(true); setError(''); setPreview(null);
    try {
      requireWrite();
      const body = { profile_version_id: selectedId, ...dates };
      const result = await api.post(`${endpoint}/preview`, { ...body, idempotency_key: referenceFor(previewCommand, body) });
      if (!isAllowed() || activePortfolio.current !== portfolioId) return;
      if (!validPreview(result)) throw new Error(label('malformed'));
      setPreview(result); setNotice('');
      const exports = await api.get(`${endpoint}/exports?portfolio_id=${encodeURIComponent(portfolioId)}&offset=${page * 10}&limit=10`);
      if (activePortfolio.current === portfolioId) setJournal(exports);
      requestAnimationFrame(() => { summaryRef.current?.focus(); summaryRef.current?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' }); });
    } catch (err) { setError(err.message); }
    finally { running.current = false; setBusy(false); }
  };

  const download = async entry => {
    if (running.current) return;
    running.current = true; setBusy(true); setError('');
    let url;
    try {
      if (!validPreview(entry)) throw new Error(label('malformed'));
      const blob = await api.getBlob(`${endpoint}/exports/${encodeURIComponent(entry.id)}/download`);
      if (blob.type.split(';')[0] !== 'application/zip' || blob.size !== entry.size) throw new Error(label('malformed'));
      const actual = [...new Uint8Array(await crypto.subtle.digest('SHA-256', await blob.arrayBuffer()))].map(b => b.toString(16).padStart(2, '0')).join('');
      if (actual !== entry.sha256) throw new Error(label('malformed'));
      if (activePortfolio.current !== portfolioId) return;
      url = URL.createObjectURL(blob);
      const anchor = document.createElement('a'); anchor.href = url; anchor.download = `DATEV_${entry.id}.zip`;
      document.body.appendChild(anchor); anchor.click(); anchor.remove();
      setNotice(`${label('downloaded')} · ${entry.id}`);
    } catch (err) { setError(err.message); }
    finally { if (url) URL.revokeObjectURL(url); running.current = false; setBusy(false); }
  };

  const moreProfiles = async () => {
    if (running.current) return;
    running.current = true; setBusy(true);
    try {
      const result = await api.get(`${endpoint}/profiles?portfolio_id=${encodeURIComponent(portfolioId)}&offset=${profiles.length}&limit=100`);
      setProfiles(current => [...current, ...result.items]); setProfileTotal(result.total);
    } catch (err) { setError(err.message); }
    finally { running.current = false; setBusy(false); }
  };

  return <div className="datev-workspace" aria-busy={busy || loading || journalLoading}>
    <header className="datev-heading"><div><p className="datev-eyebrow">{label('eyebrow')}</p><h1>{label('title')}</h1><p>{label('intro')}</p></div>
      <Link className="btn btn-secondary" to="/bookings">{label('bookings')}</Link></header>
    <div className="datev-guidance"><p>{label('scope')}</p><p>{label('limits')}</p></div>
    {error && <div className="alert alert-danger" role="alert">{error}</div>}
    {notice && <p className="datev-notice" role="status">{notice}</p>}
    {(busy || loading) && <p role="status">{label('working')}</p>}
    <label className="datev-portfolio">{label('portfolio')}<select value={portfolioId} disabled={busy || loading}
      onChange={event => changePortfolio(event.target.value)}><option value="">{label('choosePortfolio')}</option>
      {portfolios.map(portfolio => <option key={portfolio.id} value={portfolio.id}>{portfolio.name}</option>)}</select></label>
    {portfolioId && <>
      <section className="datev-panel" aria-label={label('profiles')}><div className="datev-section-head"><h2>{label('profiles')}</h2>
        {canWrite && <button type="button" className="btn btn-secondary" disabled={busy || loading || !!draft} onClick={() => beginDraft(null)}>{label('newProfile')}</button>}</div>
        <label>{label('version')}<select value={selectedId} disabled={busy || loading || !!draft} onChange={event => { setSelectedId(event.target.value); setPreview(null); }}>
          <option value="">{label('chooseVersion')}</option>{profiles.map(profile => <option key={profile.id} value={profile.id}>{profile.spec.name} · {profile.created_at} · {profile.id.slice(0, 8)}</option>)}</select></label>
        {profiles.length < profileTotal && <button type="button" disabled={busy} className="btn btn-secondary" onClick={moreProfiles}>{label('moreVersions')}</button>}
        {selected && !draft && <div className="datev-profile-summary"><p>{label('reviewedBy')}: {selected.spec.reviewed_by} · {label('versionId')}: <code>{selected.id}</code></p>
          <p>{label('adviser')}: {selected.spec.adviser} · {label('client')}: {selected.spec.client} · {label('glLength')}: {selected.spec.gl_length} · {label('mappings')}: {selected.spec.rules.length}</p>
          {canWrite && <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => beginDraft(selected)}>{label('newVersion')}</button>}</div>}
      </section>
      {draft && <section className="datev-panel"><h2>{previousVersion ? label('newVersion') : label('newProfile')}</h2><p>{label('immutable')}</p>
        <form onSubmit={saveProfile} aria-busy={busy}><fieldset disabled={busy || !canWrite}>
          <div className="datev-field-grid">
            <label>{label('name')}<input ref={firstField} required maxLength={200} value={draft.name} onChange={event => field('name', event.target.value)} /></label>
            <label>{label('adviser')}<input required inputMode="numeric" pattern="[0-9]{4,7}" value={draft.adviser} onChange={event => field('adviser', event.target.value)} /></label>
            <label>{label('client')}<input required inputMode="numeric" pattern="[0-9]{1,5}" value={draft.client} onChange={event => field('client', event.target.value)} /></label>
            <label>{label('glLength')}<select value={draft.gl_length} onChange={event => field('gl_length', event.target.value)}>{[4,5,6,7,8].map(value => <option key={value}>{value}</option>)}</select></label>
            <label>{label('chart')}<input pattern="([0-9]{2}|[0-9]{4})?" value={draft.chart} onChange={event => field('chart', event.target.value)} /></label>
            <label>{label('freeze')}<select value={draft.freeze} onChange={event => field('freeze', event.target.value)}><option value={0}>{label('notFrozen')}</option><option value={1}>{label('frozen')}</option></select></label>
            <label>{label('documentReference')}<select value={draft.document_reference} onChange={event => field('document_reference', event.target.value)}><option value="empty">{label('emptyReference')}</option><option value="internal_booking_id">{label('internalReference')}</option></select></label>
            <label>{label('reviewedBy')}<input required maxLength={200} value={draft.reviewed_by} onChange={event => field('reviewed_by', event.target.value)} /></label>
          </div>
          <p>{label('mappingHint')}</p>
          {draft.rules.map((rule, index) => <fieldset className="datev-rule" key={rule.key}><legend>{label('mapping')} {index + 1}</legend>
            <div className="datev-field-grid">
              <label>{label('account')}<select required value={rule.account_id} onChange={event => ruleField(rule.key, 'account_id', event.target.value)}><option value="">{label('choose')}</option>{options.accounts.map(account => <option key={account.id} value={account.id}>{account.name} · {account.account_type}</option>)}</select></label>
              <label>{label('category')}<select required value={rule.category_id} onChange={event => ruleField(rule.key, 'category_id', event.target.value)}><option value="">{label('choose')}</option>{options.categories.map(category => <option key={category.id} value={category.id}>{category.name}</option>)}</select></label>
              <label>{label('flow')}<select value={rule.flow} onChange={event => ruleField(rule.key, 'flow', event.target.value)}><option value="income">{label('income')}</option><option value="expense">{label('expense')}</option></select></label>
              <label>{label('bankGl')}<input required inputMode="numeric" pattern="[0-9]{1,8}" value={rule.bank_gl} onChange={event => ruleField(rule.key, 'bank_gl', event.target.value)} /></label>
              <label>{label('counterGl')}<input required inputMode="numeric" pattern="[0-9]{1,9}" value={rule.counter_gl} onChange={event => ruleField(rule.key, 'counter_gl', event.target.value)} /></label>
              <label>{label('counterKind')}<select value={rule.counter_kind} onChange={event => ruleField(rule.key, 'counter_kind', event.target.value)}><option value="general">{label('general')}</option><option value="person">{label('person')}</option></select></label>
            </div><button type="button" className="btn btn-secondary" disabled={draft.rules.length === 1} onClick={() => setDraft(current => ({ ...current, rules: current.rules.filter(item => item.key !== rule.key) }))}>{label('removeMapping')}</button>
          </fieldset>)}
          <button type="button" className="btn btn-secondary" onClick={() => setDraft(current => ({ ...current, rules: [...current.rules, newRule()] }))}>{label('addMapping')}</button>
          <label className="datev-review"><input type="checkbox" required checked={draft.review_confirmed} onChange={event => field('review_confirmed', event.target.checked)} />{label('reviewConfirmation')}</label>
          <div className="datev-actions"><button className="btn btn-primary" type="submit">{label('saveVersion')}</button><button type="button" className="btn btn-secondary" onClick={async () => { if (await confirm(label('discardDraft'))) setDraft(null); }}>{label('cancel')}</button></div>
        </fieldset></form>
      </section>}
      <section className="datev-panel"><h2>{label('preview')}</h2><form onSubmit={generatePreview}><fieldset disabled={busy || loading || !canWrite || !!draft}>
        <div className="datev-period"><label>{label('from')}<input type="date" required value={dates.start_date} onChange={event => { setDates(current => ({ ...current, start_date: event.target.value })); setPreview(null); }} /></label>
          <label>{label('to')}<input type="date" required value={dates.end_date} onChange={event => { setDates(current => ({ ...current, end_date: event.target.value })); setPreview(null); }} /></label>
          <button type="submit" className="btn btn-primary" disabled={!selectedId}>{label('validate')}</button></div>
      </fieldset></form><p>{label('validationHint')}</p>
        {preview && <div className="datev-preview" tabIndex={-1} ref={summaryRef}><h3>{label('ready')}</h3><p>{preview.rows.toLocaleString(locale)} {label('rows')} · {preview.files.length} {label('files')} · {label('income')}: {preview.income} EUR · {label('expense')}: {preview.expense} EUR</p>
          <p>{label('reference')}: <code>{preview.id}</code></p><p>{label('fingerprint')}: <code>{preview.sha256}</code></p>
          <ul>{preview.files.map(file => <li key={file.name}>{file.name} · {file.rows.toLocaleString(locale)} {label('rows')}</li>)}</ul>
          <div className="datev-table"><table><caption>{label('samples')}</caption><thead><tr><th>{label('date')}</th><th>{label('bookingId')}</th><th>{label('amount')}</th><th>{label('text')}</th></tr></thead>
            <tbody>{preview.samples.map(row => <tr key={row.id}><td>{row.date}</td><td><code>{row.id}</code></td><td>{row.amount}</td><td>{row.text}</td></tr>)}</tbody></table></div>
          <button type="button" className="btn btn-primary" disabled={busy} onClick={() => download(preview)}>{label('download')}</button>
        </div>}
      </section>
      <section className="datev-panel"><h2>{label('journal')}</h2><p>{label('journalHint')}</p>
        {journal.items.length === 0 ? <p>{label('emptyJournal')}</p> : <div className="datev-table"><table><thead><tr><th>{label('reference')}</th><th>{label('period')}</th><th>{label('rows')}</th><th>{label('versionId')}</th><th>{label('file')}</th></tr></thead>
          <tbody>{journal.items.map(entry => <tr key={entry.id}><td><code>{entry.id}</code><small>{entry.generated_at}</small></td><td>{entry.start_date} — {entry.end_date}</td><td>{entry.rows.toLocaleString(locale)}</td><td><code>{entry.profile_version_id}</code></td><td><button type="button" className="btn btn-secondary" disabled={busy} onClick={() => download(entry)}>{label('download')}</button></td></tr>)}</tbody></table></div>}
        <div className="datev-actions"><button type="button" className="btn btn-secondary" disabled={busy || loading || journalLoading || page === 0} onClick={() => setPage(current => current - 1)}>{label('previous')}</button><span>{page + 1} / {Math.max(1, Math.ceil(journal.total / 10))}</span><button type="button" className="btn btn-secondary" disabled={busy || loading || journalLoading || (page + 1) * 10 >= journal.total} onClick={() => setPage(current => current + 1)}>{label('next')}</button></div>
      </section>
    </>}
  </div>;
}
