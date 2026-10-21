import { describe, expect, it } from 'vitest';
import { deriveDocumentAssociations, documentAssociationFields, resolveDocumentContext } from '../features/documentDetail/documentAssociations';

const properties = [{ id: 'p1', name: 'Haus A' }, { id: 'p2', name: 'Haus B' }];
const units = [{ id: 'u1', label: 'Wohnung 1', property_id: 'p1' }, { id: 'u2', label: 'Wohnung 1', property_id: 'p2' }];
const contracts = [{ id: 'c1', contract_number: 'MV-A', property_id: 'p1', unit_id: 'u1', tenant_id: 't1' },
  { id: 'c2', contract_number: 'MV-B', property_id: 'p2', unit_id: 'u2', tenant_id: 't2' }];
const tenants = [{ id: 't1', full_name: 'Erste Partei' }, { id: 't2', full_name: 'Zweite Partei', archived: true }];
const fields = documentAssociationFields({ properties, units, contracts, tenants });
const field = name => fields.find(row => row.key === name);

describe('shared document assignments', () => {
  it('filters dependent choices and disambiguates identically named units', () => {
    expect(field('unit_id').options({ property_id: 'p2' })).toEqual([
      { value: '', label: '— Keine —' }, { value: 'u2', label: 'Wohnung 1 · Haus B' }]);
    expect(field('contract_id').options({ property_id: 'p1', tenant_id: 't2' })).toHaveLength(1);
    expect(field('contract_id').options({ unit_id: 'u1' })[1].value).toBe('c1');
    expect(field('tenant_id').options[2].label).toBe('Zweite Partei (archiviert)');
    expect(field('property_id').clearOnChange).toEqual(['unit_id', 'contract_id']);
  });
  it('selecting a contract fills all three related fields', () => {
    expect(deriveDocumentAssociations(units, contracts)({ contract_id: 'c2' }, 'contract_id'))
      .toEqual({ property_id: 'p2', unit_id: 'u2', tenant_id: 't2' });
    expect(deriveDocumentAssociations(units, contracts)({ unit_id: 'u1' }, 'unit_id')).toEqual({ property_id: 'p1' });
  });
  it('resolves indirect locations without modifying the saved metadata', () => {
    const doc = { contract_id: 'c1', property_id: null, unit_id: null, tenant_id: null };
    expect(resolveDocumentContext(doc, units, contracts)).toEqual({ property_id: 'p1', unit_id: 'u1', contract_id: 'c1', tenant_id: 't1' });
    expect(doc.property_id).toBeNull(); expect(doc.unit_id).toBeNull(); expect(doc.tenant_id).toBeNull();
    expect(resolveDocumentContext({ unit_id: 'u2' }, units, contracts)).toEqual({ property_id: 'p2', unit_id: 'u2', contract_id: null, tenant_id: null });
  });
});
