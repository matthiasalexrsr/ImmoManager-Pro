import { useId, useMemo, useState } from 'react';
import { formatMoney } from '../../utils/format';

const MONEY_FORMS = ['cash', 'transfer', 'deposit_account'];
const FORMS = [...MONEY_FORMS, 'guarantee', 'pledged_savings'];

const cents = value => Math.round(Number(value || 0) * 100);

function split(amount, count) {
  const total = cents(amount);
  if (!total || !count) return [];
  const base = Math.floor(total / count);
  return Array.from({ length: count }, (_, index) => ((base + (index === 0 ? total - base * count : 0)) / 100).toFixed(2));
}

/** The agreement of a deposit: amount (cap of three net cold rents), form, instalments, account. */
export default function AgreementForm({ say, contractId, initial = null, cap = null, accounts = [], suggested = null,
  busy = false, onSubmit, onCancel }) {
  const id = useId();
  const [values, setValues] = useState(() => ({
    amount: initial ? String(initial.amount) : (suggested ? String(suggested) : ''),
    form: initial?.form || 'transfer',
    count: initial?.instalments?.length || 1,
    custom: initial?.instalments?.length ? initial.instalments.map(i => Number(i.amount).toFixed(2)) : null,
    cap_reason: initial?.cap_reason || '',
    account_id: initial?.account_id || '',
    institution: initial?.institution || '',
    account_reference: initial?.account_reference || '',
    account_holder: initial?.account_holder || '',
    notes: initial?.notes || '',
  }));
  const set = (name, value) => setValues(current => ({ ...current, [name]: value }));
  const moneyForm = MONEY_FORMS.includes(values.form);
  const amounts = values.custom && values.custom.length === values.count ? values.custom : split(values.amount, values.count);
  const exceeds = cap?.known && cents(values.amount) > cents(cap.cap);
  const sumMatches = !moneyForm || amounts.reduce((sum, value) => sum + cents(value), 0) === cents(values.amount);
  const valid = cents(values.amount) > 0 && (!exceeds || values.cap_reason.trim()) && sumMatches;

  const payload = useMemo(() => ({
    contract_id: contractId,
    amount: Number(values.amount),
    form: values.form,
    instalment_count: moneyForm ? values.count : 1,
    instalment_amounts: moneyForm ? amounts.map(Number) : null,
    cap_reason: values.cap_reason.trim() || null,
    account_id: moneyForm ? (values.account_id || null) : null,
    institution: values.institution.trim() || null,
    account_reference: values.account_reference.trim() || null,
    account_holder: values.account_holder.trim() || null,
    notes: values.notes.trim() || null,
  }), [amounts, contractId, moneyForm, values]);

  const submit = event => {
    event.preventDefault();
    if (valid && !busy) onSubmit(payload);
  };

  return <form className="deposit__form" onSubmit={submit} aria-label={initial ? say('editAgreement') : say('newAgreement')}>
    <div className="deposit__grid">
      <label htmlFor={`${id}-amount`}>{say('amount')}
        <input id={`${id}-amount`} type="number" inputMode="decimal" min="0.01" step="0.01" required value={values.amount}
          onChange={event => setValues(current => ({ ...current, amount: event.target.value, custom: null }))} /></label>
      <label htmlFor={`${id}-form`}>{say('form')}
        <select id={`${id}-form`} value={values.form} onChange={event => set('form', event.target.value)}>
          {FORMS.map(form => <option key={form} value={form}>{say(`form_${form}`)}</option>)}
        </select></label>
      {moneyForm && <label htmlFor={`${id}-count`}>{say('instalmentCount')}
        <select id={`${id}-count`} value={values.count}
          onChange={event => setValues(current => ({ ...current, count: Number(event.target.value), custom: null }))}>
          {[1, 2, 3].map(count => <option key={count} value={count}>{count}</option>)}
        </select></label>}
      {moneyForm && <label htmlFor={`${id}-account`}>{say('heldAccount')}
        <select id={`${id}-account`} value={values.account_id} onChange={event => set('account_id', event.target.value)}>
          <option value="">{say('noAccount')}</option>
          {accounts.map(account => <option key={account.id} value={account.id}>{account.name}</option>)}
        </select></label>}
    </div>
    {cap && <p className={exceeds ? 'deposit__notice deposit__notice--warning' : 'deposit__muted'} role={exceeds ? 'alert' : undefined}>
      {!cap.known ? say('capUnknown') : exceeds
        ? say('capExceeded', { excess: formatMoney((cents(values.amount) - cents(cap.cap)) / 100) })
        : say('capInfo', { cap: formatMoney(cap.cap), cold: formatMoney(cap.cold_rent) })}</p>}
    {exceeds && <label className="deposit__wide" htmlFor={`${id}-reason`}>{say('capReason')}
      <textarea id={`${id}-reason`} required rows={2} value={values.cap_reason}
        onChange={event => set('cap_reason', event.target.value)} /></label>}
    {moneyForm && values.count > 1 && <fieldset className="deposit__fieldset">
      <legend>{say('instalmentAmounts')}</legend>
      <div className="deposit__grid">
        {amounts.map((value, index) => <label key={index} htmlFor={`${id}-i${index}`}>{`${index + 1}.`}
          <input id={`${id}-i${index}`} type="number" inputMode="decimal" step="0.01" min="0.01" value={value}
            onChange={event => {
              const next = [...amounts];
              next[index] = event.target.value;
              set('custom', next);
            }} /></label>)}
      </div>
      {!sumMatches && <p className="deposit__notice deposit__notice--warning" role="alert">
        {say('total')}: {formatMoney(amounts.reduce((sum, value) => sum + cents(value), 0) / 100)} ≠ {formatMoney(values.amount)}</p>}
    </fieldset>}
    <div className="deposit__grid">
      <label htmlFor={`${id}-institution`}>{say('institution')}
        <input id={`${id}-institution`} value={values.institution} maxLength={200}
          onChange={event => set('institution', event.target.value)} /></label>
      <label htmlFor={`${id}-reference`}>{say('accountReference')}
        <input id={`${id}-reference`} value={values.account_reference} maxLength={200}
          onChange={event => set('account_reference', event.target.value)} /></label>
      <label htmlFor={`${id}-holder`}>{say('accountHolder')}
        <input id={`${id}-holder`} value={values.account_holder} maxLength={200}
          onChange={event => set('account_holder', event.target.value)} /></label>
    </div>
    <label className="deposit__wide" htmlFor={`${id}-notes`}>{say('notes')}
      <textarea id={`${id}-notes`} rows={2} value={values.notes} onChange={event => set('notes', event.target.value)} /></label>
    <div className="deposit__actions">
      {onCancel && <button type="button" className="btn btn-secondary" onClick={onCancel}>{say('cancel')}</button>}
      <button type="submit" className="btn btn-primary" disabled={!valid || busy}>{say('save')}</button>
    </div>
  </form>;
}
