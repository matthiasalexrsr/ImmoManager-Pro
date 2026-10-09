import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { AlertTriangle, ClipboardCheck, FileCheck, X } from 'lucide-react';
import { useAuth } from '../../contexts/AuthContext';
import { useTranslation } from '../../i18n';
import { mayWrite } from '../../utils/permissions';
import HousingConfirmationDialog from '../housingConfirmation/HousingConfirmationDialog';
import { useModalDialog } from '../partyWorkspace/useModalDialog';
import { handoverProtocolService } from './handoverProtocolApi';
import HandoverProtocolEditor, { formatDay } from './HandoverProtocolEditor';
import { protocolState } from './handoverProtocolModel';
import { handoverText } from './handoverProtocolText';
import './HandoverProtocol.css';

/**
 * The handover protocols of one contract, and the tenant change around it: the previous
 * tenant's move-out, the next tenant's move-in and the Wohnungsgeberbestätigung.
 */
export default function HandoverProtocolsDialog({ contractId, onClose, onChanged, service = handoverProtocolService }) {
  const auth = useAuth();
  const write = auth?.write ?? null;
  const { locale } = useTranslation();
  const say = useCallback((key, params) => handoverText(locale, key, params), [locale]);
  const titleId = useId();
  const dialogRef = useRef(null);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [editor, setEditor] = useState(null);
  const [housing, setHousing] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const canEdit = mayWrite(write, '/handover-protocols');
  const covered = Boolean(editor || housing);

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    service.source(contractId, 'move_out', { signal: controller.signal })
      .then(value => { if (!controller.signal.aborted) setData(value); })
      .catch(failure => {
        if (!controller.signal.aborted && failure?.name !== 'AbortError') setError(failure?.message || say('loadFailed'));
      });
    return () => controller.abort();
  }, [attempt, contractId, say, service]);

  const open = async (targetContractId, protocolType) => {
    setBusy(true);
    setError(null);
    try {
      const detail = await service.create(targetContractId, protocolType);
      setEditor(detail.protocol.id);
      setAttempt(value => value + 1);
      onChanged?.();
    } catch (failure) {
      setError(failure?.message || say('loadFailed'));
    } finally {
      setBusy(false);
    }
  };

  const closeEditor = useCallback(() => setEditor(null), []);
  const editorChanged = useCallback(() => { setAttempt(value => value + 1); onChanged?.(); }, [onChanged]);
  useModalDialog(dialogRef, onClose, true);

  const contract = data?.source.contract;
  const related = data?.related;
  const protocols = data?.protocols || [];
  const superseded = new Set(protocols.filter(p => p.finalized_at && p.correction_of_id).map(p => p.correction_of_id));

  return createPortal(<>
    <div className="handover__overlay" role="presentation"
      onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="handover handover--list" ref={dialogRef} role="dialog" aria-modal="true"
        aria-labelledby={titleId} tabIndex={-1} aria-hidden={covered ? true : undefined} inert={covered ? true : undefined}>
        <header className="handover__header">
          <div>
            <p className="handover__eyebrow">{say('eyebrow')}</p>
            <h2 id={titleId}>{say('listTitle')}</h2>
            {data && <p>{contract.contract_number} · {data.source.property.name} · {data.source.unit.label}</p>}
          </div>
          <button type="button" className="handover__icon-button" aria-label={say('close')} onClick={onClose}>
            <X size={20} aria-hidden="true" /></button>
        </header>
        <div className="handover__body">
          {error && <div className="handover__notice handover__notice--error" role="alert">
            <AlertTriangle size={18} aria-hidden="true" /><span>{error}</span>
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => setAttempt(v => v + 1)}>{say('retry')}</button>
          </div>}
          {!data && !error && <p role="status">{say('loading')}</p>}
          {data && <>
            {canEdit && <div className="handover__actions">
              <button type="button" className="btn btn-primary" disabled={busy}
                onClick={() => void open(contractId, 'move_in')}>{say('newMoveIn')}</button>
              <button type="button" className="btn btn-primary" disabled={busy}
                onClick={() => void open(contractId, 'move_out')}>{say('newMoveOut')}</button>
            </div>}
            <section className="handover__section" aria-label={say('listTitle')}>
              {protocols.length === 0 ? <p className="handover__muted">{say('noProtocols')}</p>
                : <ul className="handover__list">
                  {protocols.map(protocol => {
                    const state = superseded.has(protocol.id) ? 'superseded' : protocolState(protocol);
                    return <li key={protocol.id}>
                      <ClipboardCheck size={18} aria-hidden="true" />
                      <div><strong>{say(`type_${protocol.protocol_type}`)} · {formatDay(protocol.protocol_date, locale)}</strong>
                        <small>{say(`state_${state}`)}</small></div>
                      <button type="button" className="btn btn-secondary btn-sm"
                        aria-label={`${say('open')}: ${say(`type_${protocol.protocol_type}`)} ${formatDay(protocol.protocol_date, locale)}`}
                        onClick={() => setEditor(protocol.id)}>{say('open')}</button>
                    </li>;
                  })}
                </ul>}
            </section>
            <section className="handover__section" aria-label={say('tenantChange')}>
              <h3>{say('tenantChange')}</h3>
              {related.previous_contract && <div className="handover__related">
                <span>{say('previousContract', { number: related.previous_contract.contract_number,
                  date: formatDay(related.previous_contract.end_date, locale) })}</span>
                {canEdit && <button type="button" className="btn btn-secondary btn-sm" disabled={busy}
                  onClick={() => void open(related.previous_contract.id, 'move_out')}>{say('previousMoveOut')}</button>}
              </div>}
              {related.next_contract && <div className="handover__related">
                <span>{say('nextContract', { number: related.next_contract.contract_number,
                  date: formatDay(related.next_contract.start_date, locale) })}</span>
                {canEdit && <button type="button" className="btn btn-secondary btn-sm" disabled={busy}
                  onClick={() => void open(related.next_contract.id, 'move_in')}>{say('nextMoveIn')}</button>}
              </div>}
              <div className="handover__related">
                <span>{say('housingConfirmation')}</span>
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => setHousing(contractId)}>
                  <FileCheck size={15} aria-hidden="true" />{say('housingConfirmation')}</button>
              </div>
              {related.templates.length === 0 && <p className="handover__muted">{say('noTemplates')}</p>}
            </section>
          </>}
        </div>
        <footer className="handover__footer">
          <button type="button" className="btn btn-secondary" onClick={onClose}>{say('close')}</button>
        </footer>
      </section>
    </div>
    {editor && <HandoverProtocolEditor key={editor} protocolId={editor} service={service} onClose={closeEditor}
      onChanged={editorChanged} />}
    {housing && <HousingConfirmationDialog contractId={housing} onClose={() => setHousing(null)} onPublished={onChanged} />}
  </>, document.body);
}
