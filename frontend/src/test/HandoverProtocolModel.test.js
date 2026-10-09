import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import {
  contentPayload,
  formErrors,
  formFromDetail,
  formSignature,
  missingKeys,
  newFreeReading,
  parseNumber,
  photosOf,
  protocolState,
} from '../features/handoverProtocol/handoverProtocolModel';
import { COPY, handoverText } from '../features/handoverProtocol/handoverProtocolText';

const ROOM = '11111111-1111-4111-8111-111111111111';
const DEFECT = '22222222-2222-4222-8222-222222222222';

export function detailFixture(overrides = {}) {
  return {
    protocol: { id: 'p-1', protocol_type: 'move_out', protocol_date: '2026-06-30', tenant_present: true,
      landlord_present: true, overall_condition: null, notes: null, tenant_signature: 'Mia Muster',
      landlord_signature: 'Linda Reiser', status: 'draft', finalized_at: null, correction_of_id: null,
      document_id: null, revision: '"rev-1"' },
    state: { finalized: false, editable: true, legacy_status_finalized: false, superseded: false },
    rooms: [{ id: ROOM, protocol_id: 'p-1', position: 0, name: 'Küche', condition: 'good', notes: null }],
    defects: [{ id: DEFECT, protocol_id: 'p-1', room_id: ROOM, position: 0, description: 'Bohrlöcher',
      responsible: 'tenant', remedy: null, due_date: null, resolved_at: null, resolution_note: null }],
    keys: [{ id: 'k-1', protocol_id: 'p-1', position: 0, key_type: 'apartment_door', label: null, handed_over: 3,
      returned: null, notes: null }],
    meter_readings: [],
    photos: [],
    meters: [
      { id: 'm-1', meter_type: 'cold_water', serial_number: 'KW-1', measure_unit: 'm³', in_service: true,
        last_reading: { reading_date: '2024-01-01', value: 100 } },
      { id: 'm-old', meter_type: 'gas', serial_number: 'G-0', measure_unit: null, in_service: false, last_reading: null },
    ],
    source: { contract: { contract_number: 'V-1', start_date: '2024-01-01', end_date: '2026-06-30' },
      property: { name: 'Bautzner Straße 61' }, unit: { label: 'WE 3' }, tenant: { full_name: 'Mia Muster' } },
    original: null, correction_of: null, corrections: [], problems: [],
    related: { previous_contract: null, next_contract: null, templates: [] },
    ...overrides,
  };
}

describe('handover protocol form', () => {
  it('reads numbers as typed in German or English', () => {
    expect(parseNumber('1.234,5')).toBe(1234.5);
    expect(parseNumber('1234.5')).toBe(1234.5);
    expect(parseNumber(' 130 ')).toBe(130);
    expect(parseNumber('')).toBeNull();
    expect(parseNumber('12a')).toBeNaN();
    expect(parseNumber('-1')).toBeNaN();
  });

  it('offers a row for every meter in service, also before it was read', () => {
    const form = formFromDetail(detailFixture());
    expect(form.meters.map(row => [row.meter_id, row.value])).toEqual([['m-1', '']]);
    expect(form.meters[0].last_reading).toEqual({ reading_date: '2024-01-01', value: 100 });
    const read = formFromDetail(detailFixture({ meter_readings: [{ id: 'r-1', meter_id: 'm-old', meter_type: 'gas',
      reading_value: 7.5, unit: 'm³', notes: null }] }));
    expect(read.meters.map(row => [row.meter_id, row.value, row.id])).toEqual([['m-1', '', expect.any(String)],
      ['m-old', '7.5', 'r-1']]);
  });

  it('sends the whole draft, without meters that were not read', () => {
    const form = formFromDetail(detailFixture());
    form.meters[0].value = '130,25';
    form.keys[0].returned = '2';
    const free = { ...newFreeReading('electricity'), value: '4711', meter_number: 'S-9', unit: 'kWh' };
    form.meters.push(free, { ...newFreeReading('gas'), value: '' });
    const payload = contentPayload(form, '"rev-1"');
    expect(payload.base_revision).toBe('"rev-1"');
    expect(payload.rooms).toEqual([{ id: ROOM, name: 'Küche', condition: 'good', notes: null }]);
    expect(payload.defects[0]).toMatchObject({ id: DEFECT, room_id: ROOM, responsible: 'tenant', due_date: null });
    expect(payload.keys[0]).toMatchObject({ handed_over: 3, returned: 2 });
    expect(payload.meter_readings).toEqual([
      { id: form.meters[0].id, meter_id: 'm-1', meter_type: null, meter_number: null, reading_value: 130.25,
        unit: null, notes: null },
      { id: free.id, meter_id: null, meter_type: 'electricity', meter_number: 'S-9', reading_value: 4711,
        unit: 'kWh', notes: null },
    ]);
  });

  it('names what cannot be saved', () => {
    const form = formFromDetail(detailFixture());
    expect(formErrors(form)).toEqual([]);
    form.rooms[0].name = ' ';
    form.defects[0].description = '';
    form.keys[0].handed_over = '1,5';
    form.meters[0].value = 'abc';
    form.protocol_date = '';
    expect(formErrors(form)).toEqual(['date', 'roomName', 'defectDescription', 'keyCount', 'meterValue']);
  });

  it('counts missing keys and groups photos', () => {
    expect(missingKeys({ handed_over: '3', returned: '2' })).toBe(1);
    expect(missingKeys({ handed_over: '3', returned: '' })).toBeNull();
    expect(missingKeys({ handed_over: '2', returned: '3' })).toBe(0);
    const photos = [{ id: 'a', room_id: ROOM }, { id: 'b', defect_id: DEFECT }, { id: 'c' }];
    expect(photosOf(photos, 'room_id', ROOM).map(p => p.id)).toEqual(['a']);
    expect(photosOf(photos, null, null).map(p => p.id)).toEqual(['c']);
    expect(protocolState({ finalized_at: '2026-07-01T00:00:00' })).toBe('finalized');
    expect(protocolState({ finalized_at: null, correction_of_id: 'x' })).toBe('correction');
    expect(formSignature(formFromDetail(detailFixture()))).toBe(formSignature(formFromDetail(detailFixture())));
  });
});

describe('handover protocol texts', () => {
  const SRC = path.resolve(__dirname, '..');
  const files = ['HandoverProtocolEditor.jsx', 'HandoverProtocolsDialog.jsx'].map(name =>
    path.join(SRC, 'features/handoverProtocol', name)).concat([path.join(SRC, 'pages/HandoverProtocols.jsx')]);
  const used = new Set();
  for (const file of files) {
    for (const match of fs.readFileSync(file, 'utf8').matchAll(/\bsay\(\s*'([A-Za-z_]+)'/g)) used.add(match[1]);
  }

  it('has every text in German, English and Spanish', () => {
    const german = Object.keys(COPY['de-DE']).sort();
    expect(Object.keys(COPY['en-US']).sort()).toEqual(german);
    expect(Object.keys(COPY['es-ES']).sort()).toEqual(german);
    expect(used.size).toBeGreaterThan(60);
    expect([...used].filter(key => !(key in COPY['de-DE']))).toEqual([]);
  });

  it('fills in parameters and falls back to German', () => {
    expect(handoverText('en-US', 'missingKeys', { count: 2 })).toBe('Missing: 2');
    expect(handoverText('fr-FR', 'title')).toBe('Übergabeprotokoll');
  });
});
