import { useCallback, useState } from 'react';
import { useTranslation } from '../i18n';
import FormModal from './FormModal';
import useBookingChoices from '../hooks/useBookingChoices';

export default function BookingEditor({ initial, onSave, onClose }) {
  const { t } = useTranslation();
  const [references, setReferences] = useState(initial || {});
  const onValuesChange = useCallback(values => setReferences(previous => {
    const keys = ['account_id', 'category_id', 'property_id', 'unit_id', 'tenant_id'];
    return keys.every(key => previous[key] === values[key]) ? previous
      : Object.fromEntries(keys.map(key => [key, values[key]]));
  }), []);
  const accountLabel = t('bookingPages.account');
  const categoryLabel = t('finance.bookings.form.category');
  const propertyLabel = t('bookingPages.property');
  const unitLabel = t('bookingPages.unit');
  const tenantLabel = t('bookingPages.tenant');
  const accounts = useBookingChoices('accounts', references.account_id, accountLabel);
  const categories = useBookingChoices('categories', references.category_id, categoryLabel);
  const properties = useBookingChoices('properties', references.property_id, propertyLabel);
  const units = useBookingChoices('units', references.unit_id, unitLabel);
  const tenants = useBookingChoices('tenants', references.tenant_id, tenantLabel);
  const fields = [
    { key: 'account_id', label: accountLabel, required: true, type: 'select', ...accounts },
    { key: 'category_id', label: categoryLabel, type: 'select', ...categories },
    { key: 'property_id', label: propertyLabel, type: 'select', ...properties },
    { key: 'unit_id', label: unitLabel, type: 'select', ...units },
    { key: 'tenant_id', label: tenantLabel, type: 'select', ...tenants },
    { key: 'booking_date', label: t('finance.bookings.form.bookingDate'), type: 'date', required: true },
    { key: 'amount', label: t('finance.bookings.form.amount'), type: 'number', required: true },
    { key: 'payment_text', label: t('finance.bookings.form.paymentText') },
    { key: 'receipt_url', label: t('finance.bookings.form.receiptUrl') },
    { key: 'status', label: t('ui.form.status'), type: 'select', default: 'open', options: [
      { value: 'open', label: t('ui.filterChips.open') },
      { value: 'matched', label: t('finance.bookings.statusOptions.matched') },
      { value: 'booked', label: t('finance.bookings.statusOptions.booked') },
      { value: 'confirmed', label: t('finance.bookings.statusOptions.confirmed') },
    ] },
  ];
  return <div onKeyDownCapture={event => {
    if (event.key === 'Enter' && event.target.name?.startsWith('lookup_')) event.preventDefault();
  }}><FormModal title={t(initial ? 'bookingPages.edit' : 'bookingPages.create')} fields={fields} initial={initial}
    onSave={onSave} onClose={onClose} onValuesChange={onValuesChange}
    saveDisabled={accounts.disabled || categories.disabled || properties.disabled || units.disabled || tenants.disabled} /></div>;
}
