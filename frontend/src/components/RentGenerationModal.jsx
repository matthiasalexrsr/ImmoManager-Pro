import { useMemo, useState } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import FormModal from './FormModal';
import DataTable from './DataTable';

export default function RentGenerationModal({ contracts, onGenerated, onClose }) {
  const { t, locale } = useTranslation();
  const [preview, setPreview] = useState(null);
  const [parameters, setParameters] = useState(() => ({
    start_month: new Date().toLocaleDateString('sv-SE').slice(0, 7),
    end_month: new Date().toLocaleDateString('sv-SE').slice(0, 7), contract_ids: [],
  }));
  const text = key => t(`pages.rentGeneration.${key}`);
  const money = value => new Intl.NumberFormat(locale, { style: 'currency', currency: 'EUR' }).format(Number(value));
  const fields = useMemo(() => [
    { key: 'start_month', label: t('pages.rentGeneration.startMonth'), type: 'month', required: true },
    { key: 'end_month', label: t('pages.rentGeneration.endMonth'), type: 'month', required: true },
    { key: 'contract_ids', label: t('pages.rentGeneration.contracts'), type: 'multiselect', default: [],
      options: contracts.filter(contract => contract.status === 'active').map(contract => ({ value: contract.id, label: contract.contract_number })) },
  ], [contracts, t]);

  const inspect = async values => {
    if (values.start_month > values.end_month) throw new Error(text('invalidRange'));
    const request = { start_month: values.start_month, end_month: values.end_month,
      ...(values.contract_ids.length ? { contract_ids: values.contract_ids } : {}) };
    const result = await api.post('/rent-charges/preview', request);
    if (!result || result.policy !== 'full_month' || !Array.isArray(result.candidates)
      || !Array.isArray(result.existing) || !Array.isArray(result.skipped_contracts)
      || typeof result.preview_hash !== 'string'
      || !Number.isFinite(Number(result.total_amount))) throw new Error(text('invalidPreview'));
    setParameters(values);
    setPreview(result);
  };
  const generate = async () => {
    const result = await api.post('/rent-charges/generate', {
      start_month: parameters.start_month, end_month: parameters.end_month,
      ...(parameters.contract_ids.length ? { contract_ids: parameters.contract_ids } : {}),
      preview_hash: preview.preview_hash,
    });
    if (!Number.isInteger(result?.created_count) || !Number.isInteger(result?.skipped_count)) {
      throw new Error(text('invalidPreview'));
    }
    onGenerated(result);
  };

  return <FormModal title={text('title')} fields={preview ? [] : fields} initial={parameters}
    onSave={preview ? generate : inspect} onClose={onClose} closeOnSave={!!preview}
    saveLabel={text(preview ? 'generate' : 'preview')} saveDisabled={!!preview && !preview.candidates.length}>
    <p>{text(preview ? 'policy' : 'selectionHelp')}</p>
    {preview && <>
      <p>{text('newItems')}: <strong>{preview.candidates.length}</strong> · {text('total')}: <strong>{money(preview.total_amount)}</strong></p>
      <p>{text('existing')}: {preview.existing.length} · {text('skipped')}: {preview.skipped_contracts.length}</p>
      <DataTable title={text('preview')} data={preview.candidates} columns={[
        { key: 'contract_number', label: text('contract') },
        { key: 'month', label: text('month') },
        { key: 'due_date', label: text('dueDate'), type: 'date' },
        { key: 'total_amount', label: text('amount'), render: money },
        { key: 'partial_month', label: text('partialMonth'), render: value => value ? text('yes') : '—' },
      ]} />
      <button className="btn btn-secondary" type="button" onClick={() => setPreview(null)}>{text('changeSelection')}</button>
    </>}
  </FormModal>;
}
