import { describe, expect, it } from 'vitest';
import { authMayWrite, mayWrite, resourceCapability, RESOURCE_CAPABILITY, writePermissions } from '../utils/writeAccess';

const grants = {
  eigentuemer: ['administration', 'portfolio', 'rental', 'finance', 'billing', 'operations', 'documents', 'marketing', 'communication'],
  verwalter: ['administration', 'portfolio', 'rental', 'finance', 'billing', 'operations', 'documents', 'marketing', 'communication'],
  buchhaltung: ['finance', 'billing', 'documents', 'communication'],
  techniker: ['operations', 'documents', 'communication'], readonly: [],
};

describe('business write capabilities', () => {
  it.each(Object.keys(grants))('matches every routed resource for %s, with authoritative and legacy UserRead shapes', role => {
    for (const [resource, capability] of Object.entries(RESOURCE_CAPABILITY)) {
      const allowed = grants[role].includes(capability);
      expect(mayWrite({ role }, `/${resource}/record/command`), resource).toBe(allowed);
      expect(mayWrite({ role, write_permissions: grants[role] }, `/api/v1/${resource}/record`), resource).toBe(allowed);
      expect(mayWrite({ role }, `/v1/${resource}?limit=100`), resource).toBe(allowed);
    }
    expect(mayWrite({ role }, '/unrecognized/command')).toBe(grants[role].includes('administration'));
  });
  it('uses supplied permissions, including an empty list, before a role fallback', () => {
    expect(writePermissions({ role: 'eigentuemer', write_permissions: [] })).toEqual([]);
    expect(mayWrite({ role: 'eigentuemer', write_permissions: [] }, '/properties')).toBe(false);
    expect(mayWrite({ role: 'eigentuemer', write_permissions: ['documents'] }, '/photos/upload')).toBe(true);
    expect(mayWrite({ role: 'eigentuemer', write_permissions: ['documents'] }, '/billing')).toBe(false);
  });
  it('fails closed without a user or known role and does not infer write access from isReadonly=false', () => {
    for (const user of [null, undefined, {}, { role: 'future-role' }]) expect(mayWrite(user, '/accounts')).toBe(false);
    expect(authMayWrite({ isReadonly: false, isAdmin: true }, '/accounts')).toBe(false);
    expect(authMayWrite(null, '/accounts')).toBe(false);
  });
  it('delegates the contextual contract and classifies nested and query endpoints exactly', () => {
    expect(authMayWrite({ canWrite: endpoint => endpoint === '/meters' }, '/meters')).toBe(true);
    expect(resourceCapability('/api/v1/billing/periods/a/create-receivables')).toBe('billing');
    expect(resourceCapability('/rent-charges/preview')).toBe('finance');
    expect(resourceCapability('/photos/upload?entity_type=unit')).toBe('documents');
    expect(resourceCapability('/updates/restart')).toBe('administration');
    expect(resourceCapability('/auth/users/me/preferences')).toBe('administration'); // Self-account APIs have their own authorization.
  });
});
