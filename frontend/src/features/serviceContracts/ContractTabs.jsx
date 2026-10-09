import { useMemo, useState } from 'react';
import { api } from '../../api';
import { useTranslation } from '../../i18n';
import FormModal from '../../components/FormModal';
import { useConfirm } from '../../components/ConfirmDialog';
import { formatDate, formatMoney, formatNumber } from '../../utils/format';
import {
  deadlineLabel, intervalLabel, locationPayload, noticeToLabel, noticeUnitLabel, renewalLabel, statusLabel,
  tariffFields, tariffInitial, tariffPayload,
} from './model';

function loadChoices() {
  return Promise.all(['/properties', '/units', '/meters'].map(path => api.list(path).catch(() => [])))
    .then(([properties, units, meters]) => ({ properties, units, meters }));
}

function locationFields(t, { properties, units, meters }) {
  return [
    { key: 'property_id', label: t('serviceContracts.fields.property'), type: 'select', required: true,
      clearOnChange: ['unit_id', 'meter_id'], options: properties.map(p => ({ value: p.id, label: p.name })) },
    { key: 'unit_id', label: t('serviceContracts.fields.unit'), type: 'select', clearOnChange: ['meter_id'],
      options: values => units.filter(u => u.property_id === values.property_id).map(u => ({ value: u.id, label: u.label })) },
    { key: 'meter_id', label: t('serviceContracts.fields.meter'), type: 'select',
      options: values => meters.filter(m => (values.unit_id ? m.unit_id === values.unit_id
        : units.some(u => u.id === m.unit_id && u.property_id === values.property_id)))
        .map(m => ({ value: m.id, label: [m.meter_type, m.serial_number].filter(Boolean).join(' · ') })) },
    { key: 'supply_point', label: t('serviceContracts.fields.supplyPoint') },
    { key: 'share_weight', label: t('serviceContracts.fields.shareWeight'), type: 'number', default: 1,
      hint: t('serviceContracts.hints.shareWeight') },
    { key: 'valid_from', label: t('serviceContracts.fields.locationFrom'), type: 'date' },
    { key: 'valid_to', label: t('serviceContracts.fields.locationTo'), type: 'date' },
    { key: 'notes', label: t('serviceContracts.fields.notes'), type: 'textarea' },
  ];
}

function RowActions({ t, label, onEdit, onDelete }) {
  return (
    <span className="sc-row-actions">
      {onEdit && <button type="button" className="btn btn-sm btn-secondary" onClick={onEdit}
        aria-label={`${t('serviceContracts.edit')}: ${label}`}>{t('serviceContracts.edit')}</button>}
      {onDelete && <button type="button" className="btn btn-sm btn-danger" onClick={onDelete}
        aria-label={`${t('serviceContracts.remove')}: ${label}`}>{t('serviceContracts.remove')}</button>}
    </span>
  );
}

export function LocationsTab({ contract, canWrite, onChanged }) {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const [modal, setModal] = useState(null);       // null | 'new' | location
  const [choices, setChoices] = useState({ properties: [], units: [], meters: [] });
  const [error, setError] = useState(null);
  const fields = useMemo(() => locationFields(t, choices), [t, choices]);
  const open = target => { setModal(target); loadChoices().then(setChoices); };
  const base = `/service-contracts/${encodeURIComponent(contract.id)}/locations`;

  const save = async values => {
    const body = locationPayload(values);
    if (modal === 'new') await api.post(base, body);
    else await api.put(`${base}/${encodeURIComponent(modal.id)}`, body);
    onChanged();
  };
  const remove = async location => {
    if (confirm && !(await confirm(t('serviceContracts.confirmRemoveLocation', { name: location.label })))) return;
    setError(null);
    try { await api.del(`${base}/${encodeURIComponent(location.id)}`); onChanged(); } catch (failure) { setError(failure.message); }
  };

  return (
    <div className="panel">
      <div className="panel-header sc-panel-header">
        <span>{t('serviceContracts.tabs.locations')}</span>
        {canWrite && <button type="button" className="btn btn-sm btn-primary" onClick={() => open('new')}>
          {t('serviceContracts.addLocation')}</button>}
      </div>
      <div className="panel-body">
        {error && <div role="alert" className="alert alert-error">{error}</div>}
        {contract.restricted && <p className="text-muted">{t('serviceContracts.hiddenLocations')}</p>}
        <div className="dossier-table-scroll" role="region" aria-label={t('serviceContracts.tabs.locations')} tabIndex={0}>
          <table className="simple-table sc-table">
            <thead><tr>
              <th>{t('serviceContracts.fields.location')}</th><th>{t('serviceContracts.fields.supplyPoint')}</th>
              <th className="text-right">{t('serviceContracts.fields.shareWeight')}</th>
              <th>{t('serviceContracts.fields.validity')}</th><th><span className="sr-only">{t('serviceContracts.actions')}</span></th>
            </tr></thead>
            <tbody>
              {contract.locations.map(location => (
                <tr key={location.id}>
                  <td>{location.label}</td>
                  <td className="sc-break">{location.supply_point || '—'}</td>
                  <td className="text-right">{formatNumber(location.share_weight, 2)}</td>
                  <td>{location.valid_from || location.valid_to
                    ? `${formatDate(location.valid_from, { blank: '…' })} – ${formatDate(location.valid_to, { blank: '…' })}` : '—'}</td>
                  <td>{canWrite && <RowActions t={t} label={location.label} onEdit={() => open(location)}
                    onDelete={contract.locations.length > 1 ? () => remove(location) : undefined} />}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      {modal && <FormModal title={modal === 'new' ? t('serviceContracts.addLocation') : t('serviceContracts.editLocation')}
        fields={fields} initial={modal === 'new' ? undefined : modal} onSave={save} onClose={() => setModal(null)} />}
    </div>
  );
}

function unitPricesText(prices) {
  return (prices || []).map(p => `${p.label}: ${p.price.replace('.', ',')} €/${p.unit}`).join('; ');
}

export function TariffsTab({ contract, canWrite, onChanged }) {
  const { t } = useTranslation();
  const confirm = useConfirm();
  const [modal, setModal] = useState(null);
  const [error, setError] = useState(null);
  const fields = useMemo(() => tariffFields(t), [t]);
  const base = `/service-contracts/${encodeURIComponent(contract.id)}/tariffs`;
  const current = contract.terms?.current_tariff_id;

  const save = async values => {
    const body = tariffPayload(values, '', modal === 'new' ? [] : modal.unit_prices || []);
    if (modal === 'new') await api.post(base, body);
    else await api.put(`${base}/${encodeURIComponent(modal.id)}`, body);
    onChanged();
  };
  const remove = async tariff => {
    if (confirm && !(await confirm(t('serviceContracts.confirmRemoveTariff', { date: formatDate(tariff.valid_from) })))) return;
    setError(null);
    try { await api.del(`${base}/${encodeURIComponent(tariff.id)}`); onChanged(); } catch (failure) { setError(failure.message); }
  };

  return (
    <div className="panel">
      <div className="panel-header sc-panel-header">
        <span>{t('serviceContracts.tabs.tariffs')}</span>
        {canWrite && <button type="button" className="btn btn-sm btn-primary" onClick={() => setModal('new')}>
          {t('serviceContracts.addTariff')}</button>}
      </div>
      <div className="panel-body">
        {error && <div role="alert" className="alert alert-error">{error}</div>}
        <p className="text-muted">{t('serviceContracts.tariffHistoryHint')}</p>
        {contract.tariffs.length === 0 ? <p className="empty-text">{t('serviceContracts.noTariffs')}</p> : (
          <div className="dossier-table-scroll" role="region" aria-label={t('serviceContracts.tabs.tariffs')} tabIndex={0}>
            <table className="simple-table sc-table">
              <thead><tr>
                <th>{t('serviceContracts.fields.validFrom')}</th><th>{t('serviceContracts.fields.tariffLabel')}</th>
                <th className="text-right">{t('serviceContracts.fields.advance')}</th>
                <th className="text-right">{t('serviceContracts.fields.basePrice')}</th>
                <th>{t('serviceContracts.fields.unitPrices')}</th><th>{t('serviceContracts.fields.priceGuarantee')}</th>
                <th><span className="sr-only">{t('serviceContracts.actions')}</span></th>
              </tr></thead>
              <tbody>
                {[...contract.tariffs].reverse().map(tariff => (
                  <tr key={tariff.id} className={tariff.id === current ? 'is-current' : undefined}>
                    <td>{formatDate(tariff.valid_from)}{tariff.id === current && <span className="badge badge-green sc-inline-badge">{t('serviceContracts.current')}</span>}</td>
                    <td>{tariff.label || '—'}</td>
                    <td className="text-right">{tariff.advance_amount != null
                      ? `${formatMoney(tariff.advance_amount)} ${intervalLabel(t, tariff.advance_interval)}` : '—'}</td>
                    <td className="text-right">{tariff.base_price != null
                      ? `${formatMoney(tariff.base_price)} ${tariff.base_price_period === 'year' ? t('serviceContracts.perYear') : t('serviceContracts.perMonth')}` : '—'}</td>
                    <td className="sc-break">{unitPricesText(tariff.unit_prices) || '—'}</td>
                    <td>{formatDate(tariff.price_guarantee_until)}</td>
                    <td>{canWrite && <RowActions t={t} label={formatDate(tariff.valid_from)}
                      onEdit={() => setModal(tariffInitial(tariff))} onDelete={() => remove(tariff)} />}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {modal && <FormModal title={modal === 'new' ? t('serviceContracts.addTariff') : t('serviceContracts.editTariff')}
        fields={fields} initial={modal === 'new' ? undefined : modal} onSave={save} onClose={() => setModal(null)} />}
    </div>
  );
}

export function DeadlinesTab({ contract }) {
  const { t } = useTranslation();
  const terms = contract.terms || {};
  const notice = terms.notice;
  const next = terms.next_notice_deadline;
  const noticeText = notice ? t('serviceContracts.noticeText', {
    value: notice.value, unit: noticeUnitLabel(t, notice.unit), to: noticeToLabel(t, notice.to) }) : t('serviceContracts.noNotice');
  return (
    <div className="detail-overview-grid">
      <div className="panel">
        <div className="panel-header">{t('serviceContracts.termTitle')}</div>
        <div className="panel-body">
          <div className="detail-field"><span>{t('serviceContracts.fields.status')}:</span> {statusLabel(t, terms.status)}</div>
          <div className="detail-field"><span>{t('serviceContracts.fields.start')}:</span> {formatDate(contract.start_date)}</div>
          <div className="detail-field"><span>{t('serviceContracts.firstTermEnd')}:</span> {formatDate(terms.first_term_end)}</div>
          <div className="detail-field"><span>{t('serviceContracts.currentTerm')}:</span> {terms.current_term
            ? `${formatDate(terms.current_term.start)} – ${formatDate(terms.current_term.end, { blank: t('serviceContracts.openEnded') })}` : '—'}</div>
          <div className="detail-field"><span>{t('serviceContracts.fields.renewal')}:</span> {renewalLabel(t, terms.renewal_mode)}
            {terms.renewal_mode === 'fixed' && terms.renewal_months ? ` (${t('serviceContracts.months', { count: terms.renewal_months })})` : ''}</div>
          <div className="detail-field"><span>{t('serviceContracts.noticePeriod')}:</span> {noticeText}</div>
          <div className="detail-field"><span>{t('serviceContracts.effectiveEnd')}:</span> {formatDate(terms.effective_end, { blank: t('serviceContracts.openEnded') })}</div>
          {terms.cancellation && <div className="detail-field"><span>{t('serviceContracts.cancellation')}:</span>
            {t('serviceContracts.cancellationText', { on: formatDate(terms.cancellation.cancelled_on), effective: formatDate(terms.cancellation.effective) })}</div>}
        </div>
      </div>
      <div className="panel">
        <div className="panel-header">{t('serviceContracts.nextNotice')}</div>
        <div className="panel-body">
          {next ? (
            <div className={`sc-deadline-card ${next.days_left <= 30 ? 'is-urgent' : ''}`} data-testid="sc-next-notice">
              <strong>{formatDate(next.date)}</strong>
              <span>{t('serviceContracts.noticeDeadlineText', { end: formatDate(next.end), days: next.days_left })}</span>
              <span className="text-muted">{next.renews_to ? t('serviceContracts.renewsTo', { date: formatDate(next.renews_to) })
                : t('serviceContracts.continuesIndefinitely')}</span>
            </div>
          ) : <p className="empty-text">{t('serviceContracts.noNoticeDeadline')}</p>}
          {terms.earliest_end_if_cancelled_today && <p className="text-muted">
            {t('serviceContracts.earliestEnd', { date: formatDate(terms.earliest_end_if_cancelled_today) })}</p>}
          <h4 className="sc-subtitle">{t('serviceContracts.upcomingDeadlines')}</h4>
          {(terms.upcoming || []).length === 0 ? <p className="empty-text">{t('serviceContracts.noUpcoming')}</p> : (
            <ul className="service-contracts-deadline-list">
              {terms.upcoming.map(d => (
                <li key={`${d.kind}-${d.date}`}><span className="sc-deadline-date">{formatDate(d.date)}</span>
                  <span>{deadlineLabel(t, d.kind)}</span>
                  <span className="text-muted">{t('serviceContracts.daysLeft', { days: d.days_left })}</span></li>
              ))}
            </ul>
          )}
          <p className="text-muted sc-note">{t('serviceContracts.reminderNote', { days: contract.reminder_days })}</p>
        </div>
      </div>
    </div>
  );
}
