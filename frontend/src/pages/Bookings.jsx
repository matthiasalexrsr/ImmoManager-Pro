import { useTranslation } from '../i18n';
import { useEntities } from '../contexts/DataStoreContext';
import CrudPage from './CrudPage';

export default function Bookings() {
  const { t } = useTranslation();
  const { items: accounts } = useEntities('accounts', '/accounts');
  const { items: categories } = useEntities('categories', '/categories');
  const { items: properties } = useEntities('properties', '/properties');
  const { items: units } = useEntities('units', '/units');
  const { items: tenants } = useEntities('tenants', '/tenants');

  const noneOpt = t('ui.form.none') || '— Keine —';

  const columns = [
    { key: 'booking_date', label: t('finance.bookings.form.date') || 'Datum', type: 'date', filterType: 'dateRange' },
    { key: 'amount', label: t('finance.bookings.form.amount') || 'Betrag (€)', type: 'number', align: 'right', filterType: 'numberRange',
      render: v => {
        const n = Number(v);
        const cls = n < 0 ? 'text-red' : 'text-green';
        return <span className={cls}>{n.toFixed(2)} €</span>;
      }},
    { key: 'payment_text', label: t('finance.bookings.form.paymentText') || 'Buchungstext', filterType: 'text' },
    { key: 'status', label: t('ui.form.status') || 'Status', type: 'status', filterType: 'select' },
  ];

  const fields = [
    { key: 'account_id', label: t('finance.accounts.form.name') || 'Konto', required: true, type: 'select',
      options: accounts.map(a => ({ value: a.id, label: a.name })) },
    { key: 'category_id', label: t('finance.bookings.form.category') || 'Kategorie', type: 'select',
      options: [{ value: '', label: noneOpt }, ...categories.map(c => ({ value: c.id, label: c.name }))] },
    { key: 'property_id', label: t('portfolio.properties.form.name') || 'Immobilie', type: 'select',
      options: [{ value: '', label: noneOpt }, ...properties.map(p => ({ value: p.id, label: p.name }))] },
    { key: 'unit_id', label: t('units.list.columns.label') || 'Einheit', type: 'select',
      options: [{ value: '', label: noneOpt }, ...units.map(u => ({ value: u.id, label: u.label }))] },
    { key: 'tenant_id', label: t('tenantsContracts.tenants.title') || 'Mieter', type: 'select',
      options: [{ value: '', label: noneOpt }, ...tenants.map(tn => ({ value: tn.id, label: tn.full_name }))] },
    { key: 'booking_date', label: t('finance.bookings.form.bookingDate') || 'Buchungsdatum', type: 'date', required: true },
    { key: 'amount', label: t('finance.bookings.form.amount') || 'Betrag (€)', type: 'number', required: true },
    { key: 'payment_text', label: t('finance.bookings.form.paymentText') || 'Buchungstext' },
    { key: 'receipt_url', label: t('finance.bookings.form.receiptUrl') || 'Beleg-URL', placeholder: '/belege/beleg.pdf' },
    { key: 'status', label: t('ui.form.status') || 'Status', type: 'select', default: 'open', options: [
      { value: 'open', label: t('ui.filterChips.open') || 'Offen' },
      { value: 'matched', label: t('finance.bookings.status.matched') || 'Zugeordnet' },
      { value: 'booked', label: t('finance.bookings.status.booked') || 'Gebucht' },
    ]},
  ];

  return <CrudPage title={t('finance.bookings.title') || 'Buchungen'} endpoint="/bookings" columns={columns} formFields={fields} />;
}
