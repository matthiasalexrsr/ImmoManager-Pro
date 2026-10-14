// The handover protocol editor's form: built from the server's detail, sent back whole (PUT .../content).

export const CONDITIONS = ['good', 'fair', 'poor'];
export const RESPONSIBLE = ['tenant', 'landlord', 'open'];
export const KEY_TYPES = ['house_door', 'apartment_door', 'mailbox', 'cellar', 'garage', 'other'];
export const METER_TYPES = ['cold_water', 'hot_water', 'heating', 'electricity', 'gas'];

export const newId = () => crypto.randomUUID();

export function formatDay(value, locale) {
  if (!value) return '—';
  const date = /^\d{4}-\d{2}-\d{2}$/.test(value) ? new Date(`${value}T00:00:00Z`) : new Date(value);
  if (!Number.isFinite(date.getTime())) return String(value);
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeZone: 'UTC' }).format(date);
}

/** A number as typed: "1.234,5" and "1234.5" are 1234.5; empty is null, anything else NaN. */
export function parseNumber(value) {
  if (typeof value === 'number') return Number.isFinite(value) ? value : Number.NaN;
  const text = String(value ?? '').trim().replace(/\s/g, '');
  if (!text) return null;
  const normalized = text.includes(',') ? text.replace(/\./g, '').replace(',', '.') : text;
  return /^\d+(\.\d+)?$/.test(normalized) ? Number(normalized) : Number.NaN;
}

const count = value => {
  const number = parseNumber(value);
  return Number.isInteger(number) && number >= 0 && number <= 999 ? number : Number.NaN;
};

export function formFromDetail(detail) {
  const protocol = detail.protocol;
  const byMeter = new Map(detail.meter_readings.filter(r => r.meter_id).map(r => [r.meter_id, r]));
  const meterRows = detail.meters.filter(meter => meter.in_service || byMeter.has(meter.id)).map(meter => {
    const reading = byMeter.get(meter.id);
    return {
      id: reading?.id || newId(), meter_id: meter.id, meter_type: meter.meter_type,
      meter_number: meter.serial_number || '', unit: meter.measure_unit || '', last_reading: meter.last_reading,
      value: reading ? String(reading.reading_value) : '', notes: reading?.notes || '',
    };
  });
  const freeRows = detail.meter_readings.filter(r => !r.meter_id).map(reading => ({
    id: reading.id, meter_id: null, meter_type: reading.meter_type, meter_number: reading.meter_number || '',
    unit: reading.unit || '', last_reading: null, value: String(reading.reading_value), notes: reading.notes || '',
  }));
  return {
    protocol_date: protocol.protocol_date || '',
    tenant_present: Boolean(protocol.tenant_present),
    landlord_present: Boolean(protocol.landlord_present),
    overall_condition: protocol.overall_condition || '',
    notes: protocol.notes || '',
    tenant_signature: protocol.tenant_signature || '',
    landlord_signature: protocol.landlord_signature || '',
    rooms: detail.rooms.map(room => ({ id: room.id, name: room.name, condition: room.condition || '',
      notes: room.notes || '' })),
    defects: detail.defects.map(defect => ({
      id: defect.id, room_id: defect.room_id || '', description: defect.description, responsible: defect.responsible,
      remedy: defect.remedy || '', due_date: defect.due_date || '',
    })),
    keys: detail.keys.map(key => ({
      id: key.id, key_type: key.key_type, label: key.label || '', handed_over: String(key.handed_over),
      returned: key.returned == null ? '' : String(key.returned), notes: key.notes || '',
    })),
    meters: [...meterRows, ...freeRows],
  };
}

export const formSignature = form => JSON.stringify(form);

export const newRoom = (name = '') => ({ id: newId(), name, condition: '', notes: '' });
export const newDefect = (roomId = '') => ({ id: newId(), room_id: roomId, description: '', responsible: 'open',
  remedy: '', due_date: '' });
export const newKey = (keyType = 'apartment_door') => ({ id: newId(), key_type: keyType, label: '', handed_over: '1',
  returned: '', notes: '' });
export const newFreeReading = (meterType = 'electricity') => ({ id: newId(), meter_id: null, meter_type: meterType,
  meter_number: '', unit: '', last_reading: null, value: '', notes: '' });

/** Keys still missing at a move-out (null while nothing is entered). */
export function missingKeys(key) {
  const handed = count(key.handed_over);
  const back = key.returned === '' ? null : count(key.returned);
  if (back === null || Number.isNaN(handed) || Number.isNaN(back)) return null;
  return Math.max(handed - back, 0);
}

/** What the form cannot be saved with (the server checks again; completeness for finalizing is its job). */
export function formErrors(form) {
  const errors = [];
  if (!/^\d{4}-\d{2}-\d{2}$/.test(form.protocol_date)) errors.push('date');
  if (form.rooms.some(room => !room.name.trim())) errors.push('roomName');
  if (form.defects.some(defect => !defect.description.trim())) errors.push('defectDescription');
  if (form.keys.some(key => Number.isNaN(count(key.handed_over))
      || (key.returned !== '' && Number.isNaN(count(key.returned))))) errors.push('keyCount');
  if (form.meters.some(row => Number.isNaN(parseNumber(row.value)))) errors.push('meterValue');
  return errors;
}

const text = value => (value ?? '').trim() || null;

export function contentPayload(form, revision) {
  return {
    base_revision: revision,
    protocol_date: form.protocol_date,
    tenant_present: form.tenant_present,
    landlord_present: form.landlord_present,
    overall_condition: form.overall_condition || null,
    notes: text(form.notes),
    tenant_signature: text(form.tenant_signature),
    landlord_signature: text(form.landlord_signature),
    rooms: form.rooms.map(room => ({ id: room.id, name: room.name.trim(), condition: room.condition || null,
      notes: text(room.notes) })),
    defects: form.defects.map(defect => ({
      id: defect.id, room_id: defect.room_id || null, description: defect.description.trim(),
      responsible: defect.responsible, remedy: text(defect.remedy), due_date: defect.due_date || null,
    })),
    keys: form.keys.map(key => ({
      id: key.id, key_type: key.key_type, label: text(key.label), handed_over: count(key.handed_over),
      returned: key.returned === '' ? null : count(key.returned), notes: text(key.notes),
    })),
    // rows without a value are meters not read (yet): they are not sent
    meter_readings: form.meters.filter(row => parseNumber(row.value) !== null).map(row => ({
      id: row.id, meter_id: row.meter_id, meter_type: row.meter_id ? null : row.meter_type,
      meter_number: row.meter_id ? null : text(row.meter_number), reading_value: parseNumber(row.value),
      unit: row.meter_id ? null : text(row.unit), notes: text(row.notes),
    })),
  };
}

/** The photos of one row (room, defect, meter reading) or, without a field, those of the protocol itself. */
export function photosOf(photos, field, id) {
  if (!field) return photos.filter(photo => !photo.room_id && !photo.defect_id && !photo.meter_reading_id);
  return photos.filter(photo => photo[field] === id);
}

export function protocolState(protocol) {
  if (protocol.finalized_at) return 'finalized';
  if (protocol.correction_of_id) return 'correction';
  return 'draft';
}
