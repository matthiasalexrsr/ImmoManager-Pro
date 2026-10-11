// Server answers of the handover protocol API, for the frontend tests.

export const ROOM = '11111111-1111-4111-8111-111111111111';
export const DEFECT = '22222222-2222-4222-8222-222222222222';

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
