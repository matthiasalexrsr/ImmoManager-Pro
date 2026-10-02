import { useMemo } from 'react';
import { workflowText } from './workflowCopy';
import { usePinnedReference } from './workflowReferenceResolution';

export function WorkflowLocationLabel({
  propertyId,
  unitId = null,
  principalKey = '',
  locale = 'de-DE',
  propertyLoader,
  unitLoaderForProperty,
}) {
  const property = usePinnedReference(propertyLoader, propertyId, principalKey);
  const unitLoader = useMemo(
    () => propertyId && unitId && typeof unitLoaderForProperty === 'function'
      ? unitLoaderForProperty(propertyId)
      : null,
    [propertyId, unitId, unitLoaderForProperty],
  );
  const unit = usePinnedReference(unitLoader, unitId, principalKey);
  const tr = (key, params) => workflowText(locale, key, params);

  const propertyName = property === undefined
    ? tr('loading')
    : property?.name || property?.label || tr('propertyUnavailable');
  if (!unitId) return <span className="workflow-location-label">{propertyName}</span>;
  const unitName = unit === undefined
    ? tr('loading')
    : unit?.label || unit?.name || tr('unitUnavailable');

  return <span className="workflow-location-label">{propertyName} · {unitName}</span>;
}
