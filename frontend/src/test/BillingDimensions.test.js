import { describe, expect, it } from 'vitest';
import {
  allocationKeyPayload,
  dimensionPresentation,
  meterPayload,
} from '../features/billingDimensions/billingDimensions';

describe('billing dimension helpers', () => {
  it('renders known codes naturally and keeps unknown historical values explicit', () => {
    expect(dimensionPresentation('cold_water', 'medium')).toMatchObject({
      text: 'Kaltwasser',
      state: 'known',
      raw: 'cold_water',
    });
    expect(dimensionPresentation('legacy_medium_x', 'medium')).toMatchObject({
      text: 'Individuell: legacy_medium_x',
      state: 'custom',
      raw: 'legacy_medium_x',
    });
    expect(dimensionPresentation(null, 'unit')).toMatchObject({
      text: 'Ungeklärt',
      state: 'unknown',
    });
    expect(dimensionPresentation(null, 'unit', { required: true })).toMatchObject({
      text: 'Pflichtangabe fehlt',
      state: 'missing',
    });
  });

  it('requires explicit consumption dimensions but preserves arbitrary valid existing strings', () => {
    expect(() => allocationKeyPayload({
      key_type: 'consumption',
      consumption_medium: null,
      consumption_unit: 'kWh',
    })).toThrow(/Verbrauchsmedium/);

    expect(allocationKeyPayload({
      key_type: 'consumption',
      consumption_medium: 'legacy_medium_x',
      consumption_unit: 'custom-unit-17',
    })).toMatchObject({
      consumption_medium: 'legacy_medium_x',
      consumption_unit: 'custom-unit-17',
    });
  });

  it('never infers measurement_unit from meter_type and maps blank explicitly to null', () => {
    expect(meterPayload({ meter_type: 'cold_water', measurement_unit: null }))
      .toEqual({ meter_type: 'cold_water', measurement_unit: null });
    expect(meterPayload({ meter_type: 'cold_water', measurement_unit: '   ' }))
      .toEqual({ meter_type: 'cold_water', measurement_unit: null });
    expect(meterPayload({ meter_type: 'cold_water', measurement_unit: 'm³' }))
      .toEqual({ meter_type: 'cold_water', measurement_unit: 'm³' });
  });
});
