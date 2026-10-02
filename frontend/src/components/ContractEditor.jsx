import { useCallback, useState } from 'react';
import { useTranslation } from '../i18n';
import useContractChoices from '../hooks/useContractChoices';
import FormModal from './FormModal';

export default function ContractEditor({ initial, onSave, onClose }) {
  const { t } = useTranslation();
  const [references, setReferences] = useState(initial || {});
  const onValuesChange = useCallback(values => setReferences(current =>
    ['property_id', 'unit_id', 'tenant_id'].every(key => current[key] === values[key]) ? current
      : Object.fromEntries(['property_id', 'unit_id', 'tenant_id'].map(key => [key, values[key]]))), []);
  const label = key => t(`tenantsContracts.contracts.${key}`);
  const properties = useContractChoices('properties', references.property_id, label('property'));
  const units = useContractChoices('units', references.unit_id, label('unit'), references.property_id);
  const tenants = useContractChoices('tenants', references.tenant_id, label('tenant'));
  const fields = [
    { key: 'contract_number', label: label('number'), required: true },
    { key: 'property_id', label: label('property'), required: true, type: 'select', ...properties,
      onChange: () => ({ unit_id: '' }) },
    { key: 'unit_id', label: label('unit'), required: true, type: 'select', ...units },
    { key: 'tenant_id', label: label('tenant'), required: true, type: 'select', ...tenants },
    { key: 'start_date', label: label('start'), required: true, type: 'date' },
    { key: 'end_date', label: label('endOptional'), type: 'date' },
    { key: 'deposit_amount', label: label('deposit'), type: 'number' },
    { key: 'index_rent', label: label('indexRent'), type: 'select', options: ['index', 'stepped', 'fixed'].map(value =>
      ({ value, label: t(`contractWorkspace.rent_${value}`) })) },
    { key: 'service_charge_settlement', label: label('serviceChargeSettlement'), type: 'select', options: ['annual', 'monthly'].map(value =>
      ({ value, label: t(`contractWorkspace.settlement_${value}`) })) },
    { key: 'notice_period', label: label('noticePeriod') },
    { key: 'status', label: label('status'), default: 'active', type: 'select', options: ['active', 'terminated', 'expired', 'draft'].map(value =>
      ({ value, label: t(`contractWorkspace.status_${value}`) })) },
  ];
  return <div className="contract-workspace-editor" onKeyDownCapture={event => {
    if (event.key === 'Enter' && event.target.name?.startsWith('lookup_contract_')) event.preventDefault();
  }}><FormModal title={t(initial ? 'contractWorkspace.edit' : 'contractWorkspace.create')}
    fields={fields} initial={initial} onValuesChange={onValuesChange} onSave={onSave} onClose={onClose}
    saveDisabled={properties.disabled || units.disabled || tenants.disabled} /></div>;
}
