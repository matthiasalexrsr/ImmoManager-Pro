import { useState, useEffect } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import CrudPage from './CrudPage';

export default function Contracts() {
  const { t } = useTranslation();
  const [properties, setProperties] = useState([]);
  const [units, setUnits] = useState([]);
  const [tenants, setTenants] = useState([]);

  useEffect(() => {
    Promise.all([
      api.get('/properties').catch(err => { console.warn('[Contracts] properties:', err.message); return []; }),
      api.get('/units').catch(err => { console.warn('[Contracts] units:', err.message); return []; }),
      api.get('/tenants').catch(err => { console.warn('[Contracts] tenants:', err.message); return []; }),
    ]).then(([p, u, tn]) => { setProperties(p); setUnits(u); setTenants(tn); });
  }, []);

  const columns = [
    { key: 'contract_number', label: t('tenantsContracts.contracts.form.contractNumber') || 'Vertragsnr.', filterType: 'text' },
    { key: 'start_date', label: t('tenantsContracts.contracts.form.startDate') || 'Beginn', type: 'date', filterType: 'dateRange' },
    { key: 'end_date', label: t('tenantsContracts.contracts.form.endDate') || 'Ende', type: 'date', filterType: 'dateRange' },
    { key: 'deposit_amount', label: t('tenantsContracts.contracts.form.deposit') || 'Kaution (€)', type: 'number', align: 'right',
      render: v => v != null ? `${Number(v).toFixed(2)} €` : '—' },
    { key: 'status', label: t('ui.form.status') || 'Status', type: 'status', filterType: 'select' },
  ];

  const fields = [
    { key: 'contract_number', label: t('tenantsContracts.contracts.form.contractNumber') || 'Vertragsnr.', required: true, placeholder: 'z.B. MV-2024-001' },
    { key: 'property_id', label: t('portfolio.properties.form.name') || 'Immobilie', required: true, type: 'select',
      options: properties.map(p => ({ value: p.id, label: p.name })) },
    { key: 'unit_id', label: t('units.list.columns.label') || 'Einheit', required: true, type: 'select',
      options: units.map(u => ({ value: u.id, label: u.label })) },
    { key: 'tenant_id', label: t('tenantsContracts.tenants.title') || 'Mieter', required: true, type: 'select',
      options: tenants.map(tn => ({ value: tn.id, label: tn.full_name })) },
    { key: 'start_date', label: t('tenantsContracts.contracts.form.startDate') || 'Vertragsbeginn', type: 'date', required: true },
    { key: 'end_date', label: t('tenantsContracts.contracts.form.endDate') || 'Vertragsende', type: 'date' },
    { key: 'deposit_amount', label: t('tenantsContracts.contracts.form.deposit') || 'Kaution (€)', type: 'number' },
    { key: 'index_rent', label: t('tenantsContracts.contracts.form.indexRent') || 'Mietanpassung', type: 'select', options: [
      { value: 'index', label: t('tenantsContracts.contracts.indexRent.index') || 'Indexmiete' },
      { value: 'stepped', label: t('tenantsContracts.contracts.indexRent.stepped') || 'Staffelmiete' },
      { value: 'fixed', label: t('tenantsContracts.contracts.indexRent.fixed') || 'Festmiete' },
    ]},
    { key: 'service_charge_settlement', label: t('tenantsContracts.contracts.form.serviceChargeSettlement') || 'NK-Abrechnung', type: 'select', options: [
      { value: 'annual', label: t('tenantsContracts.contracts.settlement.annual') || 'Jährlich' },
      { value: 'monthly', label: t('tenantsContracts.contracts.settlement.monthly') || 'Monatlich' },
    ]},
    { key: 'notice_period', label: t('tenantsContracts.contracts.form.noticePeriod') || 'Kündigungsfrist', placeholder: 'z.B. 3 Monate' },
    { key: 'status', label: t('ui.form.status') || 'Status', type: 'select', default: 'active', options: [
      { value: 'active', label: t('tenantsContracts.contracts.status.active') || 'Aktiv' },
      { value: 'terminated', label: t('tenantsContracts.contracts.status.terminated') || 'Gekündigt' },
      { value: 'expired', label: t('tenantsContracts.contracts.status.expired') || 'Ausgelaufen' },
      { value: 'draft', label: t('ui.filterChips.draft') || 'Entwurf' },
    ]},
  ];

  return <CrudPage title={t('tenantsContracts.contracts.title') || 'Verträge'} endpoint="/contracts" columns={columns} formFields={fields} />;
}
