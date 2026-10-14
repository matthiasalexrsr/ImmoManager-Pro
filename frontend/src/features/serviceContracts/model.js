// Property service contracts (Objektverträge): labels, form fields and payloads (backend: /service-contracts).
// Keys are literal on purpose: the translation test finds every one of them.

export const CONTRACT_TYPES = ['electricity', 'gas', 'district_heating', 'water', 'waste', 'cleaning', 'caretaker',
  'elevator', 'garden', 'winter_service', 'chimney_sweep', 'heating_maintenance', 'cable_tv', 'other'];

export function typeLabel(t, type) {
  switch (type) {
    case 'electricity': return t('serviceContracts.types.electricity');
    case 'gas': return t('serviceContracts.types.gas');
    case 'district_heating': return t('serviceContracts.types.district_heating');
    case 'water': return t('serviceContracts.types.water');
    case 'waste': return t('serviceContracts.types.waste');
    case 'cleaning': return t('serviceContracts.types.cleaning');
    case 'caretaker': return t('serviceContracts.types.caretaker');
    case 'elevator': return t('serviceContracts.types.elevator');
    case 'garden': return t('serviceContracts.types.garden');
    case 'winter_service': return t('serviceContracts.types.winter_service');
    case 'chimney_sweep': return t('serviceContracts.types.chimney_sweep');
    case 'heating_maintenance': return t('serviceContracts.types.heating_maintenance');
    case 'cable_tv': return t('serviceContracts.types.cable_tv');
    case 'other': return t('serviceContracts.types.other');
    default: return type || '—';
  }
}

export function statusLabel(t, status) {
  switch (status) {
    case 'upcoming': return t('serviceContracts.status.upcoming');
    case 'active': return t('serviceContracts.status.active');
    case 'cancelled': return t('serviceContracts.status.cancelled');
    case 'ended': return t('serviceContracts.status.ended');
    default: return status || '—';
  }
}

export const STATUS_BADGE = { upcoming: 'badge-blue', active: 'badge-green', cancelled: 'badge-yellow', ended: 'badge-gray' };

export function deadlineLabel(t, kind) {
  switch (kind) {
    case 'notice': return t('serviceContracts.deadlines.notice');
    case 'price_guarantee': return t('serviceContracts.deadlines.price_guarantee');
    case 'contract_end': return t('serviceContracts.deadlines.contract_end');
    default: return kind;
  }
}

export function intervalLabel(t, interval) {
  switch (interval) {
    case 'monthly': return t('serviceContracts.intervals.monthly');
    case 'bimonthly': return t('serviceContracts.intervals.bimonthly');
    case 'quarterly': return t('serviceContracts.intervals.quarterly');
    case 'semiannual': return t('serviceContracts.intervals.semiannual');
    case 'annual': return t('serviceContracts.intervals.annual');
    default: return interval || '';
  }
}

export function renewalLabel(t, mode) {
  switch (mode) {
    case 'none': return t('serviceContracts.renewal.none');
    case 'fixed': return t('serviceContracts.renewal.fixed');
    case 'indefinite': return t('serviceContracts.renewal.indefinite');
    default: return mode || '—';
  }
}

export function noticeUnitLabel(t, unit) {
  switch (unit) {
    case 'day': return t('serviceContracts.units.day');
    case 'week': return t('serviceContracts.units.week');
    case 'month': return t('serviceContracts.units.month');
    default: return unit || '';
  }
}

export function noticeToLabel(t, anchor) {
  switch (anchor) {
    case 'term_end': return t('serviceContracts.noticeTo.term_end');
    case 'any_day': return t('serviceContracts.noticeTo.any_day');
    case 'month_end': return t('serviceContracts.noticeTo.month_end');
    case 'quarter_end': return t('serviceContracts.noticeTo.quarter_end');
    case 'year_end': return t('serviceContracts.noticeTo.year_end');
    default: return anchor || '';
  }
}

export function providerName(contact) {
  if (!contact) return '';
  const person = [contact.first_name, contact.last_name].filter(Boolean).join(' ');
  return contact.company_name || person || contact.email || '';
}

// "0,3247" or "0.3247" -> "0.3247"; exact text, no float on the way (the server keeps six places)
export function decimalText(value) {
  if (value == null) return null;
  const text = String(value).trim().replace(/\s/g, '').replace(',', '.');
  if (!text) return null;
  if (!/^\d+(\.\d+)?$/.test(text)) throw new Error(`"${value}" ist keine gültige Zahl`);
  return text;
}

const blank = v => v === '' || v == null;
const orNull = v => (blank(v) ? null : v);

export function contractFields(t, { contacts, withLocation, properties = [], units = [], meters = [] }) {
  const options = list => list.map(([value, label]) => ({ value, label }));
  const fields = [
    { key: 'contract_type', label: t('serviceContracts.fields.type'), type: 'select', required: true,
      section: t('serviceContracts.sections.master'),
      options: CONTRACT_TYPES.map(type => ({ value: type, label: typeLabel(t, type) })) },
    { key: 'title', label: t('serviceContracts.fields.title'), required: true, section: t('serviceContracts.sections.master') },
    { key: 'provider_contact_id', label: t('serviceContracts.fields.provider'), type: 'select', required: true,
      section: t('serviceContracts.sections.master'), hint: t('serviceContracts.hints.provider'),
      options: [...contacts].sort((a, b) => providerName(a).localeCompare(providerName(b)))
        .map(c => ({ value: c.id, label: providerName(c) || c.id })) },
    { key: 'contract_number', label: t('serviceContracts.fields.contractNumber'), section: t('serviceContracts.sections.master') },
    { key: 'customer_number', label: t('serviceContracts.fields.customerNumber'), section: t('serviceContracts.sections.master') },
    { key: 'start_date', label: t('serviceContracts.fields.start'), type: 'date', required: true,
      section: t('serviceContracts.sections.term') },
    { key: 'end_date', label: t('serviceContracts.fields.end'), type: 'date', section: t('serviceContracts.sections.term'),
      hint: t('serviceContracts.hints.end') },
    { key: 'minimum_term_months', label: t('serviceContracts.fields.minimumTerm'), type: 'number',
      section: t('serviceContracts.sections.term') },
    { key: 'renewal_mode', label: t('serviceContracts.fields.renewal'), type: 'select', required: true, default: 'fixed',
      section: t('serviceContracts.sections.term'),
      options: options([['none', renewalLabel(t, 'none')], ['fixed', renewalLabel(t, 'fixed')],
        ['indefinite', renewalLabel(t, 'indefinite')]]) },
    { key: 'renewal_months', label: t('serviceContracts.fields.renewalMonths'), type: 'number', default: 12,
      section: t('serviceContracts.sections.term') },
    { key: 'notice_period_value', label: t('serviceContracts.fields.noticeValue'), type: 'number', default: 3,
      section: t('serviceContracts.sections.term') },
    { key: 'notice_period_unit', label: t('serviceContracts.fields.noticeUnit'), type: 'select', default: 'month',
      section: t('serviceContracts.sections.term'),
      options: ['day', 'week', 'month'].map(u => ({ value: u, label: noticeUnitLabel(t, u) })) },
    { key: 'notice_to', label: t('serviceContracts.fields.noticeTo'), type: 'select', default: 'term_end',
      section: t('serviceContracts.sections.term'), hint: t('serviceContracts.hints.noticeTo'),
      options: ['term_end', 'month_end', 'quarter_end', 'year_end', 'any_day'].map(a => ({ value: a, label: noticeToLabel(t, a) })) },
    { key: 'reminder_days', label: t('serviceContracts.fields.reminderDays'), type: 'number', default: 30,
      section: t('serviceContracts.sections.term') },
  ];
  if (withLocation) {
    fields.push(
      { key: 'property_id', label: t('serviceContracts.fields.property'), type: 'select', required: true,
        section: t('serviceContracts.sections.location'), clearOnChange: ['unit_id', 'meter_id'],
        options: properties.map(p => ({ value: p.id, label: p.name })) },
      { key: 'unit_id', label: t('serviceContracts.fields.unit'), type: 'select', section: t('serviceContracts.sections.location'),
        clearOnChange: ['meter_id'],
        options: values => units.filter(u => u.property_id === values.property_id).map(u => ({ value: u.id, label: u.label })) },
      { key: 'meter_id', label: t('serviceContracts.fields.meter'), type: 'select', section: t('serviceContracts.sections.location'),
        options: values => meters.filter(m => (values.unit_id ? m.unit_id === values.unit_id
          : units.some(u => u.id === m.unit_id && u.property_id === values.property_id)))
          .map(m => ({ value: m.id, label: [m.meter_type, m.serial_number].filter(Boolean).join(' · ') })) },
      { key: 'supply_point', label: t('serviceContracts.fields.supplyPoint'), section: t('serviceContracts.sections.location') },
      ...tariffFields(t, { prefix: 'tariff_', section: t('serviceContracts.sections.firstTariff') }),
    );
  }
  fields.push(
    { key: 'recoverable', label: t('serviceContracts.fields.recoverable'), type: 'select', default: 'false',
      section: t('serviceContracts.sections.billing'),
      options: [{ value: 'true', label: t('serviceContracts.yes') }, { value: 'false', label: t('serviceContracts.no') }] },
    { key: 'recoverable_percent', label: t('serviceContracts.fields.recoverablePercent'), type: 'number', default: 100,
      section: t('serviceContracts.sections.billing') },
    { key: 'cost_category', label: t('serviceContracts.fields.costCategory'), section: t('serviceContracts.sections.billing') },
    { key: 'notes', label: t('serviceContracts.fields.notes'), type: 'textarea' },
  );
  return fields;
}

export function tariffFields(t, { prefix = '', section } = {}) {
  const k = key => `${prefix}${key}`;
  return [
    { key: k('valid_from'), label: t('serviceContracts.fields.validFrom'), type: 'date', required: !prefix, section },
    { key: k('label'), label: t('serviceContracts.fields.tariffLabel'), section },
    { key: k('advance_amount'), label: t('serviceContracts.fields.advance'), type: 'number', section },
    { key: k('advance_interval'), label: t('serviceContracts.fields.advanceInterval'), type: 'select', default: 'monthly', section,
      options: ['monthly', 'bimonthly', 'quarterly', 'semiannual', 'annual'].map(i => ({ value: i, label: intervalLabel(t, i) })) },
    { key: k('advance_day'), label: t('serviceContracts.fields.advanceDay'), type: 'number', default: 1, section },
    { key: k('base_price'), label: t('serviceContracts.fields.basePrice'), type: 'number', section },
    { key: k('base_price_period'), label: t('serviceContracts.fields.basePricePeriod'), type: 'select', default: 'month', section,
      options: [{ value: 'month', label: t('serviceContracts.perMonth') }, { value: 'year', label: t('serviceContracts.perYear') }] },
    { key: k('price_label'), label: t('serviceContracts.fields.priceLabel'), placeholder: t('serviceContracts.hints.priceLabel'), section },
    { key: k('price_unit'), label: t('serviceContracts.fields.priceUnit'), placeholder: 'kWh', section },
    { key: k('price'), label: t('serviceContracts.fields.price'), placeholder: '0,3247', section,
      hint: t('serviceContracts.hints.price') },
    { key: k('price_guarantee_until'), label: t('serviceContracts.fields.priceGuarantee'), type: 'date', section },
  ];
}

export function tariffPayload(values, prefix = '', existing = []) {
  const get = key => values[`${prefix}${key}`];
  if (prefix && blank(get('valid_from'))) return null;
  const price = decimalText(get('price'));
  const unitPrices = existing.filter((_, index) => index > 0 || price == null);
  if (price != null) unitPrices.unshift({ label: get('price_label') || 'Arbeitspreis', unit: get('price_unit') || 'kWh', price });
  const advance = orNull(get('advance_amount'));
  return {
    valid_from: get('valid_from'),
    label: orNull(get('label')),
    advance_amount: advance,
    advance_interval: advance ? (get('advance_interval') || 'monthly') : null,
    advance_day: get('advance_day') || 1,
    base_price: orNull(get('base_price')),
    base_price_period: get('base_price_period') || 'month',
    unit_prices: unitPrices,
    price_guarantee_until: orNull(get('price_guarantee_until')),
  };
}

export function tariffInitial(tariff) {
  const [first] = tariff.unit_prices || [];
  return { ...tariff, price_label: first?.label || '', price_unit: first?.unit || '', price: first?.price || '' };
}

const MASTER_KEYS = ['contract_type', 'title', 'provider_contact_id', 'contract_number', 'customer_number', 'start_date',
  'end_date', 'minimum_term_months', 'renewal_mode', 'renewal_months', 'notice_period_value', 'notice_period_unit',
  'notice_to', 'reminder_days', 'recoverable', 'recoverable_percent', 'cost_category', 'notes', 'payment_method',
  'cancelled_on', 'cancellation_effective'];

export function contractPayload(values, current = {}) {
  const body = {};
  MASTER_KEYS.forEach(key => { body[key] = key in values ? values[key] : (current[key] ?? null); });
  body.recoverable = body.recoverable === true || body.recoverable === 'true';
  if (body.reminder_days == null) body.reminder_days = 30;
  if (body.recoverable_percent == null) body.recoverable_percent = 100;
  if (body.renewal_mode === 'indefinite' && (!body.notice_to || body.notice_to === 'term_end')) body.notice_to = 'month_end';
  if (body.renewal_mode !== 'fixed') body.renewal_months = null;
  if (body.notice_period_value == null) body.notice_period_unit = null;
  if (body.end_date) body.minimum_term_months = null;
  return body;
}

export function createPayload(values) {
  return {
    ...contractPayload(values),
    locations: [{ property_id: values.property_id, unit_id: orNull(values.unit_id), meter_id: orNull(values.meter_id),
      supply_point: orNull(values.supply_point) }],
    tariff: tariffPayload(values, 'tariff_'),
  };
}

export function locationPayload(values) {
  return {
    property_id: values.property_id, unit_id: orNull(values.unit_id), meter_id: orNull(values.meter_id),
    supply_point: orNull(values.supply_point), share_weight: values.share_weight || 1,
    valid_from: orNull(values.valid_from), valid_to: orNull(values.valid_to), notes: orNull(values.notes),
  };
}

export function yearWindow(year) {
  return { date_from: `${year}-01-01`, date_to: `${year}-12-31` };
}
