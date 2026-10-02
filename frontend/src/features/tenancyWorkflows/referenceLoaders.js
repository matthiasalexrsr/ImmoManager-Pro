import { loadDocumentVersionPage, workflowReferenceLoader } from './tenancyWorkflowApi';

export function propertyReferenceLoader() {
  return workflowReferenceLoader('properties');
}

export function unitReferenceLoader({ propertyId }) {
  return workflowReferenceLoader('units', { property_id: propertyId });
}

export function contractReferenceLoader({ propertyId, unitId = null }) {
  return workflowReferenceLoader('contracts', {
    property_id: propertyId,
    unit_id: unitId,
  });
}

export function activeUserReferenceLoader({ propertyId }) {
  return workflowReferenceLoader('users', { property_id: propertyId });
}

export function documentReferenceLoader({
  propertyId,
  unitId = null,
  contractId = null,
  direction = null,
}) {
  return workflowReferenceLoader('documents', {
    property_id: propertyId,
    unit_id: unitId,
    contract_id: contractId,
    direction,
  });
}

export function handoverReferenceLoader({
  propertyId = null,
  unitId,
  contractId = null,
  direction = null,
}) {
  return workflowReferenceLoader('handover-protocols', {
    property_id: propertyId,
    unit_id: unitId,
    contract_id: contractId,
    direction,
  });
}

export function meterReadingReferenceLoader({
  propertyId = null,
  unitId,
  contractId = null,
  direction = null,
}) {
  return workflowReferenceLoader('meter-readings', {
    property_id: propertyId,
    unit_id: unitId,
    contract_id: contractId,
    direction,
  });
}

export function meterReferenceLoader({ propertyId = null, unitId = null }) {
  return workflowReferenceLoader('meters', {
    property_id: propertyId,
    unit_id: unitId,
  });
}

export function documentVersionReferenceLoader(documentId, options) {
  return loadDocumentVersionPage(documentId, options);
}
