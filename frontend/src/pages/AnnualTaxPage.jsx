import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { useAuth } from '../contexts/AuthContext';
import { useTranslation } from '../i18n';
import { useConfirm } from '../components/ConfirmDialog';
import useWriteAccess from '../hooks/useWriteAccess';
import './AnnualTaxPage.css';

const endpoint = '/reports/annual-tax';
const key = () => crypto.randomUUID();
const newClassification = () => ({ treatment: 'income', form_line: '', reason: '', exclusion_kind: '' });
const newRule = () => ({ key: key(), account_id: '', category_id: '', ...newClassification() });
const newPart = () => ({ key: key(), property_id: '', amount: '', ...newClassification() });
const today = () => new Date().toLocaleDateString('en-CA');
const referenceFor = (ref, body) => {
  const encoded = JSON.stringify(body);
  if (ref.current?.encoded !== encoded) ref.current = { encoded, key: key() };
  return ref.current.key;
};
const centsFor = amount => {
  if (!/^-?\d+(?:[.,]\d{1,2})?$/.test(amount.trim())) throw new Error('invalid');
  const [whole, fraction = ''] = amount.trim().replace(',', '.').replace('-', '').split('.');
  const value = (BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0'))) * (amount.trim().startsWith('-') ? -1n : 1n);
  if (value === 0n || value > 999999999999n || value < -999999999999n) throw new Error('invalid');
  return value.toString();
};
const decimalFor = cents => {
  const value = BigInt(cents), absolute = value < 0n ? -value : value;
  return `${value < 0n ? '-' : ''}${absolute / 100n}.${String(absolute % 100n).padStart(2, '0')}`;
};
const euro = (cents, locale) => {
  if (!/^-?\d+$/.test(cents || '')) return '—';
  const value = BigInt(cents), absolute = value < 0n ? -value : value;
  const separator = new Intl.NumberFormat(locale).formatToParts(1.1).find(part => part.type === 'decimal').value;
  return `${value < 0n ? '−' : ''}${new Intl.NumberFormat(locale).format(absolute / 100n)}${separator}${String(absolute % 100n).padStart(2, '0')} €`;
};
const classification = row => ({ treatment: row.treatment, form_line: row.treatment === 'excluded' ? null : row.form_line.trim(),
  reason: row.reason.trim(), exclusion_kind: row.treatment === 'excluded' ? row.exclusion_kind : null });
const validClassification = row => row.reason.trim() && (row.treatment === 'excluded' ? row.exclusion_kind : row.form_line.trim());
const validPreview = value => value && typeof value.ready === 'boolean' && /^[a-f0-9]{64}$/.test(value.preview_hash || '')
  && Array.isArray(value.groups) && Array.isArray(value.source_samples) && value.totals && value.blocking_issue_counts;

function useResource(path, identity, all = false) {
  const requestKey = `${identity}:${path}`;
  const [state, setState] = useState({ data: null, loading: false, error: '', requestKey: '' });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    if (!path) return undefined;
    setState({ data: null, loading: true, error: '', requestKey });
    (all ? api.getAll(path, { signal: controller.signal }) : api.get(path, { signal: controller.signal }))
      .then(data => { if (!controller.signal.aborted) setState({ data, loading: false, error: '', requestKey }); })
      .catch(error => { if (!controller.signal.aborted) setState({ data: null, loading: false, error: error.message, requestKey }); });
    return () => controller.abort();
  }, [path, identity, requestKey, all, attempt]);
  const current = state.requestKey === requestKey && path ? state : { data: null, loading: !!path, error: '' };
  return { ...current, retry: () => setAttempt(value => value + 1) };
}

function ResourceState({ resource, t, children }) {
  if (resource.loading) return <p role="status">{t('working')}</p>;
  if (resource.error) return <div className="tax-error" role="alert"><p>{resource.error}</p><button type="button" className="btn btn-secondary" onClick={resource.retry}>{t('retry')}</button></div>;
  return children;
}

function Choice({ label, value, options, onChange, empty, required = false }) {
  return <label>{label}<select value={value || ''} required={required} onChange={event => onChange(event.target.value)}>
    <option value="">{empty}</option>{options.map(option => <option key={option.id} value={option.id}>{option.name}</option>)}</select></label>;
}

function ClassificationFields({ row, update, t }) {
  return <>
    <label>{t('treatment')}<select value={row.treatment} onChange={event => update('treatment', event.target.value)}>
      {['income', 'expense', 'excluded'].map(value => <option key={value} value={value}>{t(value)}</option>)}</select></label>
    {row.treatment === 'excluded' ? <label>{t('exclusionKind')}<select value={row.exclusion_kind || ''} required onChange={event => update('exclusion_kind', event.target.value)}>
      <option value="">{t('choose')}</option>{['internal_transfer', 'deposit', 'loan_principal', 'personal', 'other'].map(value => <option key={value} value={value}>{t(`exclusions.${value}`)}</option>)}</select></label>
      : <label>{t('formLine')}<input value={row.form_line || ''} required maxLength={200} onChange={event => update('form_line', event.target.value)} /></label>}
    <label className="tax-wide">{t('reason')}<input value={row.reason} required maxLength={1000} onChange={event => update('reason', event.target.value)} /></label>
  </>;
}

export default function AnnualTaxPage() {
  const { t: translate, locale } = useTranslation();
  const t = name => translate(`pages.annualTax.${name}`);
  const auth = useAuth();
  const identity = JSON.stringify([auth?.user?.id, auth?.user?.role, auth?.user?.portfolio_access, auth?.user?.portfolio_ids]);
  const confirm = useConfirm();
  const [portfolioId, setPortfolioId] = useState('');
  const [year, setYear] = useState(String(new Date().getFullYear() - 1));
  const [selectedId, setSelectedId] = useState('');
  const [loadedProfiles, setLoadedProfiles] = useState([]);
  const [draft, setDraft] = useState(null);
  const [asOf, setAsOf] = useState(today());
  const [overrides, setOverrides] = useState([]);
  const [pendingReason, setPendingReason] = useState('');
  const [emptyReason, setEmptyReason] = useState('');
  const [previousId, setPreviousId] = useState('');
  const [revisionReason, setRevisionReason] = useState('');
  const [preview, setPreview] = useState(null);
  const [page, setPage] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const { canWrite, requireWrite, isAllowed } = useWriteAccess('/reports', () => { setDraft(null); setOverrides([]); setPreview(null); });
  const portfolios = useResource('/portfolios', identity, true);
  const validYear = /^\d{1,4}$/.test(year) && Number(year) >= 1 && Number(year) <= 9998;
  const query = portfolioId && validYear ? `portfolio_id=${encodeURIComponent(portfolioId)}&tax_year=${year}` : '';
  const options = useResource(portfolioId ? `${endpoint}/options?portfolio_id=${encodeURIComponent(portfolioId)}` : null, identity);
  const profiles = useResource(query ? `${endpoint}/profiles?${query}&limit=100` : null, identity);
  const journal = useResource(query ? `${endpoint}/projections?${query}&offset=${page * 10}&limit=10` : null, identity);
  const allProfiles = [...(profiles.data?.items || []), ...loadedProfiles].filter((row, index, values) => values.findIndex(item => item.id === row.id) === index);
  const selected = allProfiles.find(row => row.id === selectedId);
  const choices = options.data || { accounts: [], categories: [], properties: [] };
  const running = useRef(false), profileCommand = useRef(null), snapshotCommand = useRef(null), heading = useRef(null);
  const active = useRef('');
  const namespace = `${identity}:${portfolioId}:${year}:${selectedId}`;
  active.current = namespace;
  const contextCurrent = () => active.current === namespace;
  const reviewSignature = JSON.stringify([asOf, pendingReason, emptyReason, overrides, preview?.preview_hash, previousId, revisionReason]);
  const currentReview = useRef(''); currentReview.current = reviewSignature;
  useEffect(() => { setSelectedId(''); setLoadedProfiles([]); setDraft(null); setOverrides([]); setPreview(null); }, [identity]);

  const resetPreview = () => { setPreview(null); setNotice(''); };
  const changeContext = async (setter, value) => {
    if (running.current || ((draft || overrides.length) && !await confirm(t('discard')))) return;
    setter(value); setSelectedId(''); setLoadedProfiles([]); setDraft(null); setOverrides([]); setPreview(null);
    setPreviousId(''); setRevisionReason(''); setPage(0); setError(''); setNotice('');
  };
  const beginProfile = existing => {
    if (!canWrite || running.current || !options.data) return;
    setDraft(existing ? { ...existing.spec, previous_version_id: existing.id, review_confirmed: false,
      rules: existing.spec.rules.map(rule => ({ ...rule, key: key(), category_id: rule.category_id || '', exclusion_kind: rule.exclusion_kind || '' })) }
      : { name: '', reviewed_by: auth?.user?.full_name || '', review_confirmed: false, previous_version_id: null, rules: [newRule()] });
    setError(''); profileCommand.current = null;
  };
  const ruleUpdate = (rowKey, field, value) => setDraft(current => ({ ...current, rules: current.rules.map(row => row.key === rowKey ? { ...row, [field]: value } : row) }));
  const patchOverride = (rowKey, field, value) => { setOverrides(current => current.map(row => row.key === rowKey ? { ...row, [field]: value } : row)); resetPreview(); };
  const patchPart = (rowKey, partKey, field, value) => {
    setOverrides(current => current.map(row => row.key === rowKey ? { ...row, parts: row.parts.map(part => part.key === partKey ? { ...part, [field]: value } : part) } : row)); resetPreview();
  };
  const addOverride = source => {
    if (!canWrite || running.current) return;
    const sourceId = source?.booking?.id || '';
    if (sourceId && overrides.some(row => row.booking_id === sourceId)) return;
    const from = source?.parts?.[0];
    const overrideKey = key();
    setOverrides(current => [...current, { key: overrideKey, booking_id: sourceId, reason: '', correction_of_booking_id: '', transfer_counter_booking_id: '',
      parts: [{ ...newPart(), ...(from ? { ...from, form_line: from.form_line || '', exclusion_kind: from.exclusion_kind || '' } : {}),
        property_id: from?.property_id || source?.booking?.property_id || '', amount: source?.booking?.amount_cents ? decimalFor(source.booking.amount_cents) : '' }] }]);
    resetPreview();
    requestAnimationFrame(() => document.getElementById(`tax-override-${overrideKey}`)?.focus());
  };

  const saveProfile = async event => {
    event.preventDefault(); if (running.current) return;
    if (!draft.review_confirmed || !draft.name.trim() || !draft.reviewed_by.trim() || !draft.rules.length
      || draft.rules.some(row => !row.account_id || !validClassification(row))) { setError(t('profileInvalid')); return; }
    running.current = true; setBusy(true); setError('');
    try {
      requireWrite();
      const body = { portfolio_id: portfolioId, tax_year: Number(year), currency: 'EUR', name: draft.name.trim(), reviewed_by: draft.reviewed_by.trim(),
        review_confirmed: true, previous_version_id: draft.previous_version_id, rules: draft.rules.map(row => ({ account_id: row.account_id, category_id: row.category_id || null, ...classification(row) })) };
      const saved = await api.post(`${endpoint}/profiles`, { ...body, idempotency_key: referenceFor(profileCommand, body) });
      if (!isAllowed() || !contextCurrent()) return;
      if (!saved?.id || !saved?.spec) throw new Error(t('malformed'));
      setLoadedProfiles(current => [saved, ...current]); setSelectedId(saved.id); setDraft(null); setPreview(null); setNotice(t('profileSaved'));
    } catch (err) { if (contextCurrent()) setError(err.message); }
    finally { running.current = false; setBusy(false); }
  };
  const command = () => ({ profile_version_id: selectedId, as_of: asOf, pending_review_reason: pendingReason.trim() || null, empty_cash_review_reason: emptyReason.trim() || null,
    overrides: overrides.map(row => ({ booking_id: row.booking_id.trim(), reason: row.reason.trim(), correction_of_booking_id: row.correction_of_booking_id.trim() || null,
      transfer_counter_booking_id: row.transfer_counter_booking_id.trim() || null, parts: row.parts.map(part => ({ ...classification(part), amount_cents: centsFor(part.amount), property_id: part.property_id || null })) })) });
  const preflight = async event => {
    event.preventDefault(); if (running.current) return;
    running.current = true; setBusy(true); setError(''); setPreview(null);
    try {
      requireWrite(); let body;
      try { body = command(); } catch { throw new Error(t('amountInvalid')); }
      const result = await api.post(`${endpoint}/preflight`, body);
      if (!isAllowed() || !contextCurrent()) return;
      if (!validPreview(result)) throw new Error(t('malformed'));
      setPreview(result); setNotice(''); requestAnimationFrame(() => heading.current?.focus());
    } catch (err) { if (contextCurrent()) setError(err.message); }
    finally { running.current = false; setBusy(false); }
  };
  const saveSnapshot = async () => {
    if (running.current || !preview?.ready || !canWrite) return;
    if (!await confirm(t('confirmSnapshot'))) return;
    if (running.current || !contextCurrent() || currentReview.current !== reviewSignature) return;
    running.current = true; setBusy(true); setError('');
    try {
      requireWrite();
      const body = { ...command(), preview_hash: preview.preview_hash, previous_projection_id: previousId || null, revision_reason: previousId ? revisionReason.trim() : null };
      const saved = await api.post(`${endpoint}/projections`, { ...body, idempotency_key: referenceFor(snapshotCommand, body) });
      if (!isAllowed() || !contextCurrent()) return;
      if (!saved?.id || !validPreview(saved)) throw new Error(t('malformed'));
      setPreview(saved); setPreviousId(saved.id); setRevisionReason(''); setNotice(t('snapshotSaved')); journal.retry();
    } catch (err) { if (contextCurrent()) { setError(err.message); if (err.statusCode === 409) setPreview(null); } }
    finally { running.current = false; setBusy(false); }
  };
  const download = async row => {
    if (running.current) return;
    running.current = true; setBusy(true); setError(''); let url;
    try {
      const blob = await api.getBlob(`${endpoint}/projections/${encodeURIComponent(row.id)}/download`);
      if (blob.type.split(';')[0] !== 'application/zip' || !blob.size) throw new Error(t('malformed'));
      if (!contextCurrent()) return;
      url = URL.createObjectURL(blob); const anchor = document.createElement('a');
      anchor.href = url; anchor.download = `annual-tax-${row.tax_year}-${row.id}.zip`; document.body.appendChild(anchor); anchor.click(); anchor.remove();
    } catch (err) { if (contextCurrent()) setError(err.message); }
    finally { if (url) URL.revokeObjectURL(url); running.current = false; setBusy(false); }
  };
  const moreProfiles = async () => {
    if (running.current) return; running.current = true; setBusy(true); setError('');
    try {
      const result = await api.get(`${endpoint}/profiles?${query}&offset=${allProfiles.length}&limit=100`);
      if (contextCurrent()) setLoadedProfiles(current => [...current, ...result.items]);
    } catch (err) { if (contextCurrent()) setError(err.message); }
    finally { running.current = false; setBusy(false); }
  };
  const reviseSnapshot = async row => {
    if (running.current || !canWrite) return;
    running.current = true; setBusy(true); setError('');
    try {
      requireWrite();
      const version = allProfiles.find(item => item.id === row.profile_version_id) || await api.get(`${endpoint}/profiles/${encodeURIComponent(row.profile_version_id)}`);
      if (!isAllowed() || !contextCurrent()) return;
      if (!version?.id || !version?.spec || !row.review_request) throw new Error(t('malformed'));
      const request = row.review_request;
      setLoadedProfiles(current => [version, ...current]); setSelectedId(version.id); setPreviousId(row.id); setPreview(null); setRevisionReason('');
      setAsOf(request.as_of); setPendingReason(request.pending_review_reason || ''); setEmptyReason(request.empty_cash_review_reason || '');
      setOverrides(request.overrides.map(item => ({ ...item, key: key(), correction_of_booking_id: item.correction_of_booking_id || '', transfer_counter_booking_id: item.transfer_counter_booking_id || '',
        parts: item.parts.map(part => ({ ...part, key: key(), amount: decimalFor(part.amount_cents), form_line: part.form_line || '', exclusion_kind: part.exclusion_kind || '', property_id: part.property_id || '' })) })));
    } catch (err) { if (contextCurrent()) setError(err.message); }
    finally { running.current = false; setBusy(false); }
  };

  return <div className="annual-tax-page" aria-busy={busy}>
    <header className="tax-heading"><div><p className="tax-eyebrow">{t('eyebrow')}</p><h1>{translate('finance.tax')}</h1><p>{t('intro')}</p></div>
      <Link to="/bookings" className="btn btn-secondary">{t('bookings')}</Link></header>
    <aside className="tax-guidance"><p>{t('cashBasis')}</p><p>{t('boundary')}</p></aside>
    {error && <div className="tax-error" role="alert">{error}</div>}{notice && <p className="tax-notice" role="status">{notice}</p>}
    {busy && <p role="status">{t('working')}</p>}
    <section className="tax-panel"><h2>{t('context')}</h2><ResourceState resource={portfolios} t={t}>
      <div className="tax-fields"><label>{t('portfolio')}<select value={portfolioId} disabled={busy} onChange={event => changeContext(setPortfolioId, event.target.value)}>
        <option value="">{t('choosePortfolio')}</option>{(portfolios.data || []).map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
        <label>{t('year')}<input type="number" min="1" max="9998" step="1" value={year} disabled={busy} onChange={event => changeContext(setYear, event.target.value)} /></label></div>
      {portfolios.data?.length === 0 && <p>{t('noPortfolios')}</p>}</ResourceState>
    </section>
    {query && <>
      <section className="tax-panel"><div className="tax-section-heading"><div><p className="tax-eyebrow">01</p><h2>{t('mapping')}</h2></div>
        {canWrite && <button type="button" className="btn btn-primary" disabled={busy || !options.data} onClick={() => beginProfile(null)}>{t('newProfile')}</button>}</div>
        <ResourceState resource={options} t={t}><ResourceState resource={profiles} t={t}>
          <Choice label={t('profile')} value={selectedId} options={allProfiles.map(row => ({ id: row.id, name: `${row.spec.name} · ${row.id}` }))}
            empty={t('chooseProfile')} onChange={value => { setSelectedId(value); resetPreview(); }} />
          {profiles.data?.total === 0 && !loadedProfiles.length && <p>{t('noProfiles')}</p>}
          {allProfiles.length < (profiles.data?.total || 0) && <button type="button" className="btn btn-secondary" disabled={busy} onClick={moreProfiles}>{t('moreProfiles')}</button>}
          {selected && <details className="tax-profile-proof"><summary>{t('mappingProof')}</summary><p>{selected.spec.reviewed_by} · {selected.created_at}</p>
            {selected.spec.rules.map((rule, index) => <p key={index}>{choices.accounts.find(row => row.id === rule.account_id)?.name || rule.account_id} / {choices.categories.find(row => row.id === rule.category_id)?.name || t('uncategorized')}
              {' · '}{t(rule.treatment)}{' · '}{rule.form_line || t(`exclusions.${rule.exclusion_kind}`)}{' · '}{rule.reason}</p>)}
            {canWrite && <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => beginProfile(selected)}>{t('reviseProfile')}</button>}</details>}
          {draft && canWrite && <form onSubmit={saveProfile}><fieldset disabled={busy} className="tax-draft"><legend>{t('profileDraft')}</legend>
            <div className="tax-fields"><label>{t('name')}<input autoFocus required maxLength={200} value={draft.name} onChange={event => setDraft(current => ({ ...current, name: event.target.value }))} /></label>
              <label>{t('reviewedBy')}<input required maxLength={200} value={draft.reviewed_by} onChange={event => setDraft(current => ({ ...current, reviewed_by: event.target.value }))} /></label></div>
            {draft.rules.map((rule, index) => <fieldset key={rule.key} className="tax-rule"><legend>{t('rule')} {index + 1}</legend><div className="tax-fields">
              <Choice label={t('account')} value={rule.account_id} options={choices.accounts} required empty={t('choose')} onChange={value => ruleUpdate(rule.key, 'account_id', value)} />
              <Choice label={t('category')} value={rule.category_id} options={choices.categories} empty={t('uncategorized')} onChange={value => ruleUpdate(rule.key, 'category_id', value)} />
              <ClassificationFields row={rule} t={t} update={(field, value) => ruleUpdate(rule.key, field, value)} /></div>
              <button type="button" className="btn btn-secondary" onClick={() => setDraft(current => ({ ...current, rules: current.rules.filter(row => row.key !== rule.key) }))}>{t('removeRule')}</button></fieldset>)}
            <button type="button" className="btn btn-secondary" onClick={() => setDraft(current => ({ ...current, rules: [...current.rules, newRule()] }))}>{t('addRule')}</button>
            <label className="tax-check"><input type="checkbox" checked={draft.review_confirmed} onChange={event => setDraft(current => ({ ...current, review_confirmed: event.target.checked }))} />{t('reviewConfirmed')}</label>
            <div className="tax-actions"><button type="submit" className="btn btn-primary">{t('saveProfile')}</button><button type="button" className="btn btn-secondary" onClick={() => setDraft(null)}>{t('cancel')}</button></div>
          </fieldset></form>}
        </ResourceState></ResourceState>
      </section>
      {canWrite && selected && <section className="tax-panel"><p className="tax-eyebrow">02</p><h2>{t('reviewCash')}</h2><p>{t('cashInstructions')}</p>
        <form onSubmit={preflight}><fieldset disabled={busy} className="tax-review"><div className="tax-fields">
          <label>{t('asOf')}<input required type="date" value={asOf} min={`${String(year).padStart(4, '0')}-01-01`} max={today()} onChange={event => { setAsOf(event.target.value); resetPreview(); }} /></label>
          <label>{t('pendingReason')}<input maxLength={1000} value={pendingReason} onChange={event => { setPendingReason(event.target.value); resetPreview(); }} /></label>
          <label className="tax-wide">{t('emptyReason')}<input maxLength={1000} value={emptyReason} onChange={event => { setEmptyReason(event.target.value); resetPreview(); }} /></label></div>
          <details className="tax-adjustments" open={overrides.length > 0 || undefined}><summary>{t('adjustments')}</summary><p>{t('allocationHelp')}</p>
            {overrides.map((row, index) => <fieldset className="tax-rule" key={row.key}><legend>{t('adjustment')} {index + 1}</legend>
              <div className="tax-fields"><label>{t('bookingId')}<input id={`tax-override-${row.key}`} value={row.booking_id} required onChange={event => patchOverride(row.key, 'booking_id', event.target.value)} /></label>
                <label>{t('overrideReason')}<input value={row.reason} required maxLength={1000} onChange={event => patchOverride(row.key, 'reason', event.target.value)} /></label>
                <label>{t('correctionId')}<input value={row.correction_of_booking_id} onChange={event => patchOverride(row.key, 'correction_of_booking_id', event.target.value)} /></label>
                <label>{t('transferId')}<input value={row.transfer_counter_booking_id} onChange={event => patchOverride(row.key, 'transfer_counter_booking_id', event.target.value)} /></label></div>
              {row.parts.map((part, partIndex) => <fieldset key={part.key} className="tax-part"><legend>{t('part')} {partIndex + 1}</legend><div className="tax-fields">
                <Choice label={t('property')} value={part.property_id} options={choices.properties} required={part.treatment !== 'excluded'} empty={t('choose')} onChange={value => patchPart(row.key, part.key, 'property_id', value)} />
                <label>{t('signedAmount')}<input inputMode="decimal" value={part.amount} required onChange={event => patchPart(row.key, part.key, 'amount', event.target.value)} /></label>
                <ClassificationFields row={part} t={t} update={(field, value) => patchPart(row.key, part.key, field, value)} /></div>
                <button type="button" className="btn btn-secondary" onClick={() => patchOverride(row.key, 'parts', row.parts.filter(item => item.key !== part.key))}>{t('removePart')}</button></fieldset>)}
              <div className="tax-actions"><button type="button" className="btn btn-secondary" onClick={() => patchOverride(row.key, 'parts', [...row.parts, newPart()])}>{t('addPart')}</button>
                <button type="button" className="btn btn-secondary" onClick={() => { setOverrides(current => current.filter(item => item.key !== row.key)); resetPreview(); }}>{t('removeAdjustment')}</button></div></fieldset>)}
            <button type="button" className="btn btn-secondary" onClick={() => addOverride(null)}>{t('addAdjustment')}</button></details>
          <button type="submit" className="btn btn-primary">{t('preflight')}</button>
        </fieldset></form>
      </section>}
      {preview && <section className="tax-panel" aria-label={t('result')}><h2 ref={heading} tabIndex={-1}>{preview.id ? t('savedResult') : t('result')}</h2>
        <p className={preview.ready ? 'tax-notice' : 'tax-warning'}>{preview.ready ? t('ready') : t('blocked')}</p>
        <p>{preview.period_start} – {preview.period_end} · {preview.full_year ? t('fullYear') : t('partialYear')} · {preview.confirmed_cash_rows} {t('cashRows')}</p>
        <dl className="tax-totals">{['income_cents', 'expense_cents', 'cash_cents', 'excluded_cash_cents', 'unclassified_cash_cents'].map(name => <div key={name}><dt>{t(`totals.${name}`)}</dt>
          <dd>{preview.cash_totals_complete ? euro(preview.totals[name], locale) : t('incomplete')}</dd></div>)}</dl>
        {!preview.tax_totals_complete && <p className="tax-warning">{t('partialTotals')}</p>}
        {Object.keys(preview.blocking_issue_counts).length > 0 && <ul>{Object.entries(preview.blocking_issue_counts).map(([code, count]) => <li key={code}>{t(`issues.${code}`)} ({count})</li>)}</ul>}
        <div className="tax-table-wrap" role="region" aria-label={t('taxLines')} tabIndex={0}><table><caption>{t('taxLines')}</caption><thead><tr><th>{t('property')}</th><th>{t('treatment')}</th><th>{t('formLine')}</th><th>{t('total')}</th></tr></thead>
          <tbody>{preview.groups.map((row, index) => <tr key={index}><td>{row.property_name}</td><td>{t(row.treatment)}</td><td>{row.form_line}</td><td>{euro(row.amount_cents, locale)}</td></tr>)}</tbody></table></div>
        <details><summary>{t('sourceSamples')} ({preview.source_samples.length} / {preview.source_rows})</summary><p>{t('allEvidence')}</p>
          {preview.source_samples.map(source => <article key={source.booking.id} className="tax-source"><p><strong>{source.booking.booking_date} · {euro(source.booking.amount_cents, locale)}</strong></p>
            <p>{source.booking.account_name} · {source.booking.category_name || t('uncategorized')} · {source.booking.payment_text}</p>
            <p className="tax-proof-id">{source.booking.id}</p>{source.errors.map(code => <p className="tax-warning" key={code}>{t(`issues.${code}`)}</p>)}
            {canWrite && !preview.id && source.booking.status === 'confirmed' && source.booking.booking_date <= preview.period_end
              && <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => addOverride(source)}>{t('adjustSource')}</button>}</article>)}
          {preview.blocking_issues.filter(issue => issue.booking_id && !preview.source_samples.some(source => source.booking.id === issue.booking_id)).map(issue => <p key={issue.booking_id + issue.code}>{issue.booking_id} · {t(`issues.${issue.code}`)}</p>)}</details>
        {preview.revision_delta_cents && <p>{t('revisionDelta')}: {euro(preview.revision_delta_cents.income_cents, locale)} / {euro(preview.revision_delta_cents.expense_cents, locale)}</p>}
        {canWrite && preview.ready && !preview.id && <div className="tax-confirm"><Choice label={t('previousSnapshot')} value={previousId}
          options={(journal.data?.items || []).map(row => ({ id: row.id, name: `${t('revision')} ${row.revision_number} · ${row.id}` }))} empty={t('firstSnapshot')}
          onChange={value => setPreviousId(value)} />
          {previousId && <label>{t('revisionReason')}<input maxLength={1000} value={revisionReason} onChange={event => setRevisionReason(event.target.value)} /></label>}
          <button type="button" className="btn btn-primary" disabled={busy || (!!previousId && !revisionReason.trim()) || (!previousId && journal.data?.total > 0)} onClick={saveSnapshot}>{t('saveSnapshot')}</button></div>}
      </section>}
      <section className="tax-panel"><div className="tax-section-heading"><div><p className="tax-eyebrow">03</p><h2>{t('journal')}</h2></div><button type="button" className="btn btn-secondary" disabled={busy} onClick={journal.retry}>{t('refresh')}</button></div>
        <p>{t('revisionHelp')}</p><ResourceState resource={journal} t={t}>
          {journal.data?.total === 0 && <p>{t('noSnapshots')}</p>}
          {(journal.data?.items || []).map(row => <article key={row.id} className="tax-snapshot"><div><h3>{t('revision')} {row.revision_number} · {row.tax_year}</h3>
            <p>{row.generated_at} · {row.revision_reason || t('initialSnapshot')}</p><p>{t('income')}: {euro(row.totals.income_cents, locale)} · {t('expense')}: {euro(row.totals.expense_cents, locale)}</p>
            <p className="tax-proof-id">{row.id}</p></div><div className="tax-actions"><button type="button" className="btn btn-secondary" disabled={busy} onClick={() => setPreview(row)}>{t('showSnapshot')}</button>
              <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => download(row)}>{t('download')}</button>
              {canWrite && <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => reviseSnapshot(row)}>{t('reviseSnapshot')}</button>}</div></article>)}
          <div className="tax-pagination"><button type="button" className="btn btn-secondary" disabled={busy || page === 0} onClick={() => setPage(current => current - 1)}>{t('previous')}</button>
            <span>{page + 1} / {Math.max(1, Math.ceil((journal.data?.total || 0) / 10))}</span><button type="button" className="btn btn-secondary" disabled={busy || (page + 1) * 10 >= (journal.data?.total || 0)} onClick={() => setPage(current => current + 1)}>{t('next')}</button></div>
        </ResourceState></section>
    </>}
  </div>;
}
