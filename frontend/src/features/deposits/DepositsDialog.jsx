import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { AlertTriangle, PiggyBank, X } from 'lucide-react';
import { useAuth } from '../../contexts/AuthContext';
import { useTranslation } from '../../i18n';
import { formatMoney } from '../../utils/format';
import { mayWrite } from '../../utils/permissions';
import { useModalDialog } from '../partyWorkspace/useModalDialog';
import AgreementForm from './AgreementForm';
import { depositService } from './depositApi';
import DepositFile from './DepositFile';
import { depositText } from './depositText';
import './deposits.css';

/** The deposits of one contract (from the contract row or the party file): open one, or agree a new one. */
export default function DepositsDialog({ contractId, onClose, onChanged, service = depositService }) {
  const auth = useAuth();
  const canEdit = mayWrite(auth?.write ?? null, '/deposits');
  const { locale } = useTranslation();
  const say = useCallback((key, params) => depositText(locale, key, params), [locale]);
  const titleId = useId();
  const dialogRef = useRef(null);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(null);
  const [attempt, setAttempt] = useState(0);
  useModalDialog(dialogRef, onClose, true);

  useEffect(() => {
    const controller = new AbortController();
    service.source(contractId, { signal: controller.signal })
      .then(value => { if (!controller.signal.aborted) { setData(value); setError(null); } })
      .catch(failure => { if (!controller.signal.aborted && failure?.name !== 'AbortError') setError(failure?.message || say('loadFailed')); });
    return () => controller.abort();
  }, [attempt, contractId, say, service]);

  const create = async payload => {
    setBusy(true);
    setError(null);
    try {
      const file = await service.create(payload);
      setCreating(false);
      setAttempt(value => value + 1);
      onChanged?.();
      setOpen(file.deposit.id);
    } catch (failure) {
      setError(failure?.message || say('loadFailed'));
    } finally {
      setBusy(false);
    }
  };

  const changed = useCallback(() => { setAttempt(value => value + 1); onChanged?.(); }, [onChanged]);
  const contract = data?.source.contract;

  return createPortal(<>
    <div className="deposit__overlay" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="deposit deposit--list" ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={titleId}
        tabIndex={-1} aria-hidden={open ? true : undefined} inert={open ? true : undefined}>
        <header className="deposit__header">
          <div>
            <p className="deposit__eyebrow">{say('eyebrow')}</p>
            <h2 id={titleId}>{say('listTitle')}</h2>
            {data && <p>{contract.contract_number} · {data.source.tenant.full_name} · {data.source.unit.label}</p>}
          </div>
          <button type="button" className="deposit__icon-button" aria-label={say('close')} onClick={onClose}><X size={20} aria-hidden="true" /></button>
        </header>
        <div className="deposit__body">
          {error && <div className="deposit__notice deposit__notice--error" role="alert"><AlertTriangle size={18} aria-hidden="true" />
            <span>{error}</span><button type="button" className="btn btn-secondary btn-sm" onClick={() => setAttempt(v => v + 1)}>{say('retry')}</button></div>}
          {!data && !error && <p role="status">{say('loading')}</p>}
          {data && <>
            {data.deposits.length === 0 ? <p className="deposit__muted">{say('none')}</p>
              : <ul className="deposit__list">{data.deposits.map(item => <li key={item.id}>
                <PiggyBank size={18} aria-hidden="true" />
                <div><strong>{formatMoney(item.amount)} · {say(`form_${item.form}`)}</strong>
                  <small>{say(`stage_${item.stage}`)} · {say('received')} {formatMoney(item.received)}</small></div>
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => setOpen(item.id)}
                  aria-label={`${say('open')}: ${formatMoney(item.amount)}`}>{say('open')}</button>
              </li>)}</ul>}
            {canEdit && !creating && <div className="deposit__actions"><button type="button" className="btn btn-primary"
              onClick={() => setCreating(true)}>{say('newAgreement')}</button></div>}
            {creating && <AgreementForm say={say} contractId={contractId} cap={data.cap} accounts={data.accounts}
              suggested={data.suggested_amount} busy={busy} onSubmit={payload => void create(payload)} onCancel={() => setCreating(false)} />}
          </>}
        </div>
        <footer className="deposit__footer"><button type="button" className="btn btn-secondary" onClick={onClose}>{say('close')}</button></footer>
      </section>
    </div>
    {open && <DepositFile key={open} depositId={open} service={service} onClose={() => setOpen(null)} onChanged={changed} />}
  </>, document.body);
}
