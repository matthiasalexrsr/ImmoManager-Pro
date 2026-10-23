export function scopeDefaults(params, units = []) {
  const unitId = params.get('unit_id');
  const propertyId = params.get('property_id') || units.find(unit => unit.id === unitId)?.property_id;
  return { ...(propertyId ? { property_id: propertyId } : {}), ...(unitId ? { unit_id: unitId } : {}) };
}
