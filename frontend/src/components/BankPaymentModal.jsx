import useWriteAccess from '../hooks/useWriteAccess';
import { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import FormModal from './FormModal';

const available = booking => Math.round((Number(booking.amount) - Number(booking.allocated_amount || 0)) * 100) / 100;

export default function BankPaymentModal({ row, onSave, onClose }) {
  const { t, locale } = useTranslation();
  const [bookings, setBookings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [revision, setRevision] = useState(0);
  const { canWrite, requireWrite } = useWriteAccess('/bookings', onClose);
  const text = key => t(`pages.rentOverview.${key}`);

  useEffect(() => {
    if (!canWrite) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    api.getAll('/bookings', { signal: controller.signal }).then(rows => {
      if (controller.signal.aborted) return;
      setBookings(rows.filter(booking => Number(booking.amount) > 0 && available(booking) > 0
        && !['cancelled', 'void'].includes(booking.status)
        && ['tenant_id', 'property_id', 'unit_id'].every(key => !booking[key] || booking[key] === row[key]))
        .sort((a, b) => b.booking_date.localeCompare(a.booking_date)));
    }).catch(err => { if (!controller.signal.aborted) setError(err.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [row, revision, canWrite]);

  const fields = useMemo(() => {
    if (loading || error || !bookings.length) return [];
    const label = key => t(`pages.rentOverview.${key}`);
    const fmt = value => new Intl.NumberFormat(locale, { style: 'currency', currency: 'EUR' }).format(value);
    return [
      { key: 'booking_id', label: label('bankBooking'), type: 'select', required: true,
        options: bookings.map(booking => ({ value: booking.id,
          label: `${booking.booking_date} · ${fmt(available(booking))} · ${booking.payment_text || '—'}` })),
        onChange: id => {
          const booking = bookings.find(item => item.id === id);
          return booking ? { payment_date: booking.booking_date, amount: Math.min(row.remaining, available(booking)) } : {};
        } },
      { key: 'amount', label: label('paymentAmount'), type: 'number', required: true, min: 0.01,
        max: values => Math.min(row.remaining, available(bookings.find(item => item.id === values.booking_id) || { amount: row.remaining })) },
      { key: 'payment_date', label: label('paymentDate'), type: 'date', required: true },
      { key: 'note', label: label('note'), type: 'textarea' },
    ];
  }, [bookings, loading, error, row.remaining, t, locale]);

  if (!canWrite) return null;
  return <FormModal title={`${text('allocateBooking')} — ${row.tenant_name}`} fields={fields}
    onSave={async values => { requireWrite(); await onSave(values); }} onClose={onClose} saveDisabled={loading || !!error || !bookings.length}>
    {loading ? <p role="status">{t('pages.loading')}</p> : error ? <div role="alert" className="alert alert-error">
      {error} <button type="button" className="btn btn-secondary" onClick={() => setRevision(value => value + 1)}>{text('retry')}</button>
    </div> : <p>{text(bookings.length ? 'allocationHelp' : 'noAvailableBookings')}</p>}
  </FormModal>;
}
