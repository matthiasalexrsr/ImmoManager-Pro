import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from '../i18n';
import { useEntities, useDataStore } from '../contexts/DataStoreContext';
import DataTable from '../components/DataTable';
import FormModal from '../components/FormModal';
import { useConfirm } from '../components/ConfirmDialog';
import { useToast } from '../components/Toast';
import HandoverProtocolEditor from '../features/handoverProtocol/HandoverProtocolEditor';
import { handoverProtocolService } from '../features/handoverProtocol/handoverProtocolApi';
import { protocolState } from '../features/handoverProtocol/handoverProtocolModel';
import { handoverText } from '../features/handoverProtocol/handoverProtocolText';

/** Every handover protocol; opening one leads to the editor, a new one starts prefilled from its contract. */
export default function HandoverProtocols({ service = handoverProtocolService }) {
  const { t, locale } = useTranslation();
  const say = useCallback((key, params) => handoverText(locale, key, params), [locale]);
  const confirm = useConfirm();
  const toast = useToast();
  const store = useDataStore();
  const { items: units } = useEntities('units', '/units');
  const { items: contracts } = useEntities('contracts', '/contracts');
  const [protocols, setProtocols] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [creating, setCreating] = useState(false);
  const [editor, setEditor] = useState(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    service.list({ signal: controller.signal })
      .then(rows => { if (!controller.signal.aborted) setProtocols(Array.isArray(rows) ? rows : []); })
      .catch(failure => { if (!controller.signal.aborted) setError(failure?.message || say('loadFailed')); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [attempt, say, service]);

  const refresh = useCallback(() => {
    setAttempt(value => value + 1);
    store?.invalidateRelated('handover_protocols', 'documents', 'contracts', 'units');
  }, [store]);

  const rows = useMemo(() => {
    const unitLabel = Object.fromEntries(units.map(unit => [unit.id, unit.label]));
    const contractNumber = Object.fromEntries(contracts.map(contract => [contract.id, contract.contract_number]));
    const superseded = new Set(protocols.filter(p => p.finalized_at && p.correction_of_id).map(p => p.correction_of_id));
    return protocols.map(protocol => ({
      ...protocol,
      unit_label: unitLabel[protocol.unit_id] || '—',
      contract_label: contractNumber[protocol.contract_id] || '—',
      type_label: say(`type_${protocol.protocol_type}`),
      state_label: say(`state_${superseded.has(protocol.id) ? 'superseded' : protocolState(protocol)}`),
    }));
  }, [contracts, protocols, say, units]);

  const columns = [
    { key: 'protocol_date', label: say('date'), type: 'date' },
    { key: 'type_label', label: say('kind') },
    { key: 'unit_label', label: say('unit') },
    { key: 'contract_label', label: say('contract') },
    { key: 'state_label', label: say('status') },
  ];

  const fields = [
    { key: 'contract_id', label: say('contract'), type: 'select', required: true,
      options: contracts.map(contract => ({ value: contract.id, label: contract.contract_number || contract.id })) },
    { key: 'protocol_type', label: say('kind'), type: 'select', required: true, default: 'move_out', options: [
      { value: 'move_in', label: say('type_move_in') }, { value: 'move_out', label: say('type_move_out') }] },
    { key: 'protocol_date', label: say('protocolDate'), type: 'date' },
  ];

  const create = async data => {
    const detail = await service.create(data.contract_id, data.protocol_type || 'move_out', data.protocol_date || null);
    refresh();
    setEditor(detail.protocol.id);
  };

  const remove = async row => {
    if (row.finalized_at) {
      toast.error(say('state_finalized'));
      return;
    }
    if (!await confirm(say('deleteConfirm'))) return;
    try {
      await service.remove(row.id);
      refresh();
    } catch (failure) {
      toast.error(failure?.message || t('modals.confirmDelete.body'));
    }
  };

  if (loading) return <div className="page-loading">{t('ui.table.loading')}</div>;

  return (
    <div className="page">
      {error && <div className="alert alert-error" role="alert">{error}{' '}
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => setAttempt(value => value + 1)}>{say('retry')}</button></div>}
      <DataTable
        title={say('pageTitle')}
        columns={columns}
        data={rows}
        writeArea="/handover-protocols"
        onAdd={() => setCreating(true)}
        onRowClick={row => setEditor(row.id)}
        rowActions={() => [{ label: say('open'), onClick: row => setEditor(row.id) }]}
        onDelete={remove}
      />
      {creating && <FormModal title={say('newProtocol')} fields={fields} initial={null} onSave={create}
        onClose={() => setCreating(false)} />}
      {editor && <HandoverProtocolEditor key={editor} protocolId={editor} service={service}
        onClose={() => setEditor(null)} onChanged={refresh} />}
    </div>
  );
}
