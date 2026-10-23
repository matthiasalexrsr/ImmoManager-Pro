/** Shared, dependent choices for the upload form and the document file's assignment editor. */
export function documentAssociationFields({ properties = [], units = [], contracts = [], tenants = [], tenantId = '' }) {
  const propertyNames = Object.fromEntries(properties.map(row => [row.id, row.name]));
  const tenantNames = Object.fromEntries(tenants.map(row => [row.id, row.full_name]));
  const empty = label => ({ value: '', label });
  return [
    { key: 'tenant_id', label: 'Mieter / Partei', type: 'select', default: tenantId, clearOnChange: ['contract_id'],
      options: [empty('— Über Vertrag oder ohne Partei —'), ...tenants.map(row => ({ value: row.id,
        label: `${row.full_name}${row.archived ? ' (archiviert)' : ''}` }))] },
    { key: 'property_id', label: 'Immobilie', type: 'select', clearOnChange: ['unit_id', 'contract_id'],
      options: [empty('— Keine —'), ...properties.map(row => ({ value: row.id, label: row.name }))] },
    { key: 'unit_id', label: 'Einheit', type: 'select', clearOnChange: ['contract_id'],
      options: values => [empty('— Keine —'), ...units.filter(row => !values.property_id || row.property_id === values.property_id)
        .map(row => ({ value: row.id, label: `${row.label}${propertyNames[row.property_id] ? ` · ${propertyNames[row.property_id]}` : ''}` }))] },
    { key: 'contract_id', label: 'Vertrag', type: 'select',
      options: values => [empty('— Kein —'), ...contracts.filter(row =>
        (!values.property_id || row.property_id === values.property_id) && (!values.unit_id || row.unit_id === values.unit_id)
        && (!values.tenant_id || row.tenant_id === values.tenant_id))
        .map(row => ({ value: row.id, label: `${row.contract_number}${tenantNames[row.tenant_id] ? ` · ${tenantNames[row.tenant_id]}` : ''}` }))] },
  ];
}

export function deriveDocumentAssociations(units, contracts) {
  return (values, key) => {
    if (key === 'contract_id') {
      const contract = contracts.find(row => row.id === values.contract_id);
      if (contract) return { property_id: contract.property_id, unit_id: contract.unit_id, tenant_id: contract.tenant_id };
    }
    if (key === 'unit_id') {
      const unit = units.find(row => row.id === values.unit_id);
      if (unit) return { property_id: unit.property_id };
    }
    return {};
  };
}

export function resolveDocumentContext(document, units, contracts) {
  const get = (rows, id) => Array.isArray(rows) ? rows.find(row => row.id === id) : rows[id];
  const contract = get(contracts, document.contract_id);
  const unitId = document.unit_id || contract?.unit_id || null;
  const unit = get(units, unitId);
  return { property_id: document.property_id || unit?.property_id || contract?.property_id || null,
    unit_id: unitId, contract_id: document.contract_id || null, tenant_id: document.tenant_id || contract?.tenant_id || null };
}
