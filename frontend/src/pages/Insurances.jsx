import { useEntities } from '../contexts/DataStoreContext';
import CrudPage from './CrudPage';
import { useTranslation } from '../i18n';

export default function Insurances() {
  const { t } = useTranslation();

  const COLUMNS = [
    { key: 'provider', label: t('pages.insurances.columns.provider') || 'Versicherer', filterType: 'text' },
    { key: 'insurance_type', label: t('pages.insurances.columns.type') || 'Art', filterType: 'select' },
    { key: 'policy_number', label: t('pages.insurances.columns.policyNumber') || 'Policennr.', filterType: 'text' },
    { key: 'premium_amount', label: t('pages.insurances.columns.premium') || 'Prämie (€)', type: 'number', align: 'right',
      render: v => v != null ? `${Number(v).toFixed(2)} €` : '—' },
    { key: 'premium_interval', label: t('pages.insurances.columns.interval') || 'Intervall' },
    { key: 'end_date', label: t('pages.insurances.columns.endDate') || 'Ablauf', type: 'date', filterType: 'dateRange' },
    { key: 'status', label: t('pages.insurances.columns.status') || 'Status', type: 'status', filterType: 'select' },
  ];

  const { items: properties } = useEntities('properties', '/properties');
  const { items: units } = useEntities('units', '/units');

  const fields = [
    { key: 'property_id', label: t('pages.insurances.form.property') || 'Immobilie', required: true, type: 'select',
      options: properties.map(p => ({ value: p.id, label: p.name })) },
    { key: 'unit_id', label: t('pages.insurances.form.unit') || 'Einheit (optional)', type: 'select',
      options: units.map(u => ({ value: u.id, label: u.label })) },
    { key: 'insurance_type', label: t('pages.insurances.form.type') || 'Versicherungsart', required: true, type: 'select', options: [
      { value: 'building', label: t('pages.insurances.types.building') || 'Gebäudeversicherung' },
      { value: 'liability', label: t('pages.insurances.types.liability') || 'Haftpflicht' },
      { value: 'contents', label: t('pages.insurances.types.contents') || 'Hausrat' },
      { value: 'legal', label: t('pages.insurances.types.legal') || 'Rechtsschutz' },
      { value: 'rent_loss', label: t('pages.insurances.types.rentLoss') || 'Mietausfall' },
      { value: 'other', label: t('pages.insurances.types.other') || 'Sonstige' },
    ]},
    { key: 'provider', label: t('pages.insurances.form.provider') || 'Versicherer', required: true, placeholder: t('pages.insurances.form.providerPlaceholder') || 'z.B. Allianz' },
    { key: 'policy_number', label: t('pages.insurances.form.policyNumber') || 'Policennummer', placeholder: 'z.B. VP-2024-12345' },
    { key: 'coverage_amount', label: t('pages.insurances.form.coverageAmount') || 'Deckungssumme (€)', type: 'number' },
    { key: 'premium_amount', label: t('pages.insurances.form.premiumAmount') || 'Prämie (€)', type: 'number' },
    { key: 'premium_interval', label: t('pages.insurances.form.paymentInterval') || 'Zahlungsintervall', type: 'select', default: 'annual', options: [
      { value: 'monthly', label: t('pages.insurances.interval.monthly') || 'Monatlich' },
      { value: 'quarterly', label: t('pages.insurances.interval.quarterly') || 'Vierteljährlich' },
      { value: 'annual', label: t('pages.insurances.interval.annual') || 'Jährlich' },
    ]},
    { key: 'start_date', label: t('pages.insurances.form.startDate') || 'Vertragsbeginn', type: 'date' },
    { key: 'end_date', label: t('pages.insurances.form.endDate') || 'Vertragsende', type: 'date' },
    { key: 'contact_person', label: t('pages.insurances.form.contactPerson') || 'Ansprechpartner' },
    { key: 'contact_phone', label: t('pages.insurances.form.contactPhone') || 'Telefon' },
    { key: 'notes', label: t('pages.insurances.form.notes') || 'Notizen', type: 'textarea' },
    { key: 'status', label: t('pages.insurances.form.status') || 'Status', type: 'select', default: 'active', options: [
      { value: 'active', label: t('pages.insurances.status.active') || 'Aktiv' },
      { value: 'expired', label: t('pages.insurances.status.expired') || 'Abgelaufen' },
      { value: 'cancelled', label: t('pages.insurances.status.cancelled') || 'Gekündigt' },
    ]},
  ];

  return <CrudPage title={t('pages.insurances.title') || 'Versicherungen'} endpoint="/insurances" columns={COLUMNS} formFields={fields} />;
}
