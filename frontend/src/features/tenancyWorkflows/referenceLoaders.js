import { legacyPageLoader, loadDocumentVersionPage } from './tenancyWorkflowApi';

export function propertyReferenceLoader() {
  return legacyPageLoader('/properties');
}

export function unitReferenceLoader({ propertyId }) {
  return legacyPageLoader('/units', { property_id: propertyId });
}

export function contractReferenceLoader({ propertyId }) {
  return legacyPageLoader('/contracts', { property_id: propertyId });
}

export function activeUserReferenceLoader() {
  return legacyPageLoader('/auth/users');
}

export function documentReferenceLoader({ propertyId }) {
  return legacyPageLoader('/documents', { property_id: propertyId });
}

export function handoverReferenceLoader({ unitId }) {
  return legacyPageLoader('/handover-protocols', { unit_id: unitId });
}

export function documentVersionReferenceLoader(documentId, options) {
  return loadDocumentVersionPage(documentId, options);
}

/*
 * Deliberately absent: a canonical global reference-search endpoint and a
 * dedicated immutable meter-reading picker. The current UI keeps every request
 * bounded and can load later legacy pages, but does not call that a finished
 * cross-resource search service. Root owns that remaining P1 integration.
 */
